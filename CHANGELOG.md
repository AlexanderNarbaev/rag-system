# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v2.4.0] - 2026-07-18

This release addresses MEDIUM-priority gaps across Waves 10-13: conversational context,
admin analytics, feedback hardening, i18n, response compression, progressive retrieval,
and vLLM monitoring.

### Added

- **Wave 10 — Conversation & Context**
  - Multi-turn conversational context via `ConversationMemory` with pronoun resolution
    and topic tracking across sessions (FR-140)
  - Session context bounding: configurable TTL (default 30 min) and last-N-turn token
    cap to prevent unbounded growth (FR-141)
  - Admin analytics endpoint (`GET /v1/admin/analytics`) returning 24h/7d/30d time-series
    usage data from Prometheus with JSON fallback (FR-105)
  - Admin data-quality endpoint (`GET /v1/admin/data-quality`) returning per-source
    aggregated quality metrics for Streamlit dashboard consumption (FR-106)
  - Knowledge status field (`rag_knowledge_status`) in every chat response with
    status, chunks_found, chunks_used, and confidence_threshold_met (FR-144)

- **Wave 11 — HITL, i18n & ETL**
  - Feedback available to all authenticated users (not just experts) (FR-79)
  - Feedback rate limiting at 100 submissions per user per hour (FR-81)
  - Confidence-based alerting: low-confidence answers trigger admin alerts
    tracked via `rag_low_confidence_alerts` Prometheus counter (FR-83)
  - Full i18n support: response generation in RU, EN, DE, FR, ZH via `lang`
    parameter (FR-146)
  - ETL extraction quality reports with per-document OCR confidence, table
    extraction metrics, and overall score (FR-60)

- **Wave 12 — Performance & Retrieval**
  - Response compression: gzip level 6 (default) and brotli level 4 (optional)
    with 60%+ JSON reduction and <5ms CPU overhead (FR-172)
  - Progressive context gathering: HyDE expansion → sparse-only → live sources →
    clarification when initial retrieval below `MIN_CHUNKS_THRESHOLD` (FR-143)
  - Shared Redis namespacing: single Redis instance serves both proxy and
    OpenWebUI with non-colliding key prefixes (FR-155)

- **Wave 13 — Monitoring**
  - vLLM prefix cache monitoring: `rag_vllm_prefix_cache_hit_ratio` gauge added
    to Prometheus metrics; actual scraping requires external job targeting vLLM
    `/metrics` endpoint (FR-170, PARTIAL)

### Changed

- Deployment guide updated with WORKERS=1 zero-downtime limitation note and
  recommended workarounds (NFR-D04)

### Fixed

- Compliance requirements document updated: 13 FRs marked MET, 1 marked PARTIAL,
  status summary table added

## [v2.3.0] - 2026-07-17

### Added

- **Streaming ETL pipeline** — new `--mode streaming` extracts→chunks→embeds→indexes
  documents in a single in-memory pass with zero disk storage. Uses generator-based
  document iteration, `asyncio.Semaphore` for embedder backpressure, and atomic
  `live_upsert()` to Qdrant. Configurable via `pipeline.mode` and `streaming.*` settings.
- **Remote embedder with retry + connection pooling** — `RemoteEmbedder` class is a
  drop-in SentenceTransformer replacement that calls OpenAI-compatible `/v1/embeddings`.
  Includes exponential backoff with jitter, configurable retry budget, HTTP connection
  pooling via `requests.Session` + `HTTPAdapter`, async support via `aiohttp`, and
  graceful degradation (`encode_sparse` returns `None`, health tracking).
- **Qdrant UUID v5 point IDs** — all point IDs are now derived from SHA-256 chunk hashes
  via `uuid.uuid5(uuid.NAMESPACE_OID, hash)`, ensuring idempotent upserts: re-indexing
  the same content always produces the same UUID, eliminating duplicate points.
- **Ungrounded generation** — LLM generates answers even when no relevant knowledge is
  found, with a configurable notice prepended to warn users (`ALLOW_UNGROUNDED_GENERATION`,
  `UNGOUNDED_NOTICE`). Prevents empty responses when the knowledge base lacks coverage.
- **Incremental Confluence extraction** — ETL now tracks last extraction state per space
  via WAL checkpoints, enabling delta-only ingestion of new and modified pages without
  re-processing the entire space.

### Changed

- **WAL backend extensibility** — `WAL_BACKEND` now supports `file` (local JSON, default),
  `redis` (per-key checkpoints via Redis), and `proxy` (POST to proxy API). Factory
  function `create_wal_manager()` auto-selects the backend from config or env var.

### Fixed

- **ETL WAL lock fix** — resolved race condition in WAL file locking that caused checkpoint
  corruption under concurrent ETL worker access. Added stale lock recovery (auto-release
  locks older than 10 minutes).

## [v2.2.0] - 2026-07-17

### Changed

- **WAL backend extensibility** — `WAL_BACKEND` now supports `file` (local JSON, default),
  `redis` (per-key checkpoints via Redis), and `proxy` (POST to proxy API). Factory
  function `create_wal_manager()` auto-selects the backend from config or env var.

### Fixed

- **ETL WAL lock fix** — resolved race condition in WAL file locking that caused checkpoint
  corruption under concurrent ETL worker access. Added stale lock recovery (auto-release
  locks older than 10 minutes).

## [v2.1.0] - 2026-07-17

This release completes all 5 waves of the S4-2026 sprint: Foundation Fixes, Quality Push,
Infrastructure, Polish, and Final Validation. See `docs/en/guides/sprint-plan-2026-s4.md`
for the full sprint plan.

### Highlights

- **Progressive retrieval** — multi-stage chunk retrieval with configurable depth
  (`PROGRESSIVE_RETRIEVAL_ENABLED`, `PROGRESSIVE_RETRIEVAL_STAGES`).
- **Admin config API** — `/v1/admin/config` endpoints for runtime configuration management
  without restarts.
- **RBAC by default** — role-based access control now enabled by default alongside
  `AUTH_ENABLED=true` for secure-by-default deployments.
- **Granian migration (ADR-008)** — Proxy ASGI server migrated from uvicorn to granian
  (Rust-based, ~5x faster startup).

### Added

- **Wave 1 — Foundation Fixes**
  - Mypy strict mode: 313→0 errors across 139 source files
  - Pytest collection fixes for MCP server test suites
  - Dependabot PR triage: 7 PRs merged for dependency updates
  - Production bugfixes: Qdrant connection recovery, LLM timeout handling
  - Code quality cleanup: ruff auto-fix from 8,137 issues → 23

- **Wave 2 — Quality Push**
  - Retrieval eval dataset expanded: 20→452 Q&A pairs (+2160%)
  - Coverage raised to 81% (meets 80% threshold)
  - Dependency security audit: 6 packages fixed, 0 HIGH/CRITICAL CVEs
  - Sprint documentation (S3 archived, S4 plan published, ADR indices updated)

- **Wave 3 — Infrastructure**
  - HTTPS/TLS automation for ingress endpoints
  - Secrets rotation automation (kubectl + External Secrets Operator)
  - Database migration framework for SQLite schema evolution
  - K8s Helm chart validation
  - Baseline latency benchmarks

- **Wave 4 — Polish**
  - C4 diagram gaps filled (L1, L2, L3 for remaining components)
  - OpenAPI export automation (CI pipeline integration)
  - ADR-008 POC: granian ASGI server migration from uvicorn
  - OCR/audio/video RAG support (ingestion pipeline)
  - Automated RAG maturity review

- **Wave 5 — Final Validation & Hardening**
  - Full regression suite: 4,340 tests passing (target: 3,000+)
  - Performance benchmarks: latency p50/p95/p99 baselines
  - Final security audit: bandit + trivy + dependabot, zero findings
  - Documentation final pass: all 44 guides updated
  - Sprint retrospective

- **ETL graceful shutdown** — WAL checkpoint on SIGTERM/SIGINT, in-flight task completion,
  Redis consumer group handoff, configurable `SHUTDOWN_TIMEOUT`

### Changed

- **Granian migration (ADR-008)** — Proxy ASGI server migrated from uvicorn to granian
  (Rust-based, ~5x faster startup). Dockerfile, Makefile, and all documentation updated.
- **`AUTH_ENABLED` default** changed from `false` to `true` — authentication is now enabled
  by default for security. Auto-generates `JWT_SECRET` if not provided (with warning).
- **`LOG_FORMAT` default** changed from `"text"` to `"json"` — structured JSON logging
  is now the default for production observability.
- **`GRACEFUL_SHUTDOWN_ENABLED` default** is `true` — clean shutdown with in-flight request
  draining (configurable via `SHUTDOWN_TIMEOUT`, default 30s).
- **`METRICS_ENABLED` default** is `true` — Prometheus metrics exposed by default.

### Fixed

- Qdrant connection recovery after transient network failures
- LLM timeout handling with proper retry backoff
- MCP server test collection errors with missing dependencies
- CI/CD pipeline green across all workflows (CI, Security, Docs)
- Ruff lint errors resolved project-wide
- Mypy strict type checking passes on all 139 source files
- `InMemoryCache` sync methods: removed `asyncio.run()` from running event loop
- Double JSON parsing in `_compute_dense_embedding()` cache retrieval
- ETL WAL corruption recovery and integrity checks
- ETL retry logic with exponential backoff for transient failures

### Security

- `AUTH_ENABLED=true` by default — no unauthorized access on fresh deployments
- Dependency audit: 0 HIGH/CRITICAL CVEs (bandit + trivy + dependabot)
- HTTPS/TLS automation for production deployments
- Secrets rotation automation (kubectl + External Secrets Operator)
- Final security audit passed with zero findings

## [v2.0.0] - 2026-06-26

### Added

- HyDE query expansion (query_enhancer.py)
- CRAG evaluator with action mapping
- Self-reflection module
- NLI hallucination grounding
- Corrective re-generation loops
- Agentic tool calling (live Confluence/Jira/GitLab)
- Multi-language support (RU/EN/DE/FR/ZH)
- Cross-lingual retrieval benchmarks
- Live source connectors (direct API integration)
- Self-reflection graph patterns (Neo4j)
- LLMLingua compression integration
- LongContextReorder integration
- MCP server for OpenCode/Claude Desktop integration
- Agentic Tools SDK (@tool decorator, ToolBuilder, ToolContext)
- Declarative tool definitions (YAML/JSON)
- OpenAPI auto-discovery for tool registration
- Model evolution pipeline (LoRA/QLoRA fine-tuning, EvalGate, canary deployment)

## [v1.0.0] - 2026-03-01

### Added

- OpenAI-compatible proxy API
- Qdrant hybrid search (dense + sparse + RRF)
- Cross-encoder reranking (MiniLM-L-6-v2)
- Neo4j graph expansion
- JWT authentication with RBAC
- Redis caching (embedding + response)
- Streamlit expert dashboard (HITL)
- Prometheus metrics and Grafana dashboards
- Docker Compose deployment
- Comprehensive test suite
- ADR documentation (10+ records)
- Performance and security guides
