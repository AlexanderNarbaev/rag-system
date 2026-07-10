# Knowledge Graph Guide

## 1. Overview

The Knowledge Graph is an optional layer that connects entities (people, projects, technologies, documents) extracted from your corporate data sources — Confluence, Jira, and GitLab — into a structured graph stored in Neo4j.

**Why it matters:**

- **Cross-system linking** — a Git commit can be traced to the Jira issue it resolves and the Confluence page that documents the feature.
- **Multi-hop retrieval** — when a user asks "Who worked on the authentication module?", the graph traverses from the module to related tickets to the people assigned to them.
- **Richer context** — vector search finds textually similar chunks; graph expansion adds structurally related information that may not be textually similar.

> **Status**: The Knowledge Graph is fully implemented but **disabled by default**. Enable it only when Neo4j is available and populated by the ETL pipeline.

---

## 2. Architecture

The knowledge graph spans two layers:

```
┌─────────────────────────────────────────────────────────┐
│  ETL Layer (data ingestion machine)                     │
│                                                         │
│  Extractors ─→ Chunker ─→ EntityExtractor ─→ Neo4jLoader│
│  (Confluence,      │         │                  │       │
│   Jira,            ▼         ▼                  ▼       │
│   GitLab)    Qdrant index  spaCy NER +      Neo4j       │
│                         SLM relations      (graph DB)   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  Proxy Layer (API server)                               │
│                                                         │
│  User Query ─→ hybrid_search(Qdrant) ─→ top-k chunks   │
│                     │                                   │
│                     ▼                                   │
│              graph_expand_query(Neo4j) ─→ expanded ctx   │
│                     │                                   │
│                     ▼                                   │
│              rerank ─→ build_context ─→ LLM generation  │
└─────────────────────────────────────────────────────────┘
```

### 2.1 ETL Side

| Component | File | Role |
|-----------|------|------|
| `EntityRelationExtractor` | `etl/graph_builder/entity_extractor.py` | Extracts entities via spaCy NER; optionally extracts relations via SLM |
| `Neo4jLoader` | `etl/graph_builder/neo4j_loader.py` | Loads entities/relations into Neo4j, manages constraints, indexes, and cleanup |
| Schema | `etl/graph_builder/schema.yaml` | Defines entity types, relation types, extraction rules, and Neo4j config |

### 2.2 Proxy Side

| Component | File | Role |
|-----------|------|------|
| `graph_expand_query()` | `proxy/app/core/retrieval.py` | Expands a user query by finding related entities in Neo4j |
| Config flags | `proxy/app/shared/config.py` | `GRAPH_ENABLED`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `USE_GRAPH_EXPANSION` |

---

## 3. Schema

### 3.1 Entity Types (Nodes)

| Entity Type | Neo4j Labels | Description |
|-------------|-------------|-------------|
| `PERSON` | `:Entity:Person` | Employees, developers, authors, managers |
| `ORGANIZATION` | `:Entity:Organization` | Teams, departments, companies |
| `TECHNOLOGY` | `:Entity:Technology` | Programming languages, frameworks, databases, tools |
| `PRODUCT` | `:Entity:Product` | Products, services, modules, libraries |
| `PROJECT` | `:Entity` | Jira projects, GitLab projects, Confluence spaces |
| `DOCUMENT` | `:Entity:Document` | Confluence pages, articles, general documents |
| `TICKET` | `:Entity:Ticket` | Jira issues (Bug, Task, Story, Epic) |
| `COMMIT` | `:Entity:Commit` | Git commits from GitLab |
| `CODE_FILE` | `:Entity:CodeFile` | Source code files |
| `CONCEPT` | `:Entity:Concept` | Abstract terms, domain vocabulary |
| `LOCATION` | `:Entity:Location` | Geographic locations, offices |

### 3.2 Relation Types (Edges)

| Relation | From | To | Example |
|----------|------|----|---------|
| `WORKS_ON` | PERSON | PROJECT, TICKET | "Ivan works on PROJ-123" |
| `AUTHORED_BY` | DOCUMENT, COMMIT, TICKET | PERSON | "This page was written by Maria" |
| `MENTIONS` | DOCUMENT | PERSON, TECHNOLOGY, PRODUCT, CONCEPT | "The doc mentions PostgreSQL" |
| `DEPENDS_ON` | PROJECT, TICKET, CODE_FILE | PROJECT, PRODUCT, TECHNOLOGY | "Backend depends on Redis" |
| `RELATES_TO` | any | any | General-purpose link with strength score |
| `CONTAINS` | PROJECT, DOCUMENT | CODE_FILE, DOCUMENT, TICKET | "Epic contains sub-tasks" |
| `PARENT_OF` | TICKET, DOCUMENT | TICKET, DOCUMENT | "Epic → Story → Sub-task" |
| `REFERENCES` | DOCUMENT | DOCUMENT | "Confluence page links to another page" |
| `UPDATES` | COMMIT | CODE_FILE, TICKET | "Commit modifies auth.py" |
| `BELONGS_TO` | DOCUMENT, TICKET, CODE_FILE | PROJECT, ORGANIZATION | "File belongs to backend repo" |

Full schema definition: `etl/graph_builder/schema.yaml`

---

## 4. Configuration

### 4.1 Environment Variables

```bash
# ── Proxy (proxy/.env) ──
GRAPH_ENABLED=false              # Enable graph expansion in the proxy
NEO4J_URI=bolt://localhost:7687  # Neo4j Bolt protocol address
NEO4J_USER=neo4j                 # Neo4j username
NEO4J_PASSWORD=                  # REQUIRED if GRAPH_ENABLED=true
USE_GRAPH_EXPANSION=false        # Enable entity-based graph traversal in retrieval

# ── ETL (etl/.env) ──
GRAPH_ENABLED=false              # Enable entity extraction + Neo4j loading
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=
```

### 4.2 When to Enable Each Flag

| Flag | Layer | Purpose |
|------|-------|---------|
| `GRAPH_ENABLED` (ETL) | ETL | Triggers entity extraction during indexing and loads results into Neo4j |
| `GRAPH_ENABLED` (Proxy) | Proxy | Allows the proxy to connect to Neo4j at startup |
| `USE_GRAPH_EXPANSION` | Proxy | Actually runs graph expansion during query retrieval |

**Typical deployment flow:**
1. Set `GRAPH_ENABLED=true` in ETL, run full ETL to populate Neo4j.
2. Set `GRAPH_ENABLED=true` and `USE_GRAPH_EXPANSION=true` in Proxy.
3. Restart the proxy — it connects to Neo4j on startup.

### 4.3 Docker Compose

The `proxy/docker-compose.yml` includes a Neo4j service definition. When you enable the graph:

```yaml
neo4j:
  image: neo4j:5-community
  ports:
    - "7474:7474"   # HTTP browser
    - "7687:7687"   # Bolt protocol
  environment:
    NEO4J_AUTH: neo4j/your-password
  volumes:
    - neo4j_data:/data
```

---

## 5. How It Works

### 5.1 ETL: Entity Extraction During Indexing

When `GRAPH_ENABLED=true` in the ETL config:

1. **Extract** — After text chunks are created, `EntityRelationExtractor` runs spaCy NER on each chunk to find PERSON, ORGANIZATION, TECHNOLOGY, PRODUCT, LOCATION, and CONCEPT entities.
2. **Relate** (optional) — If an SLM endpoint is configured, the extractor sends text + entity list to the SLM to infer relationships between entities.
3. **Load** — `Neo4jLoader` writes entities and relations to Neo4j using MERGE operations (idempotent). It also creates indexes and constraints on first run.
4. **Cleanup** — Outdated entities (from sources no longer in the current ETL batch) are removed.

```python
# Simplified ETL flow
from etl.graph_builder.entity_extractor import EntityRelationExtractor
from etl.graph_builder.neo4j_loader import Neo4jLoader, batch_load_from_extractor

extractor = EntityRelationExtractor(use_spacy=True)
entities, relations = extractor.extract_from_chunk(text="...", source_id="confluence_123")

with Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="...") as loader:
    batch_load_from_extractor(loader, entities_as_dicts, relations_as_dicts)
```

### 5.2 Proxy: Graph Expansion During Query

When `GRAPH_ENABLED=true` and `USE_GRAPH_EXPANSION=true`:

1. User sends a query to `/v1/chat/completions`.
2. `hybrid_search()` retrieves top-k chunks from Qdrant (dense + sparse RRF fusion).
3. `graph_expand_query()` extracts keywords from the query and searches Neo4j for matching entities and their 1-hop neighbors.
4. The graph context (entity names, types, and related entities) is appended to the LLM prompt alongside the vector-retrieved chunks.

```python
# In proxy/app/core/retrieval.py
def graph_expand_query(query: str, max_entities: int = 5) -> str:
    if not _GRAPH_ENABLED or not neo4j_driver:
        return ""  # graceful degradation — returns empty string

    keywords = [w for w in query.split() if len(w) > 3][:3]
    # Cypher: find entities matching keywords, return with related entities
    ...
```

### 5.3 Cross-System Linking

The graph's primary value is connecting information across systems:

```
Git commit abc123
  ──UPDATES──→ auth.py (CODE_FILE)
  ──MENTIONS──→ PROJ-456 (TICKET)
                ──REFERENCES──→ "Authentication Architecture" (Confluence DOCUMENT)
                ──AUTHORED_BY──→ Ivan Ivanov (PERSON)
                                  ──WORKS_ON──→ Backend Team (ORGANIZATION)
```

A user asking "Who maintains the authentication module?" gets a graph-enriched answer that connects code, tickets, documentation, and people — even though no single document contains all of this information.

---

## 6. Adding Custom Entity Types

### 6.1 Edit the Schema

Add a new entity type to `etl/graph_builder/schema.yaml`:

```yaml
entity_types:
  - name: "SERVICE"
    label: "Service"
    description: "Microservice or API endpoint"
    properties:
      - name: "name"
        type: "string"
        required: true
      - name: "endpoint"
        type: "string"
      - name: "team_owner"
        type: "string"
```

### 6.2 Add spaCy Mapping

In `entity_extractor.py`, update the `type_map` dictionary in `extract_entities_spacy()`:

```python
type_map = {
    "PERSON": "PERSON",
    "ORG": "ORGANIZATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "PRODUCT": "PRODUCT",
    "EVENT": "EVENT",
    "WORK_OF_ART": "PRODUCT",
    # Add your custom mapping:
    "FAC": "SERVICE",  # spaCy FAC label → SERVICE
}
```

### 6.3 Add Neo4j Constraint

In `neo4j_loader.py`, add the constraint in `create_constraints_and_indexes()`:

```python
constraints = [
    ...
    "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Service) REQUIRE s.id IS UNIQUE",
]
```

### 6.4 Add SLM Extraction Rule

In `schema.yaml`, add extraction rules for the SLM:

```yaml
extraction_rules:
  entity_patterns:
    SERVICE:
      - keywords: ["auth-service", "user-api", "payment-gateway"]
      - pattern: "[a-z]+-service"
```

---

## 7. Troubleshooting

### 7.1 Neo4j Connection Fails at Proxy Startup

**Symptom**: Log shows `Neo4j connection failed: ... Graph expansion disabled.`

**Causes**:
- Neo4j is not running — check `docker ps` or `systemctl status neo4j`.
- Wrong URI/port — verify `NEO4J_URI` matches your Neo4j instance.
- Wrong credentials — verify `NEO4J_USER` and `NEO4J_PASSWORD`.

**Behavior**: The proxy degrades gracefully. Graph expansion is silently disabled; all other features work normally.

### 7.2 Entity Extractor Finds No Entities

**Symptom**: ETL runs but Neo4j is empty.

**Causes**:
- spaCy model not installed — run `python -m spacy download ru_core_news_sm` (or `en_core_web_sm` for English).
- `GRAPH_ENABLED=false` in ETL config.
- Text chunks are too short or contain no named entities.

**Check**: Run the extractor standalone:
```bash
python -c "
from etl.graph_builder.entity_extractor import EntityRelationExtractor
ext = EntityRelationExtractor(use_spacy=True)
ents, rels = ext.extract_from_chunk('Ivan Ivanov works on PROJ-123 using PostgreSQL', 'test')
for e in ents: print(e.name, e.type)
"
```

### 7.3 Graph Expansion Returns Empty String

**Symptom**: `graph_expand_query()` returns `""`.

**Causes**:
- `GRAPH_ENABLED=false` or `USE_GRAPH_EXPANSION=false` in proxy config.
- Neo4j driver failed to initialize (connection error at startup).
- No entities match the query keywords (query words are ≤ 3 chars, or no matching entities in graph).

### 7.4 Slow Graph Queries

**Symptom**: Proxy latency increases significantly when graph is enabled.

**Causes**:
- Missing indexes — run `Neo4jLoader.create_constraints_and_indexes()` or check that `Entity.name` and `Entity.type` indexes exist.
- Large graph without bounds — the `max_entities` parameter in `graph_expand_query()` limits results.

### 7.5 Import Error: `neo4j` Package Not Installed

**Symptom**: `ImportError: neo4j driver is required`.

**Fix**: `pip install neo4j` (ETL) or it's included in `requirements_proxy.txt` (Proxy).

---

## References

- [Knowledge Graph Strategy (deep dive)](knowledge-graph-strategy.md) — detailed design for multi-hop traversal, path scoring, temporal awareness, and self-enrichment
- Schema definition: `etl/graph_builder/schema.yaml`
- Entity extractor: `etl/graph_builder/entity_extractor.py`
- Neo4j loader: `etl/graph_builder/neo4j_loader.py`
- Proxy retrieval: `proxy/app/core/retrieval.py`
