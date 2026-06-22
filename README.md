# RAG System — Corporate Knowledge Assistant

OpenAI-compatible RAG proxy with ETL pipeline for Confluence, Jira, GitLab, documents, books, and chat history — indexed into Qdrant + Neo4j, served via Gemma LLM.

## Status

**v0.1.0** — Complete codebase extracted, 8 critical bugs fixed, 473 tests passing.  
See [ADR documents](docs/adr/) for architecture decisions and [C4 diagrams](docs/diagrams/) for visual architecture.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ETL Machine                               │
│  extractors/ → chunker/ → graph_builder/ → indexer/ → scheduler/ │
│  (Confluence, Jira, GitLab, Books, Docs, Chats → Qdrant+Neo4j)  │
└──────────────────┬──────────────────────────────────────────────┘
                   │ shared volumes / API
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Proxy Machine (Docker)                        │
│  ┌──────────────────────────────────────────────────────┐       │
│  │ rag-proxy (FastAPI :8080)                             │       │
│  │  ├─ retrieval (Qdrant hybrid: dense+sparse)           │       │
│  │  ├─ rerank (cross-encoder)                            │       │
│  │  ├─ context_builder (dedup + versioning)              │       │
│  │  ├─ llm_router (Gemma-4-26B via vLLM)                 │       │
│  │  ├─ slm_router (Gemma-2B: intent/rewrite)             │       │
│  │  ├─ orchestrator (LangGraph: agentic multi-step)      │       │
│  │  ├─ cache (Redis: embeddings, rerank, responses)       │       │
│  │  └─ hitl (interaction logging + feedback)              │       │
│  ├─ qdrant (vector DB :6333)                              │       │
│  ├─ redis (cache :6379)                                   │       │
│  └─ neo4j (graph DB :7687)                                │       │
└──────────────────┬──────────────────────────────────────────────┘
                   │ OpenAI-compatible API (/v1/chat/completions)
                   ▼
         OpenWebUI, OpenCode, n8n, custom clients
                   │
                   ▼
         HITL Dashboard (Streamlit :8501) — expert feedback
```

### C4 Architecture Diagrams

| Level | Scope | File |
|-------|-------|------|
| **L1** | System Context (11 nodes) | [`c4-level1-context`](docs/diagrams/c4-level1-context.svg) |
| **L2** | Containers (10 nodes) | [`c4-level2-containers`](docs/diagrams/c4-level2-containers.svg) |
| **L3** | RAG Proxy Components (13 nodes) | [`c4-level3-proxy-components`](docs/diagrams/c4-level3-proxy-components.svg) |
| **L3** | ETL Pipeline Components (14 nodes) | [`c4-level3-etl-components`](docs/diagrams/c4-level3-etl-components.svg) |

Editable `.excalidraw` files available in `docs/diagrams/`.

## Project Structure

```
rag-system/
├── etl/                              # ETL pipeline (runs separately)
│   ├── extractors/                   # confluence.py, jira.py, gitlab.py
│   ├── chunker/                      # semantic_chunker.py, hash_versioning.py
│   ├── graph_builder/                # entity_extractor.py, neo4j_loader.py, schema.yaml
│   ├── indexer/                      # qdrant_hybrid.py, live_vector_lake.py, wal_manager.py
│   ├── scheduler/                    # run_etl.py (orchestrates full pipeline)
│   ├── config/                       # etl_config.yaml
│   ├── Dockerfile.etl
│   └── requirements_etl.txt
├── proxy/                            # RAG proxy (Dockerized)
│   ├── app/
│   │   ├── main.py                   # FastAPI entry point (3 endpoints)
│   │   ├── orchestrator.py           # LangGraph agentic query pipeline
│   │   ├── retrieval.py              # Qdrant hybrid search + graph expansion
│   │   ├── rerank.py                 # Cross-encoder reranker
│   │   ├── context_builder.py        # Context assembly: dedup, versioning, assembly
│   │   ├── llm_router.py             # Async vLLM/llama-cpp adapter (streaming + non-streaming)
│   │   ├── cache.py                  # Redis + in-memory cache layer
│   │   ├── slm_router.py             # Small model: intent classification, decomposition, rewrite
│   │   ├── hitl.py                   # Human-in-the-loop: interaction logging, feedback
│   │   ├── config.py                 # Environment-based configuration
│   │   └── utils.py                  # Shared utilities: tokens, hashing, masking
│   ├── .env                          # Configuration (edit before first run)
│   ├── Dockerfile
│   ├── requirements_proxy.txt
│   └── docker-compose.yml            # Qdrant + Redis + Neo4j + vLLM + Proxy
├── hitl_dashboard/                   # Streamlit expert review dashboard
│   ├── dashboard.py
│   └── feedback_logger.py
├── scripts/                          # Utility scripts
│   ├── init_collections.py           # Initialize Qdrant collections
│   └── download_models_offline.py    # Pre-download models for air-gapped env
├── tests/                            # Test suite (473 tests, all pass)
│   ├── etl/                          # 161 ETL unit tests
│   ├── proxy/                        # 255 proxy unit tests
│   ├── integration/                  # 57 integration tests
│   └── conftest.py                   # Shared fixtures
├── docs/                             # Documentation
│   ├── adr/                          # 7 Architecture Decision Records
│   ├── diagrams/                     # 4 C4 diagrams (SVG + Excalidraw)
│   └── guides/                       # Design & implementation guides
├── opencode.json
├── AGENTS.md
└── README.md
```

## Documentation Index

### Architecture Decision Records (ADRs)

| # | Decision | Document |
|---|----------|----------|
| 001 | BAAI/bge-m3 as embedding model | [`ADR-001`](docs/adr/ADR-001-bge-m3-embedding-model.md) |
| 002 | Qdrant for hybrid vector search | [`ADR-002`](docs/adr/ADR-002-qdrant-hybrid-search.md) |
| 003 | Dual-LLM (SLM + LLM) architecture | [`ADR-003`](docs/adr/ADR-003-dual-llm-architecture.md) |
| 004 | OpenAI-compatible proxy pattern | [`ADR-004`](docs/adr/ADR-004-openai-compatible-proxy.md) |
| 005 | Version-aware document indexing | [`ADR-005`](docs/adr/ADR-005-version-aware-indexing.md) |
| 006 | Agentic RAG with LangGraph | [`ADR-006`](docs/adr/ADR-006-agentic-rag-langgraph.md) |
| 007 | Human-in-the-loop feedback system | [`ADR-007`](docs/adr/ADR-007-hitl-feedback-system.md) |

### Design Guides

| Guide | Document |
|-------|----------|
| Extensibility: adding new data sources | [`extensibility-data-sources.md`](docs/guides/extensibility-data-sources.md) |
| Access control & RBAC | [`access-control-rbac.md`](docs/guides/access-control-rbac.md) |
| Knowledge graph enrichment & unrolling | [`knowledge-graph-strategy.md`](docs/guides/knowledge-graph-strategy.md) |
| Performance & quality best practices | [`performance-quality.md`](docs/guides/performance-quality.md) |

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM** | Gemma-4-26B (GGUF via llama.cpp / vLLM) | Response generation |
| **SLM** | Gemma-2B | Query routing, entity extraction |
| **Embeddings** | BAAI/bge-m3 | Dense + sparse + ColBERT |
| **Vector DB** | Qdrant | Hybrid search (dense + sparse), RRF fusion |
| **Graph DB** | Neo4j | Entity relationships, multi-hop traversal |
| **Cache** | Redis | Embedding cache, rerank results, response cache |
| **Proxy** | FastAPI + LangGraph | OpenAI-compatible API, agentic orchestration |
| **ETL** | Python, requests, BeautifulSoup, spaCy | Data extraction, chunking, indexing |
| **Dashboard** | Streamlit | HITL expert review |
| **Auth** | Keycloak (planned) | Corporate SSO, RBAC |
| **Infra** | Docker Compose | Containerized deployment |

## Key Design Decisions

1. **Hybrid embeddings** — BAAI/bge-m3 provides dense + sparse + ColBERT in one model
2. **Qdrant** — native hybrid search with RRF fusion, on-disk sparse index
3. **Semantic chunking** — MDKeyChunker, structure-aware splitting by headers/sections
4. **Version-aware** — SHA-256 hashing, LiveVectorLake for hot/cold storage stratification
5. **Dual LLM** — SLM (Gemma-2B) for fast query routing + LLM (Gemma-4-26B) for generation
6. **OpenAI-compatible** — drop-in replacement for any OpenAI client
7. **WAL-based ETL** — incremental checkpointing with resume capability
8. **Air-gapped** — all models pre-downloaded, no external API dependencies
9. **LangGraph** — optional agentic orchestration with multi-step retrieval and self-correction

## RAG Maturity Levels

| Level | Retrieval | Ranking | Multi-hop | Self-correction |
|-------|-----------|---------|-----------|-----------------|
| Naive | Dense only | None | No | No |
| Advanced | Hybrid (dense+BM25) | Cross-encoder | Query rewrite | No |
| **GraphRAG** | Graph+vector | Node centrality | Graph composition | Partial |
| Agentic | Adaptive multi-try | Sufficiency eval | Task decomposition | Full iterative |

This project implements **Advanced RAG with GraphRAG extensions** (Level 3).  
The LangGraph orchestrator (`proxy/app/orchestrator.py`) provides agentic capabilities (Level 4) when enabled.

## Quick Start

```bash
# 1. Install opencode_initializer (one-time):
curl -fsSL https://raw.githubusercontent.com/AlexanderNarbaev/opencode_initializer/main/setup.sh | bash -s -- --full

# 2. Install RAG system components:
bash setup.sh --rag-system

# 3. Configure:
cd rag-system/proxy
cp .env.example .env  # edit with your settings

# 4. Start the proxy:
docker-compose up -d

# 5. Run ETL pipeline:
cd ../etl
python scheduler/run_etl.py --config config/etl_config.yaml
```

## Running Tests

```bash
# All tests (no external services required):
pytest tests/ -v

# Specific suites:
pytest tests/proxy/ -v        # 255 proxy unit tests
pytest tests/etl/ -v          # 161 ETL unit tests
pytest tests/integration/ -v  # 57 integration tests

# Coverage:
pytest tests/ --cov=proxy --cov=etl --cov-report=html
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completion (streaming + non-streaming) |
| `/v1/models` | GET | List available models |
| `/v1/health` | GET | Health check (Qdrant + LLM status) |

The `/v1/chat/completions` endpoint accepts standard OpenAI parameters plus:
- `rag_version` — request a specific document version
- `rag_force_refresh` — bypass response cache

## License

MIT © 2026 Alexander Narbaev
