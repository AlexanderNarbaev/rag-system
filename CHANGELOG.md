# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v2.2.0] - 2026-07-17

### Added

- **Ungrounded generation** — LLM generates answers even when no relevant knowledge is found,
  with a configurable notice prepended to warn users (`ALLOW_UNGROUNDED_GENERATION`,
  `UNGOUNDED_NOTICE`). Prevents empty responses when the knowledge base lacks coverage.
- **Incremental Confluence extraction** — ETL now tracks last extraction state per space,
  enabling delta-only ingestion of new and modified pages without re-processing the entire space.
- **WAL checkpoint WAL backend** — `WAL_BACKEND` supports `file` (local JSON), `redis`, and
  `proxy` (POST to proxy API for centralized checkpoint management).

### Fixed

- **ETL WAL lock fix** — resolved race condition in WAL file locking that caused checkpoint
  corruption under concurrent ETL worker access.

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
