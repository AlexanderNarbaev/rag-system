# RAG System Architecture

## High-Level

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   ETL Pipeline  │ ──> │  Vector Store   │ <── │  RAG Proxy      │
│  (etl/)         │     │  (Qdrant)       │     │  (proxy/)       │
│                 │     │                 │     │                 │
│ • 6 extractors  │     │ • Dense + Sparse│     │ • FastAPI       │
│ • Semantic chunk│     │ • RRF Fusion    │     │ • Granian ASGI  │
│ • Embedding     │     │ • ACL filters   │     │ • Multi-provider│
│ • Graph (Neo4j) │     │                 │     │ • LangGraph     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                                               │
         │              ┌─────────────────┐              │
         └────────────> │  Model Evolution│ <────────────┘
                        │  Service        │
                        │  (port 8090)    │
                        └─────────────────┘
```

## Data Flow

### Indexing

1. Extract (Confluence/Jira/GitLab/docs/books/chats)
2. Chunk semantically
3. Generate SHA-256 hash
4. Embed with BGE-M3
5. Index in Qdrant

### Query

1. User sends chat with model+RAG
2. Rewrite query (SLM)
3. Hybrid search (dense + sparse, RRF)
4. Rerank (BGE-Reranker-v2-m3)
5. Build context (dedup, token budget)
6. Generate (LLM)
7. Confidence + grounding check
8. Return response

### HITL Feedback

1. Expert submits feedback via /v1/feedback
2. Stored in SQLite
3. Exported to JSONL
4. Model Evolution trains adapter
5. AdapterManager hot-reloads

## Key Design Decisions

- **OpenAI-compatible**: Drop-in for any client
- **+RAG routing**: Transparent to OpenWebUI
- **Multi-provider LLM**: vLLM, llama.cpp, or OpenAI-compatible
- **Air-gapped**: All models pre-downloaded
- **Graceful degradation**: Each component fails independently
- **DDD architecture**: Domain models with entities, value objects, events
