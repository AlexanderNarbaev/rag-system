# OpenCode Integration Guide

## Architecture Overview

The RAG system exposes an OpenAI-compatible API at `http://localhost:8080/v1`. OpenCode connects to it as a drop-in LLM
provider, leveraging the corporate knowledge base (Confluence, Jira, GitLab) for context-aware code assistance.

```
┌──────────┐   OpenAI-compatible API    ┌──────────────┐
│ OpenCode  │ ──── POST /v1/chat/ ────▶ │  RAG Proxy   │
│  (client) │ ◀─── completions ──────── │  (FastAPI)   │
└──────────┘                            └──────┬───────┘
                                               │
                          ┌────────────────────┼────────────────────┐
                          ▼                    ▼                    ▼
                     ┌────────┐          ┌────────┐          ┌────────┐
                      │ Qdrant │          │  Neo4j │          │  LLM   │
                     │ (vecs) │          │ (graph)│          │ Backend│
                     └────────┘          └────────┘          └────────┘
```

The proxy intercepts each chat completion request, performs hybrid retrieval from Qdrant, reranks results, builds a
context-augmented prompt, and forwards it to the LLM. OpenCode sees standard OpenAI API responses — no special client
code needed.

## MCP Server Configuration

Configure OpenCode to use the RAG system as its model provider via `opencode.json`:

```json
{
  "providers": {
    "rag-system": {
      "name": "RAG System",
      "base_url": "http://localhost:8080/v1",
      "api_key": "${RAG_API_KEY}",
      "models": ["your-model-name"]
    }
  },
  "model": "rag-system/your-model-name"
}
```

If the RAG system is deployed on a separate machine within the air-gapped network:

```json
{
  "providers": {
    "rag-system": {
      "name": "RAG System (Internal)",
      "base_url": "http://rag-proxy.internal.company.com:8080/v1",
      "api_key": "${RAG_API_KEY}",
      "models": ["your-model-name"],
      "timeout": 120
    }
  },
  "model": "rag-system/your-model-name",
  "small_model": "rag-system/your-model-name"
}
```

### Environment Variables

```bash
# Set before launching OpenCode:
export RAG_API_KEY="your-secure-api-key"
# Must match the --api-key set in your LLM backend configuration
```

## Usage Examples

### Standard Code Query

When OpenCode sends a request about code in your organization's repositories, the RAG system automatically enriches it
with relevant context:

```
User: How is the authentication middleware implemented in the backend service?

OpenCode → POST /v1/chat/completions
  RAG Proxy:
    1. Embed query → "authentication middleware backend service"
    2. Hybrid search Qdrant → returns chunks from GitLab repo docs,
       Confluence architecture pages, Jira implementation tickets
    3. Rerank top 20 from 50 → selects most relevant
    4. Build context prompt with source attribution
    5. LLM generates answer with citations

Response: The authentication middleware uses JWT tokens with
Redis-based session management (src/auth/middleware.py:42).
The implementation follows the design in [Confluence: Auth Service ADR]
and was tracked in [Jira: DEV-1423].
```

### Requesting Specific Document Versions

```json
{
  "model": "rag-system/your-model-name",
  "messages": [
    {"role": "user", "content": "What was the original database schema?"}
  ],
  "rag_version": "2025-03-15"
}
```

### Bypassing Cache for Fresh Results

```json
{
  "model": "rag-system/your-model-name",
  "messages": [
    {"role": "user", "content": "What open Jira issues block the release?"}
  ],
  "rag_force_refresh": true
}
```

## Knowledge Enrichment

The knowledge base grows through the ETL pipeline, making OpenCode progressively smarter:

| Cycle       | Data Source                    | Update Frequency | Impact                          |
|-------------|--------------------------------|------------------|---------------------------------|
| **Daily**   | Jira updates, new comments     | Every 4 hours    | Issue status, decisions         |
| **Weekly**  | Confluence page changes        | Every 24 hours   | Architecture docs, runbooks     |
| **On push** | GitLab commits, merge requests | Near real-time   | Code changes, review context    |
| **Manual**  | Chat history, uploaded docs    | On demand        | Expert knowledge, meeting notes |

### WAL-Based Incremental Updates

```bash
# The ETL scheduler tracks progress via WAL files:
cat etl/wal/etl_wal.json
# {
#   "last_confluence_sync": "2026-06-21T14:00:00Z",
#   "last_jira_sync": "2026-06-21T18:30:00Z",
#   "last_gitlab_sync": "2026-06-22T09:15:00Z",
#   "total_indexed": 48291,
#   "last_successful_run": "2026-06-22T09:15:00Z"
# }

# Only new/changed documents are processed each run:
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml
```

## Security

### API Key Management

```bash
# LLM backend — set API key (docker-compose.yml example for vLLM):
llm-backend:
  command: >
    --model /models/your-model.gguf
    --api-key ${LLM_API_KEY:-change-me-in-production}

# The proxy authenticates to LLM backend:
LLM_API_KEY=change-me-in-production  # in proxy/.env

# OpenCode authenticates to proxy:
RAG_API_KEY=change-me-in-production  # opencode environment
```

### Access Control

The proxy can be placed behind a reverse proxy with basic auth:

```nginx
# nginx.conf
server {
    listen 443 ssl;
    server_name rag-proxy.internal.company.com;

    ssl_certificate /etc/ssl/certs/rag-proxy.crt;
    ssl_certificate_key /etc/ssl/private/rag-proxy.key;

    location /v1/ {
        auth_basic "RAG System";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://rag-proxy:8080;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Data Sensitivity

- `LOG_REQUESTS=true` logs queries and responses; set `SENSITIVE_SECRETS=password,token,key` to mask in logs
- Prometheus metrics DO NOT contain query text — only counts and latencies
- Qdrant stores vector embeddings, not raw text — reverse-engineering is impractical
- Neo4j stores entity relationships, not full document contents

## Performance

### Expected Latency

| Operation            | Cold (no cache) | Warm (cache hit)       |
|----------------------|-----------------|------------------------|
| Embedding            | 50–100 ms       | 5–10 ms (Redis)        |
| Qdrant search        | 20–50 ms        | —                      |
| Reranking (20 docs)  | 100–200 ms      | 50–100 ms (Redis)      |
| LLM generation       | 2–10 s          | 1–5 s (response cache) |
| **Total round-trip** | **3–12 s**      | **1–5 s**              |

### Caching Behavior

Three-level cache architecture:

1. **Embedding cache** (Redis): query embeddings reused across similar queries, TTL 24h
2. **Rerank cache** (Redis): (query, doc_id) → relevance score, TTL 1h
3. **Response cache** (Redis): (query_hash, rag_version) → full LLM response, TTL 15min

```bash
# Monitor cache effectiveness:
docker exec rag-redis redis-cli INFO stats | grep -E 'keyspace_hits|keyspace_misses'

# Calculate hit ratio: hits / (hits + misses)
# Target: >60% hit ratio for production workloads
```

### Concurrency

```bash
# LLM backend handles concurrent sequences (example for vLLM):
--max-num-seqs 16

# Proxy uvicorn workers (docker-compose):
WORKERS=2  # per replica

# Scale horizontally for more throughput:
docker-compose up -d --scale rag-proxy=3
```

### Bandwidth Considerations

- Each query: ~5 KB request + ~50 KB context + ~2 KB response
- ETL ingestion: ~10 MB per 1000 documents (text only)
- Model serving: embeddings ~5 MB per batch, LLM ~50 MB per request (streaming)
- Internal network should have >1 Gbps between proxy, Qdrant, and LLM backend

## Troubleshooting OpenCode Integration

```bash
# Verify the endpoint is reachable:
curl http://localhost:8080/v1/models

# Test a completion:
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RAG_API_KEY}" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "What is the project structure?"}]
  }'

# Check OpenCode logs for connection errors:
# "Connection refused" → proxy not running
# "401 Unauthorized" → API key mismatch
# "504 Gateway Timeout" → increase REQUEST_TIMEOUT in .env

---

## MCP Server Tools (v0.5)

The RAG system includes an MCP (Model Context Protocol) server at `mcp_server/server.py` that exposes RAG tools to MCP-compatible clients.

### Available Tools

| Tool | Description |
|------|-------------|
| `search_knowledge_base` | Hybrid search (dense+sparse) across all indexed documents |
| `get_document` | Retrieve a specific document by source ID |
| `list_sources` | List available data sources with document counts |
| `get_graph_context` | Retrieve Neo4j graph context for an entity |
| `submit_feedback` | Submit expert feedback for HITL quality improvement |
| `get_confidence` | Get confidence score for a query-answer pair |

### Configuring in opencode.json

```json
{
  "mcp_servers": {
    "rag-system": {
      "type": "streamableHttp",
      "url": "http://localhost:8081/mcp",
      "description": "RAG System — corporate knowledge base search"
    }
  }
}
```

### Usage in OpenCode

Once configured, OpenCode can use RAG tools directly:

- "Search the knowledge base for the authentication architecture"
- "Get the document with source ID CONFL-12345"
- "List all available data sources"
- "What's the graph context around the 'AuthService' entity?"

```
