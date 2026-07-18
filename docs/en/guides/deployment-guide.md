# Deployment Guide

**Version:** v2.1.0 | **Last Updated:** 2026-07-17

Comprehensive deployment reference for the RAG Knowledge Assistant. Covers single-server Docker Compose, production
multi-node, Kubernetes with Helm, air-gapped environments, LLM backend configuration, federation, model evolution
infrastructure, security hardening, monitoring, and backup strategies.

---

## 1. Prerequisites

### Hardware

| Resource     | Minimum                | Recommended (production) |
|--------------|------------------------|--------------------------|
| **CPU**      | 8 cores                | 16+ cores                |
| **RAM**      | 16 GB                  | 64+ GB                   |
| **GPU VRAM** | 12 GB (quantized GGUF) | 48+ GB (full precision)  |
| **Disk**     | 20 GB SSD              | 500+ GB NVMe             |
| **Network**  | 1 Gbps                 | 10 Gbps (internal)       |

**Disk breakdown for production:**

| Component                                  | Typical Size |
|--------------------------------------------|--------------|
| Qdrant vectors                             | ~30 GB       |
| Neo4j graph                                | ~10 GB       |
| Model files (embedder, reranker, LLM, SLM) | ~20 GB       |
| Raw data + chunks (cold storage Parquet)   | ~20 GB       |
| Redis persistence (RDB + AOF)              | ~5 GB        |
| Logs                                       | ~10 GB       |
| **Total**                                  | **~100 GB**  |

### Software

| Component                    | Minimum Version | Recommended |
|------------------------------|-----------------|-------------|
| **Docker**                   | 24.0+           | 27.0+       |
| **Docker Compose**           | v2.20+ (plugin) | v2.30+      |
| **NVIDIA Driver**            | 535+            | 550+        |
| **NVIDIA Container Toolkit** | 1.14+           | 1.17+       |
| **Python**                   | 3.11            | 3.12        |
| **kubectl** (K8s)            | 1.28+           | 1.30+       |
| **Helm** (K8s)               | 3.14+           | 3.16+       |

### Verify GPU Availability

```bash
# Confirm driver
nvidia-smi

# Confirm Docker GPU access
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi
```

### Verify Ports

The RAG system uses these default ports — ensure they are free:

| Port       | Service                        |
|------------|--------------------------------|
| 6333, 6334 | Qdrant (HTTP, gRPC)            |
| 6379       | Redis                          |
| 7474, 7687 | Neo4j (HTTP, Bolt)             |
| 8000       | LLM Backend (vLLM / llama.cpp) |
| 8080       | RAG Proxy (FastAPI)            |
| 8081       | Federation Proxy               |
| 8082       | MCP Server                     |
| 8501       | HITL Dashboard (Streamlit)     |
| 9000, 9001 | MinIO (S3 API, Console)        |
| 5000       | MLflow Tracking Server         |

```bash
# Check for port conflicts
ss -tlnp | grep -E '6333|6379|7687|8000|808[0-2]|8501|900[01]|5000'
```

---

## 2. Quick Deploy with setup.sh

The fastest way to get the RAG system running. The interactive setup wizard handles dependency checks, configuration,
Docker Compose startup, and health verification.

### 2.1 Minimal Prerequisites

| Requirement        | Minimum     |
|--------------------|-------------|
| **Docker**         | 20.10+      |
| **Docker Compose** | v2 (plugin) |
| **RAM**            | 4 GB        |
| **Disk**           | 10 GB free  |

!!! note
These are absolute minimums for a CPU-only development setup with a small model. For production workloads with GPU
inference, see the [full prerequisites](#1-prerequisites) (16+ GB RAM, 8+ cores, GPU recommended).

### 2.2 Quick Start

```bash
# Clone the repository
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system

# Run the interactive setup wizard
./setup.sh
```

The wizard guides you through:

1. **Dependency check** — verifies Docker, Docker Compose, Python, and available ports
2. **Configuration** — creates `proxy/.env` from defaults, prompts for LLM endpoint and model name
3. **Docker Compose startup** — builds and starts Qdrant, Redis, Neo4j, and the RAG proxy
4. **Collection initialization** — creates Qdrant collections with the correct vector schema
5. **Health verification** — runs `/v1/health`, `/v1/health/live`, and `/v1/health/ready` checks

### 2.3 setup.sh Commands

```bash
./setup.sh              # Interactive menu (default)
./setup.sh install      # Fresh install (non-interactive)
./setup.sh configure    # Modify existing configuration
./setup.sh expand       # Add components (Neo4j, Redis, SLM, etc.)
./setup.sh status       # Show current status of all services
./setup.sh test         # Run tests and health checks
./setup.sh docker       # Manage containers (start/stop/restart)
./setup.sh build        # Build proxy Docker image
./setup.sh etl          # Run ETL pipeline
```

### 2.4 Verify After Setup

```bash
# Proxy health
curl http://localhost:8080/v1/health

# List models
curl http://localhost:8080/v1/models

# Test a completion
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "What is this system?"}],
    "max_tokens": 50
  }'
```

---

## 3. Quick Docker Compose Deployment (Development / Single-Server)

This deploys all services on one machine for development or small production workloads.

### 3.1 Clone and Configure

```bash
# Clone the repository
git clone https://github.com/AlexanderNarbaev/rag-system.git /opt/rag-system
cd /opt/rag-system

# Create .env from defaults
cp proxy/.env.example proxy/.env  2>/dev/null || cp proxy/.env proxy/.env.bak
```

### 3.2 Edit proxy/.env

Set only the required variables; all others have safe defaults:

```ini
# ── REQUIRED ───────────────────────────────────────────
QDRANT_HOST=qdrant
QDRANT_PORT=6333
COLLECTION_NAME=knowledge_base

# Embedder model — must match what you downloaded
EMBEDDER_MODEL=BAAI/bge-m3
EMBEDDER_DEVICE=cpu

# Reranker model
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_MAX_LENGTH=512
RERANKER_BATCH_SIZE=32

# LLM backend — any OpenAI-compatible endpoint
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=your-model-name   # ← SET THIS
LLM_API_KEY=                     # Only if backend requires it
REQUEST_TIMEOUT=120

# SLM — leave empty to disable (heuristic fallback)
SLM_ENDPOINT=
SLM_MODEL_NAME=

# ── OPTIONAL (enabled by default in docker-compose) ────
USE_REDIS=true
REDIS_URL=redis://redis:6379
USE_LANGGRAPH=true
MAX_RETRIEVAL_LOOPS=3
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change-this-password   # ← CHANGE THIS
USE_GRAPH_EXPANSION=true

# ── PRODUCTION SETTINGS ─────────────────────────────────
RATE_LIMIT_ENABLED=true
METRICS_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
MAX_CONTEXT_TOKENS=8000
RERANK_TOP_K=20
WORKERS=1         # Keep at 1 per replica for production

# ── AUTH (optional) ─────────────────────────────────────
AUTH_ENABLED=true
JWT_SECRET=       # Auto-generated if empty; set for persistence
RBAC_ENABLED=false
```

### 3.3 Set Model Path

In `proxy/docker-compose.yml`, update the LLM model mount:

```yaml
vllm:
  volumes:
    - /opt/models:/models:ro   # ← Your actual model directory
```

And the proxy model cache:

```yaml
rag-proxy:
  volumes:
    - /opt/models/cache:/app/cache:ro
```

### 3.4 Start Services

```bash
cd proxy

# Start all services (detached)
docker compose -f docker-compose.yml up -d

# Watch startup progress
docker compose logs -f --tail=20

# Check all containers are healthy
docker compose ps
# Expected: qdrant, neo4j, redis, vllm, rag-proxy, minio, mlflow, hitl-dashboard — all "Up" and "healthy"
```

### 3.5 Initialize Qdrant Collections

```bash
# Once Qdrant is running (wait ~15s):
python scripts/init_collections.py --qdrant-recreate

# Verify collection exists
curl http://localhost:6333/collections/knowledge_base
# → {"result": {"collections": [{"name": "knowledge_base"}]}}
```

### 3.6 Verify Health

```bash
# Proxy health check
curl http://localhost:8080/v1/health
# → {"status": "healthy", "qdrant": "connected", "llm": "available"}

# Kubernetes-style probes
curl http://localhost:8080/v1/health/live    # Process alive → 200
curl http://localhost:8080/v1/health/ready   # All deps ready → 200

# List models
curl http://localhost:8080/v1/models
# → {"data": [{"id": "your-model-name", ...}]}

# Test a completion
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [{"role": "user", "content": "What is this system?"}],
    "max_tokens": 50
  }'
```

### 3.7 Run First ETL Pipeline

```bash
cd /opt/rag-system

# Edit ETL config with source credentials
cp etl/config/etl_config.yaml etl/config/etl_config.local.yaml
# Edit etl_config.local.yaml — set Confluence, Jira, GitLab URLs and tokens

# Run ETL
cd etl
python scheduler/run_etl.py --config config/etl_config.local.yaml

# Or via Docker:
docker build -f Dockerfile.etl -t rag-etl .
docker run --rm --network proxy_rag-network \
  -v "$(pwd)/etl/wal:/wal" \
  -v "$(pwd)/etl/cold_chunks:/chunks" \
  -e QDRANT_HOST=qdrant \
  -e QDRANT_PORT=6333 \
  rag-etl --config /app/config/etl_config.yaml
```

### 3.8 Stop Services

```bash
cd proxy
docker compose down       # Stops, does not remove volumes
docker compose down -v    # Stops AND removes volumes (⚠ destroys data)
```

---

## 4. Production Docker Deployment

### 4.1 Production Docker Compose (standalone)

Use `docker-compose.standalone.yml` for a self-contained production deployment with resource limits, health checks, and
nginx reverse proxy:

```bash
cd proxy

# GPU-backed deployment
COMPOSE_PROFILES=gpu docker compose -f docker-compose.standalone.yml up -d

# CPU-only deployment (llama.cpp)
COMPOSE_PROFILES=cpu docker compose -f docker-compose.standalone.yml up -d
```

The standalone compose file pins exact image tags (e.g., `qdrant/qdrant:v1.10.0`, `neo4j:5.25-community`,
`redis:7.4-alpine`, `vllm/vllm-openai:v0.6.4`) and includes:

- **Resource limits** on every service (`deploy.resources.limits`)
- **Health checks** with `start_period` for slow-starting services
- **`127.0.0.1` port bindings** — prevents external access to database ports
- **nginx reverse proxy** on ports 80/443 with TLS
- **Bridge network** with fixed subnet (`172.28.0.0/16`)

### 4.2 High-Availability Docker Compose

For multi-node clustering, layer `docker-compose.ha.yml` on top:

```bash
docker compose -f docker-compose.yml -f docker-compose.ha.yml up -d
```

This adds:

| Component     | HA Configuration                                               |
|---------------|----------------------------------------------------------------|
| **Qdrant**    | 2 nodes with Raft consensus (`qdrant-0` as bootstrap)          |
| **Neo4j**     | 1 CORE + 1 READ_REPLICA causal cluster                         |
| **Redis**     | 1 master + 2 replicas + 3 Sentinel monitors                    |
| **RAG Proxy** | 2 replicas (`deploy.replicas: 2`)                              |
| **Network**   | Separate `rag-internal` network for inter-node cluster traffic |

Scale proxy replicas at runtime:

```bash
docker compose scale rag-proxy=4
```

**Redis Sentinel config** (`proxy/redis-sentinel.conf`):

```conf
sentinel monitor rag-redis redis-master 6379 2
sentinel down-after-milliseconds rag-redis 5000
sentinel failover-timeout rag-redis 30000
sentinel parallel-syncs rag-redis 1
```

### 4.3 Custom Dockerfiles

#### Proxy Dockerfile (`proxy/Dockerfile`)

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements_proxy.txt .
RUN pip install --no-cache-dir -r requirements_proxy.txt

COPY proxy/app /app/app

# Model cache directories
ENV HF_HOME=/app/cache/huggingface
ENV TRANSFORMERS_CACHE=/app/cache/huggingface/transformers
ENV SENTENCE_TRANSFORMERS_HOME=/app/cache/huggingface/sentence-transformers

RUN mkdir -p /app/logs /app/cache
RUN useradd --system --uid 1000 --create-home raguser && chown -R raguser:raguser /app
USER raguser

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=5s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8080/v1/health/live || exit 1

CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "app.main:app"]
```

**Build and push:**

```bash
docker build -f proxy/Dockerfile -t rag-proxy:v2.0.0 .
docker tag rag-proxy:v2.0.0 registry.example.com/rag-proxy:v2.0.0
docker push registry.example.com/rag-proxy:v2.0.0
```

#### ETL Dockerfile (`etl/Dockerfile.etl`)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements_etl.txt .
RUN pip install --no-cache-dir -r requirements_etl.txt
COPY etl/ /app/etl/
CMD ["python", "scheduler/run_etl.py", "--config", "config/etl_config.yaml"]
```

### 4.4 Resource Limits Reference

| Service           | CPU Limit | Memory Limit | Justification                                |
|-------------------|-----------|--------------|----------------------------------------------|
| Qdrant            | 4 cores   | 4 GB         | HNSW graph traversal, sparse vector indexing |
| Neo4j             | 2 cores   | 2 GB         | Graph traversal, page cache                  |
| Redis             | 1 core    | 2 GB         | Key-value cache, append-only file            |
| vLLM backend      | 16 cores  | 48 GB        | GPU offload; CPU for tokenizer and dispatch  |
| llama.cpp backend | 16 cores  | 64 GB        | Full CPU inference, no GPU                   |
| RAG Proxy         | 4 cores   | 8 GB         | Embedder + reranker loaded in-process        |
| nginx             | 0.5 cores | 256 MB       | Static reverse proxy                         |

### 4.5 Volume Strategy

```yaml
volumes:
  qdrant_data:
    driver: local
    driver_opts:
      type: none
      device: /data/qdrant
      o: bind

  neo4j_data:
    driver: local
    driver_opts:
      type: none
      device: /data/neo4j
      o: bind

  redis_data:
    driver: local
    driver_opts:
      type: none
      device: /data/redis
      o: bind

  model_cache:
    driver: local
    driver_opts:
      type: none
      device: /opt/models
      o: bind
```

**Ensure correct permissions:**

```bash
mkdir -p /data/{qdrant,neo4j,redis,minio,mlflow}
chown -R 1000:1000 /data/{qdrant,neo4j,redis,minio,mlflow}
chmod 755 /data/{qdrant,neo4j,redis,minio,mlflow}
```

### 4.6 Docker Logging Limits

```yaml
services:
  rag-proxy:
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "3"

  vllm:
    logging:
      driver: "json-file"
      options:
        max-size: "200m"
        max-file: "2"
```

---

## 5. Kubernetes Deployment with Helm

### 5.1 Helm Chart Structure

```
deploy/k8s/helm/rag-system/
├── Chart.yaml                     # Chart metadata (v0.2.0)
├── values.yaml                    # Default configuration values
├── .helmignore                    # Patterns to ignore when packaging
├── templates/
│   ├── _helpers.tpl               # Name, label, serviceaccount helpers
│   ├── proxy-deployment.yaml      # RAG Proxy Deployment (startup/liveness/readiness probes)
│   ├── proxy-service.yaml         # Proxy ClusterIP Service
│   ├── proxy-configmap.yaml       # Non-sensitive configuration (100+ env vars)
│   ├── proxy-secrets.yaml         # Sensitive values (API keys, passwords, tokens)
│   ├── proxy-hpa.yaml             # Horizontal Pod Autoscaler (CPU + memory metrics)
│   ├── proxy-pdb.yaml             # Pod Disruption Budget (minAvailable/maxUnavailable)
│   ├── serviceaccount.yaml        # ServiceAccount with optional IRSA annotations
│   ├── networkpolicy.yaml         # Network isolation (ingress/egress rules)
│   ├── ingress.yaml               # Ingress with TLS termination
│   ├── qdrant-statefulset.yaml    # Qdrant StatefulSet + headless Service
│   ├── neo4j-statefulset.yaml     # Neo4j StatefulSet + headless Service
│   ├── redis-deployment.yaml      # Redis Deployment + Service + PVC
│   └── tests/
│       └── test-connection.yaml   # Helm test: validates proxy, Qdrant, Redis connectivity
```

### 5.2 Quick Deploy

```bash
# 1. Create namespace
kubectl create namespace rag-system

# 2. Install Helm chart (development)
cd deploy/k8s/helm
helm upgrade --install rag-system ./rag-system \
  -n rag-system \
  --set proxy.env.llmEndpoint=http://vllm:8000/v1 \
  --set proxy.env.llmModelName=your-model-name \
  --wait \
  --timeout 10m

# 3. Install with production overrides
helm upgrade --install rag-system ./rag-system \
  -n rag-system \
  -f values.yaml \
  --set proxy.replicaCount=3 \
  --set proxy.autoscaling.enabled=true \
  --set proxy.autoscaling.minReplicas=3 \
  --set proxy.autoscaling.maxReplicas=10 \
  --set qdrant.replicaCount=3 \
  --set qdrant.persistence.size=100Gi \
  --set proxy.env.logFormat=json \
  --set proxy.env.metricsEnabled=true \
  --set proxy.env.rateLimitEnabled=true \
  --set podDisruptionBudget.enabled=true \
  --set podDisruptionBudget.minAvailable=2 \
  --set networkPolicy.enabled=true \
  --set secrets.jwtSecret=$(openssl rand -hex 32) \
  --set secrets.neo4jPassword=$(openssl rand -hex 16) \
  --wait \
  --timeout 10m

# 4. Verify deployment
kubectl get pods,svc,hpa,pdb,netpol -n rag-system

# 5. Run Helm tests
helm test rag-system -n rag-system

# 6. Check health
kubectl exec -it deploy/rag-system-proxy -n rag-system -- curl -s localhost:8080/v1/health
```

### 5.3 Chart Features

| Feature | Template | Description |
|---------|----------|-------------|
| **Startup Probe** | `proxy-deployment.yaml` | 150s grace period for model loading (`failureThreshold: 30`) |
| **Liveness Probe** | `proxy-deployment.yaml` | `/v1/health/live` — restarts if process hangs |
| **Readiness Probe** | `proxy-deployment.yaml` | `/v1/health/ready` — checks Qdrant + LLM connectivity |
| **HPA** | `proxy-hpa.yaml` | CPU + memory autoscaling with scale-down stabilization |
| **PDB** | `proxy-pdb.yaml` | Protects against voluntary disruptions during maintenance |
| **NetworkPolicy** | `networkpolicy.yaml` | Restricts ingress to ingress-nginx; egress to DNS + intra-namespace |
| **ServiceAccount** | `serviceaccount.yaml` | Supports IRSA/workload identity annotations |
| **ConfigMap** | `proxy-configmap.yaml` | 100+ env vars synced from `config.py` |
| **Secrets** | `proxy-secrets.yaml` | API keys, JWT, Neo4j password, Confluence/Jira/GitLab tokens |
| **Anti-affinity** | all workloads | Spreads replicas across nodes (soft/hard) |
| **Security Context** | all workloads | Non-root, drop ALL capabilities, no privilege escalation |

### 5.4 Key Configuration

```yaml
# Essential values to set for production
proxy:
  replicaCount: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
    behavior:
      scaleDown:
        stabilizationWindowSeconds: 300
  env:
    llmEndpoint: "http://vllm:8000/v1"
    llmModelName: "your-model-name"
    logFormat: "json"
    metricsEnabled: "true"
    rateLimitEnabled: "true"
    authEnabled: "true"

qdrant:
  replicaCount: 3        # Must be odd for Raft consensus
  persistence:
    size: 100Gi

neo4j:
  enabled: true
  persistence:
    size: 50Gi

redis:
  enabled: true
  persistence:
    size: 20Gi

podDisruptionBudget:
  enabled: true
  minAvailable: 2

networkPolicy:
  enabled: true

ingress:
  enabled: true
  className: "nginx"
  tls:
    enabled: true
    secretName: rag-system-tls
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/proxy-read-timeout: "180"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"   # Required for SSE streaming

secrets:
  jwtSecret: ""           # Set via --set or sealed-secrets
  neo4jPassword: ""       # Set via --set or sealed-secrets
  llmApiKey: ""           # Set via --set or sealed-secrets
```

### 5.5 values.yaml Walkthrough

The full `values.yaml` reference is at `deploy/k8s/helm/rag-system/values.yaml`. Key sections:

```yaml
# ── Global settings ──────────────────────────────────────
global:
  imageRegistry: ""             # Override for air-gapped (e.g., "registry.airgap.local")
  imagePullSecrets: []
  storageClass: "ssd"           # Use SSD-backed StorageClass

# ── RAG Proxy ───────────────────────────────────────────
proxy:
  enabled: true
  replicaCount: 3
  image:
    repository: rag-system/proxy
    tag: "v2.0.0"
    pullPolicy: IfNotPresent
  service:
    type: ClusterIP
    port: 8080
  resources:
    requests:
      cpu: "2"
      memory: "4Gi"
    limits:
      cpu: "4"
      memory: "8Gi"
  env:
    QDRANT_HOST: "qdrant.rag-system.svc.cluster.local"
    QDRANT_PORT: "6333"
    NEO4J_URI: "bolt://neo4j.rag-system.svc.cluster.local:7687"
    REDIS_URL: "redis://redis.rag-system.svc.cluster.local:6379"
    LLM_ENDPOINT: "http://vllm.rag-system.svc.cluster.local:8000/v1"
    LLM_MODEL_NAME: "your-model-name"
    USE_REDIS: "true"
    USE_LANGGRAPH: "true"
    GRAPH_ENABLED: "true"
    METRICS_ENABLED: "true"
    LOG_FORMAT: "json"
    WORKERS: "1"

  # Probes
  livenessProbe:
    httpGet:
      path: /v1/health/live
      port: 8080
    initialDelaySeconds: 30
    periodSeconds: 10
    timeoutSeconds: 5
    failureThreshold: 3

  readinessProbe:
    httpGet:
      path: /v1/health/ready
      port: 8080
    initialDelaySeconds: 60
    periodSeconds: 15
    timeoutSeconds: 10
    failureThreshold: 3

  startupProbe:
    httpGet:
      path: /v1/health/live
      port: 8080
    initialDelaySeconds: 0
    periodSeconds: 5
    timeoutSeconds: 3
    failureThreshold: 30    # 150 seconds total for model loading

  # Post-start warm-up
  lifecycle:
    postStart:
      exec:
        command:
          - /bin/sh
          - -c
          - |
            until curl -sf http://localhost:8080/v1/health/live; do sleep 1; done
            curl -sf -X POST http://localhost:8080/v1/admin/warmup

  # Pod Disruption Budget
  pdb:
    enabled: true
    minAvailable: 2

# ── Horizontal Pod Autoscaler ──────────────────────────
  hpa:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
    targetMemoryUtilizationPercentage: 80
    scaleDown:
      stabilizationWindowSeconds: 300

# ── Federation Proxy ───────────────────────────────────
federation:
  enabled: false               # Enable for multi-silo deployment
  replicas: 1
  service:
    port: 8081
  resources:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "2"
      memory: "4Gi"
  env:
    FEDERATION_MODE: "hub"    # "hub" or "spoke"
    FEDERATION_HUB_URL: ""    # Set for spoke instances

# ── MCP Server ─────────────────────────────────────────
mcp:
  enabled: true
  replicas: 1
  service:
    port: 8082
  resources:
    requests:
      cpu: "0.5"
      memory: "512Mi"
    limits:
      cpu: "1"
      memory: "1Gi"

# ── Qdrant ─────────────────────────────────────────────
qdrant:
  enabled: true
  replicas: 3                 # Must be odd for Raft
  image:
    repository: qdrant/qdrant
    tag: "v1.10.0"
  persistence:
    size: 100Gi
  resources:
    requests:
      cpu: "2"
      memory: "4Gi"
    limits:
      cpu: "4"
      memory: "8Gi"
  env:
    QDRANT__CLUSTER__ENABLED: "true"
    QDRANT__LOG_LEVEL: "INFO"

# ── Neo4j ──────────────────────────────────────────────
neo4j:
  enabled: true
  replicas: 3                 # Core cluster nodes
  image:
    repository: neo4j
    tag: "5.25-enterprise"
  persistence:
    size: 50Gi
  resources:
    requests:
      cpu: "2"
      memory: "2Gi"
    limits:
      cpu: "4"
      memory: "4Gi"
  env:
    NEO4J_ACCEPT_LICENSE_AGREEMENT: "yes"
    NEO4J_dbms_memory_pagecache_size: "1G"
    NEO4J_dbms_memory_heap_max__size: "2G"
    NEO4J_PLUGINS: '["apoc"]'

# ── Redis Sentinel ─────────────────────────────────────
redis:
  enabled: true
  replicas: 3                 # 1 master + 2 replicas
  image:
    repository: redis
    tag: "7.4-alpine"
  persistence:
    size: 20Gi
  resources:
    requests:
      cpu: "0.5"
      memory: "1Gi"
    limits:
      cpu: "1"
      memory: "2Gi"
  config:
    maxmemory: "2gb"
    maxmemoryPolicy: "allkeys-lru"
    save: "900 1 300 10"

# ── Ingress ────────────────────────────────────────────
ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "180"
    nginx.ingress.kubernetes.io/proxy-buffering: "off"    # SSE streaming
  hosts:
    - host: rag.example.com
      paths:
        - path: /v1/
          pathType: Prefix
          serviceName: proxy
          servicePort: 8080
        - path: /metrics
          pathType: Exact
          serviceName: proxy
          servicePort: 8080
  tls:
    - hosts:
        - rag.example.com
      secretName: rag-tls

# ── Network Policies ───────────────────────────────────
networkPolicy:
  enabled: true
  # Deny all ingress by default; allow only:
  ingressAllow:
    - from: ingress-nginx      # From ingress controller
    - from: monitoring          # From Prometheus/Grafana namespace

# ── Backup CronJob ─────────────────────────────────────
backup:
  enabled: true
  schedule: "0 */6 * * *"     # Every 6 hours
  s3:
    endpoint: "s3.amazonaws.com"
    bucket: "rag-backups"
    region: "us-east-1"

# ── Training CronJob ───────────────────────────────────
training:
  enabled: false                # Enable for model evolution
  schedule: "0 2 * * 0"       # Weekly, Sunday 2am
  profile: "prod"              # dev / prod / ci
```

### 5.6 K8s Secrets Management

Never store secrets in `values.yaml`. Use one of these approaches:

#### Option A: Kubernetes Secrets (simple)

```bash
kubectl create secret generic rag-secrets -n rag-system \
  --from-literal=jwt-secret=$(openssl rand -hex 32) \
  --from-literal=neo4j-password=$(openssl rand -hex 16) \
  --from-literal=minio-secret-key=$(openssl rand -hex 16)
```

In `templates/secrets.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rag-secrets
  namespace: {{ .Release.Namespace }}
type: Opaque
data: {}   # Populated externally; not from Helm values
```

Reference in Deployment:

```yaml
env:
  - name: NEO4J_PASSWORD
    valueFrom:
      secretKeyRef:
        name: rag-secrets
        key: neo4j-password
  - name: JWT_SECRET
    valueFrom:
      secretKeyRef:
        name: rag-secrets
        key: jwt-secret
```

#### Option B: External Secrets Operator (ESO)

```yaml
# templates/external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rag-secrets
  namespace: {{ .Release.Namespace }}
spec:
  refreshInterval: "1h"
  secretStoreRef:
    name: aws-secretsmanager
    kind: ClusterSecretStore
  target:
    name: rag-secrets
    creationPolicy: Owner
  data:
    - secretKey: jwt-secret
      remoteRef:
        key: "rag/production/jwt-secret"
    - secretKey: neo4j-password
      remoteRef:
        key: "rag/production/neo4j-password"
    - secretKey: llm-api-key
      remoteRef:
        key: "rag/production/llm-api-key"
```

#### Option C: Sealed Secrets

```bash
kubectl create secret generic rag-secrets -n rag-system \
  --from-literal=jwt-secret=... \
  --dry-run=client -o yaml | \
  kubeseal --controller-namespace sealed-secrets -o yaml > templates/sealed-secrets.yaml
```

### 5.7 Network Policies

```yaml
# templates/network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: rag-system-restrict
  namespace: {{ .Release.Namespace }}
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow from the ingress controller namespace
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - port: 8080
          protocol: TCP
    # Allow from monitoring namespace (Prometheus scraping)
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - port: 8080
          protocol: TCP
        - port: 3000
          protocol: TCP
  egress:
    # Allow DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
    # Allow intra-namespace traffic
    - to:
        - podSelector: {}
      ports:
        - protocol: TCP
```

### 5.8 Zero-Downtime Deployments

```bash
# Standard rolling update (default strategy)
kubectl set image deployment/rag-proxy rag-proxy=rag-proxy:v2.0.1 -n rag-system

# Monitor rollout
kubectl rollout status deployment/rag-proxy -n rag-system

# Manual canary with two Deployments:
helm upgrade --install rag-system ./rag-system -n rag-system --reuse-values \
  --set proxy.image.tag=v2.0.1-canary \
  --set proxy.replicas=1

# If canary is healthy, promote:
helm upgrade --install rag-system ./rag-system -n rag-system \
  --set proxy.image.tag=v2.0.1 \
  --set proxy.replicas=3

# Rollback if needed
kubectl rollout undo deployment/rag-proxy -n rag-system
```

### 5.9 WORKERS=1 Limitation and Zero-Downtime Deployments

The RAG proxy requires `WORKERS=1` per replica (see CON-03 in the compliance requirements). This is because
the embedder, reranker, and in-process caches are singletons that cannot be shared across multiple worker
processes without race conditions.

**Impact on zero-downtime deployments:**

- With `WORKERS=1`, a standard rolling update causes a brief window where the old pod is terminated before
  the new pod is ready to serve traffic. In-flight requests may be dropped during this gap.
- The proxy does **not** support graceful connection draining across multiple workers within a single pod,
  since there is only one worker.

**Recommended workarounds:**

| Strategy | Description |
|----------|-------------|
| **Weighted traffic (K8s)** | Use multiple proxy replicas (≥2) with a PDB (`minAvailable: 1`). Configure `terminationGracePeriodSeconds: 60` and a `preStop` hook that calls `/v1/admin/drain` or simply sleeps to allow in-flight requests to complete. |
| **Graceful drain (Docker Compose)** | Scale to 2+ replicas. Before shutting down a replica, remove it from the load balancer and wait for `SHUTDOWN_TIMEOUT` (default 30s) before sending SIGTERM. |
| **Canary promotion (recommended)** | Deploy the new version as a canary replica, verify health, adjust traffic split via the canary controller, then decommission the old replica. See `model_evolution/canary_controller.py` for the built-in canary mechanism. |

For multi-worker serving without this limitation, deploy the embedder and reranker as standalone remote
services (see section 8.4 for GPUStack backend) and set `EMBEDDER_ENDPOINT` and `RERANKER_ENDPOINT`
to external endpoints. This decouples model serving from the proxy and allows `WORKERS > 1`.

### 5.10 Probes Reference

| Probe         | Endpoint           | Purpose                    | Initial Delay | Period |
|---------------|--------------------|----------------------------|---------------|--------|
| **startup**   | `/v1/health/live`  | Model loading grace period | 0s            | 5s     |
| **liveness**  | `/v1/health/live`  | Process is alive           | 30s           | 10s    |
| **readiness** | `/v1/health/ready` | All dependencies available | 60s           | 15s    |

Qdrant startup probe uses the native `:6333/health` endpoint. vLLM startup probe uses `:8000/health` with
`start_period: 180s`.

---

## 6. OpenWebUI Standalone Deployment

OpenWebUI provides a ChatGPT-style web interface that connects to the RAG Proxy as an OpenAI-compatible backend.
This deployment is **fully standalone** — it uses its own PostgreSQL database, Redis for sessions, and Apache Tika
for document extraction, sharing only the Docker network with the RAG infrastructure.

### 6.1 Architecture

```
┌──────────────────────────────────────────────────────────┐
│  rag-network (EXTERNAL — shared with RAG Proxy)          │
│                                                          │
│  ┌───────────────┐  ┌───────────┐                       │
│  │  RAG Proxy    │  │  MinIO    │                       │
│  │  :8080        │  │  :9000    │                       │
│  │ (OpenAI API)  │  │ (S3 API)  │                       │
│  └───────┬───────┘  └─────┬─────┘                       │
└──────────┼─────────────────┼────────────────────────────┘
           │                 │
┌──────────┼─────────────────┼────────────────────────────┐
│  openwebui-network (INTERNAL — isolated)                 │
│          │                 │                             │
│  ┌───────┴─────────────────┴───────┐                     │
│  │         OpenWebUI :3000        │                     │
│  │  (Users access via browser)    │                     │
│  └───────┬─────────────┬──────────┘                     │
│          │             │                                 │
│  ┌───────┴───┐ ┌───────┴────┐ ┌──────────┐             │
│  │PostgreSQL │ │   Redis    │ │   Tika   │             │
│  │  :5432    │ │   :6379    │ │  :9998   │             │
│  │(users,    │ │ (sessions, │ │(document │             │
│  │ chats,    │ │  WS cache) │ │ extract) │             │
│  │ configs)  │ │            │ │          │             │
│  └───────────┘ └────────────┘ └──────────┘             │
└─────────────────────────────────────────────────────────┘
```

**Key design decisions:**

| Decision | Rationale |
|----------|-----------|
| Separate PostgreSQL (not SQLite) | Production durability, independent backups |
| Dedicated Redis instance | Session isolation from proxy's cache Redis |
| External `rag-network` | Clear ownership boundary; proxy updates don't affect OpenWebUI data |
| Apache Tika as sidecar | Full offline document extraction (PDF, DOCX, XLSX, images) |
| Built-in RAG disabled | Proxy handles all retrieval, reranking, and graph expansion |
| No Ollama | All models served through the RAG Proxy only |

### 6.2 Quick Start

```bash
# 1. Run the initialization script (generates secrets, creates MinIO bucket, starts services)
cd /opt/rag-system
./scripts/init-openwebui.sh

# Or with automatic mode (no interactive prompts):
./scripts/init-openwebui.sh --auto
```

The script will:
1. Check Docker and Docker Compose are available
2. Verify the `rag-network` exists (RAG Proxy must be running)
3. Generate `WEBUI_SECRET_KEY` and `POSTGRES_PASSWORD` (stored in `.env.openwebui`)
4. Create the `openwebui-files` bucket in MinIO
5. Pull images and start all services
6. Run health checks on all components
7. Print admin account setup instructions

### 6.3 Manual Start

```bash
cd deploy/docker

# Generate secrets first
openssl rand -hex 32  # → WEBUI_SECRET_KEY
openssl rand -hex 24  # → POSTGRES_PASSWORD

# Edit .env.openwebui with the generated secrets
vim .env.openwebui

# Start services
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui up -d

# Watch logs
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui logs -f

# Check status
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui ps
```

### 6.4 First-Time Admin Setup

Since `ENABLE_SIGNUP=false` (corporate policy), only the first visitor can create an admin account:

1. Open `http://<host>:3000` in your browser
2. Click **Sign up** and create the admin account
3. After admin creation, the signup page is disabled for all other users
4. Go to **Admin Panel → Users** to create accounts for your team

For Keycloak SSO integration:

1. Go to **Admin Panel → Settings → General → OAuth**
2. Enable OAuth and configure the Keycloak provider:
   - **Provider:** `openid`
   - **Client ID:** your-keycloak-client-id
   - **Client Secret:** your-keycloak-client-secret
   - **OpenID Configuration URL:** `https://keycloak.example.com/realms/your-realm/.well-known/openid-configuration`
   - **Scopes:** `openid profile email`
3. Set `ENABLE_SIGNUP=false` to prevent local account creation

### 6.5 Service Overview

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| **OpenWebUI** | `rag-openwebui` | 3000 → 8080 | Web interface |
| **PostgreSQL** | `rag-openwebui-postgres` | 5432 (internal) | Users, chats, configs |
| **Redis** | `rag-openwebui-redis` | 6379 (internal) | WebSocket sessions, cache |
| **Tika** | `rag-openwebui-tika` | 9998 (internal) | Document text extraction |

### 6.6 Connecting Multiple LLM Backends

OpenWebUI supports multiple OpenAI-compatible connections simultaneously. Beyond the RAG Proxy,
you can add GPUStack or vLLM endpoints:

```bash
# In .env.openwebui — multiple URLs separated by semicolons:
OPENAI_API_BASE_URLS=http://rag-proxy:8080/v1;https://gpustack.internal/v1;https://vllm-openshift.internal/v1
OPENAI_API_KEYS=sk-rag-proxy;gpustack_YOUR_KEY;vllm-openshift-key
```

Or configure via the Admin Panel UI after startup:
1. **Admin Panel → Settings → Connections → OpenAI API**
2. Add each endpoint URL with its API key
3. Models from all connections appear in the model selector

### 6.7 Operations

```bash
# Status
cd deploy/docker
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui ps

# Logs
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui logs -f openwebui
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui logs -f postgres

# Restart a specific service
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui restart openwebui

# Stop everything (data preserved in volumes)
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui down

# Stop and delete all data (⚠ destructive)
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui down -v

# Backup PostgreSQL
docker exec rag-openwebui-postgres pg_dump -U openwebui openwebui > openwebui_backup_$(date +%Y%m%d).sql

# Restore PostgreSQL
docker exec -i rag-openwebui-postgres psql -U openwebui openwebui < openwebui_backup_20260717.sql
```

### 6.8 Resource Requirements

| Service | CPU (min/limit) | RAM (min/limit) | Disk |
|---------|-----------------|-----------------|------|
| OpenWebUI | 0.5 / 2 cores | 512 MB / 2 GB | 10 GB |
| PostgreSQL | 0.25 / 2 cores | 256 MB / 1 GB | 20 GB |
| Redis | 0.1 / 1 core | 64 MB / 512 MB | 5 GB |
| Tika | 0.25 / 2 cores | 256 MB / 1 GB | — (tmpfs) |
| **Total** | **1.1 / 7 cores** | **1.1 / 4.5 GB** | **35 GB** |

### 6.9 Troubleshooting

**OpenWebUI can't connect to RAG Proxy:**
```bash
# Check rag-network connectivity
docker exec rag-openwebui curl -sf http://rag-proxy:8080/v1/health
# Should return: {"status":"healthy",...}

# Check if rag-network is attached
docker network inspect rag-network | grep openwebui
```

**"Service Unavailable" on file upload:**
```bash
# Verify MinIO bucket exists
docker exec rag-minio mc ls local/openwebui-files

# Create bucket if missing
docker exec rag-minio mc mb local/openwebui-files
```

**Tika fails on large documents:**
```bash
# Increase Tika heap size in .env.openwebui:
TIKA_HEAP_SIZE=1024m
# Then restart Tika:
docker compose -f docker-compose.openwebui.yml --env-file .env.openwebui restart tika
```

---

## 7. Air-Gapped Deployment

For environments without internet access, pre-download all assets on a connected machine, then transfer.

### 7.1 Download Models Offline

```bash
# On the internet-connected machine:
cd /opt/rag-system
python scripts/download_models_offline.py \
  --output-dir ./offline_models \
  --models embedder reranker spacy_ru spacy_en slm \
  --gguf-url https://huggingface.co/your-org/your-model-GGUF/resolve/main/your-model-Q4_K_M.gguf

# This downloads:
# - BAAI/bge-m3 (embedder + sparse vectors)
# - cross-encoder/ms-marco-MiniLM-L-6-v2 (reranker)
# - ru_core_news_sm, en_core_web_sm (spaCy models)
# - SLM model (e.g., Qwen2.5-3B)
# - LLM GGUF file (if --gguf-url provided)
```

### 7.2 Transfer Assets

```bash
# Package models
tar -czf offline_models.tar.gz offline_models/

# Transfer to air-gapped host
scp offline_models.tar.gz admin@airgap-host:/opt/rag-system/

# On air-gapped host:
cd /opt/rag-system
tar -xzf offline_models.tar.gz
```

### 7.3 Transfer Docker Images

```bash
# On internet-connected machine — pull all images:
docker pull qdrant/qdrant:v1.10.0
docker pull neo4j:5.25-community
docker pull redis:7.4-alpine
docker pull vllm/vllm-openai:v0.6.4
docker pull ghcr.io/ggerganov/llama.cpp:server
docker pull minio/minio:latest
docker pull ghcr.io/mlflow/mlflow:latest
docker pull nginx:1.27-alpine
docker pull python:3.11-slim

# Save to tar
docker save \
  qdrant/qdrant:v1.10.0 \
  neo4j:5.25-community \
  redis:7.4-alpine \
  vllm/vllm-openai:v0.6.4 \
  ghcr.io/ggerganov/llama.cpp:server \
  minio/minio:latest \
  ghcr.io/mlflow/mlflow:latest \
  nginx:1.27-alpine \
  python:3.11-slim \
  -o rag-images.tar

# Transfer
scp rag-images.tar admin@airgap-host:/opt/rag-system/

# On air-gapped host:
docker load -i rag-images.tar
```

### 7.4 Transfer pip Packages

```bash
# On internet-connected machine:
mkdir pip-offline
pip download -r proxy/requirements_proxy.txt -d pip-offline/
pip download -r etl/requirements_etl.txt -d pip-offline/

tar -czf pip-offline.tar.gz pip-offline/
scp pip-offline.tar.gz admin@airgap-host:/opt/rag-system/

# On air-gapped host — install from local directory:
pip install --no-index --find-links /opt/rag-system/pip-offline \
  -r /opt/rag-system/proxy/requirements_proxy.txt
```

### 7.5 Configure Model Paths for Air-Gapped

```bash
# proxy/.env
MODEL_CACHE_DIR=/opt/rag-system/offline_models
EMBEDDER_MODEL=/opt/rag-system/offline_models/bge-m3
RERANKER_MODEL=/opt/rag-system/offline_models/ms-marco-MiniLM-L-6-v2
```

For local SLM (no external API):

```bash
SLM_LOCAL_ENABLED=true
SLM_LOCAL_BINARY=/usr/local/bin/llama-server
SLM_LOCAL_MODEL_PATH=/opt/rag-system/offline_models/slm-model.gguf
SLM_LOCAL_CONTEXT_SIZE=4096
SLM_LOCAL_THREADS=4
SLM_LOCAL_PORT=8081
```

Docker Compose volume mounts:

```yaml
vllm:
  volumes:
    - /opt/rag-system/offline_models:/models:ro

rag-proxy:
  volumes:
    - /opt/rag-system/offline_models:/app/cache:ro
```

### 7.6 Offline Air-Gapped Values (Helm)

```yaml
# values-airgap.yaml
global:
  imageRegistry: "registry.airgap.local"   # Local Docker registry

proxy:
  image:
    repository: rag-system/proxy
    tag: "v2.0.0"
    pullPolicy: IfNotPresent

  env:
    EMBEDDER_MODEL: "/models/bge-m3"
    RERANKER_MODEL: "/models/ms-marco-MiniLM-L-6-v2"
    SLM_LOCAL_ENABLED: "true"
    SLM_LOCAL_MODEL_PATH: "/models/slm-model.gguf"
```

---

## 8. LLM Backend Setup

The RAG proxy communicates with ANY OpenAI-compatible `/v1/chat/completions` endpoint. Configure via:

```bash
LLM_ENDPOINT=http://<host>:<port>/v1
LLM_MODEL_NAME=<model-id>
LLM_API_KEY=<optional-api-key>
LLM_PROVIDER_TYPE=openai    # "openai", "anthropic", or "generic"
```

### 8.1 vLLM Backend

**Docker Compose:**

```yaml
vllm:
  image: vllm/vllm-openai:v0.6.4
  container_name: rag-vllm
  volumes:
    - /opt/models:/models:ro
  ports:
    - "8000:8000"
  environment:
    - HUGGINGFACE_HUB_CACHE=/models/cache
  command: >
    --model /models/Llama-3.1-70B-Instruct
    --port 8000
    --host 0.0.0.0
    --max-model-len 65536
    --gpu-memory-utilization 0.90
    --tensor-parallel-size 2
    --dtype auto
    --enforce-eager
    --enable-prefix-caching
    --max-num-seqs 16
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 2
            capabilities: [gpu]
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 60s
    timeout: 30s
    retries: 5
    start_period: 180s
  restart: unless-stopped
```

**Key vLLM flags:**

| Flag                       | Purpose             | Suggested Value               |
|----------------------------|---------------------|-------------------------------|
| `--max-model-len`          | Max context length  | 65536 (trade VRAM vs context) |
| `--gpu-memory-utilization` | VRAM fraction       | 0.90                          |
| `--tensor-parallel-size`   | GPUs for sharding   | 1 per 24 GB VRAM              |
| `--enable-prefix-caching`  | KV cache reuse      | Enabled                       |
| `--max-num-seqs`           | Concurrent requests | 16                            |
| `--api-key`                | Require API key     | Same as `LLM_API_KEY`         |

### 8.2 llama.cpp Backend (CPU Inference)

**Docker Compose:**

```yaml
vllm-cpu:
  image: ghcr.io/ggerganov/llama.cpp:server
  container_name: rag-vllm-cpu
  volumes:
    - /opt/models:/models:ro
  ports:
    - "8000:8000"
  command: >
    --model /models/llama-3.1-8b-instruct-Q4_K_M.gguf
    --host 0.0.0.0
    --port 8000
    --ctx-size 65536
    --n-gpu-layers 0
    --threads 16
    --batch-size 512
    --api-key ""
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 60s
    timeout: 30s
    retries: 5
    start_period: 240s
  restart: unless-stopped
```

**Key llama.cpp flags:**

| Flag             | Purpose                 | Suggested Value        |
|------------------|-------------------------|------------------------|
| `--ctx-size`     | Max context length      | 65536                  |
| `--threads`      | CPU threads             | Number of CPU cores    |
| `--n-gpu-layers` | Layers offloaded to GPU | 0 (CPU-only), -1 (all) |
| `--batch-size`   | Prompt processing batch | 512                    |
| `--api-key`      | API key requirement     | `""` for no key        |

### 8.3 OpenAI-Compatible Endpoint (any provider)

For any third-party endpoint implementing the OpenAI API spec:

```bash
# proxy/.env
LLM_ENDPOINT=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o
LLM_API_KEY=sk-...
LLM_PROVIDER_TYPE=openai

# Or Ollama
LLM_ENDPOINT=http://localhost:11434/v1
LLM_MODEL_NAME=llama3.1:70b
LLM_PROVIDER_TYPE=generic
```

### 8.4 GPUStack Backend

[GPUStack](https://github.com/gpustack/gpustack) is an open-source GPU cluster manager that serves OpenAI-compatible
endpoints for LLM, embedding, and reranker models. It's ideal for on-premise deployments where you need centralized
model serving across multiple GPU nodes.

**Configure the RAG proxy to use GPUStack:**

```bash
# proxy/.env

# LLM via GPUStack
LLM_ENDPOINT=http://<gpu-host>:80/v1
LLM_MODEL_NAME=Qwen3-635B-AWQ-T
LLM_API_KEY=gpustack_<your-api-key>
LLM_PROVIDER_TYPE=openai

# Embeddings via GPUStack
EMBEDDER_ENDPOINT=http://<gpu-host>:80/v1
EMBEDDER_API_KEY=gpustack_<your-api-key>
EMBEDDER_FALLBACK_LOCAL=true        # Fall back to local model if GPUStack unavailable

# Reranker via GPUStack
RERANKER_ENDPOINT=http://<gpu-host>:80/v1
RERANKER_API_KEY=gpustack_<your-api-key>
RERANKER_FALLBACK_LOCAL=true
```

**List available models:**

```bash
curl http://<gpu-host>:80/v1/models \
  -H "Authorization: Bearer gpustack_<your-api-key>"
```

**Key benefits:**

| Feature                  | Description                                   |
|--------------------------|-----------------------------------------------|
| Multi-node GPU cluster   | Distribute models across multiple GPU servers |
| Automatic load balancing | Round-robin across model replicas             |
| OpenAI-compatible API    | Drop-in replacement for vLLM/llama.cpp        |
| Model auto-download      | Pulls from HuggingFace on first deployment    |
| API key management       | Per-model and per-user access control         |

See the [GPUStack documentation](https://docs.gpustack.ai/) for cluster setup and model management.

### 8.5 Proxy Configuration for Backend

```bash
# proxy/.env
LLM_ENDPOINT=http://vllm:8000/v1       # Docker Compose service name
LLM_MODEL_NAME=Llama-3.1-70B-Instruct
LLM_API_KEY=                            # Only if backend enforces it
REQUEST_TIMEOUT=120
MAX_RETRIES=3
RETRY_DELAY=1.0
PREFIX_CACHING_ENABLED=true             # vLLM KV-cache reuse
```

---

## 9. Federation Setup

Federation allows querying multiple RAG silos (e.g., different departments or geographic regions) through a single
endpoint.

### 9.1 Architecture

```
Client
  │
  ▼
┌──────────────────┐
│  Federation Hub  │────► Silo A (Qdrant-A, Neo4j-A)
│    Port 8081     │────► Silo B (Qdrant-B, Neo4j-B)
│                  │────► Silo C (Qdrant-C, Neo4j-C)
└──────────────────┘
```

- **Hub** — receives user queries, fans out to spokes, aggregates results, reranks globally
- **Spoke** — independent RAG instance with its own Qdrant + Neo4j + LLM

### 9.2 Hub Configuration

```bash
# proxy/.env — Federation Hub
FEDERATION_MODE=hub
FEDERATION_INSTANCES_JSON='[
  {
    "name": "engineering",
    "url": "http://rag-eng.internal:8080/v1",
    "api_key": "eng-api-key",
    "weight": 1.0,
    "timeout": 30
  },
  {
    "name": "product",
    "url": "http://rag-product.internal:8080/v1",
    "api_key": "product-api-key",
    "weight": 0.8,
    "timeout": 30
  },
  {
    "name": "support",
    "url": "http://rag-support.internal:8080/v1",
    "api_key": "support-api-key",
    "weight": 0.5,
    "timeout": 15
  }
]'

# Federation-specific settings
FEDERATION_STRATEGY=weighted            # "weighted", "round_robin", "latency_aware"
FEDERATION_MERGE_LIMIT=30               # Max results across all silos before rerank
FEDERATION_TIMEOUT=45                   # Per-silo timeout, seconds
```

### 9.3 Spoke Configuration

```bash
# proxy/.env — Federation Spoke (each instance)
FEDERATION_MODE=spoke
# No FEDERATION_INSTANCES_JSON needed for spokes
```

### 9.4 Multi-Silo Topology Examples

**By Department:**

```
FEDERATION_INSTANCES_JSON='[
  {"name":"engineering","url":"http://rag-eng:8080/v1","weight":1.0},
  {"name":"legal","url":"http://rag-legal:8080/v1","weight":0.5},
  {"name":"hr","url":"http://rag-hr:8080/v1","weight":0.3}
]'
```

**By Region (geo-distributed):**

```
FEDERATION_INSTANCES_JSON='[
  {"name":"us-east","url":"http://rag-use1:8080/v1","weight":1.0,"timeout":15},
  {"name":"us-west","url":"http://rag-usw2:8080/v1","weight":1.0,"timeout":15},
  {"name":"eu-west","url":"http://rag-euw1:8080/v1","weight":0.7,"timeout":20}
]'
```

### 9.5 Federation in Docker Compose

```yaml
# docker-compose.yml — add federation service
federation-proxy:
  build:
    context: ..
    dockerfile: proxy/Dockerfile
  container_name: rag-federation
  ports:
    - "8081:8081"
  environment:
    - PORT=8081
    - FEDERATION_MODE=hub
    - FEDERATION_INSTANCES_JSON=${FEDERATION_INSTANCES_JSON}
  depends_on:
    - rag-proxy
  networks:
    - rag-network
```

### 9.6 Federation in Kubernetes

```yaml
# Deployment for each spoke (separate namespace)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-proxy
  namespace: rag-engineering
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: proxy
        image: rag-system/proxy:v2.0.0
        env:
        - name: FEDERATION_MODE
          value: "spoke"
```

---

## 10. Model Evolution Setup

The Model Evolution pipeline supports fine-tuning SLM, LLM, and Reranker models, with MLflow tracking, MinIO artifact
storage, automated quality gates, and canary rollouts.

### 10.1 Enable in Configuration

```bash
# proxy/.env
MODEL_EVOLUTION_ENABLED=true

# MLflow Tracking Server
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_EXPERIMENT_NAME=rag-system
MLFLOW_ARTIFACT_ROOT=s3://rag-artifacts

# MinIO S3-compatible artifact storage
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=change-this-key
MINIO_BUCKET=rag-artifacts
MINIO_SECURE=false

# Training profile
TRAINING_PROFILE=prod              # dev / staging / prod (affects batch size, epochs)

# Hot-Reload (hot-swap models without restart)
HOT_RELOAD_ENABLED=true
HOT_RELOAD_WATCH_INTERVAL=5        # Check for new adapters every 5 seconds
HOT_RELOAD_SIGNAL_ENABLED=true     # Accept SIGHUP for manual reload

# Canary Deployments
CANARY_ENABLED=true
CANARY_PHASE_DURATION_5=300        # 5% traffic for 5 minutes
CANARY_PHASE_DURATION_25=600       # 25% traffic for 10 minutes
CANARY_PHASE_DURATION_50=900       # 50% traffic for 15 minutes
CANARY_PHASE_DURATION_75=1200      # 75% traffic for 20 minutes
CANARY_COOLDOWN_SECONDS=3600       # 1 hour between rollouts

# Eval Gate Quality Thresholds
EVAL_GATE_LLM_BERTSCORE_MIN=0.70
EVAL_GATE_LLM_HALLUCINATION_MAX=0.05
EVAL_GATE_LLM_ROUGE_L_MIN=0.35
EVAL_GATE_SLM_F1_MIN=0.85
EVAL_GATE_SLM_ACCURACY_MIN=0.90
EVAL_GATE_RERANKER_MRR_MIN=0.75
EVAL_GATE_RERANKER_NDCG_MIN=0.70
```

### 10.2 Docker Compose Services

MinIO and MLflow are included in `docker-compose.yml`:

```yaml
# MinIO — S3-compatible artifact storage
minio:
  image: minio/minio:latest
  volumes:
    - minio_data:/data
  ports:
    - "9000:9000"
    - "9001:9001"
  environment:
    - MINIO_ROOT_USER=${MINIO_ACCESS_KEY:-minioadmin}
    - MINIO_ROOT_PASSWORD=${MINIO_SECRET_KEY:-minioadmin}
  command: server /data --console-address ":9001"

# Auto-create bucket
minio-create-bucket:
  image: minio/mc:latest
  depends_on:
    minio:
      condition: service_healthy
  entrypoint: >
    /bin/sh -c "
    mc alias set local http://minio:9000 $${MINIO_ACCESS_KEY} $${MINIO_SECRET_KEY} &&
    mc mb --ignore-existing local/$${MINIO_BUCKET:-rag-artifacts}
    "

# MLflow Tracking Server
mlflow:
  image: ghcr.io/mlflow/mlflow:latest
  ports:
    - "5000:5000"
  environment:
    - MLFLOW_S3_ENDPOINT_URL=http://minio:9000
    - AWS_ACCESS_KEY_ID=${MINIO_ACCESS_KEY:-minioadmin}
    - AWS_SECRET_ACCESS_KEY=${MINIO_SECRET_KEY:-minioadmin}
    - MLFLOW_S3_IGNORE_TLS=true
  command: >
    mlflow server
    --host 0.0.0.0
    --port 5000
    --backend-store-uri sqlite:///mlflow/mlflow.db
    --default-artifact-root s3://${MINIO_BUCKET:-rag-artifacts}
  volumes:
    - mlflow_data:/mlflow
```

### 10.3 Trigger Training

```bash
# Train SLM on feedback data
curl -X POST http://localhost:8080/v1/admin/models/train \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model_type": "slm",
    "dataset": "feedback",
    "training_profile": "prod",
    "hyperparameters": {
      "epochs": 3,
      "learning_rate": 2e-4,
      "lora_r": 16,
      "lora_alpha": 32
    }
  }'

# Poll training status
curl http://localhost:8080/v1/admin/models/status/job-abc123 \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# List registered models
curl http://localhost:8080/v1/admin/models \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### 10.4 Training CronJob (Kubernetes)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rag-training
  namespace: rag-system
spec:
  schedule: "0 2 * * 0"               # Sunday 2am
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: trainer
            image: rag-system/trainer:v2.0.0
            env:
            - name: TRAINING_PROFILE
              value: "prod"
            - name: MLFLOW_TRACKING_URI
              value: "http://mlflow:5000"
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: rag-secrets
                  key: minio-access-key
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: rag-secrets
                  key: minio-secret-key
            command:
              - python
              - -m
              - app.model_evolution.trainer
              - --model-type
              - slm
              - --dataset
              - feedback
              - --profile
              - prod
          restartPolicy: OnFailure
```

### 10.5 Canary Rollout

```bash
# Register new model version
MODEL_VERSION=$(curl -s -X POST http://localhost:8080/v1/admin/models/promote \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"model_id": "slm-router-v2", "stage": "staging"}' | jq -r '.version')

# Evaluate against baseline
curl -X POST http://localhost:8080/v1/admin/models/evaluate \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "{\"model_id\": \"slm-router-v2\", \"version\": \"$MODEL_VERSION\"}"

# If eval passes, start canary (5% traffic)
curl -X POST http://localhost:8080/v1/admin/models/canary/split \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"model_id": "slm-router-v2", "traffic_percent": 5}'

# Check canary status
curl http://localhost:8080/v1/admin/models/canary/status \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Promote to 100% or rollback
curl -X POST http://localhost:8080/v1/admin/models/canary/split \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"model_id": "slm-router-v2", "traffic_percent": 100}'
```

---

## 11. Security Hardening

### 11.1 Non-Root Users

All custom images should run as non-root:

```dockerfile
# proxy/Dockerfile
RUN useradd --system --uid 1000 --create-home raguser && \
    chown -R raguser:raguser /app
USER raguser
```

**Verify:**

```bash
docker inspect rag-proxy | jq '.[0].Config.User'
# → "raguser" or "1000"
```

### 11.2 Read-Only Filesystems

```yaml
# docker-compose.yml
rag-proxy:
  read_only: true
  tmpfs:
    - /tmp:size=100M,mode=1777
  volumes:
    - ./logs:/app/logs          # Writable log directory
    - ./cache:/app/cache:ro     # Model cache — read-only
    - ./.env:/app/.env:ro       # Config — read-only
```

In Kubernetes:

```yaml
securityContext:
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000

volumeMounts:
  - name: logs
    mountPath: /app/logs
  - name: tmp
    mountPath: /tmp
```

### 11.3 Capabilities Drop

```yaml
# Docker Compose
rag-proxy:
  cap_drop:
    - ALL
  cap_add:
    - NET_BIND_SERVICE    # Only if port < 1024

# Kubernetes
securityContext:
  capabilities:
    drop:
      - ALL
  allowPrivilegeEscalation: false
```

### 11.4 Secrets Rotation

**Docker Compose secrets rotation:**

```bash
# 1. Update secrets in .env
vim proxy/.env

# 2. Restart only the dependent service
docker compose restart rag-proxy

# 3. Verify
docker compose logs rag-proxy | tail -5
```

**K8s secrets rotation:**

```bash
# 1. Update the secret
kubectl create secret generic rag-secrets -n rag-system \
  --from-literal=jwt-secret=$(openssl rand -hex 32) \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. Trigger rolling restart to pick up new secret
kubectl rollout restart deployment/rag-proxy -n rag-system

# 3. Verify
kubectl rollout status deployment/rag-proxy -n rag-system
```

**Automated rotation with External Secrets Operator:**

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rag-secrets
spec:
  refreshInterval: "1h"             # Auto-refresh every hour
  target:
    name: rag-secrets
    creationPolicy: Owner
  dataFrom:
    - extract:
        key: "rag/production"       # All secrets from this path
```

When combined with `reloader.stakater.com/auto: "true"` annotation on the Deployment, pods restart automatically when
secrets change.

### 11.5 TLS Everywhere

**Docker Compose (nginx + Let's Encrypt):**

```yaml
nginx:
  image: nginx:1.27-alpine
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
    - ./certs:/etc/nginx/certs:ro
  ports:
    - "80:80"
    - "443:443"
```

```nginx
# nginx.conf
server {
    listen 443 ssl http2;
    server_name rag.example.com;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    location /v1/ {
        proxy_pass http://rag-proxy:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        proxy_buffering off;       # Required for SSE streaming
    }
}
```

### 11.6 API Key Protection

```bash
# Enforce API key on LLM backend
# vLLM:
--api-key ${LLM_API_KEY}

# llama.cpp:
--api-key ${LLM_API_KEY}

# Proxy:
LLM_API_KEY=your-key
```

### 11.7 Security Checklist

- [ ] Change ALL default passwords (Neo4j, Redis, MinIO)
- [ ] Set `LLM_API_KEY` and enforce it on the LLM backend
- [ ] Use nginx/Ingress with TLS in front of port 8080
- [ ] Enable firewall: only expose ports 80/443 externally
- [ ] Drop all Linux capabilities from containers
- [ ] Use read-only root filesystems where possible
- [ ] Run as non-root user (UID 1000) in all custom images
- [ ] Set `LOG_FORMAT=json` and `AUDIT_ENABLED=true`
- [ ] Mask all secrets in logs via `SENSITIVE_SECRETS`
- [ ] Enable rate limiting (`RATE_LIMIT_ENABLED=true`)
- [ ] Enable input sanitization (`SANITIZE_INPUT=true`)
- [ ] Rotate container logs (max 100MB × 3 files)
- [ ] Run dependency vulnerability scans in CI: `pip-audit`

---

## 12. Monitoring Setup

### 12.1 Prometheus Scrape Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'rag-proxy'
    metrics_path: '/metrics'
    static_configs:
      - targets:
          - 'rag-proxy:8080'
        labels:
          service: 'rag-proxy'
          environment: 'production'

  - job_name: 'rag-proxy-k8s'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - rag-system
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: rag-proxy
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
```

**ServiceMonitor (Kubernetes):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: rag-proxy
  namespace: rag-system
spec:
  selector:
    matchLabels:
      app: rag-proxy
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
```

### 12.2 Key Metrics Exposed

| Metric                         | Type      | Description                         |
|--------------------------------|-----------|-------------------------------------|
| `rag_requests_total`           | Counter   | Total API requests by endpoint      |
| `rag_request_duration_seconds` | Histogram | Request latency (p50/p95/p99)       |
| `rag_retrieval_chunks`         | Histogram | Chunks retrieved per query          |
| `rag_rerank_duration_seconds`  | Histogram | Reranker latency                    |
| `rag_llm_duration_seconds`     | Histogram | LLM generation latency              |
| `rag_llm_tokens_total`         | Counter   | Tokens used (prompt + completion)   |
| `rag_cache_hit_ratio`          | Gauge     | Redis cache hit ratio               |
| `rag_errors_total`             | Counter   | Error count by type                 |
| `rag_etl_stream_lag`           | Gauge     | Pending messages per consumer group |
| `rag_warmup_completed`         | Gauge     | 1 if warm-up finished               |

### 12.3 Alert Rules

```yaml
# prometheus-alerts.yml
groups:
  - name: rag-system-critical
    rules:
      - alert: RAGProxyDown
        expr: up{job="rag-proxy"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "RAG Proxy is down"
          runbook: "https://wiki.example.com/runbooks/rag-proxy-down"

      - alert: HighErrorRate
        expr: rate(rag_errors_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "RAG error rate > 5% in 5-minute window"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "p95 latency > 10s"

      - alert: LLMDown
        expr: rag_llm_duration_seconds == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "LLM not responding for 2 minutes"

      - alert: QdrantUnhealthy
        expr: up{job="qdrant"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Qdrant vector database is down"

  - name: rag-system-warning
    rules:
      - alert: LowCacheHitRate
        expr: rag_cache_hit_ratio < 0.2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Cache hit ratio below 20%"

      - alert: DiskNearFull
        expr: node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes < 0.15
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk < 15% free on /data"

      - alert: StreamConsumerLag
        expr: rag_etl_stream_lag > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Streaming ETL consumer lag > 100 messages"

      - alert: Neo4jUnhealthy
        expr: up{job="neo4j"} == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Neo4j graph database is down (graph expansion disabled)"
```

### 12.4 Grafana Dashboard Import

```bash
# Import pre-built dashboards
# Dashboards are at: infra/helm/rag-system/dashboards/

# Option A: via Grafana API
curl -X POST http://grafana:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -d @infra/helm/rag-system/dashboards/grafana-overview.json

# Option B: via ConfigMap (Kubernetes)
kubectl create configmap grafana-dashboard-rag-overview \
  --from-file=grafana-overview.json=infra/helm/rag-system/dashboards/grafana-overview.json \
  -n monitoring

kubectl label configmap grafana-dashboard-rag-overview \
  grafana_dashboard="1" -n monitoring
```

**Available dashboards:**

| Dashboard             | File                          | Key Panels                                                 |
|-----------------------|-------------------------------|------------------------------------------------------------|
| **RAG Overview**      | `grafana-overview.json`       | Request rate, latency, error rate, confidence distribution |
| **Retrieval Quality** | `grafana-retrieval.json`      | MRR, Recall@k, nDCG, cache hit ratio                       |
| **Infrastructure**    | `grafana-infrastructure.json` | CPU, memory, disk, GPU per component                       |

### 12.5 SLI/SLO Reference

| SLI             | Target | Measurement Window |
|-----------------|--------|--------------------|
| Availability    | 99.5%  | 28 days            |
| p95 Latency     | < 5s   | 5 min window       |
| Error Rate      | < 1%   | 5 min window       |
| Cache Hit Ratio | > 30%  | 1 hour window      |

---

## 13. Backup Strategy

### 13.1 Backup Schedule

| Component        | Frequency       | Retention                    | Method                            |
|------------------|-----------------|------------------------------|-----------------------------------|
| Qdrant snapshots | Every 6 hours   | 7 daily, 4 weekly, 3 monthly | `POST /collections/.../snapshots` |
| Neo4j dumps      | Every 6 hours   | 7 daily, 4 weekly, 3 monthly | `neo4j-admin database dump`       |
| Redis RDB        | Every 1 hour    | 24 hourly, 7 daily           | `redis-cli BGSAVE`                |
| ETL WAL state    | Every 30 min    | 7 daily                      | File copy                         |
| Proxy config     | On change (git) | Full history                 | `git push`                        |

### 13.2 Qdrant Snapshots

```bash
# Create snapshot
curl -X POST http://localhost:6333/collections/knowledge_base/snapshots

# List snapshots
curl http://localhost:6333/collections/knowledge_base/snapshots

# Download snapshot
SNAPSHOT_NAME=$(curl -s http://localhost:6333/collections/knowledge_base/snapshots | jq -r '.result[-1].name')
curl "http://localhost:6333/collections/knowledge_base/snapshots/${SNAPSHOT_NAME}" \
  -o qdrant_backup_$(date +%Y%m%d_%H%M).snapshot

# Restore (on target Qdrant instance)
curl -X PUT http://localhost:6333/collections/knowledge_base/snapshots/upload \
  -F "snapshot=@qdrant_backup_20260706_1200.snapshot"

# Cron schedule
# 0 */6 * * * curl -X POST http://localhost:6333/collections/knowledge_base/snapshots
```

### 13.3 Neo4j Dumps

```bash
# Dump database
docker exec rag-neo4j neo4j-admin database dump neo4j --to-path=/backups/
docker cp rag-neo4j:/backups/neo4j.dump ./neo4j_backup_$(date +%Y%m%d).dump

# Restore
docker stop rag-neo4j
docker exec rag-neo4j neo4j-admin database load neo4j \
  --from-path=/backups/ --overwrite-destination=true
docker start rag-neo4j

# Verify
docker exec rag-neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN count(n)"
```

### 13.4 Redis Persistence

Redis in the standard docker-compose uses `--appendonly yes` (AOF persistence). This provides crash-safe recovery. For
backups:

```bash
# Trigger a background save
docker exec rag-redis redis-cli BGSAVE

# Copy the RDB file
docker cp rag-redis:/data/dump.rdb ./redis_backup_$(date +%Y%m%d_%H%M).rdb

# Restore: stop Redis, copy dump.rdb in, start Redis
docker compose stop redis
cp redis_backup_20260706_1200.rdb /data/redis/dump.rdb
docker compose start redis
```

### 13.5 S3/MinIO Backup Script

```bash
#!/bin/bash
# scripts/backup.sh — Comprehensive backup to S3/MinIO
set -euo pipefail

BACKUP_DIR="/tmp/rag-backup-$(date +%Y-%m-%d-%H%M)"
S3_BUCKET="s3://rag-backups"
mkdir -p "$BACKUP_DIR"

echo "=== Qdrant Snapshot ==="
curl -s -X POST "localhost:6333/collections/knowledge_base/snapshots"
sleep 10
SNAPSHOT=$(curl -s localhost:6333/collections/knowledge_base/snapshots | jq -r '.result[-1].name')
aws s3 cp "/data/qdrant/snapshots/$SNAPSHOT" \
  "$S3_BUCKET/qdrant/$(date +%Y-%m-%d-%H%M)/"

echo "=== Neo4j Dump ==="
docker exec rag-neo4j neo4j-admin database dump neo4j --to-path=/backups/
docker cp rag-neo4j:/backups/neo4j.dump "$BACKUP_DIR/neo4j.dump"
aws s3 cp "$BACKUP_DIR/neo4j.dump" "$S3_BUCKET/neo4j/$(date +%Y-%m-%d-%H%M)/"

echo "=== Redis RDB ==="
docker exec rag-redis redis-cli BGSAVE
sleep 5
aws s3 cp /data/redis/dump.rdb "$S3_BUCKET/redis/$(date +%Y-%m-%d-%H%M)/"

echo "=== ETL WAL ==="
aws s3 cp /opt/rag-system/etl/wal/etl_wal.json "$S3_BUCKET/etl/$(date +%Y-%m-%d-%H%M)/"

echo "=== Cleanup ==="
rm -rf "$BACKUP_DIR"
echo "Backup complete."
```

```bash
# Cron entry (every 6 hours):
# 0 */6 * * * /opt/rag-system/scripts/backup.sh >> /var/log/rag-backup.log 2>&1
```

### 13.6 Backup CronJob (Kubernetes)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rag-backup
  namespace: rag-system
spec:
  schedule: "0 */6 * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: amazon/aws-cli:latest
            env:
            - name: S3_BUCKET
              value: "s3://rag-backups"
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: rag-secrets
                  key: backup-s3-access-key
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: rag-secrets
                  key: backup-s3-secret-key
            command:
              - /bin/sh
              - -c
              - |
                TIMESTAMP=$(date +%Y-%m-%d-%H%M)
                # Qdrant snapshot
                curl -s -X POST qdrant:6333/collections/knowledge_base/snapshots
                sleep 10
                # Neo4j dump
                cypher-shell -u neo4j -p $NEO4J_PASSWORD \
                  "CALL apoc.export.cypher.all('/tmp/neo4j.cypher', {})"
                aws s3 cp /tmp/neo4j.cypher "$S3_BUCKET/neo4j/$TIMESTAMP/"
                echo "Backup complete: $TIMESTAMP"
          restartPolicy: OnFailure
```

### 13.7 Restore Procedures

**Full recovery (all components):**

```bash
# 1. Deploy clean infrastructure
docker compose up -d qdrant neo4j redis

# 2. Restore Qdrant from latest snapshot
bash scripts/restore_all.sh qdrant --latest

# 3. Restore Neo4j from latest dump
bash scripts/restore_all.sh neo4j --latest

# 4. Restore Redis
bash scripts/restore_all.sh redis --latest

# 5. Restore WAL and run incremental ETL
cp backups/latest_etl_wal.json etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --incremental

# 6. Start proxy
docker compose up -d rag-proxy

# 7. Verify
curl http://localhost:8080/v1/health
```

### 13.8 WAL Corruption Recovery

If the ETL Write-Ahead Log is corrupted:

```bash
# Delete the corrupted WAL
rm etl/wal/etl_wal.json

# Run full reindex
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

---

## 14. Troubleshooting Common Deployment Issues

### 14.1 Port Conflicts

**Symptom:** `Error starting userland proxy: listen tcp4 0.0.0.0:8080: bind: address already in use`

```bash
# Find what's using the port
ss -tlnp | grep 8080

# If another service is using it, stop it or change the port:
# docker-compose.yml:
ports:
  - "8081:8080"     # Map host 8081 to container 8080
```

### 14.2 Model Not Found

**Symptom:** vLLM fails with `ValueError: Model /models/model-name not found`

```bash
# Verify the model path
ls -la /opt/models/model-name/

# Verify the volume mount in the container
docker exec rag-vllm ls -la /models/

# Correct the path in docker-compose.yml:
vllm:
  volumes:
    - /opt/models/Llama-3.1-70B-Instruct:/models/Llama-3.1-70B-Instruct:ro
```

### 14.3 OOM (Out of Memory)

**Symptom:** Container killed with exit code 137, `dmesg` shows OOM killer

**LLM backend OOM:**

```bash
# Reduce context length (vLLM)
--max-model-len 32768   # instead of 65536

# Use quantized model (llama.cpp)
# Download Q4_K_M.gguf instead of Q8 or fp16

# Reduce GPU memory utilization (vLLM)
--gpu-memory-utilization 0.70   # instead of 0.90
```

**Neo4j OOM:**

```bash
# Reduce heap size
NEO4J_dbms_memory_heap_max__size=1G   # instead of 2G
NEO4J_dbms_memory_pagecache_size=512M # instead of 1G
```

**Proxy OOM:**

```bash
# Reduce chunk limits
MAX_CHUNKS_RETRIEVAL=20    # instead of 50
RERANKER_BATCH_SIZE=8      # instead of 32
```

### 14.4 Permission Denied

**Symptom:** Container fails with `PermissionError: [Errno 13] Permission denied: '/app/logs'`

```bash
# Fix volume permissions
sudo chown -R 1000:1000 /opt/rag-system/proxy/logs
sudo chmod 755 /opt/rag-system/proxy/logs

# Check if container runs as non-root
docker inspect rag-proxy | jq '.[0].Config.User'
# → "raguser" or "1000"

# Ensure UID matches between host and container
id raguser   # On host
docker exec rag-proxy id   # In container
```

### 14.5 Qdrant Connection Refused

**Symptom:** Proxy health check shows `"qdrant": "disconnected"`

```bash
# Check Qdrant is running
docker ps | grep qdrant

# Check Qdrant health
curl http://localhost:6333/health

# Check network connectivity from proxy
docker exec rag-proxy curl -s http://qdrant:6333/health

# If using localhost instead of service name:
# Change QDRANT_HOST from "localhost" to "qdrant" in .env
```

### 14.6 vLLM Startup Takes Too Long

**Symptom:** vLLM container healthy but proxy reports LLM unavailable

```bash
# vLLM model loading can take 3-10 minutes for large models
# Increase start_period in healthcheck:
vllm:
  healthcheck:
    start_period: 300s   # 5 minutes

# Increase proxy readiness timeout
rag-proxy:
  healthcheck:
    start_period: 90s
    retries: 10

# Check vLLM progress logs
docker logs rag-vllm -f | grep -i "loading\|ready\|error"
```

### 14.7 Docker Compose "no space left on device"

```bash
# Prune unused Docker data
docker system prune -a --volumes -f

# Clean Docker build cache
docker builder prune -a -f

# Check disk usage
df -h
docker system df

# Prune old ETL cold chunks
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete

# Rotate logs
find proxy/logs/ -name "*.log" -mtime +7 -delete
```

### 14.8 Redis Streams Consumer Lag

**Symptom:** ETL events backing up, Prometheus alert `StreamConsumerLag`

```bash
# Check consumer group status
docker exec rag-redis redis-cli XINFO GROUPS etl:events

# Check pending messages
docker exec rag-redis redis-cli XPENDING etl:events etl-extract

# If a consumer is stuck, delete and recreate the consumer group:
docker exec rag-redis redis-cli XGROUP DESTROY etl:events etl-chunk
docker exec rag-redis redis-cli XGROUP CREATE etl:events etl-chunk $ MKSTREAM

# Check dead letter queue
docker exec rag-redis redis-cli XLEN etl:events:dlq

# Reprocess DLQ events
python etl/scheduler/reprocess_dlq.py --stream etl:events:dlq
```

### 14.9 Neo4j APOC Plugin Not Loaded

**Symptom:** `There is no procedure with the name 'apoc.export.cypher.all'`

```bash
# Verify APOC is in Neo4j plugins directory
docker exec rag-neo4j ls /plugins/

# If missing, mount APOC jar:
# docker-compose.yml:
neo4j:
  volumes:
    - ./neo4j-plugins/apoc-5.25-core.jar:/plugins/apoc-core.jar:ro

# Or set environment variable:
NEO4J_PLUGINS='["apoc"]'
```

### 14.10 GPU Not Detected in Container

```bash
# Verify NVIDIA Container Toolkit is installed
nvidia-container-cli info

# Check Docker GPU access
docker run --rm --gpus all nvidia/cuda:12.4-base nvidia-smi

# In docker-compose, ensure:
vllm:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
  runtime: nvidia     # Only needed for older Docker versions
```

---

## Related Documents

| Document                                                                                                      | Coverage                                                                    |
|---------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| [Kubernetes Deployment (Helm)](https://github.com/AlexanderNarbaev/rag-system/blob/main/deploy/k8s/README.md) | Helm chart, K8s deployment, secrets management, scaling                     |
| [Operations Guide](operations-guide.md)                                                                       | Day-2 ops: monitoring details, scaling, upgrades, compression, cold storage |
| [Disaster Recovery Runbook](disaster-recovery-runbook.md)                                                     | Step-by-step recovery procedures for all failure scenarios                  |
| [Performance & Quality Best Practices](performance-quality.md)                                                | HNSW tuning, quantization, inference optimization, benchmarking             |
| [Production Readiness Checklist](best-practices-checklist.md)                                                 | 8-dimension readiness tracker (94% complete)                                |
| [SLI/SLO Definitions](../sli_slo.md)                                                                          | Service level indicators, objectives, error budgets                         |
| [Access Control & RBAC](access-control-rbac.md)                                                               | JWT auth, Keycloak OIDC, RBAC implementation                                |
| [Troubleshooting](troubleshooting.md)                                                                         | Additional common issues and resolutions                                    |
