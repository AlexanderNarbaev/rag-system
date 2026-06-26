# API Reference

The RAG Proxy exposes an **OpenAI-compatible API** on port `8080`. Any OpenAI client can use it as a drop-in replacement — just point `base_url` to `http://<host>:8080/v1`. The proxy adds RAG-specific extensions for feedback, confidence scoring, source traceability, tool calling (including live Confluence/Jira/GitLab queries), and multi-language support.

---

## Base URL

```
http://<proxy-host>:8080/v1
```

All endpoints are prefixed with `/v1` to match the OpenAI API convention. The `/metrics` endpoint is at the root level.

---

## Authentication Flow

### Overview

Authentication is implemented via JWT tokens. When disabled (`AUTH_ENABLED=false`, the default), the proxy accepts all requests without authentication. When enabled, all endpoints except `/v1/auth/login`, `/v1/health`, and `/metrics` require a valid JWT.

### Token Lifecycle

```
Client                     Proxy                     Keycloak/LDAP
  |                          |                           |
  |-- POST /v1/auth/login -->|                           |
  |   {username, password}   |-- validate credentials -->|
  |                          |<---- user context --------|
  |<--- JWT token ----------|                           |
  |                          |                           |
  |-- API request ---------->|                           |
  |   Authorization: Bearer  |-- verify JWT ------------>|
  |                          |<---- valid ---------------|
  |<--- response ------------|                           |
  |                          |                           |
  |-- POST /v1/auth/refresh >|                           |
  |   (before expiry)        |-- refresh JWT ----------->|
  |                          |<---- new token -----------|
  |<--- new JWT -------------|                           |
```

### Configuration

```bash
# Enable authentication
AUTH_ENABLED=true

# JWT signing secret (generate with: openssl rand -hex 32)
JWT_SECRET=your-256-bit-secret

# For air-gapped deployments (no Keycloak):
# Comma-separated list of user:password_hash:role pairs
AUTH_VALID_USERS=admin:$2b$12$...:admin,viewer:$2b$12$...:viewer

# Token settings
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
```

### Rate Limiting

When enabled (`RATE_LIMIT_ENABLED=true`), a token bucket algorithm limits requests per IP address:

| Config Variable | Default | Description |
|-----------------|---------|-------------|
| `RATE_LIMIT_PER_MINUTE` | `60` | Sustained requests per minute per IP |
| `RATE_LIMIT_BURST` | `10` | Burst capacity above the sustained rate |

The rate limiter uses a token bucket with the following behavior:

- Tokens replenish at `RATE_LIMIT_PER_MINUTE / 60` per second
- Maximum bucket capacity is `RATE_LIMIT_PER_MINUTE + RATE_LIMIT_BURST`
- When bucket is empty, requests receive HTTP 429 with `Retry-After` header

On rate limit exceed:

```json
{
  "detail": "Rate limit exceeded. Try again later."
}
```

HTTP headers included in every response (when rate limiting is active):

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests per minute |
| `X-RateLimit-Remaining` | Remaining tokens in current window |
| `X-RateLimit-Reset` | Unix timestamp when bucket refills |
| `Retry-After` | Seconds until next request is allowed (429 only) |

---

## Endpoints

### `POST /v1/chat/completions`

Chat completion with RAG augmentation. Accepts standard OpenAI parameters plus RAG-specific extensions.

#### Request Schema

```json
{
  "model": "string (required)",
  "messages": [
    {
      "role": "string (system | user | assistant | tool)",
      "content": "string | array (required)",
      "name": "string (optional)",
      "tool_call_id": "string (required for tool role)",
      "tool_calls": [
        {
          "id": "string",
          "type": "function",
          "function": {
            "name": "string",
            "arguments": "string (JSON-encoded)"
          }
        }
      ]
    }
  ],
  "temperature": "number (0-2, default: 0.2)",
  "top_p": "number (0-1, default: 0.95)",
  "max_tokens": "integer (default: 4096)",
  "stream": "boolean (default: false)",
  "stop": ["string (optional)"],
  "presence_penalty": "number (-2.0 to 2.0, optional)",
  "frequency_penalty": "number (-2.0 to 2.0, optional)",
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "string",
        "description": "string",
        "parameters": "object (JSON Schema)"
      }
    }
  ],
  "tool_choice": "string | object (none | auto | {type: 'function', function: {name: '...'}})",
  "rag_version": "string (optional)",
  "rag_force_refresh": "boolean (default: false)"
}
```

#### Standard Parameters

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | string | Yes | — | Model ID. Use your configured `LLM_MODEL_NAME` or the virtual model `rag-proxy` which enables the full RAG pipeline |
| `messages` | array | Yes | — | Chat messages. System prompt is incorporated into the RAG context |
| `temperature` | number | No | `0.2` | Sampling temperature (0–2). Lower = more deterministic |
| `top_p` | number | No | `0.95` | Nucleus sampling threshold |
| `max_tokens` | number | No | `4096` | Maximum tokens in the generated response |
| `stream` | boolean | No | `false` | Enable Server-Sent Events streaming |
| `stop` | array | No | `null` | Up to 4 stop sequences |
| `presence_penalty` | number | No | `null` | Penalize repeated tokens (-2.0 to 2.0) |
| `frequency_penalty` | number | No | `null` | Penalize frequent tokens (-2.0 to 2.0) |
| `tools` | array | No | `null` | Available function/tool definitions |
| `tool_choice` | string/object | No | `"auto"` | Tool selection: `"none"`, `"auto"`, or specific function |

#### RAG-Specific Parameters

These parameters extend the standard OpenAI schema. They are silently ignored by standard OpenAI clients and only affect behavior when the request passes through the RAG proxy.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `rag_version` | string | No | `null` | Request context from a specific document version. Accepts ISO date (`"2026-01-15"`), SHA-256 prefix (`"a1b2c3d4"`), or version tag (`"v2.1"`). Filters retrieved chunks to match the specified version. |
| `rag_force_refresh` | boolean | No | `false` | Bypass Redis response cache. Forces fresh retrieval, reranking, context assembly, and LLM generation. Useful when documents have been updated and cached responses are stale. |
| `lang` | string | No | `"en"` | Response language for multi-language support. Supported: `ru`, `en`, `de`, `fr`, `zh`. Affects both document retrieval (cross-lingual matching) and response generation language. |
| `enable_live_sources` | boolean | No | `false` | Enable live queries to Confluence/Jira/GitLab APIs alongside indexed data. When enabled, the proxy can make real-time API calls to source systems for fresh data. Requires `LIVE_SOURCES_ENABLED=true` in configuration. |
| `enable_hyde` | boolean | No | `true` | Enable HyDE (Hypothetical Document Embeddings) query expansion. Generates a hypothetical document from the user query and uses it for second-pass retrieval. Improves recall for technical queries with uncommon terminology. |
| `enable_self_reflection` | boolean | No | `true` | Enable self-reflection critique step. After generation, the LLM re-reads its answer against retrieved context and flags inconsistencies. Low-scoring answers may trigger corrective re-generation. |

#### Response Schema (Non-Streaming, 200 OK)

```json
{
  "id": "string",
  "object": "chat.completion",
  "created": "integer (unix timestamp)",
  "model": "string",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "string | null (null when tool_calls present)",
        "tool_calls": [
          {
            "id": "string",
            "type": "function",
            "function": {
              "name": "string",
              "arguments": "string (JSON-encoded)"
            }
          }
        ]
      },
      "finish_reason": "string (stop | length | tool_calls | content_filter)"
    }
  ],
  "usage": {
    "prompt_tokens": "integer",
    "completion_tokens": "integer",
    "total_tokens": "integer"
  },
  "rag_feedback_id": "string | null",
  "rag_confidence": "float (0.0–1.0) | null",
  "rag_sources": [
    {
      "chunk_id": "string (SHA-256 hash)",
      "source": "string (document title)",
      "source_type": "string (confluence | jira | gitlab | document | book | chat)",
      "version": "string (formatted date)",
      "relevance_score": "float",
      "url": "string | null"
    }
  ]
}
```

#### RAG Response Extensions

| Field | Type | Description |
|-------|------|-------------|
| `rag_feedback_id` | string | Unique ID for submitting expert feedback via `/v1/feedback`. Generated per response. |
| `rag_confidence` | float | Confidence score (0.0–1.0). Based on context sufficiency, answer length vs. context ratio, and uncertainty phrase detection. Scores below 0.5 trigger `needs_review` flag. |
| `rag_sources` | array | Retrieved chunks used to generate the response. Each entry includes chunk ID, source document, type, version, relevance score, and optional URL. Useful for citation and audit. |

#### Tool Calling Response

When the LLM requests a tool call, `content` is `null` and `tool_calls` is populated:

```json
{
  "id": "rag_1719057600_a1b2c3d4",
  "object": "chat.completion",
  "created": 1719057600,
  "model": "your-model-name",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "search_knowledge_base",
              "arguments": "{\"query\":\"deployment process\",\"max_results\":5}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "rag_feedback_id": "fbk_1719057600_d4e5f6g7",
  "rag_confidence": 0.85
}
```

To continue the conversation with tool results, send a follow-up message with role `tool`:

```json
{
  "model": "your-model-name",
  "messages": [
    {"role": "user", "content": "How do I deploy the proxy?"},
    {"role": "assistant", "content": null, "tool_calls": [
      {"id": "call_abc123", "type": "function", "function": {"name": "search_knowledge_base", "arguments": "{\"query\":\"deployment\"}"}}
    ]},
    {"role": "tool", "tool_call_id": "call_abc123", "name": "search_knowledge_base", "content": "The proxy is deployed via docker-compose up -d from the proxy/ directory..."}
  ]
}
```

#### Streaming Response (SSE)

When `"stream": true`, the response uses Server-Sent Events with `text/event-stream` content type:

```
data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"content":"The"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"content":" proxy"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{},"finish_reason":"stop","rag_feedback_id":"fbk_1719057600_d4e5f6g7","rag_confidence":0.82,"rag_sources":[...]}]}

data: [DONE]
```

**Streaming behavior:**

- `delta` contains incremental content (instead of `message`)
- `finish_reason` is `null` until the final chunk
- RAG extensions (`rag_feedback_id`, `rag_confidence`, `rag_sources`) appear only in the **final chunk**
- The `[DONE]` sentinel terminates the stream
- When tool calls are streamed, `delta.tool_calls` is populated incrementally

#### RAG Pipeline (Under the Hood)

When a chat completion request arrives at the proxy:

1. **Query Analysis** — SLM classifies intent (5 classes: factual, procedural, comparison, troubleshooting, meta), optionally decomposes into sub-queries, extracts entities
2. **HyDE Query Expansion** (optional, `enable_hyde=true`) — Generates a hypothetical document from the query, embeds it, and uses it for a second-pass retrieval alongside the original query
3. **Hybrid Retrieval** — Dense (BGE-M3 1024-dim) + sparse (lexical BM25-style) vectors searched in Qdrant with RRF fusion (k=60). Returns up to `MAX_CHUNKS_RETRIEVAL` (default 50) chunks
4. **Live Source Query** (optional, `enable_live_sources=true`) — Direct API calls to Confluence/Jira/GitLab for real-time data alongside indexed results. Configured via tool/function calling
5. **Retrieval Quality Evaluation (CRAG)** — `RetrievalEvaluator` scores results (confidence 0.0–1.0) based on score distribution (0.4), coverage ratio (0.3), result count factor (0.2), and recency decay (0.1). Maps confidence to action: `USE`, `REWRITE`, `EXPAND`, or `FALLBACK`
6. **Query Rewriting** (if needed) — SLM or LLM rewrites ambiguous/failed queries; up to `MAX_RETRIEVAL_LOOPS=3` iterations
7. **Cross-Encoder Reranking** — MiniLM-L-6-v2 scores top-N candidates, selects top `MAX_CHUNKS_AFTER_RERANK` (default 20)
8. **LongContextReorder** — Re-ranks documents with significant content at edges (beginning/end) to combat "lost in the middle" effect
9. **Graph Expansion** (optional, `USE_GRAPH_EXPANSION=true`) — Neo4j multi-hop traversal enriches context with related entities and self-reflection validation edges
10. **De-duplication & Version Filtering** — Chunks deduplicated by SHA-256 hash; filtered by `rag_version` if specified
11. **LLMLingua Context Compression** — Token-level prompt compression for long documents (2-5x ratio with < 5% information loss)
12. **Context Assembly** — `TokenOptimizer` allocates token budget across system prompt, context, history, response, and self-reflection overhead
13. **LLM Generation** — Assembled prompt sent to configured LLM provider (vLLM, llama.cpp, Anthropic, Ollama, or generic OpenAI-compatible)
14. **Confidence Scoring** — `compute_confidence()` heuristic: context sufficiency (0.4 weight), context-to-answer ratio (0.3), uncertainty phrase detection (0.2), answer length check (0.1)
15. **Self-Reflection** (optional, `enable_self_reflection=true`) — Post-generation critique step: LLM re-reads answer against context, scores faithfulness, flags inconsistencies
16. **Hallucination Grounding** — NLI-based verification: cosine similarity embedding check + entailment classification. Answers with grounding score < 0.70 flagged for review
17. **Corrective Re-Generation** — Low-confidence or ungrounded answers trigger re-generation with expanded context, factuality-focused system prompt, or adjusted temperature
18. **Response Caching** — Response cached in Redis (1h TTL) unless `rag_force_refresh=true`

With LangGraph enabled (`USE_LANGGRAPH=true`), steps 1–9 are orchestrated by a 7-node state graph with conditional looping and self-correction:

```
rewrite → hyde_expand → retrieve → check_sufficiency → rerank → reorder → graph_expand → build_context → generate → self_reflect → check_confidence → (corrective_regen if needed)
    ↑          ↑               ↓                                                                                ↓
    └──────────┴─── (if insufficient, loop ≤3 times)                                                 (low confidence/grounding → corrective re-generation)
```

---

## Agentic Tool Calling (Live Sources)

v2.0 adds agentic tool calling that allows the LLM to make live queries to Confluence, Jira, and GitLab APIs alongside indexed data. Tools are defined as standard OpenAI-compatible function definitions and are routed through the provider adapter for transparent multi-provider support.

### Built-in Tools

| Tool Name | Source | Description |
|-----------|--------|-------------|
| `search_confluence` | Confluence REST API | Search Confluence pages by title, space, or content |
| `get_jira_issue` | Jira REST API | Retrieve Jira issue details by key or JQL query |
| `search_gitlab_merge_requests` | GitLab API | Search GitLab merge requests, commits, and discussions |
| `search_knowledge_base` | Qdrant + Neo4j | Search the indexed knowledge base (hybrid retrieval) |

### Tool Calling Example

```json
{
  "model": "rag-proxy",
  "messages": [
    {"role": "user", "content": "What's the latest status of the authentication migration project?"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_jira_issue",
        "description": "Get Jira issue details by project key",
        "parameters": {
          "type": "object",
          "properties": {
            "project_key": {"type": "string", "description": "Jira project key (e.g., AUTH)"},
            "status": {"type": "string", "description": "Filter by status"}
          }
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "search_confluence",
        "description": "Search Confluence for relevant documentation",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {"type": "string", "description": "Search query"},
            "space_key": {"type": "string", "description": "Confluence space key"}
          }
        }
      }
    }
  ],
  "tool_choice": "auto",
  "enable_live_sources": true
}
```

### Configuration

```bash
# Enable live source queries
LIVE_SOURCES_ENABLED=true

# Source API endpoints
CONFLUENCE_API_URL=https://confluence.example.com/rest/api
CONFLUENCE_API_TOKEN=your-token
JIRA_API_URL=https://jira.example.com/rest/api/2
JIRA_API_TOKEN=your-token
GITLAB_API_URL=https://gitlab.example.com/api/v4
GITLAB_API_TOKEN=your-token
```

Tool calling works across all supported LLM providers (OpenAI, Anthropic, Ollama, Generic REST) with automatic format translation by `provider_adapter.py`.

---

### `GET /v1/models`

List available models.

#### Request

```http
GET /v1/models HTTP/1.1
```

#### Response Schema (200 OK)

```json
{
  "object": "list",
  "data": [
    {
      "id": "string",
      "object": "model",
      "created": "integer (unix timestamp)",
      "owned_by": "string"
    }
  ]
}
```

#### Example Response

```json
{
  "object": "list",
  "data": [
    {
      "id": "llama-3-70b-instruct",
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

- `llama-3-70b-instruct` — the actual LLM configured via `LLM_MODEL_NAME`
- `rag-proxy` — virtual model alias. When used, the proxy applies the full RAG pipeline (retrieval + reranking + context assembly) before calling the LLM

---

### `GET /v1/health`

Health check for the proxy and its dependencies.

#### Request

```http
GET /v1/health HTTP/1.1
```

#### Response Schema (200 OK — Healthy)

```json
{
  "status": "ok",
  "timestamp": "string (ISO 8601)",
  "version": "string",
  "components": {
    "qdrant": "ok",
    "llm": "ok",
    "neo4j": "ok | disabled",
    "redis": "ok | disabled",
    "slm": "ok | disabled"
  }
}
```

#### Response Schema (503 — Degraded)

```json
{
  "status": "degraded",
  "timestamp": "string (ISO 8601)",
  "version": "string",
  "components": {
    "qdrant": "ok",
    "llm": "error: Connection refused",
    "neo4j": "disabled",
    "redis": "ok",
    "slm": "error: timeout"
  },
  "degraded_reason": "LLM backend unreachable"
}
```

**Component status values:**

| Value | Meaning |
|-------|---------|
| `ok` | Component responded within timeout |
| `error: <message>` | Component unreachable or returned error |
| `disabled` | Component not configured (e.g., `USE_REDIS=false`) |

**Graceful degradation:** The proxy never crashes on component failure. If Qdrant is down, retrieval returns empty results. If the LLM is down, the proxy returns 503 on `/v1/chat/completions`. If Neo4j is down but `USE_GRAPH_EXPANSION=false`, graph expansion is silently skipped.

---

### `GET /v1/health/live`

Kubernetes-compatible liveness probe. Returns 200 as long as the process is alive.

#### Request

```http
GET /v1/health/live HTTP/1.1
```

#### Response (200 OK)

```json
{
  "status": "alive",
  "timestamp": "string (ISO 8601)"
}
```

---

### `GET /v1/health/ready`

Kubernetes-compatible readiness probe. Returns 200 when the proxy is ready to serve requests (all required dependencies available). Returns 503 if critical dependencies are down.

#### Request

```http
GET /v1/health/ready HTTP/1.1
```

#### Response (200 OK — Ready)

```json
{
  "status": "ready",
  "timestamp": "string (ISO 8601)",
  "components": {
    "qdrant": "ok",
    "llm": "ok"
  }
}
```

#### Response (503 — Not Ready)

```json
{
  "status": "not_ready",
  "timestamp": "string (ISO 8601)",
  "reason": "Qdrant unreachable"
}
```

---

### `GET /metrics`

Prometheus metrics in OpenMetrics text format.

#### Request

```http
GET /metrics HTTP/1.1
```

#### Available Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rag_requests_total` | Counter | `endpoint`, `status` | Total API requests by endpoint and HTTP status |
| `rag_request_duration_seconds` | Histogram | `endpoint` | Request latency distribution (buckets: 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, +Inf) |
| `rag_retrieval_chunks` | Histogram | — | Chunks retrieved per query (buckets: 1, 5, 10, 20, 50) |
| `rag_retrieval_duration_seconds` | Histogram | — | Hybrid search + rerank latency |
| `rag_rerank_duration_seconds` | Histogram | — | Cross-encoder reranker latency |
| `rag_llm_duration_seconds` | Histogram | `provider` | LLM generation latency by provider type |
| `rag_llm_tokens_total` | Counter | `type` (`prompt` \| `completion` \| `total`) | Total tokens consumed |
| `rag_cache_hit_ratio` | Gauge | `cache_type` (`embedding` \| `rerank` \| `response`) | Cache hit ratio per cache tier |
| `rag_errors_total` | Counter | `type` (`llm` \| `qdrant` \| `neo4j` \| `validation` \| `timeout` \| `internal`) | Error count by failure type |
| `rag_active_requests` | Gauge | — | Currently in-flight requests |
| `rag_confidence_score` | Histogram | — | Distribution of confidence scores (buckets: 0.1, 0.3, 0.5, 0.7, 0.9) |
| `rag_feedback_total` | Counter | `rating` (`positive` \| `negative`) | Total feedback submissions |
| `rag_rate_limit_hits_total` | Counter | `endpoint` | Rate limit exceeded count per endpoint |

#### Example Response (excerpt)

```
# HELP rag_requests_total Total API requests by endpoint and status
# TYPE rag_requests_total counter
rag_requests_total{endpoint="/v1/chat/completions",status="200"} 1423
rag_requests_total{endpoint="/v1/chat/completions",status="429"} 12
rag_requests_total{endpoint="/v1/chat/completions",status="500"} 3

# HELP rag_request_duration_seconds Request latency distribution
# TYPE rag_request_duration_seconds histogram
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="0.1"} 12
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="0.5"} 87
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="1.0"} 234
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="5.0"} 1201
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="10.0"} 1405
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="30.0"} 1422
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="+Inf"} 1423

# HELP rag_llm_tokens_total Total tokens used
# TYPE rag_llm_tokens_total counter
rag_llm_tokens_total{type="prompt"} 1780000
rag_llm_tokens_total{type="completion"} 256000
rag_llm_tokens_total{type="total"} 2036000

# HELP rag_cache_hit_ratio Cache hit ratio per tier
# TYPE rag_cache_hit_ratio gauge
rag_cache_hit_ratio{cache_type="embedding"} 0.87
rag_cache_hit_ratio{cache_type="rerank"} 0.62
rag_cache_hit_ratio{cache_type="response"} 0.34

# HELP rag_confidence_score Confidence score distribution
# TYPE rag_confidence_score histogram
rag_confidence_score_bucket{le="0.1"} 23
rag_confidence_score_bucket{le="0.3"} 89
rag_confidence_score_bucket{le="0.5"} 234
rag_confidence_score_bucket{le="0.7"} 876
rag_confidence_score_bucket{le="0.9"} 1390
rag_confidence_score_bucket{le="+Inf"} 1423

# HELP rag_feedback_total Total feedback submissions
# TYPE rag_feedback_total counter
rag_feedback_total{rating="positive"} 156
rag_feedback_total{rating="negative"} 34
```

---

### `POST /v1/auth/login`

Generate a JWT token for the given credentials. In production deployments, this validates against Keycloak/LDAP. For air-gapped deployments, it uses a credential store configured via `AUTH_VALID_USERS` environment variable.

#### Request Schema

```json
{
  "username": "string (required)",
  "password": "string (required)",
  "expires_in_hours": "integer (optional, default: 24)"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `username` | string | Yes | — | Username |
| `password` | string | Yes | — | Password |
| `expires_in_hours` | integer | No | `24` | Token expiry in hours (1–720) |

#### Response Schema (200 OK)

```json
{
  "access_token": "string (JWT)",
  "token_type": "bearer",
  "expires_in": "integer (seconds)",
  "user_id": "string",
  "username": "string",
  "roles": ["string"],
  "groups": ["string"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `access_token` | string | Signed JWT to include in `Authorization: Bearer` header |
| `token_type` | string | Always `"bearer"` |
| `expires_in` | integer | Seconds until token expires |
| `user_id` | string | Unique user identifier |
| `username` | string | Login username |
| `roles` | array | Assigned roles (e.g., `["admin"]`, `["viewer"]`, `["editor"]`) |
| `groups` | array | Assigned groups for document-level access control |

---

### `POST /v1/auth/refresh`

Refresh an existing JWT token. Validates the current token (must not be expired) and issues a new one with the same claims but a fresh expiration timestamp.

#### Request Schema

```json
{
  "token": "string (required)"
}
```

**Headers:** `Authorization: Bearer <current-token>`

#### Response Schema (200 OK)

```json
{
  "access_token": "string (JWT)",
  "token_type": "bearer",
  "expires_in": "integer (seconds)"
}
```

---

### `GET /v1/auth/me`

Return the current authenticated user's context including roles, groups, and access level.

#### Request

```http
GET /v1/auth/me HTTP/1.1
Authorization: Bearer <your-token>
```

#### Response Schema (200 OK)

```json
{
  "user_id": "string",
  "username": "string",
  "roles": ["string"],
  "groups": ["string"],
  "access_level": "string (internal | external | restricted)",
  "is_admin": "boolean",
  "is_authenticated": "boolean"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `access_level` | string | `internal` (full access), `external` (limited sources), `restricted` (specific documents only) |
| `is_admin` | boolean | Whether user has admin role |
| `is_authenticated` | boolean | Always `true` when auth succeeds |

---

### `POST /v1/feedback`

Submit expert feedback on a RAG response. Used by the HITL dashboard and programmatic feedback collection. Positive feedback with corrections triggers enrichment — the corrected Q&A pair is indexed back into Qdrant for future retrieval improvement.

#### Request Schema

```json
{
  "feedback_id": "string (required)",
  "rating": "string (positive | negative)",
  "correction": "string (optional)",
  "comment": "string (optional)"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `feedback_id` | string | Yes | The `rag_feedback_id` from the original chat completion response |
| `rating` | string | Yes | `"positive"` or `"negative"` |
| `correction` | string | No | Corrected answer text. When provided with `rating: "positive"`, triggers enrichment indexing |
| `comment` | string | No | Free-text expert comment (e.g., why the response was incorrect) |

#### Response Schema (200 OK)

```json
{
  "status": "ok",
  "message": "Feedback recorded"
}
```

#### Enrichment Behavior

When `ENRICHMENT_ENABLED=true` and the feedback includes a `correction`:

1. The original query and corrected answer are paired as a Q&A chunk
2. The chunk is embedded and indexed into Qdrant with `source_type: "feedback_enrichment"`
3. Future similar queries will retrieve the corrected answer as context

Enrichment failure is **non-blocking** — the feedback is still recorded even if indexing fails.

---

### `POST /v1/admin/warmup`

Pre-load embedder, reranker, and SLM models into GPU/CPU memory before serving traffic. Eliminates cold-start latency on first request. Optionally warms up the LLM backend.

#### Request

```http
POST /v1/admin/warmup HTTP/1.1
Authorization: Bearer <admin-token>
```

No request body required. Requires admin role when `AUTH_ENABLED=true`.

#### Response Schema (200 OK)

```json
{
  "status": "ok",
  "warmed_components": {
    "embedder": "ok",
    "reranker": "ok",
    "slm": "ok",
    "llm": "skipped"
  },
  "duration_ms": 2500
}
```

| Field | Type | Description |
|-------|------|-------------|
| `warmed_components` | object | Status per component: `ok`, `skipped` (disabled), or `error: <message>` |
| `duration_ms` | integer | Total warm-up time in milliseconds |

**Warm-up behavior:**

- Embedder: Runs a single `encode("warmup")` call to trigger model loading
- Reranker: Runs a single dummy pair scoring to initialize the cross-encoder
- SLM: Sends a single-token completion (`"ping"`) to the SLM endpoint
- LLM: Skipped by default. Set `WARMUP_LLM=true` to include a single-token completion

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/admin/warmup \
  -H "Authorization: Bearer <admin-token>"
```

---

### `POST /webhook/confluence`

Receive Confluence webhook events for real-time indexing. Validates HMAC-SHA256 signatures and enqueues events into Redis Streams for processing by the streaming ETL pipeline.

#### Request

```http
POST /webhook/confluence HTTP/1.1
Content-Type: application/json
X-Confluence-Webhook-Signature: sha256=<hmac-signature>
```

#### Request Body

```json
{
  "event": "page_created | page_updated | page_removed",
  "page": {
    "id": "string",
    "title": "string",
    "spaceKey": "string",
    "version": "integer",
    "url": "string"
  },
  "timestamp": "string (ISO 8601)"
}
```

#### Response Schema (200 OK)

```json
{
  "status": "accepted",
  "event_id": "string",
  "message": "Event enqueued for processing"
}
```

| Field | Description |
|-------|-------------|
| `status` | Always `"accepted"` — events are processed asynchronously |
| `event_id` | Unique ID for tracking the event through the streaming pipeline |
| `message` | Human-readable status |

#### Error Responses

| HTTP Status | Description |
|-------------|-------------|
| **401** | Invalid or missing `X-Confluence-Webhook-Signature` header |
| **400** | Malformed event body or unsupported event type |
| **503** | Redis Streams unavailable (event not enqueued) |

#### cURL Example

```bash
curl -X POST http://localhost:8080/webhook/confluence \
  -H "Content-Type: application/json" \
  -H "X-Confluence-Webhook-Signature: sha256=abc123..." \
  -d '{
    "event": "page_updated",
    "page": {
      "id": "12345",
      "title": "Deployment Guide",
      "spaceKey": "ENG",
      "version": 3,
      "url": "https://confluence.example.com/display/ENG/Deployment+Guide"
    },
    "timestamp": "2026-06-26T10:30:00Z"
  }'
```

---

### Response Compression

All API responses support gzip and brotli compression via the `Accept-Encoding` request header. Compression is applied to responses larger than 1 KB (configurable via `COMPRESSION_MIN_SIZE`).

#### Behavior

| Header | Value | Effect |
|--------|-------|--------|
| `Accept-Encoding: gzip` | gzip | Response compressed with gzip (level 6) |
| `Accept-Encoding: br` | brotli | Response compressed with brotli (level 4) |
| `Accept-Encoding: gzip, br` | br or gzip | Brotli preferred, gzip as fallback |
| (not present) | — | Uncompressed response |

**Compression applies to:**
- All JSON responses (chat completions, health checks, models list, etc.)
- Error responses (when body > 1 KB)
- Prometheus metrics (`/metrics`)

**Compression does NOT apply to:**
- Streaming SSE responses (`text/event-stream`) — uses `Transfer-Encoding: chunked` instead
- Responses smaller than `COMPRESSION_MIN_SIZE` (default: 1 KB)

#### Configuration

```bash
# Enable response compression (default: true)
COMPRESSION_ENABLED=true

# Minimum response size in bytes to apply compression (default: 1000)
COMPRESSION_MIN_SIZE=1000

# Compression level: gzip 1-9, brotli 0-11 (default: 6 for gzip, 4 for brotli)
COMPRESSION_LEVEL=6
```

#### Performance Benchmarks

| Content Type | Uncompressed | gzip | Brotli | Reduction |
|-------------|-------------|------|--------|-----------|
| JSON (rag_sources) | ~45 KB | ~15 KB | ~13 KB | 65–72% |
| JSON (chat completion) | ~12 KB | ~3.5 KB | ~3.1 KB | 70–75% |
| HTML (health dashboard) | ~28 KB | ~6 KB | ~5.5 KB | 75–80% |
| Prometheus metrics | ~18 KB | ~4 KB | ~3.8 KB | 75–80% |

CPU overhead: < 5ms for gzip, < 15ms for brotli per request.

---

## Error Codes

All errors follow a consistent format:

```json
{
  "detail": "string (human-readable error message)",
  "error_type": "string (machine-readable error code, optional)"
}
```

| HTTP Status | Error Type | Meaning | Typical Cause | Remediation |
|-------------|-----------|---------|---------------|-------------|
| **200** | — | Success | Normal operation | — |
| **400** | `bad_request` | Invalid request | Missing `messages` field, empty user query, invalid JSON, or `model` field missing | Check request body against schema |
| **400** | `validation_error` | Input validation failed | `messages.content` is empty string, `temperature` out of range, unknown `role` value | Validate input fields |
| **401** | `unauthorized` | Missing or invalid credentials | No `Authorization` header, expired JWT, invalid signature | Re-login via `/v1/auth/login` |
| **403** | `forbidden` | Insufficient permissions | User lacks required role or group for requested document source | Request access from admin |
| **404** | `not_found` | Resource not found | Feedback ID doesn't match any recorded interaction | Verify `rag_feedback_id` from response |
| **413** | `payload_too_large` | Request body too large | Message list exceeds proxy's configured limit | Reduce message count or content length |
| **429** | `rate_limited` | Too many requests | Rate limit exceeded per IP | Wait for `Retry-After` seconds; check `X-RateLimit-*` headers |
| **500** | `internal_error` | Unhandled exception | Bug in pipeline code, unexpected None value, or dependency crash | Check proxy logs; report bug |
| **502** | `upstream_error` | LLM backend returned invalid response | LLM provider returned malformed JSON or HTTP error | Check LLM backend health; verify `LLM_ENDPOINT` |
| **503** | `service_unavailable` | Component degradation | LLM or Qdrant unreachable, health check returns degraded status | Check Docker services; verify network connectivity |
| **504** | `timeout` | LLM request timed out | Generation took longer than `REQUEST_TIMEOUT` (default 120s) | Increase `REQUEST_TIMEOUT` or reduce `max_tokens` |

### Error Response Examples

**400 — Missing required field:**
```json
{
  "detail": "Field 'messages' is required",
  "error_type": "bad_request"
}
```

**401 — Expired token:**
```json
{
  "detail": "Token has expired. Please refresh or re-login.",
  "error_type": "unauthorized"
}
```

**429 — Rate limited:**
```json
{
  "detail": "Rate limit exceeded. Try again later.",
  "error_type": "rate_limited"
}
```

**500 — Internal error (production mode, details masked):**
```json
{
  "detail": "An internal error occurred. Please check logs or contact support.",
  "error_type": "internal_error"
}
```

---

## Multi-Provider Support

The proxy supports multiple LLM providers through the `LLM_PROVIDER_TYPE` environment variable. Each provider is handled by a dedicated adapter in `provider_adapter.py` that transparently translates between the internal OpenAI-compatible format and the provider-specific API format.

### Supported Providers

| Provider | `LLM_PROVIDER_TYPE` | Description |
|----------|---------------------|-------------|
| **OpenAI-compatible** | `openai` | vLLM, llama.cpp, Ollama, LiteLLM, and any OpenAI-compatible endpoint |
| **Anthropic** | `anthropic` | Claude API via Anthropic Messages API |
| **Ollama** | `ollama` | Native Ollama API (minor differences from OpenAI-compatible) |
| **Generic** | `generic` | Custom REST API with configurable request/response transforms |

### Configuration

Set in `proxy/.env`:

```bash
# Provider type (openai, anthropic, ollama, generic)
LLM_PROVIDER_TYPE=openai

# LLM endpoint URL
LLM_ENDPOINT=http://localhost:8000/v1

# Model name to request from the provider
LLM_MODEL_NAME=your-model-name

# API key (if required by the provider)
LLM_API_KEY=your-api-key
```

### Provider Translation Matrix

| Format | OpenAI | Anthropic | Ollama |
|--------|--------|-----------|--------|
| System prompt | `messages[].role: "system"` | Top-level `system` field | `messages[].role: "system"` |
| Tool definition | `tools[].function` | `tools[].input_schema` | `tools[].function` |
| Tool call ID | `tool_calls[].id` | `content[].id` | `tool_calls[].id` |
| Tool call args | JSON string | JSON object | JSON string |
| Tool result | `role: "tool"`, `tool_call_id` | `role: "user"`, `content: [{type: "tool_result"}]` | `role: "tool"`, `tool_call_id` |
| Stream events | `chat.completion.chunk` | `content_block_delta` | `chat.completion.chunk` |
| Endpoint path | `/v1/chat/completions` | `/v1/messages` | `/api/chat` |

---

## Environment Variable Reference

All proxy configuration via environment variables (see `proxy/.env` and `proxy/app/config.py`).

### Required

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_HOST` | `localhost` | Qdrant server hostname |
| `QDRANT_PORT` | `6333` | Qdrant gRPC port |
| `LLM_ENDPOINT` | `http://localhost:8000/v1` | LLM provider endpoint URL |
| `LLM_MODEL_NAME` | (empty) | Model name to request from LLM endpoint |
| `LLM_PROVIDER_TYPE` | `openai` | Provider type: `openai`, `anthropic`, `ollama`, `generic` |

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
| `RATE_LIMIT_PER_MINUTE` | `60` | Sustained requests per minute per IP |
| `RATE_LIMIT_BURST` | `10` | Burst capacity above sustained rate |
| `LOG_FORMAT` | `text` | Log format: `text` or structured `json` |
| `LOG_REQUESTS` | `true` | Log each request to JSONL file |
| `LOG_DIR` | `./logs` | Directory for log files |
| `AUTH_ENABLED` | `false` | Enable JWT authentication |
| `JWT_SECRET` | (empty) | JWT signing secret (generate: `openssl rand -hex 32`) |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRATION_HOURS` | `24` | Token expiry in hours |
| `AUTH_VALID_USERS` | (empty) | Comma-separated `user:hash:role` for air-gapped auth |
| `LLM_API_KEY` | (empty) | API key for the LLM provider |
| `ENRICHMENT_ENABLED` | `false` | Index corrected Q&A pairs from feedback |

### Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_CHUNKS_RETRIEVAL` | `50` | Chunks to retrieve from Qdrant |
| `MAX_CHUNKS_AFTER_RERANK` | `20` | Chunks after cross-encoder reranking |
| `MAX_RETRIEVAL_LOOPS` | `3` | Max rewrite iterations in LangGraph |
| `SUFFICIENCY_THRESHOLD` | `0.6` | Score threshold for context sufficiency |
| `EMBEDDER_DEVICE` | `cpu` | Device for embedding model: `cpu` or `cuda` |
| `RERANKER_BATCH_SIZE` | `32` | Batch size for cross-encoder |
| `REQUEST_TIMEOUT` | `120` | LLM request timeout in seconds |
| `MAX_RETRIES` | `3` | Retry attempts on LLM connection failure |
| `RETRY_DELAY` | `1.0` | Delay between retries in seconds |
| `WORKERS` | `1` | Uvicorn worker processes (keep at 1 for shared caches) |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `COMPRESSION_ENABLED` | `true` | Enable gzip/brotli response compression |
| `COMPRESSION_MIN_SIZE` | `1000` | Minimum response size in bytes to compress |
| `COMPRESSION_LEVEL` | `6` | Compression level (1-9 for gzip, 0-11 for brotli) |
| `WARMUP_LLM` | `false` | Include LLM in model warm-up |
| `WEBHOOK_SECRET` | (empty) | Shared secret for Confluence/GitLab webhook HMAC verification |
| `STREAMING_ETL_ENABLED` | `false` | Enable Redis Streams based streaming ETL pipeline |
| `REDIS_STREAMS_URL` | `redis://localhost:6379` | Redis Streams connection URL for streaming ETL |

### SLM / Small Language Model

| Variable | Default | Description |
|----------|---------|-------------|
| `SLM_ENDPOINT` | (empty) | SLM endpoint for routing/decomposition. Leave empty to disable SLM (fallback to regex heuristics). |
| `SLM_MODEL_NAME` | (empty) | SLM model name |
| `SLM_API_KEY` | (empty) | API key for SLM |
| `SLM_MAX_TOKENS` | `256` | Max tokens for SLM responses |

---

## Endpoint Summary

| Method | Endpoint | Auth | Rate Limited | Description |
|--------|----------|------|-------------|-------------|
| `POST` | `/v1/chat/completions` | Optional | Yes | Chat completion with RAG augmentation (streaming + non-streaming) |
| `GET` | `/v1/models` | No | No | List available models |
| `GET` | `/v1/health` | No | No | Health check with component status |
| `GET` | `/v1/health/live` | No | No | Liveness probe (process alive) |
| `GET` | `/v1/health/ready` | No | No | Readiness probe (dependencies ready) |
| `GET` | `/metrics` | No | No | Prometheus metrics in OpenMetrics format |
| `POST` | `/v1/auth/login` | No | Yes | JWT token generation |
| `POST` | `/v1/auth/refresh` | Yes | No | Token refresh |
| `GET` | `/v1/auth/me` | Yes | No | Current user context |
| `POST` | `/v1/feedback` | No | No | Submit expert feedback |
| `POST` | `/v1/admin/warmup` | Yes (admin) | No | Pre-load models into GPU/CPU memory |
| `POST` | `/webhook/confluence` | No (HMAC) | No | Receive Confluence webhook events for streaming ETL |

---

## SDK Usage Examples

### Python (openai package)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed"  # placeholder when auth is disabled
)

# ── Non-streaming with RAG extensions ──
response = client.chat.completions.create(
    model="rag-proxy",  # use "rag-proxy" for full RAG pipeline
    messages=[
        {"role": "system", "content": "You are a technical documentation assistant."},
        {"role": "user", "content": "What is the project structure and how does the ETL pipeline work?"}
    ],
    temperature=0.2,
    max_tokens=4096,
    extra_body={
        "rag_version": "2026-01-15",      # request specific doc version
        "rag_force_refresh": False         # use cache if available
    }
)

print(f"Answer: {response.choices[0].message.content}")
print(f"Confidence: {response.rag_confidence}")
print(f"Feedback ID: {response.rag_feedback_id}")

# ── Streaming ──
stream = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Explain the deployment process."}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")

# ── Tool calling ──
response = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Search for authentication documentation."}],
    tools=[{
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search the RAG knowledge base",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "source_filter": {"type": "string", "enum": ["confluence", "jira", "gitlab", "all"]}
                },
                "required": ["query"]
            }
        }
    }],
    tool_choice="auto"
)

if response.choices[0].message.tool_calls:
    for tc in response.choices[0].message.tool_calls:
        print(f"Tool called: {tc.function.name}({tc.function.arguments})")

# ── Submit feedback ──
import requests
requests.post("http://localhost:8080/v1/feedback", json={
    "feedback_id": response.rag_feedback_id,
    "rating": "positive",
    "comment": "Accurate and well-sourced answer."
})
```

### cURL

```bash
# ── Non-streaming chat completion ──
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "system", "content": "You are a documentation assistant."},
      {"role": "user", "content": "How many ADRs are there and what do they cover?"}
    ],
    "temperature": 0.2,
    "max_tokens": 1024,
    "rag_version": "2026-03",
    "rag_force_refresh": false
  }' | jq '.'

# ── Streaming ──
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "Summarize the deployment process."}],
    "stream": true
  }'

# ── Tool calling ──
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "Calculate 25 * 17 + 3"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "calculator",
        "description": "Perform arithmetic operations",
        "parameters": {
          "type": "object",
          "properties": {
            "expression": {"type": "string", "description": "Arithmetic expression to evaluate"}
          },
          "required": ["expression"]
        }
      }
    }]
  }' | jq '.choices[0].message.tool_calls'

# ── Health check ──
curl -s http://localhost:8080/v1/health | jq '.'

# ── List models ──
curl -s http://localhost:8080/v1/models | jq '.'

# ── Prometheus metrics ──
curl -s http://localhost:8080/metrics | head -20

# ── Auth login ──
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "securepass", "expires_in_hours": 48}' | jq '.'

# ── Token refresh ──
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{"token": "eyJhbGciOi..."}' | jq '.'

# ── User info ──
curl -s http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer eyJhbGciOi..." | jq '.'

# ── Submit feedback ──
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "feedback_id": "fbk_1719057600_a1b2c3d4",
    "rating": "positive",
    "comment": "Answer was accurate and well-cited."
  }' | jq '.'

# ── Submit negative feedback with correction ──
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "feedback_id": "fbk_1719057600_d4e5f6g7",
    "rating": "negative",
    "correction": "The proxy is deployed via docker-compose up -d from the proxy/ directory, not the project root.",
    "comment": "Answer referenced wrong directory."
  }' | jq '.'
```

### JavaScript / TypeScript

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "not-needed",
});

// Non-streaming with RAG options
const completion = await client.chat.completions.create({
  model: "rag-proxy",
  messages: [
    { role: "system", content: "You are a documentation assistant." },
    { role: "user", content: "What database does the system use for vector search?" },
  ],
  temperature: 0.2,
  max_tokens: 1024,
  // @ts-expect-error — RAG-specific extensions
  rag_version: "2026-03",
});

console.log("Answer:", completion.choices[0].message.content);
// @ts-expect-error — RAG-specific extensions
console.log("Confidence:", completion.rag_confidence);
// @ts-expect-error — RAG-specific extensions
console.log("Sources:", completion.rag_sources);

// Streaming
const stream = await client.chat.completions.create({
  model: "your-model-name",
  messages: [{ role: "user", content: "Explain the MCP server setup." }],
  stream: true,
});

for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content ?? "");
}

// Tool calling
const toolResult = await client.chat.completions.create({
  model: "your-model-name",
  messages: [{ role: "user", content: "Search for deployment docs." }],
  tools: [{
    type: "function" as const,
    function: {
      name: "search_docs",
      description: "Search the knowledge base",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query" },
          max_results: { type: "integer", default: 5 },
        },
        required: ["query"],
      },
    },
  }],
  tool_choice: "auto",
});

console.log(toolResult.choices[0].message.tool_calls);

// Submit feedback
const feedbackResponse = await fetch("http://localhost:8080/v1/feedback", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    feedback_id: completion.rag_feedback_id,
    rating: "positive",
    comment: "Excellent answer with proper citations.",
  }),
});
console.log(await feedbackResponse.json());
```
