# Development Roadmap

**Last Updated:** 2026-06-22
**Current Version:** v0.1.0

---

## Version History

### v0.1.0 — Core Infrastructure (Current)

**Released:** June 2026
**Status:** ✅ Complete

**Features delivered:**
- Hybrid retrieval (dense + sparse) with RRF fusion via Qdrant
- Cross-encoder reranking with MiniLM-L-6-v2
- Content-addressable chunk versioning (SHA-256) with hot/cold storage
- Dual-LLM architecture: SLM (lightweight) for routing + LLM (full-scale) for generation
- LangGraph agentic orchestrator (7-node state graph, optional)
- OpenAI-compatible proxy API (`/v1/chat/completions`, `/v1/models`, `/v1/health`)
- Redis-backed multi-tier cache (embeddings, rerank, responses)
- Human-in-the-loop feedback dashboard (Streamlit)
- WAL-based incremental ETL with checkpoint recovery
- GraphRAG via Neo4j entity extraction and multi-hop traversal
- Prometheus metrics and structured logging
- Rate limiting (token bucket per IP)
- Graceful degradation design for all components
- Air-gapped deployment support (models pre-downloaded)
- **546 designed / 505 collected / 483 passing tests** (96% pass rate)
- 7 Architecture Decision Records, 4 C4 diagrams, 8 design guides

**Known issues:**
- 21 test failures (mostly assertion drift after code changes)
- 1 test collection error (`test_extractors.py` — missing `requests` dependency)
- No retrieval quality evaluation dataset or metrics
- No end-to-end tests with real services
- 40+ mypy type errors in proxy modules
- MCP server has 46 tests but is not referenced in README
- `USE_LANGGRAPH=false` by default; agentic path is opt-in

---

### v0.2 — Token Optimization & Quality Foundations

**Target:** Q3 2026
**Status:** 🔵 Planning

**Theme:** Reduce token costs by 40% and establish measurable quality baselines.

#### Features

| # | Feature | Description | Success Criteria |
|---|---------|-------------|------------------|
| 1 | **Retrieval evaluation dataset** | Build 200+ query–document labeled pairs from HITL logs + expert annotation | MRR, Recall@k, nDCG@k computable for every commit |
| 2 | **Automated evaluation pipeline** | `evaluate_retrieval.py` script that computes MRR, Recall@20, nDCG@10, Precision@5 | Regression test in CI fails if MRR < 0.75 |
| 3 | **Context grounding score** | Wire cosine-similarity grounding check into orchestrator `generate` node | Grounding score logged on every response; <0.4 triggers "I don't know" |
| 4 | **Token optimizer integration** | Integrate `TokenOptimizer` into `build_context` (token-aware truncation) and default pipeline | Per-query token usage reduced by 25-40% |
| 5 | **Dynamic top-k retrieval** | SLM classifies query complexity → adjusts `MAX_CHUNKS_RETRIEVAL` dynamically | 30% fewer tokens for simple queries |
| 6 | **vLLM prefix caching** | Enable `--enable-prefix-caching` for repeated system prompts | Eliminate system prompt token cost after first request in session |
| 7 | **Consistent error handling** | Define custom exception hierarchy (`RAGError`, `RetrievalError`, `LLMError`, etc.) | All catch blocks use specific exceptions |
| 8 | **Readiness/liveness probes** | Add `/v1/health/live` and `/v1/health/ready` endpoints | Docker/K8s health checks work correctly |
| 9 | **Fix 21 failing tests** | Resolve assertion mismatches and test dependency issues | 505/505 tests pass (100%) |
| 10 | **Dependency scanning** | Integrate `pip-audit` or `safety` into CI pipeline | CI fails on critical CVEs |

#### Dependencies
- HITL logs must have accumulated enough interaction data for evaluation dataset
- Expert availability for annotation (~10 hours)
- `token_optimizer.py` already implemented; needs wiring into pipeline

#### Effort Estimate
- **Engineering:** 15-20 person-days
- **Annotation:** 3-5 person-days (domain expert)
- **Total:** ~4 weeks at 1 FTE + part-time expert

---

### v0.3 — Security & Multi-Tenancy

**Target:** Q4 2026
**Status:** ⚪ Planned

**Theme:** Make the system safe for multi-user corporate deployment.

#### Features

| # | Feature | Description | Success Criteria |
|---|---------|-------------|------------------|
| 1 | **JWT authentication** | Keycloak integration for SSO; validate JWT on all endpoints | Unauthenticated requests return 401 |
| 2 | **RBAC implementation** | Role-based access: admin, expert, user, read-only | Users see only authorized documents; experts can submit feedback |
| 3 | **User data isolation** | Per-user/per-group Qdrant filtering by namespace | User A cannot retrieve User B's private documents |
| 4 | **Input sanitization** | Content-length limits, SQL/DQL injection protection in query params | OWASP Top-10 injection tests pass |
| 5 | **Audit logging** | Authenticated request logging with user identity, action, timestamp | Complete audit trail for compliance |
| 6 | **HTTPS/TLS termination** | Documented nginx/HAProxy reverse proxy config with TLS | All traffic encrypted in transit |
| 7 | **Chunker quality metrics** | Compute semantic coherence, boundary precision, overlap ratio during ETL | Metrics logged per ETL run; alert if coherence < 0.70 |
| 8 | **Log rotation** | logrotate config for HITL JSONL logs and proxy logs | Logs rotate at 100MB, keep 7 days |
| 9 | **A/B test harness** | Framework to compare pipeline variants (LangGraph on/off, different rerankers) | Statistically significant quality comparison in < 500 queries |
| 10 | **Integration test coverage for auth** | Tests for all RBAC scenarios | 100% of auth paths covered |

#### Dependencies
- Keycloak instance deployed in corporate environment
- Completion of evaluation dataset from v0.2 (needed for A/B testing)
- Network/security team approval for JWT flow

#### Effort Estimate
- **Engineering:** 25-30 person-days
- **Infrastructure:** 5 person-days (Keycloak setup)
- **Total:** ~6 weeks at 1 FTE

---

### v0.4 — Multi-Modal RAG

**Target:** Q1 2027
**Status:** ⚪ Planned

**Theme:** Expand beyond text to images, diagrams, and code.

#### Features

| # | Feature | Description | Success Criteria |
|---|---------|-------------|------------------|
| 1 | **Image embedding & retrieval** | CLIP/BLIP integration for diagram and screenshot indexing | "Find architecture diagram for service X" returns correct image |
| 2 | **Code-aware chunking** | AST-aware splitting for Python/JS/Java; function/class-level chunks | Code search matches function signatures, not just comments |
| 3 | **Table extraction** | Parse Confluence/Jira tables into structured representations | "Show me the performance benchmarks table" returns tabular data |
| 4 | **Multi-modal context assembly** | Mix text + image + code in LLM context | LLM handles interleaved content without confusion |
| 5 | **HITL feedback loop closure** | Use expert corrections to fine-tune reranker on domain data | MRR improvement of ≥5% after 500 corrections |
| 6 | **ColBERT late interaction** | Enable bge-m3 ColBERT multi-vectors for maximum relevance | Recall@20 improvement of ≥3% over dense+sparse alone |
| 7 | **Automated cold storage cleanup** | TTL-based Parquet version pruning; keep last 5 versions per document | Cold storage stays under 2× hot storage size |

#### Dependencies
- GPU with ≥24GB VRAM for CLIP + ColBERT inference
- At least 500 expert corrections accumulated from HITL
- AST parsers for target languages

#### Effort Estimate
- **Engineering:** 30-35 person-days
- **Model evaluation:** 5 person-days
- **Total:** ~8 weeks at 1 FTE

---

### v0.5 — Real-Time Indexing & Streaming

**Target:** Q2 2027
**Status:** ⚪ Planned

**Theme:** Eliminate ETL latency with streaming ingestion.

#### Features

| # | Feature | Description | Success Criteria |
|---|---------|-------------|------------------|
| 1 | **Webhook-driven ingestion** | Confluence/GitLab webhooks trigger incremental indexing | New document searchable within 30 seconds of publish |
| 2 | **Streaming ETL pipeline** | Kafka/Redis Streams replacing batch scheduler for real-time processing | Pipeline processes events within 5 seconds of arrival |
| 3 | **Live Qdrant upserts** | Atomic chunk-level updates without full reindexing | Zero downtime during document updates |
| 4 | **Streaming LLM generation** | Optimize SSE streaming for lower time-to-first-token | TTFT < 1s for cached contexts |
| 5 | **Model warm-up endpoint** | Pre-load embedder/reranker/LLM into GPU memory on startup | First request latency equals subsequent requests |
| 6 | **Response compression** | gzip/brotli middleware for large responses | 60%+ reduction in response body size |

#### Dependencies
- Message broker infrastructure (Kafka or Redis Streams)
- Webhook configuration on source systems (Confluence, GitLab)
- Network connectivity from source systems to ETL machine

#### Effort Estimate
- **Engineering:** 25-30 person-days
- **Infrastructure:** 5-10 person-days
- **Total:** ~7 weeks at 1 FTE

---

### v1.0 — Production Hardening & GA

**Target:** Q3 2027
**Status:** ⚪ Planned

**Theme:** Meet all production readiness checklist items.

#### Features

| # | Feature | Description | Success Criteria |
|---|---------|-------------|------------------|
| 1 | **E2E test suite** | Full-stack tests against live Qdrant/Neo4j/LLM in CI | All critical paths tested end-to-end |
| 2 | **Performance benchmarks** | Load testing at 10/50/100 concurrent users; latency, throughput, error rate | p95 < 5s at 50 concurrent users |
| 3 | **Chaos/resilience testing** | Service failure simulation, network partitions, resource exhaustion | System degrades gracefully in all scenarios |
| 4 | **Multi-AZ/HA deployment** | Qdrant replication, Neo4j cluster, Redis Sentinel | Zero-downtime single-node failure |
| 5 | **Kubernetes deployment** | Helm chart with HPA, probes, config maps, secrets | Production-grade K8s deployment |
| 6 | **Backup automation** | Automated Qdrant snapshots, Neo4j dumps, Redis RDB to S3/MinIO | RPO < 1 hour, RTO < 30 minutes |
| 7 | **Disaster recovery runbook** | Step-by-step procedures for all failure scenarios | DR drill completes in < 2 hours |
| 8 | **Grafana dashboards** | Pre-built dashboard JSON for latency, errors, cache hits, retrieval quality | All key metrics visualized |
| 9 | **Prometheus alert rules** | Alerts for latency, error rate, cache hit ratio, disk/memory pressure | On-call team receives actionable alerts |
| 10 | **SLI/SLO definitions** | Formal objectives: 99.5% availability, p95 < 5s, error rate < 1% | SLO compliance dashboard |
| 11 | **CHANGELOG.md** | Versioned changelog with breaking changes, features, fixes | Standard keep-a-changelog format |
| 12 | **Zero-downtime deployment** | Rolling updates with health-check gating | No 5xx errors during deployment |

#### Dependencies
- Infrastructure budget for HA (additional Qdrant/Neo4j nodes)
- Monitoring stack (Prometheus + Grafana) deployed
- Completion of v0.2-v0.5 feature set

#### Effort Estimate
- **Engineering:** 30-40 person-days
- **Infrastructure/DevOps:** 15-20 person-days
- **Documentation:** 5 person-days
- **Total:** ~10 weeks at 1 FTE + DevOps support

---

### Beyond v1.0 — Future Horizons

| Horizon | Theme | Ideas |
|---------|-------|-------|
| H1 2028 | **Self-Correcting RAG (Level 5)** | CRAG evaluator, HyDE, self-reflection loops, answer verification, hallucination rate < 5% |
| H1 2028 | **Agentic Tools** | Tool-calling API (Confluence/Jira/GitLab live queries, not just indexed data), function calling |
| H2 2028 | **Multi-Language Expansion** | Beyond RU+EN: DE, FR, ZH; cross-lingual retrieval benchmarks |
| H2 2028 | **Model Evolution** | Migrate to newer model generations; evaluate alternative architectures (Llama, Mistral, etc.); on-prem fine-tuning pipeline |
| 2029+ | **Federated RAG** | Multi-instance search across departments; federated query routing; cross-silo retrieval |

---

## Summary Timeline

```
2026 Q2  ████████████ v0.1 — Core Infrastructure (COMPLETE)
2026 Q3  ░░░░░░░░░░░░ v0.2 — Token Optimization + Quality Foundations
2026 Q4  ░░░░░░░░░░░░ v0.3 — Security + RBAC + Multi-Tenancy
2027 Q1  ░░░░░░░░░░░░ v0.4 — Multi-Modal RAG (Images, Code, Tables)
2027 Q2  ░░░░░░░░░░░░ v0.5 — Real-Time Indexing + Streaming
2027 Q3  ░░░░░░░░░░░░ v1.0 — Production Hardening + GA
2028+   ░░░░░░░░░░░░ v2.0 — Self-Correcting, Agentic Tools, Federated
```

**Total estimated effort to v1.0:** ~40 weeks at 1 FTE + part-time domain expert and DevOps support.
