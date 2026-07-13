# Sprint Plan — S3 2026 (Updated)

**Sprint Duration:** 2 weeks (2026-07-14 → 2026-07-25)
**Sprint ID:** S3-2026-UPDATED
**Status:** 🟡 In Progress
**Updated:** 2026-07-13

---

## Sprint Goal

Complete high-impact research items, wire remaining Phase 3 evaluation infrastructure, and address key quality gaps from the project checklist.

---

## Prioritization Matrix

All open items ranked by **Impact ÷ Effort** (highest first):

| Rank | Item | Source | Effort | Priority | Impact/Effort |
|------|------|--------|--------|----------|---------------|
| 1 | Self-critique verification loop | Research | LOW | 🔴 HIGH | ⭐⭐⭐⭐⭐ |
| 2 | CRAG evaluator wiring | Research | LOW | 🔴 HIGH | ⭐⭐⭐⭐⭐ |
| 3 | Embedding cache | Research | LOW | 🟡 MED | ⭐⭐⭐⭐ |
| 4 | Text-to-Cypher for Neo4j | Research | LOW | 🟡 MED | ⭐⭐⭐⭐ |
| 5 | Adaptive query routing | Research | MED | 🔴 HIGH | ⭐⭐⭐ |
| 6 | Mypy strict mode | Checklist #5 | MED | 🟡 MED | ⭐⭐⭐ |
| 7 | Retrieval evaluation dataset | Checklist #4 | HIGH | 🟡 MED | ⭐⭐ |
| 8 | Global Search Mode (GraphRAG) | Phase 3 #2 | MED | 🟡 MED | ⭐⭐ |
| 9 | Multi-Hop Reasoning | Phase 3 #3 | MED | 🟡 MED | ⭐⭐ |
| 10 | Quarterly RAG maturity review | Checklist #17 | LOW | 🟢 LOW | ⭐⭐ |
| 11 | HTTPS/TLS automation | Checklist #6 | MED | 🟢 LOW | ⭐ |
| 12 | Secrets rotation automation | Checklist #7 | MED | 🟢 LOW | ⭐ |
| 13 | Database migration framework | Checklist #8 | MED | 🟢 LOW | ⭐ |

---

## Sprint Backlog

### Wave 1 — Quick Wins (Days 1–3)

> **Theme:** Wire existing components, immediate quality gains
> **Parallel tracks:** 3 independent workstreams

| ID | Task | Source | Assignee | SP | Dependencies |
|----|------|--------|----------|-----|--------------|
| RQ-01 | Wire self-critique verification loop | Research #2 | Developer | 3 | None |
| RQ-02 | Wire CRAG evaluator into orchestrator | Research #3 | Developer | 3 | None |
| RQ-03 | Add embedding cache layer | Research #4 | Developer | 2 | None |
| RQ-04 | Implement Text-to-Cypher for Neo4j | Research #5 | Developer | 3 | None |
| DOC-01 | Update architecture.md with new wiring | — | Architect | 1 | RQ-01, RQ-02 |

**Wave 1 Total:** 12 SP

#### RQ-01: Self-Critique Verification Loop

**Objective:** Wire existing `hallucination.py` and `confidence.py` modules into a post-generation critique step.

**Inputs:**
- `proxy/app/core/hallucination.py` (existing)
- `proxy/app/core/confidence.py` (existing)
- `proxy/app/core/orchestrator/graph.py` (existing)

**Outputs:**
- New `verify_answer` node in LangGraph orchestrator
- Configuration flag `SELF_CRITIQUE_ENABLED`
- Unit tests for verification node

**Verification:**
```bash
python -m pytest tests/proxy/test_orchestrator.py -k "self_critique" -v
make lint && make typecheck
```

**Acceptance Criteria:**
- [ ] `verify_answer` node added to LangGraph graph
- [ ] Low-confidence answers trigger re-generation with expanded context
- [ ] Self-critique score logged in response metadata
- [ ] Feature disabled by default (opt-in via config)
- [ ] Unit tests pass with ≥90% branch coverage

**Rollback:** Remove `verify_answer` node from graph, disable feature flag.

---

#### RQ-02: CRAG Evaluator Wiring

**Objective:** Connect `retrieval_evaluator.py` to orchestrator routing decisions.

**Inputs:**
- `proxy/app/core/retrieval_evaluator.py` (existing)
- `proxy/app/core/orchestrator/nodes.py` (existing)

**Outputs:**
- CRAG evaluation integrated into `retrieve` node
- Action routing: USE / REWRITE / EXPAND / FALLBACK
- Telemetry metrics for CRAG actions

**Verification:**
```bash
python -m pytest tests/proxy/test_retrieval_evaluator.py -v
python -m pytest tests/proxy/test_orchestrator.py -k "crag" -v
```

**Acceptance Criteria:**
- [ ] CRAG evaluator runs after retrieval, before generation
- [ ] Action routing works: USE (pass-through), REWRITE (query rewrite), EXPAND (more chunks), FALLBACK (live sources)
- [ ] Prometheus counter `rag_crag_actions_total{action}` increments
- [ ] Feature gated behind `CRAG_EVALUATOR_ENABLED` flag
- [ ] Integration test covers all 4 action paths

**Rollback:** Bypass evaluator node, route directly to generate.

---

#### RQ-03: Embedding Cache

**Objective:** Add in-memory LRU cache for embedding computations to reduce embedder calls.

**Inputs:**
- `proxy/app/shared/cache.py` (existing)
- `proxy/app/core/retrieval.py` (existing)

**Outputs:**
- `EmbeddingCache` class with LRU eviction
- Cache hit/miss Prometheus metrics
- Configuration: `EMBEDDING_CACHE_SIZE`, `EMBEDDING_CACHE_TTL`

**Verification:**
```bash
python -m pytest tests/proxy/test_cache.py -k "embedding" -v
make benchmark  # Verify latency improvement
```

**Acceptance Criteria:**
- [ ] Repeated identical queries skip embedder call
- [ ] Cache hit ratio > 40% after warm-up period
- [ ] Memory bounded (configurable max entries, default 10000)
- [ ] TTL-based expiration (default 1 hour)
- [ ] Prometheus gauge `rag_embedding_cache_size` and counter `rag_embedding_cache_hits_total`

**Rollback:** Disable cache, pass through to embedder directly.

---

#### RQ-04: Text-to-Cypher for Neo4j

**Objective:** Enable natural language to Cypher query translation using SLM for graph queries.

**Inputs:**
- `proxy/app/core/retrieval.py` (existing graph expansion)
- `proxy/app/llm/slm.py` (existing SLM router)
- `etl/graph_builder/schema.yaml` (graph schema)

**Outputs:**
- `text_to_cypher()` function in retrieval module
- Cypher query validation and sanitization
- SLM prompt template for Cypher generation

**Verification:**
```bash
python -m pytest tests/proxy/test_retrieval.py -k "cypher" -v
```

**Acceptance Criteria:**
- [ ] SLM generates valid Cypher from natural language queries
- [ ] Generated queries validated against schema before execution
- [ ] Query timeout protection (max 5s)
- [ ] Read-only queries enforced (no WRITE/DELETE/CREATE)
- [ ] Fallback to existing graph expansion on failure
- [ ] Unit tests cover 10+ query patterns

**Rollback:** Disable `TEXT_TO_CYPHER_ENABLED`, use existing entity-based expansion.

---

### Wave 2 — Quality Infrastructure (Days 4–7)

> **Theme:** Evaluation datasets, type safety, query routing
> **Parallel tracks:** 2 workstreams (dev + quality)

| ID | Task | Source | Assignee | SP | Dependencies |
|----|------|--------|----------|-----|--------------|
| RQ-05 | Adaptive query routing with SLM | Research #1 | Developer | 5 | RQ-02 |
| EVAL-01 | Build retrieval evaluation dataset (200+ pairs) | Checklist #4 | Analyst | 8 | None |
| QUAL-01 | Fix mypy strict mode errors | Checklist #5 | Developer | 5 | None |
| DOC-02 | Document new features in guides | — | Architect | 2 | RQ-01–RQ-05 |

**Wave 2 Total:** 20 SP

#### RQ-05: Adaptive Query Routing

**Objective:** Use SLM to classify query intent and route to optimal retrieval strategy.

**Inputs:**
- `proxy/app/llm/slm.py` (existing)
- `proxy/app/core/retrieval.py` (existing)
- `proxy/app/core/query_enhancer.py` (existing)

**Outputs:**
- Query intent classifier (factual, analytical, comparative, exploratory)
- Strategy mapping: intent → retrieval params (top-k, rerank weight, graph depth)
- Routing decision logged for analysis

**Verification:**
```bash
python -m pytest tests/proxy/test_slm.py -k "routing" -v
python -m pytest tests/proxy/test_retrieval.py -k "adaptive" -v
```

**Acceptance Criteria:**
- [ ] SLM classifies queries into 4+ intent categories
- [ ] Each intent maps to distinct retrieval parameters
- [ ] Routing decision logged with `rag_query_intent` field
- [ ] Latency overhead < 50ms (SLM classification only)
- [ ] A/B testable via `ADAPTIVE_ROUTING_ENABLED` flag
- [ ] Accuracy > 85% on labeled test set

**Rollback:** Disable adaptive routing, use fixed retrieval parameters.

---

#### EVAL-01: Retrieval Evaluation Dataset

**Objective:** Build 200+ labeled query–document pairs for automated quality regression testing.

**Inputs:**
- HITL feedback logs (`/v1/feedback` data)
- Expert annotations
- Existing Qdrant collection contents

**Outputs:**
- `eval/retrieval_eval_dataset.jsonl` — labeled pairs
- `scripts/eval_retrieval.py` — evaluation script
- CI integration: regression test fails if MRR < 0.75

**Verification:**
```bash
python scripts/eval_retrieval.py --dataset eval/retrieval_eval_dataset.jsonl
# Expected: MRR ≥ 0.75, Recall@20 ≥ 0.85, nDCG@10 ≥ 0.80
```

**Acceptance Criteria:**
- [ ] ≥ 200 labeled query–document pairs
- [ ] Coverage: all 4 intent categories represented
- [ ] Evaluation script computes MRR, Recall@k, nDCG@k, Precision@k
- [ ] CI job fails on quality regression (MRR < 0.75)
- [ ] Dataset versioned and stored in `eval/` directory
- [ ] Documentation on how to add new labeled pairs

**Rollback:** Remove CI gate, keep dataset for manual evaluation.

---

#### QUAL-01: Mypy Strict Mode

**Objective:** Fix all mypy strict mode errors to improve type safety.

**Inputs:**
- `pyproject.toml` mypy configuration
- All `proxy/app/**/*.py` files

**Outputs:**
- `mypy --strict` passes with 0 errors
- Type annotations added to all public functions
- `make typecheck` uses strict mode

**Verification:**
```bash
make typecheck  # Should pass with 0 errors
```

**Acceptance Criteria:**
- [ ] `mypy --strict proxy/` exits with code 0
- [ ] All public functions have type annotations
- [ ] No `Any` types except where unavoidable (external APIs)
- [ ] CI pipeline runs mypy in strict mode
- [ ] Existing tests still pass after changes

**Rollback:** Revert to non-strict mypy config.

---

### Wave 3 — GraphRAG Enhancements (Days 8–10)

> **Theme:** Advanced graph features and process improvements
> **Parallel tracks:** 2 workstreams

| ID | Task | Source | Assignee | SP | Dependencies |
|----|------|--------|----------|-----|--------------|
| GRPH-01 | Global Search Mode (community summaries) | Phase 3 #2 | Developer | 5 | None |
| GRPH-02 | Multi-Hop Reasoning enhancement | Phase 3 #3 | Developer | 5 | GRPH-01 |
| PROC-01 | Quarterly RAG maturity review cadence | Checklist #17 | PM | 1 | None |
| DOC-03 | Update roadmap and checklist | — | Architect | 1 | All |

**Wave 3 Total:** 12 SP

#### GRPH-01: Global Search Mode

**Objective:** Implement GraphRAG community summaries for broad topical queries.

**Inputs:**
- `proxy/app/core/retrieval.py` (existing)
- Neo4j community detection algorithms
- `etl/graph_builder/` (existing graph data)

**Outputs:**
- Community detection in Neo4j (Louvain/Leiden algorithm)
- Community summary generation and caching
- `GLOBAL_SEARCH_ENABLED` configuration flag

**Verification:**
```bash
python -m pytest tests/proxy/test_retrieval.py -k "global_search" -v
```

**Acceptance Criteria:**
- [ ] Community detection runs during ETL graph building
- [ ] Community summaries stored as Neo4j node properties
- [ ] Global search queries use community summaries instead of entity traversal
- [ ] Response quality improvement on broad queries (measured via eval dataset)
- [ ] Feature gated behind configuration flag
- [ ] Graceful fallback to local search on failure

**Rollback:** Disable `GLOBAL_SEARCH_ENABLED`, use entity-based local search.

---

#### GRPH-02: Multi-Hop Reasoning Enhancement

**Objective:** Improve graph traversal for multi-hop reasoning queries.

**Inputs:**
- `proxy/app/core/retrieval.py` (existing graph expansion)
- Neo4j graph data

**Outputs:**
- Configurable traversal depth (1–4 hops)
- Path relevance scoring
- Cycle detection and prevention

**Verification:**
```bash
python -m pytest tests/proxy/test_retrieval.py -k "multi_hop" -v
```

**Acceptance Criteria:**
- [ ] Traversal depth configurable via `GRAPH_MAX_HOPS` (default: 2)
- [ ] Path relevance scored by entity importance and edge weight
- [ ] Cycles detected and pruned
- [ ] Performance: < 200ms for 3-hop traversal
- [ ] Context from multi-hop paths integrated into generation prompt
- [ ] Unit tests cover 1-hop, 2-hop, and 3-hop scenarios

**Rollback:** Set `GRAPH_MAX_HOPS=1` for single-hop only.

---

### Wave 4 — Deferred Items (Backlog)

> **Items deferred to S4 or later sprints.**

| ID | Task | Source | Effort | Priority | Deferred To |
|----|------|--------|--------|----------|-------------|
| SEC-04 | HTTPS/TLS automation | Checklist #6 | MED | 🟢 LOW | S4-2026 |
| SEC-05 | Secrets rotation automation | Checklist #7 | MED | 🟢 LOW | S4-2026 |
| INFRA-01 | Database migration framework | Checklist #8 | MED | 🟢 LOW | S4-2026 |

**Rationale:** These are infrastructure improvements that don't block feature delivery or quality improvements. They can be addressed in a dedicated DevOps sprint.

---

## Documentation Updates

| ID | Document | Changes | Wave |
|----|----------|---------|------|
| DOC-01 | `docs/en/architecture.md` | Add self-critique loop, CRAG wiring diagrams | 1 |
| DOC-02 | `docs/en/guides/model-evolution.md` | Document adaptive routing, embedding cache | 2 |
| DOC-02 | `docs/en/guides/knowledge-graph-strategy.md` | Document Text-to-Cypher, global search, multi-hop | 2 |
| DOC-03 | `docs/en/guides/roadmap.md` | Update phase status, move completed items | 3 |
| DOC-03 | `docs/en/guides/project-checklist.md` | Mark completed items, update scores | 3 |
| DOC-03 | `docs/en/guides/sprint-plan-2026-s3.md` | Archive original, link to updated | 3 |

---

## Dependency Graph

```
Wave 1 (Quick Wins):
  RQ-01 (Self-Critique)  ─────────┐
  RQ-02 (CRAG Evaluator) ─────────┼──► DOC-01 (Architecture docs)
  RQ-03 (Embedding Cache) ────────┤
  RQ-04 (Text-to-Cypher) ─────────┘

Wave 2 (Quality):
  RQ-02 ──────────────────────────► RQ-05 (Adaptive Routing)
  EVAL-01 (Eval Dataset) ──────────► (standalone, blocks CI)
  QUAL-01 (Mypy Strict) ───────────► (standalone)

Wave 3 (GraphRAG):
  GRPH-01 (Global Search) ────────► GRPH-02 (Multi-Hop)
  PROC-01 (Review Cadence) ────────► (standalone)
  All ─────────────────────────────► DOC-03 (Final docs)
```

---

## Sprint Capacity

| Role | Capacity (SP) | Allocated (SP) | Utilization |
|------|---------------|----------------|-------------|
| Developer | 25 | 23 | 92% |
| Analyst | 8 | 8 | 100% |
| Architect | 4 | 4 | 100% |
| PM | 4 | 1 | 25% |
| **Total** | **41** | **36** | **88%** |

---

## Acceptance Criteria (Sprint-Level)

### Must Have (Sprint Success)

- [ ] Self-critique verification loop wired and tested (RQ-01)
- [ ] CRAG evaluator wired into orchestrator (RQ-02)
- [ ] Embedding cache operational with >30% hit ratio (RQ-03)
- [ ] Text-to-Cypher functional with security validation (RQ-04)
- [ ] Adaptive query routing classifying 4+ intents (RQ-05)
- [ ] All new code has unit tests (≥85% coverage for new modules)
- [ ] `make lint && make typecheck && make test` passes

### Should Have (High Value)

- [ ] Retrieval evaluation dataset ≥200 pairs (EVAL-01)
- [ ] Mypy strict mode passing (QUAL-01)
- [ ] Documentation updated for all new features (DOC-01, DOC-02, DOC-03)

### Nice to Have (Stretch)

- [ ] Global Search Mode implemented (GRPH-01)
- [ ] Multi-Hop Reasoning enhanced (GRPH-02)
- [ ] Quarterly review cadence documented (PROC-01)

---

## Risks & Mitigations

| ID | Risk | Probability | Impact | Mitigation | Owner |
|----|------|-------------|--------|------------|-------|
| R1 | Text-to-Cypher generates unsafe queries | 🟡 MED | 🔴 HIGH | Schema validation, read-only enforcement, query sanitization | Developer |
| R2 | Self-critique loop increases latency >2s | 🟡 MED | 🟡 MED | Feature flag, timeout protection, async critique | Developer |
| R3 | Eval dataset quality insufficient | 🟢 LOW | 🟡 MED | Expert review, inter-annotator agreement check | Analyst |
| R4 | Mypy strict reveals deep type issues | 🟡 MED | 🟡 MED | Incremental fix, module-by-module approach | Developer |
| R5 | Embedding cache memory pressure | 🟢 LOW | 🟢 LOW | LRU eviction, configurable size limit | Developer |
| R6 | GraphRAG community detection slow | 🟡 MED | 🟡 MED | Run during ETL (offline), cache results | Developer |

---

## Definition of Done

- [ ] All tests pass (unit, integration, E2E)
- [ ] `make lint && make format-check && make typecheck` clean
- [ ] Coverage ≥ 80% (including new modules)
- [ ] CI/CD pipeline green
- [ ] Documentation updated for all new features
- [ ] Configuration flags documented in `.env.example`
- [ ] Code reviewed by at least one team member
- [ ] No critical or high-severity bugs introduced

---

## Sprint Review Agenda

### Demo Checklist

- [ ] Self-critique loop: show low-confidence answer re-generation
- [ ] CRAG evaluator: demonstrate 4 action routing paths
- [ ] Embedding cache: show hit ratio metrics in Grafana
- [ ] Text-to-Cypher: demonstrate natural language → Cypher → results
- [ ] Adaptive routing: show different strategies for different query types
- [ ] Eval dataset: show CI regression test running

### Metrics Review

- [ ] Test coverage: ___%
- [ ] Embedding cache hit ratio: ___%
- [ ] CRAG action distribution: USE=__%, REWRITE=__%, EXPAND=__%, FALLBACK=__%
- [ ] Query intent classification accuracy: ___%
- [ ] p95 latency (with new features): ___ms

---

## Tracking

| Wave | Dates | Status | Notes |
|------|-------|--------|-------|
| Wave 1 | Jul 14–16 | 🟡 In Progress | Quick wins, parallel execution |
| Wave 2 | Jul 17–21 | ⚪ Not Started | Quality infrastructure |
| Wave 3 | Jul 22–24 | ⚪ Not Started | GraphRAG enhancements |
| Wave 4 | Jul 25 | ⚪ Not Started | Final docs, review prep |

---

**Last Updated:** 2026-07-13
**Next Review:** 2026-07-14 (Sprint Planning)
**Sprint Owner:** PM
