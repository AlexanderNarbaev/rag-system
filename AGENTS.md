# AGENTS.md — RAG System

## Project Overview

Corporate RAG Knowledge Assistant — an OpenAI-compatible proxy with an ETL pipeline that ingests Confluence, Jira,
GitLab, documents, and chat history into Qdrant (vector DB) + Neo4j (knowledge graph), and serves answers via a
configurable LLM backend (vLLM, llama.cpp, or any OpenAI-compatible endpoint). Designed for air-gapped enterprise
environments: it runs fully offline with no external API calls at runtime.

- **Version**: 2.0.0 (`pyproject.toml`)
- **Python**: >= 3.11 (mypy targets 3.12)
- **License**: MIT
- **Docs site**: MkDocs Material (`mkdocs.yml`), published to GitHub Pages

## Language

English for code and comments. The system supports full i18n — documentation is maintained in both English
(`docs/en/`) and Russian (`docs/ru/`) with a language switcher, and the two trees must stay synchronized.

## Architecture

Six-layer system plus supporting services, with multi-provider LLM backend support:

1. **ETL Layer** — data extraction, chunking, embedding, indexing (runs on a separate machine)
2. **Proxy Layer** — FastAPI app with OpenAI-compatible API, hybrid retrieval, reranking, multi-provider LLM routing
   (vLLM, llama.cpp, or any OpenAI-compatible endpoint)
3. **HITL Layer** — Streamlit expert dashboard for feedback and quality control
4. **MCP Server** — Model Context Protocol server exposing RAG tools to MCP-compatible clients (OpenCode, Claude
   Desktop)
5. **Model Evolution** — LoRA/QLoRA fine-tuning pipeline for SLM, LLM, and Reranker; MLflow experiment tracking; MinIO
   artifact storage; EvalGate CI/CD quality gating; AdapterManager hot-reload; CanaryController gradual rollout
6. **Agentic Tools Expansion** — custom tool SDK for user-defined tools; declarative tool definitions; OpenAPI
   auto-discovery; parallel tool execution with dependency resolution

## Key Architectural Principles

1. **Air-gapped first** — all models pre-downloaded, no external API calls at runtime. The system must function fully
   offline.
2. **Graceful degradation** — every component can fail independently: Neo4j unavailable → skip graph expansion.
   Reranker OOM → use raw hybrid scores. Redis down → fall back to in-memory cache. The proxy never crashes on
   component failure.
3. **Incremental by default** — WAL-based ETL checkpointing. SHA-256 content-addressable chunks. Only changed documents
   are reindexed.
4. **OpenAI compatibility** — the proxy is a drop-in replacement for any OpenAI client. Extensions (`rag_version`,
   `rag_force_refresh`, etc.) are silently ignored by standard clients.
5. **Dual-model routing** — lightweight SLM for fast preprocessing (intent classification, query decomposition, entity
   extraction); full-scale LLM for heavy generation. Keeps latency low for routing tasks.
6. **Multi-provider support** — pluggable backend adapters via the provider layer allow swapping between vLLM,
   llama.cpp, and any OpenAI-compatible API without changing orchestration logic.
7. **Optional complexity** — LangGraph orchestrator, Neo4j graph expansion, and Redis caching are all optional. The
   system runs in simple RAG mode by default.
8. **Token economy** — every token counts. Token optimizer provides BPE-aware counting, compression strategies, and
   smart budget allocation.

## Project Structure

```
rag-system/
├── etl/                              # ETL pipeline (standalone)
│   ├── extractors/                   # confluence.py, jira.py, gitlab.py, books.py, docs.py, chats.py
│   ├── chunker/                      # semantic chunking, hash-based versioning
│   ├── graph_builder/                # entity extraction, Neo4j loader, schema.yaml, community detection
│   ├── indexer/                      # Qdrant hybrid indexing, live vector lake, WAL manager
│   ├── scheduler/                    # run_etl.py (orchestrates full pipeline, batch/streaming modes)
│   ├── config/                       # etl_config.yaml
│   ├── Dockerfile.etl
│   ├── docker-compose.yml
│   └── requirements_etl.txt
├── proxy/                            # RAG proxy (Dockerized)
│   ├── app/
│   │   ├── main.py                   # FastAPI entry point (30+ endpoints: chat, models, health, auth, widget,
│   │   │                             #   feedback, admin, tools, files, model evolution)
│   │   ├── api/                      # API endpoint handlers
│   │   │   ├── chat.py               # /v1/chat/completions — streaming + non-streaming
│   │   │   ├── auth_endpoints.py     # /v1/auth/* — login, register, refresh, logout, me
│   │   │   ├── health.py             # /v1/health, /v1/health/live, /v1/health/ready
│   │   │   ├── admin.py              # /v1/admin/* — model training, promotion, canary, knowledge bases
│   │   │   ├── feedback.py           # /v1/feedback — expert feedback submission
│   │   │   ├── files.py              # /v1/files/* — file upload/download via MinIO
│   │   │   ├── tools.py              # /v1/tools — list/get tools with filters
│   │   │   ├── widget.py             # /v1/widget — embeddable chat widget HTML/JS
│   │   │   └── metrics.py            # /metrics — Prometheus endpoint
│   │   ├── auth/                     # Authentication & authorization
│   │   │   ├── jwt.py                # JWT token generation (access + refresh pairs)
│   │   │   ├── rbac.py               # Role-based access control (admin/expert/user/read-only)
│   │   │   ├── user_db.py            # SQLite user database with bcrypt + refresh token management
│   │   │   ├── ldap.py               # LDAP/AD authentication integration
│   │   │   └── api_keys.py           # API key management and validation
│   │   ├── core/                     # RAG pipeline logic
│   │   │   ├── retrieval.py          # Qdrant hybrid search (dense+sparse RRF) + graph expansion
│   │   │   ├── rerank.py             # Cross-encoder reranker (BAAI/bge-reranker-v2-m3, 8192-token context)
│   │   │   ├── confidence.py         # Confidence scoring: heuristics + optional SLM verification
│   │   │   ├── grounding.py          # NLI-based answer grounding (cosine + entailment)
│   │   │   ├── hallucination.py      # Hallucination detection and scoring
│   │   │   ├── evaluation.py         # Retrieval eval pipeline: MRR, Recall@k, nDCG, Precision@k
│   │   │   ├── retrieval_evaluator.py # CRAG-style retrieval quality assessment
│   │   │   ├── hyde.py               # Hypothetical Document Embeddings for query expansion
│   │   │   ├── query_enhancer.py     # Query rewriting, expansion, and decomposition
│   │   │   ├── token_optimizer.py    # BPE-aware token counting, compression, budget allocation
│   │   │   ├── enricher.py           # Self-enrichment: feedback Q&A → chunk → Qdrant
│   │   │   ├── hitl.py               # Human-in-the-loop: async interaction logging, feedback collection
│   │   │   ├── live_sources.py       # Live Confluence/Jira/GitLab API queries
│   │   │   ├── context/              # Context assembly (builder, compression, versioning)
│   │   │   └── orchestrator/         # LangGraph agentic pipeline (11-node state graph + node impls)
│   │   ├── llm/                      # LLM routing & provider abstraction
│   │   │   ├── router.py             # Async LLM adapter (streaming + non-streaming)
│   │   │   ├── slm.py                # SLM: intent classification, query decomposition, entity extraction
│   │   │   ├── remote_services.py    # Remote embedder/reranker clients with local fallback
│   │   │   └── provider/             # Provider adapters (base router; OpenAI/Anthropic/Ollama/Generic
│   │   │                             #   adapters all live in openai.py)
│   │   ├── tools/                    # Agentic Tools Expansion
│   │   │   ├── sdk.py                # Custom tool SDK: @tool decorator, ToolBuilder, ToolContext
│   │   │   ├── definition.py         # ToolDefinition model and schemas
│   │   │   ├── registry.py           # Central tool registry
│   │   │   ├── declarative.py        # YAML/JSON declarative tool definitions
│   │   │   ├── builtin.py            # Built-in tool implementations
│   │   │   ├── orchestrator.py       # Parallel tool execution with dependency resolution
│   │   │   ├── security.py           # Tool security validation and sandboxing
│   │   │   ├── audit.py              # Tool usage auditing and logging
│   │   │   ├── metrics.py            # Tool execution metrics and monitoring
│   │   │   ├── errors.py             # Tool-specific error hierarchy
│   │   │   └── openapi/              # OpenAPI auto-discovery (discovery.py, converter.py)
│   │   ├── db/                       # Database migrations (SQLite users, API keys, Neo4j schema)
│   │   ├── domain/                   # Domain models
│   │   ├── shared/                   # Shared utilities & middleware
│   │   │   ├── config.py             # Environment-based configuration (all settings)
│   │   │   ├── cache.py              # Redis + in-memory multi-tier cache
│   │   │   ├── exceptions.py         # RAGError, RetrievalError, LLMError, SecurityError hierarchy
│   │   │   ├── middleware.py         # Request ID, correlation ID, logging, CORS middleware
│   │   │   ├── logging.py            # Structured logging (text/JSON), secret masking
│   │   │   ├── metrics.py            # Prometheus metric definitions
│   │   │   ├── rate_limiter.py       # Token bucket rate limiting middleware (per IP)
│   │   │   ├── circuit_breaker.py    # Circuit breaker for downstream service calls
│   │   │   ├── security.py           # Input validation (InputValidator)
│   │   │   ├── access_control.py     # Unified access control logic
│   │   │   ├── audit.py              # Audit event logging
│   │   │   ├── ab_test.py            # A/B test harness for pipeline variants
│   │   │   ├── i18n.py               # Internationalization support
│   │   │   ├── tracing.py            # Distributed tracing (OpenTelemetry)
│   │   │   ├── warmup.py             # Application warmup/cache priming
│   │   │   ├── memory_manager.py     # Memory management for long-running processes
│   │   │   ├── minio_client.py       # MinIO/S3 object storage client
│   │   │   └── utils.py              # Shared utilities: token counting, hashing, masking
│   │   └── model_evolution/          # Fine-tuning pipeline (trainer registry, SLM/LLM/Reranker trainers,
│   │                                 #   adapter manager, canary controller, model registry, EvalGate,
│   │                                 #   MLflow tracking, data processing, NLI evaluation, env profiles)
│   ├── .env                          # Configuration (create from .env.example before first run)
│   ├── Dockerfile
│   ├── docker-compose.yml            # Qdrant + Redis + Neo4j + MinIO + Proxy
│   ├── docker-compose.ha.yml         # HA variant (nginx, redis-sentinel)
│   └── requirements_proxy.txt        # plus requirements_proxy_gpu.txt for GPU deployments
├── mcp_server/                       # MCP server (FastMCP: STDIO + Streamable HTTP)
├── dashboard/                        # Streamlit expert review dashboard
├── tui/                              # Terminal UI for RAG interaction
├── model_evolution_service/          # Standalone model evolution service (API, trainers, deployment).
│   │                                 #   KNOWN TECH DEBT: largely duplicates proxy/app/model_evolution/
│   │                                 #   (byte-identical canary_controller/artifact_store/model_registry,
│   │                                 #   near-identical trainers). proxy/app/model_evolution/ is the
│   │                                 #   source of truth — port changes to the service tree manually.
├── scripts/                          # Utility scripts
│   ├── init_collections.py           # Initialize Qdrant collections
│   ├── download_models_offline.py    # Pre-download models for air-gapped env
│   ├── deploy.sh                     # Deploy script (dev/prod)
│   ├── setup_wizard.py               # Interactive configuration wizard
│   ├── benchmark.py / run_benchmarks.py  # Latency benchmarks and baseline comparison
│   ├── export_openapi.py             # Export OpenAPI spec + generate API docs
│   ├── mock_llm_server.py            # Mock LLM for integration/e2e tests
│   └── ops/                          # Operations scripts (backup/restore, health check, status)
├── deploy/                           # Deployment manifests
│   ├── docker/                       # Docker Compose variants (prod, distributed, OpenWebUI)
│   ├── k8s/helm/rag-system/          # Kubernetes Helm chart
│   ├── nginx/                        # Reverse proxy config + cert generation
│   └── haproxy/                      # HAProxy config
├── config/monitoring/                # Prometheus + Grafana configs
├── tests/                            # Test suite (see Testing section)
├── docs/                             # Documentation (EN + RU), MkDocs source
├── requirements-proxy.txt            # Root-level dependency pins (audited by `make audit`)
├── requirements-etl.txt
├── requirements-dev.txt
├── Makefile                          # Primary dev entry point
├── pyproject.toml                    # Ruff, mypy, pytest, coverage configuration
└── setup.sh / install.sh             # Installation scripts
```

## Tech Stack

| Component       | Technology                                                                         | Purpose                                           |
|-----------------|------------------------------------------------------------------------------------|---------------------------------------------------|
| **LLM**         | Any OpenAI-compatible model (e.g., Llama, Mistral, Gemma, Qwen) via vLLM/llama.cpp | Response generation (configurable context length) |
| **SLM**         | Lightweight model (e.g., Llama-3B, Gemma-2B, Qwen-2.5-3B)                          | Query routing, entity extraction (fast path)      |
| **Embeddings**  | BAAI/bge-m3                                                                        | Dense (1024-dim) + sparse (lexical) + ColBERT     |
| **Reranker**    | BAAI/bge-reranker-v2-m3                                                            | Cross-encoder reranking, fine-tuning supported    |
| **Vector DB**   | Qdrant                                                                             | Hybrid search (dense + sparse), RRF fusion        |
| **Graph DB**    | Neo4j                                                                              | Entity relationships, multi-hop traversal         |
| **Cache**       | Redis                                                                              | Embedding cache, rerank results, response cache   |
| **Proxy**       | FastAPI + LangGraph, served by Granian (ASGI)                                      | OpenAI-compatible API, agentic orchestration      |
| **ETL**         | Python, requests, BeautifulSoup, spaCy, sentence-transformers                      | Data extraction, chunking, indexing               |
| **Dashboard**   | Streamlit                                                                          | HITL expert review                                |
| **MCP**         | FastMCP                                                                            | Model Context Protocol server for IDE integration |
| **Auth**        | JWT + bcrypt (SQLite), Keycloak OIDC, LDAP/AD                                      | Corporate SSO, RBAC (4 roles)                     |
| **Infra**       | Kubernetes + Helm                                                                  | Production deployment with HPA, probes            |
| **Backup**      | S3/MinIO                                                                           | Automated snapshots, dumps, RDB backups           |
| **Fine-tuning** | LoRA/QLoRA, MLflow, MinIO                                                          | Model training, tracking, canary deployment       |

## Build, Run, and Test Commands

The `Makefile` is the primary entry point (`make help` lists all targets):

```bash
# ── Setup ──
make install            # Full setup (proxy + ETL) via setup.sh --full
make install-dev        # Setup with dev dependencies (lint, test, typecheck)
make setup              # Create proxy/.env and etl/.env from examples
make wizard             # Interactive configuration wizard

# ── Run ──
make run                # Start proxy locally: granian --interface asgi --port 8080 proxy.app.main:app
make run-dev            # Same, with hot reload
make etl                # Run full ETL pipeline
make etl-run-streaming  # ETL streaming mode with remote embedder
make etl-run-batch      # ETL batch mode
make dashboard          # Streamlit dashboard on :8501
make tui                # Terminal UI
make mcp-server         # MCP server

# ── Tests ──
make test               # All tests
make test-proxy         # Proxy unit tests only
make test-etl           # ETL unit tests only
make test-integration   # Integration tests
make test-performance   # Performance/benchmark tests (marker: benchmark)
make test-e2e           # End-to-end tests (marker: e2e, requires running services)
make test-resilience    # Chaos/resilience tests (marker: chaos)

# ── Code quality ──
make lint               # ruff check .
make format             # ruff format .
make format-check       # Check formatting without changes
make typecheck          # mypy proxy/ etl/
make audit              # pip-audit on requirements-{proxy,etl,dev}.txt
make helm-lint          # Helm chart validation (skips if helm not installed)
make all                # CI pipeline: install → lint → test

# ── Docker & deploy ──
make docker-build       # Build Docker images (proxy/docker-compose.yml)
make docker-up          # Start Qdrant + Redis + Neo4j + MinIO + Proxy
make docker-down
make docker-logs
make deploy             # Deploy dev via scripts/deploy.sh
make deploy-prod        # Deploy prod

# ── Ops ──
make backup             # Back up Qdrant, Neo4j, Redis
make restore            # Restore from latest backups
make health-check       # Comprehensive service health check
make status             # Real-time service status
```

Manual equivalents:

```bash
# ETL (run on ETL machine)
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml

# Proxy (Docker)
cd proxy && docker compose up -d

# Single test
python -m pytest tests/proxy/test_retrieval.py -v

# Coverage (also configured as pytest addopts in pyproject.toml)
python -m pytest tests/ --cov=proxy --cov=etl --cov-report=html
```

## Code Style Guidelines

- **Formatter & linter**: Ruff (replaces black/isort/flake8). Line length **120**, double quotes, target `py312`.
- **Ruff rules** (`pyproject.toml`): `E`, `F`, `I`, `N`, `W`, `UP`, `B`, `C4`, `SIM`. NFR test classes may use
  `NFR-XX` prefixes (`N801` ignored in `tests/**/test_nfr_*.py`).
- **Type checker**: mypy `strict = true` for `proxy/`; `etl.*` has relaxed overrides while type coverage matures.
  `ignore_missing_imports = true`.
- **Docstrings**: Google style. All public functions must have type annotations.
- **Naming**: modules/functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`, private members with a
  leading underscore.
- **Language**: English only in code and comments — no Russian (project rule).
- **Commits**: Conventional Commits — `<type>(<scope>): <subject>` with types `feat`, `fix`, `docs`, `style`,
  `refactor`, `test`, `chore`, `perf` (see `CONTRIBUTING.md`).

## Testing Instructions

Test layout under `tests/`:

- `tests/proxy/` — proxy unit tests (~150 files)
- `tests/etl/` — ETL unit tests (~40 files)
- `tests/mcp_server/`, `tests/model_evolution/`, `tests/security/`, `tests/deploy/` — component suites
- `tests/integration/` — requires running services (Qdrant, Neo4j, Redis); minikube variant via `make test-minikube`
- `tests/e2e/` — end-to-end, requires running services
- `tests/performance/` — latency benchmarks with saved baselines (`tests/performance/latency_benchmarks.json`)
- `tests/resilience/` — chaos / graceful-degradation tests
- `tests/features/` — BDD feature tests (require `RAG_PROXY_URL`)
- `tests/conftest.py` — shared fixtures

Pytest markers (registered in `pyproject.toml`): `e2e`, `benchmark`, `chaos`, `asyncio`, `slow`, `integration`,
`regression`, `bdd`.

Rules:

- Coverage floor: **80%** (`fail_under = 80` in `pyproject.toml`, enforced in CI); critical paths (auth, retrieval,
  generation) target 90%+.
- Mock external services (Qdrant, Redis, Neo4j, LLM) in unit tests; test success and failure paths.
- Test naming: `test_<what>_<condition>_<expected>`.
- New features must include tests.
- Some suites are explicitly excluded from coverage because they need live services (`etl/scheduler/
  streaming_pipeline.py`, `proxy/app/core/flare.py`, `proxy/app/core/ragas_eval.py`) — see `[tool.coverage.run] omit`
  in `pyproject.toml`.

CI workflows live in `.github/workflows/`: `ci.yml` (lint/format/typecheck/tests, Python 3.12), `security.yml`,
`model-evolution.yml`, `docs.yml` (MkDocs publish).

## API Endpoints

| Endpoint                           | Method | Description                                                    |
|------------------------------------|--------|----------------------------------------------------------------|
| `/v1/chat/completions`             | POST   | Chat completion (streaming + non-streaming)                    |
| `/v1/models`                       | GET    | List available models                                          |
| `/v1/health`                       | GET    | Health check (Qdrant + LLM + KB manager status)                |
| `/v1/health/live`                  | GET    | Liveness probe (K8s-compatible)                                |
| `/v1/health/ready`                 | GET    | Readiness probe (Qdrant + LLM connectivity)                    |
| `/v1/feedback`                     | POST   | Submit expert feedback (positive/negative + corrections)       |
| `/v1/auth/login`                   | POST   | JWT token generation (access + refresh pair)                   |
| `/v1/auth/register`                | POST   | User self-registration (bcrypt-hashed passwords in SQLite)     |
| `/v1/auth/refresh`                 | POST   | Token refresh (exchange refresh token for new pair)            |
| `/v1/auth/logout`                  | POST   | Logout (revoke refresh tokens, blacklist access token)         |
| `/v1/auth/me`                      | GET    | Current user context                                           |
| `/v1/widget`                       | GET    | Embeddable RAG chat widget (HTML)                              |
| `/v1/widget.js`                    | GET    | Standalone widget JavaScript                                   |
| `/v1/tools`                        | GET    | List available tools with optional category/tag filters        |
| `/v1/tools/{name}`                 | GET    | Get a single tool's details (parameters, visibility, provider) |
| `/v1/admin/kb/*`                   | *      | Knowledge base CRUD and ETL task tracking                      |
| `/v1/admin/models/train`           | POST   | Trigger a model training job (SLM/LLM/Reranker)                |
| `/v1/admin/models/status/{job_id}` | GET    | Poll training job status and metrics                           |
| `/v1/admin/models`                 | GET    | List registered models with versions and metrics               |
| `/v1/admin/models/promote`         | POST   | Promote a model version to production                          |
| `/v1/admin/models/rollback`        | POST   | Rollback model to a previous version                           |
| `/v1/admin/models/evaluate`        | POST   | Evaluate model quality against baseline                        |
| `/v1/admin/models/canary/split`    | POST   | Configure canary traffic split ratio                           |
| `/v1/admin/models/canary/status`   | GET    | Get current canary deployment status                           |
| `/metrics`                         | GET    | Prometheus metrics (counters, histograms, gauges)              |

RAG-specific parameters on `/v1/chat/completions`:

- `rag_version` — request a specific document version
- `rag_force_refresh` — bypass response cache
- `rag_skip_generation` — search-only mode (federation)
- `rag_return_chunks` — return retrieved chunks in response
- `rag_top_k` — override number of chunks after rerank
- Response extensions: `rag_feedback_id`, `rag_confidence`, `rag_sources`

## Configuration

All configuration via environment variables or `proxy/.env` (created from `proxy/.env.example`; `make setup`
creates both `proxy/.env` and `etl/.env` from their respective `.env.example` templates). The ETL Compose stack
(`etl/docker-compose.yml`) expects an external Docker network — create it once with
`docker network create rag-network`. Key settings:

```bash
# Required
QDRANT_HOST=localhost                     # Qdrant server
LLM_ENDPOINT=http://localhost:8000/v1     # LLM backend endpoint (vLLM/llama.cpp/OpenAI-compatible)
LLM_MODEL_NAME=your-model-name
LLM_PROVIDER=vllm                         # Backend provider: vllm, llama_cpp, openai_compatible

# Optional features (disabled by default)
USE_LANGGRAPH=true                        # Enable agentic orchestration
USE_REDIS=true                            # Enable Redis caching
GRAPH_ENABLED=true                        # Enable Neo4j graph expansion
AUTH_ENABLED=true                         # Enable JWT authentication
RATE_LIMIT_ENABLED=true                   # Enable rate limiting
METRICS_ENABLED=true                      # Enable Prometheus metrics
MODEL_EVOLUTION_ENABLED=true              # Enable fine-tuning pipelines
LOG_FORMAT=json                           # Structured JSON logging
```

See `proxy/app/shared/config.py` for all settings and `docs/en/guides/configuration-reference.md` for the full
reference.

## Security Considerations

- **Never commit secrets.** `proxy/.env`, `etl/.env`, and credential files are gitignored; use the `.example`
  templates. `JWT_SECRET` must be set in production — an ephemeral secret is generated with a warning otherwise.
- **Auth stack**: JWT access+refresh pairs, bcrypt-hashed passwords in SQLite, refresh-token revocation, token
  blacklist on logout. Optional Keycloak OIDC and LDAP/AD integration. RBAC roles: admin, expert, user, read-only.
- **Input validation** via `proxy/app/shared/security.py` (`InputValidator`); tool execution goes through
  `proxy/app/tools/security.py` validation and sandboxing.
- **Audit logging**: structured audit events (`proxy/app/shared/audit.py`, `logs/audit.jsonl`); compliance
  requirements tracked in `docs/en/guides/compliance-requirements.md`.
- **Rate limiting**: per-IP token bucket middleware (`RATE_LIMIT_ENABLED`).
- **Dependency scanning**: `make audit` runs pip-audit (OSV) over all requirements files;
  `.github/workflows/security.yml` runs in CI. Secret rotation procedures: `docs/en/guides/secrets-rotation.md`.
- **Air-gapped**: no external API calls at runtime; pre-download models with
  `python scripts/download_models_offline.py --all`.

## Key Constraints

- **Air-gapped environment** — all components must work without internet access
- **LLM context limits**: configurable (depends on deployed model); 8K tokens (embedder/reranker)
- **Technical documents**: versioned, overlapping, duplicate-prone
- **Incremental updates**: WAL-based checkpointing for resume capability
- **Single worker proxy**: `WORKERS=1` to protect shared embedder/cache state

## Git Remotes

- GitHub: https://github.com/AlexanderNarbaev/rag-system
- GitVerse: https://gitverse.ru/AlexandrNarbaev/rag-system

## Documentation Index

Full bilingual docs under `docs/en/` and `docs/ru/` (MkDocs source; rendered site in `site/`).

| Document                                       | Purpose                                               |
|------------------------------------------------|-------------------------------------------------------|
| `docs/en/adr/ADR-001` through `ADR-014`        | Architecture Decision Records (English)               |
| `docs/en/diagrams/`                            | C4 diagrams (SVG + Excalidraw)                        |
| `docs/en/guides/quickstart.md`                 | 5-minute setup tutorial                               |
| `docs/en/api_reference.md`                     | Complete endpoint reference                           |
| `docs/en/guides/configuration-reference.md`    | All environment variables                             |
| `docs/en/guides/rag-maturity-assessment.md`    | RAG maturity model, capability scoring, token economy |
| `docs/en/guides/best-practices-checklist.md`   | Production readiness checklist (8 dimensions)         |
| `docs/en/guides/roadmap.md`                    | Development roadmap and phased approach               |
| `docs/en/guides/disaster-recovery-runbook.md`  | DR procedures for all failure scenarios               |
| `docs/en/sli_slo.md`                           | SLI/SLO definitions with error budgets                |
| `docs/en/guides/performance-quality.md`        | HNSW tuning, quantization, monitoring, resilience     |
| `docs/en/guides/extensibility-data-sources.md` | Adding new ETL data sources                           |
| `docs/en/guides/access-control-rbac.md`        | RBAC and access control design                        |
| `docs/en/guides/knowledge-graph-strategy.md`   | Neo4j graph enrichment strategy                       |
| `docs/en/guides/federated-rag.md`              | Multi-silo federated RAG with fan-out and RRF merge   |
| `docs/en/guides/model-evolution.md`            | LoRA/QLoRA fine-tuning, EvalGate, canary deployment   |
| `docs/en/guides/agentic-tools-sdk.md`          | `@tool` decorator, `ToolBuilder`, `ToolContext`       |
| `docs/en/guides/agentic-tools-declarative.md`  | YAML/JSON declarative tool definitions                |
| `docs/en/guides/agentic-tools-openapi.md`      | OpenAPI/Swagger auto-discovery                        |
| `docs/en/guides/deployment-guide.md`           | Deployment and operations                             |
| `docs/en/guides/operations-guide.md`           | Operational procedures                                |
| `docs/en/guides/integration-opencode.md`       | OpenCode IDE integration                              |
| `docs/en/guides/troubleshooting.md`            | Common issues and resolutions                         |

## Multi-Agent Continuous Development Framework v3.0

The project is developed by an enhanced multi-agent team operating in wave-based sprints with checkpoint/resume
capabilities and an integrated tool ecosystem.

### Agent Team Composition (23 Roles)

#### Strategic & Product Layer

| Role                         | Responsibilities                                                                    |
|------------------------------|-------------------------------------------------------------------------------------|
| Product Manager              | Backlog, priorities, release criteria, roadmap ownership                            |
| Business Analyst             | User scenarios, acceptance criteria (Gherkin), requirement traceability             |
| Strategic Steering Committee | Wave planning, cross-wave prioritization, architectural governance, risk assessment |
| Domain Expert                | Golden dataset curation, answer quality verification, knowledge validation          |

#### Architecture & Technical Leadership

| Role                    | Responsibilities                                                                                 |
|-------------------------|--------------------------------------------------------------------------------------------------|
| System Architect        | Architecture design, ADRs, technology selection, system boundaries                               |
| Tech Lead               | Code review, technical debt management, tooling standards, merge gating                          |
| Tool Orchestrator       | MCP server coordination, tool SDK governance, OpenAPI auto-discovery, parallel execution routing |
| Focus & Session Manager | Context compaction, checkpoint management, session persistence, task continuity                  |

#### Development & Engineering

| Role               | Responsibilities                                                              |
|--------------------|-------------------------------------------------------------------------------|
| Backend Developer  | API, ETL, Qdrant/Neo4j/Redis/LLM integration                                  |
| ML Engineer        | Embeddings, reranking, HyDE, CRAG, hallucination detection, model fine-tuning |
| Data Engineer      | ETL pipelines, data quality, incremental extraction, WAL management           |
| Frontend Developer | OpenWebUI, admin panel, widget embedding                                      |
| UX/UI Designer     | User research, interaction design, accessibility, component library           |

#### Quality & Security

| Role                             | Responsibilities                                                                      |
|----------------------------------|---------------------------------------------------------------------------------------|
| QA Engineer                      | Unit/integration/e2e/performance tests, test framework maintenance                    |
| Security Engineer                | JWT, Keycloak, LDAP/AD, RBAC, vulnerability scanning, secret management               |
| Dual-Guardian Validator (Code)   | Static analysis enforcement, type safety, lint rules, code quality gates              |
| Dual-Guardian Validator (Domain) | Business logic verification, acceptance criteria validation, golden dataset alignment |
| Infrastructure Sentinel          | CI/CD health, K8s probe monitoring, backup integrity, resource utilization alerts     |

#### Operations & Integration

| Role                | Responsibilities                                                            |
|---------------------|-----------------------------------------------------------------------------|
| DevOps Engineer     | CI/CD, Docker, Kubernetes, monitoring, Helm chart maintenance               |
| Integration Manager | Module integration, staging coordination, inter-service contract validation |

#### Documentation & Analytics

| Role               | Responsibilities                                                                       |
|--------------------|----------------------------------------------------------------------------------------|
| Technical Writer   | API docs, architecture docs, runbooks, ADR authoring                                   |
| Doc-Sync Reflector | Bilingual documentation sync (EN/RU), changelog alignment, compliance doc traceability |
| Data Analyst       | RAG quality metrics, dashboards, SLI/SLO monitoring, regression analysis               |

### Enhanced Wave-Based Development Process

1. **Initiation** (PM + BA + Architect + Strategic Steering Committee) → goals, acceptance criteria, ADRs, risk
   assessment
2. **Detailing** (BA + Data Analyst + Domain Expert + UX/UI Designer) → test cases, golden dataset, UX research
3. **Design** (Architect + Tech Lead + Tool Orchestrator + ML + Data Eng) → specs, APIs, schemas, tool definitions
4. **Implementation** (all developers + DevOps + Tool Orchestrator) → parallel with mocks, CI gates,
   [STRATEGIC_NEEDED] blocking
5. **Testing** (QA + Integration + Security + Dual-Guardian Validators) → all test types, dual validation
6. **Quality Assessment** (Data Analyst + Domain Expert + UX + Doc-Sync Reflector) → metrics, verification, doc sync
7. **Acceptance** (PM + Tech Lead + DevOps + Infrastructure Sentinel) → final review, canary deploy, checkpoint commit
8. **Reflection** (Focus & Session Manager + Strategic Steering Committee) → context compaction, session checkpoint,
   next-wave planning

### Checkpoint & Resume Mechanism

- **Session state persisted after every action** via `artifacts/state/session_checkpoint.json`
- **Context compaction** logged in `artifacts/state/context_compaction_log.md` — carried-forward context, decisions,
  open items
- **Wave tracking** in `artifacts/state/current_wave.md` (mirror at repo-root `current_wave.md`) — active task,
  protected zones, status
- **Team state** in `.rag-team/state.json` — current project snapshot
- **Protected zones** — critical files that require Strategic Steering Committee approval to modify
- On session restart, load `artifacts/state/session_checkpoint.json` and `context_compaction_log.md` to resume state

### Strategic Blocking ([STRATEGIC_NEEDED])

- Critical architectural decisions that require Strategic Steering Committee approval are tagged `[STRATEGIC_NEEDED]`
- Protected zones (listed in `artifacts/state/current_wave.md`) require explicit committee sign-off
- No agent may modify protected zone files without clearing the `[STRATEGIC_NEEDED]` gate

### Bilingual Documentation Requirement

- All documentation, ADRs, guides, and runbooks must be maintained in both **English (EN)** and **Russian (RU)**
- `docs/en/` and `docs/ru/` directories must remain parallel and synchronized
- Doc-Sync Reflector validates parity between EN and RU documentation at each wave completion
- Code and comments remain English-only

## Development Rules

1. **Always commit + push after each wave** — never leave uncommitted work
2. **Run full verification**: lint, format, typecheck, tests before every commit
3. **Test coverage >= 80%** — enforced at CI level
4. **No Russian in code or comments** — English only
5. **Keep CHANGELOG.md and docs in sync** with every feature
6. **Check .rag-team/state.json** for current project snapshot
7. **Push to BOTH remotes**: origin (GitHub) + gitverse (GitVerse mirror)
8. **Compliance**: every change must be traceable to a requirement in
   `docs/en/guides/compliance-requirements.md`
9. **Graceful degradation** — every component must fail independently
10. **Air-gapped first** — no external API calls at runtime
11. **Session persistence** — update `artifacts/state/session_checkpoint.json` after every action; log context
    compactions
12. **Protected zones** — no modification of `proxy/app/shared/config.py` or `etl/scheduler/run_etl.py` without
    Strategic Steering Committee approval
13. **Bilingual docs** — all documentation must exist in EN and RU; Doc-Sync Reflector validates parity
14. **Checkpoint on resume** — load `artifacts/state/session_checkpoint.json` and `context_compaction_log.md` at
    session start
15. **[STRATEGIC_NEEDED]** — tag blocking decisions; do not proceed past unacknowledged strategic gates

## Key Verification Commands

```bash
ruff check .                                  # lint
ruff format --check .                         # format
make typecheck                                # mypy strict (proxy), relaxed (etl)
python -m pytest tests/proxy/ tests/etl/ -q   # main unit suites
make audit                                    # dependency vulnerability scan
helm lint deploy/k8s/helm/rag-system/         # K8s validation (or: make helm-lint)
```
