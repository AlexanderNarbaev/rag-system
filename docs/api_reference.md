# API Reference

The RAG Proxy exposes an **OpenAI-compatible API** on port `8080`. Any OpenAI client can use it as a drop-in replacement — just point `base_url` to `http://<host>:8080/v1`.

---

## Base URL

```
http://<proxy-host>:8080/v1
```

All endpoints are prefixed with `/v1` to match the OpenAI API convention.

---

## Authentication

**Planned for v0.3 (Keycloak SSO).** Currently, the proxy relies on:

- **Network isolation** — deployed within a private corporate network
- **Reverse proxy with basic auth** — recommended for external access (see [Proxy Deployment](deploy_proxy.md#security))
- **vLLM API key** — set via `LLM_API_KEY` in `.env` to authenticate proxy-to-LLM communication

When auth is enabled, include the API key in requests:

```http
Authorization: Bearer <your-api-key>
```

---

## Endpoints

### `POST /v1/chat/completions`

Chat completion with RAG augmentation. Accepts standard OpenAI parameters plus RAG-specific extensions.

#### Request

```json
{
  "model": "gemma-4-26b-it",
  "messages": [
    {"role": "system", "content": "You are a technical assistant."},
    {"role": "user", "content": "How is authentication implemented in the backend?"}
  ],
  "temperature": 0.2,
  "top_p": 0.95,
  "max_tokens": 4096,
  "stream": false
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | string | Yes | — | Model ID. Use `gemma-4-26b-it` or `rag-proxy` |
| `messages` | array | Yes | — | Chat messages. System prompt is replaced with RAG context |
| `temperature` | number | No | `0.2` | Sampling temperature (0–2) |
| `top_p` | number | No | `0.95` | Nucleus sampling |
| `max_tokens` | number | No | `4096` | Maximum tokens in response |
| `stream` | boolean | No | `false` | Enable Server-Sent Events streaming |

##### RAG-Specific Parameters

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `rag_version` | string | No | `null` | Request context from a specific document version (ISO date or SHA prefix) |
| `rag_force_refresh` | boolean | No | `false` | Bypass response cache and force fresh retrieval + generation |

#### Response (Non-Streaming)

```json
{
  "id": "rag_1719057600_a1b2c3d4",
  "object": "chat.completion",
  "created": 1719057600,
  "model": "gemma-4-26b-it",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Authentication is implemented using JWT tokens with Redis-based session management...\n\nSources: [Confluence: Auth Service ADR], [src/auth/middleware.py:42]"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 1250,
    "completion_tokens": 180,
    "total_tokens": 1430
  }
}
```

#### Streaming Response (SSE)

When `"stream": true`, the response uses Server-Sent Events:

```
data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"gemma-4-26b-it","choices":[{"index":0,"delta":{"role":"assistant","content":"Auth"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"gemma-4-26b-it","choices":[{"index":0,"delta":{"content":"entication"},"finish_reason":null}]}

...

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"gemma-4-26b-it","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Each chunk follows the OpenAI streaming format:
- `delta` contains incremental content (instead of `message`)
- `finish_reason` is `null` until the final chunk

#### RAG Pipeline (Under the Hood)

When a chat completion request arrives, the proxy:

1. **Embeds** the user query with `BAAI/bge-m3`
2. **Searches** Qdrant with hybrid retrieval (dense + sparse, RRF fusion) — up to `MAX_CHUNKS_RETRIEVAL` results
3. **Reranks** results with `cross-encoder/ms-marco-MiniLM-L-6-v2` — selects top `MAX_CHUNKS_AFTER_RERANK`
4. **Deduplicates** chunks by SHA-256 hash and filters by version
5. **Evaluates** retrieval quality (CRAG-style) — may trigger expansion, fallback, or normal assembly
6. **Assembles** context with smart token budget allocation
7. **Generates** response via Gemma-4-26B (vLLM or llama.cpp)
8. **Caches** response in Redis (unless `rag_force_refresh` is set)

With LangGraph enabled (`USE_LANGGRAPH=true`), the pipeline uses a 7-node agentic state graph with multi-step retrieval and self-correction.

---

### `GET /v1/models`

List available models.

#### Request

```http
GET /v1/models HTTP/1.1
```

#### Response

```json
{
  "object": "list",
  "data": [
    {
      "id": "gemma-4-26b-it",
      "object": "model",
      "created": 1719057600,
      "owned_by": "local"
    },
    {
      "id": "rag-proxy",
      "object": "model",
      "created": 1719057600,
      "owned_by": "local"
    }
  ]
}
```

- `gemma-4-26b-it` — the actual LLM
- `rag-proxy` — virtual model alias for the full RAG pipeline

---

### `GET /v1/health`

Health check for the proxy and its dependencies.

#### Request

```http
GET /v1/health HTTP/1.1
```

#### Response (Healthy)

```json
{
  "status": "ok",
  "timestamp": "2026-06-22T10:00:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "ok"
  }
}
```

**HTTP 200** when all components are healthy.

#### Response (Degraded)

```json
{
  "status": "degraded",
  "timestamp": "2026-06-22T10:00:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "error: Connection refused"
  }
}
```

**HTTP 503** when any component is unreachable.

The proxy never crashes on component failure (graceful degradation). If Qdrant is down, retrieval returns empty results. If the LLM is down, the proxy returns a 503 on `/v1/chat/completions`.

---

### `GET /metrics`

Prometheus metrics in OpenMetrics format.

#### Request

```http
GET /metrics HTTP/1.1
```

#### Response (excerpt)

```
# HELP rag_requests_total Total API requests
# TYPE rag_requests_total counter
rag_requests_total{endpoint="/v1/chat/completions"} 1423
rag_requests_total{endpoint="/v1/models"} 89

# HELP rag_request_duration_seconds Request latency
# TYPE rag_request_duration_seconds histogram
rag_request_duration_seconds_bucket{le="0.1"} 12
rag_request_duration_seconds_bucket{le="0.5"} 87
rag_request_duration_seconds_bucket{le="1.0"} 234
rag_request_duration_seconds_bucket{le="5.0"} 1201
rag_request_duration_seconds_bucket{le="+Inf"} 1423

# HELP rag_llm_tokens_total Total tokens used
# TYPE rag_llm_tokens_total counter
rag_llm_tokens_total{type="prompt"} 1780000
rag_llm_tokens_total{type="completion"} 256000

# HELP rag_cache_hit_ratio Cache hit ratio
# TYPE rag_cache_hit_ratio gauge
rag_cache_hit_ratio 0.62
```

Key metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `rag_requests_total` | Counter | Total API requests by endpoint |
| `rag_request_duration_seconds` | Histogram | Request latency (p50/p95/p99) |
| `rag_retrieval_chunks` | Histogram | Chunks retrieved per query |
| `rag_rerank_duration_seconds` | Histogram | Reranker latency |
| `rag_llm_duration_seconds` | Histogram | LLM generation latency |
| `rag_llm_tokens_total` | Counter | Tokens used (prompt + completion) |
| `rag_cache_hit_ratio` | Gauge | Redis cache hit ratio |
| `rag_errors_total` | Counter | Error count by type |

---

## Error Codes

| HTTP Status | Meaning | Typical Cause |
|-------------|---------|---------------|
| **200** | Success | Normal operation |
| **400** | Bad Request | Missing `messages`, empty user query, invalid JSON |
| **401** | Unauthorized | Missing or invalid API key (when auth is enabled) |
| **429** | Too Many Requests | Rate limit exceeded (when `RATE_LIMIT_ENABLED=true`) |
| **500** | Internal Error | Unhandled exception in the pipeline |
| **503** | Service Unavailable | LLM or Qdrant unreachable, health check degraded |

### Rate Limiting

When enabled (`RATE_LIMIT_ENABLED=true`), a token bucket algorithm limits requests:

| Config Variable | Default | Description |
|-----------------|---------|-------------|
| `RATE_LIMIT_PER_MINUTE` | `60` | Sustained requests per minute per IP |
| `RATE_LIMIT_BURST` | `10` | Burst capacity above the sustained rate |

On rate limit exceed, the proxy returns:

```json
{
  "detail": "Rate limit exceeded. Try again later."
}
```

---

## Environment Variable Reference

All proxy configuration via environment variables (see `proxy/.env`). Key settings:

### Required

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_HOST` | `localhost` | Qdrant server hostname |
| `QDRANT_PORT` | `6333` | Qdrant gRPC port |
| `LLM_ENDPOINT` | `http://localhost:8000/v1` | vLLM/llama-cpp endpoint |
| `LLM_MODEL_NAME` | `gemma-4-26b-it` | Model name to request from LLM endpoint |

### Optional Features

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_LANGGRAPH` | `false` | Enable agentic orchestration (7-node state graph) |
| `USE_REDIS` | `false` | Enable Redis caching |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `GRAPH_ENABLED` | `false` | Enable Neo4j connectivity |
| `USE_GRAPH_EXPANSION` | `false` | Enable graph context enrichment |
| `METRICS_ENABLED` | `true` | Expose Prometheus `/metrics` endpoint |
| `RATE_LIMIT_ENABLED` | `false` | Enable IP-based rate limiting |
| `LOG_FORMAT` | `text` | Log format: `text` or structured `json` |

### Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_CHUNKS_RETRIEVAL` | `50` | Chunks to retrieve from Qdrant |
| `MAX_CHUNKS_AFTER_RERANK` | `20` | Chunks after cross-encoder reranking |
| `EMBEDDER_DEVICE` | `cpu` | Device for embedding model: `cpu` or `cuda` |
| `RERANKER_BATCH_SIZE` | `32` | Batch size for cross-encoder |
| `REQUEST_TIMEOUT` | `120` | LLM request timeout in seconds |
| `MAX_RETRIES` | `3` | Retry attempts on LLM connection failure |
| `RETRY_DELAY` | `1.0` | Delay between retries in seconds |
| `WORKERS` | `1` | Uvicorn worker processes (keep at 1 for shared caches) |

Full configuration reference: `proxy/app/config.py`

---

## SDK Usage Examples

### Python (openai package)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed"  # placeholder, no auth in v0.1
)

# Non-streaming
response = client.chat.completions.create(
    model="gemma-4-26b-it",
    messages=[
        {"role": "user", "content": "What is the project structure?"}
    ],
    temperature=0.2,
    max_tokens=4096,
    extra_body={
        "rag_version": "2026-01-15",
        "rag_force_refresh": False
    }
)
print(response.choices[0].message.content)

# Streaming
stream = client.chat.completions.create(
    model="gemma-4-26b-it",
    messages=[{"role": "user", "content": "Explain the ETL pipeline."}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### cURL

```bash
# Non-streaming
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma-4-26b-it",
    "messages": [{"role": "user", "content": "How many ADRs are there?"}],
    "temperature": 0.2,
    "max_tokens": 1024
  }'

# Streaming
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "model": "gemma-4-26b-it",
    "messages": [{"role": "user", "content": "Summarize the deployment process."}],
    "stream": true
  }'

# Health check
curl http://localhost:8080/v1/health

# List models
curl http://localhost:8080/v1/models

# Metrics
curl http://localhost:8080/metrics
```

### JavaScript / TypeScript

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "not-needed",
});

const completion = await client.chat.completions.create({
  model: "gemma-4-26b-it",
  messages: [
    { role: "user", content: "What database does the system use?" },
  ],
  temperature: 0.2,
});
console.log(completion.choices[0].message.content);
```
