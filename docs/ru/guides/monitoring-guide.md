# Руководство по мониторингу и наблюдаемости

Данное руководство охватывает стратегию наблюдаемости RAG System, включая метрики Prometheus, проверки здоровья,
структурированное логирование, распределённую трассировку и оповещения.

## Содержание

1. [Обзор](#обзор)
2. [Метрики Prometheus](#метрики-prometheus)
3. [Дашборды Grafana](#дашборды-grafana)
4. [Проверки здоровья](#проверки-здоровья)
5. [Логирование](#логирование)
6. [Трассировка](#трассировка)
7. [Оповещения](#оповещения)
8. [Устранение неполадок](#устранение-неполадок)

---

## Обзор

RAG System обеспечивает полную наблюдаемость через три столпа:

| Столп           | Технология                  | Эндпоинт             |
|-----------------|-----------------------------|----------------------|
| **Метрики**     | Prometheus                  | `/metrics`           |
| **Логи**        | Структурированные JSON/text | stdout / JSONL-файлы |
| **Трассировка** | OpenTelemetry (OTLP)        | OTLP HTTP коллектор  |

### Архитектура

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  RAG Proxy  │────▶│  Prometheus  │────▶│   Grafana   │
│  /metrics   │     │   Scraper    │     │  Dashboards │
└──────┬──────┘     └──────────────┘     └─────────────┘
       │
       ├──── stdout (JSON/text логи) ────▶ Loki / ELK
       │
       └──── OTLP HTTP ────────────────▶ Tempo / Jaeger
```

### Конфигурация

```bash
METRICS_ENABLED=true              # Включить метрики Prometheus (по умолчанию: true)
LOG_FORMAT=json                   # "json" для структурированных, "text" для консоли
OTEL_ENABLED=false                # Включить трассировку OpenTelemetry
OTEL_EXPORTER_ENDPOINT=http://localhost:4318/v1/traces
OTEL_SERVICE_NAME=rag-proxy
```

---

## Метрики Prometheus

### Эндпоинт скрапинга

```
GET /metrics
```

Возвращает метрики в формате Prometheus. Аутентификация не требуется (указан как публичный эндпоинт).

### Доступные метрики

#### Счётчики (Counters)

| Метрика                | Метки                | Описание                         |
|------------------------|----------------------|----------------------------------|
| `rag_requests_total`   | `endpoint`, `status` | Общее количество RAG-запросов    |
| `rag_cache_hits_total` | —                    | Общее количество попаданий в кеш |

#### Гистограммы (Histograms)

| Метрика                          | Метки      | Бакеты (секунды)                                            | Описание                  |
|----------------------------------|------------|-------------------------------------------------------------|---------------------------|
| `rag_request_duration_seconds`   | `endpoint` | 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0 | Длительность запроса      |
| `rag_retrieval_duration_seconds` | —          | 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0             | Длительность этапа поиска |
| `rag_rerank_duration_seconds`    | —          | 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0                   | Длительность этапа rerank |
| `rag_llm_duration_seconds`       | —          | 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0            | Длительность вызова LLM   |

#### Датчики (Gauges)

| Метрика               | Описание                                       |
|-----------------------|------------------------------------------------|
| `rag_context_tokens`  | Количество токенов контекста, переданных в LLM |
| `rag_active_requests` | Количество активных запросов в данный момент   |

### Примеры запросов

```promql
# Интенсивность запросов в секунду
rate(rag_requests_total[5m])

# P95 длительности запроса
histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m]))

# Коэффициент попаданий в кеш
rate(rag_cache_hits_total[5m]) / rate(rag_requests_total[5m])

# Средняя длительность поиска
rate(rag_retrieval_duration_seconds_sum[5m]) / rate(rag_retrieval_duration_seconds_count[5m])

# Активные запросы
rag_active_requests

# Частота ошибок по эндпоинтам
rate(rag_requests_total{status=~"5.."}[5m])
```

### Исходный файл

Все метрики определены в `proxy/app/shared/metrics.py`:

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

## Дашборды Grafana

### Рекомендуемые панели

#### Обзор запросов

- **Интенсивность запросов**: `rate(rag_requests_total[5m])` — временной ряд
- **Длительность P50/P95/P99**: `histogram_quantile(0.95, ...)` — временной ряд
- **Активные запросы**: `rag_active_requests` — датчик
- **Частота ошибок**: `rate(rag_requests_total{status=~"5.."}[5m])` — временной ряд

#### Производительность поиска

- **Длительность поиска**: `rag_retrieval_duration_seconds` — тепловая карта
- **Длительность rerank**: `rag_rerank_duration_seconds` — тепловая карта
- **Длительность LLM**: `rag_llm_duration_seconds` — тепловая карта

#### Кеш и эффективность

- **Коэффициент попаданий в кеш**: вычисляется из `rag_cache_hits_total` / `rag_requests_total`
- **Токены контекста**: `rag_context_tokens` — датчик во времени

### JSON дашборда

Готовый JSON дашборда Grafana может быть сгенерирован из определений метрик. Импорт в Grafana: **Dashboards → Import →
Upload JSON**.

---

## Проверки здоровья

### Эндпоинты

| Эндпоинт           | Метод | Назначение                                   | Kubernetes       |
|--------------------|-------|----------------------------------------------|------------------|
| `/v1/health`       | GET   | Общий статус здоровья                        | —                |
| `/v1/health/live`  | GET   | Liveness-проба                               | `livenessProbe`  |
| `/v1/health/ready` | GET   | Readiness-проба (подключение к Qdrant + LLM) | `readinessProbe` |

### Liveness-проба

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

### Readiness-проба

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

### Формат ответа

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

## Логирование

### Конфигурация

```bash
LOG_FORMAT=text     # "text" для читаемого вывода в консоль
LOG_FORMAT=json     # "json" для структурированных логов
LOG_DIR=./logs      # Директория для лог-файлов
LOG_REQUESTS=true   # Логировать каждый запрос (метод, путь, статус, длительность)
```

### Форматы логов

#### Текстовый формат (разработка)

```
2024-01-15 10:30:00 [rag-proxy] [INFO] [abc-123] POST /v1/chat/completions 200 1234.56ms
```

#### JSON-формат (продакшн)

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

### Распространение Request ID

Каждый запрос получает уникальный `X-Request-ID` (UUID v4), внедряемый `RequestIdMiddleware`. Если клиент предоставляет
свой, он сохраняется. ID:

1. Добавляется в `request.state.request_id`
2. Внедряется во все записи логов для данного запроса
3. Возвращается в заголовке ответа `X-Request-ID`

### Correlation ID

`CorrelationIdMiddleware` распространяет `X-Correlation-ID` между сервисами для распределённой трассировки. При
отсутствии генерируется новый UUID.

### Маскирование чувствительных данных

Модуль логирования автоматически маскирует:

- API-ключи (`api_key=...`, `API_KEY=...`)
- Bearer-токены (`Authorization: Bearer ...`)
- Пароли (`password=...`)
- Секреты (`secret=...`)
- Токены (`token=...`)

### Уровни логирования

| Уровень    | Применение                                                     |
|------------|----------------------------------------------------------------|
| `DEBUG`    | Детальная диагностическая информация                           |
| `INFO`     | События нормальной работы (запросы, проверки здоровья)         |
| `WARNING`  | Деградированная работа (активирован запасной вариант, таймаут) |
| `ERROR`    | Сбои операций (таймаут LLM, ошибка поиска)                     |
| `CRITICAL` | Сбои уровня системы (крах при запуске, повреждение данных)     |

---

## Трассировка

### Интеграция с OpenTelemetry

При `OTEL_ENABLED=true` прокси экспортирует распределённые трассы через OTLP HTTP.

#### Конфигурация

```bash
OTEL_ENABLED=true                                    # Включить трассировку
OTEL_EXPORTER_ENDPOINT=http://localhost:4318/v1/traces  # OTLP-коллектор
OTEL_SERVICE_NAME=rag-proxy                          # Имя сервиса в трассах
OTEL_BATCH_TIMEOUT=5                                 # Интервал пакетного экспорта (секунды)
OTEL_MAX_ATTRIBUTES_PER_SPAN=128                     # Макс. атрибутов на спан
```

#### Использование в коде

```python
from proxy.app.shared.tracing import tracer, add_event, set_span_error

with tracer.start_as_current_span("rag.retrieve") as span:
    span.set_attribute("rag.query", query)
    results = hybrid_search(query)
    span.set_attribute("rag.num_results", len(results))
    add_event("retrieval.complete", {"chunks": len(results)})
```

#### Утилитарные функции

| Функция                       | Описание                                                     |
|-------------------------------|--------------------------------------------------------------|
| `tracer`                      | Экземпляр трейсера уровня модуля (no-op при отключении)      |
| `setup_tracing()`             | Инициализация OTLP-экспортёра (вызвать один раз при запуске) |
| `get_current_span()`          | Получить активный спан или неактивный no-op спан             |
| `add_event(name, attributes)` | Добавить именованное событие в текущий спан                  |
| `set_span_error(exc)`         | Записать исключение и установить статус ошибки               |

#### Рекомендуемые спаны

| Имя спана      | Атрибуты                                                  |
|----------------|-----------------------------------------------------------|
| `rag.request`  | `rag.endpoint`, `rag.user_id`                             |
| `rag.retrieve` | `rag.query`, `rag.num_results`                            |
| `rag.rerank`   | `rag.num_candidates`, `rag.num_results`                   |
| `rag.llm`      | `rag.model`, `rag.tokens_prompt`, `rag.tokens_completion` |
| `rag.cache`    | `rag.cache_hit`                                           |

### Варианты бэкендов

| Бэкенд        | Протокол  | Примечания                         |
|---------------|-----------|------------------------------------|
| Jaeger        | OTLP HTTP | Популярный open-source трейсинг    |
| Grafana Tempo | OTLP HTTP | Интегрируется со стеком Grafana    |
| Zipkin        | OTLP HTTP | Альтернативный open-source вариант |
| Datadog       | OTLP HTTP | Коммерческий APM                   |

---

## Оповещения

### Правила оповещений Prometheus

Создайте правила оповещений в `alerts/rag-alerts.yml`:

```yaml
groups:
  - name: rag-proxy
    rules:
      # Высокая частота ошибок
      - alert: HighErrorRate
        expr: rate(rag_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Высокая частота ошибок RAG-прокси"
          description: "Частота ошибок {{ $value }} запросов/сек (порог: 0.05)"

      # Высокая задержка
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(rag_request_duration_seconds_bucket[5m])) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая P95-задержка RAG-прокси"
          description: "P95-задержка {{ $value }} секунд (порог: 10s)"

      # Медленные ответы LLM
      - alert: SlowLLM
        expr: histogram_quantile(0.95, rate(rag_llm_duration_seconds_bucket[5m])) > 60
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Медленные ответы LLM"
          description: "P95-длительность LLM {{ $value }} секунд"

      # Низкий коэффициент попаданий в кеш
      - alert: LowCacheHitRatio
        expr: rate(rag_cache_hits_total[5m]) / rate(rag_requests_total[5m]) < 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Низкий коэффициент попаданий в кеш"
          description: "Коэффициент попаданий {{ $value }} (порог: 0.1)"

      # Слишком много активных запросов
      - alert: HighActiveRequests
        expr: rag_active_requests > 50
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Большое количество активных запросов"
          description: "{{ $value }} активных запросов (порог: 50)"

      # Сбой проверки здоровья
      - alert: HealthCheckFailed
        expr: up{job="rag-proxy"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Сбой проверки здоровья RAG-прокси"
          description: "RAG-прокси не отвечает на запросы Prometheus"
```

### Конфигурация Alertmanager

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

## Устранение неполадок

### Типичные проблемы

#### Эндпоинт метрик возвращает 404

**Причина**: `METRICS_ENABLED` не установлен или установлен в `false`.

**Исправление**:

```bash
METRICS_ENABLED=true
```

#### Трассы не появляются в коллекторе

**Причина**: `OTEL_ENABLED` равен `false` или эндпоинт коллектора недоступен.

**Исправление**:

```bash
# Проверить конфигурацию
OTEL_ENABLED=true
OTEL_EXPORTER_ENDPOINT=http://localhost:4318/v1/traces

# Проверить доступность коллектора
curl -v http://localhost:4318/v1/traces
```

#### Логи содержат маскированные значения там, где не нужно

**Причина**: Регулярные выражения маскирования чувствительных данных слишком широкие.

**Исправление**: Паттерны маскирования в `proxy/app/shared/logging.py` совпадают с:

- `api_key`, `API_KEY`
- `Authorization: Bearer`
- `password`, `secret`, `token`

Если легитимные значения маскируются, отредактируйте список `SENSITIVE_PATTERNS`.

#### Проверка здоровья показывает нездоровые компоненты

**Причина**: Один или несколько бэкенд-сервисов (Qdrant, LLM, Redis, Neo4j) недоступны.

**Исправление**:

```bash
# Проверить Qdrant
curl http://localhost:6333/healthz

# Проверить LLM
curl http://localhost:8000/v1/models

# Проверить Redis
redis-cli ping

# Проверить Neo4j
cypher-shell -u neo4j -p neo4j "RETURN 1"
```

#### Ограничение частоты не работает

**Причина**: `RATE_LIMIT_ENABLED` равен `false` или промежуточное ПО не зарегистрировано.

**Исправление**:

```bash
RATE_LIMIT_ENABLED=true
```

Проверьте регистрацию промежуточного ПО в `main.py` — наличие вызова `add_rate_limit_middleware()`.

#### Request ID не появляется в логах

**Причина**: `RequestIdFilter` не добавлен к обработчику логов.

**Исправление**: Убедитесь, что `setup_logging()` вызывается при запуске — он добавляет `RequestIdFilter` к корневому
обработчику.

### Чеклист отладки

1. Проверить `/v1/health` для статуса компонентов
2. Проверить `/metrics` для метрик Prometheus
3. Проверить логи на наличие сообщений об ошибках (используйте `LOG_FORMAT=json` для структурированного поиска)
4. Проверить заголовок `X-Request-ID` в ответах для трассировки запросов
5. Проверить коллектор OpenTelemetry для распределённых трасс

---

## Связанная документация

- [Руководство по безопасности](security-guide.md) — аутентификация, авторизация, аудит-логирование
- [Руководство по развёртыванию](deployment-guide.md) — продакшн-развёртывание с мониторингом
- [Руководство по эксплуатации](operations-guide.md) — операционные процедуры
- [Производительность и качество](performance-quality.md) — настройка HNSW, квантизация, мониторинг
- [Устранение неполадок](troubleshooting.md) — типичные проблемы и решения
