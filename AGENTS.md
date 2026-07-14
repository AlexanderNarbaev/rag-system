# AGENTS.md — RAG System

## Identity

Corporate RAG Knowledge Assistant — OpenAI-compatible proxy with ETL pipeline for Confluence, Jira, GitLab data
ingestion into Qdrant + Neo4j, served via configurable LLM backend.

## Language

English for code and comments. The system supports full i18n — documentation is available in RU and EN with a language
switcher. See `docs/en/` and `docs/ru/`.

## Architecture

Three-layer system plus supporting services, with multi-provider LLM backend support:

1. **ETL Layer** — data extraction, chunking, embedding, indexing (runs on a separate machine)
2. **Proxy Layer** — FastAPI app with OpenAI-compatible API, hybrid retrieval, reranking, multi-provider LLM routing (
   vLLM, llama.cpp, or any OpenAI-compatible endpoint)
3. **HITL Layer** — Streamlit expert dashboard for feedback and quality control
4. **MCP Server** — Model Context Protocol server exposing RAG tools to MCP-compatible clients (OpenCode, Claude
   Desktop)
5. **Model Evolution** — LoRA/QLoRA fine-tuning pipeline for SLM, LLM, and Reranker; MLflow experiment tracking; MinIO
   artifact storage; EvalGate CI/CD quality gating; AdapterManager hot-reload; CanaryController gradual rollout
6. **Agentic Tools Expansion** — Custom tool SDK for user-defined tools; declarative tool definitions; OpenAPI
   auto-discovery; parallel tool execution with dependency resolution

## Key Architectural Principles

1. **Air-gapped first** — all models pre-downloaded, no external API calls at runtime. The system must function fully
   offline.
2. **Graceful degradation** — every component can fail independently: Neo4j unavailable → skip graph expansion. Reranker
   OOM → use raw hybrid scores. Redis down → fall back to in-memory cache. The proxy never crashes on component failure.
3. **Incremental by default** — WAL-based ETL checkpointing. SHA-256 content-addressable chunks. Only changed documents
   are reindexed.
4. **OpenAI compatibility** — the proxy is a drop-in replacement for any OpenAI client. Extensions (`rag_version`,
   `rag_force_refresh`) are silently ignored by standard clients.
5. **Dual-model routing** — lightweight SLM for fast preprocessing (intent classification, query decomposition, entity
   extraction); full-scale LLM for heavy generation. Keeps latency low for routing tasks.
6. **Multi-provider support** — pluggable backend adapters via `provider_adapter.py` allow swapping between vLLM,
   llama.cpp, and any OpenAI-compatible API without changing orchestration logic.
7. **Optional complexity** — LangGraph orchestrator, Neo4j graph expansion, and Redis caching are all optional. The
   system runs in simple RAG mode by default.
8. **Token economy** — every token counts. Token optimizer provides BPE-aware counting, 4 compression strategies, and
   smart budget allocation.

## Project Structure

```
rag-system/
├── etl/                              # ETL pipeline (standalone)
│   ├── extractors/                   # confluence.py, jira.py, gitlab.py, books.py, docs.py, chats.py
│   ├── chunker/                      # semantic_chunker.py, hash_versioning.py
│   ├── graph_builder/                # entity_extractor.py, neo4j_loader.py, schema.yaml
│   ├── indexer/                      # qdrant_hybrid.py, live_vector_lake.py, wal_manager.py
│   ├── scheduler/                    # run_etl.py (orchestrates full pipeline)
│   ├── config/                       # etl_config.yaml
│   ├── Dockerfile.etl
│   └── requirements_etl.txt
├── proxy/                            # RAG proxy (Dockerized)
│   ├── app/
│   │   ├── main.py                   # FastAPI entry point (30+ endpoints: chat, models, health, auth, widget, feedback, admin, tools, files, model evolution)
│   │   ├── api/                      # API endpoint handlers
│   │   │   ├── chat.py               # /v1/chat/completions — streaming + non-streaming
│   │   │   ├── auth_endpoints.py     # /v1/auth/* — login, register, refresh, logout, me
│   │   │   ├── health.py             # /v1/health, /v1/health/live, /v1/health/ready
│   │   │   ├── admin.py              # /v1/admin/* — model training, promotion, canary
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
│   │   │   ├── rerank.py             # Cross-encoder reranker (MiniLM-L-6-v2)
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
│   │   │   ├── context/              # Context assembly
│   │   │   │   ├── builder.py        # Context assembly: dedup, versioning, token-budgeted assembly
│   │   │   │   ├── compression.py    # Context compression strategies
│   │   │   │   └── versioning.py     # Document version tracking in context
│   │   │   └── orchestrator/         # LangGraph agentic pipeline
│   │   │       ├── graph.py          # LangGraph state graph definition (10-node agentic pipeline)
│   │   │       └── nodes.py          # Individual graph node implementations
│   │   ├── llm/                      # LLM routing & provider abstraction
│   │   │   ├── router.py             # Async LLM adapter (streaming + non-streaming)
│   │   │   ├── slm.py                # SLM: intent classification, query decomposition, entity extraction
│   │   │   ├── remote_services.py    # Remote embedder/reranker clients with local fallback
│   │   │   └── provider/             # Provider adapters
│   │   │       ├── base.py           # Multi-provider router with adapter pattern
│   │   │       ├── openai.py         # OpenAI/Anthropic/Ollama/Generic adapters
│   │   │       └── utils.py          # Backward-compatible wrappers
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
│   │   │   └── openapi/              # OpenAPI auto-discovery
│   │   │       ├── discovery.py      # Auto-discovery of OpenAPI endpoints
│   │   │       └── converter.py      # OpenAPI spec to tool definition converter
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
│   │   ├── model_evolution/          # Fine-tuning pipeline (17 modules)
│   │   │   ├── trainer.py            # Base trainer classes + TrainingJob + registry
│   │   │   ├── trainer_base.py       # ABC for all trainers
│   │   │   ├── slm_trainer.py        # SLM LoRA fine-tuning
│   │   │   ├── llm_trainer.py        # LLM QLoRA fine-tuning
│   │   │   ├── reranker_trainer.py   # Reranker Full/LoRA fine-tuning
│   │   │   ├── adapter_manager.py    # Hot-reload trained adapters
│   │   │   ├── canary_controller.py  # Gradual rollout with traffic splitting
│   │   │   ├── model_registry.py     # Model artifact registry (MLflow + MinIO)
│   │   │   ├── artifact_store.py     # Artifact storage abstraction
│   │   │   ├── eval_gate.py          # EvalGate CI/CD quality gating
│   │   │   ├── experiment_tracker.py # MLflow experiment tracking
│   │   │   ├── data_processor.py     # Training data preprocessing
│   │   │   ├── metrics_gen.py        # Training metrics generation
│   │   │   ├── nli_evaluator.py      # NLI-based model evaluation
│   │   │   ├── env_profile.py        # Dev/Prod/CI training profiles
│   │   │   └── exceptions.py         # Model evolution error hierarchy
│   │   └── tools.py                  # Legacy tool utilities
│   ├── .env                          # Configuration (edit before first run)
│   ├── Dockerfile
│   ├── requirements_proxy.txt
│   └── docker-compose.yml            # Qdrant + Redis + Neo4j + MinIO + Proxy
├── mcp_server/                       # MCP server for OpenCode/Claude Desktop integration
│   ├── server.py                     # STDIO + Streamable HTTP transports, tools/resources/prompts
│   └── __init__.py
├── dashboard/                        # Streamlit expert review dashboard (Planned)
├── tui/                              # Terminal UI for RAG interaction
│   ├── app.py
│   └── requirements.txt
├── scripts/                          # Utility scripts
│   ├── init_collections.py           # Initialize Qdrant collections
│   ├── download_models_offline.py    # Pre-download models for air-gapped env
│   ├── deploy.sh                     # Deploy script (dev/prod)
│   ├── setup_wizard.py               # Interactive configuration wizard
│   └── ops/                          # Operations scripts
│       ├── backup_cron.sh            # Cron backup orchestrator
│       ├── backup_qdrant.sh          # Qdrant snapshot backup
│       ├── backup_neo4j.sh           # Neo4j database backup
│       ├── backup_redis.sh           # Redis RDB backup
│       ├── restore_all.sh            # Restore all services from backup
│       └── verify_restore.sh         # Verify backup integrity
├── deploy/                           # Deployment manifests
│   ├── docker/                       # Docker Compose variants
│   │   ├── docker-compose.prod.yml   # Production deployment
│   │   └── docker-compose.openwebui.yml # OpenWebUI integration
│   └── k8s/helm/rag-system/          # Kubernetes Helm chart (Planned)
├── config/                           # Monitoring configuration
│   └── monitoring/                   # Prometheus + Grafana configs
├── tests/                            # Test suite
│   ├── proxy/                        # Proxy unit tests (72 files)
│   ├── etl/                          # ETL unit tests (22 files)
│   ├── integration/                  # Integration tests (5 files)
│   ├── e2e/                          # End-to-end tests (3 files)
│   ├── performance/                  # Performance tests (2 files)
│   ├── resilience/                   # Chaos/resilience tests (2 files)
│   └── conftest.py                   # Shared fixtures
├── docs/                             # Documentation (EN + RU)
│   ├── en/adr/                       # Architecture Decision Records (14 ADRs)
│   ├── en/diagrams/                  # C4 diagrams (SVG + Excalidraw)
│   ├── en/guides/                    # Design & implementation guides (29 guides)
│   ├── ru/adr/                       # Russian translations of ADRs
│   └── ru/guides/                    # Russian translations of guides
├── Makefile                          # Primary dev entry point (36 targets)
├── pyproject.toml                    # Python project config (ruff, mypy, pytest)
├── setup.sh                          # Installation script
├── opencode.json                     # OpenCode IDE configuration
└── README.md
```

## Tech Stack

| Component      | Technology                                                                         | Purpose                                           |
|----------------|------------------------------------------------------------------------------------|---------------------------------------------------|
| **LLM**        | Any OpenAI-compatible model (e.g., Llama, Mistral, Gemma, Qwen) via vLLM/llama.cpp | Response generation (configurable context length) |
| **SLM**        | Lightweight model (e.g., Llama-3B, Gemma-2B, Qwen-2.5-3B)                          | Query routing, entity extraction (fast path)      |
| **Embeddings** | BAAI/bge-m3                                                                        | Dense (1024-dim) + sparse (lexical) + ColBERT     |
| **Vector DB**  | Qdrant                                                                             | Hybrid search (dense + sparse), RRF fusion        |
| **Graph DB**   | Neo4j                                                                              | Entity relationships, multi-hop traversal         |
| **Cache**      | Redis                                                                              | Embedding cache, rerank results, response cache   |
| **Proxy**      | FastAPI + LangGraph                                                                | OpenAI-compatible API, agentic orchestration      |
| **ETL**        | Python, requests, BeautifulSoup, spaCy, sentence-transformers                      | Data extraction, chunking, indexing               |
| **Dashboard**  | Streamlit                                                                          | HITL expert review                                |
| **MCP**        | FastMCP                                                                            | Model Context Protocol server for IDE integration |
| **Auth**       | Keycloak OIDC                                                                      | Corporate SSO, RBAC                               |
| **Infra**      | Kubernetes + Helm                                                                  | Production-grade deployment with HPA, probes      |
| **Backup**     | S3/MinIO                                                                           | Automated snapshots, dumps, RDB backups           |

## MCP Servers (configured in opencode.json)

| Server                    | Purpose                                           |
|---------------------------|---------------------------------------------------|
| **`filesystem`**          | File operations within the project                |
| **`context7`**            | Live documentation for libraries and frameworks   |
| **`context7-official`**   | Official Context7 library documentation (upstash) |
| **`sequential-thinking`** | Step-by-step reasoning for complex problems       |
| **`codegraph`**           | Code graph navigation and call tracing            |
| **`agentic-tools`**       | Hierarchical task management and memory           |
| **`memorylayer`**         | Semantic memory and session context               |
| **`fetch`**               | HTTP requests and web content retrieval           |
| **`sqlite`**              | SQLite database interactions                      |
| **`github`**              | GitHub API (repositories, PRs, issues)            |
| **`excalidraw`**          | Architecture diagrams (C4, system design)         |

## Key Constraints

- **Air-gapped environment** — all components must work without internet access
- **LLM context limits**: configurable (depends on deployed model); 8K tokens (embedder/reranker)
- **Technical documents**: versioned, overlapping, duplicate-prone
- **Incremental updates**: WAL-based checkpointing for resume capability
- **Single worker proxy**: `WORKERS=1` to protect shared embedder/cache state

## Development

```bash
# ── Quick commands (preferred) ──
make install        # Full setup (proxy + ETL)
make install-dev    # Setup with dev dependencies
make test           # Run all tests
make test-proxy     # Proxy unit tests only
make test-etl       # ETL unit tests only
make test-integration  # Integration tests
make lint           # Lint with ruff
make format         # Format with ruff
make format-check   # Check formatting without changes
make typecheck      # Run mypy static type checker
make clean          # Remove build artifacts and caches
make docker-build   # Build Docker images
make docker-up      # Start docker-compose services (detached)
make docker-down    # Stop docker-compose services
make docker-logs    # Tail docker-compose logs
make all            # CI pipeline: install → lint → test
make help           # Show all available targets

# ── Manual commands ──

# ETL (run on ETL machine)
cd etl && pip install -r requirements_etl.txt
python scheduler/run_etl.py --config config/etl_config.yaml

# Proxy (run on proxy machine)
cd proxy && docker-compose up -d

# Single test with verbose output
python -m pytest tests/proxy/test_retrieval.py::TestHybridSearch::test_rrf_fusion -v

# Coverage report
python -m pytest tests/ --cov=proxy --cov=etl --cov-report=html

# Watch mode (requires pytest-watch)
ptw tests/ -- -v
```

## API Endpoints

| Endpoint                           | Method | Description                                                    |
|------------------------------------|--------|----------------------------------------------------------------|
| `/v1/chat/completions`             | POST   | Chat completion (streaming + non-streaming)                    |
| `/v1/models`                       | GET    | List available models                                          |
| `/v1/health`                       | GET    | Health check (Qdrant + LLM status)                             |
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
- Response extensions: `rag_feedback_id`, `rag_confidence`, `rag_sources`

## Configuration

All configuration via environment variables or `.env` file in `proxy/.env`. Key settings:

```bash
# Required
QDRANT_HOST=localhost          # Qdrant server
LLM_ENDPOINT=http://localhost:8000/v1  # LLM backend endpoint (vLLM/llama.cpp/OpenAI-compatible)
LLM_MODEL_NAME=your-model-name
LLM_PROVIDER=vllm              # Backend provider: vllm, llama_cpp, openai_compatible

# Optional features (disabled by default)
USE_LANGGRAPH=true             # Enable agentic orchestration
USE_REDIS=true                 # Enable Redis caching
GRAPH_ENABLED=true             # Enable Neo4j graph expansion
USE_GRAPH_EXPANSION=true       # Enable graph context enrichment
RATE_LIMIT_ENABLED=true        # Enable rate limiting
METRICS_ENABLED=true           # Enable Prometheus metrics
LOG_FORMAT=json                # Structured JSON logging
```

See `proxy/app/config.py` for all available settings and defaults.

## Git Remotes

- GitHub: https://github.com/AlexanderNarbaev/rag-system
- GitVerse: https://gitverse.ru/AlexandrNarbaev/rag-system

## Documentation Index

| Document                                       | Purpose                                               |
|------------------------------------------------|-------------------------------------------------------|
| `docs/en/adr/ADR-001` through `ADR-014`        | Architecture Decision Records (English)               |
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
