# SLI/SLO Definitions — RAG System v2.0

## Overview

This document defines Service Level Indicators (SLIs) and Service Level Objectives (SLOs)
for the RAG System. These metrics drive alerting, dashboarding, and reliability engineering.

## Error Budget Policy

| SLA Target | Availability | Allowed Downtime (monthly) |
|-----------|-------------|---------------------------|
| 99.5%     | 99.5%       | ~3.6 hours/month          |

Error budget = `(total_minutes_in_window - error_minutes) / total_minutes_in_window * 100`

When the error budget is exhausted (burn rate > 1x), new feature deploys are frozen
until reliability is restored.

## SLI/SLO Table

| # | SLI | SLO Target | Measurement Window | PromQL | Notes |
|---|-----|-----------|-------------------|--------|-------|
| 1 | **Availability** | 99.5% | 30 days | `avg_over_time(up{job="rag-proxy"}[30d])` | Proxy uptime as reported by Prometheus |
| 2 | **Latency (p95)** | < 5s | 30 days | `histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[30d]))` | End-to-end request latency |
| 3 | **Error Rate** | < 1% | 30 days | `sum(rate(rag_requests_total{status=~"5.."}[30d])) / sum(rate(rag_requests_total[30d]))` | 5xx errors only |
| 4 | **Cache Hit Rate** | > 60% | 30 days | `rate(rag_cache_hits_total[30d]) / rate(rag_requests_total[30d])` | Semantic + exact cache hits |
| 5 | **Retrieval MRR** | > 0.75 | per eval run | `rag_retrieval_mrr` | Mean Reciprocal Rank; measured during evaluation pipeline runs |
| 6 | **Confidence > 0.5 Rate** | > 70% | 30 days | `rag_confidence_score_high_ratio` | Fraction of responses with confidence ≥ 0.5 |
| 7 | **TTFT (streaming)** | < 1s | 30 days | `rag_ttft_seconds` | Time To First Token for streaming responses |
| 8 | **Backup RPO** | < 1 hour | per backup | `time() - rag_last_backup_timestamp_seconds` | Recovery Point Objective: max data loss |
| 9 | **Backup RTO** | < 30 min | per restore drill | Manual measurement during restore drills | Recovery Time Objective: time to restore |

## Uptime Calculation

```
uptime_percent = (total_minutes - error_minutes) / total_minutes * 100
```

Where `error_minutes` is the sum of minutes where the service returned 5xx errors
or was unreachable (proxy down).

## Error Budget Burn Rate Alerts

| Burn Rate | Time Window | Alert | Action |
|-----------|-------------|-------|--------|
| 14.4x | 1 hour | Critical | Page on-call, halt deploys |
| 6x | 6 hours | Critical | Page on-call |
| 3x | 24 hours | Warning | Investigate |
| 1x | 30 days | Warning | Team review |

Burn rate = `error_rate / error_budget`

Error budget = `1 - SLO_target` (e.g., `1 - 0.995 = 0.005` for availability).

## Monitoring Stack

| Component | Tool | Endpoint | Interval |
|-----------|------|----------|----------|
| Proxy metrics | Prometheus | `localhost:8080/metrics` | 15s |
| Qdrant metrics | Prometheus | `localhost:6333/metrics` | 30s |
| Redis metrics | Redis Exporter | `localhost:9121/metrics` | 30s |
| Neo4j metrics | Neo4j Exporter | `localhost:2004/metrics` | 30s |
| Dashboards | Grafana | Port 3000 | 10s refresh |
| Alerting | Alertmanager (future) | — | — |

## Runbooks

See [Operations Guide](guides/operations-guide.md) for incident response procedures.
