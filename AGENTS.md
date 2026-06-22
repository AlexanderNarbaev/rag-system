# AGENTS.md — RAG System

## Identity
Corporate RAG Knowledge Assistant — OpenAI-compatible proxy with ETL pipeline for Confluence, Jira, GitLab data ingestion into Qdrant + Neo4j, served via Gemma LLM.

## Language
English for code and comments. Russian for discussions.

## Current State
- **Version:** v0.1.0 (June 2026)
- **Tests:** 505 total, 483 passing (96% pass rate), 21 failing, 1 collection error
- **Maturity:** RAG Level 4 (Agentic) operational, Level 5 (Self-Correcting) partially designed
- **Production readiness:** 45% across 8 dimensions — see `docs/guides/best-practices-checklist.md`
- **Next milestone:** v0.2 — Token optimization + retrieval quality evaluation (see `docs/guides/roadmap.md`)

## Architecture
Three-layer system plus supporting services:

1. **ETL Layer** — data extraction, chunking, embedding, indexing (runs on a separate machine)
2. **Proxy Layer** — FastAPI app with OpenAI-compatible API, hybrid retrieval, reranking, LLM routing
3. **HITL Layer** — Streamlit expert dashboard for feedback and quality control
4. **MCP Server** — Model Context Protocol server exposing RAG tools to MCP-compatible clients (OpenCode, Claude Desktop)

## Key Architectural Principles

1. **Air-gapped first** — all models pre-downloaded, no external API calls at runtime. The system must function fully offline.
2. **Graceful degradation** — every component can fail independently: Neo4j unavailable → skip graph expansion. Reranker OOM → use raw hybrid scores. Redis down → fall back to in-memory cache. The proxy never crashes on component failure.
3. **Incremental by default** — WAL-based ETL checkpointing. SHA-256 content-addressable chunks. Only changed documents are reindexed.
4. **OpenAI compatibility** — the proxy is a drop-in replacement for any OpenAI client. Extensions (`rag_version`, `rag_force_refresh`) are silently ignored by standard clients.
5. **Dual-model routing** — SLM (Gemma-2B) for fast preprocessing; LLM (Gemma-4-26B) for heavy generation. Keeps latency low for routing tasks.
6. **Optional complexity** — LangGraph orchestrator, Neo4j graph expansion, and Redis caching are all optional. The system runs in simple RAG mode by default.
7. **Token economy** — every token counts. Token optimizer provides BPE-aware counting, 4 compression strategies, and smart budget allocation.

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
│   │   ├── main.py                   # FastAPI entry point (3 endpoints + health + metrics)
│   │   ├── orchestrator.py           # LangGraph agentic query pipeline (7-node state graph)
│   │   ├── retrieval.py              # Qdrant hybrid search (dense+sparse RRF) + graph expansion
│   │   ├── rerank.py                 # Cross-encoder reranker (MiniLM-L-6-v2)
│   │   ├── context_builder.py        # Context assembly: dedup, versioning, token-budgeted assembly
│   │   ├── llm_router.py             # Async vLLM/llama-cpp adapter (streaming + non-streaming)
│   │   ├── slm_router.py             # SLM: intent classification, query decomposition, entity extraction
│   │   ├── token_optimizer.py        # BPE-aware token counting, compression, budget allocation
│   │   ├── cache.py                  # Redis + in-memory multi-tier cache
│   │   ├── hitl.py                   # Human-in-the-loop: async interaction logging, feedback collection
│   │   ├── metrics.py                # Prometheus metrics (counters, histograms, gauges)
│   │   ├── rate_limiter.py           # Token bucket rate limiting middleware (per IP)
│   │   ├── middleware.py             # Request ID, correlation ID, logging middleware
│   │   ├── logging_config.py         # Structured logging (text/JSON), secret masking
│   │   ├── config.py                 # Environment-based configuration (all settings)
│   │   └── utils.py                  # Shared utilities: token counting, hashing, masking, safe division
│   ├── .env                          # Configuration (edit before first run)
│   ├── Dockerfile
│   ├── requirements_proxy.txt
│   └── docker-compose.yml            # Qdrant + Redis + Neo4j + vLLM + Proxy
├── mcp_server/                       # MCP server for OpenCode/Claude Desktop integration
│   ├── server.py                     # STDIO + Streamable HTTP transports, tools/resources/prompts
│   └── __init__.py
├── hitl_dashboard/                   # Streamlit expert review dashboard
│   ├── dashboard.py
│   └── feedback_logger.py
├── scripts/                          # Utility scripts
│   ├── init_collections.py           # Initialize Qdrant collections
│   └── download_models_offline.py    # Pre-download models for air-gapped env
├── tests/                            # Test suite
│   ├── proxy/                        # 282 proxy unit tests
│   ├── etl/                          # 121 ETL unit tests
│   ├── integration/                  # 56 integration tests
│   ├── mcp_server/                   # 46 MCP server tests
│   └── conftest.py                   # Shared fixtures
├── docs/                             # Documentation
│   ├── adr/                          # 7 Architecture Decision Records
│   ├── diagrams/                     # 4 C4 diagrams (SVG + Excalidraw)
│   └── guides/                       # 11 design & implementation guides
├── Makefile                          # Primary dev entry point
├── pyproject.toml                    # Python project config (ruff, mypy, pytest)
├── setup.sh                          # Installation script
├── opencode.json                     # OpenCode IDE configuration
└── README.md
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM** | Gemma-4-26B (GGUF via llama.cpp / vLLM) | Response generation (130K context) |
| **SLM** | Gemma-2B | Query routing, entity extraction (fast path) |
| **Embeddings** | BAAI/bge-m3 | Dense (1024-dim) + sparse (lexical) + ColBERT |
| **Vector DB** | Qdrant | Hybrid search (dense + sparse), RRF fusion |
| **Graph DB** | Neo4j | Entity relationships, multi-hop traversal |
| **Cache** | Redis | Embedding cache, rerank results, response cache |
| **Proxy** | FastAPI + LangGraph | OpenAI-compatible API, agentic orchestration |
| **ETL** | Python, requests, BeautifulSoup, spaCy, sentence-transformers | Data extraction, chunking, indexing |
| **Dashboard** | Streamlit | HITL expert review |
| **MCP** | FastMCP | Model Context Protocol server for IDE integration |
| **Auth** | Keycloak (planned v0.3) | Corporate SSO, RBAC |
| **Infra** | Docker Compose | Containerized deployment |

## Key Constraints
- **Air-gapped environment** — all components must work without internet access
- **Gemma context limits**: 130K tokens (LLM), 8K tokens (embedder/reranker)
- **Technical documents**: versioned, overlapping, duplicate-prone
- **Incremental updates**: WAL-based checkpointing for resume capability
- **Single worker proxy**: `WORKERS=1` to protect shared embedder/cache state

## Development

```bash
# ── Quick commands (preferred) ──
make install        # Full setup (proxy + ETL)
make install-dev    # Setup with dev dependencies
make test           # Run all tests (483+ passing)
make test-proxy     # Proxy unit tests only (282)
make test-etl       # ETL unit tests only (121)
make test-integration  # Integration tests (56)
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

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completion (streaming + non-streaming) |
| `/v1/models` | GET | List available models |
| `/v1/health` | GET | Health check (Qdrant + LLM status) |
| `/metrics` | GET | Prometheus metrics (counters, histograms, gauges) |

RAG-specific parameters on `/v1/chat/completions`:
- `rag_version` — request a specific document version
- `rag_force_refresh` — bypass response cache

## Configuration

All configuration via environment variables or `.env` file in `proxy/.env`. Key settings:

```bash
# Required
QDRANT_HOST=localhost          # Qdrant server
LLM_ENDPOINT=http://localhost:8000/v1  # vLLM/llama-cpp endpoint
LLM_MODEL_NAME=gemma-4-26b-it

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

| Document | Purpose |
|----------|---------|
| `docs/adr/ADR-001` through `ADR-007` | Architecture Decision Records |
| `docs/guides/rag-maturity-assessment.md` | RAG maturity model, capability scoring, token economy |
| `docs/guides/best-practices-checklist.md` | Production readiness checklist (8 dimensions) |
| `docs/guides/roadmap.md` | Version history and development roadmap (v0.1 → v1.0) |
| `docs/guides/performance-quality.md` | HNSW tuning, quantization, monitoring, resilience |
| `docs/guides/extensibility-data-sources.md` | Adding new ETL data sources |
| `docs/guides/access-control-rbac.md` | RBAC and access control design |
| `docs/guides/knowledge-graph-strategy.md` | Neo4j graph enrichment strategy |
| `docs/guides/deployment-guide.md` | Deployment and operations |
| `docs/guides/operations-guide.md` | Operational procedures |
| `docs/guides/integration-opencode.md` | OpenCode IDE integration |
| `docs/guides/troubleshooting.md` | Common issues and resolutions |
