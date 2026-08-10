# RAG System — Distributed Deployment Guide

**Production deployment with GPUStack on Machine A, RAG proxy + Qdrant + Redis + Open WebUI on Machine B, ETL on user laptop.**

---

## Architecture

```
┌──────────────────────────┐         ┌────────────────────────────────┐         ┌──────────────────────┐
│  MACHINE A (GPU)         │         │  MACHINE B (Proxy)            │         │  USER LAPTOP         │
│  GPUStack                │         │                                │         │                      │
│                          │         │  ┌──────────────┐             │         │  ┌────────────────┐   │
│  ┌────────────────────┐  │         │  │ Open WebUI    │             │         │  │ ETL Pipeline   │   │
│  │ Qwen 3.6 (LLM)     │──┼────┐    │  │ :3000         │             │         │  │                │   │
│  │ 8K context         │  │    │    │  └──────┬───────┘             │         │  │ • Confluence   │   │
│  └────────────────────┘  │    │    │         │ HTTPS                │         │  │ • Jira         │   │
│  ┌────────────────────┐  │    ├────┼─────────┘                       │         │  │ • GitLab       │   │
│  │ Saiga (SLM)        │──┼────┘    │  ┌──────▼───────┐               │         │  │ • Docs/Books   │   │
│  │ Routing, classify  │  │         │  │ RAG Proxy    │               │         │  └────────┬───────┘   │
│  └────────────────────┘  │         │  │ :8080        │               │         │           │           │
│  ┌────────────────────┐  │         │  └──────┬───────┘               │         │           │ HTTPS     │
│  │ BGE-m3 (Embedder)  │──┼─────────┼──┐       │                       │         │           │ (VPN)     │
│  │ 1024-dim dense     │  │         │  │       │                       │         │           │           │
│  │ + sparse + ColBERT │  │         │  │  ┌────▼──────┐               │  HTTPS  │           ▼           │
│  └────────────────────┘  │         │  │  │ Qdrant    │               ├─────────┘   ┌────────────────┐   │
│  ┌────────────────────┐  │         │  │  │ :6333     │               │             │  GPUStack       │   │
│  │ BGE-reranker-v2-m3│──┼─────────┼──┘  │ :6334 gRPC │               │             │  (Machine A)    │   │
│  │ Cross-encoder      │  │         │     └───────────┘               │             └────────────────┘   │
│  └────────────────────┘  │         │                                │                                │
│                          │         │  ┌───────────┐                 │                                │
│  API: http://<A>:8080/v1 │         │  │ Redis     │                 │                                │
│  Token: sk-xxxxx         │         │  │ :6379     │                 │                                │
└──────────────────────────┘         │  └───────────┘                 │                                │
                                     │                                │                                │
                                     │  ┌─────────────────┐ (optional)│                                │
                                     │  │ Prometheus+Grafana│          │                                │
                                     │  └─────────────────┘           │                                │
                                     └────────────────────────────────┘                                │
                                                                                                    │
                          All connections are TLS/HTTPS over the corporate network.            │
```

---

## Network Requirements

| Connection                | Port  | Direction        | Protocol       | Required    |
|---------------------------|-------|------------------|----------------|-------------|
| Open WebUI → Proxy        | 8080  | B → B            | HTTP           | Yes         |
| Proxy → Qdrant            | 6333, 6334 | B → B         | HTTP / gRPC    | Yes         |
| Proxy → Redis             | 6379  | B → B            | TCP            | Yes         |
| Proxy → Neo4j             | 7687  | B → B            | Bolt           | Yes         |
| Browser → Neo4j Browser   | 7474  | User → B         | HTTP           | Optional    |
| Proxy → GPUStack          | 8080  | B → A            | HTTPS          | Yes         |
| Browser → Open WebUI      | 3000  | User → B         | HTTP           | Yes         |
| ETL → Qdrant              | 6333  | Laptop → B       | HTTPS (VPN)    | Yes         |
| ETL → Neo4j               | 7687  | Laptop → B       | Bolt (VPN)     | Optional    |
| ETL → GPUStack            | 8080  | Laptop → A       | HTTPS          | Yes         |
| Proxy → Prometheus        | 9090  | B → B            | HTTP           | Optional    |
| Proxy → S3/MinIO          | 9000  | B → B            | HTTPS          | Optional    |

---

## Step 1: Verify Machine A (GPUStack)

```bash
# From Machine B (or any host with network access to A):
curl -H "Authorization: Bearer $GPUSTACK_TOKEN" \
  http://<MACHINE_A_IP>:8080/v1/models

# Expected output: list of models including Qwen 3.6, Saiga, bge-m3, bge-reranker-v2-m3
```

**Note:** GPUStack exposes all models through the same OpenAI-compatible API. The model name in the request determines which model is used. For example:
- `qwen3-6b` → Qwen 3.6 LLM
- `saiga` → Saiga SLM
- `bge-m3` → BGE-m3 embedder
- `bge-reranker-v2-m3` → BGE reranker

---

## Step 2: Deploy on Machine B (Proxy + Qdrant + Redis + Open WebUI)

### 2.1. Clone the repository

```bash
ssh user@<MACHINE_B_IP>
cd /opt
sudo git clone <repo> rag-system
cd rag-system
```

### 2.2. Create proxy configuration

Create `proxy/.env.production`:

```bash
# === Server ===
HOST=0.0.0.0
PORT=8080
WORKERS=1

# === Logging ===
LOG_FORMAT=json
LOG_LEVEL=INFO
LOG_REQUESTS=true
LOG_DIR=/app/logs

# === Vector Store (Qdrant on Machine B) ===
QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_GRPC_ENABLED=true
QDRANT_GRPC_PORT=6334
QDRANT_QUANTIZATION_ENABLED=true
QDRANT_HNSW_M=16
QDRANT_HNSW_EF_CONSTRUCT=128
COLLECTION_NAME=knowledge_base

# === Cache (Redis on Machine B) ===
USE_REDIS=true
REDIS_URL=redis://redis:6379
REDIS_KEY_PREFIX=proxy:

# === LLM (Machine A — GPUStack) ===
LLM_ENDPOINT=http://<MACHINE_A_IP>:8080/v1
LLM_PROVIDER_TYPE=openai
LLM_API_KEY=<GPUSTACK_TOKEN>
LLM_MODEL_NAME=qwen3-6b
AVAILABLE_MODELS=qwen3-6b,qwen3-6b-instruct
REQUEST_TIMEOUT=120
MAX_RETRIES=3
RETRY_DELAY=1.0

# === SLM (Machine A — GPUStack) ===
SLM_ENDPOINT=http://<MACHINE_A_IP>:8080/v1
SLM_API_KEY=<GPUSTACK_TOKEN>
SLM_MODEL_NAME=saiga
SLM_LOCAL_ENABLED=false
SLM_MAX_TOKENS=256

# === Embedder (Machine A — GPUStack) ===
EMBEDDER_ENDPOINT=http://<MACHINE_A_IP>:8080/v1
EMBEDDER_API_KEY=<GPUSTACK_TOKEN>
EMBEDDER_MODEL=bge-m3
EMBEDDER_FALLBACK_LOCAL=false
EMBEDDER_DEVICE=cpu

# === Reranker (Machine A — GPUStack) ===
RERANKER_ENDPOINT=http://<MACHINE_A_IP>:8080/v1
RERANKER_API_KEY=<GPUSTACK_TOKEN>
RERANKER_MODEL=bge-reranker-v2-m3
RERANKER_FALLBACK_LOCAL=false
RERANKER_MAX_LENGTH=8192
RERANKER_BATCH_SIZE=32

# === Retrieval ===
MAX_CHUNKS_RETRIEVAL=50
MAX_CHUNKS_AFTER_RERANK=20
PROGRESSIVE_RETRIEVAL_ENABLED=true
PROGRESSIVE_RETRIEVAL_STAGES=5,10,20

# === Graph (Neo4j) ===
GRAPH_ENABLED=true
USE_GRAPH_EXPANSION=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<password>

# === Optional features (disabled by default) ===
USE_LANGGRAPH=false
TOOLS_ENABLED=false
LIVE_SOURCES_ENABLED=false

# === Compression & Optimization ===
COMPRESSION_ENABLED=true
COMPRESSION_LEVEL=6
COMPRESSION_MIN_SIZE=1024
TOKEN_OPTIMIZER_ENABLED=true
EMBEDDING_CACHE_ENABLED=true
RESPONSE_CACHE_ENABLED=true
SEMANTIC_CACHE_ENABLED=true

# === Auth (off for internal corporate) ===
AUTH_ENABLED=false
JWT_SECRET=<openssl-rand-hex-32>
CORS_ORIGINS=http://<MACHINE_B_IP>:3000

# === Observability ===
METRICS_ENABLED=true
OTEL_ENABLED=false
SHUTDOWN_TIMEOUT=30
WARMUP_ENABLED=true
WARMUP_ON_STARTUP=true

# === MinIO (optional) ===
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=<minio-user>
MINIO_SECRET_KEY=<minio-pass>
MINIO_BUCKET=rag-artifacts
MINIO_DOCS_BUCKET=rag-documents
MINIO_SECURE=false

# === Rate limiting ===
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10

# === Quality features ===
HYDE_ENABLED=true
CRAG_DECOMPOSITION_ENABLED=true
SELF_CRITIQUE_ENABLED=true
HALLUCINATION_CHECK_ENABLED=true
NLI_GROUNDING_ENABLED=true
REORDER_ENABLED=true

# === I18N ===
I18N_ENABLED=true
DEFAULT_LANGUAGE=ru
SUPPORTED_LANGUAGES=ru,en,de,fr,zh
```

### 2.3. Create docker-compose.yml

Create `docker-compose.yml` in project root:

```yaml
version: '3.8'
services:
  proxy:
    build:
      context: .
      dockerfile: proxy/Dockerfile
    container_name: rag-proxy
    ports:
      - "8080:8080"
    env_file: proxy/.env.production
    depends_on:
      qdrant:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/v1/health/live"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks: [rag-net]

  qdrant:
    image: qdrant/qdrant:v1.12.1
    container_name: rag-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks: [rag-net]

  redis:
    image: redis:7-alpine
    container_name: rag-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks: [rag-net]

  neo4j:
    image: neo4j:5
    container_name: rag-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/<neo4j-password>
      - NEO4J_PLUGINS=["apoc"]
    volumes:
      - neo4j_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7474/"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks: [rag-net]

  openwebui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: rag-openwebui
    ports:
      - "3000:8080"
    environment:
      - OPENAI_API_BASE_URL=http://proxy:8080/v1
      - OPENAI_API_KEY=dummy-not-used
      - WEBUI_AUTH=false
      - ENABLE_RAG_WEB_SEARCH=false
      - DEFAULT_MODELS=qwen3-6b+RAG
    volumes:
      - openwebui_data:/app/backend/data
    depends_on:
      proxy:
        condition: service_healthy
    restart: unless-stopped
    networks: [rag-net]

  prometheus:
    image: prom/prometheus:latest
    container_name: rag-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./config/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    restart: unless-stopped
    networks: [rag-net]

  grafana:
    image: grafana/grafana:latest
    container_name: rag-grafana
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - ./config/monitoring/grafana-rag-dashboard.json:/var/lib/grafana/dashboards/rag.json
      - grafana_data:/var/lib/grafana
    depends_on:
      - prometheus
    restart: unless-stopped
    networks: [rag-net]

volumes:
  qdrant_data:
  neo4j_data:
  redis_data:
  openwebui_data:
  prometheus_data:
  grafana_data:

networks:
  rag-net:
    driver: bridge
```

### 2.4. Start services

```bash
# On Machine B
cd /opt/rag-system
docker compose up -d

# Watch logs
docker compose logs -f proxy

# Expected: "Application startup complete"
```

### 2.5. Verify deployment

```bash
# Proxy health
curl http://localhost:8080/v1/health/live
# {"status":"alive","timestamp":"..."}

curl http://localhost:8080/v1/health/ready
# {"status":"ready","components":{"qdrant":"ok","llm":"ok"}}

# Model listing (should show Qwen 3.6 + Qwen 3.6+RAG)
curl http://localhost:8080/v1/models | python3 -m json.tool

# Qdrant
curl http://localhost:6333/collections
# {"result":{"collections":[]},"status":"ok","time":0.001}

# Open WebUI
curl -I http://localhost:3000
# HTTP/1.1 200 OK
```

---

## Step 3: Configure Open WebUI

1. Open browser: `http://<MACHINE_B_IP>:3000`
2. Open WebUI starts at the Admin Setup screen (skip if `WEBUI_AUTH=false`)
3. Go to **Settings → Connections → OpenAI API**
4. Add connection:
   - **URL**: `http://proxy:8080/v1`
   - **API Key**: any non-empty value (proxy doesn't check it)
5. Click **Verify Connection** — should succeed
6. Models `qwen3-6b` and `qwen3-6b+RAG` appear in the model dropdown
7. Start chatting with `qwen3-6b+RAG` for RAG-enabled answers

---

## Step 4: ETL from User Laptop

### 4.1. Create ETL configuration

Create `etl/.env.laptop` on your laptop:

```bash
# === USER LAPTOP: ETL Configuration ===

# === Source systems (corporate) ===
# Confluence
CONFLUENCE_URL=https://confluence.corp.example.com
CONFLUENCE_USERNAME=your.username
CONFLUENCE_TOKEN=<personal-access-token>
CONFLUENCE_SPACES=ENG,HR,PRODUCT,DATA
CONFLUENCE_BATCH_SIZE=50

# Jira
JIRA_URL=https://jira.corp.example.com
JIRA_USERNAME=your.username
JIRA_TOKEN=<personal-access-token>
JIRA_PROJECTS=PROJ,INFRA,SUPPORT
JIRA_BATCH_SIZE=50

# GitLab
GITLAB_URL=https://gitlab.corp.example.com
GITLAB_TOKEN=<personal-access-token>
GITLAB_GROUPS=engineering,data,product
GITLAB_BATCH_SIZE=50

# Local documents
DOCS_PATH=./data/documents
BOOKS_PATH=./data/books

# === Target (Qdrant on Machine B, via VPN) ===
QDRANT_HOST=<MACHINE_B_IP>
QDRANT_PORT=6333
QDRANT_HTTPS=true
QDRANT_API_KEY=
COLLECTION_NAME=knowledge_base

# === Embedder (Machine A via VPN) ===
EMBEDDER_ENDPOINT=http://<MACHINE_A_IP>:8080/v1
EMBEDDER_API_KEY=<GPUSTACK_TOKEN>
EMBEDDER_MODEL=bge-m3
EMBEDDER_BATCH_SIZE=32

# === Processing settings ===
CHUNK_SIZE=512
CHUNK_OVERLAP=50
CHUNKER_TYPE=semantic
MAX_WORKERS=5

# === ACL settings (extracted from source systems) ===
ACL_ENABLED=true
DEFAULT_ACCESS_LEVEL=internal

# === Reranker (used during indexing for quality scoring) ===
RERANKER_ENDPOINT=http://<MACHINE_A_IP>:8080/v1
RERANKER_API_KEY=<GPUSTACK_TOKEN>
RERANKER_MODEL=bge-reranker-v2-m3

# === Logging ===
LOG_LEVEL=INFO
LOG_FORMAT=json

# === State ===
WAL_PATH=./etl_state/wal
STATE_PATH=./etl_state
```

### 4.2. Run ETL

```bash
# On laptop
cd /path/to/rag-system
cp etl/.env.laptop.example etl/.env.laptop
# Edit .env.laptop with your corporate credentials

# First run — full indexing (may take hours)
python -m etl.scheduler.run_etl \
  --config etl/config/production.yaml \
  --source all \
  --full

# Subsequent runs — incremental (recommended nightly)
python -m etl.scheduler.run_etl \
  --config etl/config/production.yaml \
  --source all \
  --incremental
```

### 4.3. Schedule incremental ETL

Add to crontab (laptop):

```cron
# ETL incremental every night at 2 AM
0 2 * * * cd /path/to/rag-system && python -m etl.scheduler.run_etl --config etl/config/production.yaml --source all --incremental >> /var/log/rag-etl.log 2>&1
```

---

## Step 5: Verification

### 5.1. End-to-end test

From Machine B:

```bash
# Test full RAG pipeline
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-6b+RAG",
    "messages": [{"role": "user", "content": "Что такое RAG?"}],
    "stream": false
  }' | python3 -m json.tool
```

Expected response:

```json
{
  "id": "rag-...",
  "object": "chat.completion",
  "model": "qwen3-6b+RAG",
  "choices": [{
    "message": {"role": "assistant", "content": "..."},
    "finish_reason": "stop"
  }],
  "rag_feedback_id": "fb-...",
  "rag_confidence": 0.85,
  "rag_sources": [...],
  "rag_knowledge_status": "found"
}
```

### 5.2. Distributed verification script

Create `scripts/verify_distributed.sh`:

```bash
#!/bin/bash
set -e

# === Configuration ===
MACHINE_A_IP="${MACHINE_A_IP:-10.0.1.10}"
MACHINE_B_IP="${MACHINE_B_IP:-localhost}"
GPUSTACK_TOKEN="${GPUSTACK_TOKEN:-dummy}"
PROXY_PORT="${PROXY_PORT:-8080}"
OPENWEBUI_PORT="${OPENWEBUI_PORT:-3000}"

echo "=== Distributed RAG Verification ==="
echo "Machine A (GPUStack): $MACHINE_A_IP"
echo "Machine B (Proxy): $MACHINE_B_IP"
echo ""

# Test 1: GPUStack connectivity
echo "[1/7] GPUStack (Machine A) — LLM/SLM/Embedder/Reranker..."
curl -sf -H "Authorization: Bearer $GPUSTACK_TOKEN" \
  http://$MACHINE_A_IP:8080/v1/models | python3 -m json.tool | head -20

# Test 2: Qdrant
echo ""
echo "[2/7] Qdrant (Machine B)..."
curl -sf http://$MACHINE_B_IP:6333/collections | python3 -m json.tool

# Test 3: Redis
echo ""
echo "[3/7] Redis (Machine B)..."
redis-cli -h $MACHINE_B_IP -p 6379 ping 2>/dev/null || echo "(no redis-cli, skipping)"

# Test 4: Proxy liveness
echo ""
echo "[4/7] Proxy liveness (Machine B)..."
curl -sf http://$MACHINE_B_IP:$PROXY_PORT/v1/health/live | python3 -m json.tool

# Test 5: Proxy readiness (checks all deps)
echo ""
echo "[5/7] Proxy readiness (Machine B)..."
curl -sf http://$MACHINE_B_IP:$PROXY_PORT/v1/health/ready | python3 -m json.tool

# Test 6: Model listing
echo ""
echo "[6/7] Models (Machine B)..."
curl -sf http://$MACHINE_B_IP:$PROXY_PORT/v1/models | python3 -m json.tool

# Test 7: RAG chat
echo ""
echo "[7/7] RAG chat test..."
curl -sf -X POST http://$MACHINE_B_IP:$PROXY_PORT/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-6b+RAG",
    "messages": [{"role": "user", "content": "test"}]
  }' | python3 -m json.tool

echo ""
echo "=== Verification complete ==="
```

Make executable: `chmod +x scripts/verify_distributed.sh`

### 5.3. Run verification

```bash
# On Machine B
MACHINE_A_IP=10.0.1.10 GPUSTACK_TOKEN=sk-xxx bash scripts/verify_distributed.sh
```

---

## Step 6: Monitoring

### 6.1. Grafana dashboards

Open `http://<MACHINE_B_IP>:3001` (admin/admin).

Pre-configured dashboard: `RAG System Overview`
- Request rate (RPS)
- Latency percentiles (p50, p95, p99)
- Error rate
- Cache hit ratio
- Retrieval latency
- LLM latency
- Token usage
- Feedback stats
- Confidence distribution

### 6.2. Prometheus alerts

Pre-configured alerts in `config/monitoring/alerts.yml`:
- `HighLatency` — p95 > 5s
- `HighErrorRate` — 5xx > 5%
- `LLMUnavailable` — LLM down > 2 min
- `QdrantUnavailable` — Qdrant down > 1 min
- `LowCacheHitRatio` — cache hit < 20%

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Proxy 503 — Qdrant down | Qdrant container not started | `docker compose restart qdrant` |
| Proxy 503 — LLM down | GPUStack unreachable | Check network, token |
| Empty responses | Knowledge base empty | Run ETL from laptop |
| Slow responses | GPUStack overloaded | Reduce `MAX_CHUNKS_RETRIEVAL` |
| 401 Unauthorized | `AUTH_ENABLED=true` but no key | Set `AUTH_ENABLED=false` |
| CORS errors | Wrong `CORS_ORIGINS` | Add Open WebUI URL |
| Open WebUI 502 | Proxy not ready | Wait 30s, retry |
| ETL connection refused | VPN not connected | Check VPN status |
| RAG returns no chunks | Chunks not indexed | Run `python -m etl.scheduler.run_etl` |

### Health check endpoints

```bash
# Proxy liveness
curl http://proxy:8080/v1/health/live

# Proxy readiness (all components)
curl http://proxy:8080/v1/health/ready

# Qdrant
curl http://qdrant:6333/

# Redis
redis-cli ping

# GPUStack models
curl -H "Authorization: Bearer $TOKEN" http://gpu:8080/v1/models
```

---

## Backup

### Automated backups

The system includes backup scripts for:
- Qdrant snapshots → `scripts/ops/backup_qdrant.sh`
- ETL WAL state → `scripts/ops/backup_etl_wal.sh`
- Configuration → `scripts/ops/backup_config.sh`

Schedule via cron on Machine B:

```cron
# Daily at 3 AM
0 3 * * * /opt/rag-system/scripts/ops/backup_all.sh >> /var/log/rag-backup.log 2>&1
```

### Disaster recovery

See `docs/en/guides/disaster-recovery-runbook.md` (if exists) or:
1. Restore Qdrant from snapshot
2. Re-run ETL for missing data
3. Verify health endpoints
4. Resume traffic

---

## Security Notes

1. **GPUStack token**: store in `.env.production` (chmod 600), not in version control
2. **JWT_SECRET**: generate with `openssl rand -hex 32` for token signing
3. **CORS**: only allow Open WebUI origin in `CORS_ORIGINS`
4. **TLS**: use HTTPS for GPUStack endpoint if exposed outside private network
5. **Network**: keep Machine B in private network, only expose 3000 (Open WebUI) externally
6. **Secrets rotation**: rotate GPUStack token quarterly via `scripts/security_audit.sh`
7. **Audit log**: all admin actions logged to `audit.jsonl` on proxy host

---

## Quick Reference

| Task | Command |
|------|---------|
| Start services | `docker compose up -d` |
| Stop services | `docker compose down` |
| View logs | `docker compose logs -f proxy` |
| Restart proxy | `docker compose restart proxy` |
| Update code | `git pull && docker compose build proxy && docker compose up -d` |
| Run ETL | `python -m etl.scheduler.run_etl --config etl/config/production.yaml` |
| Verify | `bash scripts/verify_distributed.sh` |
| Backup | `bash scripts/ops/backup_all.sh` |
| Restore | `bash scripts/ops/restore_all.sh --latest` |
