# Block C. Knowledge Graph — Neo4j (FR-19 — FR-25)

---

## FR-19. Entity extraction (spaCy NER + SLM)

**Description:**
The ETL pipeline extracts entities from documents using spaCy NER and optional
SLM augmentation. 10 entity types are supported: Person, Organization, Project,
Technology, API, Service, Team, Location, Document, Event. And 9 relationship types:
uses, belongs_to, depends_on, documents, owns, created_by, related_to, manages, hosts.

**Acceptance criteria:**

1. After an ETL run, Neo4j contains nodes with types from the list above
2. Neo4j contains relationships with types from the list above
3. Each entity has properties: name, type, source_doc, created_at

**Status:** ✅ Confirmed (with mock Neo4j)
**Priority:** HIGH (opt-in)
**Reference:** ADR-006, knowledge-graph-strategy

---

## FR-20. Batch loading into Neo4j (UNWIND)

**Description:**
Entities are loaded into Neo4j in batches via UNWIND queries. Parameters:
`batch_size=500`, `max_retries=3`, `retry_delay=1s`. Duplicates are handled
via MERGE (create if absent, update if present).

**Acceptance criteria:**

1. 1000 entities are loaded in ≤ 5 seconds
2. Reloading the same entities does not create duplicates
3. On a Neo4j error — retry up to 3 times with exponential backoff

**Status:** ✅ Confirmed (with mock Neo4j)
**Priority:** HIGH (opt-in)
**Reference:** knowledge-graph-strategy 1.4

---

## FR-21. Multi-hop graph traversal

**Description:**
During search, the system can expand the context by traversing the knowledge graph:

- 1-hop: neighboring entities of the found chunk
- 2-hop: neighbors of neighbors
- N-hop: with depth limiting and centrality scoring (PageRank)

Graph traversal results are added to the LLM context.

**Acceptance criteria:**

1. A query related to an entity in the graph — returns expanded context
2. Results contain entities from 2+ hops
3. When Neo4j is unavailable — graph expansion is skipped (no 5xx)

**Status:** ✅ Confirmed (with mock Neo4j)
**Priority:** HIGH (opt-in)
**Reference:** ADR-006

---

## FR-22. Global Search / Multi-Hop Reasoning / Text-to-Cypher

**Description:**
Three modes of working with the graph:

- **Global Search** — search over community summaries (entity clusters)
- **Multi-Hop Reasoning** — a reasoning chain through multiple entities
- **Text-to-Cypher** — the LLM generates a Cypher query from a natural-language question

**Acceptance criteria:**

1. Global Search — returns a summary for a cluster
2. Multi-Hop — returns a chain of relationships between entities
3. Text-to-Cypher — the LLM generates valid Cypher, Neo4j executes it

**Status:** ✅ Confirmed (with mock Neo4j)
**Priority:** HIGH (opt-in)
**Reference:** roadmap Phase 3

---

## FR-23. Community Detection

**Description:**
The system detects clusters (communities) in the knowledge graph using community
detection algorithms (Louvain/Label Propagation). Community summaries are used
for Global Search mode.

**Acceptance criteria:**

1. After ETL, the graph contains community nodes with summaries
2. Global Search over communities returns aggregated context

**Status:** ✅ Confirmed (with mock Neo4j)
**Priority:** HIGH (opt-in)
**Reference:** roadmap Phase 3

---

## FR-24. Graceful degradation when Neo4j is unavailable

**Description:**
If Neo4j is unavailable, the system does NOT crash. Graph expansion is skipped, and
search works only through Qdrant. A warning is logged. The response HTTP code is
200 (not 503).

**Acceptance criteria:**

1. With Neo4j stopped — the request is processed successfully (without graph expansion)
2. Log contains: "Neo4j unavailable — skipping graph expansion"
3. Response HTTP code — 200

**Status:** ✅ Confirmed (with mock Neo4j)
**Priority:** CRITICAL
**Reference:** AGENTS.md, ADR-011

---

## FR-25. Graph schema versioning (90-day retention)

**Description:**
Entities and relationships in the graph have an `updated_at` timestamp. A scheduled
task (every 24 hours) deletes entities older than 90 days that have not been updated.

**Acceptance criteria:**

1. An entity with `updated_at` > 90 days ago — is deleted
2. An entity with a recent `updated_at` — is kept
3. The task runs on a schedule (cron)

**Status:** ✅ Confirmed
**Priority:** MEDIUM
**Reference:** knowledge-graph-strategy 1.4
