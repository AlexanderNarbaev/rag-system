# AGENTS.md — RAG System

## Identity
Corporate RAG Knowledge Assistant — OpenAI-compatible proxy with ETL pipeline for Confluence, Jira, GitLab data ingestion into Qdrant, served via Gemma LLM.

## Language
English for code and comments. Russian for discussions.

## Architecture
Three-layer system:
1. **ETL Layer** — data extraction, chunking, embedding, indexing (runs on a separate machine)
2. **Proxy Layer** — FastAPI app with OpenAI-compatible API, hybrid retrieval, reranking, LLM routing
3. **HITL Layer** — expert dashboard for feedback and quality control

## Project Structure
```
rag-system/
├── etl/                    # Data pipeline (standalone)
│   ├── extractors/         # confluence.py, jira.py, gitlab.py
│   ├── chunker/            # semantic_chunker.py, hash_versioning.py
│   ├── graph_builder/      # entity_extractor.py, neo4j_loader.py
│   ├── indexer/            # qdrant_hybrid.py, live_vector_lake.py
│   ├── scheduler/          # run_etl.py
│   └── config/             # etl_config.yaml
├── proxy/                  # RAG proxy (Docker)
│   ├── app/                # FastAPI application
│   ├── Dockerfile
│   └── docker-compose.yml
├── hitl_dashboard/         # Streamlit expert dashboard
├── scripts/                # Utility scripts
└── docs/                   # Documentation + research
```

## Tech Stack
- **LLM**: Gemma-4-26B (GGUF via llama.cpp / vLLM)
- **SLM**: Gemma-2B (query routing, entity extraction)
- **Embeddings**: BAAI/bge-m3 (dense + sparse + ColBERT)
- **Vector DB**: Qdrant (hybrid search, RRF fusion)
- **Graph DB**: Neo4j (entity relationships)
- **Cache**: Redis
- **Proxy**: FastAPI + LangGraph
- **ETL**: Python, requests, BeautifulSoup, sentence-transformers

## Key Constraints
- **Air-gapped environment** — all components must work without internet access
- **Gemma context**: 130K tokens (LLM), 8K tokens (embedder/reranker)
- **Technical documents**: versioned, overlapping, duplicate-prone
- **Incremental updates**: WAL-based checkpointing for resume capability

## Development
```bash
# ETL
cd etl && pip install -r requirements_etl.txt
python scheduler/run_etl.py --config config/etl_config.yaml

# Proxy
cd proxy && docker-compose up -d
```

## Git Remotes
- GitHub: https://github.com/AlexanderNarbaev/rag-system
- GitVerse: https://gitverse.ru/AlexandrNarbaev/rag-system
