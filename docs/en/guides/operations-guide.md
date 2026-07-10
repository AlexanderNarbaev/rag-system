# Operations Guide

**Version:** v2.0.0 | **Last Updated:** 2026-07-06

Definitive operations reference for the RAG Knowledge Assistant. Covers monitoring, health checks, performance tuning, scaling, backup/restore, maintenance, upgrades, disaster recovery, day-to-day commands, and SLI/SLO management.

---

## 1. Monitoring

### 1.1 Prometheus Metrics Reference

All metrics are exposed at `GET /metrics` (port 8080). Set `METRICS_ENABLED=true` and `LOG_FORMAT=json` for structured logging.

#### Proxy Application Metrics

| # | Metric Name | Type | Labels | Description |
|---|-------------|------|--------|-------------|
| 1 | `rag_requests_total` | Counter | `endpoint`, `status` | Total API requests per endpoint with HTTP status |
| 2 | `rag_request_duration_seconds` | Histogram | `endpoint` | End-to-end request latency (buckets: 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0) |
| 3 | `rag_retrieval_duration_seconds` | Histogram | — | Qdrant hybrid search latency (buckets: 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0) |
| 4 | `rag_rerank_duration_seconds` | Histogram | — | Cross-encoder reranker latency (buckets: 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0) |
| 5 | `rag_llm_duration_seconds` | Histogram | — | LLM generation latency (buckets: 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0) |
| 6 | `rag_cache_hits_total` | Counter | — | Cumulative cache hit count across all tiers |
| 7 | `rag_context_tokens` | Gauge | — | Current number of context tokens passed to LLM |
| 8 | `rag_active_requests` | Gauge | — | Number of currently in-flight requests |

#### Infrastructure Metrics (external exporters)

| # | Metric Name | Source | Description |
|---|-------------|--------|-------------|
| 9 | `up{job="rag-proxy"}` | Prometheus scrape | Proxy process up/down (1/0) |
| 10 | `up{job="qdrant"}` | Qdrant `/metrics` | Qdrant up/down |
| 11 | `up{job="neo4j"}` | Neo4j exporter `:2004/metrics` | Neo4j up/down |
| 12 | `up{job="redis"}` | Redis exporter `:9121/metrics` | Redis up/down |
| 13 | `qdrant_collections_vector_count` | Qdrant `/metrics` | Total vectors indexed |
| 14 | `qdrant_grpc_responses_total` | Qdrant `/metrics` | gRPC search requests |
| 15 | `qdrant_collections_segments_count` | Qdrant `/metrics` | HNSW segment count |
| 16 | `redis_connected_clients` | Redis exporter | Active Redis connections |
| 17 | `redis_used_memory_bytes` | Redis exporter | Redis memory usage |
| 18 | `redis_evicted_keys_total` | Redis exporter | Keys evicted (LRU) |
| 19 | `redis_keyspace_hits_total` | Redis exporter | Successful key lookups |
| 20 | `redis_keyspace_misses_total` | Redis exporter | Missed key lookups |
| 21 | `neo4j_dbms_memory_heap_used` | Neo4j exporter | Neo4j heap usage |
| 22 | `neo4j_dbms_memory_pagecache_usage_ratio` | Neo4j exporter | Page cache hit/miss |
| 23 | `neo4j_bolt_connections_opened_total` | Neo4j exporter | Bolt connections opened |
| 24 | `node_cpu_seconds_total` | Node exporter | CPU usage per instance |
| 25 | `node_memory_MemAvailable_bytes` | Node exporter | Available memory |
| 26 | `node_filesystem_avail_bytes` | Node exporter | Available disk space |
| 27 | `node_network_receive_bytes_total` | Node exporter | Network ingress |
| 28 | `node_network_transmit_bytes_total` | Node exporter | Network egress |
| 29 | `rag_warmup_completed` | Gauge | 1 if model warm-up completed successfully |
| 30 | `rag_etl_stream_lag` | Gauge (from Redis Streams) | Pending ETL messages per consumer group |

#### RAG Quality Metrics (from evaluation pipeline)

| # | Metric Name | Type | Description |
|---|-------------|------|-------------|
| 31 | `rag_retrieval_mrr` | Gauge | Mean Reciprocal Rank from eval run |
| 32 | `rag_retrieval_recall_at_10` | Gauge | Recall@10 from eval run |
| 33 | `rag_retrieval_ndcg_at_10` | Gauge | nDCG@10 from eval run |
| 34 | `rag_confidence_score_high_ratio` | Gauge | Fraction of responses with confidence ≥ 0.5 |
| 35 | `rag_ttft_seconds` | Histogram | Time To First Token for streaming responses |
| 36 | `rag_last_backup_timestamp_seconds` | Gauge | Unix timestamp of last successful backup |

### 1.2 Key Dashboards

Three Grafana dashboards are defined:

#### Dashboard 1: RAG Overview (`grafana-overview.json`)

**Key panels:**
- **Request Rate**: `rate(rag_requests_total[5m])` by endpoint
- **Latency Distribution**: `histogram_quantile(0.50, 0.95, 0.99, rate(rag_request_duration_seconds_bucket[5m]))`
- **Error Rate**: `sum(rate(rag_requests_total{status=~"5.."}[5m])) / sum(rate(rag_requests_total[5m]))`
- **Active Requests**: `rag_active_requests`
- **Confidence Distribution**: `rag_confidence_score_high_ratio`
- **Cache Hit Rate**: `rate(rag_cache_hits_total[5m]) / rate(rag_requests_total[5m])`
- **TTFT (p95)**: `histogram_quantile(0.95, rate(rag_ttft_seconds_bucket[5m]))`
- **Pipeline Breakdown**: retrieval vs rerank vs LLM latency stacked area

#### Dashboard 2: Retrieval Quality (`grafana-retrieval.json`)

**Key panels:**
- **MRR over time**: `rag_retrieval_mrr`
- **Recall@10 over time**: `rag_retrieval_recall_at_10`
- **nDCG@10 over time**: `rag_retrieval_ndcg_at_10`
- **Chunks Retrieved**: `avg(rag_context_tokens)` — proxy for retrieval breadth
- **Reranker Impact**: `rag_rerank_duration_seconds` hotspot map

#### Dashboard 3: Infrastructure (`grafana-infrastructure.json`)

**Key panels:**
- **CPU per component**: `rate(node_cpu_seconds_total{mode!="idle"}[5m])` grouped by service
- **Memory per component**: `node_memory_MemAvailable_bytes` per node
- **Disk usage**: `(node_filesystem_size_bytes - node_filesystem_avail_bytes) / node_filesystem_size_bytes`
- **Qdrant segments**: `qdrant_collections_segments_count`
- **Redis evictions**: `rate(redis_evicted_keys_total[5m])`
- **Neo4j heap**: `neo4j_dbms_memory_heap_used`

#### Import Dashboards

```bash
# Via Grafana API
curl -X POST http://grafana:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -d @k8s/helm/rag-system/dashboards/grafana-overview.json

# Via ConfigMap (K8s)
kubectl create configmap grafana-dashboard-rag-overview \
  --from-file=grafana-overview.json=k8s/helm/rag-system/dashboards/grafana-overview.json \
  -n monitoring
kubectl label configmap grafana-dashboard-rag-overview grafana_dashboard="1" -n monitoring
```

### 1.3 Alert Rules

Create `prometheus-alerts.yml` and load via `prometheus --rules.file=prometheus-alerts.yml`.

```yaml
groups:
  # ── Critical Alerts ──────────────────────────────────
  - name: rag-system-critical
    rules:
      - alert: RAGProxyDown
        expr: up{job="rag-proxy"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "RAG Proxy is down on {{ $labels.instance }}"
          description: "Proxy has been unreachable for 1 minute. All RAG requests failing."
          runbook: "https://wiki.example.com/runbooks/rag-proxy-down"

      - alert: HighRequestLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 10
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "p95 request latency exceeds 10s"
          description: "p95 latency is {{ $value | humanizeDuration }}. Threshold: 10s."
          runbook: "https://wiki.example.com/runbooks/rag-high-latency"

      - alert: QdrantUnhealthy
        expr: up{job="qdrant"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Qdrant vector database is down on {{ $labels.instance }}"
          description: "All hybrid search requests will fail. Proxy returning empty contexts."
          runbook: "https://wiki.example.com/runbooks/qdrant-down"

      - alert: LLMUnavailable
        expr: rate(rag_llm_duration_seconds_count[5m]) == 0 and rag_requests_total > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "LLM backend not responding"
          description: "No successful LLM calls in 2 minutes despite incoming requests."
          runbook: "https://wiki.example.com/runbooks/llm-down"

  # ── Warning Alerts ───────────────────────────────────
  - name: rag-system-warning
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(rag_requests_total{status=~"5.."}[5m]))
          / sum(rate(rag_requests_total[5m])) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Error rate > 1% over 5 minutes"
          description: "Current error rate: {{ $value | humanizePercentage }}. Threshold: 1%."
          runbook: "https://wiki.example.com/runbooks/rag-high-errors"

      - alert: LowCacheHitRate
        expr: rate(rag_cache_hits_total[10m]) / rate(rag_requests_total[10m]) < 0.2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Cache hit ratio below 20%"
          description: "Cache hit ratio: {{ $value | humanizePercentage }}. Check Redis connectivity."
          runbook: "https://wiki.example.com/runbooks/rag-low-cache"

      - alert: DiskNearFull
        expr: |
          node_filesystem_avail_bytes{mountpoint="/data"}
          / node_filesystem_size_bytes{mountpoint="/data"} < 0.15
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk usage > 85% on /data"
          description: "Available: {{ $value | humanizePercentage }}. Run disk cleanup."
          runbook: "https://wiki.example.com/runbooks/rag-disk-full"

      - alert: RedisHighEvictionRate
        expr: rate(redis_evicted_keys_total[5m]) > 1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Redis evicting keys at > 1/s"
          description: "Eviction rate: {{ $value }}/s. Increase maxmemory or reduce cache TTL."
          runbook: "https://wiki.example.com/runbooks/rag-redis-evictions"

      - alert: Neo4jUnhealthy
        expr: up{job="neo4j"} == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Neo4j graph database unreachable"
          description: "Graph expansion disabled. Non-graph queries unaffected (graceful degradation)."
          runbook: "https://wiki.example.com/runbooks/neo4j-down"

      - alert: StreamConsumerLag
        expr: rag_etl_stream_lag > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "ETL streaming consumer lag > 100 messages"
          description: "Consumer group lag: {{ $value }}. Check ETL pipeline throughput."
          runbook: "https://wiki.example.com/runbooks/rag-etl-lag"

  # ── Error Budget Alerts ──────────────────────────────
  - name: rag-system-error-budget
    rules:
      - alert: ErrorBudgetBurnCritical
        expr: |
          (
            sum(rate(rag_requests_total{status=~"5.."}[1h]))
            / sum(rate(rag_requests_total[1h]))
          ) > (1 - 0.995) * 14.4
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Error budget burning at > 14.4x (critical)"
          description: "Burn rate: {{ $value }}. Halt all deployments immediately."

      - alert: ErrorBudgetBurnWarning
        expr: |
          (
            sum(rate(rag_requests_total{status=~"5.."}[6h]))
            / sum(rate(rag_requests_total[6h]))
          ) > (1 - 0.995) * 6
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Error budget burning at > 6x (warning)"
          description: "Burn rate: {{ $value }}. Page on-call engineer."
```

### 1.4 Log Analysis

**Log format** is controlled by `LOG_FORMAT` (text or json). Structured JSON is recommended for production:

```bash
LOG_FORMAT=json
```

**Key log fields for querying (json):**

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 timestamp |
| `level` | DEBUG, INFO, WARNING, ERROR |
| `logger` | Component name (rag-proxy, retrieval, rerank, etc.) |
| `request_id` | Unique request identifier (`rag_<timestamp>_<hex>`) |
| `client_ip` | Originating IP address |
| `query` | Sanitized user query (truncated at 100 chars) |
| `duration_ms` | Request processing time |
| `chunks_count` | Retrieved chunks |
| `confidence` | Confidence score |

**Common log queries (jq):**

```bash
# Top 10 slowest requests
cat logs/rag-proxy.log | jq 'select(.duration_ms != null)' | jq -s 'sort_by(.duration_ms) | reverse | .[0:10]'

# Error rate by endpoint
cat logs/rag-proxy.log | jq 'select(.level == "ERROR") | .endpoint' | sort | uniq -c | sort -rn

# Requests with low confidence
cat logs/rag-proxy.log | jq 'select(.confidence != null and .confidence < 0.5)'

# Audit trail for a specific user
cat logs/audit.log | jq 'select(.user_id == "192.168.1.100")'

# Count requests by hour
cat logs/rag-proxy.log | jq -r '.timestamp[:13]' | sort | uniq -c
```

**Log rotation** (Docker):

```yaml
services:
  rag-proxy:
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"
```

**Log rotation** (systemd, bare-metal):

```
# /etc/logrotate.d/rag-proxy
/opt/rag-system/proxy/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 100M
}
```

---

## 2. Health Checks

### 2.1 Endpoint Reference

| Endpoint | Method | Purpose | Success Code | Degraded Code |
|----------|--------|---------|-------------|---------------|
| `/v1/health/live` | GET | Liveness — process is alive | 200 | — |
| `/v1/health/ready` | GET | Readiness — deps available | 200 | 503 |
| `/v1/health` | GET | Full health — detailed component status | 200 if all ok | 503 if any component degraded |
| `/metrics` | GET | Prometheus scrape endpoint | 200 | — |

### 2.2 What Each Probe Checks

**Liveness (`/v1/health/live`):**
Returns 200 as long as the Python process is alive. No dependency checks. Purpose: detect deadlocked or crashed processes.

```json
{"status": "alive", "timestamp": "2026-07-06T12:00:00Z"}
```

**Readiness (`/v1/health/ready`):**
Checks Qdrant connectivity (`get_collections()`) and LLM backend health (`GET /health` on the LLM endpoint with 2s timeout). Returns 503 if either is unreachable. Purpose: remove pod from service load balancer when dependencies are down.

```json
{
  "status": "ready",
  "timestamp": "2026-07-06T12:00:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "ok"
  }
}
```

**Full Health (`/v1/health`):**
Same checks as readiness but returns individual component status strings. Returns 200 if all OK, 503 if any degraded. Purpose: human-readable health dashboard.

```json
{
  "status": "ok",
  "timestamp": "2026-07-06T12:00:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "ok"
  }
}
```

### 2.3 Probe Configuration

#### Kubernetes Probes (from Helm `values.yaml`)

```yaml
proxy:
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
    failureThreshold: 30     # 150s total for model loading
```

#### Docker Compose Healthchecks

```yaml
rag-proxy:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/v1/health/live"]
    interval: 10s
    timeout: 5s
    retries: 3
    start_period: 60s

qdrant:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
    interval: 15s
    timeout: 5s
    retries: 3
    start_period: 10s

neo4j:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:7474"]
    interval: 15s
    timeout: 10s
    retries: 5
    start_period: 60s

redis:
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 5s
    retries: 3

vllm:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
    interval: 60s
    timeout: 30s
    retries: 5
    start_period: 180s
```

### 2.4 Startup Probe Rationale

The startup probe tolerates model loading time:
- **Embedder** (bge-m3): ~5-15s to load
- **Reranker** (MiniLM-L-6-v2): ~3-5s
- **spaCy models**: ~2s each
- **Neo4j driver connect**: ~2-5s
- **SLM local (llama.cpp)**: up to 60s

Total startup time typically 30-60s. The startup probe allows 150s (`failureThreshold: 30 × periodSeconds: 5`) to accommodate cold starts and concurrent model loading.

---

## 3. Performance Tuning

### 3.1 Qdrant HNSW Index Parameters

Configure via collection creation in `scripts/init_collections.py` or your ETL pipeline:

| Collection Size | `ef_construct` | `ef` (search) | `m` | Expected Recall@10 | RAM per 1M vec |
|-----------------|----------------|---------------|-----|--------------------|----------------|
| < 100K vectors | 128 | 64 | 16 | > 0.98 | ~1.5 GB |
| 100K – 1M vectors | 200 | 128 | 24 | > 0.96 | ~2.5 GB |
| > 1M vectors | 256 | 200 | 32 | > 0.94 | ~3.5 GB |

**Apply via Qdrant API:**

```python
from qdrant_client.http import models

client.create_collection(
    collection_name="knowledge_base",
    hnsw_config=models.HnswConfigDiff(
        m=24,
        ef_construct=200,
    ),
    ...
)

# At search time, override ef per query:
client.search(
    collection_name="knowledge_base",
    query_vector=vector,
    search_params=models.SearchParams(
        hnsw_ef=128,
        exact=False,
    ),
    limit=20,
)
```

**Tuning notes:**
- `m`: Number of edges per node. Higher = better recall, more RAM. Rule of thumb: `m = 16` to `64`, scale with `log(N)`.
- `ef_construct`: Controls build-time search depth. Higher = slower indexing, better graph quality. Keep 100-256.
- `ef` (search): Controls query-time search depth. Higher = better recall, slower search. Keep `ef ≥ k × 4` (e.g., `ef=128` for `top_k=20`).

### 3.2 Quantization Strategies

| Strategy | RAM Reduction | Recall Impact | Config |
|----------|--------------|---------------|--------|
| Scalar (int8) | 4× | < 1% | `models.ScalarQuantization(type=models.ScalarType.INT8, quantile=0.99, always_ram=True)` |
| Product (PQ) | 16× | 2–4% | `models.ProductQuantization(compression="x16", always_ram=True)` |
| Binary (BQ) | 32× | 5–8% | `models.BinaryQuantization(always_ram=True)` |

**Recommendation:**
- **Always enable scalar quantization** — 4× RAM savings with negligible recall loss.
- Enable **product quantization** for collections > 5M vectors.
- Enable **binary quantization** only for pre-filtered retrieval where you already reduce candidates to < 1000.

**On-disk indexing** for sparse vectors (bge-m3 sparse has up to 250K dimensions per vector):

```python
models.OptimizersConfigDiff(
    default_segment_number=2,
    indexing_threshold=20000,
)
# Set on collection creation:
on_disk_payload=True,
on_disk=True,  # moves vectors to disk, reduces RAM by 60%, ~5% latency increase
```

### 3.3 Cache Sizing

The proxy uses a multi-tier cache with the `CacheManager` (Redis or in-memory fallback):

| Cache Tier | Key Pattern | TTL | Expected Hit Rate |
|------------|-------------|-----|-------------------|
| **Embedding cache** | `embed:{md5(text)}` | 3600s (1h) | 15-25% |
| **Search result cache** | `rag:{user_id}:{query}:{version}` | 3600s (1h) | 5-10% |
| **Rerank cache** | `rerank:{md5(query)}:{md5(chunk_ids)}` | 300s (5min) | 8-12% |

**Redis configuration** in `docker-compose.yml` or K8s:

```bash
# Redis command args
--appendonly yes
--maxmemory 2gb
--maxmemory-policy allkeys-lru
--save 900 1 300 10
```

**Sizing guidelines:**
- 500K unique chunks: ~2 GB embedding cache (4KB per 1024-dim float32 dense vector)
- If `redis_evicted_keys_total` > 100/hour, increase `maxmemory` to 4 GB or reduce embedding TTL to 1800s
- Monitor: `redis-cli INFO stats | grep evicted_keys`

### 3.4 Worker Configuration

The proxy runs with `WORKERS=1` per replica. This is intentional:

- **Embedder, reranker, and cache state** are loaded per-process. Multiple workers mean multiple model copies in memory.
- **SSE streaming** works correctly with 1 worker per process.
- **Scale horizontally** via replicas (K8s `replicaCount`, Docker `docker compose scale`) instead of increasing `WORKERS`.

```bash
# proxy/.env — always keep at 1
WORKERS=1

# Docker Compose — scale replicas
docker compose -f docker-compose.yml up -d --scale rag-proxy=3

# Kubernetes — set replicaCount in values.yaml
proxy:
  replicaCount: 3
```

### 3.5 LLM Backend Tuning

#### vLLM (GPU)

```bash
# vLLM command flags
--model /models/your-model
--max-model-len 65536           # Match model's max context
--gpu-memory-utilization 0.92   # Leave 8% for KV-cache spikes
--tensor-parallel-size 2        # 1 per 24 GB VRAM
--enable-prefix-caching         # Reuse system prompt KV cache
--max-num-seqs 16               # Concurrent requests
--dtype auto
```

**Set `PREFIX_CACHING_ENABLED=true`** in the proxy to benefit from vLLM prefix caching.

#### llama.cpp (CPU)

```bash
# llama.cpp command flags
--model /models/your-model.gguf
--ctx-size 65536
--threads 16                   # Number of CPU cores
--n-gpu-layers 0               # 0 = CPU-only, -1 = all GPU
--batch-size 512               # Prompt processing batch
--api-key ""
```

### 3.6 Reranker Trade-off

| Model | Latency per pair | MRR Delta | VRAM |
|-------|-----------------|-----------|------|
| MiniLM-L-6-v2 (default) | 8ms | +15% over dense | 0.5 GB |
| MiniLM-L-12-v2 | 15ms | +18% | 1 GB |
| bge-reranker-v2-m3 | 25ms | +22% | 2 GB |

Stay with MiniLM-L-6-v2 unless MRR < 0.75. Configure via:

```bash
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_MAX_LENGTH=512
RERANKER_BATCH_SIZE=32
```

---

## 4. Scaling

### 4.1 Horizontal Pod Autoscaling (Kubernetes)

```yaml
# k8s/helm/rag-system/templates/proxy-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rag-proxy
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: rag-proxy
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 30
```

**Operational commands:**

```bash
# Check HPA status
kubectl get hpa -n rag-system

# Manually scale
kubectl scale deployment rag-proxy --replicas=5 -n rag-system

# View scaling events
kubectl describe hpa rag-proxy -n rag-system
```

**Docker Compose scaling:**

```bash
docker compose -f docker-compose.yml up -d --scale rag-proxy=4
```

### 4.2 Vertical Scaling (Resource Limits)

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|------------|-----------|----------------|--------------|
| RAG Proxy | 1 core | 4 cores | 2 Gi | 8 Gi |
| Qdrant | 500m | 4 cores | 1 Gi | 8 Gi |
| Neo4j | 500m | 4 cores | 2 Gi | 4 Gi |
| Redis | 100m | 1 core | 256 Mi | 2 Gi |
| vLLM | — | 16 cores | — | 48 Gi |
| llama.cpp | — | 16 cores | — | 64 Gi |

**When to increase:**

- **Proxy CPU > 70% sustained** → increase `proxy.resources.limits.cpu` or scale out.
- **Proxy Memory > 6 Gi** → embedder + reranker + spaCy loaded. Increase `limits.memory` to 12 Gi.
- **Qdrant Memory > 6 Gi** → increase `limits.memory` or enable scalar quantization.
- **Redis evictions > 100/hour** → increase `maxmemory` to 4 GB.

### 4.3 Qdrant Cluster (Raft Consensus)

For high availability, deploy Qdrant with 3 or 5 nodes:

```yaml
# values.yaml
qdrant:
  replicaCount: 3           # Must be odd for Raft quorum
  env:
    - name: QDRANT__CLUSTER__ENABLED
      value: "true"
```

**Sharding strategy:**
- 1 shard per collection for < 1M vectors (simpler)
- 2-4 shards for 1M-10M vectors (parallelizes writes)
- Replication factor: 2 for durability (tolerates 1 node failure)

```bash
# Check cluster status
curl http://qdrant-0.qdrant:6333/cluster

# Remove a failed peer
curl -X DELETE http://qdrant-0.qdrant:6333/cluster/peer/{peer_id}?force=true
```

### 4.4 Neo4j Clustering (Enterprise)

**Causal Cluster** topology (minimum 3 nodes):

```yaml
neo4j:
  replicaCount: 3
  tag: "5-enterprise"
  env:
    - name: NEO4J_dbms_mode
      value: "CORE"          # CORE or READ_REPLICA
    - name: NEO4J_causal__clustering_initial__discovery__members
      value: "neo4j-0.neo4j:5000,neo4j-1.neo4j:5000,neo4j-2.neo4j:5000"
```

**Container mode (Docker Compose HA):**

```yaml
# docker-compose.ha.yml
neo4j-core:
  image: neo4j:5.25-enterprise
  environment:
    NEO4J_dbms_mode: CORE
    NEO4J_causal__clustering_minimum__core__cluster__size__at__formation: "3"

neo4j-read-replica:
  image: neo4j:5.25-enterprise
  environment:
    NEO4J_dbms_mode: READ_REPLICA
```

### 4.5 Redis Sentinel (HA)

**Docker Compose HA setup:**

```yaml
redis-master:
  image: redis:7.4-alpine
  command: redis-server --appendonly yes

redis-replica-1:
  image: redis:7.4-alpine
  command: redis-server --appendonly yes --replicaof redis-master 6379

redis-replica-2:
  image: redis:7.4-alpine
  command: redis-server --appendonly yes --replicaof redis-master 6379

redis-sentinel-1:
  image: redis:7.4-alpine
  command: redis-sentinel /etc/redis/sentinel.conf
  volumes:
    - ./redis-sentinel.conf:/etc/redis/sentinel.conf:ro
```

**Sentinel config** (`redis-sentinel.conf`):

```conf
sentinel monitor rag-redis redis-master 6379 2
sentinel down-after-milliseconds rag-redis 5000
sentinel failover-timeout rag-redis 30000
sentinel parallel-syncs rag-redis 1
```

**Update proxy `REDIS_URL`** to point to Sentinel: `redis-sentinel://sentinel-1:26379,sentinel-2:26379,sentinel-3:26379/mymaster/rag-redis`.

---

## 5. Backup & Restore

### 5.1 Backup Schedule

| Component | Frequency | Retention | Method |
|-----------|-----------|-----------|--------|
| Qdrant snapshots | Every 6h | 7 daily, 4 weekly, 3 monthly | `POST /collections/{name}/snapshots` |
| Neo4j dumps | Every 6h | 7 daily, 4 weekly, 3 monthly | `neo4j-admin database dump` |
| Redis RDB | Every 1h | 24 hourly, 7 daily | `redis-cli BGSAVE` |
| ETL WAL state | Every 30m | 7 daily | File copy to S3 |
| Proxy config | On change (git) | Full history | `git push` |

### 5.2 Qdrant Snapshots

```bash
# ── Create snapshot ──────────────────────────────────────
curl -X POST http://${QDRANT_HOST}:6333/collections/knowledge_base/snapshots

# ── List snapshots ───────────────────────────────────────
curl http://${QDRANT_HOST}:6333/collections/knowledge_base/snapshots | jq '.result[] | {name, creation_time, size}'

# ── Download latest snapshot ─────────────────────────────
SNAPSHOT_NAME=$(curl -s http://${QDRANT_HOST}:6333/collections/knowledge_base/snapshots | jq -r '.result[-1].name')
curl "http://${QDRANT_HOST}:6333/collections/knowledge_base/snapshots/${SNAPSHOT_NAME}" \
  -o qdrant_backup_$(date +%Y%m%d_%H%M).snapshot

# ── Upload to S3 ─────────────────────────────────────────
aws s3 cp qdrant_backup_*.snapshot s3://rag-backups/qdrant/$(date +%Y/%m/%d)/

# ── Restore snapshot ─────────────────────────────────────
# On target Qdrant instance:
curl -X PUT "http://${QDRANT_HOST}:6333/collections/knowledge_base/snapshots/upload?priority=snapshot" \
  -F snapshot=@qdrant_backup.snapshot
```

### 5.3 Neo4j Dumps

```bash
# ── Create dump ──────────────────────────────────────────
# Inside container or on host:
neo4j-admin database dump neo4j --to-path=/backups/ --overwrite-destination=true

# Compress
gzip /backups/neo4j.dump
mv /backups/neo4j.dump.gz /backups/neo4j_$(date +%Y%m%d_%H%M).dump.gz

# ── Upload to S3 ─────────────────────────────────────────
aws s3 cp /backups/neo4j_*.dump.gz s3://rag-backups/neo4j/$(date +%Y/%m/%d)/

# ── Restore dump ─────────────────────────────────────────
# Stop Neo4j first
neo4j stop
# Restore
neo4j-admin database load neo4j --from-path=/backups/neo4j.dump --overwrite-destination=true
# Start Neo4j
neo4j start
# Verify
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "MATCH (n) RETURN count(n);"
```

### 5.4 Redis Persistence

**Enable AOF + RDB for point-in-time recovery:**

```bash
# redis.conf or command args
--appendonly yes
--save 900 1 300 10
--dir /data
```

**Manual backup:**

```bash
# Trigger RDB snapshot
redis-cli BGSAVE

# Wait for completion
redis-cli LASTSAVE

# Copy RDB file
cp /data/dump.rdb /backups/redis_$(date +%Y%m%d_%H%M).rdb

# Upload to S3
aws s3 cp /backups/redis_*.rdb s3://rag-backups/redis/$(date +%Y/%m/%d)/
```

**Restore:**

```bash
# Stop Redis, replace dump.rdb, start Redis
docker compose stop redis
cp redis_backup.rdb /data/redis/dump.rdb
docker compose start redis
redis-cli PING
```

### 5.5 Automated Backup CronJob (Kubernetes)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rag-backup
  namespace: rag-system
spec:
  schedule: "0 */6 * * *"             # Every 6 hours
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
            - name: QDRANT_HOST
              value: "qdrant.rag-system.svc.cluster.local"
            - name: NEO4J_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: rag-secrets
                  key: neo4j-password
            command:
            - /bin/sh
            - -c
            - |
              set -e
              DATE=$(date +%Y%m%d_%H%M)
              # Qdrant snapshot
              curl -s -X POST "http://${QDRANT_HOST}:6333/collections/knowledge_base/snapshots"
              SNAP=$(curl -s "http://${QDRANT_HOST}:6333/collections/knowledge_base/snapshots" | jq -r '.result[-1].name')
              curl -s "http://${QDRANT_HOST}:6333/collections/knowledge_base/snapshots/${SNAP}" -o /tmp/qdrant_${DATE}.snapshot
              aws s3 cp /tmp/qdrant_${DATE}.snapshot s3://rag-backups/qdrant/${DATE}/

              # Neo4j dump
              kubectl exec -n rag-system statefulset/neo4j -- neo4j-admin database dump neo4j --to-path=/tmp/
              kubectl cp rag-system/neo4j-0:/tmp/neo4j.dump /tmp/neo4j_${DATE}.dump
              aws s3 cp /tmp/neo4j_${DATE}.dump s3://rag-backups/neo4j/${DATE}/

              # Redis BGSAVE
              kubectl exec -n rag-system deploy/redis -- redis-cli BGSAVE
              echo "Backup completed: ${DATE}"
          restartPolicy: OnFailure
```

### 5.6 Automated Cleanup CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rag-backup-cleanup
  namespace: rag-system
spec:
  schedule: "0 3 * * *"               # Daily at 3am
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cleanup
            image: amazon/aws-cli:latest
            command:
            - /bin/sh
            - -c
            - |
              # Delete Qdrant snapshots older than 7 days
              aws s3 rm s3://rag-backups/qdrant/ --recursive --exclude "*" --include "*.snapshot" \
                --older-than 7d
              # Delete Neo4j dumps older than 7 days
              aws s3 rm s3://rag-backups/neo4j/ --recursive --exclude "*" --include "*.dump" \
                --older-than 7d
              # Delete Redis RDB older than 7 days
              aws s3 rm s3://rag-backups/redis/ --recursive --exclude "*" --include "*.rdb" \
                --older-than 7d
          restartPolicy: OnFailure
```

---

## 6. Maintenance

### 6.1 Model Rotation (Adapter Hot-Reload)

When fine-tuned adapters are ready, hot-reload them without restarting the proxy:

```bash
# Enable hot-reload in config
HOT_RELOAD_ENABLED=true
HOT_RELOAD_WATCH_INTERVAL=5            # Poll every 5 seconds
HOT_RELOAD_SIGNAL_ENABLED=true         # Accept SIGHUP for manual reload

# After placing new model files in the adapter directory:
# Method 1: Wait for automatic discovery (within 5s)
# Method 2: Signal manual reload
pkill -HUP -f "uvicorn.*main:app"

# Verify model is loaded
curl http://localhost:8080/v1/admin/models \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.models'
```

**Canary rollout workflow (admin API):**

```bash
# 1. Register new model version (via training job or manually)
MODEL_VERSION="slm-router-v2"

# 2. Evaluate against quality gate
curl -X POST http://localhost:8080/v1/admin/models/evaluate \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"model_name\": \"slm\", \"version\": \"$MODEL_VERSION\", \"metrics\": {\"accuracy\": 0.93, \"weighted_f1\": 0.88, \"mrr\": 0.78}}"

# 3. Start canary (5% traffic)
curl -X POST http://localhost:8080/v1/admin/models/canary/split \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"model_name\": \"slm\", \"traffic_split\": 0.05}"

# 4. Monitor canary status
curl http://localhost:8080/v1/admin/models/canary/status \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 5. Ramp canary phases
# Phase 2: 25% traffic
curl -X POST ... -d '{"model_name": "slm", "traffic_split": 0.25}'
# Phase 3: 50% traffic
curl -X POST ... -d '{"model_name": "slm", "traffic_split": 0.50}'
# Phase 4: 75% traffic
curl -X POST ... -d '{"model_name": "slm", "traffic_split": 0.75}'
# Phase 5: 100% (promote to production)
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"model_name\": \"slm\", \"version\": \"$MODEL_VERSION\"}"

# 6. Rollback if canary fails
curl -X POST http://localhost:8080/v1/admin/models/rollback \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"model_name\": \"slm\"}"
```

### 6.2 Index Optimization (Qdrant)

```bash
# Force segment optimization (merge small segments)
curl -X POST http://${QDRANT_HOST}:6333/collections/knowledge_base/optimizers \
  -H "Content-Type: application/json" \
  -d '{
    "default_segment_number": 2,
    "indexing_threshold": 50000,
    "flush_interval_sec": 5,
    "max_optimization_threads": 2
  }'

# Trigger vacuum (reclaim disk space after deletions)
curl -X POST "http://${QDRANT_HOST}:6333/collections/knowledge_base/update" \
  -H "Content-Type: application/json" \
  -d '{
    "optimizers_config": {
      "memmap_threshold_kb": 20000,
      "deleted_threshold": 0.2,
      "vacuum_min_vector_number": 1000
    }
  }'
```

### 6.3 Log Rotation

**Docker:** Configure via `logging` driver options (see Section 1.4).

**Kubernetes:** The `logDir` is `/app/logs` inside the container. Mount a persistent volume or use the sidecar pattern to forward to a centralized logging system (ELK/Loki).

**Manual cleanup:**

```bash
# Delete logs older than 30 days
find /opt/rag-system/proxy/logs/ -name "*.log" -mtime +30 -delete

# Truncate large log files (keep last 10000 lines)
for f in /opt/rag-system/proxy/logs/*.log; do
  tail -n 10000 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done
```

### 6.4 Disk Cleanup

```bash
# ── Clean Docker artifacts ───────────────────────────────
docker system prune -af --filter "until=72h"    # Images older than 3 days
docker volume prune -f                           # Unused volumes

# ── Clean pip cache ─────────────────────────────────────
pip cache purge

# ── Clean Python __pycache__ ────────────────────────────
find /opt/rag-system -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# ── Clean model cache (HuggingFace) ─────────────────────
# Keep only current models, delete cached blobs older than 30 days
find $HF_HOME -type f -mtime +30 -delete

# ── Clean ETL cold storage (keep last N versions) ───────
# Configured via COLD_STORAGE_MAX_VERSIONS=5
ls -t /data/cold_storage/ | tail -n +6 | xargs -I{} rm -rf /data/cold_storage/{}
```

**Disk usage monitoring (PromQL):**

```promql
# Alert when any data mount is > 85% full
(node_filesystem_avail_bytes{mountpoint=~"/data.*"}
  / node_filesystem_size_bytes{mountpoint=~"/data.*"}) < 0.15
```

---

## 7. Upgrades

### 7.1 Zero-Downtime Rolling Updates (Kubernetes)

The proxy `Deployment` uses `strategy: RollingUpdate` by default:

```yaml
# templates/proxy-deployment.yaml
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0       # Never drop below desired replicas
  minReadySeconds: 30          # Wait for pod to be ready
```

**Execute rolling update:**

```bash
# Update image tag
kubectl set image deployment/rag-proxy rag-proxy=rag-proxy:v2.0.1 -n rag-system

# Monitor rollout
kubectl rollout status deployment/rag-proxy -n rag-system

# Check old pods are terminated, new pods are healthy
kubectl get pods -n rag-system -w

# If rollout stalls (> 10 min), investigate
kubectl describe pod -n rag-system -l app=rag-proxy | grep -A5 Events

# Immediate rollback if needed
kubectl rollout undo deployment/rag-proxy -n rag-system
```

### 7.2 Canary Deployments (Manual)

For high-risk changes, use a separate canary deployment:

```bash
# 1. Deploy canary with 1 replica, new image
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-proxy-canary
  namespace: rag-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: rag-proxy
      version: canary
  template:
    metadata:
      labels:
        app: rag-proxy
        version: canary
    spec:
      containers:
      - name: rag-proxy
        image: rag-proxy:v2.0.1-rc1
        # ... same config as stable
EOF

# 2. Split traffic at ingress level (example with nginx ingress)
# Annotate canary service:
# nginx.ingress.kubernetes.io/canary: "true"
# nginx.ingress.kubernetes.io/canary-weight: "10"

# 3. Monitor canary metrics vs stable
# 4. If canary is healthy, promote to stable:
kubectl set image deployment/rag-proxy rag-proxy=rag-proxy:v2.0.1-rc1 -n rag-system

# 5. Remove canary deployment
kubectl delete deployment rag-proxy-canary -n rag-system
```

**Docker Compose canary:**

```bash
# Bring up canary on a different port
docker compose -f docker-compose.yml up -d --scale rag-proxy-canary=1

# Route a subset of traffic to the canary port via nginx
```

### 7.3 Rollback Procedures

**Kubernetes:**

```bash
# Option A: Revert to previous ReplicaSet
kubectl rollout undo deployment/rag-proxy -n rag-system

# Option B: Explicitly set a known-good image
kubectl set image deployment/rag-proxy rag-proxy=rag-proxy:v2.0.0 -n rag-system

# Option C: Helm rollback
helm rollback rag-system -n rag-system
```

**Docker Compose:**

```bash
# Edit proxy/.env or docker-compose.yml to use previous image tag
IMAGE_TAG=v2.0.0 docker compose up -d rag-proxy

# Or use git to revert config
git checkout v2.0.0 -- proxy/docker-compose.yml
docker compose up -d
```

**Model rollback (admin API):**

```bash
curl -X POST http://localhost:8080/v1/admin/models/rollback \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "slm"}'
```

### 7.4 Version Compatibility Matrix

| Proxy | Qdrant | Neo4j | Redis | vLLM | Python |
|-------|--------|-------|-------|------|--------|
| v2.0.0 | v1.10.x | 5.25.x | 7.4.x | 0.6.x | 3.11-3.12 |
| v1.5.0 | v1.9.x | 5.23.x | 7.2.x | 0.5.x | 3.11 |
| v1.0.0 | v1.8.x | 5.20.x | 7.0.x | 0.4.x | 3.10-3.11 |

**Upgrade order:**
1. **Databases first** (Qdrant, Neo4j, Redis) — backward compatible within major versions
2. **LLM backend** (vLLM/llama.cpp) — ensure model compatibility
3. **Proxy last** — reads from databases, makes API calls to LLM
4. **Update config** to enable new features

### 7.5 Graceful Shutdown

The proxy implements graceful shutdown (`GRACEFUL_SHUTDOWN_ENABLED=true`):

1. On `SIGTERM`/`SIGINT`, sets `shutting_down = True`
2. Waits for in-flight requests to complete (up to `SHUTDOWN_TIMEOUT=30s`)
3. Cancels any remaining pending tasks
4. Closes Redis connections
5. Exits

**Kubernetes termination graceful period** must exceed `SHUTDOWN_TIMEOUT`:

```yaml
spec:
  terminationGracePeriodSeconds: 60     # > SHUTDOWN_TIMEOUT (30s)
```

**Docker Compose:**

```yaml
rag-proxy:
  stop_grace_period: 45s
```

---

## 8. Disaster Recovery

### 8.1 Qdrant Failure

**Detection:**
- `/v1/health/ready` returns 503 with `qdrant: "unavailable"`
- Prometheus alert: `QdrantUnhealthy` (critical)
- All retrieval fails; proxy returns empty contexts

**Impact:** Complete retrieval failure. Proxy returns "I don't have enough information" with `rag_confidence: 0`. LLM still generates responses but without context.

**Recovery (total data loss):**

```bash
# 1. Stop ETL pipeline
kubectl scale deployment rag-etl --replicas=0 -n rag-system
# Or: systemctl stop rag-etl

# 2. Restore from latest snapshot
bash scripts/restore_all.sh qdrant --latest

# 3. Verify vectors restored
curl -s http://${QDRANT_HOST}:6333/collections | jq '.result.collections[].vectors_count'

# 4. Identify last backup timestamp for delta recovery
LAST_BACKUP=$(aws s3 ls s3://rag-backups/qdrant/ --recursive | sort | tail -1 | awk '{print $1"T"$2}')
echo "Last backup: $LAST_BACKUP"

# 5. Re-run ETL for delta since last backup
python scheduler/run_etl.py --since "$LAST_BACKUP" --config config/etl_config.yaml

# 6. Verify retrieval works
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"test query"}]}' \
  | jq '.rag_confidence'

# 7. Restart ETL in normal mode
kubectl scale deployment rag-etl --replicas=1 -n rag-system
```

**Recovery (node failure in Qdrant cluster):**

```bash
# If using Raft cluster (3+ nodes), the remaining nodes continue serving.
# Remove failed peer and add replacement:
curl -X DELETE "http://${QDRANT_HOST}:6333/cluster/peer/${FAILED_PEER_ID}?force=true"

# On replacement node, join cluster:
curl -X PUT "http://${QDRANT_HOST}:6333/cluster/recover" \
  -H "Content-Type: application/json" \
  -d "{\"uri\": \"http://qdrant-0.qdrant:6335\"}"
```

**RTO:** < 30 min (snapshot restore) | **RPO:** < 1 hour (delta ETL re-run)

### 8.2 Neo4j Corruption

**Detection:**
- `/v1/health/ready` reports LLM ok but Neo4j connectivity fails
- Prometheus alert: `Neo4jUnhealthy` (warning)
- Graph expansion returns empty results

**Impact:** Graph context is skipped. Non-agentic queries unaffected. Agentic queries lose entity expansion (~500 tokens of entity context). Proxy degrades gracefully per design.

**Recovery:**

```bash
# 1. Stop ETL pipeline
kubectl scale deployment rag-etl --replicas=0 -n rag-system

# 2. Restore from latest dump
bash scripts/restore_all.sh neo4j --latest

# 3. Verify
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN count(n) AS node_count;"

# 4. Re-run ETL for delta
python scheduler/run_etl.py --since "$LAST_BACKUP" --config config/etl_config.yaml

# 5. Restart ETL
kubectl scale deployment rag-etl --replicas=1 -n rag-system
```

**Database repair (if restoring from dump fails):**

```bash
# Check database consistency
neo4j-admin database check neo4j

# Force recovery
neo4j-admin database recover --force neo4j

# If still broken, create fresh database
neo4j-admin database create neo4j --force
# Then run full ETL re-index
```

**RTO:** < 30 min | **RPO:** < 1 hour

### 8.3 Redis Data Loss

**Detection:**
- Cache hit rate drops to near-zero
- Prometheus alert: `LowCacheHitRate` (warning)
- Proxy still functions but with higher latency (no cache)

**Impact:** All cache tiers empty. Search and LLM latencies increase by 20-50ms per embedding compute and 8-25ms per reranker call. Not a critical failure — proxy degrades gracefully.

**Recovery:**

```bash
# Redis with AOF persistence will auto-recover on restart.
# If AOF is corrupted, repair:
redis-check-aof --fix /data/appendonly.aof

# If disk is totally lost, restore from backup:
docker compose stop redis   # or kubectl scale deploy redis --replicas=0
cp /backups/redis_latest.rdb /data/redis/dump.rdb
docker compose start redis  # or kubectl scale deploy redis --replicas=1

# Verify
redis-cli PING
redis-cli INFO stats | grep keyspace_hits

# Cache will automatically repopulate as queries come in.
# No ETL re-run needed. No data loss for durable stores (Qdrant/Neo4j).
```

**RTO:** < 5 min | **RPO:** Cache-only. No permanent data loss. Cache rebuilds automatically.

### 8.4 Proxy Crash

**Detection:**
- Prometheus alert: `RAGProxyDown` (critical)
- Kubernetes: Pod shows `CrashLoopBackOff` or `Error`
- Docker: Container exits

**Impact:** All API endpoints unavailable. Ingress returns 502/503. All user requests fail.

**Recovery (Kubernetes):**

```bash
# 1. Check pod status and logs
kubectl get pods -n rag-system -l app=rag-proxy
kubectl logs deployment/rag-proxy --tail=100 -n rag-system

# 2. Check events for OOMKilled or startup failures
kubectl describe pod -n rag-system -l app=rag-proxy | grep -A10 Events

# 3. If OOMKilled: increase memory limits
kubectl set resources deployment/rag-proxy -n rag-system \
  --limits=memory=12Gi --requests=memory=4Gi

# 4. If startup failure: check model loading
kubectl exec -it deploy/rag-proxy -n rag-system -- python -c "
from app.retrieval import initialize_retrieval
initialize_retrieval()"

# 5. Rollback to last known good version
kubectl rollout undo deployment/rag-proxy -n rag-system

# 6. Scale to ensure minimum replicas
kubectl scale deployment rag-proxy --replicas=3 -n rag-system
```

**Recovery (Docker Compose):**

```bash
# Check logs for crash reason
docker compose logs rag-proxy --tail=100

# Restart
docker compose restart rag-proxy

# If crashed due to config error, fix .env and restart
docker compose up -d rag-proxy

# If crashed due to model path issue, verify:
ls -la /opt/models/
docker compose logs rag-proxy | grep -i "model"
```

### 8.5 LLM Backend Failure

**Detection:**
- `/v1/health/ready` returns 503 with `llm: "unavailable"`
- Non-streaming responses time out
- Streaming responses return errors
- Prometheus alert: `LLMUnavailable` (critical)

**Impact:** LLM generation fails. Retrieved contexts are returned but no synthesis. Responses contain only raw chunk text.

**Recovery:**

```bash
# 1. Check vLLM/llama.cpp process
# vLLM:
kubectl get pods -n rag-system -l app=vllm
docker compose logs vllm --tail=50

# llama.cpp:
docker compose logs vllm-cpu --tail=50

# 2. Check GPU availability (vLLM)
nvidia-smi
kubectl describe node <gpu-node> | grep nvidia

# 3. Restart LLM backend
kubectl rollout restart deployment/vllm -n rag-system
docker compose restart vllm

# 4. Wait for model to load (180s for vLLM, 240s for llama.cpp)
# Monitor readiness
watch -n 5 'curl -s http://localhost:8000/health'

# 5. Verify proxy picks up LLM again
curl http://localhost:8080/v1/health/ready | jq '.components.llm'
```

### 8.6 Disk Full Recovery

```bash
# 1. Identify what's consuming disk
du -sh /data/* | sort -rh | head -10

# 2. Emergency cleanup
# Docker:
docker system prune -af
docker volume prune -f

# Qdrant: trigger WAL segment cleanup
curl -X POST "http://${QDRANT_HOST}:6333/collections/knowledge_base/update" \
  -H "Content-Type: application/json" \
  -d '{"optimizers_config": {"deleted_threshold": 0.1}}'

# Neo4j: rotate transaction logs
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "CALL db.checkpoint()"

# Logs: delete old logs
find /data/logs/ -name "*.log" -mtime +7 -delete

# 3. If still full, extend PVC (K8s) or expand volume
# K8s: edit PVC to increase size, then restart pod
kubectl edit pvc qdrant-data-rag-proxy-0 -n rag-system
# Change spec.resources.requests.storage to larger value

# Docker: add new volume mount
```

---

## 9. Day-to-Day Commands

### 9.1 Quick Status Checks

```bash
# ── Kubernetes ───────────────────────────────────────────
# Overall system health
kubectl get pods,svc,hpa,ing,pvc -n rag-system

# Proxy health
kubectl exec -it deploy/rag-proxy -n rag-system -- curl -s localhost:8080/v1/health | jq

# Resource usage
kubectl top pods -n rag-system
kubectl top nodes

# Recent events
kubectl get events -n rag-system --sort-by='.lastTimestamp' | tail -20

# Logs (last 100 lines)
kubectl logs -l app=rag-proxy -n rag-system --tail=100 --prefix

# ── Docker Compose ───────────────────────────────────────
# Service status
docker compose -f docker-compose.yml ps

# Health
curl http://localhost:8080/v1/health | jq

# Resource usage
docker stats --no-stream

# Logs
docker compose logs --tail=50 rag-proxy
```

### 9.2 Common Operational Tasks

```bash
# ── Restart proxy (rolling, no downtime) ───────────────────
kubectl rollout restart deployment/rag-proxy -n rag-system
docker compose restart rag-proxy

# ── View proxy configuration ───────────────────────────────
kubectl exec -it deploy/rag-proxy -n rag-system -- python -c "from app.config import print_config; print_config()"
docker compose exec rag-proxy python -c "from app.config import print_config; print_config()"

# ── Test a chat completion ─────────────────────────────────
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"What is this system?"}],"max_tokens":100}' | jq

# ── Check retrieval confidence ─────────────────────────────
curl -s -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"test retrieval"}]}' \
  | jq '.rag_confidence'

# ── Get model list ─────────────────────────────────────────
curl http://localhost:8080/v1/models | jq

# ── Trigger warm-up ────────────────────────────────────────
curl -X POST http://localhost:8080/v1/admin/warmup \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# ── Check Qdrant collection stats ──────────────────────────
curl http://localhost:6333/collections/knowledge_base | jq '.result'
curl http://localhost:6333/collections/knowledge_base/cluster | jq

# ── Check Redis cache stats ────────────────────────────────
redis-cli INFO stats | grep -E 'keyspace|evicted|hit_rate'
redis-cli DBSIZE

# ── Check Neo4j node count ─────────────────────────────────
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt ORDER BY cnt DESC"

# ── Run ETL pipeline manually ──────────────────────────────
cd /opt/rag-system/etl
python scheduler/run_etl.py --config config/etl_config.yaml

# ── View ETL WAL status ────────────────────────────────────
cat /opt/rag-system/etl/wal/checkpoint.json | jq

# ── Force reindex (clear and re-ingest) ────────────────────
# ⚠ Destructive — only when needed
python scripts/init_collections.py --qdrant-recreate
python scheduler/run_etl.py --full-reindex --config config/etl_config.yaml
```

### 9.3 Administration via API

```bash
# ── Auth: Generate admin token ─────────────────────────────
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<admin-password>"}' \
  | jq -r '.access_token')

# ── List registered models ─────────────────────────────────
curl http://localhost:8080/v1/admin/models \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq

# ── Check training job status ──────────────────────────────
curl http://localhost:8080/v1/admin/models/status/train-abc123 \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq

# ── Promote model to production ────────────────────────────
curl -X POST http://localhost:8080/v1/admin/models/promote \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "slm", "version": "v2"}'

# ── Evaluate model quality ─────────────────────────────────
curl -X POST http://localhost:8080/v1/admin/models/evaluate \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "slm", "version": "v2", "metrics": {"accuracy": 0.92, "weighted_f1": 0.87}}'

# ── Rollback model ─────────────────────────────────────────
curl -X POST http://localhost:8080/v1/admin/models/rollback \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "slm"}'

# ── Canary traffic split ───────────────────────────────────
curl -X POST http://localhost:8080/v1/admin/models/canary/split \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "slm", "traffic_split": 0.25}'

# ── Canary status ──────────────────────────────────────────
curl http://localhost:8080/v1/admin/models/canary/status \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq
```

### 9.4 Troubleshooting Cheatsheet

| Symptom | Check | Command |
|---------|-------|---------|
| **Latency spike** | Qdrant segment count | `curl localhost:6333/collections/knowledge_base | jq '.result.segments_count'` |
| | LLM backend queue | vLLM: `curl localhost:8000/metrics | grep vllm:num_requests_waiting` |
| | Redis eviction rate | `redis-cli INFO stats | grep evicted_keys` |
| **Empty responses** | Qdrant vectors count | `curl localhost:6333/collections/knowledge_base | jq '.result.vectors_count'` |
| | Embedder loaded | `docker compose logs rag-proxy | grep -i embedder` |
| | Access control filtering | Check `LOG_REQUESTS` logs for "Access control filtered" messages |
| **High error rate** | Proxy crash loop | `kubectl describe pod -n rag-system -l app=rag-proxy` |
| | LLM timeout | Check `REQUEST_TIMEOUT` and increase if model is slow |
| | Rate limiting | Check `RATE_LIMIT_PER_MINUTE` and `RATE_LIMIT_BURST` |
| **Cache misses** | Redis connectivity | `redis-cli PING` from proxy container |
| | Cache TTL too short | Check `ttl` parameter in `CacheManager.set()` calls (3600s default) |
| | Memory pressure | `redis-cli INFO memory | grep used_memory_human` |

---

## 10. SLI/SLO Management

### 10.1 SLO Definitions

| # | SLI | SLO Target | Window | PromQL |
|---|-----|-----------|--------|--------|
| 1 | **Availability** | 99.5% | 30 days | `avg_over_time(up{job="rag-proxy"}[30d])` |
| 2 | **Latency (p95)** | < 5s | 30 days | `histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[30d]))` |
| 3 | **Error Rate** | < 1% | 30 days | `sum(rate(rag_requests_total{status=~"5.."}[30d])) / sum(rate(rag_requests_total[30d]))` |
| 4 | **Cache Hit Rate** | > 30% | 30 days | `rate(rag_cache_hits_total[30d]) / rate(rag_requests_total[30d])` |
| 5 | **Retrieval MRR** | > 0.75 | per eval | `rag_retrieval_mrr` |
| 6 | **Confidence ≥ 0.5** | > 70% | 30 days | `rag_confidence_score_high_ratio` |
| 7 | **TTFT (streaming)** | < 1s | 30 days | `histogram_quantile(0.95, rate(rag_ttft_seconds_bucket[30d]))` |
| 8 | **Backup RPO** | < 1h | per backup | `time() - rag_last_backup_timestamp_seconds` |
| 9 | **Backup RTO** | < 30m | per drill | Manual measurement |

### 10.2 Error Budget Calculation

```
Error Budget = (1 - SLO_target) × total_minutes_in_window

Example for Availability SLO (99.5%):
  Monthly minutes: 30 × 24 × 60 = 43,200
  Allowed downtime: (1 - 0.995) × 43,200 = 216 minutes/month (~3.6 hours)
```

**Grafana panel for error budget tracking:**

```promql
# Remaining error budget (%)
100 * (
  1 - (
    sum(rate(rag_requests_total{status=~"5.."}[30d]))
    / sum(rate(rag_requests_total[30d]))
  ) / 0.005
)
```

### 10.3 Burn Rate Alerts

| Burn Rate | Time Window | Alert Severity | Action |
|-----------|-------------|----------------|--------|
| 14.4× | 1 hour | Critical | Page on-call, freeze deployments |
| 6× | 6 hours | Critical | Page on-call |
| 3× | 24 hours | Warning | Investigate, notify team |
| 1× | 30 days | Warning | Team review in sprint planning |

**PromQL for burn rate detection:**

```promql
# Burn rate = error_rate / error_budget
# Critical: burn rate > 14.4x over 1 hour
(
  sum(rate(rag_requests_total{status=~"5.."}[1h]))
  / sum(rate(rag_requests_total[1h]))
) / 0.005 > 14.4

# Warning: burn rate > 3x over 24 hours
(
  sum(rate(rag_requests_total{status=~"5.."}[24h]))
  / sum(rate(rag_requests_total[24h]))
) / 0.005 > 3
```

### 10.4 SLO Dashboards

**Key panels for the SLO dashboard:**

```promql
# 1. Current SLO compliance (gauge)
1 - (
  sum(rate(rag_requests_total{status=~"5.."}[30d]))
  / sum(rate(rag_requests_total[30d]))
)

# 2. Error budget remaining (gauge)
1 - (
  sum(rate(rag_requests_total{status=~"5.."}[30d]))
  / sum(rate(rag_requests_total[30d]))
) / 0.005

# 3. Multi-window burn rate (heat map)
# 1h window burn rate:
(
  sum(rate(rag_requests_total{status=~"5.."}[1h]))
  / sum(rate(rag_requests_total[1h]))
) / 0.005

# 4. Error budget consumption velocity
# Change in error budget over last 24h:
delta(
  (1 - sum(rate(rag_requests_total{status=~"5.."}[30d])) / sum(rate(rag_requests_total[30d])) / 0.005)
  [24h]
)
```

### 10.5 Operational Response to Budget Exhaustion

1. **Error budget > 50% consumed in month**: Notify engineering manager. Begin reliability-focused sprint.
2. **Error budget > 80% consumed**: Freeze all feature deployments. Only reliability fixes allowed.
3. **Error budget exhausted**: Incident declared. All hands on recovery. Post-mortem required.

**Enforce deployment freeze:**

```bash
# Gate in CI/CD pipeline (example):
ERROR_BUDGET_REMAINING=$(curl -s http://grafana:3000/api/datasources/proxy/1/api/v1/query \
  --data-urlencode 'query=(1 - sum(rate(rag_requests_total{status=~"5.."}[30d])) / sum(rate(rag_requests_total[30d]))) / 0.005' \
  | jq -r '.data.result[0].value[1]')

if (( $(echo "$ERROR_BUDGET_REMAINING < 20" | bc -l) )); then
  echo "ERROR: Error budget below 20%. Deployment blocked."
  exit 1
fi
```

---

## Appendix A: Port Reference

| Port | Service | Protocol | External? |
|------|---------|----------|-----------|
| 80, 443 | nginx Ingress | HTTP/HTTPS | Yes |
| 3000 | Grafana | HTTP | Internal (VPN) |
| 5000 | MLflow | HTTP | Internal |
| 6333 | Qdrant HTTP | HTTP/JSON | Internal |
| 6334 | Qdrant gRPC | gRPC | Internal |
| 6379 | Redis | TCP | Internal |
| 7474 | Neo4j Browser | HTTP | Internal |
| 7687 | Neo4j Bolt | TCP | Internal |
| 8000 | vLLM/llama.cpp | HTTP | Internal |
| 8080 | RAG Proxy | HTTP | External (via ingress) |
| 8081 | Federation Proxy | HTTP | Internal |
| 8082 | MCP Server | HTTP/STDIO | Internal |
| 8501 | HITL Dashboard | HTTP | Internal |
| 9000 | MinIO S3 API | HTTP | Internal |
| 9001 | MinIO Console | HTTP | Internal |

## Appendix B: Environment Variable Quick Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `QDRANT_HOST` | `localhost` | Qdrant server hostname |
| `QDRANT_PORT` | `6333` | Qdrant HTTP port |
| `LLM_ENDPOINT` | `http://localhost:8000/v1` | LLM backend URL |
| `LLM_MODEL_NAME` | — | Model identifier (Required) |
| `LLM_API_KEY` | — | Backend API key |
| `LLM_PROVIDER_TYPE` | `openai` | `openai`, `anthropic`, `generic` |
| `EMBEDDER_MODEL` | — | Embedder model path/name |
| `RERANKER_MODEL` | — | Reranker model path/name |
| `USE_REDIS` | `false` | Enable Redis cache |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `USE_LANGGRAPH` | `false` | Enable LangGraph orchestration |
| `GRAPH_ENABLED` | `false` | Enable Neo4j |
| `METRICS_ENABLED` | `true` | Enable Prometheus metrics |
| `LOG_FORMAT` | `text` | `text` or `json` |
| `RATE_LIMIT_ENABLED` | `false` | Enable rate limiting |
| `AUTH_ENABLED` | `false` | Enable JWT authentication |
| `RBAC_ENABLED` | `false` | Enable role-based access control |
| `WORKERS` | `1` | Uvicorn workers (keep at 1) |
| `SHUTDOWN_TIMEOUT` | `30` | Graceful shutdown wait (seconds) |
| `COMPRESSION_ENABLED` | `true` | Enable gzip response compression |
| `WARMUP_ENABLED` | `true` | Enable model warm-up on startup |

## Appendix C: Related Documents

- [Operational Scripts (Backup/Restore)](https://github.com/AlexanderNarbaev/rag-system/blob/main/scripts/ops/README.md)
- [Kubernetes Deployment (Helm)](https://github.com/AlexanderNarbaev/rag-system/blob/main/deploy/k8s/README.md)
- [SLI/SLO Definitions](../sli_slo.md)
- [Disaster Recovery Runbook](disaster-recovery-runbook.md)
- [Deployment Guide](deployment-guide.md)
- [Performance & Quality Best Practices](performance-quality.md)
- [Troubleshooting Guide](troubleshooting.md)

> **Note:** This guide is also available in Russian via the language switcher in the top navigation.
