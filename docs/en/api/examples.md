# RAG System API Examples

Quick reference for the most common API calls. All examples assume the proxy
is running at `http://localhost:8080`. For a complete reference see
[`reference.md`](reference.md) and the OpenAPI schema in [`openapi.json`](openapi.json).

## Quick Start

### Health Check

```bash
curl -X GET http://localhost:8080/v1/health/live
# {"status":"alive","timestamp":"..."}

curl -X GET http://localhost:8080/v1/health/ready
# {"status":"ready","components":{"qdrant":"ok","llm":"ok"}}
```

### List Models

```bash
curl -X GET http://localhost:8080/v1/models
# Returns list of models with +RAG suffix variants
```

### Chat with RAG (Non-streaming)

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-635b+RAG",
    "messages": [{"role": "user", "content": "What is RAG?"}]
  }'
```

### Chat with RAG (Streaming)

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-635b+RAG",
    "stream": true,
    "messages": [{"role": "user", "content": "Explain RAG"}]
  }'
```

### Direct LLM Passthrough

```bash
# Without +RAG suffix — direct LLM call, no retrieval
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-635b",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## Python Examples

### Using OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed",
)

# RAG chat
response = client.chat.completions.create(
    model="qwen3-635b+RAG",
    messages=[{"role": "user", "content": "What is RAG?"}],
)
print(response.choices[0].message.content)

# Streaming
stream = client.chat.completions.create(
    model="qwen3-635b+RAG",
    messages=[{"role": "user", "content": "Explain"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

## RAG Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| rag_version | string | Request specific document version (e.g., "v1") |
| rag_force_refresh | bool | Bypass response cache |
| rag_skip_generation | bool | Search-only mode (return chunks without LLM) |
| rag_return_chunks | bool | Include chunks in response |
| rag_top_k | int | Override number of chunks after rerank |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| rag_feedback_id | string | ID for submitting expert feedback |
| rag_confidence | float (0-1) | System's confidence in answer |
| rag_sources | array | List of source chunks used |
| rag_knowledge_status | string | "found", "absent", "partial" |
