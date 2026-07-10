# Quick Start Guide

**Version:** v2.0.0 | **Last Updated:** 2026-07-10

Get the RAG Knowledge Assistant up and running in 5 minutes. This guide covers local development setup with Docker Compose.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Docker** | 24.0+ | With Compose v2 plugin |
| **Python** | 3.11+ | For ETL and local dev |
| **RAM** | 16 GB minimum | 32 GB recommended |
| **Disk** | 20 GB free | SSD strongly recommended |
| **GPU** | Optional | CPU-only works for testing |

!!! tip "GPU Acceleration"
    An NVIDIA GPU with 12+ GB VRAM is recommended for LLM inference. Without a GPU, the system works in CPU mode with significantly slower response times. You can also point to a remote LLM endpoint.

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system
```

Expected output:

```
Cloning into 'rag-system'...
remote: Enumerating objects: ...
Receiving objects: 100% (...)
```

---

## Step 2 — Configure Environment

```bash
# Copy the example environment file
cp proxy/.env.example proxy/.env

# Edit with your settings (at minimum, set LLM endpoint)
nano proxy/.env
```

### Minimal Configuration

At minimum, configure these variables in `proxy/.env`:

```bash
# Qdrant (uses Docker service name by default)
QDRANT_HOST=qdrant

# LLM backend — choose one option:

# Option A: Local vLLM (requires GPU)
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=your-model-name
LLM_PROVIDER=vllm

# Option B: llama.cpp server
LLM_ENDPOINT=http://llama-cpp:8080/v1
LLM_MODEL_NAME=your-model-name
LLM_PROVIDER=llama_cpp

# Option C: Any OpenAI-compatible endpoint
LLM_ENDPOINT=https://your-api.example.com/v1
LLM_MODEL_NAME=your-model-name
LLM_PROVIDER=openai_compatible
```

!!! warning "No LLM Endpoint?"
    If you don't have an LLM backend yet, the system will start but chat completions will return errors. You can still test health endpoints and explore the API. See the [Deployment Guide](deployment-guide.md) for LLM setup instructions.

---

## Step 3 — Start Services

```bash
# Start all infrastructure (Qdrant + Redis + Neo4j + Proxy)
cd proxy && docker compose up -d
```

Expected output:

```
[+] Running 5/5
 ✔ Network proxy_default    Created
 ✔ Container qdrant         Started
 ✔ Container redis          Started
 ✔ Container neo4j          Started
 ✔ Container rag-proxy      Started
```

!!! note "First Start"
    The first startup takes 1-2 minutes as Docker images are downloaded. Subsequent starts take ~10 seconds.

### Verify Services

```bash
# Check all containers are running
docker compose ps

# Check proxy health
curl http://localhost:8080/v1/health
```

Expected health response:

```json
{
  "status": "healthy",
  "qdrant": "connected",
  "llm": "connected",
  "version": "2.0.0"
}
```

---

## Step 4 — Test the API

### Simple Chat Request

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "What is RAG?"}
    ]
  }'
```

### Streaming Response

```bash
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "user", "content": "Explain hybrid search in RAG systems"}
    ],
    "stream": true
  }'
```

### Using Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed",  # Auth disabled by default
)

response = client.chat.completions.create(
    model="rag-proxy",
    messages=[
        {"role": "user", "content": "What is RAG?"}
    ],
    stream=True,
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### Using JavaScript

```javascript
const response = await fetch("http://localhost:8080/v1/chat/completions", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "rag-proxy",
    messages: [{ role: "user", content: "What is RAG?" }],
  }),
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

---

## Step 5 — Explore the API

### List Available Models

```bash
curl http://localhost:8080/v1/models
```

### View Prometheus Metrics

```bash
curl http://localhost:8080/metrics
```

### Access the Chat Widget

Open in a browser:

```
http://localhost:8080/v1/widget
```

### K8s Health Probes

```bash
# Liveness
curl http://localhost:8080/v1/health/live

# Readiness
curl http://localhost:8080/v1/health/ready
```

---

## Common Pitfalls & Solutions

### 1. "Connection refused" on startup

**Symptom:** `curl: (7) Failed to connect to localhost port 8080`

**Cause:** Proxy container is still starting or crashed.

**Solution:**

```bash
# Check container status
docker compose ps

# Check proxy logs for errors
docker compose logs rag-proxy --tail=50

# If container exited, restart
docker compose restart rag-proxy
```

### 2. Qdrant connection errors

**Symptom:** Health check shows `"qdrant": "disconnected"`

**Cause:** Qdrant container not ready or wrong host configured.

**Solution:**

```bash
# Verify Qdrant is running
docker compose ps qdrant

# Check Qdrant logs
docker compose logs qdrant --tail=20

# Ensure QDRANT_HOST matches Docker service name
grep QDRANT_HOST proxy/.env
# Should be: QDRANT_HOST=qdrant (not localhost)
```

### 3. LLM backend not reachable

**Symptom:** Health check shows `"llm": "disconnected"`

**Cause:** LLM endpoint misconfigured or backend not running.

**Solution:**

```bash
# Test LLM endpoint directly
curl http://your-llm-endpoint:8000/v1/models

# Check proxy logs for connection details
docker compose logs rag-proxy | grep -i "llm"

# Update LLM_ENDPOINT in proxy/.env
```

### 4. Out of memory (OOM)

**Symptom:** Container killed unexpectedly, `dmesg` shows OOM killer.

**Cause:** Insufficient RAM for model + services.

**Solution:**

```bash
# Check memory usage
docker stats --no-stream

# Reduce memory: disable optional features
# In proxy/.env:
GRAPH_ENABLED=false    # Disable Neo4j
USE_REDIS=false        # Use in-memory cache
```

### 5. Port already in use

**Symptom:** `Bind for 0.0.0.0:8080 failed: port is already allocated`

**Solution:**

```bash
# Find what's using the port
lsof -i :8080

# Change the port in docker-compose.yml
# Or stop the conflicting service
```

### 6. Permission denied on volumes

**Symptom:** `PermissionError` in container logs.

**Solution:**

```bash
# Fix data directory permissions
sudo chown -R 1000:1000 proxy/data/
```

---

## Next Steps

Now that the system is running:

| Goal | Guide |
|------|-------|
| **Ingest your data** | [ETL Guide](etl-guide.md) — Connect Confluence, Jira, GitLab |
| **Deploy to production** | [Deployment Guide](deployment-guide.md) — K8s, HA, GPU setup |
| **Explore the API** | [API Examples](api-examples.md) — curl, Python, JavaScript examples |
| **Full API reference** | [API Reference](../../api_reference.md) — All endpoints, schemas, parameters |
| **Configure authentication** | [Access Control](access-control-rbac.md) — JWT, Keycloak, LDAP |
| **Add custom tools** | [Agentic Tools SDK](agentic-tools-sdk.md) — `@tool` decorator |
| **Tune performance** | [Performance & Quality](performance-quality.md) — HNSW, caching, quantization |
| **Monitor the system** | [Operations Guide](operations-guide.md) — Prometheus, Grafana, alerts |

---

## Stopping Services

```bash
cd proxy

# Stop all services (preserves data)
docker compose down

# Stop and remove volumes (clean slate)
docker compose down -v

# Stop and remove images
docker compose down -v --rmi all
```

---

## Quick Reference

| Command | Description |
|---------|-------------|
| `docker compose up -d` | Start all services |
| `docker compose down` | Stop all services |
| `docker compose logs -f` | Follow all logs |
| `docker compose logs rag-proxy` | Proxy logs only |
| `docker compose ps` | List running containers |
| `docker compose restart` | Restart all services |
| `curl localhost:8080/v1/health` | Health check |
| `curl localhost:8080/v1/models` | List models |
| `curl localhost:8080/metrics` | Prometheus metrics |
