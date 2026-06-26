# Deployment Guide

## Prerequisites

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **Docker** | 24.0+ | 27.0+ |
| **Docker Compose** | v2.20+ (plugin) | v2.30+ |
| **NVIDIA Driver** | 535+ | 550+ |
| **NVIDIA Container Toolkit** | 1.14+ | 1.17+ |
| **Python** | 3.11 | 3.12 |

Verify GPU availability:
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

## Infrastructure Requirements

| Resource | Minimum | Recommended (prod) |
|----------|---------|---------------------|
| **CPU** | 8 cores | 16+ cores |
| **RAM** | 32 GB | 64+ GB |
| **GPU VRAM** | 24 GB (quantized GGUF) | 48+ GB (full precision) |
| **Disk** | 100 GB SSD | 500+ GB NVMe |
| **Network** | 1 Gbps | 10 Gbps (internal) |

**Disk breakdown**: Qdrant vectors ~30 GB, Neo4j graph ~10 GB, model files ~20 GB, raw data + chunks ~20 GB, logs ~10 GB.

## Air-Gapped Deployment

In an air-gapped environment, download all assets on an internet-connected machine, then transfer them.

### 1. Download Models Offline

```bash
# On internet-connected machine:
cd rag-system
python scripts/download_models_offline.py \
  --output-dir ./offline_models \
  --models embedder reranker spacy_ru spacy_en slm \
  --gguf-url https://huggingface.co/your-org/your-model-GGUF/resolve/main/your-model-Q4_K_M.gguf

# This downloads:
# - BAAI/bge-m3 (embedder + sparse)
# - cross-encoder/ms-marco-MiniLM-L-6-v2 (reranker)
# - ru_core_news_sm, en_core_web_sm (spaCy)
# - your-slm-model (SLM)
# - your-llm-model GGUF (LLM)

# Transfer to air-gapped machine:
tar -czf offline_models.tar.gz offline_models/
scp offline_models.tar.gz user@airgap-machine:/opt/rag-system/
```

### 2. Transfer Docker Images

```bash
# On internet-connected machine:
docker pull qdrant/qdrant:latest
docker pull neo4j:5-enterprise
docker pull redis:7-alpine
docker pull python:3.11-slim

docker save qdrant/qdrant:latest neo4j:5-enterprise redis:7-alpine \
  python:3.11-slim -o rag-images.tar

# For LLM backend (choose one):
# - vLLM: docker pull vllm/vllm-openai:latest
# - llama.cpp: docker pull ghcr.io/ggerganov/llama.cpp:server
# - Any OpenAI-compatible server

scp rag-images.tar user@airgap-machine:/opt/rag-system/

# On air-gapped machine:
docker load -i rag-images.tar
```

### 3. Offline pip Packages

```bash
# On internet-connected machine:
mkdir pip-offline
pip download -r proxy/requirements_proxy.txt -d pip-offline/
pip download -r etl/requirements_etl.txt -d pip-offline/

tar -czf pip-offline.tar.gz pip-offline/
scp pip-offline.tar.gz user@airgap-machine:/opt/rag-system/
```

## Step-by-Step Deployment

### Step 1: Configure Environment

```bash
cp proxy/.env proxy/.env.bak
# Edit proxy/.env with your settings:
```

Key variables to configure:
```ini
QDRANT_HOST=qdrant
QDRANT_PORT=6333
LLM_ENDPOINT=http://llm-backend:8000/v1
LLM_MODEL_NAME=your-model-name
REQUEST_TIMEOUT=120
USE_REDIS=true
REDIS_URL=redis://redis:6379
USE_LANGGRAPH=true
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_PASSWORD=your_secure_password
```

### Step 2: Update Model Paths

In `proxy/docker-compose.yml`, update the LLM backend volume:
```yaml
volumes:
  - /opt/rag-system/offline_models:/models:ro
```
And the rag-proxy volume:
```yaml
volumes:
  - /opt/rag-system/offline_models/cache:/app/cache:ro
```

### Step 3: Initialize Qdrant Collections

```bash
# Ensure Qdrant is running first, then:
python scripts/init_collections.py --qdrant-recreate

# Verify:
curl http://localhost:6333/collections/knowledge_base
```

### Step 4: Start Services

```bash
cd proxy
docker-compose up -d

# Check all containers are healthy:
docker-compose ps
# Expected: qdrant, neo4j, redis, llm-backend, rag-proxy, hitl-dashboard — all "Up"
```

### Step 5: Verify Health

```bash
# Proxy health endpoint:
curl http://localhost:8080/v1/health
# Response: {"status": "healthy", "qdrant": "connected", "llm": "available"}

# List models:
curl http://localhost:8080/v1/models
# Response: {"data": [{"id": "your-model-name", ...}]}
```

### Step 6: Run First ETL Pipeline

```bash
cd ../etl
# Edit config/etl_config.yaml with your source credentials
python scheduler/run_etl.py --config config/etl_config.yaml

# Or via Docker:
docker build -f Dockerfile.etl -t rag-etl .
docker run --rm --network=host \
  -v $(pwd)/wal:/wal \
  -v $(pwd)/chunks:/chunks \
  rag-etl --config /app/etl/config/etl_config.yaml
```

## Production Checklist

### Security
- [ ] Change ALL default passwords (Neo4j, Qdrant API key if set)
- [ ] Set `LLM_API_KEY` and restrict LLM backend with `--api-key`
- [ ] Use reverse proxy (nginx/Caddy) with TLS in front of port 8080
- [ ] Enable firewall: only expose 8080 and 8501 externally
- [ ] Set `LOG_REQUESTS=true` but mask `SENSITIVE_SECRETS` in config
- [ ] Configure log rotation for feedback logs and proxy logs

### Nginx with TLS Termination

```nginx
# /etc/nginx/sites-available/rag-proxy
server {
    listen 443 ssl http2;
    server_name rag-proxy.internal.company.com;

    ssl_certificate     /etc/ssl/certs/rag-proxy.crt;
    ssl_certificate_key /etc/ssl/private/rag-proxy.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location /v1/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        proxy_buffering off;  # Required for SSE streaming
    }

    location /metrics {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

### Log Rotation

```bash
# /etc/logrotate.d/rag-system
./logs/feedback/*.jsonl {
    daily
    rotate 7
    maxsize 100M
    compress
    missingok
    notifempty
}

./logs/proxy/*.log {
    daily
    rotate 14
    maxsize 50M
    compress
    missingok
    notifempty
    postrotate
        docker exec rag-proxy kill -HUP 1 2>/dev/null || true
    endscript
}
```

### Monitoring
- [ ] Configure Prometheus to scrape `/metrics` on all services
- [ ] Set up alerts: disk >80%, RAM >85%, GPU utilization >95%, proxy 5xx rate
- [ ] Enable Docker healthchecks for all containers

### Backup
- [ ] Schedule daily Qdrant snapshots: `POST /collections/knowledge_base/snapshots`
- [ ] Schedule daily Neo4j dumps: `neo4j-admin database dump`
- [ ] Back up `wal/etl_wal.json` and `wal/version_wal.json` after each ETL run
- [ ] Keep 7 daily + 4 weekly + 3 monthly backups

## Troubleshooting Common Issues

### OOM (Out of Memory)
```bash
# LLM backend OOM: reduce context, use quantized model
# For vLLM, edit docker-compose.yml backend command:
--max-model-len 65536  # instead of 130000
--tensor-parallel-size 1

# Neo4j OOM: reduce heap
NEO4J_dbms_memory_heap_max__size=1G  # instead of 2G
```

### Port Conflicts
```bash
# Check what's using ports:
ss -tlnp | grep -E '6333|6379|7687|8000|8080|8501'

# Override in docker-compose.yml or .env
```

### Disk Space
```bash
# Prune unused Docker data:
docker system prune -a --volumes -f

# Clean old ETL cold chunks:
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete

# Rotate logs:
find proxy/logs/ -name "*.log" -mtime +7 -delete
```

### LLM Backend Won't Start
```bash
# Check GPU access:
docker run --rm --gpus all your-llm-backend-image nvidia-smi

# Verify model file exists:
ls -la /opt/rag-system/offline_models/your-model.gguf

# Check backend logs:
docker logs rag-llm-backend
```
