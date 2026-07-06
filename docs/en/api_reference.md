# API Reference — RAG System v2.0

The RAG Proxy exposes an **OpenAI-compatible API** on port `8080`. Any OpenAI client can use it as a drop-in replacement — just point `base_url` to `http://<host>:8080/v1`. The proxy adds RAG-specific extensions for feedback, confidence scoring, source traceability, tool calling (including live Confluence/Jira/GitLab queries), multi-language support, and model evolution management.

---

## Base URL

```
http://<proxy-host>:8080/v1
```

All endpoints are prefixed with `/v1` to match the OpenAI API convention. The `/metrics` endpoint is at the root level. Health probes are at `/v1/health`, `/v1/health/live`, and `/v1/health/ready`.

---

## Authentication

### Overview

Authentication uses JWT token pairs (access + refresh). When disabled (`AUTH_ENABLED=false`, the default), the proxy accepts all requests without authentication. When enabled, all endpoints except `/v1/auth/login`, `/v1/auth/register`, `/v1/auth/refresh`, `/v1/health*`, `/v1/models`, `/v1/widget*`, and `/metrics` require a valid JWT.

Four RBAC roles (hierarchical):
| Role | Rank | Access |
|------|------|--------|
| `admin` | 4 (highest) | All endpoints including `/v1/admin/*` |
| `expert` | 3 | Chat + feedback submission |
| `user` | 2 | Chat only |
| `read_only` | 1 | Models list + health checks |

### Configuration

```bash
# Enable authentication
AUTH_ENABLED=true

# JWT signing secret (generate with: openssl rand -hex 32)
JWT_SECRET=your-256-bit-secret
JWT_ALGORITHM=HS256

# Access token lifetime (minutes)
ACCESS_TOKEN_MINUTES=60

# Refresh token lifetime (days)
REFRESH_TOKEN_DAYS=7

# SQLite user database path
USER_DB_PATH=./data/users.db

# Keycloak OIDC integration (optional)
KEYCLOAK_URL=https://auth.example.com
KEYCLOAK_REALM=master
KEYCLOAK_CLIENT_ID=rag-proxy
```

---

## Endpoints

### `POST /v1/auth/register`

Register a new user account. Stores user with bcrypt-hashed password in SQLite. Rate-limited to 3 registrations per IP per minute.

**Auth required:** No

#### Request Schema

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `username` | string | Yes | 2–64 chars | Desired username |
| `password` | string | Yes | 8–128 chars | Password (bcrypt-hashed on storage) |
| `email` | string | No | — | Optional email address |

```json
{
  "username": "alice",
  "password": "s3cur3P@ssw0rd!",
  "email": "alice@example.com"
}
```

#### Response Schema (201 Created)

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string | Unique user identifier (UUID) |
| `username` | string | Confirmed username |
| `created_at` | string | ISO 8601 creation timestamp |

```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "username": "alice",
  "created_at": "2026-07-06T14:30:00Z"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| **400** | `"Registration is not enabled. Set AUTH_ENABLED=true."` |
| **409** | `"Username 'alice' already exists"` |
| **429** | `"Too many registration attempts. Try again in N seconds."` |

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "s3cur3P@ssw0rd!", "email": "alice@example.com"}'
```

---

### `POST /v1/auth/login`

Authenticate user and return a token pair (access + refresh). Validates against SQLite user database with bcrypt password verification. Falls back to LDAP/AD when `AD_ENABLED=true`. Rate-limited to 5 attempts per username+IP in a 5-minute window.

**Auth required:** No

#### Request Schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `username` | string | Yes | — | Account username |
| `password` | string | Yes | — | Account password |
| `expires_in_hours` | integer | No | `24` | Access token expiry in hours (1–720) |

```json
{
  "username": "alice",
  "password": "s3cur3P@ssw0rd!",
  "expires_in_hours": 24
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `access_token` | string | Signed JWT for use in `Authorization: Bearer` header |
| `refresh_token` | string | Opaque token for token refresh (one-time use) |
| `token_type` | string | Always `"bearer"` |
| `expires_in` | integer | Seconds until access token expires |
| `user_id` | string | Unique user identifier |
| `username` | string | Login username |
| `roles` | array | Assigned roles (e.g., `["admin"]`, `["user"]`) |
| `groups` | array | Assigned groups for document-level access control |

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4tZXhhbXBsZQ...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "username": "alice",
  "roles": ["user"],
  "groups": ["engineering"]
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| **401** | `"Invalid credentials"` |
| **403** | `"Account is deactivated"` |
| **429** | `"Too many login attempts. Try again in N seconds."` |

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "s3cur3P@ssw0rd!"}'
```

---

### `POST /v1/auth/refresh`

Exchange a refresh token (or valid access token) for a new token pair. Tries refresh token first; falls back to validating as an access token for backward compatibility.

**Auth required:** No (token passed in body)

#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | string | Yes | Refresh token or valid access token |

```json
{
  "token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4tZXhhbXBsZQ..."
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `access_token` | string | New signed JWT |
| `refresh_token` | string | New opaque refresh token (previous one consumed) |
| `token_type` | string | Always `"bearer"` |
| `expires_in` | integer | Seconds until new access token expires |

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "bmV3LXJlZnJlc2gtdG9rZW4tZXhhbXBsZQ...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| **400** | `"Authentication is not enabled"` |
| **401** | `"Invalid or expired refresh token"` |

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4tZXhhbXBsZQ..."}'
```

---

### `POST /v1/auth/logout`

Revoke refresh tokens and optionally blacklist the current access token.

**Auth required:** Optional (uses `get_optional_auth_context`)

#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `refresh_token` | string | No | Revoke a specific refresh token |
| `all_sessions` | boolean | No | Revoke ALL refresh tokens for the authenticated user |

```json
{
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4tZXhhbXBsZQ...",
  "all_sessions": false
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"ok"` |
| `message` | string | Human-readable confirmation |

```json
{
  "status": "ok",
  "message": "Logged out successfully"
}
```

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/auth/logout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{"all_sessions": true}'
```

---

### `GET /v1/auth/me`

Return the current authenticated user's context including roles, groups, and access level.

**Auth required:** Yes (when `AUTH_ENABLED=true`)

#### Request Headers

```
Authorization: Bearer <access-token>
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | string | Unique user identifier |
| `username` | string | Login username |
| `roles` | array | Assigned roles |
| `groups` | array | Assigned groups |
| `access_level` | string | `internal` (full access), `external` (limited sources), `restricted` (specific documents only), or `public` (anonymous) |
| `is_admin` | boolean | Whether user has admin role |
| `is_authenticated` | boolean | `true` when authenticated, `false` for anonymous |

```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "username": "alice",
  "roles": ["user", "expert"],
  "groups": ["engineering", "platform"],
  "access_level": "internal",
  "is_admin": false,
  "is_authenticated": true
}
```

#### cURL Example

```bash
curl http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### `GET /v1/health`

Health check for the proxy and all configured dependencies.

**Auth required:** No

#### Response Schema (200 OK — Healthy)

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Overall status: `"ok"` or `"degraded"` |
| `timestamp` | string | ISO 8601 timestamp |
| `components.qdrant` | string | `"ok"` or `"error: <message>"` |
| `components.llm` | string | `"ok"`, `"unhealthy"`, or `"error: <message>"` |

```json
{
  "status": "ok",
  "timestamp": "2026-07-06T14:30:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "ok"
  }
}
```

#### Response Schema (503 — Degraded)

```json
{
  "status": "degraded",
  "timestamp": "2026-07-06T14:30:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "error: Connection refused"
  }
}
```

#### cURL Example

```bash
curl http://localhost:8080/v1/health
```

---

### `GET /v1/health/live`

Kubernetes-compatible liveness probe. Returns 200 as long as the process is alive.

**Auth required:** No

#### Response (200 OK)

```json
{
  "status": "alive",
  "timestamp": "2026-07-06T14:30:00Z"
}
```

#### cURL Example

```bash
curl http://localhost:8080/v1/health/live
```

---

### `GET /v1/health/ready`

Kubernetes-compatible readiness probe. Returns 200 when Qdrant and LLM are reachable. Returns 503 if critical dependencies are down.

**Auth required:** No

#### Response (200 OK — Ready)

```json
{
  "status": "ready",
  "timestamp": "2026-07-06T14:30:00Z",
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
  "timestamp": "2026-07-06T14:30:00Z",
  "components": {
    "qdrant": "unavailable",
    "llm": "unavailable"
  }
}
```

#### cURL Example

```bash
curl http://localhost:8080/v1/health/ready
```

---

### `POST /v1/chat/completions`

Chat completion with RAG augmentation. Accepts standard OpenAI parameters plus RAG-specific extensions. This is the primary endpoint for all RAG queries.

**Auth required:** Yes (when `AUTH_ENABLED=true`)

#### Request Schema

```json
{
  "model": "string (required)",
  "messages": [
    {
      "role": "string (system | user | assistant | tool)",
      "content": "string (required)"
    }
  ],
  "temperature": "number (0–2, default: 0.2)",
  "top_p": "number (0–1, default: 0.95)",
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
  "rag_force_refresh": "boolean (default: false)",
  "rag_skip_generation": "boolean (default: false)",
  "rag_return_chunks": "boolean (default: false)",
  "rag_top_k": "integer (optional)",
  "federation_silo": "string (optional)",
  "federation_mode": "string (optional: auto | local | remote)"
}
```

#### Standard Parameters

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | string | Yes | — | Model ID. Use your configured `LLM_MODEL_NAME` or `"rag-proxy"` to enable the full RAG pipeline |
| `messages` | array | Yes | — | Chat messages. System prompt is incorporated into the RAG context |
| `temperature` | number | No | `0.2` | Sampling temperature (0–2). Lower = more deterministic |
| `top_p` | number | No | `0.95` | Nucleus sampling threshold |
| `max_tokens` | integer | No | `4096` | Maximum tokens in the generated response |
| `stream` | boolean | No | `false` | Enable Server-Sent Events streaming |
| `stop` | array | No | — | Up to 4 stop sequences |
| `presence_penalty` | number | No | — | Penalize repeated tokens (-2.0 to 2.0) |
| `frequency_penalty` | number | No | — | Penalize frequent tokens (-2.0 to 2.0) |
| `tools` | array | No | — | Available function/tool definitions |
| `tool_choice` | string/object | No | `"auto"` | Tool selection: `"none"`, `"auto"`, or specific function |

#### RAG-Specific Parameters

These parameters extend the standard OpenAI schema. They are silently ignored by standard OpenAI clients.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `rag_version` | string | No | — | Request context from a specific document version. Accepts ISO date (`"2026-01-15"`), SHA-256 prefix (`"a1b2c3d4"`), or version tag (`"v2.1"`). Filters retrieved chunks to match the specified version |
| `rag_force_refresh` | boolean | No | `false` | Bypass Redis response cache. Forces fresh retrieval, reranking, and LLM generation |
| `rag_skip_generation` | boolean | No | `false` | Federation: skip LLM generation entirely, return only retrieved chunks |
| `rag_return_chunks` | boolean | No | `false` | Federation: include full chunk text bodies in the response |
| `rag_top_k` | integer | No | — | Federation: override the default `MAX_CHUNKS_RETRIEVAL` for this request only |
| `federation_silo` | string | No | — | Federation: route query to a specific deployment silo by name |
| `federation_mode` | string | No | `"auto"` | Federation: `"auto"` (local + remote merge), `"local"` (local only), `"remote"` (remote only) |

#### Response Schema (200 OK — Non-Streaming)

```json
{
  "id": "rag_1719057600_a1b2c3d4",
  "object": "chat.completion",
  "created": 1719057600,
  "model": "rag-proxy",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The deployment process involves..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 1240,
    "completion_tokens": 156,
    "total_tokens": 1396
  },
  "rag_feedback_id": "fbk_1719057600_d4e5f6g7",
  "rag_confidence": 0.87,
  "rag_sources": [
    {
      "chunk_id": "a1b2c3d4e5f6789012345678901234567890abcd12345678901234567890abcdef",
      "source": "confluence",
      "title": "Deployment Guide",
      "version": "2026-03-15",
      "relevance": 0.9231,
      "text_preview": "The proxy is deployed via docker-compose up -d from the proxy/ directory. Ensure Qdrant, Redis, and Neo4j are running before starting the proxy...",
      "silo_id": "us-east-1"
    }
  ]
}
```

#### RAG Response Extensions

| Field | Type | Description |
|-------|------|-------------|
| `rag_feedback_id` | string | Unique ID for submitting expert feedback via `/v1/feedback`. Generated per response. Format: `fbk_<unix_timestamp>_<random_hex>` |
| `rag_confidence` | float | Confidence score (0.0–1.0). Based on context sufficiency, answer length vs. context ratio, and uncertainty phrase detection. **Interpretation:** ≥0.8 = high confidence, 0.5–0.8 = moderate (should verify), <0.5 = low (needs review) |
| `rag_sources` | array | Retrieved chunks used to generate the response |

#### `rag_sources` Entry Schema

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | string | SHA-256 content-addressable hash of the chunk |
| `source` | string | Source type: `"confluence"`, `"jira"`, `"gitlab"`, `"document"`, `"book"`, `"chat"`, `"feedback_enrichment"` |
| `title` | string | Document or page title |
| `version` | string | Formatted version date or tag |
| `relevance` | float | Re-ranked relevance score (post-reranker) |
| `text_preview` | string | First 200 characters of the chunk text |
| `silo_id` | string | Federation: identifier of the deployment silo where this chunk was retrieved |

#### Streaming Response (SSE)

When `"stream": true`, the response uses Server-Sent Events with `text/event-stream` content type:

```
data: {"role":"initial_chunk"}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"rag-proxy","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"rag-proxy","choices":[{"index":0,"delta":{"content":"The"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"rag-proxy","choices":[{"index":0,"delta":{"content":" proxy"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"rag-proxy","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: {"rag_feedback_id":"fbk_1719057600_d4e5f6g7","rag_confidence":0.87}

data: [DONE]
```

**Streaming behavior:**
- An empty initial chunk (`{"role":"initial_chunk"}`) is sent immediately to reduce Time-To-First-Token (TTFT)
- `delta` contains incremental content (instead of `message`)
- `finish_reason` is `null` until the final chunk
- RAG extensions (`rag_feedback_id`, `rag_confidence`) appear in a separate metadata chunk before `[DONE]`
- `rag_sources` is available only in non-streaming mode for efficiency
- The `[DONE]` sentinel terminates the stream

#### RAG Pipeline (Under the Hood)

1. **Query Analysis** — SLM classifies intent (5 classes: factual, procedural, comparison, troubleshooting, meta), optionally decomposes into sub-queries, extracts entities
2. **HyDE Query Expansion** — Generates a hypothetical document from the query, embeds it, and uses it for a second-pass retrieval alongside the original query
3. **Hybrid Retrieval** — Dense (BGE-M3 1024-dim) + sparse (lexical BM25-style) vectors searched in Qdrant with RRF fusion (k=60). Returns up to `MAX_CHUNKS_RETRIEVAL` (default 50) chunks
4. **Access Control Filtering** — Row-level filtering by user roles, groups, and namespace
5. **Live Source Query** (optional) — Direct API calls to Confluence/Jira/GitLab for real-time data
6. **Retrieval Quality Evaluation (CRAG)** — Scores results (confidence 0.0–1.0) based on score distribution, coverage ratio, result count, and recency decay. Maps to action: `USE`, `REWRITE`, `EXPAND`, or `FALLBACK`
7. **Query Rewriting** (if needed) — SLM or LLM rewrites ambiguous/failed queries; up to `MAX_RETRIEVAL_LOOPS=3` iterations
8. **Cross-Encoder Reranking** — MiniLM-L-6-v2 scores top-N candidates, selects top `MAX_CHUNKS_AFTER_RERANK` (default 20)
9. **LongContextReorder** — Re-ranks documents to combat "lost in the middle" effect
10. **Graph Expansion** (optional) — Neo4j multi-hop traversal for entity enrichment
11. **Deduplication & Version Filtering** — SHA-256 hash dedup; filtered by `rag_version` if specified
12. **Token Budget Allocation** — Smart budget across system prompt, context, response, and self-reflection overhead
13. **LLMLingua Context Compression** — Token-level prompt compression (2-5x ratio with <5% information loss)
14. **LLM Generation** — Prompt sent to configured LLM provider
15. **Confidence Scoring** — Heuristic: context sufficiency (0.4), context-to-answer ratio (0.3), uncertainty phrase detection (0.2), answer length (0.1)
16. **Self-Reflection** — Post-generation critique: LLM re-reads answer against context, flags inconsistencies
17. **Hallucination Grounding** — NLI-based verification: cosine similarity + entailment classification
18. **Corrective Re-Generation** — Low-confidence answers trigger re-generation with expanded context
19. **Response Caching** — Response cached in Redis (1h TTL) unless `rag_force_refresh=true`

#### cURL Examples

**Basic RAG Query:**
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "system", "content": "You are a technical documentation assistant."},
      {"role": "user", "content": "What is the project structure and how does the ETL pipeline work?"}
    ],
    "temperature": 0.2,
    "max_tokens": 1024,
    "rag_version": "2026-03",
    "rag_force_refresh": false
  }' | jq '.'
```

**Streaming:**
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "Explain the deployment process."}],
    "stream": true
  }'
```

**Federation (skip generation, return chunks only):**
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "security policy"}],
    "rag_skip_generation": true,
    "rag_return_chunks": true,
    "rag_top_k": 10
  }' | jq '.rag_sources'
```

**Tool Calling:**
```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "What Jira tickets are blocking the release?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_jira_issue",
        "description": "Get Jira issue details by project key",
        "parameters": {
          "type": "object",
          "properties": {
            "project_key": {"type": "string"},
            "status": {"type": "string"}
          }
        }
      }
    }],
    "tool_choice": "auto"
  }'
```

---

### `GET /v1/models`

List available models in OpenAI-compatible format.

**Auth required:** No

#### Response Schema (200 OK)

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

#### cURL Example

```bash
curl http://localhost:8080/v1/models
```

---

### `GET /v1/tools`

List available tools with optional filters. RBAC: visibility-filtered by user role. Tools come from SDK-registered (`@tool` decorator), declarative (YAML/JSON), and OpenAPI auto-discovery providers.

**Auth required:** Optional

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `category` | string | No | Filter by tool category |
| `tag` | string | No | Filter by a single tag |
| `provider` | string | No | Filter by provider name (e.g., `"sdk"`, `"declarative"`, `"openapi"`) |

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `count` | integer | Number of tools matching filters |
| `tools` | array | Tool entries |

Each tool entry:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique tool name |
| `description` | string | Human-readable description |
| `category` | string | Tool category |
| `tags` | array | Tags for filtering |
| `version` | string | Tool version |
| `parameters` | object | JSON Schema for tool parameters |
| `provider` | string | Provider name |

```json
{
  "count": 3,
  "tools": [
    {
      "name": "search_knowledge_base",
      "description": "Search the indexed knowledge base using hybrid retrieval",
      "category": "retrieval",
      "tags": ["search", "internal"],
      "version": "1.0.0",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "Search query"},
          "max_results": {"type": "integer", "default": 5}
        },
        "required": ["query"]
      },
      "provider": "sdk"
    }
  ]
}
```

#### cURL Examples

```bash
# List all tools
curl http://localhost:8080/v1/tools | jq '.'

# Filter by category and tag
curl "http://localhost:8080/v1/tools?category=retrieval&tag=search" | jq '.'

# Filter by provider
curl "http://localhost:8080/v1/tools?provider=sdk" | jq '.'
```

---

### `GET /v1/tools/{name}`

Get a single tool's full details by name. Never exposes handler code. RBAC: returns 403 if tool is not visible to the user's role.

**Auth required:** Optional

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | Exact tool name (case-sensitive) |

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique tool name |
| `description` | string | Human-readable description |
| `category` | string | Tool category |
| `tags` | array | Tags for filtering |
| `version` | string | Tool version |
| `visibility` | string | Minimum role required: `"admin"`, `"expert"`, `"user"`, `"read_only"` |
| `timeout_seconds` | integer | Execution timeout |
| `parameters` | object | JSON Schema for tool parameters |
| `provider` | string | Provider name |
| `depends_on` | array | Tool dependency names for parallel execution ordering |

```json
{
  "name": "search_knowledge_base",
  "description": "Search the indexed knowledge base using hybrid retrieval",
  "category": "retrieval",
  "tags": ["search", "internal"],
  "version": "1.0.0",
  "visibility": "read_only",
  "timeout_seconds": 30,
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Search query"},
      "max_results": {"type": "integer", "default": 5}
    },
    "required": ["query"]
  },
  "provider": "sdk",
  "depends_on": []
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| **403** | `"Tool not visible to your role"` |
| **404** | `"Tool 'unknown_tool' not found"` |

#### cURL Example

```bash
curl http://localhost:8080/v1/tools/search_knowledge_base | jq '.'
```

---

### `POST /v1/feedback`

Submit expert feedback on a RAG response. Requires EXPERT role when `AUTH_ENABLED=true`. Positive feedback with corrections triggers enrichment — the corrected Q&A pair is indexed back into Qdrant.

**Auth required:** Yes (EXPERT role)

#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `feedback_id` | string | Yes | The `rag_feedback_id` from the original chat completion response |
| `rating` | string | Yes | `"positive"` or `"negative"` |
| `correction` | string | No | Corrected answer text. When provided with `rating: "positive"`, triggers enrichment indexing |
| `comment` | string | No | Free-text expert comment (e.g., why the response was incorrect) |

```json
{
  "feedback_id": "fbk_1719057600_a1b2c3d4",
  "rating": "negative",
  "correction": "The proxy is deployed via docker-compose up -d from the proxy/ directory, not the project root.",
  "comment": "Answer referenced wrong directory. Corrected above."
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"ok"` if recorded |
| `message` | string | Human-readable confirmation |

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

#### cURL Examples

```bash
# Positive feedback
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{
    "feedback_id": "fbk_1719057600_a1b2c3d4",
    "rating": "positive",
    "comment": "Accurate and well-sourced answer."
  }'

# Negative feedback with correction
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{
    "feedback_id": "fbk_1719057600_d4e5f6g7",
    "rating": "negative",
    "correction": "The deployment command is docker-compose up -d, not docker compose up.",
    "comment": "Incorrect command syntax."
  }'
```

---

### `POST /v1/admin/warmup`

Pre-load embedder, reranker, SLM, and optionally LLM models into GPU/CPU memory before serving traffic. Eliminates cold-start latency on first request.

**Auth required:** Yes (ADMIN role)

#### Request

No request body required.

```http
POST /v1/admin/warmup HTTP/1.1
Authorization: Bearer <admin-token>
```

#### Response Schema (200 OK)

```json
{
  "status": "ok",
  "results": {
    "embedder": true,
    "reranker": true,
    "slm": true,
    "llm": false
  },
  "duration_ms": 2500
}
```

**Component results:** `true` (warmed successfully), `false` (skipped or failed). The `llm` component is skipped by default unless `WARMUP_LLM=true`.

#### Response (Warm-Up Disabled)

```json
{
  "status": "disabled",
  "message": "Warm-up is disabled"
}
```

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/admin/warmup \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### `GET /v1/widget`

Serve the embeddable RAG chat widget HTML page. The widget connects to `/v1/chat/completions` via SSE streaming.

**Auth required:** No

#### Response

Returns an HTML page with a self-contained chat interface. Can be opened directly in a browser or embedded via iframe.

#### cURL Example

```bash
curl http://localhost:8080/v1/widget
```

#### HTML Embed Example

```html
<!-- Full-page embed via iframe -->
<iframe
  src="http://localhost:8080/v1/widget"
  width="720"
  height="560"
  frameborder="0"
  style="border-radius: 8px;">
</iframe>
```

---

### `GET /v1/widget.js`

Serve the standalone RAG chat widget JavaScript. Can be embedded in any page for a full chat interface.

**Auth required:** No

#### Response

Returns `application/javascript` — the widget initialization script.

#### Embed Example

```html
<script src="http://localhost:8080/v1/widget.js"></script>
<div id="rag-chat"></div>
<script>
  RAGChatWidget.init({
    container: 'rag-chat',
    apiUrl: 'http://localhost:8080/v1',
    placeholder: 'Ask me anything...',
    theme: 'dark'
  });
</script>
```

#### cURL Example

```bash
curl http://localhost:8080/v1/widget.js
```

---

### `POST /v1/admin/models/train`

Trigger a model training job (SLM, LLM, or Reranker). Launches async training and returns immediately with a `job_id`. Poll `/v1/admin/models/status/{job_id}` for completion.

**Auth required:** Yes (ADMIN role)

#### Request Schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `trainer_type` | string | Yes | — | Type of model to train: `"slm"`, `"llm"`, `"reranker"` |
| `base_model` | string | No | `""` | Base model name or HuggingFace ID (uses SLM_MODEL_NAME/LLM_MODEL_NAME if empty) |
| `profile` | string | No | `"dev"` | Training profile: `"dev"` (fast, small), `"ci"` (medium), `"prod"` (full) |
| `data_dir` | string | No | `"./data/training/"` | Directory with training datasets |
| `epochs` | integer | No | `3` | Number of training epochs |
| `batch_size` | integer | No | `8` | Training batch size |
| `learning_rate` | float | No | `2e-4` | Learning rate |
| `use_lora` | boolean | No | `true` | Use LoRA/QLoRA for memory-efficient fine-tuning |

```json
{
  "trainer_type": "slm",
  "base_model": "Qwen/Qwen2.5-1.5B-Instruct",
  "profile": "dev",
  "epochs": 3,
  "batch_size": 4,
  "learning_rate": 2e-4,
  "use_lora": true
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Unique job ID for status polling (format: `train-<12_hex_chars>`) |
| `trainer_type` | string | Type confirmed from request |
| `status` | string | Initial status: `"running"` |
| `message` | string | Human-readable confirmation |

```json
{
  "job_id": "train-a1b2c3d4e5f6",
  "trainer_type": "slm",
  "status": "running",
  "message": "Training job train-a1b2c3d4e5f6 started"
}
```

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{
    "trainer_type": "slm",
    "profile": "dev",
    "epochs": 3
  }'
```

---

### `GET /v1/admin/models/status/{job_id}`

Check training job progress and final metrics.

**Auth required:** Yes (ADMIN role)

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `job_id` | string | Job ID returned from `POST /v1/admin/models/train` |

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Job ID |
| `trainer_type` | string | Type: `"slm"`, `"llm"`, `"reranker"` |
| `status` | string | `"queued"`, `"running"`, `"completed"`, or `"failed"` |
| `config` | object | Training configuration used |
| `metrics` | object | Training metrics (populated on completion) |
| `artifact_uri` | string | Path to trained model artifacts (on completion) |
| `started_at` | string | ISO 8601 start timestamp |
| `completed_at` | string | ISO 8601 completion timestamp |
| `error_message` | string | Error details (on failure) |

**Running:**
```json
{
  "job_id": "train-a1b2c3d4e5f6",
  "trainer_type": "slm",
  "status": "running",
  "config": {"base_model": "Qwen/Qwen2.5-1.5B-Instruct", "profile": "dev", "epochs": 3},
  "metrics": {},
  "started_at": "2026-07-06T14:30:00Z",
  "completed_at": null,
  "error_message": null
}
```

**Completed:**
```json
{
  "job_id": "train-a1b2c3d4e5f6",
  "trainer_type": "slm",
  "status": "completed",
  "config": {"base_model": "Qwen/Qwen2.5-1.5B-Instruct", "profile": "dev", "epochs": 3},
  "metrics": {"accuracy": 0.923, "f1_score": 0.91, "eval_loss": 0.34},
  "artifact_uri": "./models/slm_train-a1b2c3d4e5f6",
  "started_at": "2026-07-06T14:30:00Z",
  "completed_at": "2026-07-06T14:45:30Z",
  "error_message": null
}
```

**Failed:**
```json
{
  "job_id": "train-a1b2c3d4e5f6",
  "trainer_type": "slm",
  "status": "failed",
  "error_message": "CUDA out of memory. Tried to allocate 2.0 GiB",
  "completed_at": "2026-07-06T14:31:02Z"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| **404** | `"Training job 'train-xyz' not found"` |

#### cURL Example

```bash
curl http://localhost:8080/v1/admin/models/status/train-a1b2c3d4e5f6 \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### `GET /v1/admin/models`

List all registered models with versions, statuses, and production version info.

**Auth required:** Yes (ADMIN role)

#### Response Schema (200 OK)

```json
{
  "models": {
    "slm": {
      "versions": [
        {
          "version": "v1.0.0",
          "status": "production",
          "artifact_path": "s3://rag-artifacts/slm/v1.0.0",
          "metrics": {"accuracy": 0.923, "f1_score": 0.91},
          "created_at": "2026-07-01T10:00:00Z"
        },
        {
          "version": "v1.1.0",
          "status": "staging",
          "artifact_path": "s3://rag-artifacts/slm/v1.1.0",
          "metrics": {"accuracy": 0.941, "f1_score": 0.93},
          "created_at": "2026-07-06T14:45:30Z"
        }
      ],
      "production_version": "v1.0.0"
    },
    "reranker": {
      "versions": [
        {
          "version": "v1.0.0",
          "status": "production",
          "artifact_path": "./models/reranker_v1",
          "metrics": {"mrr": 0.85, "recall_at_10": 0.78},
          "created_at": "2026-06-15T08:30:00Z"
        }
      ],
      "production_version": "v1.0.0"
    }
  }
}
```

#### cURL Example

```bash
curl http://localhost:8080/v1/admin/models \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### `POST /v1/admin/models/promote`

Promote a model version through staging → canary → production.

**Auth required:** Yes (ADMIN role)

#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | string | Yes | Model identifier (e.g., `"slm"`, `"llm"`, `"reranker"`) |
| `version` | string | Yes | Version to promote (e.g., `"v1.1.0"`) |

```json
{
  "model_name": "slm",
  "version": "v1.1.0"
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `model_name` | string | Model identifier |
| `version` | string | Promoted version |
| `previous_status` | string | Status before promotion |
| `new_status` | string | Status after promotion |

```json
{
  "model_name": "slm",
  "version": "v1.1.0",
  "previous_status": "staging",
  "new_status": "production"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| **404** | `"Model 'slm' version 'v99.0.0' not found"` |

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{"model_name": "slm", "version": "v1.1.0"}'
```

---

### `POST /v1/admin/models/rollback`

Rollback to the previous production version of a model.

**Auth required:** Yes (ADMIN role)

#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | string | Yes | Model identifier (e.g., `"slm"`, `"llm"`, `"reranker"`) |

```json
{
  "model_name": "slm"
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `model_name` | string | Model identifier |
| `version` | string | Version reverted to |
| `previous_version` | string | Version that was previously production |
| `status` | string | Status of the reverted-to version |

```json
{
  "model_name": "slm",
  "version": "v1.0.0",
  "previous_version": "v1.1.0",
  "status": "production"
}
```

#### Error Responses

| Status | Detail |
|--------|--------|
| **400** | `"No previous version to rollback to"` |
| **404** | `"Model 'unknown' not found"` or `"No production version for model 'slm'"` |

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/admin/models/rollback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{"model_name": "slm"}'
```

---

### `POST /v1/admin/models/evaluate`

Evaluate model quality metrics against configured thresholds (eval gate). Returns pass/fail status with failures and warnings.

**Auth required:** Yes (ADMIN role)

#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | string | Yes | Model identifier |
| `version` | string | No | Version being evaluated (default: `"unknown"`) |
| `metrics` | object | Yes | Key-value pairs of metric name → float value |

```json
{
  "model_name": "slm",
  "version": "v1.1.0",
  "metrics": {
    "accuracy": 0.941,
    "weighted_f1": 0.93,
    "mrr": 0.72,
    "recall_at_10": 0.68,
    "rouge_l_f1": 0.41,
    "eval_loss": 0.34
  }
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `model_name` | string | Model identifier |
| `version` | string | Evaluated version |
| `status` | string | `"PASS"`, `"FAIL"`, or `"WARN"` |
| `failures` | array | List of failed threshold checks (e.g., `"recall_at_10: 0.68 < 0.65"`) |
| `warnings` | array | List of warning-level threshold checks |
| `metrics` | object | Echoed metrics |

```json
{
  "model_name": "slm",
  "version": "v1.1.0",
  "status": "PASS",
  "failures": [],
  "warnings": [],
  "metrics": {
    "accuracy": 0.941,
    "weighted_f1": 0.93,
    "mrr": 0.72,
    "recall_at_10": 0.68,
    "rouge_l_f1": 0.41,
    "eval_loss": 0.34
  }
}
```

**Default eval gate thresholds:**

| Metric | Threshold | Operator | Severity |
|--------|-----------|----------|----------|
| `accuracy` | ≥ 0.90 | gte | fail |
| `weighted_f1` | ≥ 0.85 | gte | fail |
| `mrr` | ≥ 0.70 | gte | fail |
| `recall_at_10` | ≥ 0.65 | gte | fail |
| `rouge_l_f1` | ≥ 0.35 | gte | fail |
| `eval_loss` | ≤ 1.0 | lte | warn |

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/admin/models/evaluate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{
    "model_name": "slm",
    "version": "v1.1.0",
    "metrics": {"accuracy": 0.941, "weighted_f1": 0.93, "mrr": 0.72}
  }'
```

---

### `POST /v1/admin/models/canary/split`

Configure canary traffic split for gradual rollout. Sets the fraction of traffic routed to the canary version.

**Auth required:** Yes (ADMIN role)

#### Request Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_name` | string | Yes | Model identifier |
| `traffic_split` | float | Yes | Fraction of traffic to canary version (0.0–1.0). 0.0 = all stable, 1.0 = all canary |

```json
{
  "model_name": "slm",
  "traffic_split": 0.25
}
```

#### Response Schema (200 OK)

| Field | Type | Description |
|-------|------|-------------|
| `model_name` | string | Model identifier |
| `traffic_split` | float | Canary traffic fraction |
| `status` | string | Canary phase: `"idle"` (0.0), `"ramp"` (>0.0) |

```json
{
  "model_name": "slm",
  "traffic_split": 0.25,
  "status": "ramp"
}
```

**Typical canary rollout phases:**

| Phase | Split | Duration | Description |
|-------|-------|----------|-------------|
| Idle | 0.0 | — | No canary traffic |
| Phase 1 | 5% | 5 min | Initial smoke test |
| Phase 2 | 25% | 10 min | Expanded validation |
| Phase 3 | 50% | 15 min | Half traffic |
| Phase 4 | 75% | 20 min | Near-full rollout |
| Full | 100% | — | Full promotion |

Phase durations are configurable via `CANARY_PHASE_DURATION_*` env vars.

#### cURL Example

```bash
curl -X POST http://localhost:8080/v1/admin/models/canary/split \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOi..." \
  -d '{"model_name": "slm", "traffic_split": 0.25}'
```

---

### `GET /v1/admin/models/canary/status`

Get current canary deployment status and metrics for all models.

**Auth required:** Yes (ADMIN role)

#### Response Schema (200 OK)

```json
{
  "canary_models": {
    "slm": {
      "traffic_split": 0.25,
      "stable_traffic": 0.75,
      "phase": "ramp",
      "stable_version": "v1.0.0",
      "canary_version": "v1.1.0"
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `traffic_split` | float | Current canary traffic fraction |
| `stable_traffic` | float | Current stable traffic fraction (1.0 - traffic_split) |
| `phase` | string | `"idle"` or `"ramp"` |
| `stable_version` | string | Current stable (production) version |
| `canary_version` | string | Canary version being rolled out |

#### cURL Example

```bash
curl http://localhost:8080/v1/admin/models/canary/status \
  -H "Authorization: Bearer eyJhbGciOi..."
```

---

### `GET /metrics`

Prometheus metrics in OpenMetrics text format.

**Auth required:** No

#### Available Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rag_requests_total` | Counter | `endpoint`, `status` | Total API requests by endpoint and HTTP status |
| `rag_request_duration_seconds` | Histogram | `endpoint` | Request latency distribution (buckets: 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, +Inf) |
| `rag_retrieval_chunks` | Histogram | — | Chunks retrieved per query (buckets: 1, 5, 10, 20, 50) |
| `rag_retrieval_duration_seconds` | Histogram | — | Hybrid search + rerank latency |
| `rag_rerank_duration_seconds` | Histogram | — | Cross-encoder reranker latency |
| `rag_llm_duration_seconds` | Histogram | `provider` | LLM generation latency by provider type |
| `rag_llm_tokens_total` | Counter | `type` (`prompt`, `completion`, `total`) | Total tokens consumed |
| `rag_cache_hit_ratio` | Gauge | `cache_type` (`embedding`, `rerank`, `response`) | Cache hit ratio per cache tier |
| `rag_errors_total` | Counter | `type` (`llm`, `qdrant`, `neo4j`, `validation`, `timeout`, `internal`) | Error count by failure type |
| `rag_active_requests` | Gauge | — | Currently in-flight requests |
| `rag_confidence_score` | Histogram | — | Distribution of confidence scores (buckets: 0.1, 0.3, 0.5, 0.7, 0.9) |
| `rag_feedback_total` | Counter | `rating` (`positive`, `negative`) | Total feedback submissions |
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
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="1.0"} 234
rag_request_duration_seconds_bucket{endpoint="/v1/chat/completions",le="5.0"} 1201
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
rag_confidence_score_bucket{le="0.5"} 234
rag_confidence_score_bucket{le="0.7"} 876
rag_confidence_score_bucket{le="+Inf"} 1423
```

#### cURL Example

```bash
curl http://localhost:8080/metrics
```

---

## Error Codes

All errors follow a consistent format:

```json
{
  "detail": "string (human-readable error message)"
}
```

| HTTP Status | Meaning | Typical Cause | Remediation |
|-------------|---------|---------------|-------------|
| **200** | Success | Normal operation | — |
| **400** | Bad request | Missing `messages` field, empty user query, invalid JSON, or `model` field missing | Check request body against schema |
| **401** | Unauthorized | Missing `Authorization` header, expired JWT, invalid signature | Re-login via `/v1/auth/login` |
| **403** | Forbidden | User lacks required role or group for endpoint or document source | Request access from admin |
| **404** | Not found | Feedback ID doesn't match any recorded interaction; tool name not found; training job not found | Verify IDs |
| **409** | Conflict | Username already exists during registration | Choose different username |
| **413** | Payload too large | Message list exceeds proxy's configured limit | Reduce message count or content length |
| **429** | Too many requests | Rate limit exceeded per IP | Wait for `Retry-After` seconds; check `X-RateLimit-*` headers |
| **500** | Internal error | Unhandled exception, bug in pipeline code, or dependency crash | Check proxy logs; report bug |
| **502** | Upstream error | LLM backend returned invalid response | Check LLM backend health |
| **503** | Service unavailable | LLM or Qdrant unreachable; health check returns degraded | Check Docker services; verify network |
| **504** | Timeout | LLM request timed out (> `REQUEST_TIMEOUT`, default 120s) | Increase `REQUEST_TIMEOUT` or reduce `max_tokens` |

### Error Response Examples

**400 — Missing required field:**
```json
{
  "detail": "No user message found"
}
```

**401 — Expired token:**
```json
{
  "detail": "Token has expired"
}
```

**401 — Missing auth:**
```json
{
  "detail": "Authentication required"
}
```

**403 — Insufficient role:**
```json
{
  "detail": "Tool not visible to your role"
}
```

**404 — Not found:**
```json
{
  "detail": "Tool 'unknown_tool' not found"
}
```

**409 — Conflict:**
```json
{
  "detail": "Username 'alice' already exists"
}
```

**429 — Rate limited:**
```json
{
  "detail": "Rate limit exceeded. Try again later."
}
```

**500 — Internal error:**
```json
{
  "detail": "Failed to record feedback: database connection error"
}
```

---

## Rate Limiting

When enabled (`RATE_LIMIT_ENABLED=true`), a token bucket algorithm limits requests per IP address.

### Configuration

```bash
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60     # Sustained requests per minute per IP
RATE_LIMIT_BURST=10          # Burst capacity above sustained rate
```

### Rate Limit Headers

Included in every response when rate limiting is active:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests per minute |
| `X-RateLimit-Remaining` | Remaining tokens in current window |
| `X-RateLimit-Reset` | Unix timestamp when bucket refills |
| `Retry-After` | Seconds until next request is allowed (429 only) |

### Behavior

- Tokens replenish at `RATE_LIMIT_PER_MINUTE / 60` per second
- Maximum bucket capacity is `RATE_LIMIT_PER_MINUTE + RATE_LIMIT_BURST`
- When bucket is empty, requests receive HTTP 429 with `Retry-After` header

---

## Response Compression

All API responses support gzip and brotli compression via the `Accept-Encoding` request header. Compression is applied to responses larger than `COMPRESSION_MIN_SIZE` bytes (default: 500).

### Behavior

| Request Header | Response Encoding |
|----------------|-------------------|
| `Accept-Encoding: gzip` | gzip (level 6) |
| `Accept-Encoding: br` | brotli (level 4) |
| `Accept-Encoding: gzip, br` | brotli preferred, gzip fallback |
| (not present) | Uncompressed |

**Compression applies to:** All JSON responses (chat completions, health checks, models list, etc.), error responses (when body > threshold), and Prometheus metrics.

**Compression does NOT apply to:** Streaming SSE responses (`text/event-stream`), responses smaller than `COMPRESSION_MIN_SIZE`.

### Configuration

```bash
COMPRESSION_ENABLED=true
COMPRESSION_MIN_SIZE=500    # Minimum response size in bytes to compress
COMPRESSION_LEVEL=6         # Compression level (gzip: 1-9, brotli: 0-11)
```

---

## Endpoint Summary

| Method | Endpoint | Auth | Rate Limited | Description |
|--------|----------|------|-------------|-------------|
| `POST` | `/v1/chat/completions` | Optional | Yes | Main RAG endpoint (streaming + non-streaming) |
| `GET` | `/v1/models` | No | No | List available models |
| `GET` | `/v1/health` | No | No | Health check with component status |
| `GET` | `/v1/health/live` | No | No | K8s liveness probe |
| `GET` | `/v1/health/ready` | No | No | K8s readiness probe |
| `POST` | `/v1/auth/register` | No | Yes | Self-registration (bcrypt passwords) |
| `POST` | `/v1/auth/login` | No | Yes | JWT access + refresh token pair |
| `POST` | `/v1/auth/refresh` | No | No | Refresh token exchange |
| `POST` | `/v1/auth/logout` | Optional | No | Token revocation |
| `GET` | `/v1/auth/me` | Yes | No | Current user context |
| `GET` | `/v1/tools` | Optional | No | List tools with category/tag/provider filters |
| `GET` | `/v1/tools/{name}` | Optional | No | Single tool details |
| `POST` | `/v1/feedback` | Yes (EXPERT) | No | Expert feedback submission |
| `POST` | `/v1/admin/warmup` | Yes (ADMIN) | No | Pre-load models into memory |
| `GET` | `/v1/widget` | No | No | Embeddable chat widget HTML |
| `GET` | `/v1/widget.js` | No | No | Widget JavaScript |
| `POST` | `/v1/admin/models/train` | Yes (ADMIN) | No | Trigger training job |
| `GET` | `/v1/admin/models/status/{job_id}` | Yes (ADMIN) | No | Training progress |
| `GET` | `/v1/admin/models` | Yes (ADMIN) | No | Model registry |
| `POST` | `/v1/admin/models/promote` | Yes (ADMIN) | No | Promote version |
| `POST` | `/v1/admin/models/rollback` | Yes (ADMIN) | No | Rollback version |
| `POST` | `/v1/admin/models/evaluate` | Yes (ADMIN) | No | Eval gate quality check |
| `POST` | `/v1/admin/models/canary/split` | Yes (ADMIN) | No | Canary traffic configuration |
| `GET` | `/v1/admin/models/canary/status` | Yes (ADMIN) | No | Canary deployment status |
| `GET` | `/metrics` | No | No | Prometheus metrics |

---

## SDK Usage Examples

### Python (openai package)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed"  # placeholder when auth is disabled
)

# Non-streaming with RAG extensions
response = client.chat.completions.create(
    model="rag-proxy",
    messages=[
        {"role": "system", "content": "You are a technical documentation assistant."},
        {"role": "user", "content": "What is the project structure?"}
    ],
    temperature=0.2,
    max_tokens=4096,
    extra_body={
        "rag_version": "2026-01-15",
        "rag_force_refresh": False
    }
)

print(f"Answer: {response.choices[0].message.content}")
print(f"Confidence: {response.rag_confidence}")
print(f"Feedback ID: {response.rag_feedback_id}")
for src in response.rag_sources:
    print(f"  Source: {src['title']} (relevance: {src['relevance']})")

# Streaming
stream = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Explain the deployment process."}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")

# Tool calling
response = client.chat.completions.create(
    model="rag-proxy",
    messages=[{"role": "user", "content": "Search for authentication docs."}],
    tools=[{
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search the RAG knowledge base",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
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

# Submit feedback
import requests
requests.post("http://localhost:8080/v1/feedback", json={
    "feedback_id": response.rag_feedback_id,
    "rating": "positive",
    "comment": "Accurate and well-sourced answer."
}, headers={"Authorization": "Bearer eyJhbGciOi..."})
```

### JavaScript / TypeScript (openai package)

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "not-needed",
});

const completion = await client.chat.completions.create({
  model: "rag-proxy",
  messages: [
    { role: "system", content: "You are a documentation assistant." },
    { role: "user", content: "What database does the system use for vector search?" },
  ],
  temperature: 0.2,
  max_tokens: 1024,
});

console.log("Answer:", completion.choices[0].message.content);
console.log("Confidence:", (completion as any).rag_confidence);
console.log("Sources:", (completion as any).rag_sources);

// Streaming
const stream = await client.chat.completions.create({
  model: "rag-proxy",
  messages: [{ role: "user", content: "Explain the MCP server setup." }],
  stream: true,
});

for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content ?? "");
}

// Submit feedback
const fbResp = await fetch("http://localhost:8080/v1/feedback", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": "Bearer eyJhbGciOi...",
  },
  body: JSON.stringify({
    feedback_id: (completion as any).rag_feedback_id,
    rating: "positive",
    comment: "Excellent answer with proper citations.",
  }),
});
console.log(await fbResp.json());
```

---

## Configuration Reference

All proxy configuration is loaded from environment variables or the `proxy/.env` file. See `proxy/app/config.py` for the complete source of truth.

### Required Settings

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `QDRANT_HOST` | string | `localhost` | Qdrant server hostname |
| `QDRANT_PORT` | integer | `6333` | Qdrant gRPC port |
| `LLM_ENDPOINT` | string | `http://localhost:8000/v1` | LLM provider endpoint URL |
| `LLM_MODEL_NAME` | string | `""` | Model name to request from LLM endpoint. Example: `"gemma-4-26b-it"` |
| `LLM_PROVIDER_TYPE` | string | `openai` | Provider type: `openai`, `anthropic`, `generic` |

### Embedder / Embedding Model

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `EMBEDDER_MODEL` | string | `""` | Local embedding model name. Examples: `"BAAI/bge-m3"`, `"intfloat/multilingual-e5-large"` |
| `EMBEDDER_DEVICE` | string | `cpu` | Device for local model: `cpu` or `cuda` |
| `EMBEDDER_ENDPOINT` | string | `""` | Remote embedding service URL (OpenAI `/v1/embeddings` compatible). Leave empty for local model |
| `EMBEDDER_API_KEY` | string | `""` | API key for remote embedder |
| `EMBEDDER_FALLBACK_LOCAL` | boolean | `true` | Fall back to local SentenceTransformer when remote embedder is unavailable |

### Reranker / Cross-Encoder

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RERANKER_MODEL` | string | `""` | Cross-encoder model. Examples: `"cross-encoder/ms-marco-MiniLM-L-6-v2"`, `"BAAI/bge-reranker-v2-m3"` |
| `RERANKER_MAX_LENGTH` | integer | `512` | Maximum sequence length for reranker input |
| `RERANKER_BATCH_SIZE` | integer | `32` | Batch size for cross-encoder |
| `RERANKER_ENDPOINT` | string | `""` | Remote reranker service (Cohere `/v1/rerank` compatible). Leave empty for local model |
| `RERANKER_API_KEY` | string | `""` | API key for remote reranker |
| `RERANKER_FALLBACK_LOCAL` | boolean | `true` | Fall back to local CrossEncoder when remote reranker is unavailable |

### LLM / Primary Language Model

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `LLM_ENDPOINT` | string | `http://localhost:8000/v1` | LLM provider endpoint URL. Examples: `"http://vllm:8000/v1"`, `"http://localhost:11434/v1"` |
| `LLM_MODEL_NAME` | string | `""` | Model name. Examples: `"gemma-4-26b-it"`, `"meta-llama/Llama-3.1-70B"` |
| `LLM_API_KEY` | string | `""` | API key for the LLM provider (empty for local deployments) |
| `LLM_PROVIDER` | string | `vllm` | Backend provider: `vllm`, `llama_cpp`, `openai_compatible` |
| `REQUEST_TIMEOUT` | integer | `120` | LLM request timeout in seconds |
| `MAX_RETRIES` | integer | `3` | Retry attempts on LLM connection failure |
| `RETRY_DELAY` | float | `1.0` | Delay between retries in seconds |
| `PREFIX_CACHING_ENABLED` | boolean | `false` | Enable vLLM prefix caching for reduced prefill latency |

### SLM / Small Language Model

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SLM_ENDPOINT` | string | `""` | SLM endpoint for routing/decomposition. Leave empty to disable SLM (fallback to regex heuristics). Example: `"http://slm:8081/v1"` |
| `SLM_MODEL_NAME` | string | `""` | SLM model name. Examples: `"gemma-2b-it"`, `"Qwen/Qwen2.5-1.5B-Instruct"` |
| `SLM_API_KEY` | string | `""` | API key for SLM |
| `SLM_MAX_TOKENS` | integer | `256` | Max tokens for SLM responses |
| `SLM_LOCAL_ENABLED` | boolean | `false` | Enable local llama.cpp subprocess for air-gapped SLM |
| `SLM_LOCAL_BINARY` | string | `llama.cpp/build/bin/llama-server` | Path to llama.cpp server binary |
| `SLM_LOCAL_MODEL_PATH` | string | `""` | Path to .gguf model file |
| `SLM_LOCAL_CONTEXT_SIZE` | integer | `4096` | Context size for local SLM |
| `SLM_LOCAL_THREADS` | integer | `4` | CPU threads for local SLM inference |
| `SLM_LOCAL_PORT` | integer | `8081` | Port for local llama-server |

### Retrieval Tuning

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MAX_CHUNKS_RETRIEVAL` | integer | `50` | Chunks to retrieve from Qdrant |
| `MAX_CHUNKS_AFTER_RERANK` | integer | `20` | Chunks after cross-encoder reranking |
| `MAX_RETRIEVAL_LOOPS` | integer | `3` | Max rewrite iterations in LangGraph (when enabled) |

### Confidence & Self-Correction

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CONFIDENCE_THRESHOLD` | float | `0.5` | Threshold below which answers are flagged for review |
| `NLI_GROUNDING_ENABLED` | boolean | `true` | Enable NLI-based answer grounding (cosine + entailment) |
| `SELF_CRITIQUE_ENABLED` | boolean | `true` | Enable self-reflection critique step |
| `MAX_VERIFY_LOOPS` | integer | `2` | Max corrective re-generation cycles |
| `HYDE_ENABLED` | boolean | `true` | Enable HyDE query expansion |
| `REFLECTION_ENABLED` | boolean | `true` | Enable self-reflection in LangGraph pipeline |
| `CRAG_DECOMPOSITION_ENABLED` | boolean | `true` | Enable CRAG-style retrieval evaluation |
| `REORDER_ENABLED` | boolean | `true` | Enable LongContextReorder |
| `COMPRESSION_STRATEGY` | string | `keyword` | Context compression strategy: `"keyword"`, `"perplexity"`, `"none"` |
| `HALLUCINATION_CHECK_ENABLED` | boolean | `false` | Enable full hallucination detection pipeline |
| `NLI_MODEL_ENABLED` | boolean | `false` | Enable dedicated NLI model for grounding |

### Cache

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `USE_REDIS` | boolean | `false` | Enable Redis caching |
| `REDIS_URL` | string | `redis://localhost:6379` | Redis connection string |

### Agentic Orchestration (LangGraph)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `USE_LANGGRAPH` | boolean | `false` | Enable agentic orchestration with LangGraph state graph |

### Knowledge Graph (Neo4j)

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `GRAPH_ENABLED` | boolean | `false` | Enable Neo4j connectivity |
| `NEO4J_URI` | string | `bolt://localhost:7687` | Neo4j bolt URI |
| `NEO4J_USER` | string | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | string | `""` | Neo4j password |
| `USE_GRAPH_EXPANSION` | boolean | `false` | Enable graph context enrichment (requires `GRAPH_ENABLED=true`) |

### Authentication

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTH_ENABLED` | boolean | `false` | Enable JWT authentication |
| `JWT_SECRET` | string | `""` | JWT signing secret. Generate: `openssl rand -hex 32` |
| `JWT_ALGORITHM` | string | `HS256` | JWT signing algorithm: `HS256`, `RS256` |
| `JWT_PUBLIC_KEY` | string | `""` | PEM public key for RS256 verification |
| `TOKEN_EXPIRE_HOURS` | integer | `24` | Access token expiry in hours |
| `AUTH_VALID_USERS` | string | `{}` | JSON dict of legacy users auto-migrated to SQLite |
| `USER_DB_PATH` | string | `./data/users.db` | SQLite user database path |
| `BCRYPT_ROUNDS` | integer | `12` | bcrypt cost factor for password hashing |
| `ACCESS_TOKEN_MINUTES` | integer | `60` | Access token lifetime in minutes |
| `REFRESH_TOKEN_DAYS` | integer | `7` | Refresh token lifetime in days |
| `TOKEN_BLACKLIST_MAX_ENTRIES` | integer | `10000` | Max token blacklist entries before cleanup |
| `KEYCLOAK_URL` | string | `""` | Keycloak server URL for OIDC. Example: `"https://auth.example.com"` |
| `KEYCLOAK_REALM` | string | `master` | Keycloak realm name |
| `KEYCLOAK_CLIENT_ID` | string | `rag-proxy` | Keycloak client ID |
| `AD_ENABLED` | boolean | `false` | Enable Active Directory / LDAP integration |
| `AD_URL` | string | `""` | LDAP server URL. Example: `"ldap://dc.example.com:389"` |
| `AD_BASE_DN` | string | `""` | LDAP base DN. Example: `"dc=example,dc=com"` |
| `AD_USER_DN_TEMPLATE` | string | `cn={username},{base_dn}` | LDAP user DN template |
| `AD_GROUP_DN` | string | `""` | LDAP group DN for membership check |
| `RBAC_ENABLED` | boolean | `false` | Enable role-based access control |

### Rate Limiting

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `RATE_LIMIT_ENABLED` | boolean | `false` | Enable IP-based rate limiting |
| `RATE_LIMIT_PER_MINUTE` | integer | `60` | Sustained requests per minute per IP |
| `RATE_LIMIT_BURST` | integer | `10` | Burst capacity above sustained rate |

### Observability

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `METRICS_ENABLED` | boolean | `true` | Expose Prometheus `/metrics` endpoint |
| `LOG_FORMAT` | string | `text` | Log format: `"text"` or `"json"` |
| `LOG_DIR` | string | `./logs` | Directory for log files |
| `LOG_REQUESTS` | boolean | `true` | Log each request to JSONL file |
| `AUDIT_ENABLED` | boolean | `true` | Enable audit logging |
| `OTEL_ENABLED` | boolean | `false` | Enable OpenTelemetry tracing |
| `OTEL_EXPORTER_ENDPOINT` | string | `http://localhost:4318/v1/traces` | OTLP exporter endpoint |
| `OTEL_SERVICE_NAME` | string | `rag-proxy` | Service name for traces |

### Server Settings

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `HOST` | string | `0.0.0.0` | Bind address |
| `PORT` | integer | `8080` | Bind port |
| `WORKERS` | integer | `1` | Uvicorn worker processes (keep at 1 for shared caches) |
| `RELOAD` | boolean | `false` | Enable hot reload in development |
| `CORS_ORIGINS` | string | `*` | Allowed CORS origins. Comma-separated or `"*"` for all |
| `COMPRESSION_ENABLED` | boolean | `true` | Enable gzip/brotli response compression |
| `COMPRESSION_MIN_SIZE` | integer | `500` | Minimum response size in bytes to compress |
| `COMPRESSION_LEVEL` | integer | `6` | Compression level (1-9 for gzip, 0-11 for brotli) |
| `GRACEFUL_SHUTDOWN_ENABLED` | boolean | `true` | Enable graceful shutdown on SIGTERM/SIGINT |
| `SHUTDOWN_TIMEOUT` | integer | `30` | Max seconds to wait for in-flight requests during shutdown |
| `SANITIZE_INPUT` | boolean | `true` | Enable input sanitization (SQL injection, XSS, length limits) |

### Model Warm-Up

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `WARMUP_ENABLED` | boolean | `true` | Enable model warm-up on startup and via admin endpoint |
| `WARMUP_ON_STARTUP` | boolean | `true` | Run warm-up automatically on first startup |

### Model Evolution

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MODEL_EVOLUTION_ENABLED` | boolean | `false` | Enable model evolution (fine-tuning, registry, eval gates, canary) |
| `MLFLOW_TRACKING_URI` | string | `http://localhost:5000` | MLflow tracking server URI |
| `MLFLOW_EXPERIMENT_NAME` | string | `rag-system` | MLflow experiment name |
| `MINIO_ENDPOINT` | string | `localhost:9000` | MinIO S3 endpoint for artifact storage |
| `MINIO_ACCESS_KEY` | string | `minioadmin` | MinIO access key |
| `MINIO_SECRET_KEY` | string | `minioadmin` | MinIO secret key |
| `MINIO_BUCKET` | string | `rag-artifacts` | MinIO bucket name |
| `MINIO_SECURE` | boolean | `false` | Use HTTPS for MinIO |
| `TRAINING_PROFILE` | string | `dev` | Default training profile: `dev`, `ci`, `prod` |
| `HOT_RELOAD_ENABLED` | boolean | `false` | Enable adapter hot-reload |
| `CANARY_ENABLED` | boolean | `false` | Enable canary deployment |
| `CANARY_PHASE_DURATION_5` | integer | `300` | Duration in seconds for 5% canary phase |
| `CANARY_PHASE_DURATION_25` | integer | `600` | Duration for 25% phase |
| `CANARY_PHASE_DURATION_50` | integer | `900` | Duration for 50% phase |
| `CANARY_PHASE_DURATION_75` | integer | `1200` | Duration for 75% phase |
| `CANARY_COOLDOWN_SECONDS` | integer | `3600` | Cooldown between canary phases |
| `EVAL_GATE_LLM_BERTSCORE_MIN` | float | `0.70` | Minimum BERTScore for LLM eval gate |
| `EVAL_GATE_LLM_HALLUCINATION_MAX` | float | `0.05` | Maximum hallucination rate for LLM eval gate |
| `EVAL_GATE_LLM_ROUGE_L_MIN` | float | `0.35` | Minimum ROUGE-L for LLM eval gate |
| `EVAL_GATE_SLM_F1_MIN` | float | `0.85` | Minimum F1 for SLM eval gate |
| `EVAL_GATE_SLM_ACCURACY_MIN` | float | `0.90` | Minimum accuracy for SLM eval gate |
| `EVAL_GATE_RERANKER_MRR_MIN` | float | `0.75` | Minimum MRR for reranker eval gate |
| `EVAL_GATE_RERANKER_NDCG_MIN` | float | `0.70` | Minimum nDCG for reranker eval gate |

### Tool Calling

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `TOOLS_ENABLED` | boolean | `false` | Enable tool calling / function calling |
| `LIVE_SOURCES_ENABLED` | boolean | `false` | Enable live queries to Confluence/Jira/GitLab APIs |
| `TOOLS_PARALLEL_EXECUTION` | boolean | `true` | Enable parallel tool execution with dependency resolution |
| `TOOLS_MAX_CONCURRENCY` | integer | `10` | Max concurrent tool executions |
| `TOOLS_DECLARATIVE_DIR` | string | `./tools/declarative` | Directory for YAML/JSON tool definitions |
| `TOOLS_OPENAPI_SPECS` | string | `""` | Comma-separated OpenAPI spec URLs for auto-discovery |

### Multi-Modal RAG

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `MULTI_MODAL_ENABLED` | boolean | `true` | Enable multi-modal RAG (images, code, tables) |
| `COLBERT_ENABLED` | boolean | `true` | Enable ColBERT multi-vector indexing |
| `IMAGE_MODEL` | string | `clip-ViT-B-32` | CLIP model for image embeddings |
| `IMAGE_EXTRACTION_ENABLED` | boolean | `false` | Extract images from documents |
| `TABLE_EXTRACTION_ENABLED` | boolean | `false` | Extract tables from documents |
| `CODE_CHUNKING_ENABLED` | boolean | `false` | Enable AST-aware code chunking |
| `AST_LANGUAGES` | string | `python,javascript,java` | Languages for AST-aware chunking |

### I18N / Multi-Language

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `I18N_ENABLED` | boolean | `true` | Enable multi-language support |
| `DEFAULT_LANGUAGE` | string | `en` | Default language: `en`, `ru`, `de`, `fr`, `zh` |
| `SUPPORTED_LANGUAGES` | string | `en,ru,de,fr,zh` | Comma-separated list of supported languages |
| `CROSS_LINGUAL_ENABLED` | boolean | `true` | Enable cross-lingual retrieval |

### Enrichment

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ENRICHMENT_ENABLED` | boolean | `false` | Index corrected Q&A pairs from positive feedback |

### Security

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `NAMESPACE_ISOLATION_ENABLED` | boolean | `false` | Enable namespace-level data isolation |
| `A/B_TEST_ENABLED` | boolean | `false` | Enable A/B test harness for pipeline variants |
| `DEPENDENCY_SCAN_ENABLED` | boolean | `false` | Enable dependency vulnerability scanning |
| `ADMIN_ALERT_ENABLED` | boolean | `false` | Enable admin alerting |
| `ADMIN_ALERT_ENDPOINT` | string | `""` | Webhook endpoint for admin alerts |

### Live Source APIs

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `CONFLUENCE_API_URL` | string | `""` | Confluence REST API URL. Example: `"https://confluence.example.com/rest/api"` |
| `CONFLUENCE_API_TOKEN` | string | `""` | Confluence API token |
| `CONFLUENCE_API_USER` | string | `""` | Confluence API username |
| `JIRA_API_URL` | string | `""` | Jira REST API URL. Example: `"https://jira.example.com/rest/api/2"` |
| `JIRA_API_TOKEN` | string | `""` | Jira API token |
| `JIRA_API_USER` | string | `""` | Jira API username |
| `GITLAB_API_URL` | string | `""` | GitLab API URL. Example: `"https://gitlab.example.com/api/v4"` |
| `GITLAB_API_TOKEN` | string | `""` | GitLab API token |

### SSE Streaming

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SSE_CHUNK_SIZE` | integer | `4` | Number of tokens to buffer before emitting SSE chunk |
| `STREAM_BUFFER_SIZE` | integer | `1` | Stream buffer size for token aggregation |

