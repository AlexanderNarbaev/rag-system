# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-06-26

### Added
- Production hardening: E2E test suite against live services
- Performance benchmarks at 10/50/100 concurrent users (p95 < 5s)
- Chaos/resilience testing with graceful degradation verification
- Kubernetes Helm chart with HPA, probes, config maps, secrets
- Grafana dashboards: overview, retrieval quality, infrastructure
- Prometheus alert rules (critical, warning, info severity levels)
- SLI/SLO definitions: 99.5% availability, p95 < 5s, error rate < 1%
- Error budget tracking and SLO compliance dashboard
- HA deployment: Qdrant replication, Neo4j cluster, Redis Sentinel
- Backup automation: Qdrant snapshots, Neo4j dumps, Redis RDB → S3/MinIO
- Disaster recovery runbook with step-by-step procedures for all failure scenarios
- Graceful shutdown and zero-downtime rolling deployment
- 1321 tests, 100% pass rate

## [0.6.0] — 2026-06-26

### Added
- Streaming ETL pipeline via Redis Streams (4 consumer groups, <5s end-to-end latency)
- Webhook-driven ingestion for Confluence and GitLab (HMAC-SHA256 verification)
- Live Qdrant upserts with atomic chunk-level updates (zero-downtime index updates)
- Model warm-up endpoint (`POST /v1/admin/warmup`) with startup auto-warm
- SSE TTFT optimization: connection pooling, chunked transfer, reduced buffering
- Response compression middleware: gzip/brotli with configurable level
- Dead letter queue for failed streaming ETL events (max 3 retries)
- Prometheus `rag_warmup_completed` gauge metric

### Changed
- Webhook receiver validates signatures on all configured sources
- Consumer lag monitoring via `XPENDING` for stream health checks

## [0.5.0] — 2026-06-26

### Added
- Multi-modal RAG: image embedding and retrieval with CLIP/BLIP integration
- Code-aware chunking: AST-based splitting for Python, JavaScript, Java
- Table extraction from Confluence/Jira into structured representations
- Multi-modal context assembly: text + images + code in LLM context
- ColBERT late interaction via bge-m3 multi-vectors (Recall@20 +3% improvement)
- Automated cold storage cleanup: TTL-based Parquet version pruning
- HITL feedback loop closure: reranker fine-tuning from expert corrections

## [0.4.0] — 2026-06-26

### Added
- JWT authentication with token generation, verification, and refresh endpoints
- RBAC implementation: admin, expert, user, read-only roles
- User data isolation: per-user/per-group Qdrant namespace filtering
- Input sanitization: content-length limits, SQL/DQL injection protection
- Audit logging: authenticated request logging with user identity and timestamps
- HTTPS/TLS termination documentation (nginx/HAProxy reverse proxy config)
- Chunker quality metrics: semantic coherence, boundary precision, overlap ratio
- Log rotation configuration (logrotate for HITL JSONL and proxy logs)
- A/B test harness for pipeline variant comparison
- Integration test coverage for all RBAC/auth scenarios

## [0.3.0] — 2026-06-26

### Added
- Retrieval evaluation dataset: 200+ labeled query-document pairs
- Automated evaluation pipeline: MRR, Recall@k, nDCG, Precision@k metrics
- Context grounding score via cosine-similarity check in orchestrator
- Token optimizer integration into context builder (25-40% token reduction)
- Dynamic top-k retrieval: SLM classifies query complexity, adjusts retrieval depth
- vLLM prefix caching for repeated system prompts
- Consistent error handling: custom exception hierarchy (RAGError, RetrievalError, LLMError)
- Readiness/liveness probe endpoints (`/v1/health/live`, `/v1/health/ready`)
- Dependency vulnerability scanning (pip-audit integration in CI)

### Fixed
- 21 failing tests resolved (assertion mismatches, dependency issues)

## [0.2.0] — 2026-06-26

### Added
- Confidence scoring: context sufficiency, context-to-answer ratio, uncertainty phrase detection
- Active feedback via `/v1/feedback` endpoint with `rag_feedback_id` in all responses
- VERIFY_CASCADE routing in LangGraph orchestrator for low-confidence answer recovery
- Self-enrichment: positive feedback with corrections indexed back into Qdrant as Q&A pairs
- Admin alerts for low-confidence answers beyond recovery loop limit
- Response metadata: `rag_confidence` and `rag_feedback_id` in streaming and non-streaming responses

## [0.1.0] — 2026-06-26

### Added
- Initial release: core RAG infrastructure
- Hybrid retrieval (dense + sparse) with RRF fusion via Qdrant
- Cross-encoder reranking with MiniLM-L-6-v2
- Content-addressable chunk versioning (SHA-256) with hot/cold storage
- Dual-LLM architecture: SLM for routing + LLM for generation
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
- Cross-encoder reranker fine-tuning from HITL feedback
- Multi-provider LLM adapter: vLLM, llama.cpp, Anthropic, Ollama, Generic REST
- Tool/function calling support across all providers
- MCP server for IDE integration (OpenCode, Claude Desktop)
- 7 Architecture Decision Records, 4 C4 diagrams, 8 design guides
- 1248 tests passing (100% pass rate)

[1.0.0]: https://github.com/AlexanderNarbaev/rag-system/releases/tag/v1.0.0
[0.6.0]: https://github.com/AlexanderNarbaev/rag-system/releases/tag/v0.6.0
[0.5.0]: https://github.com/AlexanderNarbaev/rag-system/releases/tag/v0.5.0
[0.4.0]: https://github.com/AlexanderNarbaev/rag-system/releases/tag/v0.4.0
[0.3.0]: https://github.com/AlexanderNarbaev/rag-system/releases/tag/v0.3.0
[0.2.0]: https://github.com/AlexanderNarbaev/rag-system/releases/tag/v0.2.0
[0.1.0]: https://github.com/AlexanderNarbaev/rag-system/releases/tag/v0.1.0
