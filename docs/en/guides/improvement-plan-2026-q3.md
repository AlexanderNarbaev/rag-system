# RAG System Improvement Plan — Q3 2026

> **Status**: Draft  
> **Created**: 2026-07-13  
> **Author**: System Architect  
> **Review Cycle**: Weekly  

---

## Executive Summary

Based on deep research of 19 Habr articles + 12 academic papers, we identified 25 techniques. **12 are implemented**, **13 need implementation**. This plan covers the remaining improvements across 5 phases over 12 weeks.

### Research Sources
- **Habr**: RAG best practices, ColBERT integration, RAPTOR tree construction, GraphRAG community detection, RAGAS evaluation, FLARE active retrieval
- **Papers**: RAPTOR (Stanford 2024), ColBERTv2, GraphRAG (Microsoft 2024), RAGAS, FLARE, HyDE

### Current State (Implemented ✅)
| Feature | Status | Location |
|---------|--------|----------|
| Hybrid Search (dense + sparse + RRF) | ✅ | `proxy/app/core/retrieval.py` |
| Cross-encoder Reranking | ✅ | `proxy/app/core/rerank.py` |
| HyDE Query Expansion | ✅ | `proxy/app/core/hyde.py` |
| LangGraph Orchestration | ✅ | `proxy/app/core/orchestrator/` |
| Neo4j Graph Expansion | ✅ | `proxy/app/core/retrieval.py` |
| Semantic Chunking | ✅ | `etl/chunker/semantic_chunker.py` |
| Token Optimization | ✅ | `proxy/app/core/token_optimizer.py` |
| Context Compression | ✅ | `proxy/app/core/context/compression.py` |
| Hallucination Detection | ✅ | `proxy/app/core/hallucination.py` |
| Confidence Scoring | ✅ | `proxy/app/core/confidence.py` |
| Query Enhancement | ✅ | `proxy/app/core/query_enhancer.py` |
| Live Source Queries | ✅ | `proxy/app/core/live_sources.py` |

### Gap Analysis (13 improvements needed)
| # | Feature | Priority | Phase | Research Source |
|---|---------|----------|-------|----------------|
| 1 | ColBERT Late Interaction | CRITICAL | 1 | ColBERTv2, Habr |
| 2 | RAGAS Integration | CRITICAL | 1 | RAGAS paper, Habr |
| 3 | Negative Rejection | CRITICAL | 1 | Best practices, Habr |
| 4 | NLI Model Upgrade | CRITICAL | 1 | NLI papers, Habr |
| 5 | RAPTOR Hierarchical | HIGH | 2 | RAPTOR paper |
| 6 | Multi-Query Rewriting | HIGH | 2 | HyDE extension |
| 7 | Knee-Point Pruning | HIGH | 2 | Score analysis |
| 8 | GraphRAG Community | MEDIUM | 3 | GraphRAG paper |
| 9 | Global Search Mode | MEDIUM | 3 | GraphRAG paper |
| 10 | Multi-Hop Reasoning | MEDIUM | 3 | Graph traversal |
| 11 | FLARE Active Retrieval | MEDIUM | 5 | FLARE paper |
| 12 | Two-Stage Reranking | MEDIUM | 5 | ColBERT + Cross-encoder |
| 13 | Adaptive Chunking | MEDIUM | 5 | Semantic chunking |

---

## Phase 1 — Foundation (Week 1-2) [CRITICAL]

> **Goal**: Establish quality measurement, improve retrieval precision, fix hallucination  
> **Risk**: HIGH — foundation for all subsequent phases  
> **Dependencies**: bge-m3 model, NLI model pre-download  

### 1.1 ColBERT Late Interaction

**Goal**: Add ColBERT token-level reranking using bge-m3's native ColBERT support

**Why**: ColBERT provides fine-grained token-level relevance scoring. bge-m3 already generates ColBERT vectors — we just need to store and query them.

**Research**: ColBERTv2 paper shows 15-20% precision improvement over dense-only retrieval.

**Files to Modify**:
```
etl/indexer/qdrant_hybrid.py     — Store ColBERT vectors during indexing
proxy/app/core/retrieval.py      — Query with ColBERT late interaction
proxy/app/core/rerank.py         — Integrate ColBERT into reranking pipeline
```

**New Files**:
```
tests/proxy/test_colbert.py      — Unit + integration tests
docs/en/adr/ADR-015-colbert.md   — Architecture decision
```

**Implementation Steps**:
1. Configure Qdrant collection with ColBERT vector field
2. Modify ETL to extract and store ColBERT vectors from bge-m3
3. Implement ColBERT scoring function (MaxSim)
4. Integrate into hybrid search with configurable weight
5. A/B test against current retrieval

**Acceptance Criteria**:
- [ ] ColBERT vectors stored for all indexed documents
- [ ] ColBERT scoring returns correct MaxSim values
- [ ] Reranking precision improves by ≥15% on test set
- [ ] Latency increase < 50ms per query

**TDD Approach**:
```python
# tests/proxy/test_colbert.py

def test_colbert_vectors_stored(qdrant_client, sample_docs):
    """Given indexed docs, ColBERT vectors should be present."""
    # Arrange: index sample documents
    # Act: retrieve point with vectors
    # Assert: colbert_vectors field exists and has correct dimensions

def test_maxsim_scoring(query_tokens, doc_tokens):
    """MaxSim should compute token-level similarity correctly."""
    # Arrange: known token vectors
    # Act: compute MaxSim
    # Assert: score matches expected value (±0.01)

def test_colbert_improves_reranking(test_queries, ground_truth):
    """ColBERT reranking should outperform dense-only."""
    # Arrange: test queries with known relevant docs
    # Act: retrieve with and without ColBERT
    # Assert: ColBERT variant has higher MRR
```

**Risk**: Storage overhead +20%
**Mitigation**: Use ColBERT quantization (int8), IVF index

---

### 1.2 RAGAS Integration

**Goal**: Wire RAGAS metrics into feedback loop for systematic quality measurement

**Why**: RAGAS provides standardized RAG quality metrics (faithfulness, answer relevancy, context precision, context recall). Currently we have no systematic quality measurement.

**Research**: RAGAS paper (2023) — industry standard for RAG evaluation.

**Files to Modify**:
```
proxy/app/core/ragas_eval.py     — NEW: RAGAS evaluation module
proxy/app/api/feedback.py        — Add RAGAS scoring to feedback
proxy/app/api/chat.py            — Include RAGAS scores in response
```

**New Files**:
```
tests/proxy/test_ragas.py        — Unit tests
config/ragas_config.yaml         — RAGAS configuration
```

**Implementation Steps**:
1. Create `ragas_eval.py` with metric implementations
2. Wire into feedback endpoint for post-hoc evaluation
3. Add RAGAS scores to response extensions
4. Create evaluation dataset from expert feedback
5. Set up regression detection in CI/CD

**Acceptance Criteria**:
- [ ] Every response includes RAGAS scores in extensions
- [ ] `ragas.faithfulness` > 0.8 for test set
- [ ] `ragas.answer_relevancy` > 0.7 for test set
- [ ] RAGAS scores stored in feedback database

**RAGAS Metrics**:
| Metric | Description | Target |
|--------|-------------|--------|
| Faithfulness | Answer grounded in context | > 0.8 |
| Answer Relevancy | Answer addresses question | > 0.7 |
| Context Precision | Retrieved context is relevant | > 0.7 |
| Context Recall | All relevant context retrieved | > 0.6 |

**Risk**: RAGAS evaluation adds latency
**Mitigation**: Async evaluation, sample-based for high-volume

---

### 1.3 Negative Rejection

**Goal**: Return "I don't know" when retrieval quality is insufficient

**Why**: System currently hallucinates when no relevant documents exist. Better to refuse than to fabricate.

**Research**: Best practices from RAG production deployments — negative rejection is critical for trust.

**Files to Modify**:
```
proxy/app/core/confidence.py     — Add retrieval quality threshold
proxy/app/main.py                — Handle rejection in chat endpoint
proxy/app/api/chat.py            — Return structured rejection response
```

**New Files**:
```
tests/proxy/test_negative_rejection.py — Behavior tests
docs/en/adr/ADR-016-negative-rejection.md
```

**Implementation Steps**:
1. Define "strong source" criteria (score > threshold, count >= 2)
2. Add retrieval quality check before LLM call
3. Return structured "I don't know" with confidence 0.0
4. Log rejections for analysis
5. A/B test threshold values

**Acceptance Criteria**:
- [ ] 100% refusal rate for queries with < 2 strong sources
- [ ] Rejection response includes `rag_confidence: 0.0`
- [ ] Rejection response includes reason (insufficient_sources)
- [ ] No hallucinated answers for unknown topics

**BDD Scenario**:
```gherkin
Feature: Negative Rejection

  Scenario: Query with no relevant sources
    Given the knowledge base has no documents about "quantum computing"
    When user asks "What is quantum computing?"
    Then system returns "I don't have enough information to answer that question"
    And response includes rag_confidence: 0.0
    And response includes rag_rejection_reason: "insufficient_sources"

  Scenario: Query with weak sources
    Given the knowledge base has 1 document about "quantum computing" with score 0.3
    When user asks "What is quantum computing?"
    Then system returns "I don't have enough information to answer that question"
    And response includes rag_confidence: 0.1
```

**Risk**: Over-rejection blocks valid answers
**Mitigation**: Configurable threshold, A/B testing, expert review loop

---

### 1.4 NLI Model Upgrade

**Goal**: Replace word-overlap proxy with real NLI model for hallucination detection

**Why**: Current hallucination detection uses word overlap — primitive and unreliable. Real NLI models provide semantic entailment scoring.

**Research**: NLI-based grounding is state-of-the-art for hallucination detection.

**Files to Modify**:
```
proxy/app/core/confidence.py     — Use NLI for grounding check
proxy/app/core/hallucination.py  — NLI-based hallucination scoring
proxy/app/core/grounding.py      — Upgrade NLI implementation
```

**Model**: `cross-encoder/nli-distilroberta-base` (pre-downloaded for air-gapped)

**New Files**:
```
tests/proxy/test_nli.py          — NLI-specific tests
```

**Implementation Steps**:
1. Load NLI model at startup (lazy loading with warmup)
2. Replace word-overlap with NLI entailment scoring
3. Implement three-way classification: entailment/neutral/contradiction
4. Set thresholds: entailment > 0.7 = grounded, contradiction > 0.7 = hallucination
5. Benchmark against current approach

**Acceptance Criteria**:
- [ ] NLI model loaded and functional
- [ ] Hallucination detection F1 > 0.8
- [ ] False positive rate < 10%
- [ ] Latency < 100ms per check

**Risk**: NLI model memory usage (~500MB)
**Mitigation**: Distilled model, lazy loading, circuit breaker

---

## Phase 2 — Advanced Retrieval (Week 3-4) [HIGH]

> **Goal**: Improve retrieval quality with advanced techniques  
> **Risk**: MEDIUM — depends on Phase 1 completion  
> **Dependencies**: ColBERT integration, RAGAS baseline  

### 2.1 RAPTOR Hierarchical Retrieval

**Goal**: Build tree-structured summaries for multi-level retrieval

**Why**: RAPTOR enables retrieval at different abstraction levels — from specific details to high-level summaries. Critical for complex queries.

**Research**: RAPTOR paper (Stanford 2024) — 20% improvement on multi-hop QA.

**New Files**:
```
etl/indexer/tree_builder.py      — Tree construction from chunks
etl/indexer/summarizer.py        — Level-by-level summarization
tests/etl/test_tree_builder.py   — Tree construction tests
```

**Files to Modify**:
```
etl/scheduler/run_etl.py         — Add tree building step
proxy/app/core/retrieval.py      — Multi-level retrieval
```

**Implementation Steps**:
1. Cluster chunks by embedding similarity (Gaussian Mixture)
2. Summarize clusters → level 1 nodes
3. Cluster summaries → level 2 nodes
4. Repeat until tree depth 3-4
5. Index all tree nodes in Qdrant with level metadata
6. Retrieve from multiple levels, merge with RRF

**Acceptance Criteria**:
- [ ] Tree depth 3-4 levels for documents > 10 chunks
- [ ] Summary quality score > 0.7 (human eval)
- [ ] Multi-level retrieval improves Recall@10 by > 10%
- [ ] Tree building time < 5min per 1000 chunks

**Algorithm**:
```
1. chunks = extract_chunks(document)
2. embeddings = embed(chunks)
3. clusters = gaussian_mixture(embeddings, n_components=sqrt(len(chunks)))
4. for level in range(max_depth):
5.     summaries = llm_summarize(clusters)
6.     if len(summaries) < min_cluster_size: break
7.     clusters = gaussian_mixture(embed(summaries))
8. tree = build_tree(clusters, summaries)
9. index_tree(tree)
```

**Risk**: Build time, summary quality
**Mitigation**: Async ETL, human-in-the-loop for quality

---

### 2.2 Query Rewriting with Multiple Formulations

**Goal**: Generate 2-3 query variants, fuse results with RRF

**Why**: Single query may miss relevant documents. Multiple formulations increase recall.

**Research**: HyDE extension — multiple hypothetical documents improve coverage.

**Files to Modify**:
```
proxy/app/core/query_enhancer.py — Multi-query generation
proxy/app/core/retrieval.py      — RRF fusion of multi-query results
```

**New Files**:
```
tests/proxy/test_query_enhancer.py — Multi-query tests
```

**Implementation Steps**:
1. Generate 2-3 query reformulations using SLM
2. Retrieve for each variant
3. Fuse results with RRF (Reciprocal Rank Fusion)
4. Deduplicate and rerank

**Acceptance Criteria**:
- [ ] 2-3 query variants generated per request
- [ ] Recall@10 improvement > 10%
- [ ] Latency increase < 200ms
- [ ] Variants are semantically diverse

**Query Reformulation Strategies**:
| Strategy | Example |
|----------|---------|
| Paraphrase | "How to configure X?" → "X configuration guide" |
| Specificity | "auth" → "JWT authentication setup" |
| Abstraction | "JWT token refresh" → "authentication token management" |

---

### 2.3 Knee-Point Pruning

**Goal**: Dynamic top-k using score curve analysis

**Why**: Fixed top-k either includes irrelevant docs or misses relevant ones. Knee-point finds the natural cutoff.

**Research**: Score distribution analysis — maximum distance from chord.

**Files to Modify**:
```
proxy/app/core/retrieval.py      — Knee-point detection
```

**New Files**:
```
tests/proxy/test_knee_point.py   — Knee-point tests
```

**Algorithm**:
```
1. scores = [doc.score for doc in retrieved_docs]
2. normalized = normalize(scores)  # [0, 1]
3. chord = line from (0, normalized[0]) to (n-1, normalized[-1])
4. distances = [perpendicular_distance(point, chord) for point in enumerate(normalized)]
5. knee_index = argmax(distances)
6. return docs[:knee_index + 1]
```

**Acceptance Criteria**:
- [ ] 60%+ irrelevant docs pruned automatically
- [ ] No relevant docs pruned (precision = 1.0 for pruned set)
- [ ] Works across different score distributions
- [ ] Fallback to fixed top-k if curve is linear

**Risk**: Over-pruning for uniform scores
**Mitigation**: Minimum doc count (3), fallback threshold

---

## Phase 3 — Knowledge Graph (Week 5-6) [MEDIUM]

> **Goal**: Leverage graph structure for complex queries  
> **Risk**: MEDIUM — Neo4j dependency  
> **Dependencies**: Neo4j GDS library, community detection  

### 3.1 GraphRAG Community Detection

**Goal**: Leiden algorithm for community detection in Neo4j

**Why**: Communities represent topic clusters. Summaries enable corpus-wide questions.

**Research**: GraphRAG paper (Microsoft 2024) — community detection + summarization.

**New Files**:
```
etl/graph_builder/community.py   — Community detection
etl/graph_builder/summarizer.py  — Community summarization
tests/etl/test_community.py      — Community tests
```

**Files to Modify**:
```
etl/graph_builder/neo4j_loader.py — Store communities
etl/graph_builder/schema.yaml     — Community schema
```

**Implementation Steps**:
1. Install Neo4j GDS library
2. Run Leiden algorithm on entity graph
3. Store community membership as node property
4. Generate community summaries using LLM
5. Index summaries in Qdrant for retrieval

**Acceptance Criteria**:
- [ ] Communities detected with modularity > 0.3
- [ ] Community summaries generated for all communities
- [ ] Summaries indexed and retrievable
- [ ] Community detection runs in < 10min for 10K nodes

---

### 3.2 Global Search Mode

**Goal**: Answer corpus-wide questions using community summaries

**Why**: Some questions require understanding across entire knowledge base, not just specific documents.

**Research**: GraphRAG global search — map-reduce over community summaries.

**Files to Modify**:
```
proxy/app/core/retrieval.py      — Global search mode
proxy/app/api/chat.py            — Expose global search parameter
```

**New Files**:
```
tests/proxy/test_global_search.py — Global search tests
```

**Implementation Steps**:
1. Detect if query is "global" (corpus-wide) vs "local" (specific)
2. For global: retrieve all community summaries
3. Map: generate partial answers from each summary
4. Reduce: combine partial answers into final answer
5. Include community sources in response

**Acceptance Criteria**:
- [ ] Global queries return community-level answers
- [ ] Sources include community summaries
- [ ] Global search latency < 5s
- [ ] Answer quality > 0.7 (human eval)

---

### 3.3 Multi-Hop Reasoning

**Goal**: Traverse graph for complex queries requiring multiple entities

**Why**: Some questions require following entity relationships across multiple hops.

**Research**: Knowledge graph traversal for multi-hop QA.

**Files to Modify**:
```
proxy/app/core/retrieval.py      — graph_expand() enhancement
```

**New Files**:
```
tests/proxy/test_multi_hop.py    — Multi-hop tests
```

**Implementation Steps**:
1. Extract entities from query
2. Find entities in Neo4j
3. Traverse graph up to 3 hops
4. Collect connected documents
5. Merge with vector retrieval results

**Acceptance Criteria**:
- [ ] 3+ hop queries answered correctly
- [ ] Graph traversal adds relevant context
- [ ] Latency < 500ms for 3-hop traversal
- [ ] No circular traversals

---

## Phase 4 — Production Hardening (Week 7-8) [HIGH]

> **Goal**: Achieve production-grade quality, security, and observability  
> **Risk**: LOW — incremental improvements  
> **Dependencies**: All feature phases  

### 4.1 TDD/BDD Test Coverage

**Goal**: 90%+ test coverage with real behavioral tests

**Why**: Current tests are mostly unit tests. Need integration and behavior tests.

**Strategy**: Given-When-Then for all user stories.

**Files to Modify**:
```
All test files                    — Add behavior tests
tests/conftest.py                — Shared fixtures
```

**New Files**:
```
tests/bdd/                       — BDD feature files
pytest.ini                       — Pytest configuration
```

**Acceptance Criteria**:
- [ ] Coverage > 90% (measured by `pytest --cov`)
- [ ] 0 fake tests (all tests verify real behavior)
- [ ] All user stories have BDD scenarios
- [ ] CI fails on coverage drop

**Test Categories**:
| Category | Count | Coverage Target |
|----------|-------|-----------------|
| Unit | 200+ | 95% |
| Integration | 50+ | 80% |
| BDD | 30+ | All user stories |
| E2E | 10+ | Critical paths |

---

### 4.2 CI/CD Pipeline

**Goal**: Full GitHub Actions pipeline with quality gates

**Why**: Automated quality checks on every PR.

**New Files**:
```
.github/workflows/ci.yml         — Main CI pipeline
.github/workflows/security.yml   — Security scanning
.github/workflows/release.yml    — Release automation
```

**Pipeline Stages**:
```yaml
stages:
  - lint:        ruff check, ruff format --check
  - typecheck:   mypy --strict
  - test:        pytest --cov --cov-fail-under=80
  - security:    bandit, trivy, codeql
  - build:       docker build
  - deploy:      staging (on main)
```

**Acceptance Criteria**:
- [ ] All gates pass on every PR
- [ ] PR blocked if any gate fails
- [ ] Coverage report in PR comments
- [ ] Security scan results in PR

---

### 4.3 Security Hardening

**Goal**: Fix all security findings, enable Dependabot

**Why**: Production security baseline.

**New Files**:
```
.github/dependabot.yml           — Dependency updates
.github/workflows/codeql.yml     — Code scanning
```

**Files to Modify**:
```
proxy/app/auth/                  — Security fixes
requirements_proxy.txt           — Pin versions
```

**Acceptance Criteria**:
- [ ] 0 critical/high vulnerabilities (Trivy)
- [ ] 0 high/critical code issues (Bandit)
- [ ] Dependabot enabled for all ecosystems
- [ ] Secrets scanning enabled

---

### 4.4 Observability

**Goal**: Structured logging, metrics, tracing

**Why**: Production debugging and monitoring.

**Files to Modify**:
```
proxy/app/shared/logging.py      — Structured JSON logging
proxy/app/shared/metrics.py      — Prometheus metrics
proxy/app/shared/tracing.py      — OpenTelemetry tracing
```

**New Files**:
```
config/monitoring/prometheus.yml — Prometheus config
config/monitoring/grafana/       — Grafana dashboards
```

**Metrics to Track**:
| Metric | Type | Description |
|--------|------|-------------|
| `rag_retrieval_latency_ms` | Histogram | Retrieval latency |
| `rag_rerank_latency_ms` | Histogram | Reranking latency |
| `rag_llm_latency_ms` | Histogram | LLM generation latency |
| `rag_ragas_faithfulness` | Gauge | RAGAS faithfulness score |
| `rag_hallucination_rate` | Counter | Hallucination detections |
| `rag_negative_rejection_rate` | Counter | Negative rejections |
| `rag_cache_hit_rate` | Gauge | Cache effectiveness |

**Acceptance Criteria**:
- [ ] All requests traced with correlation ID
- [ ] Metrics exported to Prometheus
- [ ] Grafana dashboards operational
- [ ] Alerts configured for SLA breaches

---

## Phase 5 — Advanced Features (Week 9-12) [MEDIUM]

> **Goal**: Implement cutting-edge RAG techniques  
> **Risk**: LOW — optional enhancements  
> **Dependencies**: Phase 1-4 complete  

### 5.1 FLARE Active Retrieval

**Goal**: Monitor generation confidence, re-retrieve when low

**Why**: For long-form answers, initial retrieval may be insufficient. FLARE triggers re-retrieval mid-generation.

**Research**: FLARE paper — active retrieval during generation.

**Files to Modify**:
```
proxy/app/core/orchestrator/nodes.py — FLARE node
proxy/app/core/orchestrator/graph.py — Add FLARE loop
```

**New Files**:
```
tests/proxy/test_flare.py           — FLARE tests
```

**Implementation Steps**:
1. Monitor token probabilities during generation
2. If confidence < threshold, pause generation
3. Generate hypothetical query from partial answer
4. Retrieve additional context
5. Resume generation with new context

**Acceptance Criteria**:
- [ ] Long-form answers maintain quality throughout
- [ ] Re-retrieval triggered when confidence drops
- [ ] Latency increase < 30% for long answers
- [ ] No infinite re-retrieval loops (max 2)

---

### 5.2 Two-Stage Reranking

**Goal**: Fast embed (30-50ms) → cross-encoder (150-400ms)

**Why**: Current reranking applies cross-encoder to all candidates. Two-stage is faster.

**Files to Modify**:
```
proxy/app/core/rerank.py            — Two-stage implementation
```

**New Files**:
```
tests/proxy/test_rerank.py          — Reranking tests
```

**Implementation Steps**:
1. Stage 1: Fast embedding rerank (top-50 → top-15)
2. Stage 2: Cross-encoder rerank (top-15 → top-5)
3. Configurable stage thresholds
4. Fallback to single-stage if needed

**Acceptance Criteria**:
- [ ] 50% latency reduction with same quality
- [ ] Stage 1 latency < 50ms
- [ ] Stage 2 latency < 400ms
- [ ] Quality within 2% of single-stage

---

### 5.3 Adaptive Chunking

**Goal**: Dynamic chunk size based on document structure

**Why**: Fixed chunk size breaks semantic units. Adaptive respects document structure.

**Files to Modify**:
```
etl/chunker/semantic_chunker.py    — Adaptive logic
```

**New Files**:
```
tests/etl/test_adaptive_chunking.py — Adaptive tests
```

**Implementation Steps**:
1. Analyze document structure (headers, paragraphs, lists)
2. Set base chunk size by document type
3. Adjust boundaries to respect semantic units
4. Merge small chunks, split large ones
5. Preserve metadata (section, page, etc.)

**Acceptance Criteria**:
- [ ] Chunk quality > 0.8 across document types
- [ ] No broken sentences at chunk boundaries
- [ ] Section metadata preserved
- [ ] Works for Confluence, Jira, GitLab, docs

---

## Architecture Decisions

### ADR-015: ColBERT Integration
- **Status**: Proposed
- **Context**: bge-m3 supports ColBERT natively, storage overhead acceptable
- **Decision**: Store ColBERT vectors alongside dense vectors in Qdrant
- **Consequences**: +20% storage, +15% retrieval precision, +30ms query latency
- **Alternatives**: Late interaction at query time (rejected: too slow)

### ADR-016: RAGAS as Quality Gate
- **Status**: Proposed
- **Context**: Need systematic RAG quality measurement
- **Decision**: RAGAS metrics in CI/CD pipeline, block deploy on regression
- **Consequences**: Quality regression detected before deployment, evaluation cost
- **Alternatives**: Manual evaluation (rejected: not scalable)

### ADR-017: Negative Rejection Policy
- **Status**: Proposed
- **Context**: System hallucinates when no relevant docs exist
- **Decision**: Refuse to generate when < 2 strong sources (score > 0.5)
- **Consequences**: Some queries get "I don't know" instead of answer
- **Alternatives**: Always generate with disclaimer (rejected: erodes trust)

---

## Implementation Strategy

### TDD Approach (Test-Driven Development)
```
1. Write failing test first (RED)
2. Implement minimum code to pass (GREEN)
3. Refactor with confidence (REFACTOR)
4. Commit with test evidence
```

### BDD User Stories (Behavior-Driven Development)
```gherkin
Feature: Negative Rejection
  Scenario: Query with no relevant sources
    Given the knowledge base has no documents about "quantum computing"
    When user asks "What is quantum computing?"
    Then system returns "I don't have enough information"
    And response includes rag_confidence: 0.0

Feature: ColBERT Reranking
  Scenario: Improved precision with ColBERT
    Given documents about "JWT authentication"
    When user asks "How to implement JWT?"
    Then ColBERT-reranked results have higher precision
    And top-3 results are all relevant
```

### DDD Boundaries (Domain-Driven Design)
```
┌─────────────────────────────────────────────────────────────┐
│                    RAG System                               │
├──────────────────┬──────────────────┬───────────────────────┤
│ Retrieval Domain │ Generation Domain│    ETL Domain         │
│                  │                  │                       │
│ retrieval.py     │ orchestrator/    │ extractors/           │
│ hyde.py          │ confidence.py    │ chunker/              │
│ query_enhancer.py│ hallucination.py │ indexer/              │
│ rerank.py        │ grounding.py     │ graph_builder/        │
│ colbert.py       │                  │                       │
├──────────────────┴──────────────────┴───────────────────────┤
│                   Evaluation Domain                         │
│                                                             │
│ evaluation.py    │ ragas_eval.py    │ retrieval_evaluator.py│
└─────────────────────────────────────────────────────────────┘
```

---

## Quality Gates

### Every PR Must Pass:
1. `ruff check` — 0 errors
2. `ruff format --check` — formatted
3. `mypy --strict` — 0 errors (target)
4. `pytest` — all tests pass
5. `pytest --cov --cov-fail-under=80` — coverage ≥ 80%
6. `bandit -r proxy/` — 0 high/critical
7. `trivy fs .` — 0 critical CVEs
8. GitHub CI — all green

### Every Release Must Have:
1. CHANGELOG.md updated with all changes
2. All ADRs reviewed and accepted
3. Performance benchmarks (retrieval, rerank, generation)
4. Security scan report (Bandit, Trivy, CodeQL)
5. Documentation updated (API, guides, ADRs)
6. RAGAS evaluation on test set

---

## Monitoring & Observability

### Key Metrics (SLIs):
| SLI | Definition | Target (SLO) |
|-----|-----------|--------------|
| Retrieval Latency | p95 time to retrieve | < 500ms |
| Rerank Latency | p95 time to rerank | < 400ms |
| End-to-End Latency | p95 total response time | < 3s |
| RAGAS Faithfulness | Answer grounded in context | > 0.8 |
| Hallucination Rate | % answers with hallucination | < 5% |
| Negative Rejection | Correct refusal rate | 100% |
| Availability | Uptime | > 99.5% |

### Alerts:
| Alert | Condition | Severity |
|-------|-----------|----------|
| High Latency | p95 > 2s | Warning |
| Critical Latency | p95 > 5s | Critical |
| Low Faithfulness | RAGAS < 0.7 | Warning |
| High Hallucination | > 10% | Critical |
| Service Down | Health check fails | Critical |
| Disk Full | > 90% usage | Warning |

### Grafana Dashboards:
1. **RAG Overview**: Request rate, latency, error rate
2. **Retrieval Quality**: RAGAS scores, rerank metrics
3. **ETL Pipeline**: Indexing rate, chunk quality, tree depth
4. **Infrastructure**: CPU, memory, disk, network

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation | Owner |
|------|-------------|--------|------------|-------|
| ColBERT storage overhead | High | Medium | Quantize vectors (int8), IVF index | ETL Lead |
| RAPTOR build time | Medium | Low | Async ETL, progress tracking | ETL Lead |
| NLI model memory | Medium | Medium | Distilled model, lazy loading | Proxy Lead |
| GraphRAG complexity | High | High | Start with local search only | Architect |
| RAGAS evaluation cost | Medium | Low | Sample-based, async | QA Lead |
| Negative rejection over-refuse | Medium | Medium | A/B test, expert review | Product |
| Neo4j GDS dependency | Low | High | Fallback to simple graph queries | Architect |

---

## Success Metrics

| Metric | Current | Target | Deadline | Owner |
|--------|---------|--------|----------|-------|
| Test coverage | ~77% | 90% | Week 4 | QA Lead |
| RAGAS faithfulness | N/A | > 0.8 | Week 2 | Proxy Lead |
| Hallucination rate | Unknown | < 5% | Week 4 | Proxy Lead |
| Retrieval latency p95 | ~500ms | < 300ms | Week 6 | Proxy Lead |
| Negative rejection | 0% | 100% | Week 1 | Proxy Lead |
| ColBERT precision gain | 0% | +15% | Week 2 | ETL Lead |
| Multi-query recall gain | 0% | +10% | Week 4 | Proxy Lead |
| Security vulnerabilities | ? | 0 critical | Week 8 | DevOps |

---

## Dependencies

### External:
| Dependency | Purpose | Status | Action |
|------------|---------|--------|--------|
| bge-m3 model | ColBERT vectors | Available | Verify ColBERT support |
| Neo4j GDS | Community detection | Needs install | Add to docker-compose |
| NLI model | Hallucination detection | Needs download | Pre-download offline |
| RAGAS library | Quality metrics | Needs install | Add to requirements |

### Internal:
| Dependency | Impact | Action |
|------------|--------|--------|
| Qdrant collection rebuild | ColBERT vectors | Migration script |
| Neo4j schema update | Communities | Schema migration |
| Config update | New features | .env updates |
| Test infrastructure | BDD support | pytest-bdd setup |

---

## Rollback Plan

Each phase is independently deployable with rollback capability:

1. **Feature Flags**: New behavior behind `ENABLE_COLBERT`, `ENABLE_RAPTOR`, etc.
2. **A/B Testing**: Compare new vs old with traffic splitting
3. **Circuit Breakers**: Disable new components on failure
4. **WAL for ETL**: Resume from checkpoint on tree build failure
5. **Database Migrations**: Reversible schema changes

---

## Communication Plan

### Weekly:
- Progress update in `project-checklist.md`
- Test results in CI/CD dashboard
- Security scan results summary
- Risk register update

### Per Change:
- Git commit with clear message (conventional commits)
- CHANGELOG.md entry
- ADR for architectural decisions
- Memory update for context persistence

### Milestones:
| Week | Milestone | Deliverable |
|------|-----------|-------------|
| 2 | Foundation Complete | ColBERT, RAGAS, Negative Rejection, NLI |
| 4 | Advanced Retrieval | RAPTOR, Multi-Query, Knee-Point |
| 6 | Knowledge Graph | GraphRAG, Global Search, Multi-Hop |
| 8 | Production Ready | Tests, CI/CD, Security, Observability |
| 12 | Advanced Features | FLARE, Two-Stage Rerank, Adaptive Chunking |

---

## Appendix

### A. Research Sources

**Habr Articles** (19):
1. RAG best practices for production
2. ColBERT integration with Qdrant
3. RAPTOR tree construction
4. GraphRAG community detection
5. RAGAS evaluation framework
6. FLARE active retrieval
7. HyDE query expansion
8. Semantic chunking strategies
9. Cross-encoder reranking
10. Hybrid search with RRF
11. Knowledge graph for RAG
12. Token optimization techniques
13. Context compression strategies
14. Hallucination detection methods
15. Negative rejection patterns
16. Multi-hop reasoning
17. Query rewriting techniques
18. Score distribution analysis
19. RAG observability

**Academic Papers** (12):
1. RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval (Stanford 2024)
2. ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction
3. GraphRAG: Unlocking LLM Discovery on Narrative Private Data (Microsoft 2024)
4. RAGAS: Automated Evaluation of Retrieval Augmented Generation
5. FLARE: Forward-Looking Active REtrieval Augmented Generation
6. HyDE: Precise Zero-Shot Dense Retrieval without Relevance Labels
7. Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks
8. Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods
9. NLI-based Hallucination Detection
10. Semantic Chunking for RAG
11. Token-Level Late Interaction
12. Adaptive Retrieval for RAG

### B. Glossary
| Term | Definition |
|------|-----------|
| ColBERT | Contextualized Late Interaction over BERT |
| RAPTOR | Recursive Abstractive Processing for Tree-Organized Retrieval |
| GraphRAG | Graph-based Retrieval Augmented Generation |
| RAGAS | Retrieval Augmented Generation Assessment |
| FLARE | Forward-Looking Active REtrieval |
| HyDE | Hypothetical Document Embeddings |
| RRF | Reciprocal Rank Fusion |
| NLI | Natural Language Inference |
| MaxSim | Maximum Similarity (ColBERT scoring) |
| Leiden | Community detection algorithm |

---

*This plan is a living document. Update weekly with progress, risks, and decisions.*
