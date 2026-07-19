# Proxy Deployment Guide

The RAG Proxy is the core serving layer — a FastAPI application exposing an OpenAI-compatible API. It connects to
Qdrant (vector search), Neo4j (knowledge graph), Redis (cache), and an LLM backend (vLLM, llama.cpp, or any
OpenAI-compatible endpoint).

---

## Prerequisites

| Component                    | Minimum | Recommended |
|------------------------------|---------|-------------|
| **Docker**                   | 24.0+   | 27.0+       |
| **Docker Compose**           | v2.20+  | v2.30+      |
| **NVIDIA Driver**            | 535+    | 550+        |
| **NVIDIA Container Toolkit** | 1.14+   | 1.17+       |
| **Python** (bare-metal only) | 3.11    | 3.12        |

### Verify GPU Access

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

If the second command fails, install the NVIDIA Container Toolkit:

```bash
# Ubuntu/Debian
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

---

## Infrastructure Requirements

| Resource     | Minimum                | Recommended (Production) |
|--------------|------------------------|--------------------------|
| **CPU**      | 8 cores                | 16+ cores                |
| **RAM**      | 32 GB                  | 64+ GB                   |
| **GPU VRAM** | 24 GB (quantized GGUF) | 48+ GB (full precision)  |
| **Disk**     | 100 GB SSD             | 500+ GB NVMe             |
| **Network**  | 1 Gbps                 | 10 Gbps (internal)       |

**Disk breakdown:**

- Qdrant vectors: ~30 GB
- Neo4j graph: ~10 GB
- Model files: ~20 GB
- Raw data + chunks: ~20 GB
- Logs: ~10 GB

---

## Quick Start (Docker Compose)

```bash
cd proxy

# 1. Configure environment
cp .env.example .env
# Edit .env with your settings (see Configuration section below)

# 2. Start all services
docker-compose up -d

# 3. Check status
docker-compose ps
# Expected: qdrant, neo4j, redis, llm, rag-proxy, hitl-dashboard — all "Up"

# 4. Verify health
curl http://localhost:8080/v1/health
# {"status":"ok","components":{"qdrant":"ok","llm":"ok"}}

# 5. List models
curl http://localhost:8080/v1/models
```

---

## Configuration

All proxy settings are in `proxy/.env`. Copy the example and edit:

```bash
cp proxy/.env.example proxy/.env
```

### Required Settings

```ini
# Qdrant connection
QDRANT_HOST=qdrant
QDRANT_PORT=6333
COLLECTION_NAME=knowledge_base

# LLM endpoint (vLLM, llama.cpp, or any OpenAI-compatible backend)
LLM_ENDPOINT=http://llm:8000/v1
LLM_MODEL_NAME=your-model-name
LLM_API_KEY=           # optional; must match backend --api-key if set

# Embedding model
EMBEDDER_MODEL=your-embedding-model
EMBEDDER_DEVICE=cpu    # "cpu" or "cuda"

# Reranker
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_MAX_LENGTH=512
RERANKER_BATCH_SIZE=32

# Server
HOST=0.0.0.0
PORT=8080
WORKERS=1              # Keep at 1 for shared embedder/cache safety
```

### Optional Feature Flags

```ini
# Agentic orchestration (LangGraph 7-node state graph)
USE_LANGGRAPH=true
MAX_RETRIEVAL_LOOPS=3

# Redis caching
USE_REDIS=true
REDIS_URL=redis://redis:6379

# Graph knowledge base
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_secure_password
USE_GRAPH_EXPANSION=true

# Rate limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10

# SLM (small model for query routing)
SLM_ENDPOINT=http://llm:8000/v1
SLM_MODEL_NAME=your-slm-model-name
SLM_MAX_TOKENS=256
```

### Observability

```ini
# Metrics
METRICS_ENABLED=true

# Logging
LOG_REQUESTS=true
LOG_DIR=./logs
LOG_FORMAT=json              # "json" for structured, "text" for human-readable
SENSITIVE_SECRETS=password,token,key
```

### Tuning

```ini
# RAG pipeline
MAX_CHUNKS_RETRIEVAL=50      # Chunks to fetch from Qdrant
MAX_CHUNKS_AFTER_RERANK=20   # Chunks after cross-encoder reranking

# LLM communication
REQUEST_TIMEOUT=120          # LLM request timeout (seconds)
MAX_RETRIES=3                # Retry attempts on failure
RETRY_DELAY=1.0              # Delay between retries (seconds)

# CORS
CORS_ORIGINS=*              # Allowed origins; use specific domains in production
```

### Full Configuration Reference

See `proxy/app/config.py` for all 40+ environment variables and their defaults.

---

## Service Architecture

The `docker-compose.yml` defines these services:

```
┌──────────────────────────────────────────────────┐
│                  Docker Network                    │
│                                                   │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
│  │ qdrant   │  │ redis   │  │ neo4j   │          │
│  │ :6333    │  │ :6379   │  │ :7687   │          │
│  └────┬─────┘  └────┬────┘  └────┬────┘          │
│       │              │            │               │
│       └──────────────┼────────────┘               │
│                      │                            │
│               ┌──────┴──────┐                    │
│               │  rag-proxy  │                    │
│               │    :8080    │                    │
│               └──────┬──────┘                    │
│                      │                            │
│               ┌──────┴──────┐                    │
│               │    llm      │                    │
│               │    :8000    │                    │
│               └─────────────┘                    │
│                                                   │
│  ┌──────────────────┐                            │
│  │ hitl-dashboard   │                            │
│  │    :8501         │                            │
│  └──────────────────┘                            │
└──────────────────────────────────────────────────┘
```

### Service Details

| Service            | Image                               | Port       | GPU     | Purpose                                          |
|--------------------|-------------------------------------|------------|---------|--------------------------------------------------|
| **qdrant**         | `qdrant/qdrant:latest`              | 6333, 6334 | No      | Vector database for hybrid search                |
| **redis**          | `redis:7-alpine`                    | 6379       | No      | Multi-tier cache (embeddings, rerank, responses) |
| **neo4j**          | `neo4j:5-enterprise`                | 7474, 7687 | No      | Knowledge graph for entity relationships         |
| **llm**            | Custom or `vllm/vllm-openai:latest` | 8000       | **Yes** | LLM inference server (your model)                |
| **rag-proxy**      | Custom (FastAPI)                    | 8080       | No      | OpenAI-compatible API with RAG pipeline          |
| **hitl-dashboard** | Custom (Streamlit)                  | 8501       | No      | Expert review and feedback dashboard             |

---

## Graceful Degradation

The proxy is designed to never crash on component failure. Each dependency fails independently:

| Component Unavailable | Behavior                                                      |
|-----------------------|---------------------------------------------------------------|
| **Qdrant**            | Retrieval returns empty results; LLM responds without context |
| **Neo4j**             | Graph expansion skipped; retrieval falls back to vector-only  |
| **Redis**             | Falls back to in-memory cache; no persistence, lower hit rate |
| **LLM backend**       | `/v1/health` returns 503; all completions fail with 503       |
| **Reranker OOM**      | Uses raw hybrid scores instead of cross-encoder scores        |

Health check (`/v1/health`) reports degraded status with per-component details.

---

## Security

### Reverse Proxy with TLS

Place nginx or Caddy in front of the proxy:

```nginx
# /etc/nginx/sites-available/rag-proxy
server {
    listen 443 ssl http2;
    server_name rag-proxy.internal.company.com;

    ssl_certificate     /etc/ssl/certs/rag-proxy.crt;
    ssl_certificate_key /etc/ssl/private/rag-proxy.key;

    # Optional: Basic auth
    auth_basic "RAG System";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location /v1/ {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;  # Allow long LLM generations
        proxy_buffering off;      # Required for SSE streaming
    }

    location /metrics {
        # Internal only — deny external access
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        deny all;
        proxy_pass http://localhost:8080;
    }
}
```

### Production Security Checklist

- [ ] Change all default passwords (Neo4j, Qdrant API key if set)
- [ ] Set `LLM_API_KEY` and configure the LLM backend with `--api-key`
- [ ] Use reverse proxy with TLS in front of port 8080
- [ ] Enable firewall: only expose 8080 and 8501 externally
- [ ] Set `LOG_FORMAT=json` for structured audit logs
- [ ] Configure `SENSITIVE_SECRETS=password,token,key` for log masking
- [ ] Restrict `/metrics` endpoint to internal IPs
- [ ] Set `CORS_ORIGINS` to specific domains (not `*`)

---

## Air-Gapped Deployment

### 1. Download Models

On an internet-connected machine:

```bash
cd rag-system

# Download all required models
python scripts/download_models_offline.py \
  --output-dir ./offline_models \
  --models embedder reranker spacy_ru spacy_en slm \
  --gguf-url https://huggingface.co/your-org/your-model-GGUF/resolve/main/your-model.gguf

# Package
tar -czf offline_models.tar.gz offline_models/
scp offline_models.tar.gz user@airgap-machine:/opt/rag-system/
```

### 2. Transfer Docker Images

```bash
# On internet-connected machine
docker pull qdrant/qdrant:latest
docker pull neo4j:5-enterprise
docker pull redis:7-alpine
docker pull vllm/vllm-openai:latest  # or your LLM backend image
docker pull python:3.11-slim

docker save qdrant/qdrant:latest neo4j:5-enterprise redis:7-alpine \
  vllm/vllm-openai:latest python:3.11-slim -o rag-images.tar

scp rag-images.tar user@airgap-machine:/opt/rag-system/

# On air-gapped machine
docker load -i rag-images.tar
```

### 3. Offline pip Packages

```bash
# On internet-connected machine
mkdir pip-offline
pip download -r proxy/requirements_proxy.txt -d pip-offline/

tar -czf pip-offline.tar.gz pip-offline/
scp pip-offline.tar.gz user@airgap-machine:/opt/rag-system/
```

### 4. Configure and Start

```bash
# On air-gapped machine
cd /opt/rag-system
tar -xzf offline_models.tar.gz

# Update docker-compose.yml volume mounts:
#   llm: /opt/rag-system/offline_models:/models:ro
#   rag-proxy: /opt/rag-system/offline_models/cache:/app/cache:ro

# Edit proxy/.env with your settings
# QDRANT_HOST=qdrant (docker service name)
# LLM_ENDPOINT=http://llm:8000/v1

cd proxy
docker-compose up -d
```

---

## Scaling

### Vertical Scaling

Increase resources for the LLM container:

```yaml
# docker-compose.yml
llm:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 2              # Use 2 GPUs
            capabilities: [gpu]
  command: >
    --model /models/your-model.gguf
    --tensor-parallel-size 2     # Split across 2 GPUs
    --max-model-len 65536
    --max-num-seqs 16
```

### Horizontal Scaling

```bash
# Scale proxy replicas (requires Redis for shared state)
docker-compose up -d --scale rag-proxy=3

# Place a load balancer (nginx/HAProxy) in front:
#   upstream rag_proxy {
#       server proxy1:8080;
#       server proxy2:8080;
#       server proxy3:8080;
#   }
```

**Note:** The LLM backend handles concurrency internally (up to 16 concurrent sequences). The proxy can scale
horizontally, but each replica must share Redis for cache coherence.

---

## Monitoring

### Health Checks

```bash
# Proxy health (includes dependency status)
curl http://localhost:8080/v1/health

# Individual service health
curl http://localhost:6333/health               # Qdrant
docker exec rag-neo4j cypher-shell -u neo4j -p password "RETURN 1"  # Neo4j
docker exec rag-redis redis-cli PING           # Redis
curl http://localhost:8000/health               # LLM backend
```

### Prometheus Metrics

Scrape `/metrics` on the proxy and all services. Key alerts:

```yaml
# prometheus-alerts.yml
groups:
  - name: rag-system
    rules:
      - alert: HighErrorRate
        expr: rate(rag_errors_total[5m]) > 0.05
        annotations:
          summary: "RAG error rate >5%"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 30
        annotations:
          summary: "P95 latency >30 seconds"

      - alert: LowCacheHitRate
        expr: rag_cache_hit_ratio < 0.3
        annotations:
          summary: "Cache hit ratio below 30%"

      - alert: LLMDown
        expr: up{job="llm"} == 0
        annotations:
          summary: "LLM backend is down"
```

### Container Health

All containers include Docker healthchecks:

```bash
# View health status
docker-compose ps

# View specific container logs
docker-compose logs -f rag-proxy
docker-compose logs -f llm --tail 100
```

---

## Backup

### Qdrant Snapshots

```bash
# Create snapshot
curl -X POST http://localhost:6333/collections/knowledge_base/snapshots

# List snapshots
curl http://localhost:6333/collections/knowledge_base/snapshots

# Download snapshot
curl http://localhost:6333/collections/knowledge_base/snapshots/<snapshot-name> -o qdrant_snapshot.tar
```

Schedule daily snapshots via cron:

```cron
0 2 * * * curl -X POST http://localhost:6333/collections/knowledge_base/snapshots
```

### Neo4j Dumps

```bash
docker exec rag-neo4j neo4j-admin database dump neo4j --to-path=/backups/
docker cp rag-neo4j:/backups/neo4j.dump ./neo4j_backup_$(date +%Y%m%d).dump
```

### Configuration Backup

```bash
# Backup critical configs
tar -czf rag-config-backup.tar.gz \
  proxy/.env \
  proxy/docker-compose.yml \
  etl/config/etl_config.yaml
```

### Retention Policy

- Keep 7 daily + 4 weekly + 3 monthly backups
- Store backups on a separate machine or network-attached storage
- Test restore procedure quarterly

---

## Troubleshooting

### Proxy Won't Start

```bash
# Check logs
docker-compose logs rag-proxy

# Common causes:
# 1. Port conflict
ss -tlnp | grep 8080
# Fix: change PORT in .env

# 2. Missing .env file
ls -la proxy/.env
# Fix: cp proxy/.env.example proxy/.env

# 3. Configuration error
docker run --rm -v $(pwd)/.env:/app/.env:ro rag-proxy python -c "from app.config import print_config; print_config()"
```

### LLM Backend Won't Start

```bash
# Check GPU access
docker run --rm --gpus all vllm/vllm-openai:latest nvidia-smi

# Check model file
ls -la /opt/rag-system/offline_models/your-model.gguf

# Check logs
docker-compose logs llm --tail 50

# Common OOM fix — reduce context window:
# Edit docker-compose.yml llm command:
#   --max-model-len 32768  (instead of 130000)
```

### OOM (Out of Memory)

```bash
# LLM backend OOM: reduce model context, use smaller quant
--max-model-len 32768
--gpu-memory-utilization 0.80

# Neo4j OOM: reduce heap
NEO4J_dbms_memory_heap_max__size=1G

# Redis OOM: set memory limit
redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru

# Proxy OOM: reduce batch sizes
MAX_CHUNKS_RETRIEVAL=30
RERANKER_BATCH_SIZE=8
```

### Poor Search Results

```bash
# Verify embedder model
grep EMBEDDER_MODEL proxy/.env

# Verify collection schema (dense + sparse)
curl http://localhost:6333/collections/knowledge_base | python -m json.tool

# Recreate collection with correct schema
python scripts/init_collections.py --qdrant-recreate
```

See the full [Troubleshooting Guide](guides/troubleshooting.md) for more issues and solutions.
