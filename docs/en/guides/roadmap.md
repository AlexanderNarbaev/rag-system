# Development Roadmap

**Last Updated:** 2026-07-13

---

## Overview

The RAG system follows a phased development approach, building capabilities incrementally from core retrieval through
self-correcting, agentic, and federated architectures.

---

## Implementation Status (2026-07-13)

### Phase 1 — Foundation ✅ COMPLETE

| Feature                  | Status | File                         |
|--------------------------|--------|------------------------------|
| ColBERT Late Interaction | ✅      | proxy/app/core/rerank.py     |
| RAGAS Integration        | ✅      | proxy/app/core/ragas_eval.py |
| Negative Rejection       | ✅      | proxy/app/core/confidence.py |

### Phase 2 — Advanced Retrieval ✅ COMPLETE

| Feature               | Status | File                             |
|-----------------------|--------|----------------------------------|
| Knee-Point Pruning    | ✅      | proxy/app/core/retrieval.py      |
| Multi-Query Rewriting | ✅      | proxy/app/core/query_enhancer.py |
| RAPTOR Hierarchical   | ✅      | etl/indexer/tree_builder.py      |

### Phase 3 — Knowledge Graph ✅ COMPLETE

| Feature             | Status | File                           |
|---------------------|--------|--------------------------------|
| Community Detection | ✅      | etl/graph_builder/community.py |
| Global Search Mode  | ✅      | proxy/app/core/retrieval.py    |
| Multi-Hop Reasoning | ✅      | proxy/app/core/retrieval.py    |
| Text-to-Cypher      | ✅      | proxy/app/core/retrieval.py    |

### Phase 4 — Production Hardening ✅ COMPLETE

| Feature            | Status | File                                   |
|--------------------|--------|----------------------------------------|
| Security Scanners  | ✅      | .github/workflows/security.yml         |
| Prometheus Metrics | ✅      | proxy/app/shared/metrics.py            |
| E2E Test Suite     | ✅      | tests/e2e/test_full_rag_pipeline.py    |
| RAGAS Dashboard    | ✅      | config/monitoring/ragas-dashboard.json |

### Phase 5 — Advanced Features ✅ COMPLETE

| Feature                | Status | File                            |
|------------------------|--------|---------------------------------|
| FLARE Active Retrieval | ✅      | proxy/app/core/flare.py         |
| Two-Stage Reranking    | ✅      | proxy/app/core/rerank.py        |
| Adaptive Chunking      | ✅      | etl/chunker/semantic_chunker.py |

### Wave 1 — Quick Wins ✅ COMPLETE

| Feature                    | Status | File                         |
|----------------------------|--------|------------------------------|
| Self-Critique Verification | ✅      | proxy/app/core/confidence.py |
| CRAG Corrective Retrieval  | ✅      | proxy/app/main.py            |
| Embedding Cache            | ✅      | proxy/app/core/retrieval.py  |

### Wave 2 — Quality & Routing ✅ COMPLETE

| Feature                | Status | File                           |
|------------------------|--------|--------------------------------|
| Adaptive Query Routing | ✅      | proxy/app/core/query_router.py |

### Test Statistics

- Total tests: 2,688 passed
- Coverage: 75.00%
- CI/CD: All green (CI, Security, Docs)
- Security: bandit + trivy + dependabot

---

## Current Status

**All Phases 1–8: COMPLETE ✅**

| Component                                      | Status            | Tests     |
|------------------------------------------------|-------------------|-----------|
| Core RAG Pipeline                              | ✅ Complete        | 544       |
| Model Evolution (LoRA/QLoRA, EvalGate, Canary) | ✅ Complete        | 277       |
| MCP Server                                     | ✅ Complete        | 56        |
| Integration Tests                              | ✅ Complete        | 64        |
| E2E Tests                                      | ✅ Complete        | 32        |
| Performance Tests                              | ✅ Complete        | 12        |
| **Total Test Suite**                           | **✅ 2,688 tests** | **2,688** |

---

## Phase 1: Core Infrastructure ✅

**Theme:** Establish the foundation — hybrid retrieval, reranking, ETL pipeline, and OpenAI-compatible API.

**Status:** Complete

### Features

- Hybrid retrieval (dense + sparse) with RRF fusion via Qdrant
- Cross-encoder reranking with MiniLM-L-6-v2
- Content-addressable chunk versioning (SHA-256) with hot/cold storage
- Dual-LLM architecture: SLM for routing + LLM for generation
- LangGraph agentic orchestrator (optional)
- OpenAI-compatible proxy API (`/v1/chat/completions`, `/v1/models`, `/v1/health`)
- Redis-backed multi-tier cache (embeddings, rerank, responses)
- Human-in-the-loop feedback dashboard (Streamlit)
- WAL-based incremental ETL with checkpoint recovery
- GraphRAG via Neo4j entity extraction and multi-hop traversal
- Prometheus metrics and structured logging
- Rate limiting (token bucket per IP)
- Graceful degradation design for all components
- Air-gapped deployment support (models pre-downloaded)
- Cross-encoder reranker fine-tuning from HITL feedback

---

## Phase 2: Self-Improving RAG ✅

**Theme:** Add confidence scoring, active feedback, and knowledge base self-enrichment.

**Status:** Complete

### Features

- **Confidence scoring** — heuristic scoring (context sufficiency, context-to-answer ratio, uncertainty phrase
  detection) with configurable threshold
- **Active feedback** — `/v1/feedback` endpoint, `rag_feedback_id` in all responses, expert rating collection
- **VERIFY_CASCADE routing** — `check_confidence` node in LangGraph orchestrator; low-confidence answers trigger query
  rewrite loop
- **Self-enrichment** — positive feedback with corrections indexed back into Qdrant as Q&A pairs
- **Admin alerts** — low-confidence answers beyond loop limit trigger admin alerts
- **Response metadata** — `rag_confidence` score and `rag_feedback_id` injected into responses

---

## Phase 3: Token Optimization & Quality Foundations ✅

**Theme:** Reduce token costs and establish measurable quality baselines.

**Status:** Complete

### Features

| # | Feature                           | Description                                                                                   | Success Criteria                                                       |
|---|-----------------------------------|-----------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| 1 | **Retrieval evaluation dataset**  | Build 200+ query–document labeled pairs from HITL logs + expert annotation                    | MRR, Recall@k, nDCG@k computable for every commit                      |
| 2 | **Automated evaluation pipeline** | `evaluate_retrieval.py` script that computes MRR, Recall@20, nDCG@10, Precision@5             | Regression test in CI fails if MRR < 0.75                              |
| 3 | **Context grounding score**       | Wire cosine-similarity grounding check into orchestrator `generate` node                      | Grounding score logged on every response; <0.4 triggers "I don't know" |
| 4 | **Token optimizer integration**   | Integrate `TokenOptimizer` into `build_context` (token-aware truncation) and default pipeline | Per-query token usage reduced by 25-40%                                |
| 5 | **Dynamic top-k retrieval**       | SLM classifies query complexity → adjusts `MAX_CHUNKS_RETRIEVAL` dynamically                  | 30% fewer tokens for simple queries                                    |
| 6 | **vLLM prefix caching**           | Enable `--enable-prefix-caching` for repeated system prompts                                  | Eliminate system prompt token cost after first request in session      |
| 7 | **Consistent error handling**     | Define custom exception hierarchy (`RAGError`, `RetrievalError`, `LLMError`, etc.)            | All catch blocks use specific exceptions                               |
| 8 | **Readiness/liveness probes**     | Add `/v1/health/live` and `/v1/health/ready` endpoints                                        | Docker/K8s health checks work correctly                                |
| 9 | **Dependency scanning**           | Integrate `pip-audit` or `safety` into CI pipeline                                            | CI fails on critical CVEs                                              |

---

## Phase 4: Security & Multi-Tenancy ✅

**Theme:** Make the system safe for multi-user corporate deployment.

**Status:** Complete

### Features

| #  | Feature                                | Description                                                                    | Success Criteria                                                 |
|----|----------------------------------------|--------------------------------------------------------------------------------|------------------------------------------------------------------|
| 1  | **JWT authentication**                 | Keycloak integration for SSO; validate JWT on all endpoints                    | Unauthenticated requests return 401                              |
| 2  | **RBAC implementation**                | Role-based access: admin, expert, user, read-only                              | Users see only authorized documents; experts can submit feedback |
| 3  | **User data isolation**                | Per-user/per-group Qdrant filtering by namespace                               | User A cannot retrieve User B's private documents                |
| 4  | **Input sanitization**                 | Content-length limits, SQL/DQL injection protection in query params            | OWASP Top-10 injection tests pass                                |
| 5  | **Audit logging**                      | Authenticated request logging with user identity, action, timestamp            | Complete audit trail for compliance                              |
| 6  | **HTTPS/TLS termination**              | Documented nginx/HAProxy reverse proxy config with TLS                         | All traffic encrypted in transit                                 |
| 7  | **Chunker quality metrics**            | Compute semantic coherence, boundary precision, overlap ratio during ETL       | Metrics logged per ETL run; alert if coherence < 0.70            |
| 8  | **Log rotation**                       | logrotate config for HITL JSONL logs and proxy logs                            | Logs rotate at 100MB, keep 7 days                                |
| 9  | **A/B test harness**                   | Framework to compare pipeline variants (LangGraph on/off, different rerankers) | Statistically significant quality comparison in < 500 queries    |
| 10 | **Integration test coverage for auth** | Tests for all RBAC scenarios                                                   | 100% of auth paths covered                                       |

---

## Phase 5: Multi-Modal RAG ✅

**Theme:** Expand beyond text to images, diagrams, and code.

**Status:** Complete

### Features

| # | Feature                            | Description                                                          | Success Criteria                                                |
|---|------------------------------------|----------------------------------------------------------------------|-----------------------------------------------------------------|
| 1 | **Image embedding & retrieval**    | CLIP/BLIP integration for diagram and screenshot indexing            | "Find architecture diagram for service X" returns correct image |
| 2 | **Code-aware chunking**            | AST-aware splitting for Python/JS/Java; function/class-level chunks  | Code search matches function signatures, not just comments      |
| 3 | **Table extraction**               | Parse Confluence/Jira tables into structured representations         | "Show me the performance benchmarks table" returns tabular data |
| 4 | **Multi-modal context assembly**   | Mix text + image + code in LLM context                               | LLM handles interleaved content without confusion               |
| 5 | **HITL feedback loop closure**     | Use expert corrections to fine-tune reranker on domain data          | MRR improvement of ≥5% after 500 corrections                    |
| 6 | **ColBERT late interaction**       | Enable bge-m3 ColBERT multi-vectors for maximum relevance            | Recall@20 improvement of ≥3% over dense+sparse alone            |
| 7 | **Automated cold storage cleanup** | TTL-based Parquet version pruning; keep last 5 versions per document | Cold storage stays under 2× hot storage size                    |

---

## Phase 6: Real-Time Indexing & Streaming ✅

**Theme:** Eliminate ETL latency with streaming ingestion.

**Status:** Complete

### Features

| # | Feature                      | Description                                                                    | Success Criteria                                      |
|---|------------------------------|--------------------------------------------------------------------------------|-------------------------------------------------------|
| 1 | **Webhook-driven ingestion** | Confluence/GitLab webhooks trigger incremental indexing via Redis Streams      | New document searchable within 30 seconds of publish  |
| 2 | **Streaming ETL pipeline**   | Redis Streams consumer groups replace batch scheduler for real-time processing | Pipeline processes events within 5 seconds of arrival |
| 3 | **Live Qdrant upserts**      | Atomic chunk-level updates without full reindexing                             | Zero downtime during document updates                 |
| 4 | **Streaming LLM generation** | SSE streaming optimized: connection pooling, chunked transfer encoding         | TTFT < 1s for cached contexts                         |
| 5 | **Model warm-up endpoint**   | `POST /v1/admin/warmup` pre-loads embedder, reranker, and SLM                  | First request latency equals subsequent requests      |
| 6 | **Response compression**     | gzip/brotli middleware via Starlette `GZipMiddleware`                          | 60%+ reduction in response body size                  |

---

## Phase 7: Production Hardening ✅

**Theme:** Meet all production readiness checklist items.

**Status:** Complete

### Features

| #  | Feature                       | Description                                                                 | Success Criteria                            |
|----|-------------------------------|-----------------------------------------------------------------------------|---------------------------------------------|
| 1  | **E2E test suite**            | Full-stack tests against live Qdrant/Neo4j/LLM in CI                        | All critical paths tested end-to-end        |
| 2  | **Performance benchmarks**    | Load testing at 10/50/100 concurrent users                                  | p95 < 5s at 50 concurrent users             |
| 3  | **Chaos/resilience testing**  | Service failure simulation, network partitions, resource exhaustion         | System degrades gracefully in all scenarios |
| 4  | **Multi-AZ/HA deployment**    | Qdrant replication, Neo4j cluster, Redis Sentinel                           | Zero-downtime single-node failure           |
| 5  | **Kubernetes deployment**     | Helm chart with HPA, probes, config maps, secrets                           | Production-grade K8s deployment             |
| 6  | **Backup automation**         | Automated Qdrant snapshots, Neo4j dumps, Redis RDB to S3/MinIO              | RPO < 1 hour, RTO < 30 minutes              |
| 7  | **Disaster recovery runbook** | Step-by-step procedures for all failure scenarios                           | DR drill completes in < 2 hours             |
| 8  | **Grafana dashboards**        | Pre-built dashboard JSON for latency, errors, cache hits, retrieval quality | All key metrics visualized                  |
| 9  | **Prometheus alert rules**    | Alerts for latency, error rate, cache hit ratio, disk/memory pressure       | On-call team receives actionable alerts     |
| 10 | **SLI/SLO definitions**       | Formal objectives: 99.5% availability, p95 < 5s, error rate < 1%            | SLO compliance dashboard                    |
| 11 | **Zero-downtime deployment**  | Rolling updates with health-check gating                                    | No 5xx errors during deployment             |

---

## Phase 8: Self-Correcting RAG ✅

**Theme:** Achieve full self-correction with agentic tools and multi-language support.

**Status:** Complete

### Features

| # | Feature                                 | Description                                                                      | Success Criteria                                                          |
|---|-----------------------------------------|----------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| 1 | **HyDE query expansion**                | Generate hypothetical documents from queries for improved sparse retrieval       | Recall improvement of 10%+ for technical queries                          |
| 2 | **CRAG evaluator**                      | Multi-factor retrieval quality assessment with configurable action routing       | Confidence score maps correctly to action: USE, REWRITE, EXPAND, FALLBACK |
| 3 | **Self-reflection loops**               | Post-generation critique step: LLM re-reads own answer against retrieved context | Self-reflection score correlates with expert feedback                     |
| 4 | **Hallucination detection & grounding** | NLI-based answer verification: cosine similarity + entailment classification     | Hallucination rate < 5% across all query types                            |
| 5 | **Corrective re-generation**            | Low-confidence answers trigger re-generation with expanded context               | 90% of initially low-confidence answers improve after re-generation       |
| 6 | **Agentic tool calling**                | Live queries to Confluence/Jira/GitLab APIs via function calling                 | Tool-call success rate > 95%                                              |
| 7 | **Multi-language support**              | Full i18n: response generation in RU, EN, DE, FR, ZH                             | Cross-lingual MRR > 0.75 for all supported languages                      |
| 8 | **LLMLingua compression**               | Token-level prompt compression for context optimization                          | 2-5x compression ratio with < 5% information loss                         |
| 9 | **LongContextReorder**                  | Re-rank documents with significant content at edges                              | nDCG improvement of 5%+ for long-context documents                        |

---

## Beyond Phases (v2.0) ✅

These items were originally in Future Horizons and have been completed:

| Feature                                                                                                                                                                 | Status     | Tests |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------|-------|
| **Model Evolution** — LoRA/QLoRA fine-tuning, EvalGate CI/CD gating, CanaryController, MLflow tracking, MinIO artifacts                                                 | ✅ Complete | 277   |
| **Agentic Tools Expansion** — Custom tool SDK, `@tool` decorator, `ToolBuilder`, `ToolContext`, YAML/JSON declarative tools, OpenAPI auto-discovery, parallel execution | ✅ Complete | —     |
| **MCP Server** — Model Context Protocol for OpenCode/Claude Desktop integration, STDIO + Streamable HTTP transports                                                     | ✅ Complete | 56    |
| **Federated RAG** — Multi-silo federated RAG with fan-out, RRF merge, privacy-preserving aggregation                                                                    | ✅ Complete | —     |

---

## In Progress

These items are actively being worked on:

| Item                           | Description                                                              | Status         |
|--------------------------------|--------------------------------------------------------------------------|----------------|
| **Documentation improvements** | Updating guides, ADRs, and operational docs to reflect v2.0 capabilities | 🔄 In Progress |
| **Code quality improvements**  | Linting cleanup, type annotation coverage, dead code removal             | 🔄 In Progress |
| **Test coverage improvements** | Expanding unit test coverage for edge cases and error paths              | 🔄 In Progress |

---

## Future Horizons

These items remain planned for future development:

| Horizon   | Theme                             | Ideas                                                                                                     |
|-----------|-----------------------------------|-----------------------------------------------------------------------------------------------------------|
| Mid-term  | **Java/Quarkus Migration**        | Migrate proxy layer from FastAPI to Quarkus for enterprise Java ecosystem integration                     |
| Mid-term  | **Advanced Multi-Modal**          | Video/audio content indexing; OCR pipeline for scanned documents; diagram understanding with visual QA    |
| Long-term | **Autonomous Knowledge Curation** | Automated knowledge gap detection; proactive document update recommendations; knowledge freshness scoring |
| Long-term | **Federated Learning**            | Privacy-preserving model training across distributed knowledge silos without centralizing data            |

---

## Phased Approach Summary

```
Phase 1  ████████████ Core Infrastructure              ✅ COMPLETE
Phase 2  ████████████ Self-Improving RAG                ✅ COMPLETE
Phase 3  ████████████ Token Optimization & Quality       ✅ COMPLETE
Phase 4  ████████████ Security & Multi-Tenancy           ✅ COMPLETE
Phase 5  ████████████ Multi-Modal RAG                   ✅ COMPLETE
Phase 6  ████████████ Real-Time Indexing & Streaming     ✅ COMPLETE
Phase 7  ████████████ Production Hardening               ✅ COMPLETE
Phase 8  ████████████ Self-Correcting RAG                ✅ COMPLETE
v2.0     ████████████ Model Evolution, MCP, Federated    ✅ COMPLETE
Future   ░░░░░░░░░░░░ Java Migration, Advanced Multi-Modal, Autonomous Curation
```

Each phase builds on the previous one, with features designed to compose incrementally. The system is designed to run in
simple RAG mode (Phase 1 only) or with any combination of advanced features enabled via configuration flags.
