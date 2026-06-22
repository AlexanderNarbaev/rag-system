# RAG System — Corporate Knowledge Assistant

OpenAI-compatible RAG proxy with ETL pipeline for Confluence, Jira, GitLab → Qdrant → LLM.

## Architecture

```
┌─────────────────────────────────────────┐
│              ETL Machine                 │
│  extractors/ → chunker/ → indexer/      │
│  graph_builder/ → scheduler/            │
│  (Confluence, Jira, GitLab → Qdrant)    │
└──────────────┬──────────────────────────┘
               │ shared volumes / API
               ▼
┌─────────────────────────────────────────┐
│            Proxy Machine (Docker)        │
│  ┌─────────────────────────────────┐    │
│  │ rag-proxy (FastAPI)             │    │
│  │  ├─ retrieval (Qdrant hybrid)   │    │
│  │  ├─ rerank (cross-encoder)      │    │
│  │  ├─ context_builder             │    │
│  │  ├─ llm_router (Gemma/vLLM)     │    │
│  │  └─ orchestrator (LangGraph)    │    │
│  ├─ qdrant (vector DB)             │    │
│  ├─ redis (cache)                  │    │
│  └─ neo4j (graph DB)               │    │
└──────────────┬──────────────────────┘
               │ OpenAI API (/v1/chat/completions)
               ▼
     OpenWebUI, OpenCode, custom clients
```

## Project Structure

```
rag-system/
├── etl/                          # ETL pipeline (runs separately)
│   ├── extractors/               # confluence.py, jira.py, gitlab.py
│   ├── chunker/                  # semantic_chunker.py, hash_versioning.py
│   ├── graph_builder/            # entity_extractor.py, neo4j_loader.py
│   ├── indexer/                  # qdrant_hybrid.py, live_vector_lake.py
│   ├── scheduler/                # run_etl.py
│   ├── config/                   # etl_config.yaml
│   ├── Dockerfile.etl
│   └── requirements_etl.txt
├── proxy/                        # RAG proxy (Dockerized)
│   ├── app/
│   │   ├── main.py               # FastAPI entry point
│   │   ├── orchestrator.py       # LangGraph query pipeline
│   │   ├── retrieval.py          # Qdrant hybrid search
│   │   ├── rerank.py             # Cross-encoder reranker
│   │   ├── context_builder.py    # Context assembly for LLM
│   │   ├── llm_router.py         # vLLM/llama-cpp adapter
│   │   ├── cache.py              # Redis cache layer
│   │   ├── slm_router.py         # Small model routing
│   │   ├── hitl.py               # Human-in-the-loop hooks
│   │   ├── config.py             # Configuration
│   │   └── utils.py              # Shared utilities
│   ├── Dockerfile
│   ├── requirements_proxy.txt
│   └── docker-compose.yml
├── hitl_dashboard/               # Expert review interface
├── scripts/                      # init_collections.py, download_models_offline.py
├── docs/                         # deploy_etl.md, deploy_proxy.md, api_reference.md
│   └── deepseek-chat-2c423805.json  # Research chat export
├── opencode.json
├── AGENTS.md
└── README.md
```

## RAG Maturity Levels

| Level | Retrieval | Ranking | Multi-hop | Self-correction |
|-------|-----------|---------|-----------|-----------------|
| Naive | Dense only | None | No | No |
| Advanced | Hybrid (dense+BM25) | Cross-encoder | Query rewrite | No |
| **GraphRAG** | Graph+vector | Node centrality | Graph composition | Partial |
| Agentic | Adaptive multi-try | Sufficiency eval | Task decomposition | Full iterative |

This project implements Advanced RAG with GraphRAG extensions.

## Key Design Decisions

1. **BAAI/bge-m3** for embeddings — dense+sparse+ColBERT in one model, 100+ languages, 8192 token context
2. **Qdrant** for vector storage — hybrid search (dense + sparse) with RRF fusion
3. **Semantic chunking** — MDKeyChunker, structure-aware splitting by headers/sections
4. **Version-aware** — SHA-256 hashing, LiveVectorLake for document versioning
5. **Dual LLM** — SLM (Gemma-2B) for query routing + LLM (Gemma-4-26B) for generation
6. **OpenAI-compatible API** — drop-in replacement for any OpenAI client

## Quick Start

```bash
# 1. Install opencode_initializer (one-time):
curl -fsSL https://raw.githubusercontent.com/AlexanderNarbaev/opencode_initializer/main/setup.sh | bash -s -- --full

# 2. Install RAG system components:
bash setup.sh --rag-system

# 3. Start the proxy:
cd rag-system/proxy && docker-compose up -d

# 4. Run ETL pipeline:
cd rag-system/etl && python scheduler/run_etl.py --config config/etl_config.yaml
```

## License

MIT © 2026 Alexander Narbaev
