# Блок J-P. MCP, Deployment, Observability, Performance, Multi-Modal (FR-121 — FR-175)

---

## MCP Server (FR-121 — FR-125)

### FR-121. MCP tools: rag_search, rag_chat, rag_feedback

**Описание:**
MCP сервер обрабатывает 3 инструмента:

- `rag_search` — поиск по knowledge base (параметр: query)
- `rag_chat` — chat completion через RAG (параметр: messages)
- `rag_feedback` — отправка feedback (параметр: feedback_id, type, correction)

**Критерий приёмки:**

1. MCP-клиент видит все 3 инструмента
2. `rag_search("query")` — возвращает найденные чанки
3. `rag_chat([{"role":"user","content":"..."}])` — возвращает ответ
4. `rag_feedback(...)` — отправляет feedback

**Статус:** ⚠️ Код есть (`mcp_server/server.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-013

---

### FR-122. MCP resource: rag://collections

**Описание:**
MCP сервер вызывает ресурс `rag://collections` — список доступных коллекций.

**Критерий приёмки:**

1. MCP-клиент может прочитать ресурс
2. Возвращает список коллекций с метаданными

**Статус:** ⚠️ Код есть (`mcp_server/server.py`), нужен интеграционный тест
**Приоритет:** MEDIUM
**Связь:** ADR-013

---

### FR-123. MCP prompt: rag_help

**Описание:**
MCP сервер вызывает промпт `rag_help` с инструкциями по использованию.

**Критерий приёмки:**

1. MCP-клиент может получить промпт
2. Промпт содержит описание всех инструментов и параметров

**Статус:** ⚠️ Код есть (`mcp_server/server.py`), нужен интеграционный тест
**Приоритет:** MEDIUM
**Связь:** ADR-013

---

### FR-124. Dual transport: STDIO + HTTP

**Описание:**
MCP сервер поддерживает два транспорта:

- STDIO (по умолчанию) — для OpenCode, Claude Desktop
- HTTP — для web-клиентов

**Критерий приёмки:**

1. STDIO mode — клиент подключается через stdin/stdout
2. HTTP mode — клиент подключается по HTTP
3. Оба транспорта работают одновременно

**Статус:** ⚠️ Код есть (`mcp_server/server.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-013

---

### FR-125. Standalone installation

**Описание:**
MCP сервер устанавливается как standalone pip-пакет или скрипт.
Конфигурация через переменную окружения `RAG_PROXY_URL`.

**Критерий приёмки:**

1. `pip install` или `python mcp_server/server.py` — сервер запускается
2. `RAG_PROXY_URL=http://proxy:8080` — подключается к прокси
3. Без переменной — ошибка с инструкцией

**Статус:** ⚠️ Код есть (`mcp_server/server.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-013

---

## Deployment (FR-149 — FR-156)

### FR-149. Docker Compose deployment

**Описание:**
Система деплоится одной командой: `docker compose up -d`. Запускает: proxy, Qdrant,
Redis, Neo4j (опционально), MinIO (опционально).

**Критерий приёмки:**

1. `docker compose up -d` — все сервисы запускаются
2. `/v1/health` — все компоненты healthy
3. `docker compose down` — чистое завершение

**Статус:** ⚠️ Код есть (`proxy/docker-compose.yml`), нужен smoke test
**Приоритет:** CRITICAL
**Связь:** AGENTS.md

---

### FR-150. Helm chart для Kubernetes

**Описание:**
Helm chart для K8s деплоя с:

- Deployment (proxy)
- StatefulSets (Qdrant, Neo4j, Redis, MinIO, PostgreSQL)
- HPA (auto-scaling)
- Probes (liveness, readiness)
- ConfigMaps, Secrets
- NetworkPolicies
- ServiceAccount, PDB

**Критерий приёмки:**

1. `helm lint deploy/k8s/helm/rag-system/` — без ошибок
2. `helm template` — рендерит валидные манифесты
3. `kubectl apply` — все ресурсы создаются

**Статус:** ⚠️ Код есть (16 templates), нужен `helm lint` + smoke test
**Приоритет:** CRITICAL
**Связь:** best-practices-checklist 7.4

---

### FR-151. ETL Helm component

**Описание:**
ETL деплоится как отдельный Helm component:

- CronJob для scheduled ETL
- PVC для WAL state
- ConfigMap для etl_config.yaml
- Resource limits

**Критерий приёмки:**

1. `etl.enabled: true` в values.yaml — ETL CronJob создаётся
2. CronJob запускается по расписанию
3. WAL state сохраняется в PVC

**Статус:** ⚠️ Код есть, нужен smoke test
**Приоритет:** HIGH
**Связь:** FR-151

---

### FR-152. Distributed compose

**Описание:**
`docker-compose.distributed.yml` для multi-machine deployment:

- Proxy на машине A
- Qdrant на машине B
- LLM на GPU-машине C
- Redis/Neo4j на машине D

**Критерий приёмки:**

1. `docker compose -f docker-compose.distributed.yml config` — валидный
2. Сервисы подключаются друг к другу по hostname
3. Health checks работают

**Статус:** ⚠️ Код есть, нужен smoke test
**Приоритет:** HIGH
**Связь:** FR-152

---

### FR-153. MinIO Helm deployment

**Описание:**
MinIO деплоится через Helm для:

- Model artifacts (LoRA adapters)
- Backup storage (Qdrant snapshots, Neo4j dumps)
- File uploads (rag-documents bucket)

**Критерий приёмки:**

1. MinIO PVC создаётся
2. Buckets создаются автоматически (rag-documents, rag-artifacts, open-webui)
3. Proxy подключается к MinIO

**Статус:** ⚠️ Код есть, нужен smoke test
**Приоритет:** HIGH
**Связь:** ADR-014

---

### FR-154. PostgreSQL Helm deployment

**Описание:**
PostgreSQL для structured data (user DB, feedback store) в K8s deployment.
Опционально: в single-node режиме используется SQLite.

**Критерий приёмки:**

1. PostgreSQL StatefulSet создаётся
2. Proxy подключается к PostgreSQL
3. Миграции применяются автоматически

**Статус:** ⚠️ Код есть, нужен smoke test
**Приоритет:** HIGH
**Связь:** FR-154

---

### FR-156. Setup wizard

**Описание:**
Интерактивный скрипт `setup.sh` выполняет:

1. Проверку зависимостей (Python, Docker, etc.)
2. Генерацию .env из .env.example
3. Запуск Docker-сервисов
4. Инициализацию коллекций
5. Health verification

**Критерий приёмки:**

1. `bash setup.sh --full` — все шаги завершаются успешно
2. После setup — `/v1/health` возвращает 200
3. Ошибка на любом шаге — понятное сообщение

**Статус:** ⚠️ Код есть (`scripts/setup_wizard.py`), нужен smoke test
**Приоритет:** HIGH
**Связь:** deployment-guide

---

## Observability (FR-160 — FR-164)

### FR-160. Prometheus /metrics

**Описание:**
Эндпоинт `GET /metrics` возвращает метрики в формате Prometheus:

- Counters: `rag_requests_total`, `rag_errors_total`, `rag_cache_hits_total`
- Histograms: `rag_request_duration_seconds`, `rag_retrieval_duration_seconds`
- Gauges: `rag_active_requests`, `rag_confidence_score`

**Критерий приёмки:**

1. `/metrics` — валидный Prometheus text format
2. Минимум 12 метрик
3. Labels: method, path, status

**Статус:** ⚠️ Код есть (`proxy/app/shared/metrics.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** best-practices-checklist 4.1

---

### FR-161. Structured JSON logging

**Описание:**
При `LOG_FORMAT=json` логи输出 в JSON-формате. Секреты маскируются.

**Критерий приёмки:**

1. `LOG_FORMAT=json` — логи в JSON
2. Каждая строка — валидный JSON
3. Секреты замаскированы
4. request_id propagируется через все логи запроса

**Статус:** ⚠️ Код есть (`proxy/app/shared/logging.py`), нужен интеграционный тест
**Приоритет:** CRITICAL
**Связь:** best-practices-checklist 4.2

---

### FR-162. Grafana dashboard

**Описание:**
JSON-файл для импорта в Grafana с панелями:

- Request rate (RPS)
- Latency percentiles (p50, p95, p99)
- Error rate
- Cache hit ratio
- Token usage
- Confidence distribution
- Feedback stats

**Критерий приёмки:**

1. JSON импортируется в Grafana без ошибок
2. Все панели отображают данные
3. Дашборд обновляется в реальном времени

**Статус:** ⚠️ Код есть (`config/monitoring/ragas-dashboard.json`), нужен smoke test
**Приоритет:** HIGH
**Связь:** best-practices-checklist 4.6

---

### FR-163. Prometheus alert rules

**Описание:**
Alert rules для Prometheus:

- `HighLatency` — p95 > 5s
- `HighErrorRate` — 5xx > 5%
- `LLMUnavailable` — LLM down > 2 min
- `QdrantUnavailable` — Qdrant down > 1 min
- `LowCacheHitRatio` — cache hit < 20%

**Критерий приёмки:**

1. `promtool check rules alerts.yml` — без ошибок
2. Все 5 alert rules присутствуют
3. Пороги настраиваемые

**Статус:** ⚠️ Код есть (`config/monitoring/alerts.yml`), нужен `promtool check`
**Приоритет:** HIGH
**Связь:** best-practices-checklist 4.5

---

### FR-164. OpenTelemetry tracing

**Описание:**
Система поддерживает distributed tracing через OpenTelemetry:

- W3C traceparent propagation
- Trace ID в логах и HTTP-заголовках
- Spans для каждого этапа RAG pipeline

**Критерий приёмки:**

1. `OTEL_ENABLED=true` — tracing активен
2. Trace ID присутствует в логах
3. Trace ID в HTTP-заголовках ответа

**Статус:** ⚠️ Код есть (`proxy/app/shared/tracing.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** best-practices-checklist 4.4

---

## Backup и DR (FR-165 — FR-167)

### FR-165. Automated backup scripts

**Описание:**
Скрипты для автоматического бэкапа:

- Qdrant snapshots — каждые 6 часов
- Neo4j dumps — каждые 6 часов
- Redis RDB — каждый час
- ETL WAL state — каждые 30 минут

Бэкапы сохраняются в S3/MinIO.

**Критерий приёмки:**

1. Скрипты выполняются по расписанию (cron)
2. Бэкапы сохраняются в S3 bucket
3. Лог: "Backup completed: X MB"

**Статус:** ⚠️ Код есть (`scripts/ops/`), нужен smoke test
**Приоритет:** CRITICAL
**Связь:** disaster-recovery-runbook

---

### FR-166. Disaster recovery runbook ✅

**Описание:**
Runbook покрывает 8 сценариев:

1. Потеря Qdrant — restore from snapshot
2. Потеря Neo4j — restore from dump
3. Потеря Redis — rebuild from source
4. Отказ ноды — failover
5. Network partition — graceful degradation
6. Полный outage — full restore
7. LLM backend failure — fallback
8. Disk full — cleanup + expand

**Критерий приёмки:**

1. Для каждого сценария — пошаговая инструкция
2. RTO < 30 минут
3. RPO < 1 час

**Статус:** ✅ Подтверждено (документация есть)
**Приоритет:** CRITICAL
**Связь:** disaster-recovery-runbook.md

---

### FR-167. Restore script

**Описание:**
Скрипт `restore_all.sh` восстанавливает все сервисы из бэкапа:

- `--latest` — последний бэкап
- `--date YYYY-MM-DD` — бэкап на дату
- Проверка целостности после restore

**Критерий приёмки:**

1. `restore_all.sh --latest` — все сервисы восстановлены
2. Данные доступны после restore
3. Health check проходит

**Статус:** ⚠️ Код есть (`scripts/ops/restore_all.sh`), нужен smoke test
**Приоритет:** CRITICAL
**Связь:** disaster-recovery-runbook

---

## Performance (FR-168 — FR-173)

### FR-168. Qdrant scalar quantization (INT8)

**Описание:**
Qdrant использует INT8 квантизацию для векторов, снижая потребление памяти в 4 раза
с минимальной потерей качества (MRR drop ≤ 2%).

**Критерий приёмки:**

1. Коллекция создана с quantization_config
2. Потребление памяти ≤ 50% от неквантизированной
3. MRR drop ≤ 2%

**Статус:** ⚠️ Нужно проверить настройки в init_collections.py
**Приоритет:** HIGH
**Связь:** NFR-P07, NFR-P13

---

### FR-169. Qdrant gRPC client

**Описание:**
Прокси подключается к Qdrant через gRPC (prefer_grpc=True) для снижения latency.
HTTP используется как fallback.

**Критерий приёмки:**

1. `prefer_grpc=True` в настройках клиента
2. Retrieval latency p50 < 130ms
3. Fallback на HTTP при недоступности gRPC

**Статус:** ⚠️ Нужно проверить настройки в retrieval.py
**Приоритет:** HIGH
**Связь:** NFR-P02

---

### FR-170. vLLM prefix caching ⚠️ partial

**Описание:**
vLLM кэширует prefix (system prompt) для снижения TTFT на 50%+ при повторных
запросах с тем же system prompt.

**Критерий приёмки:**

1. `--enable-prefix-caching` включён на vLLM
2. Gauge `rag_vllm_prefix_cache_hit_ratio` ≥ 40%
3. TTFT снижается на ≥ 50%

**Статус:** ⚠️ Partial (gauge добавлен, нужен мониторинг)
**Приоритет:** HIGH
**Связь:** NFR-P08

---

### FR-171. HNSW tuning

**Описание:**
Параметры HNSW индекса настраиваются под размер коллекции:

- < 100K vectors: m=16, ef_construct=128, ef_search=64
- 100K-1M: m=24, ef_construct=192, ef_search=128
- > 1M: m=32, ef_construct=256, ef_search=200

**Критерий приёмки:**

1. Параметры соответствуют размеру коллекции
2. Recall@10 ≥ 0.95
3. Latency в допустимых пределах

**Статус:** ⚠️ Нужно проверить настройки
**Приоритет:** HIGH
**Связь:** NFR-P13

---

### FR-173. Model warm-up

**Описание:**
При старте система «прогревает» модели (embedder, reranker, SLM) dummy-запросами
для устранения cold-start latency.

**Критерий приёмки:**

1. Warm-up выполняется при старте (если `WARMUP_ON_STARTUP=true`)
2. Первый реальный запрос — latency в пределах 100ms от 10-го
3. Warm-up duration < 30s

**Статус:** ⚠️ Код есть (`proxy/app/shared/warmup.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** NFR-P12

---

## Multi-Modal (FR-174 — FR-175)

### FR-174. AST-based code chunking

**Описание:**
Исходный код разбивается по AST-структуре:

- Python: по функциям и классам (через `ast` модуль)
- JavaScript: по функциям и классам (через tree-sitter)
- Java: по методам и классам

**Критерий приёмки:**

1. Python-файл с 5 функциями → 5 чанков
2. Каждый чанк содержит полную функцию (не обрезанную)
3. Контекст (имя файла, класса) добавляется в метаданные

**Статус:** ⚠️ Код есть (`etl/chunker/code_chunker.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** roadmap Phase 5.2

---

### FR-175. Table extraction from Confluence

**Описание:**
Таблицы из Confluence-страниц извлекаются в структурированном виде и индексируются
отдельно. Запрос «какая таблица X?» возвращает структурированные данные.

**Критерий приёмки:**

1. Confluence-страница с таблицей → таблица извлечена
2. Таблица индексируется как отдельный чанк с type=table
3. Поиск по таблице возвращает структурированные данные

**Статус:** ⚠️ Код есть (`etl/chunker/table_extractor.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** roadmap Phase 5.3
