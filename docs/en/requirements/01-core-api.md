# Block A. OpenAI-Compatible API (FR-01 — FR-08)

---

## FR-01. Chat Completions — streaming and non-streaming

**Description:**
The proxy provides a `/v1/chat/completions` endpoint compatible with the OpenAI API.
The client sends a POST request with a `messages` array (role + content), and the
`temperature`, `max_tokens`, `stream` parameters. The proxy runs the RAG pipeline
(retrieval → ranking → context assembly → LLM generation) and returns a response
in the OpenAI Chat Completion format.

A model with the `+RAG` suffix (e.g., `qwen3-635b+RAG`) activates the RAG pipeline.
A model without the suffix is a direct proxy to the LLM with no retrieval.

With `stream=true` the response is delivered via SSE (Server-Sent Events) as
`data: {...}` lines and a final `data: [DONE]`. With `stream=false` a full JSON
is returned.

**Acceptance criteria:**

1. `curl -X POST /v1/chat/completions -d '{"messages":[{"role":"user","content":"test"}],"stream":false}'` returns
   200 with JSON `{choices: [{message: {content: "..."}}]}`
2. The same request with `"stream":true` returns an SSE stream ending with `data: [DONE]`
3. OpenAI Python SDK `OpenAI(base_url="http://localhost:8080/v1").chat.completions.create(...)` works without errors

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR01ChatCompletions`,
`tests/integration/test_core_api_e2e.py::TestFR01Integration`)
**Priority:** CRITICAL
**Reference:** ADR-004, `proxy/app/api/chat.py`

---

## FR-02. Models endpoint

**Description:**
The `GET /v1/models` endpoint returns the list of models from `AVAILABLE_MODELS`.
For each model, a version with the `+RAG` suffix (with the RAG pipeline)
and one without the suffix (direct proxy) are shown.

**Acceptance criteria:**

1. `curl /v1/models` returns `{object: "list", data: [{id: "...", object: "model", ...}]}`
2. The list contains the model from `LLM_MODEL_NAME`

**Status:** ✅ Confirmed (`proxy/app/main.py:846`)
**Priority:** CRITICAL
**Reference:** ADR-004

---

## FR-03. Health check — full status

**Description:**
The `GET /v1/health` endpoint checks the availability of all dependencies: Qdrant, LLM,
Neo4j (optional), Redis (optional), embedder, reranker. It returns a JSON with the
status of each component (`healthy`/`degraded`/`down`) and an overall HTTP code: 200
if all critical components are healthy, 503 if at least one critical component is unavailable.

**Acceptance criteria:**

1. With all services running — HTTP 200, all components `healthy`
2. With Qdrant stopped — HTTP 503, Qdrant `down`, others `healthy`
3. With Neo4j stopped (GRAPH_ENABLED=true) — HTTP 200 (Neo4j is not critical), Neo4j `down`

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR03HealthCheck`,
`tests/integration/test_core_api_e2e.py::TestFR03Integration`)
**Priority:** CRITICAL
**Reference:** ADR-004, best-practices-checklist 4.3

---

## FR-04. Kubernetes probes — liveness and readiness

**Description:**

- `GET /v1/health/live` — liveness probe. Returns 200 if the process is alive (not hung).
  Does not check external dependencies.
- `GET /v1/health/ready` — readiness probe. Returns 200 only if all critical
  dependencies are available (Qdrant, LLM). Otherwise — 503.

**Acceptance criteria:**

1. `/v1/health/live` always returns 200 while the process is running
2. `/v1/health/ready` returns 503 when Qdrant is unavailable

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR04KubernetesProbes`,
`tests/integration/test_core_api_e2e.py::TestFR04Integration`)
**Priority:** CRITICAL
**Reference:** roadmap Phase 3, best-practices-checklist 4.7

---

## FR-05. RAG-specific request parameters

**Description:**
Additional parameters are added to the standard OpenAI request:

- `rag_version` (string) — requests a specific document version
- `rag_force_refresh` (bool) — bypasses the response cache
- `rag_skip_generation` (bool) — "retrieval only" mode (returns the retrieved chunks)
- `rag_return_chunks` (bool) — returns the retrieved chunks in the response
- `rag_top_k` (int) — overrides the number of chunks after ranking

All parameters are optional. Standard OpenAI clients ignore them.

**Acceptance criteria:**

1. `rag_version="v1"` — the response contains only chunks of version v1
2. `rag_force_refresh=true` — the response is generated anew (not from cache)
3. `rag_skip_generation=true` — only retrieved chunks are returned, without generation
4. `rag_return_chunks=true` — the response contains the `rag_sources` field with chunks
5. `rag_top_k=5` — no more than 5 chunks after ranking

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR05RAGParameters`,
`tests/integration/test_core_api_e2e.py::TestFR05FR06Integration`)
**Priority:** CRITICAL
**Reference:** ADR-004

---

## FR-06. RAG-specific response fields

**Description:**
Every `/v1/chat/completions` response contains additional fields:

- `rag_feedback_id` (string) — unique ID for submitting feedback
- `rag_confidence` (float 0-1) — the system's confidence in the answer
- `rag_sources` (array) — list of sources with `chunk_id`, `source`, `title`, `version`, `relevance`

> **Note:** The `rag_sources`, `rag_confidence`, `rag_feedback_id` fields are extensions
> to the standard OpenAI format. Standard clients (OpenWebUI) ignore them, but they
> are available via the API.

**Acceptance criteria:**

1. The response contains `rag_feedback_id` (non-empty string)
2. The response contains `rag_confidence` (float from 0 to 1)
3. The response contains `rag_sources` (array, may be empty if there are no retrieval results)

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR06RAGResponseFields`,
`tests/integration/test_core_api_e2e.py::TestFR05FR06Integration`)
**Priority:** CRITICAL
**Reference:** ADR-004

---

## FR-07. Response caching (Redis)

**Description:**
Non-streaming responses are cached in Redis with a 1-hour TTL. A repeated request with the same
content returns the cached response without calling the LLM. The
`rag_force_refresh=true` parameter bypasses the cache. The cache key is formed as
`rag:{user_id}:{query}:{version}`.

**Acceptance criteria:**

1. Two identical requests — the second one is served from cache (log: "Cache hit")
2. A request with `rag_force_refresh=true` — generated anew
3. TTL expires after 1 hour — the next request is generated anew

**Status:** ✅ Confirmed (`proxy/app/shared/cache.py`)
**Priority:** CRITICAL
**Reference:** ADR-004, performance-quality 1.4

---

## FR-08. SSE streaming format

**Description:**
With `stream=true` the response is delivered via Server-Sent Events. Each chunk is a
`data: {"choices":[{"delta":{"content":"token"}}]}\n\n` line. The stream ends with
`data: [DONE]\n\n`. Content-Type: `text/event-stream`.

**Acceptance criteria:**

1. Response Content-Type — `text/event-stream`
2. Each line starts with `data: `
3. The last line is `data: [DONE]`
4. Each intermediate JSON parses and contains `choices[0].delta.content`

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR08SSEStreaming`,
`tests/integration/test_core_api_e2e.py::TestFR08Integration`)
**Priority:** CRITICAL
**Reference:** ADR-004
