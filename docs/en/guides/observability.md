# Observability

Distributed tracing, metrics, and logging for the RAG proxy.

## Current State

- **Score**: 8.5/10 — Distributed tracing is partially implemented
- **Metrics**: Prometheus counters, histograms, and gauges via `/metrics`
- **Logging**: Structured (JSON) or text via `LOG_FORMAT`
- **Tracing**: OpenTelemetry with OTLP HTTP/protobuf exporter

## Distributed Tracing

### Architecture

```
Client  ─→  TraceContextMiddleware  ─→  chat_completions  ─→  retrieval  ─→  rerank
  │              │                        │                     │              │
  │ traceparent  │ rag.http.request       │ rag.chat.           │ rag.retrieval.│ rag.rerank
  │              │                        │ completions         │ hybrid_search │
  ▼              ▼                        ▼                     ▼              ▼
W3C context ─→ Server span ─────────→ Pipeline span ──────→ Search span ───→ Rerank span
```

### Configuration

```bash
# Enable/disable tracing (default: false)
OTEL_ENABLED=true

# OTLP collector endpoint (HTTP/protobuf)
OTEL_EXPORTER_ENDPOINT=http://jaeger:4318/v1/traces

# Service name in traces
OTEL_SERVICE_NAME=rag-proxy

# Batch export interval in seconds
OTEL_BATCH_TIMEOUT=5
```

### Span Hierarchy

| Span Name | Location | Attributes |
|---|---|---|
| `rag.http.request` | `middleware.py` | `http.method`, `http.url`, `http.status_code` |
| `rag.chat.completions` | `chat.py` | `rag.query`, `rag.model`, `rag.stream` |
| `rag.pipeline.process` | `chat.py` | `rag.query`, `rag.version`, `rag.stream` |
| `rag.retrieval.hybrid_search` | `retrieval.py` | `rag.query`, `rag.top_k`, `rag.num_results`, `rag.quality` |
| `rag.rerank` | `rerank.py` | `rag.query`, `rag.num_chunks`, `rag.top_k`, `rag.rerank.top_score` |

### Span Events

| Event Name | Context | Attributes |
|---|---|---|
| `rag.pipeline.stream.start` | Streaming pipeline | `query`, `version` |
| `rag.pipeline.refusal` | Retrieval refusal | `reason` |
| `rag.retrieval.qdrant_unavailable` | Qdrant down | — |
| `rag.retrieval.combined` | Dense+sparse merge | `dense_count`, `sparse_count` |
| `rag.retrieval.insufficient_quality` | Low-quality results | — |
| `rag.embedding.cache_hit` | Embedding cache hit | `cache` (local/redis) |
| `rag.embedding.compute` | Embedding computation | `text_length` |
| `rag.rerank.computed` | Rerank scores computed | `num_pairs` |
| `rag.rerank.cache_hit` | Rerank cache hit | `num_pairs` |

### Context Propagation

The `TraceContextMiddleware` in `middleware.py` extracts W3C `traceparent` headers from incoming requests.
Downstream services receive `traceparent` via `inject_context_to_headers()`.

```python
from proxy.app.shared.tracing import inject_context_to_headers

headers = {}
inject_context_to_headers(headers)
# headers now contains: {"traceparent": "00-..."}
```

### Instrumenting New Code

```python
from proxy.app.shared.tracing import tracer, add_event, traced

# Context manager
with tracer.start_as_current_span("rag.custom.operation") as span:
    span.set_attribute("rag.key", "value")
    add_event("rag.custom.milestone", {"detail": "x"})

# Decorator
@traced("rag.custom.func")
def my_func():
    return 42
```

### Zero-Overhead Guarantee

When `OTEL_ENABLED=false` or `opentelemetry` is not installed:

- All span operations are no-ops (silently discarded)
- No memory allocations for spans
- No background export threads
- `_NoOpTracer`, `_NoOpSpan` stubs handle all API calls

## Metrics

Prometheus metrics exposed at `/metrics`:

| Metric | Type | Labels |
|---|---|---|
| `rag_requests_total` | Counter | `method`, `status` |
| `rag_request_duration_ms` | Histogram | `endpoint` |
| `rag_retrieval_results` | Histogram | `quality` |
| `rag_cache_hits_total` | Counter | `cache_type` |
| `rag_llm_tokens_total` | Counter | `model` |

## Logging

```bash
# JSON structured logging
LOG_FORMAT=json

# Text logging (default)
LOG_FORMAT=text
```

Structured log fields: `request_id`, `correlation_id`, `trace_id`, `span_id`, `client_ip`, `duration_ms`.

## Related ADRs

- [ADR-001: Architecture Overview](../adr/ADR-001.md)
- [Monitoring Guide](monitoring-guide.md)
