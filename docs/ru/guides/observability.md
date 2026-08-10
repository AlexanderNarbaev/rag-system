# Наблюдаемость

Distributed tracing, метрики и логирование для RAG-прокси.

## Текущее состояние

- **Оценка**: 10/10 — полный стек наблюдаемости завершён
- **Метрики**: 25+ Prometheus-счётчиков, гистограмм и датчиков через `/metrics`
- **Логирование**: структурированное (JSON) или текстовое через `LOG_FORMAT`
- **Tracing**: OpenTelemetry с OTLP HTTP/protobuf экспортёром
- **Кэш**: отслеживание hit/miss по типу кэша (memory, redis)
- **Очередь**: датчик глубины очереди запросов для мониторинга concurrency

## Distributed Tracing

### Архитектура

```
Client  ─→  TraceContextMiddleware  ─→  chat_completions  ─→  retrieval  ─→  rerank
  │              │                        │                     │              │
  │ traceparent  │ rag.http.request       │ rag.chat.           │ rag.retrieval.│ rag.rerank
  │              │                        │ completions         │ hybrid_search │
  ▼              ▼                        ▼                     ▼              ▼
W3C context ─→ Server span ─────────→ Pipeline span ──────→ Search span ───→ Rerank span
```

### Конфигурация

```bash
# Включить/выключить tracing (по умолчанию: false)
OTEL_ENABLED=true

# Эндпоинт OTLP-коллектора (HTTP/protobuf)
OTEL_EXPORTER_ENDPOINT=http://jaeger:4318/v1/traces

# Имя сервиса в трейсах
OTEL_SERVICE_NAME=rag-proxy

# Интервал батч-экспорта в секундах
OTEL_BATCH_TIMEOUT=5
```

### Иерархия спанов

| Имя спана               | Расположение     | Атрибуты                                                            |
|-------------------------|------------------|---------------------------------------------------------------------|
| `rag.http.request`       | `middleware.py`  | `http.method`, `http.url`, `http.status_code`                        |
| `rag.chat.completions`   | `chat.py`        | `rag.query`, `rag.model`, `rag.stream`                              |
| `rag.pipeline.process`   | `chat.py`        | `rag.query`, `rag.version`, `rag.stream`                             |
| `rag.retrieval.hybrid_search` | `retrieval.py` | `rag.query`, `rag.top_k`, `rag.num_results`, `rag.quality`           |
| `rag.rerank`            | `rerank.py`      | `rag.query`, `rag.num_chunks`, `rag.top_k`, `rag.rerank.top_score`   |

### События спанов

| Имя события                          | Контекст                   | Атрибуты                          |
|--------------------------------------|----------------------------|-----------------------------------|
| `rag.pipeline.stream.start`           | Стриминговый pipeline       | `query`, `version`                |
| `rag.pipeline.refusal`                | Отказ retrieval             | `reason`                          |
| `rag.retrieval.qdrant_unavailable`    | Qdrant недоступен          | —                                 |
| `rag.retrieval.combined`              | Слияние dense+sparse        | `dense_count`, `sparse_count`      |
| `rag.retrieval.insufficient_quality`  | Низкое качество результатов| —                                 |
| `rag.embedding.cache_hit`             | Hit кэша эмбеддингов         | `cache` (local/redis)             |
| `rag.embedding.compute`               | Вычисление эмбеддинга        | `text_length`                     |
| `rag.rerank.computed`                 | Вычисление скоров rerank    | `num_pairs`                        |
| `rag.rerank.cache_hit`                | Hit кэша rerank             | `num_pairs`                        |

### Распространение контекста

`TraceContextMiddleware` в `middleware.py` извлекает W3C-заголовки `traceparent` из входящих запросов.
Downstream-сервисы получают `traceparent` через `inject_context_to_headers()`.

```python
from proxy.app.shared.tracing import inject_context_to_headers

headers = {}
inject_context_to_headers(headers)
# headers now contains: {"traceparent": "00-..."}
```

### Инструментирование нового кода

```python
from proxy.app.shared.tracing import tracer, add_event, traced

# Context manager
with tracer.start_as_current_span("rag.custom.operation") as span:
    span.set_attribute("rag.key", "value")
    add_event("rag.custom.milestone", {"detail": "x"})

# Декоратор
@traced("rag.custom.func")
def my_func():
    return 42
```

### Гарантия нулевых накладных расходов

При `OTEL_ENABLED=false` или когда `opentelemetry` не установлен:

- Все операции со спанами — no-op (тихо отбрасываются)
- Никаких аллокаций памяти под спаны
- Нет фоновых потоков экспорта
- Заглушки `_NoOpTracer`, `_NoOpSpan` обрабатывают все вызовы API

## Метрики

Prometheus-метрики доступны на `/metrics`:

### Запросы и задержка

| Метрика                          | Тип         | Метки                       |
|----------------------------------|-------------|-----------------------------|
| `rag_requests_total`              | Counter     | `endpoint`, `status`        |
| `rag_request_total`               | Counter     | `method`, `status`, `has_context` |
| `rag_request_duration_seconds`    | Histogram   | `endpoint`                  |
| `rag_rag_latency_seconds`         | Histogram   | `operation`                 |
| `rag_active_requests`             | Gauge       | —                           |

### Retrieval и Rerank

| Метрика                              | Тип       | Метки |
|--------------------------------------|-----------|-------|
| `rag_retrieval_duration_seconds`     | Histogram | —     |
| `rag_retrieval_chunks_total`          | Gauge     | —     |
| `rag_retrieval_chunks_after_rerank`   | Gauge     | —     |
| `rag_retrieval_mrr`                   | Gauge     | —     |
| `rag_retrieval_scores`                | Histogram | —     |
| `rag_rerank_duration_seconds`         | Histogram | —     |

### Кэш

| Метрика                       | Тип       | Метки        |
|-------------------------------|-----------|--------------|
| `rag_cache_hits_total`         | Counter   | —            |
| `rag_cache_hits_total_v2`      | Counter   | `cache_type` |
| `rag_cache_misses_total`       | Counter   | `cache_type` |

### LLM

| Метрика                       | Тип       | Метки                            |
|-------------------------------|-----------|----------------------------------|
| `rag_llm_duration_seconds`     | Histogram | —                                |
| `rag_llm_tokens_total`         | Counter   | `direction` (prompt, completion)|
| `rag_context_tokens`           | Gauge     | —                                |

### Качество и уверенность

| Метрика                                | Тип       | Метки |
|----------------------------------------|-----------|-------|
| `rag_confidence_score`                 | Histogram | —     |
| `rag_confidence_score_high_ratio`      | Gauge     | —     |
| `rag_grounding_score_high_ratio`        | Gauge     | —     |
| `rag_hallucination_detected_total`     | Counter   | —     |
| `rag_negative_rejection_total`         | Counter   | —     |
| `rag_compression_ratio`                 | Gauge     | —     |
| `rag_graph_expansion_rate`             | Gauge     | —     |

### Конкурентность

| Метрика              | Тип     | Метки |
|----------------------|---------|-------|
| `rag_queue_depth`    | Gauge   | —     |

## Логирование

```bash
# Структурированное логирование JSON
LOG_FORMAT=json

# Текстовое логирование (по умолчанию)
LOG_FORMAT=text
```

Поля структурированного лога: `request_id`, `correlation_id`, `trace_id`, `span_id`, `client_ip`, `duration_ms`.

## Связанные ADR

- [ADR-001: BAAI/bge-m3 Embedding Model](../adr/ADR-001-bge-m3-embedding-model.md)
- [Monitoring Guide](monitoring-guide.md)
