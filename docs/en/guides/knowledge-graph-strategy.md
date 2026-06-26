# Knowledge Graph Enrichment & Context Unrolling

## 1. Current Graph Architecture

### 1.1 Entity Types & Schema

The knowledge graph models 10 entity types covering the corporate domain, defined in `etl/graph_builder/schema.yaml:9-158`:

| Entity Type | Neo4j Label | Properties | Source Mapping |
|---|---|---|---|
| PERSON | `:Entity:Person` | full_name, username, email, role, department | confluence.author, jira.assignee/reporter, gitlab.author |
| PROJECT | `:Entity` | key, name, url, source_system (jira/gitlab/confluence) | Jira project key, GitLab project ID, Confluence space key |
| DOCUMENT | `:Entity:Document` | id, title, url, source_type, version, updated_at | All source pages/issues/commits |
| TICKET | `:Entity:Ticket` | key, status, priority, issue_type (Bug/Task/Story/Epic) | Jira sub-type of DOCUMENT |
| COMMIT | `:Entity:Commit` | sha, message, author, date | GitLab sub-type of DOCUMENT |
| CODE_FILE | `:Entity:CodeFile` | path, language, repository | GitLab files |
| ORGANIZATION | `:Entity:Organization` | name, type (team/department/company), parent | Cross-source |
| TECHNOLOGY | `:Entity:Technology` | name, category, version | All sources (keyword matching) |
| PRODUCT | `:Entity:Product` | name, status (active/deprecated/planning), owner | All sources |
| CONCEPT | `:Entity:Concept` | name, definition | All sources |
| LOCATION | `:Entity:Location` | name, country, city | All sources |

### 1.2 Relation Types

Nine relation types defined in `schema.yaml:161-251`:

- **WORKS_ON** — PERSON → PROJECT/TICKET (role, since date)
- **AUTHORED_BY** — DOCUMENT/COMMIT/TICKET/CODE_FILE → PERSON (date)
- **MENTIONS** — DOCUMENT → PERSON/TECHNOLOGY/PRODUCT/PROJECT/CONCEPT (context, count)
- **DEPENDS_ON** — PROJECT/TICKET/CODE_FILE → PROJECT/PRODUCT/TECHNOLOGY (type: build/runtime/optional)
- **RELATES_TO** — any → any (strength 0..1, evidence)
- **CONTAINS** — PROJECT/DOCUMENT → CODE_FILE/DOCUMENT/TICKET
- **PARENT_OF** — TICKET/DOCUMENT → TICKET/DOCUMENT (epic→task, folder→page)
- **REFERENCES** — DOCUMENT → DOCUMENT (url, type: internal/external)
- **UPDATES** — COMMIT → CODE_FILE/TICKET (lines_added, lines_deleted)
- **BELONGS_TO** — DOCUMENT/TICKET/CODE_FILE → PROJECT/ORGANIZATION

### 1.3 Entity Extraction Pipeline

Implemented in `etl/graph_builder/entity_extractor.py:51-277`:

1. **spaCy NER** (`extract_entities_spacy`, line 117) — extracts PERSON, ORG, GPE, PRODUCT, EVENT from text chunks. Maps spaCy labels to internal types. Uses `ru_core_news_sm` by default.
2. **SLM augmentation** (`extract_relations_slm`, line 149) — sends text + entity list to a local SLM to infer relations. Prompt structured for JSON-only output. Results cached by SHA-256 of text.
3. **Deduplication** (`extract_batch`, line 248) — merges duplicate entities by ID and duplicate relations by (source, target, type)` tuple.

### 1.4 Graph Loading & Constraints

Neo4jLoader (`etl/graph_builder/neo4j_loader.py:26-352`):

- **Constraints**: Unique constraints on `Entity.id`, `Person.id`, `Organization.id`, `Technology.id`, `Product.id`, `Location.id` (line 101-107)
- **Indexes**: On `Entity.name`, `Entity.source_id`, `Entity.type`, and `RELATES_TO.type` (line 108-113)
- **Batch loading**: UNWIND-based operations with configurable `batch_size=500` and `max_retries=3` (lines 121-212)
- **State cleanup**: `delete_outdated_entities` by source_id (line 214) and `delete_outdated_relations` by `max_age_days=30` (line 239)
- **Versioning**: `updated_at` timestamp on all nodes/edges, 90-day retention (schema.yaml:298-302)

---

## 2. Multi-Hop Knowledge Unrolling

### 2.1 Retrieval-to-Graph Pipeline

The core idea: vector search returns document chunks → extract entities from chunks → traverse graph → return enriched context.

```
Query → hybrid_search(Qdrant) → top-k chunks → NER on chunk text
  → find entities in Neo4j → traverse 1/2/N-hop paths → score paths → return graph context
```

### 2.2 Traversal Strategies

**1-hop: Direct relations** — Fastest, used when query intent is specific:
```cypher
MATCH (e:Entity {name: $entity})-[:WORKS_ON|AUTHORED_BY|MENTIONS|BELONGS_TO]->(related)
RETURN related.name, labels(related), type(r)
```
Covers: person→team, ticket→project, document→author, commit→file.

**2-hop: Indirect connections** — Uncovers latent links:
```cypher
MATCH (e:Entity {name: $entity})-[r1]->(mid)-[r2]->(target)
WHERE target <> e
RETURN e.name, type(r1), mid.name, type(r2), target.name
```
Examples: person→team→project, Jira issue→references→Confluence page, MR→updates→file→belongs_to→repo.

**N-hop with centrality scoring** — For exploratory questions:
```cypher
CALL gds.pageRank.stream('entity-graph') YIELD nodeId, score
MATCH (n) WHERE id(n) = nodeId AND score > 0.01
WITH n, score ORDER BY score DESC LIMIT 20
MATCH path = shortestPath((start)-[*1..3]-(n))
RETURN path, score
```
Use Neo4j GDS library PageRank and Betweenness centrality. Filter paths by `score > 0.01` to suppress noise.

### 2.3 Path Scoring & Ranking

```
path_score = Σ(node_centrality × 0.3) + Σ(relation_strength × 0.5) + log(1 + mentions_count) × 0.2
```

- **node_centrality**: PageRank score (0..1)
- **relation_strength**: from `RELATES_TO.strength` property (0..1)
- **mentions_count**: from `MENTIONS.count` property

Filter threshold: `path_score > 0.15`. Rank by score descending, limit to top-10 paths.

---

## 3. Graph-Enhanced Retrieval

### 3.1 Current Implementation

`graph_expand_query()` in `proxy/app/retrieval.py:180-216`: Baseline implementation using simple keyword matching:
- Splits query into words > 3 chars
- Runs CONTAINS match on `Entity.name`
- Returns 1-hop neighbors as text lines

**Limitations**: No entity recognition, no multi-hop, no scoring, no token budget management.

### 3.2 Proposed Improvements

**Subgraph extraction around retrieved entities**: After vector search, extract entity names from the top-10 retrieved chunks using spaCy NER, then fetch the induced subgraph from Neo4j:

```cypher
MATCH (e:Entity) WHERE e.name IN $entity_names
MATCH (e)-[r*1..2]-(related:Entity)
RETURN e, r, related
```

**Relationship-aware context enrichment**: Instead of flat text lists, format graph results as structured markup:

```
[GRAPH_CONTEXT]
Entity: PROJ-123 (TICKET) — status: In Progress, priority: High
  AUTHORED_BY → Иван Иванов (role: backend developer)
  PARENT_OF → PROJ-456 (sub-task)
  DEPENDS_ON → PostgreSQL 15 (runtime dependency)
  MENTIONS → CI/CD Pipeline (count: 3)
[/GRAPH_CONTEXT]
```

**Graph attention for relevance scoring**: Score graph entities using a weighted combination of vector similarity (from Qdrant), graph centrality (PageRank), and relation type relevance to the query domain. Weighted fusion:
```
final_score = 0.4 × vector_score + 0.3 × centrality + 0.3 × relation_relevance
```

### 3.3 Integration with Orchestrator

In the LangGraph pipeline (`orchestrator.py:212-251`), graph expansion runs between `rerank` and `build_context`:

```
rewrite → retrieve → check_sufficiency → rerank → graph_expand → build_context → generate
```

When `check_sufficiency` detects low confidence (`avg_score < 0.6`), the pipeline loops back to `rewrite`. If confidence is marginal (0.6–0.75), graph expansion is triggered as a supplement without a full rewrite loop.

---

## 4. Cross-Source Entity Resolution

### 4.1 Identity Resolution Rules

**Author matching** (Jira ↔ GitLab ↔ Confluence):
- Canonical key: `email` (highest confidence), `username` (medium), `full_name` (low, requires fuzzy match)
- Fuzzy matching threshold: Levenshtein distance ≤ 2 for names
- Resolution: `MERGE` on email, then optionally merge name-only matches with `similarity_score > 0.9`

**Issue–document linking** (PROJ-123 ↔ related Confluence page):
- Pattern-based: Extract Jira issue keys (`[A-Z]{2,}-\d+`) from Confluence page content and comments
- Explicit links: Parse Confluence macro `{jira:PROJ-123}`
- Backlink resolution: Jira issue "mentioned in" field → Confluence page URL

**Merge request → resolved issue → updated documentation chain**:
```
COMMIT (sha) → UPDATES → CODE_FILE
COMMIT (sha) → MENTIONS (PROJ-123) → TICKET → REFERENCES → DOCUMENT (Confluence)
```

### 4.2 Canonical Entity Store

Propose a `canonical_id` property on all entities. Resolution pipeline:
1. Group entities by email/username (strict match)
2. Within each group, select the entity with the most properties as canonical
3. Set `canonical_id` on duplicates pointing to the canonical entity
4. Run weekly to merge newly discovered identities

---

## 5. Temporal Awareness

### 5.1 Version Evolution Tracking

Every node and relation carries `updated_at` (datetime) and `source_version` (string). On ETL re-index:
- New version: insert with new `source_version`, keep old node with `deprecated: true`
- Chain versions: `PREVIOUS_VERSION` relation between document versions

### 5.2 "As of Date X" Queries

Filter graph traversal by temporal constraint:
```cypher
MATCH (e:Entity)-[r:RELATES_TO]->(related)
WHERE r.updated_at <= datetime($target_date)
  AND (r.deprecated IS NULL OR r.deprecated > datetime($target_date))
RETURN e, r, related
```

### 5.3 Stale Relation Cleanup

`Neo4jLoader.delete_outdated_relations(max_age_days=30)` removes relations untouched for 30+ days. Run as a daily cron alongside incremental ETL.

---

## 6. Self-Enriching Knowledge Base

### 6.1 Automatic Discovery of Missing Links

- **Co-occurrence mining**: Entities frequently appearing in the same chunks but lacking a relation → suggest `RELATES_TO` with weak `strength=0.3` and `evidence="co-occurrence"`
- **Pattern-based inference**: "X depends on Y" text pattern → create `DEPENDS_ON` relation
- **Transitive closure**: If A→B→C exists and A→C is missing and path score > 0.5, suggest A→C

### 6.2 Periodic Graph Analytics

Run weekly (scheduled in ETL scheduler):
- **Community detection** (Louvain algorithm via GDS): Identify document/ticket clusters by project domain
- **Centrality recalculation**: Update PageRank scores stored as `pagerank` property on all Entity nodes
- **Orphan detection**: Entities with degree 0 — flag for HITL review or auto-prune after 90 days

### 6.3 HITL Feedback Loop

From `hitl_dashboard/`:
- Expert marks suggested relation as "confirmed" → set `strength=1.0`, `evidence="hitl_verified"`
- Expert marks as "incorrect" → set `deprecated=true` with `deprecated_reason`
- Feedback integrated via `proxy/app/hitl.py` hooks, written back to Neo4j on next ETL cycle

---

## 7. Context Assembly with Graph Data

### 7.1 Format for LLM Prompt Injection

Graph context appended to vector context with clear delimiters:

```
=== DOCUMENT CONTEXT ===
[chunk 1] ... (score: 0.89)
[chunk 2] ... (score: 0.82)

=== KNOWLEDGE GRAPH ===
Entity: Иван Иванов (PERSON)
  WORKS_ON → PROJ-123 (since 2025-01)
  AUTHORED_BY → Confluence: Architecture Overview (2025-03-15)

Entity: PROJ-123 (TICKET) — status: In Progress
  DEPENDS_ON → PostgreSQL 15
  REFERENCES → GitLab: backend/schema.sql
```

### 7.2 Token Budget Allocation

With the configured LLM's context window:

| Component | Tokens | Percentage |
|---|---|---|
| System prompt | ~500 | <1% |
| User query | ~200 | <1% |
| Vector-retrieved chunks (top-10) | ~90,000 | 69% |
| Graph context | ~30,000 | 23% |
| Generation reserve (output) | ~9,300 | 7% |

**Rule**: Graph context capped at `min(30,000 tokens, 25% of remaining budget)`. When vector context already consumes >100K tokens, graph context is truncated to top-5 entities with 1-hop relations only.

### 7.3 Entity-Relationship Summary Format

For queries with many graph hits, compress to summary table:

```
| Entity | Type | Relations |
|---|---|---|
| PROJ-123 | TICKET | depends on: PostgreSQL 15, Redis; worked on by: Иван Иванов |
| Architecture Overview | DOCUMENT | references: PROJ-123; authored by: Иван Иванов |
```

This compresses ~2,000 tokens of graph text into ~200 tokens while preserving relationship semantics.

---

## 8. CRAG Decomposition (v0.5)

### 8.1 Corrective RAG Overview

CRAG (Corrective Retrieval-Augmented Generation) decomposition splits complex queries into sub-queries, retrieves answers for each, then synthesizes a final response. This is enabled via `CRAG_DECOMPOSITION_ENABLED=true`.

**Pipeline:**
1. **Decompose** — SLM splits query into atomic sub-questions
2. **Retrieve** — Each sub-question retrieves independently from Qdrant + Neo4j
3. **Evaluate** — Confidence scorer checks each sub-answer for grounding
4. **Correct** — Low-confidence sub-answers trigger re-retrieval with modified queries
5. **Synthesize** — LLM combines verified sub-answers into coherent response

### 8.2 Query Decomposition Strategies

| Strategy | Trigger | Example |
|----------|---------|---------|
| **Comparison** | Queries with "vs", "compare", "difference" | "How does X differ from Y?" → [X details, Y details, diff] |
| **Temporal** | "before/after", "from X to Y" | "How did X evolve?" → [v1.0 X, v2.0 X, changes] |
| **Composite** | Multiple entities or joins | "What is X and how does it relate to Y?" → [explain X, explain Y, relationship] |
| **Multi-hop** | Requires reasoning chain | "Who wrote the doc that describes X?" → [find doc, find author] |

### 8.3 Verification & Self-Correction

Each sub-answer goes through:
- **NLI Grounding**: Check if answer claims are supported by retrieved context
- **Confidence threshold**: Sub-answers below `CONFIDENCE_THRESHOLD` are re-retrieved
- **Loop limit**: `MAX_VERIFY_LOOPS=2` prevents infinite correction cycles

### 8.4 Configuration

```bash
# In proxy/.env
CRAG_DECOMPOSITION_ENABLED=true
NLI_MODEL_ENABLED=false          # Set true for NLI-based verification
CONFIDENCE_THRESHOLD=0.5
MAX_VERIFY_LOOPS=2
SELF_CRITIQUE_ENABLED=true
```
