# API Examples

**Version:** v2.0.0 | **Last Updated:** 2026-07-10

Practical examples for every RAG System API endpoint using **curl**, **Python (httpx)**, and **JavaScript (fetch)**. All examples assume the proxy is running at `http://localhost:8080`.

---

## Base URL

```
http://localhost:8080/v1
```

When authentication is enabled, include the JWT token in all requests:

```
Authorization: Bearer <access_token>
```

---

## Chat Completions

### Simple Chat

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "rag-proxy",
        "messages": [
          {"role": "user", "content": "What is retrieval-augmented generation?"}
        ]
      }'
    ```

=== "Python"

    ```python
    import httpx

    response = httpx.post(
        "http://localhost:8080/v1/chat/completions",
        json={
            "model": "rag-proxy",
            "messages": [
                {"role": "user", "content": "What is retrieval-augmented generation?"}
            ],
        },
    )
    data = response.json()
    print(data["choices"][0]["message"]["content"])
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "rag-proxy",
        messages: [
          { role: "user", content: "What is retrieval-augmented generation?" },
        ],
      }),
    });

    const data = await response.json();
    console.log(data.choices[0].message.content);
    ```

### Streaming Response

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "rag-proxy",
        "messages": [
          {"role": "user", "content": "Explain hybrid search"}
        ],
        "stream": true
      }'
    ```

=== "Python"

    ```python
    import httpx

    with httpx.stream(
        "POST",
        "http://localhost:8080/v1/chat/completions",
        json={
            "model": "rag-proxy",
            "messages": [
                {"role": "user", "content": "Explain hybrid search"}
            ],
            "stream": True,
        },
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                import json
                chunk = json.loads(line[6:])
                content = chunk["choices"][0]["delta"].get("content", "")
                if content:
                    print(content, end="", flush=True)
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "rag-proxy",
        messages: [{ role: "user", content: "Explain hybrid search" }],
        stream: true,
      }),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value);
      const lines = text.split("\n").filter((l) => l.startsWith("data: "));
      for (const line of lines) {
        if (line === "data: [DONE]") break;
        const chunk = JSON.parse(line.slice(6));
        const content = chunk.choices[0]?.delta?.content;
        if (content) process.stdout.write(content);
      }
    }
    ```

### RAG-Specific Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `rag_version` | `string` | `null` | Request a specific document version |
| `rag_force_refresh` | `bool` | `false` | Bypass response cache for fresh results |
| `rag_top_k` | `int` | `null` | Override the number of retrieved chunks |
| `rag_skip_generation` | `bool` | `false` | Return retrieved chunks without LLM generation |
| `rag_return_chunks` | `bool` | `false` | Include raw chunks in the response |

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "What changed in the deployment guide?"}
    ],
    "rag_version": "2026-07-01",
    "rag_force_refresh": true,
    "rag_top_k": 5
  }'
```

**Return chunks without generation** (useful for debugging retrieval):

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "deployment guide"}
    ],
    "rag_skip_generation": true,
    "rag_return_chunks": true
  }'
```

### Tools / Function Calling

Pass `tools` in the request to enable agentic tool calling. The proxy selects and invokes tools automatically via the orchestrator.

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "Search for deployment docs in Confluence"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "search_confluence",
          "description": "Search Confluence pages by query",
          "parameters": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query"
              },
              "max_results": {
                "type": "integer",
                "description": "Max results to return",
                "default": 5
              }
            },
            "required": ["query"]
          }
        }
      }
    ]
  }'
```

=== "Python"

    ```python
    import httpx

    response = httpx.post(
        "http://localhost:8080/v1/chat/completions",
        json={
            "model": "rag-proxy",
            "messages": [
                {"role": "user", "content": "Search for deployment docs"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "search_confluence",
                        "description": "Search Confluence pages",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                            },
                            "required": ["query"],
                        },
                    },
                }
            ],
        },
    )
    data = response.json()
    print(data["choices"][0]["message"]["content"])
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "rag-proxy",
        messages: [{ role: "user", content: "Search for deployment docs" }],
        tools: [
          {
            type: "function",
            function: {
              name: "search_confluence",
              description: "Search Confluence pages",
              parameters: {
                type: "object",
                properties: { query: { type: "string" } },
                required: ["query"],
              },
            },
          },
        ],
      }),
    });
    const data = await response.json();
    console.log(data.choices[0].message.content);
    ```

### Multi-Turn Conversation

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant for internal documentation."},
      {"role": "user", "content": "How do I deploy the proxy?"},
      {"role": "assistant", "content": "Use docker compose up -d in the proxy directory..."},
      {"role": "user", "content": "What about Kubernetes?"}
    ]
  }'
```

---

## Models

### List Models

=== "curl"

    ```bash
    curl http://localhost:8080/v1/models
    ```

=== "Python"

    ```python
    import httpx

    response = httpx.get("http://localhost:8080/v1/models")
    for model in response.json()["data"]:
        print(f"  {model['id']}")
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/models");
    const data = await response.json();
    data.data.forEach((m) => console.log(m.id));
    ```

---

## Health Checks

### Service Health

=== "curl"

    ```bash
    curl http://localhost:8080/v1/health
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.get("http://localhost:8080/v1/health")
    health = r.json()
    print(f"Status: {health['status']}")
    print(f"Qdrant: {health.get('qdrant', 'N/A')}")
    print(f"LLM: {health.get('llm', 'N/A')}")
    ```

### Liveness Probe (K8s)

```bash
curl http://localhost:8080/v1/health/live
```

### Readiness Probe (K8s)

```bash
curl http://localhost:8080/v1/health/ready
```

---

## Authentication

### Register

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/auth/register \
      -H "Content-Type: application/json" \
      -d '{
        "username": "analyst",
        "password": "secure-password-123",
        "email": "analyst@company.com"
      }'
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.post(
        "http://localhost:8080/v1/auth/register",
        json={
            "username": "analyst",
            "password": "secure-password-123",
            "email": "analyst@company.com",
        },
    )
    print(r.json())
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "analyst",
        password: "secure-password-123",
        email: "analyst@company.com",
      }),
    });
    console.log(await response.json());
    ```

### Login

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/auth/login \
      -H "Content-Type: application/json" \
      -d '{
        "username": "analyst",
        "password": "secure-password-123"
      }'
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.post(
        "http://localhost:8080/v1/auth/login",
        json={"username": "analyst", "password": "secure-password-123"},
    )
    tokens = r.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    print(f"Access: {access_token[:20]}...")
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "analyst", password: "secure-password-123" }),
    });
    const { access_token, refresh_token } = await response.json();
    ```

### Refresh Token

```bash
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<your-refresh-token>"}'
```

### Get Current User

```bash
curl http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### Logout

```bash
curl -X POST http://localhost:8080/v1/auth/logout \
  -H "Authorization: Bearer <access_token>"
```

---

## Feedback

### Submit Positive Feedback

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/feedback \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer <access_token>" \
      -d '{
        "feedback_id": "fb-abc123",
        "rating": "positive",
        "comment": "Answer was accurate and well-sourced"
      }'
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.post(
        "http://localhost:8080/v1/feedback",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "feedback_id": "fb-abc123",
            "rating": "positive",
            "comment": "Answer was accurate and well-sourced",
        },
    )
    print(r.json())  # {"status": "ok", "message": "Feedback recorded"}
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/feedback", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({
        feedback_id: "fb-abc123",
        rating: "positive",
        comment: "Answer was accurate and well-sourced",
      }),
    });
    console.log(await response.json());
    ```

### Submit Negative Feedback with Correction

```bash
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{
    "feedback_id": "fb-def456",
    "rating": "negative",
    "comment": "Answer missed the latest policy update",
    "correction": "The correct procedure is to submit via the new portal"
  }'
```

!!! note
    The `feedback_id` comes from the `rag_feedback_id` field in the chat completion response. The `correction` field (singular) provides the corrected answer text. The `comment` field is an optional expert note. Requires `expert` or `admin` role.

---

## Files

The files API provides upload, download, list, and delete operations backed by MinIO. Requires `user` role or above.

!!! info
    The files API requires MinIO/S3 to be configured. Install `boto3` (`pip install boto3`) and set the `MINIO_*` environment variables in `proxy/.env`.

### Upload File

=== "curl"

    ```bash
    curl -X POST http://localhost:8080/v1/files \
      -H "Authorization: Bearer <access_token>" \
      -F "file=@/path/to/document.pdf"
    ```

=== "Python"

    ```python
    import httpx

    with open("/path/to/document.pdf", "rb") as f:
        r = httpx.post(
            "http://localhost:8080/v1/files",
            headers={"Authorization": f"Bearer {access_token}"},
            files={"file": ("document.pdf", f, "application/pdf")},
        )
    print(r.json())
    # {"id": "abc123", "filename": "document.pdf", "size": 102400, ...}
    ```

=== "JavaScript"

    ```javascript
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    const response = await fetch("http://localhost:8080/v1/files", {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
      body: formData,
    });
    console.log(await response.json());
    ```

**Allowed file types:** PDF, plain text, Markdown, CSV, JSON, JSONL, XLSX, DOCX (max 100 MB).

### List Files

=== "curl"

    ```bash
    curl http://localhost:8080/v1/files \
      -H "Authorization: Bearer <access_token>"

    # With prefix filter
    curl "http://localhost:8080/v1/files?prefix=documents/" \
      -H "Authorization: Bearer <access_token>"
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.get(
        "http://localhost:8080/v1/files",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    for f in r.json()["files"]:
        print(f"{f['filename']} ({f['size']} bytes)")
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch("http://localhost:8080/v1/files", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const data = await response.json();
    data.files.forEach((f) => console.log(`${f.filename} (${f.size} bytes)`));
    ```

### Download File

=== "curl"

    ```bash
    curl -o output.pdf http://localhost:8080/v1/files/<file_id> \
      -H "Authorization: Bearer <access_token>"
    ```

=== "Python"

    ```python
    import httpx

    r = httpx.get(
        f"http://localhost:8080/v1/files/{file_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with open("output.pdf", "wb") as f:
        f.write(r.content)
    ```

=== "JavaScript"

    ```javascript
    const response = await fetch(`http://localhost:8080/v1/files/${fileId}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const blob = await response.blob();
    ```

### Get File Metadata

```bash
curl http://localhost:8080/v1/files/<file_id>/metadata \
  -H "Authorization: Bearer <access_token>"
```

### Get Presigned URL

```bash
curl "http://localhost:8080/v1/files/<file_id>/presign?expiration=3600" \
  -H "Authorization: Bearer <access_token>"
```

### Delete File

```bash
curl -X DELETE http://localhost:8080/v1/files/<file_id> \
  -H "Authorization: Bearer <access_token>"
```

!!! warning
    Deleting files requires `expert` or `admin` role.

---

## Tools

### List All Tools

```bash
curl http://localhost:8080/v1/tools
```

### Filter Tools by Category

```bash
curl "http://localhost:8080/v1/tools?category=search"
```

### Get Tool Details

```bash
curl http://localhost:8080/v1/tools/confluence_search
```

---

## Model Evolution (Admin)

### List Registered Models

```bash
curl http://localhost:8080/v1/admin/models \
  -H "Authorization: Bearer <admin_token>"
```

### Trigger Training Job

```bash
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_type": "slm",
    "base_model": "Qwen/Qwen2.5-3B",
    "dataset_path": "/data/training/feedback.jsonl",
    "epochs": 3,
    "learning_rate": 2e-4
  }'
```

### Check Training Status

```bash
curl http://localhost:8080/v1/admin/models/status/<job_id> \
  -H "Authorization: Bearer <admin_token>"
```

### Promote Model Version

```bash
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_name": "slm-router",
    "version": "v3",
    "stage": "production"
  }'
```

### Rollback Model

```bash
curl -X POST http://localhost:8080/v1/admin/models/rollback \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_name": "slm-router",
    "target_version": "v2"
  }'
```

### Configure Canary Traffic Split

```bash
curl -X POST http://localhost:8080/v1/admin/models/canary/split \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_name": "slm-router",
    "canary_version": "v3",
    "traffic_percent": 10
  }'
```

### Get Canary Status

```bash
curl http://localhost:8080/v1/admin/models/canary/status \
  -H "Authorization: Bearer <admin_token>"
```

### Evaluate Model Quality

```bash
curl -X POST http://localhost:8080/v1/admin/models/evaluate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{
    "model_name": "slm-router",
    "version": "v3",
    "eval_dataset": "/data/eval/test_set.jsonl"
  }'
```

---

## Metrics

### Prometheus Metrics

```bash
curl http://localhost:8080/metrics
```

### Key Metrics to Monitor

```bash
# Request count by endpoint
curl http://localhost:8080/metrics | grep rag_requests_total

# Latency histogram
curl http://localhost:8080/metrics | grep rag_request_duration_seconds

# Active connections
curl http://localhost:8080/metrics | grep rag_active_connections

# Cache hit rate
curl http://localhost:8080/metrics | grep rag_cache_hits_total
```

---

## Widget

### Embeddable Chat Widget (HTML)

```bash
curl http://localhost:8080/v1/widget
```

### Widget JavaScript

```bash
curl http://localhost:8080/v1/widget.js
```

### Embed in HTML

```html
<!DOCTYPE html>
<html>
<head>
  <title>RAG Chat</title>
</head>
<body>
  <div id="rag-widget"></div>
  <script src="http://localhost:8080/v1/widget.js"></script>
  <script>
    RAGWidget.init({
      container: "#rag-widget",
      apiUrl: "http://localhost:8080",
      model: "rag-proxy",
      theme: "light",
    });
  </script>
</body>
</html>
```

---

## Error Handling

### Common HTTP Status Codes

| Code | Meaning | Typical Cause |
|------|---------|---------------|
| `200` | Success | Request completed |
| `400` | Bad Request | Invalid JSON or missing required fields |
| `401` | Unauthorized | Missing or expired JWT token |
| `403` | Forbidden | Insufficient RBAC role |
| `404` | Not Found | Endpoint or resource does not exist |
| `422` | Validation Error | Request body fails schema validation |
| `429` | Too Many Requests | Rate limit exceeded |
| `500` | Internal Server Error | Unexpected server failure |
| `502` | Bad Gateway | LLM backend unreachable |
| `503` | Service Unavailable | Proxy not ready or overloaded |

### Error Response Format

```json
{
  "error": {
    "message": "Invalid request: missing required field 'messages'",
    "type": "invalid_request_error",
    "code": "missing_field"
  }
}
```

### Handling Errors in Python

```python
import httpx

try:
    response = httpx.post(
        "http://localhost:8080/v1/chat/completions",
        json={"model": "rag-proxy", "messages": []},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
except httpx.HTTPStatusError as e:
    error = e.response.json().get("error", {})
    print(f"API Error {e.response.status_code}: {error.get('message')}")
except httpx.ConnectError:
    print("Cannot connect to RAG proxy. Is it running?")
except httpx.TimeoutException:
    print("Request timed out. The LLM backend may be slow.")
```

### Handling Errors in JavaScript

```javascript
async function chatCompletion(messages) {
  try {
    const response = await fetch("http://localhost:8080/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: "rag-proxy", messages }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(`API Error ${response.status}: ${error.error?.message}`);
    }

    return await response.json();
  } catch (err) {
    if (err.name === "TypeError") {
      console.error("Cannot connect to RAG proxy. Is it running?");
    } else {
      console.error(err.message);
    }
  }
}
```

### Retry with Exponential Backoff (Python)

```python
import httpx
import time

def chat_with_retry(messages, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = httpx.post(
                "http://localhost:8080/v1/chat/completions",
                json={"model": "rag-proxy", "messages": messages},
                timeout=60.0,
            )
            if response.status_code == 429:
                wait = 2 ** attempt
                print(f"Rate limited. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise Exception("Max retries exceeded")
```

---

## Full Workflow Example

### Authenticated Chat with Feedback

=== "Python"

    ```python
    import httpx

    BASE = "http://localhost:8080/v1"

    # 1. Register
    r = httpx.post(f"{BASE}/auth/register", json={
        "username": "demo", "password": "demo123", "email": "demo@co.com"
    })
    print("Registered:", r.json())

    # 2. Login
    r = httpx.post(f"{BASE}/auth/login", json={
        "username": "demo", "password": "demo123"
    })
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Chat
    r = httpx.post(f"{BASE}/chat/completions", headers=headers, json={
        "model": "rag-proxy",
        "messages": [{"role": "user", "content": "How do I configure RBAC?"}],
    })
    answer = r.json()
    feedback_id = answer.get("rag_feedback_id")
    print("Answer:", answer["choices"][0]["message"]["content"][:200])

    # 4. Submit feedback (requires expert role)
    if feedback_id:
        r = httpx.post(f"{BASE}/feedback", headers=headers, json={
            "feedback_id": feedback_id,
            "rating": "positive",
            "comment": "Helpful answer",
        })
        print("Feedback submitted:", r.status_code, r.json())
    ```

=== "JavaScript"

    ```javascript
    const BASE = "http://localhost:8080/v1";

    // 1. Register
    await fetch(`${BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "demo", password: "demo123", email: "demo@co.com",
      }),
    });

    // 2. Login
    const loginRes = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "demo", password: "demo123" }),
    });
    const { access_token } = await loginRes.json();
    const headers = {
      "Content-Type": "application/json",
      Authorization: `Bearer ${access_token}`,
    };

    // 3. Chat
    const chatRes = await fetch(`${BASE}/chat/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        model: "rag-proxy",
        messages: [{ role: "user", content: "How do I configure RBAC?" }],
      }),
    });
    const answer = await chatRes.json();
    const feedbackId = answer.rag_feedback_id;
    console.log("Answer:", answer.choices[0].message.content.slice(0, 200));

    // 4. Submit feedback
    if (feedbackId) {
      await fetch(`${BASE}/feedback`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          feedback_id: feedbackId,
          rating: "positive",
          comment: "Helpful answer",
        }),
      });
    }
    ```
