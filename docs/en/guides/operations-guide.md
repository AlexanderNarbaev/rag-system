# Operations & Maintenance Guide

## Monitoring

### Prometheus Metrics Reference

The proxy exposes metrics at `/metrics` in OpenMetrics format. Key metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `rag_requests_total` | Counter | Total API requests by endpoint |
| `rag_request_duration_seconds` | Histogram | Request latency (p50/p95/p99) |
| `rag_retrieval_chunks` | Histogram | Chunks retrieved per query |
| `rag_rerank_duration_seconds` | Histogram | Reranker latency |
| `rag_llm_duration_seconds` | Histogram | LLM generation latency |
| `rag_llm_tokens_total` | Counter | Tokens used (prompt + completion) |
| `rag_cache_hit_ratio` | Gauge | Redis cache hit ratio |
| `rag_errors_total` | Counter | Error count by type |

### Key Alerts

```yaml
# Prometheus alert rules (prometheus-alerts.yml)
groups:
  - name: rag-system
    rules:
      - alert: HighErrorRate
        expr: rate(rag_errors_total[5m]) > 0.05
        annotations:
          summary: "RAG error rate >5% in 5-minute window"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 10
        annotations:
          summary: "p95 latency >10s"

      - alert: LLMDown
        expr: rag_llm_duration_seconds == 0 for 2m
        annotations:
          summary: "LLM not responding"

      - alert: LowCacheHitRate
        expr: rag_cache_hit_ratio < 0.3
        annotations:
          summary: "Cache hit ratio below 30%"

      - alert: DiskNearFull
        expr: node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes < 0.15
        annotations:
          summary: "Disk <15% free"
```

### Docker Healthchecks

```yaml
# Add to docker-compose.yml services:
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/v1/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

## Backup & Restore

### Qdrant Snapshots

```bash
# Create snapshot:
curl -X POST http://localhost:6333/collections/knowledge_base/snapshots

# List snapshots:
curl http://localhost:6333/collections/knowledge_base/snapshots

# Download snapshot:
curl http://localhost:6333/collections/knowledge_base/snapshots/<snapshot_name> \
  -o qdrant_backup.snapshot

# Restore (on target Qdrant instance):
curl -X PUT http://localhost:6333/collections/knowledge_base/snapshots/upload \
  -F "snapshot=@qdrant_backup.snapshot"

# Automated daily backup cron:
0 2 * * * curl -X POST http://localhost:6333/collections/knowledge_base/snapshots
```

### Neo4j Dumps

```bash
# Dump database:
docker exec rag-neo4j neo4j-admin database dump neo4j --to-path=/backups/
docker cp rag-neo4j:/backups/neo4j.dump ./neo4j_backup_$(date +%Y%m%d).dump

# Restore:
docker exec rag-neo4j neo4j-admin database load neo4j \
  --from-path=/backups/ --overwrite-destination=true
```

### WAL Backup

```bash
# The ETL WAL files are critical for incremental updates:
cp etl/wal/etl_wal.json ./backups/wal_$(date +%Y%m%d_%H%M%S).json
cp etl/wal/version_wal.json ./backups/version_wal_$(date +%Y%m%d_%H%M%S).json

# WAL corruption recovery: delete corrupted WAL and run full reindex
rm etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

### Backup Retention Policy

| Type | Daily | Weekly | Monthly |
|------|-------|--------|---------|
| Qdrant snapshot | 7 kept | 4 kept | 3 kept |
| Neo4j dump | 7 kept | 4 kept | 3 kept |
| WAL files | 14 kept | — | — |

## Scaling

### Horizontal Proxy Scaling

```yaml
# docker-compose.yml — add replicas and load balancer:
rag-proxy:
  deploy:
    replicas: 3
  environment:
    - WORKERS=2  # uvicorn workers per replica

# Add nginx load balancer:
nginx:
  image: nginx:alpine
  ports:
    - "8080:8080"
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
```

```nginx
# nginx.conf — round-robin across replicas:
upstream rag_backend {
    server rag-proxy-1:8080;
    server rag-proxy-2:8080;
    server rag-proxy-3:8080;
}
server {
    listen 8080;
    location / {
        proxy_pass http://rag_backend;
        proxy_read_timeout 120s;
    }
}
```

### Qdrant Sharding

```bash
# Create sharded collection at init time:
# In scripts/init_collections.py or via API:
curl -X PUT http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{
    "vectors": {"size": 1024, "distance": "Cosine"},
    "shard_number": 3,
    "replication_factor": 2
  }'
```

### Redis Clustering

For cache scaling beyond single-node capacity:
```bash
# Start Redis in cluster mode (3 master + 3 replica nodes)
redis-cli --cluster create \
  redis-1:6379 redis-2:6379 redis-3:6379 \
  redis-4:6379 redis-5:6379 redis-6:6379 \
  --cluster-replicas 1
```

## Upgrades

### Version Compatibility Matrix

| Component | Compatible Versions | Upgrade Path |
|-----------|---------------------|-------------|
| Qdrant | 1.7.x → 1.10.x | Rolling restart |
| Neo4j | 5.x → 5.x | Database migration script |
| Redis | 6.x → 7.x | AOF compatibility check |
| vLLM | 0.4.x → 0.6.x | Model re-download may be needed |
| Python | 3.11 → 3.12 | requirements reinstall |

### Migration Steps

```bash
# 1. Stop services:
docker-compose down

# 2. Backup everything (see Backup section above)

# 3. Pull new images or build from updated Dockerfiles:
docker-compose build --no-cache rag-proxy

# 4. Run collection migration if schema changed:
python scripts/init_collections.py  # with updated schema

# 5. Start with new version:
docker-compose up -d

# 6. Verify:
curl http://localhost:8080/v1/health

# 7. If issues, rollback:
docker-compose down
docker-compose -f docker-compose.yml.bak up -d
```

## Disaster Recovery

| Target | RPO | RTO |
|--------|-----|-----|
| Qdrant vectors | 24 hours | 2 hours |
| Neo4j graph | 24 hours | 1 hour |
| WAL state | 1 hour | 30 minutes |
| Proxy configuration | Immediate (git) | 15 minutes |

### Recovery Procedures

**Scenario: Full data loss**
```bash
# 1. Deploy clean infrastructure:
docker-compose up -d qdrant neo4j redis

# 2. Restore latest Qdrant snapshot:
curl -X PUT http://localhost:6333/collections/knowledge_base/snapshots/upload \
  -F "snapshot=@latest_qdrant.snapshot"

# 3. Restore Neo4j dump:
docker cp latest_neo4j.dump rag-neo4j:/backups/
docker exec rag-neo4j neo4j-admin database load neo4j --from-path=/backups/ --overwrite=true

# 4. Restore WAL files, run incremental ETL:
cp backups/latest_wal.json etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --incremental

# 5. Start proxy:
docker-compose up -d rag-proxy
curl http://localhost:8080/v1/health
```

**Scenario: ETL corrupted midway**
```bash
# Delete checkpoint and re-run:
rm etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

## Performance Tuning

### HNSW Parameters (Qdrant)

```json
{
  "hnsw_config": {
    "m": 32,           // more edges = higher recall, more RAM (default: 16)
    "ef_construct": 200, // higher = better index quality (default: 100)
    "ef": 128           // higher = better recall at query time (default: 128)
  },
  "optimizers_config": {
    "indexing_threshold": 20000  // build HNSW after this many points
  }
}
```

### Cache Sizing

```ini
# proxy/.env — tune based on workload:
MAX_CHUNKS_RETRIEVAL=50       # reduce if memory-constrained
MAX_CHUNKS_AFTER_RERANK=10    # fewer chunks = faster LLM call

# Redis maxmemory (in docker-compose.yml):
redis:
  command: redis-server --appendonly yes --maxmemory 2gb --maxmemory-policy allkeys-lru
```

### Batch Sizes

```yaml
# etl/config/etl_config.yaml:
indexing:
  batch_size: 100     # 50-200 range; lower if OOM, higher for throughput

# proxy/.env:
RERANKER_BATCH_SIZE=16  # 8-32 range; lower reduces memory spikes
```

### LLM Tuning

```yaml
# vLLM command in docker-compose.yml:
--max-model-len 65536       # balance context vs VRAM
--gpu-memory-utilization 0.90  # leave headroom
--max-num-seqs 16           # concurrent requests
```

## Cold Storage Cleanup

### Automatic Version Pruning

The cold storage directory (`COLD_DIR` in ETL config) accumulates Parquet files for each document version. To prevent unbounded growth, enable TTL-based cleanup:

```bash
# In proxy/.env or ETL config
COLD_STORAGE_ENABLED=true
COLD_STORAGE_MAX_VERSIONS=5   # Keep latest 5 versions per document
```

The cleanup process:
1. Scans cold storage for `*.parquet` files matching pattern `<doc_name>_v<N>.parquet`
2. Groups files by document name
3. Sorts by version number (descending)
4. Deletes all files beyond `COLD_STORAGE_MAX_VERSIONS`

**Manual trigger:**
```bash
python etl/scheduler/cold_storage_cleanup.py --cold-dir /data/cold_chunks --max-versions 3
```

**Cron integration:**
```cron
0 3 * * 0 cd /opt/rag-system && python etl/scheduler/cold_storage_cleanup.py
```

---

## Model Warm-Up

### Startup Latency Optimization

On first request after deployment, models are loaded into memory (GPU/CPU), causing high latency. Pre-warm models at startup:

```bash
# Pre-warm all models
curl -X POST http://localhost:8080/v1/health/ready

# Pre-warm with a dummy query
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"warmup","messages":[{"role":"user","content":"ping"}]}'
```

**Docker Compose healthcheck with warm-up:**
```yaml
services:
  proxy:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/v1/health/live"]
      interval: 30s
      retries: 3
      start_period: 120s  # Allow time for model loading
```

### Log Rotation

```yaml
# logrotate config (/etc/logrotate.d/rag-system):
/opt/rag-system/proxy/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

### Docker Log Driver

```yaml
# docker-compose.yml — limit container logs:
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

### Log Aggregation

```bash
# Forward to Loki/Grafana via promtail:
# promtail config scrape target:
scrape_configs:
  - job_name: rag-system
    static_configs:
      - targets: [localhost]
        labels:
          job: rag-proxy
          __path__: /opt/rag-system/proxy/logs/*.log
```

### Retention Policy

| Log Type | Retention | Storage |
|----------|-----------|---------|
| Proxy request logs | 7 days | Local disk + Loki |
| vLLM logs | 3 days | Local + Loki |
| ETL run logs | 30 days | Local disk |
| HITL feedback logs | 90 days | Database |
| Docker container logs | 3 rotations of 100 MB | Local |

---

## Streaming ETL Monitoring

### Redis Streams Consumer Lag

Monitor streaming ETL health via Redis Streams metrics:

```bash
# Check consumer group status:
docker exec rag-redis redis-cli XINFO GROUPS etl:events

# Check pending messages per consumer:
docker exec rag-redis redis-cli XPENDING etl:events etl-extract
docker exec rag-redis redis-cli XPENDING etl:events etl-chunk
docker exec rag-redis redis-cli XPENDING etl:events etl-embed
docker exec rag-redis redis-cli XPENDING etl:events etl-index

# Consumer lag alert threshold:
# - Pending > 100: warning (bottleneck detected)
# - Pending > 1000: critical (consumer may be stuck)
# - Idle time > 5 min: consumer likely crashed
```

### Dead Letter Queue Monitoring

```bash
# Check DLQ size:
docker exec rag-redis redis-cli XLEN etl:events:dlq

# Inspect failed events:
docker exec rag-redis redis-cli XRANGE etl:events:dlq - + COUNT 10

# Reprocess DLQ events:
python etl/scheduler/reprocess_dlq.py --stream etl:events:dlq
```

### Streaming ETL Prometheus Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `rag_etl_stream_events_total` | Counter | Total events processed by streaming ETL |
| `rag_etl_stream_lag` | Gauge | Pending messages per consumer group |
| `rag_etl_stream_dlq_size` | Gauge | Dead letter queue size |
| `rag_etl_stream_processing_duration_seconds` | Histogram | Per-event processing time by stage |

### Alert Rules for Streaming ETL

```yaml
- alert: StreamConsumerLag
  expr: rag_etl_stream_lag > 100
  for: 5m
  annotations:
    summary: "Streaming ETL consumer lag > 100 messages"

- alert: StreamDLQGrowing
  expr: rate(rag_etl_stream_dlq_size[5m]) > 0
  for: 10m
  annotations:
    summary: "Dead letter queue is growing"

- alert: StreamConsumerStuck
  expr: rag_etl_stream_lag > 1000
  for: 2m
  annotations:
    summary: "Streaming ETL consumer may be stuck (> 1000 pending)"
```

---

## Model Warm-Up Procedure

### After Model Update

When a new model is deployed (LLM, embedder, or reranker), run warm-up before routing traffic:

```bash
# 1. Deploy new model backend (vLLM/llama.cpp)
docker-compose up -d llm-backend

# 2. Wait for model to load:
until curl -sf http://localhost:8000/health; do sleep 2; done

# 3. Trigger warm-up:
curl -X POST http://localhost:8080/v1/admin/warmup

# 4. Verify warm-up completed:
curl -s http://localhost:8080/v1/health | jq '.components'

# 5. Confirm first-request latency is normal:
time curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-proxy","messages":[{"role":"user","content":"ping"}],"max_tokens":10}'
```

### Warm-Up Automation (Systemd)

```ini
# /etc/systemd/system/rag-warmup.service
[Unit]
Description=RAG Proxy Model Warm-Up
After=docker-compose.service
Requires=docker-compose.service

[Service]
Type=oneshot
ExecStart=/usr/bin/curl -sf -X POST http://localhost:8080/v1/admin/warmup
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Warm-Up Monitoring

```bash
# Check warm-up status via Prometheus:
curl -s http://localhost:8080/metrics | grep rag_warmup_completed

# Expected: rag_warmup_completed 1 (warm-up done)
# If 0: warm-up not yet completed or failed
```

---

## Compression Performance Benchmarks

### Benchmark Results (v0.6)

Measured on a production workload of 10,000 chat completion requests:

| Compression | Avg Response Size | Reduction | CPU Overhead (p95) | Network Savings |
|------------|-------------------|-----------|---------------------|-----------------|
| None | 45.2 KB | — | 0ms | 0% |
| gzip (level 6) | 12.8 KB | 71.7% | 3.2ms | 32.4 MB per 1000 requests |
| brotli (level 4) | 11.3 KB | 75.0% | 11.8ms | 33.9 MB per 1000 requests |

### When to Use Brotli vs Gzip

| Scenario | Recommendation |
|----------|---------------|
| Internal network (LAN) | gzip — lower CPU, compression difference negligible |
| External/WAN clients | brotli — higher compression ratio worth the CPU cost |
| High-throughput (>100 req/s) | gzip — CPU overhead becomes significant at scale |
| Mobile/low-bandwidth clients | brotli — maximum compression for limited connections |

### Compression Tuning

```bash
# Fast compression (lower ratio, lower CPU):
COMPRESSION_LEVEL=1  # gzip: 58% reduction, <1ms CPU

# Balanced (default):
COMPRESSION_LEVEL=6  # gzip: 72% reduction, ~3ms CPU

# Maximum compression (highest ratio, highest CPU):
COMPRESSION_LEVEL=9  # gzip: 76% reduction, ~15ms CPU
```

---

## Cold Storage Cleanup
