# Monitoring Configuration

Prometheus + Grafana monitoring stack for the RAG System.

## Directory Structure

```
config/monitoring/
├── grafana/
│   ├── dashboards/
│   │   ├── dashboards.yaml              # Dashboard provisioning provider config
│   │   ├── rag-overview.json            # Traffic, latency, errors, cache, tokens
│   │   ├── rag-infrastructure.json      # Qdrant, Neo4j, Redis health
│   │   └── rag-retrieval-quality.json   # Retrieval MRR, confidence, grounding
│   └── datasources/
│       └── prometheus.yaml              # Grafana datasource provisioning
└── prometheus/
    ├── prometheus.yml                   # Scrape targets and intervals
    └── alert_rules.yml                  # Alert rules (critical/warning/info)
```

## Quick Start

### Option A: Standalone monitoring stack

Run the monitoring stack independently from the RAG proxy:

```bash
cd config/monitoring
docker compose -f docker-compose.monitoring.yml up -d
```

This starts Prometheus (port 9090), Grafana (port 3000), Redis exporter, and
Neo4j exporter. The proxy must be running separately and reachable on the
Docker network.

### Option B: Add to existing proxy compose

Uncomment the monitoring services in `proxy/docker-compose.yml` and restart:

```bash
cd proxy
docker compose up -d
```

## Setting Up Prometheus

Prometheus scrapes the proxy's `/metrics` endpoint. The configuration is in
`prometheus/prometheus.yml`.

### Scrape Targets

| Job | Target | Interval | Description |
|-----|--------|----------|-------------|
| `rag-proxy` | `rag-proxy:8080` | 15s | RAG proxy metrics |
| `qdrant` | `rag-qdrant:6333` | 30s | Qdrant vector DB metrics |
| `redis-exporter` | `redis-exporter:9121` | 30s | Redis metrics via exporter |
| `neo4j` | `neo4j-exporter:2004` | 30s | Neo4j graph DB metrics |
| `prometheus` | `localhost:9090` | 30s | Prometheus self-monitoring |

### Bare-Metal Deployment

If running Prometheus outside Docker, update targets to `localhost`:

```yaml
scrape_configs:
  - job_name: "rag-proxy"
    static_configs:
      - targets: ["localhost:8080"]
```

## Setting Up Grafana Dashboards

### Automatic Provisioning (recommended)

When using the provided Docker Compose file, dashboards are auto-provisioned
from `grafana/dashboards/` via the volume mount. No manual import needed.

### Manual Import

1. Open Grafana at `http://localhost:3000` (default: `admin` / `admin`)
2. Navigate to **Dashboards > Import**
3. Upload each JSON file from `grafana/dashboards/`
4. Select the **Prometheus** datasource when prompted

### Available Dashboards

#### RAG Overview (`rag-overview-v1`)

| Panel | Metric | Description |
|-------|--------|-------------|
| Request Rate (RPS) | `rag_requests_total` | Requests/sec by status code |
| Latency (p50/p95/p99) | `rag_request_duration_seconds_bucket` | End-to-end request latency |
| Error Rate (5xx %) | `rag_requests_total{status=~"5.."}` | 5xx error ratio |
| Cache Hit Ratio | `rag_cache_hits_total` | Cache effectiveness |
| Active Requests | `rag_active_requests` | Concurrent request count |
| Context Tokens | `rag_context_tokens` | Tokens passed to LLM |
| LLM Latency | `rag_llm_duration_seconds_bucket` | LLM call duration |
| Retrieval Latency | `rag_retrieval_duration_seconds_bucket` | Vector search duration |
| Reranker Latency | `rag_rerank_duration_seconds_bucket` | Reranking duration |

#### RAG Infrastructure (`rag-infrastructure-v1`)

| Panel | Metric Source | Description |
|-------|--------------|-------------|
| Qdrant Collection Count | Qdrant `/metrics` | Number of collections |
| Qdrant Indexed Vectors | Qdrant `/metrics` | Total indexed vectors |
| Qdrant Disk Usage | Qdrant `/metrics` | Storage consumption |
| Neo4j Nodes/Relations | Neo4j exporter | Graph database size |
| Neo4j Disk Usage | Neo4j exporter | Graph storage size |
| Neo4j Status | `up{job="neo4j"}` | Uptime indicator |
| Redis Memory | Redis exporter | Used vs max memory |
| Redis Cache Hit Rate | Redis exporter | Keyspace hit ratio |
| Redis Clients | Redis exporter | Connected clients |
| Redis Operations | Redis exporter | Commands/sec |

#### RAG Retrieval Quality (`rag-retrieval-quality-v1`)

| Panel | Metric | Description |
|-------|--------|-------------|
| Chunks Retrieved | `rag_retrieval_chunks_total` | Chunks before/after rerank |
| Reranker Latency | `rag_rerank_duration_seconds_bucket` | Reranking p50/p95/p99 |
| Graph Expansion Rate | `rag_graph_expansion_rate` | % queries using graph expansion |
| Retrieval MRR | `rag_retrieval_mrr` | Mean Reciprocal Rank |
| Confidence Score | `rag_confidence_score_high_ratio` | % answers with confidence > 0.5 |
| Grounding Score | `rag_grounding_score_high_ratio` | % answers grounded in sources |
| Token Usage | `rag_context_tokens`, `rag_compression_ratio` | Token economy tracking |

## Alert Rules

Alerts are defined in `prometheus/alert_rules.yml` with three severity levels:

### Critical (P1) — immediate action required

| Alert | Condition | Description |
|-------|-----------|-------------|
| `HighErrorRate` | 5xx rate > 1% for 5m | Elevated error rate |
| `HighLatency` | p95 > 10s for 5m | SLO breach |
| `ServiceDown` | proxy unreachable for 1m | Proxy is down |
| `QdrantUnavailable` | Qdrant unreachable for 2m | Vector store down |
| `LLMTimeout` | >5% LLM calls > 60s for 5m | LLM backend overloaded |

### Warning (P2) — investigate within 30 minutes

| Alert | Condition | Description |
|-------|-----------|-------------|
| `LowCacheHitRate` | < 50% for 15m | Cache underperforming |
| `HighMemoryUsage` | > 80% for 10m | System memory pressure |
| `HighDiskUsage` | > 85% for 5m | Disk space low |
| `LowConfidenceRate` | > 30% low-confidence for 15m | Answer quality degraded |
| `SlowReranking` | p95 > 1s for 10m | Reranker bottleneck |
| `HighTokenUsage` | > 8000 tokens for 10m | Token budget exceeded |
| `Neo4jUnavailable` | Neo4j down for 10m | Graph expansion disabled |
| `RedisUnavailable` | Redis down for 5m | Fallback to in-memory cache |

### Info (P3) — informational, no immediate action

| Alert | Condition | Description |
|-------|-----------|-------------|
| `NoRecentRequests` | 0 RPS for 30m | Possible traffic drop |
| `ColdStorageNearLimit` | versions >= 5 | Approaching version limit |
| `BackupMissed` | last backup > 2h ago | Backup schedule drift |
| `HighActiveRequests` | > 50 for 5m | Load spike |
| `QdrantHighDiskUsage` | > 50 GB for 10m | Storage growth |
| `RedisHighMemory` | > 85% max for 10m | Redis memory pressure |
| `LLMRequestBacklog` | > 10 active for 10m | Sustained load |
| `QdrantVectorGrowth` | > 10k vectors/hour for 1h | High ingestion rate |

## Metrics Reference

All proxy metrics are defined in `proxy/app/shared/metrics.py` and exposed at
`/metrics` in Prometheus text format.

### Proxy Metrics (from `metrics.py`)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rag_requests_total` | Counter | `endpoint`, `status` | Total requests by endpoint and HTTP status |
| `rag_request_duration_seconds` | Histogram | `endpoint` | End-to-end request duration |
| `rag_retrieval_duration_seconds` | Histogram | — | Vector search step duration |
| `rag_rerank_duration_seconds` | Histogram | — | Reranking step duration |
| `rag_llm_duration_seconds` | Histogram | — | LLM inference duration |
| `rag_cache_hits_total` | Counter | — | Cache hit count |
| `rag_context_tokens` | Gauge | — | Current context token count |
| `rag_active_requests` | Gauge | — | Currently in-flight requests |

### Dashboard Metrics Not Yet Implemented

The Grafana dashboards are templates that reference some metrics not yet
exported by `proxy/app/shared/metrics.py`. These need to be added when the
corresponding features are instrumented:

| Metric | Used In | Required Feature |
|--------|---------|-----------------|
| `rag_retrieval_chunks_total` | Retrieval Quality | Chunk count tracking |
| `rag_retrieval_chunks_after_rerank` | Retrieval Quality | Post-rerank chunk tracking |
| `rag_graph_expansion_rate` | Retrieval Quality | Graph expansion instrumentation |
| `rag_retrieval_mrr` | Retrieval Quality | Retrieval evaluation pipeline |
| `rag_confidence_score_high_ratio` | Retrieval Quality | Confidence scoring aggregation |
| `rag_grounding_score_high_ratio` | Retrieval Quality | Grounding score aggregation |
| `rag_compression_ratio` | Retrieval Quality | Token optimizer compression tracking |
| `rag_confidence_low_ratio` | Alert rules | Confidence scoring aggregation |
| `rag_cold_storage_versions` | Alert rules | Version management tracking |
| `rag_last_backup_timestamp_seconds` | Alert rules | Backup monitoring |

### External Metrics (from exporters)

| Source | Exporter | Default Port |
|--------|----------|-------------|
| Qdrant | Built-in `/metrics` | 6333 |
| Redis | [redis\_exporter](https://github.com/oliver006/redis_exporter) | 9121 |
| Neo4j | [neo4j-prometheus-exporter](https://github.com/neo4j-contrib/neo4j-prometheus-exporter) | 2004 |

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAFANA_ADMIN_USER` | `admin` | Grafana admin username |
| `GRAFANA_ADMIN_PASSWORD` | `admin` | Grafana admin password |
| `PROMETHEUS_RETENTION` | `30d` | Prometheus data retention |

### Ports

| Service | Port | Description |
|---------|------|-------------|
| Prometheus | 9090 | Prometheus UI and API |
| Grafana | 3000 | Grafana dashboards |
| Redis Exporter | 9121 | Redis metrics endpoint |
| Neo4j Exporter | 2004 | Neo4j metrics endpoint |
