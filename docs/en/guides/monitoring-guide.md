# Monitoring & Observability Guide

This guide covers the observability strategy for the RAG System, including Prometheus metrics, health checks, structured logging, distributed tracing, and alerting.

## Table of Contents

1. [Overview](#overview)
2. [Prometheus Metrics](#prometheus-metrics)
3. [Grafana Dashboards](#grafana-dashboards)
4. [Health Checks](#health-checks)
5. [Logging](#logging)
6. [Tracing](#tracing)
7. [Alerting](#alerting)
8. [Troubleshooting](#troubleshooting)

---

## Overview

The RAG System provides full observability through three pillars:

| Pillar | Technology | Endpoint |
|--------|-----------|----------|
| **Metrics** | Prometheus | `/metrics` |
| **Logging** | Structured JSON/text | stdout / JSONL files |
| **Tracing** | OpenTelemetry (OTLP) | OTLP HTTP collector |

### Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  RAG Proxy  │────▶│  Prometheus  │────▶│   Grafana   │
│  /metrics   │     │   Scraper    │     │  Dashboards │
└──────┬──────┘     └──────────────┘     └─────────────┘
       │
       ├──── stdout (JSON/text logs) ────▶ Loki / ELK
       │
       └──── OTLP HTTP ────────────────▶ Tempo / Jaeger
```

### Configuration

```bash
METRICS_ENABLED=true              # Enable Prometheus metrics (default: true)
LOG_FORMAT=json                   # "json" for structured, "text" for console
OTEL_ENABLED=false                # Enable OpenTelemetry tracing
OTEL_EXPORTER_ENDPOINT=http://localhost:4318/v1/traces
OTEL_SERVICE_NAME=rag-proxy
```

---

## Prometheus Metrics

### Scraping Endpoint

```
GET /metrics
```

Returns Prometheus-formatted metrics in plain text. No authentication required (listed as a public endpoint).

### Available Metrics

#### Counters

| Metric | Labels | Description |
|--------|--------|-------------|
| `rag_requests_total` | `endpoint`, `status` | Total number of RAG requests |
| `rag_cache_hits_total` | — | Total number of cache hits |

#### Histograms

| Metric | Labels | Buckets (seconds) | Description |
|--------|--------|-------------------|-------------|
| `rag_request_duration_seconds` | `endpoint` | 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0 | Request duration |
| `rag_retrieval_duration_seconds` | — | 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0 | Retrieval step duration |
| `rag_rerank_duration_seconds` | — | 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0 | Rerank step duration |
| `rag_llm_duration_seconds` | — | 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0 | LLM call duration |

#### Gauges

| Metric | Description |
|--------|-------------|
| `rag_context_tokens` | Number of context tokens passed to LLM |
| `rag_active_requests` | Number of currently active requests |

### Example Queries

```promql
# Request rate per second
rate(rag_requests_total[5m])

# P95 request duration
histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m]))

# Cache hit ratio
rate(rag_cache_hits_total[5m]) / rate(rag_requests_total[5m])

# Average retrieval duration
rate(rag_retrieval_duration_seconds_sum[5m]) / rate(rag_retrieval_duration_seconds_count[5m])

# Active requests
rag_active_requests

# Error rate by endpoint
rate(rag_requests_total{status=~"5.."}[5m])
```

### Source File

All metrics are defined in `proxy/app/shared/metrics.py`:

```python
from proxy.app.shared.metrics import (
    rag_requests_total,
    rag_request_duration_seconds,
    rag_retrieval_duration_seconds,
    rag_rerank_duration_seconds,
    rag_llm_duration_seconds,
    rag_cache_hits_total,
    rag_context_tokens,
    rag_active_requests,
    metrics_endpoint,
)
```

---

## Grafana Dashboards

### Recommended Dashboard Panels

#### Request Overview

- **Request Rate**: `rate(rag_requests_total[5m])` — time series
- **Request Duration P50/P95/P99**: `histogram_quantile(0.95, ...)` — time series
- **Active Requests**: `rag_active_requests` — gauge
- **Error Rate**: `rate(rag_requests_total{status=~"5.."}[5m])` — time series

#### Retrieval Performance

- **Retrieval Duration**: `rag_retrieval_duration_seconds` — heatmap
- **Rerank Duration**: `rag_rerank_duration_seconds` — heatmap
- **LLM Duration**: `rag_llm_duration_seconds` — heatmap

#### Cache & Efficiency

- **Cache Hit Ratio**: computed from `rag_cache_hits_total` / `rag_requests_total`
- **Context Tokens**: `rag_context_tokens` — gauge over time

### Dashboard JSON

Pre-built Grafana dashboard JSON can be generated from the metrics definitions. Import into Grafana via **Dashboards → Import → Upload JSON**.

---

## Health Checks

### Endpoints

| Endpoint | Method | Purpose | Kubernetes |
|----------|--------|---------|------------|
| `/v1/health` | GET | General health status | — |
| `/v1/health/live` | GET | Liveness probe | `livenessProbe` |
| `/v1/health/ready` | GET | Readiness probe (Qdrant + LLM connectivity) | `readinessProbe` |

### Liveness Probe

```yaml
livenessProbe:
  httpGet:
    path: /v1/health/live
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 15
  timeoutSeconds: 5
  failureThreshold: 3
```

### Readiness Probe

```yaml
readinessProbe:
  httpGet:
    path: /v1/health/ready
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 10
  failureThreshold: 3
```

### Health Response Format

```json
{
  "status": "healthy",
  "components": {
    "qdrant": "connected",
    "llm": "connected",
    "redis": "connected",
    "neo4j": "connected"
  },
  "version": "1.0.0",
  "uptime_seconds": 3600
}
```

---

## Logging

### Configuration

```bash
LOG_FORMAT=text     # "text" for human-readable console output
LOG_FORMAT=json     # "json" for structured machine-parseable logs
LOG_DIR=./logs      # Directory for log files
LOG_REQUESTS=true   # Log every request (method, path, status, duration)
```

### Log Formats

#### Text Format (development)

```
2024-01-15 10:30:00 [rag-proxy] [INFO] [abc-123] POST /v1/chat/completions 200 1234.56ms
```

#### JSON Format (production)

```json
{
  "timestamp": "2024-01-15T10:30:00+00:00",
  "level": "INFO",
  "logger": "rag-proxy.middleware",
  "message": "POST /v1/chat/completions 200 1234.56ms",
  "module": "middleware",
  "function": "dispatch",
  "line": 49,
  "request_id": "abc-123"
}
```

### Request ID Propagation

Every request gets a unique `X-Request-ID` (UUID v4) injected by the `RequestIdMiddleware`. If the client provides one, it is preserved. The ID is:

1. Added to `request.state.request_id`
2. Injected into all log records for that request
3. Returned in the response header `X-Request-ID`

### Correlation ID

The `CorrelationIdMiddleware` propagates `X-Correlation-ID` across services for distributed tracing. If absent, a new UUID is generated.

### Sensitive Data Masking

The logging module automatically masks:
- API keys (`api_key=...`, `API_KEY=...`)
- Bearer tokens (`Authorization: Bearer ...`)
- Passwords (`password=...`)
- Secrets (`secret=...`)
- Tokens (`token=...`)

### Log Levels

| Level | Usage |
|-------|-------|
| `DEBUG` | Detailed diagnostic information |
| `INFO` | Normal operation events (requests, health checks) |
| `WARNING` | Degraded operation (fallback activated, timeout) |
| `ERROR` | Operation failures (LLM timeout, retrieval error) |
| `CRITICAL` | System-level failures (startup crash, data corruption) |

---

## Tracing

### OpenTelemetry Integration

When `OTEL_ENABLED=true`, the proxy exports distributed traces via OTLP HTTP.

#### Configuration

```bash
OTEL_ENABLED=true                                    # Enable tracing
OTEL_EXPORTER_ENDPOINT=http://localhost:4318/v1/traces  # OTLP collector
OTEL_SERVICE_NAME=rag-proxy                          # Service name in traces
OTEL_BATCH_TIMEOUT=5                                 # Batch export interval (seconds)
OTEL_MAX_ATTRIBUTES_PER_SPAN=128                     # Max attributes per span
```

#### Usage in Code

```python
from proxy.app.shared.tracing import tracer, add_event, set_span_error

with tracer.start_as_current_span("rag.retrieve") as span:
    span.set_attribute("rag.query", query)
    results = hybrid_search(query)
    span.set_attribute("rag.num_results", len(results))
    add_event("retrieval.complete", {"chunks": len(results)})
```

#### Utility Functions

| Function | Description |
|----------|-------------|
| `tracer` | Module-level tracer instance (no-op when disabled) |
| `setup_tracing()` | Initialize OTLP exporter (call once at startup) |
| `get_current_span()` | Get active span or invalid no-op span |
| `add_event(name, attributes)` | Add named event to current span |
| `set_span_error(exc)` | Record exception and set error status |

#### Recommended Spans

| Span Name | Attributes |
|-----------|------------|
| `rag.request` | `rag.endpoint`, `rag.user_id` |
| `rag.retrieve` | `rag.query`, `rag.num_results` |
| `rag.rerank` | `rag.num_candidates`, `rag.num_results` |
| `rag.llm` | `rag.model`, `rag.tokens_prompt`, `rag.tokens_completion` |
| `rag.cache` | `rag.cache_hit` |

### Backend Options

| Backend | Protocol | Notes |
|---------|----------|-------|
| Jaeger | OTLP HTTP | Popular open-source tracing |
| Grafana Tempo | OTLP HTTP | Integrates with Grafana stack |
| Zipkin | OTLP HTTP | Alternative open-source option |
| Datadog | OTLP HTTP | Commercial APM |

---

## Alerting

### Prometheus Alert Rules

Create alert rules in `alerts/rag-alerts.yml`:

```yaml
groups:
  - name: rag-proxy
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: rate(rag_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate on RAG proxy"
          description: "Error rate is {{ $value }} requests/sec (threshold: 0.05)"

      # High latency
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High P95 latency on RAG proxy"
          description: "P95 latency is {{ $value }} seconds (threshold: 10s)"

      # Slow LLM responses
      - alert: SlowLLM
        expr: histogram_quantile(0.95, rate(rag_llm_duration_seconds_bucket[5m])) > 60
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Slow LLM responses"
          description: "P95 LLM duration is {{ $value }} seconds"

      # Low cache hit ratio
      - alert: LowCacheHitRatio
        expr: rate(rag_cache_hits_total[5m]) / rate(rag_requests_total[5m]) < 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Low cache hit ratio"
          description: "Cache hit ratio is {{ $value }} (threshold: 0.1)"

      # Too many active requests
      - alert: HighActiveRequests
        expr: rag_active_requests > 50
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High number of active requests"
          description: "{{ $value }} active requests (threshold: 50)"

      # Health check failure
      - alert: HealthCheckFailed
        expr: up{job="rag-proxy"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "RAG proxy health check failed"
          description: "The RAG proxy is not responding to Prometheus scrapes"
```

### Alertmanager Configuration

```yaml
route:
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty'

receivers:
  - name: 'default'
    webhook_configs:
      - url: 'http://alertmanager-webhook:5001/'

  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: '<key>'
```

---

## Troubleshooting

### Common Issues

#### Metrics endpoint returns 404

**Cause**: `METRICS_ENABLED` is not set or set to `false`.

**Fix**:
```bash
METRICS_ENABLED=true
```

#### No traces appear in collector

**Cause**: `OTEL_ENABLED` is `false` or collector endpoint is unreachable.

**Fix**:
```bash
# Check configuration
OTEL_ENABLED=true
OTEL_EXPORTER_ENDPOINT=http://localhost:4318/v1/traces

# Verify collector is running
curl -v http://localhost:4318/v1/traces
```

#### Logs contain masked values where they shouldn't

**Cause**: The sensitive data masking regex is too broad.

**Fix**: The masking patterns in `proxy/app/shared/logging.py` match:
- `api_key`, `API_KEY`
- `Authorization: Bearer`
- `password`, `secret`, `token`

If legitimate values are being masked, adjust the `SENSITIVE_PATTERNS` list.

#### Health check shows unhealthy components

**Cause**: One or more backend services (Qdrant, LLM, Redis, Neo4j) are unreachable.

**Fix**:
```bash
# Check Qdrant
curl http://localhost:6333/healthz

# Check LLM
curl http://localhost:8000/v1/models

# Check Redis
redis-cli ping

# Check Neo4j
cypher-shell -u neo4j -p neo4j "RETURN 1"
```

#### Rate limiting not working

**Cause**: `RATE_LIMIT_ENABLED` is `false` or middleware is not registered.

**Fix**:
```bash
RATE_LIMIT_ENABLED=true
```

Verify the middleware is registered in `main.py` by checking for `add_rate_limit_middleware()`.

#### Request IDs not appearing in logs

**Cause**: `RequestIdFilter` is not added to the log handler.

**Fix**: Ensure `setup_logging()` is called at startup, which adds `RequestIdFilter` to the root handler.

### Debug Checklist

1. Check `/v1/health` for component status
2. Check `/metrics` for Prometheus metrics
3. Check logs for error messages (use `LOG_FORMAT=json` for structured search)
4. Check `X-Request-ID` header in responses for request tracing
5. Check OpenTelemetry collector for distributed traces

---

## Related Documentation

- [Security Guide](security-guide.md) — authentication, authorization, audit logging
- [Deployment Guide](deployment-guide.md) — production deployment with monitoring
- [Operations Guide](operations-guide.md) — operational procedures
- [Performance & Quality](performance-quality.md) — HNSW tuning, quantization, monitoring
- [Troubleshooting](troubleshooting.md) — common issues and resolutions
