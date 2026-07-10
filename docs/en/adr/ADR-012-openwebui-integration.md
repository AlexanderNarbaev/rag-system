# ADR-012: OpenWebUI Integration Architecture

**Status:** Accepted  
**Date:** 2026-07-10  
**Author:** Architecture Design  
**Scope:** OpenWebUI integration with RAG proxy, MinIO file storage, and dedicated vector DB

---

## Context

The RAG system needs a user-friendly web interface for non-technical users. OpenWebUI (formerly Ollama WebUI) provides:
- Chat interface with model selection
- File upload and management
- Tool/function calling support
- Knowledge base management
- User authentication and administration

The system must work in an air-gapped corporate environment with:
- Dedicated MinIO instance for file storage
- Shared Qdrant for vector search
- RAG proxy as the primary LLM backend

## Decision

Integrate OpenWebUI as a first-class frontend with:

1. **OpenAI-compatible API connection** — OpenWebUI connects to RAG proxy via `OPENAI_API_BASE_URL=http://rag-proxy:8080/v1`
2. **S3/MinIO storage** — File uploads stored in MinIO via `STORAGE_PROVIDER=s3`
3. **Shared Qdrant** — OpenWebUI's built-in RAG uses the same Qdrant instance
4. **Tool server integration** — RAG proxy registered as OpenAPI tool server
5. **Dedicated Docker Compose** — `docker-compose.openwebui.yml` with all services

## Architecture

```
User Browser → OpenWebUI (3000) → RAG Proxy (8080) → LLM Backend (8000)
                     ↓
              MinIO (9000) ← File uploads
                     ↓
              Qdrant (6333) ← Vector search (shared)
```

## Consequences

### Positive
- Non-technical users get a polished chat interface
- File uploads handled by MinIO (S3-compatible, scalable)
- Tool calling works via OpenAPI integration
- Shared Qdrant means consistent search results

### Negative
- Dual RAG systems (OpenWebUI + proxy) may confuse users
- Additional infrastructure (MinIO, OpenWebUI container)
- File upload flow needs sync with ETL pipeline

### Mitigations
- Document clearly which RAG to use for what purpose
- Use separate Qdrant collections for OpenWebUI vs proxy RAG
- Create sync script for OpenWebUI uploads → ETL input
