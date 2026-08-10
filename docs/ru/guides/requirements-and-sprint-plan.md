# RAG System — Единые требования и план спринта S5-2026

**Статус:** Draft  
**Дата:** 2026-07-17  
**Автор:** Product Manager & Business Analyst  
**Предыдущий спринт:** [S4-2026](sprint-plan-2026-s4.md) — Complete  
**Вход:** Cross-team research gap analysis (R1–R13)

---

## Executive Summary

Три параллельные исследовательские команды идентифицировали 12 пробелов требований в RAG-системе, охватывающих критические блоки функциональности через оптимизацию производительности. Этот документ синтезирует все находки в единый FR каталог, NFR каталог и 5-волновой план спринта для S5-2026.

**Область:** 24 всего items — 12 CRITICAL, 12 HIGH — организованы в 5 волн за ~10 недель.  
**Цель:** Разрешить все CRITICAL items. Решить HIGH items по скорости команды.

---

## 1. Функциональные требования

### FR-01: Knowledge Status Flag в API ответе
**Источник:** R6-Knowledge | **Приоритет:** CRITICAL | **Оценка:** S (4ч)

Chat completion ответ ДОЛЖЕН включать структурированное поле `rag_knowledge_status` указывающее качество и полноту знаний использованных для генерации ответа.

**Критерии приёмки:**
- [ ] `rag_knowledge_status` present в каждом `/v1/chat/completions` ответе (streaming и не-streaming)
- [ ] Поле содержит как минимум: `status` (enum: `sufficient`, `partial`, `insufficient`, `absent`), `chunks_found` (int), `chunks_used` (int), `confidence_threshold_met` (bool)
- [ ] Когда `status` — `insufficient` или `absent`, тело ответа чётко сигнализирует это клиенту
- [ ] Поле задокументировано в OpenAPI spec
- [ ] Тесты верифицируют: sufficient retrieval, empty retrieval, partial retrieval, edge cases

**Файлы для модификации:**
```
proxy/app/api/chat.py                  — Заполнить rag_knowledge_status в ответе
proxy/app/core/retrieval.py            — Экспонировать retrieval-quality metadata
proxy/app/core/context/builder.py      — Трекать chunks_found vs chunks_used
```

---

### FR-02: Conversational Context Management
**Источник:** R13-Conversation | **Приоритет:** CRITICAL | **Оценка:** M (12ч)

Chat endpoint ДОЛЖЕН накапливать conversational context через multi-turn session и использовать его для улучшения релевантности retrieval и когерентности ответа.

**Критерии приёмки:**
- [ ] `ConversationMemory` класс подключён к `/v1/chat/completions` handler
- [ ] Сообщения из того же `session_id` накапливаются и передаются retriever как контекст
- [ ] Предыдущие Q&A пары в сессии влияют на расширение запроса (например, разрешение местоимений, трекинг темы)
- [ ] Session context ограничен (последние N turns или token cap) для предотвращения context overflow
- [ ] Session истекает после настраиваемого TTL (default: 30 мин)
- [ ] Redis-backed session storage когда Redis доступен; in-memory fallback иначе
- [ ] Тесты верифицируют: multi-turn context accumulation, session expiration, context bounding

**Файлы для модификации:**
```
proxy/app/api/chat.py                  — Передать session_id, подключить ConversationMemory
proxy/app/core/query_enhancer.py       — Использовать conversation context для расширения запроса
proxy/app/shared/cache.py              — Session storage (Redis + in-memory fallback)
```

---

### FR-03: Clarifying Questions при недостаточности знаний
**Источник:** R13-Conversation | **Приоритет:** CRITICAL | **Оценка:** M (8ч)

Когда система определяет что доступных знаний недостаточно для ответа на запрос, она ДОЛЖНА генерировать clarifying questions вместо low-confidence или hallucinated ответа.

**Критерии приёмки:**
- [ ] Когда `rag_knowledge_status.status` — `insufficient` или `absent`, LLM промптится генерировать clarifying questions
- [ ] Clarifying questions специфичны для темы запроса (не generic fallbacks)
- [ ] Контейнер ответа включает `"clarifying": true` и перечисляет 1–3 specific questions
- [ ] Настраиваемый порог контролирует когда clarification mode активируется (на основе confidence score)
- [ ] Пользователь может отвечать на clarifying questions в том же session context
- [ ] Тесты верифицируют: low-confidence triggering, sufficient-knowledge passthrough, question specificity

**Файлы для модификации:**
```
proxy/app/api/chat.py                  — Clarification mode в response builder
proxy/app/core/confidence.py           — Конфигурация порога clarification
proxy/app/llm/router.py                — Шаблон промпта clarifying-question
```

---

### FR-04: Post-Indexing Data Cleanup Pipeline
**Источник:** R8-ETL | **Приоритет:** CRITICAL | **Оценка:** M (16ч)

ETL pipeline ДОЛЖЕН очищать raw extracts, промежуточные чанки и устаревшие vector data после успешной индексации. WAL state ДОЛЖЕН персиститься для переживания перезапусков контейнеров.

**Критерии приёмки:**
- [ ] Cleanup stage выполняется после успешной Qdrant индексации, удаляя:
  - Raw extract файлы (текст уже хранится в Qdrant)
  - Промежуточные chunk artifacts
  - Cold storage artifacts старше `RETENTION_DAYS`
- [ ] Cleanup настраивается: `ETL_CLEANUP_ENABLED`, `ETL_CLEANUP_RETENTION_DAYS`, `ETL_CLEANUP_RAW_EXTRACTS`
- [ ] WAL state персистится на durable volume (PVC или host path), не ephemeral container storage
- [ ] WAL включает checkpoint snapshots так что перезапущенный ETL возобновляет с последнего чекпоинта
- [ ] Dry-run режим (`--dry-run-cleanup`) отчитывается что было бы удалено без удаления
- [ ] Тесты верифицируют: cleanup после успешной индексации, WAL resume после restart, dry-run reporting

**Файлы для модификации:**
```
etl/indexer/wal_manager.py             — Durable WAL persistence, checkpoint snapshots
etl/scheduler/run_etl.py               — Cleanup stage в pipeline
etl/config/etl_config.yaml             — Конфигурация cleanup
```

---

### FR-05: OCR Pipeline для сканированных документов
**Источник:** R10-Multimodal | **Приоритет:** CRITICAL | **Оценка:** HIGH (24ч)

ETL pipeline ДОЛЖЕН извлекать текст из сканированных документов (PDF, images) используя OCR движок, обеспечивая retrieval по сканированному контенту.

**Критерии приёмки:**
- [ ] Tesseract OCR движок интегрирован в pipeline извлечения документов
- [ ] PDF страницы которые не дают текста при прямом извлечении автоматически проходят через OCR
- [ ] Поддерживаемые форматы изображений: PNG, JPEG, TIFF, BMP (как standalone так и embedded в PDF)
- [ ] OCR язык настраивается через переменную окружения `OCR_LANGUAGE` (default: `eng+rus`)
- [ ] OCR результаты объединяются с извлечённым текстом и чанкятся вместе
- [ ] OCR обработка логируется со статистикой по страницам (страниц просканировано, символов извлечено)
- [ ] Производительность: 100-страничный сканированный PDF обрабатывается за 5 минут на CPU
- [ ] Тесты верифицируют: извлечение сканированных PDF, OCR embedded images, language fallback

**Файлы для модификации:**
```
etl/extractors/docs.py                  — OCR fallback для PDF страниц
etl/requirements_etl.txt                — Добавить pytesseract, pdf2image
```

---

### FR-06: Image Embedding Pipeline
**Источник:** R10-Multimodal | **Приоритет:** CRITICAL | **Оценка:** HIGH (20ч)

Модуль image embedding ДОЛЖНА производить meaningful векторные представления для изображений найденных в документах, вместо возврата пустых placeholder векторов.

**Критерии приёмки:**
- [ ] CLIP-based (или эквивалентная) vision модель генерирует embeddings для извлечённых изображений
- [ ] Image embeddings хранятся в Qdrant рядом с text chunks с `content_type: "image"`
- [ ] Изображения ассоциированы с их parent document через `parent_doc_id`
- [ ] Описания изображений (caption) генерируются vision моделью и хранятся как metadata
- [ ] Image retrieval поддерживается в гибридном поиске когда `rag_include_images` установлен
- [ ] Vision модель предзагружена для air-gapped окружений
- [ ] Тесты верифицируют: генерация image embeddings, хранение в Qdrant, гибридный поиск с изображениями, качество captions

**Файлы для модификации:**
```
etl/indexer/qdrant_hybrid.py            — Сохранение image embeddings с content_type
etl/extractors/docs.py                  — Извлечение embedded images из PDF
proxy/app/core/retrieval.py             — Image content type фильтр
```

---

### FR-07: User Feedback Submission
**Источник:** R11-Feedback | **Приоритет:** CRITICAL | **Оценка:** M (12ч)

Все аутентифицированные пользователи ДОЛЖНЫ иметь возможность отправлять feedback по RAG ответам, не только эксперты.

**Критерии приёмки:**
- [ ] `/v1/feedback` endpoint принимает submissions от любого аутентифицированного пользователя (не только `expert` роль)
- [ ] Feedback включает: rating (positive/negative), optional correction text, `rag_feedback_id` reference
- [ ] Новое `feedback_dimension: "retrieval_quality"` поддерживается наряду с существующими dimensions
- [ ] Пользователи видят свою историю feedback через `GET /v1/feedback?user_id=self`
- [ ] Защита от злоупотреблений: rate limit 100 feedback submissions per user per hour
- [ ] Тесты верифицируют: submission обычного пользователя, submission эксперта, retrieval-quality dimension, rate limiting

**Файлы для модификации:**
```
proxy/app/api/feedback.py               — Ослабить role check, добавить retrieval_quality dimension
proxy/app/auth/rbac.py                  — Добавить feedback:submit permission для всех ролей
proxy/app/shared/rate_limiter.py         — Feedback-специфичный rate limit
```

---

### FR-08: Feedback Review & Moderation Workflow
**Источник:** R11-Feedback | **Приоритет:** CRITICAL | **Оценка:** M (12ч)

Администраторы и эксперты ДОЛЖНЫ иметь инструменты для ревью, модерации и действий по пользовательскому feedback.

**Критерии приёмки:**
- [ ] `GET /v1/admin/feedback` возвращает пагинированный, фильтруемый feedback список (только admin/expert)
- [ ] Фильтры: по status (pending/reviewed/dismissed), по rating, по dimension, по date range
- [ ] `POST /v1/admin/feedback/{id}/review` отмечает feedback как reviewed с заметками модератора
- [ ] `POST /v1/admin/feedback/{id}/dismiss` отклоняет feedback с причиной
- [ ] Reviewed feedback с corrections может триггерить self-enrichment (optional flag)
- [ ] Действия модерации audit-логируются
- [ ] Тесты верифицируют: list/filter/review/dismiss workflows, audit trail, self-enrichment trigger

**Файлы для модификации:**
```
proxy/app/api/admin.py                  — Feedback management endpoints
proxy/app/core/hitl.py                  — Moderation state machine
proxy/app/core/enricher.py              — Self-enrichment из moderated feedback
```

---

### FR-09: Stale Document Detection
**Источник:** R12-Stale | **Приоритет:** CRITICAL | **Оценка:** M (12ч)

Система ДОЛЖНА обнаруживать документы которые вероятно устарели и флагировать их для ревью или переиндексации.

**Критерии приёмки:**
- [ ] Metadata поле `last_verified_at` хранится per document в Qdrant
- [ ] Scheduled job сканирует документы где `last_verified_at` старше `STALE_THRESHOLD_DAYS` (настраивается, default: 90)
- [ ] Устаревшие документы флагируются `stale: true` в metadata (видимо в retrieval результатах)
- [ ] Когда устаревший документ извлекается, ответ включает поле `rag_stale_sources` listing потенциально устаревшие источники
- [ ] `POST /v1/admin/stale/report` endpoint возвращает отчёт об устаревших документах сгруппированных по источнику
- [ ] Источники с live API (Confluence, Jira) могут проверяться на обновлённые версии
- [ ] Тесты верифицируют: stale detection job, response flagging, report generation, live-source version check

**Файлы для модификации:**
```
etl/scheduler/run_etl.py                — Stale detection scheduled job
proxy/app/core/live_sources.py          — Live version check для Confluence/Jira
proxy/app/core/retrieval.py             — Stale flag в retrieval результатах
proxy/app/api/admin.py                  — Stale report endpoint
```

---

### FR-10: Automated Reindexing Triggers
**Источник:** R12-Stale | **Приоритет:** CRITICAL | **Оценка:** M (12ч)

Устаревшие или изменённые документы ДОЛЖНЫ автоматически переиндексироваться без ручного вмешательства.

**Критерии приёмки:**
- [ ] Когда live source check идентифицирует обновлённую версию документа, reindexing job ставится в очередь
- [ ] Reindexing сохраняет `feedback_count`, `positive_feedback`, и user-contributed corrections от старой версии
- [ ] Старые vector entries удаляются после успешного reindex (нет дубликатов)
- [ ] Webhook endpoint `POST /v1/admin/reindex/trigger` принимает внешние reindexing сигналы (например, из CI/CD)
- [ ] Reindexing job status трекается через `GET /v1/admin/reindex/status/{job_id}`
- [ ] Failed reindexing jobs retry до 3 раз с exponential backoff
- [ ] Тесты верифицируют: live-source trigger, webhook trigger, feedback preservation, dedup после reindex, retry logic

**Файлы для модификации:**
```
etl/scheduler/run_etl.py                — Reindex job queue и orchestrator
proxy/app/api/admin.py                  — Reindex trigger и status endpoints
etl/indexer/qdrant_hybrid.py            — Сохранение metadata во время reindex
```

---

### FR-11: Runtime Configuration Management API
**Источник:** R9-Admin | **Приоритет:** HIGH | **Оценка:** M (12ч)

Администраторы ДОЛЖНЫ иметь возможность просматривать и изменять конфигурацию системы во время выполнения без перезапуска прокси.

**Критерии приёмки:**
- [ ] `GET /v1/admin/config` возвращает все несекретные значения конфигурации
- [ ] `PATCH /v1/admin/config` обновляет указанные значения конфигурации
- [ ] Изменения валидируются (type checking, range checking) перед применением
- [ ] Hot-reloadable settings вступают в силу немедленно; остальные требуют restart (чётко задокументировано)
- [ ] Изменения конфигурации audit-логируются с timestamp и admin identity
- [ ] Критические settings (LLM endpoint, model name, Qdrant host) требуют подтверждения
- [ ] Тесты верифицируют: read/write/validate цикл, audit trail, restart-required notification

**Файлы для модификации:**
```
proxy/app/api/admin.py                  — Config endpoints
proxy/app/shared/config.py              — Runtime config override mechanism
proxy/app/shared/audit.py               — Config change audit events
```

---

### FR-12: Usage Analytics Endpoint
**Источник:** R9-Admin | **Приоритет:** HIGH | **Оценка:** M (8ч)

Администраторы ДОЛЖНЫ иметь доступ к агрегированной usage analytics для мониторинга здоровья системы и adoption.

**Критерии приёмки:**
- [ ] `GET /v1/admin/analytics` возвращает time-series usage data с настраиваемым window (24h/7d/30d)
- [ ] Метрики включают: total requests, unique users, avg/p50/p95/p99 latency, cache hit rate, feedback ratio
- [ ] Метрики включают: top queries, top sources, retrieval-quality distribution, confidence-score distribution
- [ ] Данные sourced из Prometheus counters (when available) с JSON aggregation fallback
- [ ] Response — JSON с `summary` блоком и `time_series` массивом
- [ ] Тесты верифицируют: metric aggregation, time window filtering, Prometheus vs fallback

**Файлы для модификации:**
```
proxy/app/api/admin.py                  — Analytics endpoint
proxy/app/shared/metrics.py             — Metric aggregation queries
proxy/app/shared/cache.py               — Analytics caching (5-min TTL)
```

---

### FR-13: Data Quality Dashboard
**Источник:** R9-Admin | **Приоритет:** HIGH | **Оценка:** M (10ч)

Програмmatic API ДОЛЖЕН экспонировать data quality метрики чтобы Streamlit dashboard мог рендерить quality визуализации.

**Критерии приёмки:**
- [ ] `GET /v1/admin/data-quality` возвращает агрегированные quality метрики per source
- [ ] Метрики: documents indexed, stale count, avg chunks per doc, feedback score, last index time
- [ ] Метрики: chunk size distribution (histogram), content type breakdown
- [ ] Response включает per-source breakdown и overall summary
- [ ] Совместим с Streamlit dashboard data model (JSON формат)
- [ ] Тесты верифицируют: metric accuracy, source grouping, histogram generation

**Файлы для модификации:**
```
proxy/app/api/admin.py                  — Data quality endpoint
proxy/app/core/retrieval.py             — Qdrant count/facet queries
dashboard/app.py                        — Потребление data-quality API
```

---

### FR-14: Collection-Level ACL в Qdrant
**Источник:** R7-RBAC | **Приоритет:** HIGH | **Оценка:** M (12ч)

RBAC access restrictions ДОЛЖНЫ enforceиться на уровне Qdrant запроса, не только на уровне API, чтобы unauthorized documents никогда не извлекались.

**Критерии приёмки:**
- [ ] Qdrant запросы включают `must` фильтр с permitted коллекциями/access groups пользователя
- [ ] Access filter derived из JWT ролей пользователя и применяется прозрачно в `retrieval.py`
- [ ] Пользователи без permitted коллекций получают empty results (не 403) с `rag_knowledge_status: absent`
- [ ] Коллекции назначаются access labels через ETL metadata (`access_groups: ["engineering", "finance"]`)
- [ ] Access filter работает как с dense так и с sparse vector search
- [ ] Тесты верифицируют: restricted user видит только permitted content, unrestricted user видит всё, no-collection user видит пустоту

**Файлы для модификации:**
```
proxy/app/core/retrieval.py             — Применить access filter к Qdrant запросам
proxy/app/auth/rbac.py                  — JWT-to-access-group mapping
etl/indexer/qdrant_hybrid.py            — Сохранение access_groups в payload
```

---

### FR-15: Expert Knowledge Base Management Endpoints
**Источник:** R7-RBAC | **Приоритет:** HIGH | **Оценка:** M (8ч)

Эксперты ДОЛЖНЫ иметь API endpoints для управления контентом базы знаний: просмотр индексированных документов, запуск частичных переиндексаций и ревью metadata документов.

**Критерии приёмки:**
- [ ] `GET /v1/expert/documents` listing индексированных документов с metadata (source, date, status, feedback)
- [ ] `POST /v1/expert/documents/{id}/reindex` запускает reindex конкретного документа
- [ ] `POST /v1/expert/documents/{id}/flag` флагает документ для ревью с причиной
- [ ] `GET /v1/expert/documents/{id}/chunks` listing всех чанков документа
- [ ] Все expert endpoints требуют `expert` или `admin` роль
- [ ] Тесты верифицируют: RBAC enforcement, document listing, single-document reindex, chunk listing

**Файлы для модификации:**
```
proxy/app/api/admin.py                  — Expert KB management endpoints
proxy/app/auth/rbac.py                  — Expert role permissions
```

---

### FR-16: ETL Kubernetes & Unified Deployment Manifests
**Источник:** R1-Deploy | **Приоритет:** HIGH | **Оценка:** M (12ч)

ETL компонент ДОЛЖЕН быть развёртываемым через Kubernetes Helm chart и Docker Compose. Единый distributed deployment ДОЛЖЕН быть задокументирован и протестирован.

**Критерии приёмки:**
- [ ] ETL добавлен в Helm chart как optional компонент (`etl.enabled: true`)
- [ ] ETL Helm values включают: image, WAL PVC, config mount, cron schedule, resource limits
- [ ] ETL имеет `docker-compose.etl.yml` интегрированный с shared network
- [ ] Единый `docker-compose.distributed.yml` создан для multi-machine деплоя
- [ ] OpenWebUI добавлен в Helm chart (отсутствовал)
- [ ] Документация деплоя покрывает single-machine и distributed сценарии
- [ ] Тесты верифицируют: Helm template renders корректно, compose files запускают сервисы

**Файлы для модификации:**
```
deploy/k8s/helm/rag-system/templates/etl-deployment.yaml
deploy/k8s/helm/rag-system/values.yaml
proxy/docker-compose.yml                — Добавить ETL service
deploy/docker/docker-compose.distributed.yml  (NEW)
etl/Dockerfile.etl
```

---

### FR-17: Qdrant Scalar Quantization
**Источник:** R3-Performance | **Приоритет:** HIGH | **Оценка:** S (4ч)

Qdrant ДОЛЖЕН использовать scalar quantization для сокращения memory footprint и улучшения throughput запросов.

**Критерии приёмки:**
- [ ] Qdrant коллекции создаются с `quantization: ScalarQuantization` (default в `init_collections.py`)
- [ ] Тип квантования настраивается: `SCALAR` (default), `PRODUCT`, `BINARY`, или `NONE`
- [ ] Существующие коллекции могут мигрироваться к квантованию через флаг `recreate_on_quantization_change`
- [ ] Квантование сокращает использование памяти минимум на 50% (benchmark required)
- [ ] Качество retrieval (MRR) не деградирует более чем на 2% с включённым квантованием
- [ ] Тесты верифицируют: создание коллекции с квантованием, миграция, quality regression gate

**Файлы для модификации:**
```
scripts/init_collections.py             — Конфигурация quantization при создании коллекции
etl/indexer/qdrant_hybrid.py            — Квантование во время индексации
proxy/app/shared/config.py              — QUANTIZATION_TYPE setting
```

---

### FR-18: Qdrant gRPC Client
**Источник:** R3-Performance | **Приоритет:** HIGH | **Оценка:** M (8ч)

Qdrant клиент ДОЛЖЕН использовать gRPC протокол для более низкой задержки и более высокого throughput по сравнению с HTTP.

**Критерии приёмки:**
- [ ] `QdrantClient` инициализируется с `prefer_grpc=True` когда `QDRANT_GRPC_PORT` настроен
- [ ] gRPC — default когда оба HTTP и gRPC порта доступны
- [ ] HTTP fallback seamless когда gRPC недоступен (graceful degradation)
- [ ] Connection pooling включён для gRPC (min 4, max 16 connections)
- [ ] p50 latency improvement минимум 30% vs HTTP (benchmark required)
- [ ] Тесты верифицируют: gRPC подключение, HTTP fallback, connection pool поведение

**Файлы для модификации:**
```
proxy/app/core/retrieval.py             — QdrantClient с gRPC preference
proxy/app/shared/config.py              — QDRANT_GRPC_PORT setting
etl/indexer/qdrant_hybrid.py            — gRPC для indexing throughput
```

---

### FR-19: vLLM Prefix Caching
**Источник:** R3-Performance | **Приоритет:** HIGH | **Оценка:** S (3ч)

vLLM prefix caching ДОЛЖЕН быть включён в конфигурации LLM backend для сокращения time-to-first-token для повторных system prompts.

**Критерии приёмки:**
- [ ] vLLM сервер настроен с флагом `--enable-prefix-caching`
- [ ] LLM клиент прокси использует consistent system prompt formatting для максимизации cache hits
- [ ] Time-to-first-token для кэшированных prompts снижен минимум на 50% (benchmark required)
- [ ] Поведение кэширования задокументировано для операторов
- [ ] Тесты верифицируют: cache hit detection, latency improvement

**Файлы для модификации:**
```
deploy/k8s/helm/rag-system/templates/vllm-deployment.yaml  — Добавить --enable-prefix-caching
proxy/app/llm/router.py                — Consistent prompt formatting
proxy/docker-compose.yml                — vLLM service flags
```

---

### FR-20: MinIO в Helm Chart
**Источник:** R4-ProxyData | **Приоритет:** HIGH | **Оценка:** M (8ч)

MinIO object storage ДОЛЖЕН быть развёртываемым через Helm chart для model artifacts, backup storage и file uploads.

**Критерии приёмки:**
- [ ] MinIO добавлен в Helm chart как optional компонент (`minio.enabled: true`)
- [ ] Helm values включают: image, PVC, access key, secret key, bucket auto-creation
- [ ] MinIO интегрирован с model evolution pipeline (MLflow artifact store)
- [ ] MinIO интегрирован с backup скриптами
- [ ] PostgreSQL добавлен в Helm chart для structured data (user DB, feedback store)
- [ ] Тесты верифицируют: Helm template renders MinIO, bucket creation, S3-compatible API health

**Файлы для модификации:**
```
deploy/k8s/helm/rag-system/templates/minio-deployment.yaml  (NEW)
deploy/k8s/helm/rag-system/templates/postgres-deployment.yaml  (NEW)
deploy/k8s/helm/rag-system/values.yaml
```

---

### FR-21: Redis Deduplication (Merge Proxy + OpenWebUI)
**Источник:** R4-ProxyData | **Приоритет:** HIGH | **Оценка:** S (3ч)

Redis instances для proxy и OpenWebUI ДОЛЖНЫ быть объединены в единый shared instance для сокращения дублирования ресурсов.

**Критерии приёмки:**
- [ ] Единый Redis сервис определён в `docker-compose.yml` (не отдельные proxy + OpenWebUI instances)
- [ ] Cache keys namespaced по сервису (например, `proxy:cache:*`, `openwebui:session:*`) для избежания коллизий
- [ ] Helm chart экспонирует единый Redis deployment с namespace конфигурацией
- [ ] Migration guide документирует как консолидировать существующие Redis данные
- [ ] Тесты верифицируют: proxy cache access, OpenWebUI session access, нет key collisions

**Файлы для модификации:**
```
proxy/docker-compose.yml                — Единый Redis сервис
deploy/docker/docker-compose.openwebui.yml  — Использовать shared Redis
deploy/k8s/helm/rag-system/templates/redis-deployment.yaml
```

---

### FR-22: ETL Persistent WAL Volume
**Источник:** R4-ProxyData | **Приоритет:** HIGH | **Оценка:** S (4ч)

ETL WAL ДОЛЖЕН храниться на persistent volume для переживания перезапусков контейнеров и обеспечения инкрементальной обработки.

**Критерии приёмки:**
- [ ] ETL Docker Compose сервис монтирует named volume для `/var/lib/etl/wal`
- [ ] Helm chart определяет PVC для ETL WAL данных
- [ ] WAL данные персистятся через `docker-compose down && docker-compose up`
- [ ] WAL включает checkpoint markers так что новый ETL контейнер возобновляет корректно
- [ ] Тесты верифицируют: WAL persistence через restarts, checkpoint resume

**Файлы для модификации:**
```
etl/docker-compose.etl.yml              — Named volume mount (already referenced в FR-16)
etl/indexer/wal_manager.py             — Checkpoint markers (already referenced в FR-04)
```

---

### FR-23: Progressive Context Gathering
**Источник:** R6-Knowledge | **Приоритет:** HIGH | **Оценка:** M (8ч)

Когда начальный retrieval даёт недостаточные результаты, система ДОЛЖНА прогрессивно расширять поиск используя альтернативные стратегии перед fallback на clarification.

**Критерии приёмки:**
- [ ] Если начальный retrieval даёт меньше чем `MIN_CHUNKS_THRESHOLD` (default: 3) релевантных чанков, система:
  1. Повторяет с HyDE расширением запроса
  2. Повторяет с keyword-only sparse search
  3. Расширяется до live sources (Confluence/Jira API)
  4. Fallback на clarification (FR-03)
- [ ] Каждый прогрессивный шаг логируется с количеством найденных чанков
- [ ] `rag_knowledge_status` отчитывается какие стратегии были попробованы
- [ ] Настраивается: `PROGRESSIVE_RETRIEVAL_ENABLED`, `MIN_CHUNKS_THRESHOLD`, `MAX_RETRIEVAL_ROUNDS`
- [ ] Тесты верифицируют: progressive expansion chain, вклад каждой стратегии, fallback на clarification

**Файлы для модификации:**
```
proxy/app/core/retrieval.py             — Progressive retrieval orchestrator
proxy/app/core/hyde.py                  — HyDE expansion в progressive chain
proxy/app/core/live_sources.py          — Live-source fallback в chain
```

---

### FR-24: HNSW Tuning Parameters
**Источник:** R3-Performance | **Приоритет:** HIGH | **Оценка:** S (3ч)

Qdrant HNSW index параметры ДОЛЖНЫ быть затюнены под характеристики датасета для оптимизации trade-off recall vs latency.

**Критерии приёмки:**
- [ ] HNSW параметры настраиваются per collection: `HNSW_M`, `HNSW_EF_CONSTRUCT`, `HNSW_EF_SEARCH`
- [ ] Sensible defaults установлены: `m=16`, `ef_construct=200`, `ef_search=128` (тюнится)
- [ ] Benchmark скрипт измеряет recall@k vs query latency для разных комбинаций параметров
- [ ] Рекомендации по тюнингу задокументированы для разных размеров датасетов (<100K, 100K–1M, >1M vectors)
- [ ] Тесты верифицируют: применение параметров, benchmark скрипт запускается

**Файлы для модификации:**
```
scripts/init_collections.py             — HNSW config параметры
etl/indexer/qdrant_hybrid.py            — HNSW config при создании коллекции
scripts/benchmark_hnsw.py               (NEW)
```

---

## 2. Нефункциональные требования

### NFR-1: Производительность

| ID      | Требование                      | Цель                                  | Измерение                          |
|---------|--------------------------------|---------------------------------------|--------------------------------------|
| NFR-1.1 | Retrieval latency (p95)       | <200ms (HTTP), <130ms (gRPC)         | Prometheus histogram `retrieval_duration_seconds` |
| NFR-1.2 | End-to-end latency (p95)       | <3s (simple), <8s (agentic)          | Prometheus histogram `request_duration_seconds` |
| NFR-1.3 | Qdrant memory (quantized)      | ≤50% от unquantized                   | Qdrant `/metrics` endpoint            |
| NFR-1.4 | Cache hit rate                  | ≥60% embedding cache, ≥30% rerank    | Prometheus counter `cache_hits_total` / `cache_requests_total` |
| NFR-1.5 | Prefix cache hit rate (vLLM)   | ≥40% для system prompt tokens        | vLLM metrics endpoint                 |
| NFR-1.6 | ETL OCR throughput              | ≤5 min per 100-page scanned PDF       | ETL job logs                          |
| NFR-1.7 | Retrieval quality regression    | MRR drop ≤2% с квантованием       | Evaluation pipeline (`evaluate_retrieval.py`) |

### NFR-2: Безопасность

| ID      | Требование                      | Цель                                  | Измерение                          |
|---------|--------------------------------|---------------------------------------|--------------------------------------|
| NFR-2.1 | ACL enforcement                | Access filter pushed к Qdrant запросу  | Integration тест: restricted user получает только permitted chunks |
| NFR-2.2 | Audit trail                     | Все config changes и moderation actions logged | Audit log query |
| NFR-2.3 | Feedback abuse prevention       | 100 submissions/user/hour макс         | Rate limiter counter                  |
| NFR-2.4 | RBAC default                    | RBAC включён по умолчанию для всех endpoints | Integration тест: unauthorized requests return 403 |
| NFR-2.5 | Secret isolation                | MinIO/PostgreSQL credentials в K8s secrets, не configmaps | Helm template validation |

### NFR-3: Deployability

| ID      | Требование                      | Цель                                  | Измерение                          |
|---------|--------------------------------|---------------------------------------|--------------------------------------|
| NFR-3.1 | Helm chart completeness         | Покрывает proxy, ETL, Qdrant, Redis, Neo4j, MinIO, PostgreSQL, vLLM | `helm template` renders все компоненты |
| NFR-3.2 | Distributed compose             | Единый `docker-compose.distributed.yml` для multi-machine | `docker-compose config` validates |
| NFR-3.3 | ETL network configurability     | Qdrant/Neo4j endpoints настраиваются через env vars | `docker-compose config` показывает env var interpolation |
| NFR-3.4 | WAL persistence                 | Переживает ETL container restart        | Integration тест: restart ETL, verify checkpoint resume |
| NFR-3.5 | Air-gapped compatibility        | Все модели и зависимости предзагружаемые | `download_models_offline.py` включает vision model |

### NFR-4: Maintainability

| ID      | Требование                      | Цель                                  | Измерение                          |
|---------|--------------------------------|---------------------------------------|--------------------------------------|
| NFR-4.1 | Runtime config                  | Non-secret settings hot-reloadable    | Integration тест: PATCH config, verify effect без restart |
| NFR-4.2 | Stale document monitoring       | Automated detection каждые 24ч         | Cron schedule в Helm chart           |
| NFR-4.3 | Reindexing resilience           | Retry 3x с exponential backoff     | ETL log verification                  |
| NFR-4.4 | Cache key namespacing           | Нет collisions между сервисами        | Integration тест: proxy и OpenWebUI keys не пересекаются |
| NFR-4.5 | Feedback data preservation      | Corrections survive reindex           | Integration тест: feedback preserved после reindex |

---

## 3. План спринта — S5-2026

### Обзор

| Волна  | Тема                        | Items   | Оценка часов | Цель         |
|--------|------------------------------|---------|------------|----------------|
| 1      | RAG Core Quality             | FR-01, FR-02, FR-03, FR-23 | 32ч   | Week 1–2       |
| 2      | Data Pipeline                | FR-04, FR-05, FR-06, FR-22 | 64ч   | Week 2–4       |
| 3      | Feedback & Evolution         | FR-07, FR-08, FR-09, FR-10 | 48ч   | Week 4–6       |
| 4      | Admin & RBAC                 | FR-11, FR-12, FR-13, FR-14, FR-15 | 50ч | Week 6–8   |
| 5      | Deployment & Performance     | FR-16, FR-17, FR-18, FR-19, FR-20, FR-21, FR-24 | 43ч | Week 8–10 |
| **Итого** |                          | **24**   | **237ч**   | **10 недель**   |

---

### Wave 1: RAG Core Quality (Week 1–2) — 32ч

> **Цель:** Сделать RAG опыт user-visible и заслуживающим доверия. Каждый ответ несёт сигнал о качестве знаний. Разговоры сохраняются через turns. Недостаточность знаний триггерит clarification вместо галлюцинации.

| ID     | Описание                           | Оценка | Роль               | Зависимости |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-01  | Knowledge status flag в API ответе | 4ч   | Backend Developer  | —            |
| FR-02  | Conversational context management     | 12ч  | Backend Developer  | FR-01        |
| FR-03  | Clarifying questions                  | 8ч   | Backend + LLM      | FR-01, FR-02 |
| FR-23  | Progressive context gathering         | 8ч   | Backend + ML       | FR-03        |

**Wave 1 Definition of Done:**
- [ ] Все 4 FRs имеют passing тесты
- [ ] `rag_knowledge_status` present во всех chat ответах
- [ ] Multi-turn conversation сохраняет context внутри TTL
- [ ] Low-confidence запросы генерируют specific clarifying questions
- [ ] Progressive retrieval chain пробует все стратегии перед fallback
- [ ] OpenAPI spec обновлён с новыми полями ответа

---

### Wave 2: Data Pipeline (Week 2–4) — 64ч

> **Цель:** Завершить ETL pipeline с cleanup, OCR, image embeddings и durable WAL. Каждый тип документа полностью индексирован.

| ID     | Описание                           | Оценка | Роль               | Зависимости |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-04  | Post-indexing data cleanup            | 16ч  | Backend + DevOps   | —            |
| FR-22  | ETL persistent WAL volume             | 4ч   | DevOps             | FR-04        |
| FR-05  | OCR pipeline для сканированных документов    | 24ч  | ML Engineer        | —            |
| FR-06  | Image embedding pipeline              | 20ч  | ML Engineer        | FR-05        |

**Wave 2 Definition of Done:**
- [ ] ETL cleanup удаляет raw extracts после индексации (dry-run tested)
- [ ] WAL персистится через container restarts с checkpoint resume
- [ ] OCR извлекает текст из сканированных PDF (eng+rus)
- [ ] CLIP embeddings хранятся в Qdrant с `content_type: image`
- [ ] Image captions сгенерированы и searchable
- [ ] Vision модель добавлена в offline download script

---

### Wave 3: Feedback & Evolution (Week 4–6) — 48ч

> **Цель:** Открыть feedback всем пользователям, добавить moderation workflow, обнаруживать устаревшие документы, автоматизировать переиндексацию.

| ID     | Описание                           | Оценка | Роль               | Зависимости |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-07  | User feedback submission              | 12ч  | Backend Developer  | —            |
| FR-08  | Feedback review & moderation          | 12ч  | Backend Developer  | FR-07        |
| FR-09  | Stale document detection              | 12ч  | Backend + DevOps   | —            |
| FR-10  | Automated reindexing triggers         | 12ч  | Backend + DevOps   | FR-09        |

**Wave 3 Definition of Done:**
- [ ] Все аутентифицированные пользователи могут отправлять feedback (rate-limited)
- [ ] `retrieval_quality` dimension доступен в feedback
- [ ] Admins/experts могут ревьюить, dismiss и trigger enrichment из feedback
- [ ] Scheduled job флагирует устаревшие документы ежедневно
- [ ] Live-source version changes триггерят automatic reindex
- [ ] Reindex сохраняет feedback metadata

---

### Wave 4: Admin & RBAC (Week 6–8) — 50ч

> **Цель:** Администраторы получают runtime config, analytics и data quality дашборды. RBAC enforceится на уровне vector database.

| ID     | Описание                           | Оценка | Роль               | Зависимости |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-11  | Runtime config management API         | 12ч  | Backend Developer  | —            |
| FR-12  | Usage analytics endpoint              | 8ч   | Backend + DevOps   | —            |
| FR-13  | Data quality dashboard API            | 10ч  | Backend + Frontend | FR-12        |
| FR-14  | Collection-level ACL в Qdrant        | 12ч  | Backend + Auth     | —            |
| FR-15  | Expert KB management endpoints        | 8ч   | Backend Developer  | FR-14        |

**Wave 4 Definition of Done:**
- [ ] Runtime config PATCHable с validation и audit
- [ ] Analytics endpoint возвращает time-series usage data
- [ ] Data quality API обслуживает метрики для Streamlit dashboard
- [ ] Qdrant запросы включают user-specific access filters
- [ ] Experts могут listing, флагировать и переиндексировать individual documents
- [ ] RBAC включён по умолчанию для всех endpoints

---

### Wave 5: Deployment & Performance (Week 8–10) — 43ч

> **Цель:** Production-grade деплой с K8s/Compose completeness. Оптимизации производительности для latency и throughput.

| ID     | Описание                           | Оценка | Роль               | Зависимости |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-16  | ETL K8s + unified deployment          | 12ч  | DevOps             | FR-22        |
| FR-20  | MinIO + PostgreSQL в Helm chart      | 8ч   | DevOps             | —            |
| FR-21  | Redis deduplication                   | 3ч   | DevOps             | —            |
| FR-17  | Qdrant scalar quantization            | 4ч   | ML + Backend       | —            |
| FR-18  | Qdrant gRPC client                    | 8ч   | Backend Developer  | —            |
| FR-19  | vLLM prefix caching                   | 3ч   | ML + DevOps        | —            |
| FR-24  | HNSW tuning                           | 3ч   | ML Engineer        | FR-17        |

**Wave 5 Definition of Done:**
- [ ] ETL deployable через Helm (`etl.enabled: true`) и Compose
- [ ] Единый distributed compose validated
- [ ] OpenWebUI в Helm chart
- [ ] MinIO и PostgreSQL в Helm chart
- [ ] Единый Redis instance (namespaced keys) для proxy + OpenWebUI
- [ ] Qdrant quantization включён (MRR regression ≤2%)
- [ ] gRPC default с HTTP fallback (p95 latency ≤130ms)
- [ ] vLLM prefix caching включён (TTFT reduced ≥50%)
- [ ] HNSW параметры затюнены и benchmarked
- [ ] Performance benchmarks перезапущены и опубликованы

---

## 4. Матрица рисков

| Риск                                    | Вероятность | Влияние | Митигация                                              |
|-----------------------------------------|-------------|---------|---------------------------------------------------------|
| OCR качество недостаточное для RU документов | MED | HIGH | Pre-test Tesseract с русскими + английскими mixed docs; fallback на EasyOCR |
| CLIP модель слишком большая для air-gapped | LOW   | HIGH   | Использовать ONNX-optimized CLIP-ViT-B/32 (580MB); задокументировать размер |
| Scalar quantization деградирует MRR >2%    | LOW   | MED    | Gate с retrieval eval pipeline; fallback на no quantization |
| ConversationMemory race conditions       | MED   | MED    | Redis locking для concurrent session writes |
| Feedback spam от regular users        | MED   | LOW    | Rate limiting + moderation queue |
| gRPC ломается в некоторых network configs  | LOW   | MED    | HTTP fallback автоматический и tested |
| ETL cleanup удаляет нужные raw data      | MED   | HIGH   | Dry-run режим обязателен перед enable; retention period buffer |
| Stale detection false positives          | MED   | LOW    | Настраиваемый порог; human review в moderation flow |
| Helm chart complexity grows unmaintainable | LOW | MED  | Template helper functions; validation в CI |

---

## 5. Сводка трудозатрат

| Волна  | Тема                    | FR Count | Часы | Кумулятивно |
|--------|--------------------------|----------|-------|------------|
| 1      | RAG Core Quality         | 4        | 32    | 32ч        |
| 2      | Data Pipeline            | 4        | 64    | 96ч        |
| 3      | Feedback & Evolution     | 4        | 48    | 144ч       |
| 4      | Admin & RBAC             | 5        | 50    | 194ч       |
| 5      | Deployment & Performance | 7        | 43    | 237ч       |
| **Итого** |                      | **24**   | **237ч** | —        |

---

## 6. Требуемые решения от человека

1. **FR-05 OCR:** Tesseract vs EasyOCR для русскоязычных документов? Tesseract рекомендуется для более широкой поддержки языков, EasyOCR для лучшей точности на сложных layouts.
2. **FR-06 Vision Model:** CLIP-ViT-B/32 (580MB, быстро) vs CLIP-ViT-L/14 (1.7GB, точнее)? Рекомендуется ViT-B/32 для air-gapped ограничений.
3. **FR-14 RBAC:** Должен ли RBAC быть включён по умолчанию (breaking change для существующих деплоев)? Рекомендуется да, с migration guide.
4. **FR-17 Quantization:** Применить квантование к существующим коллекциям или только новым? Рекомендуется migration script с opt-in флагом.
5. **Sprint cadence:** Один 10-недельный спринт или 2×5-недельных с midpoint review? Рекомендуется 10-week с bi-weekly checkpoints.

---

## 7. Traceability Matrix

| FR      | Источник пробела       | Волна | Приоритет |
|---------|------------------|------|----------|
| FR-01   | R6-Knowledge     | 1    | CRITICAL |
| FR-02   | R13-Conversation | 1    | CRITICAL |
| FR-03   | R13-Conversation | 1    | CRITICAL |
| FR-04   | R8-ETL           | 2    | CRITICAL |
| FR-05   | R10-Multimodal   | 2    | CRITICAL |
| FR-06   | R10-Multimodal   | 2    | CRITICAL |
| FR-07   | R11-Feedback     | 3    | CRITICAL |
| FR-08   | R11-Feedback     | 3    | CRITICAL |
| FR-09   | R12-Stale        | 3    | CRITICAL |
| FR-10   | R12-Stale        | 3    | CRITICAL |
| FR-11   | R9-Admin         | 4    | HIGH     |
| FR-12   | R9-Admin         | 4    | HIGH     |
| FR-13   | R9-Admin         | 4    | HIGH     |
| FR-14   | R7-RBAC          | 4    | HIGH     |
| FR-15   | R7-RBAC          | 4    | HIGH     |
| FR-16   | R1-Deploy        | 5    | HIGH     |
| FR-17   | R3-Performance   | 5    | HIGH     |
| FR-18   | R3-Performance   | 5    | HIGH     |
| FR-19   | R3-Performance   | 5    | HIGH     |
| FR-20   | R4-ProxyData     | 5    | HIGH     |
| FR-21   | R4-ProxyData     | 5    | HIGH     |
| FR-22   | R4-ProxyData     | 2    | HIGH     |
| FR-23   | R6-Knowledge     | 1    | HIGH     |
| FR-24   | R3-Performance   | 5    | HIGH     |

---

## 8. Приложение: Gap Coverage Verification

| Источник пробела         | Покрывается                              | Статус |
|---------------------|----------------------------------------|--------|
| R1-Deploy           | FR-16 (ETL K8s + unified deploy)       | ✅     |
| R2-Coupling         | FR-16 (unified compose), FR-21 (Redis merge) | ✅  |
| R3-Performance      | FR-17 (quantization), FR-18 (gRPC), FR-19 (vLLM cache), FR-24 (HNSW) | ✅ |
| R4-ProxyData        | FR-20 (MinIO Helm), FR-21 (Redis merge), FR-22 (WAL PVC) | ✅ |
| R6-Knowledge        | FR-01 (knowledge_status), FR-23 (progressive context) | ✅ |
| R7-RBAC             | FR-14 (collection ACL), FR-15 (expert KB) | ✅     |
| R8-ETL              | FR-04 (data cleanup), FR-22 (WAL persistence) | ✅ |
| R9-Admin            | FR-11 (runtime config), FR-12 (analytics), FR-13 (data quality) | ✅ |
| R10-Multimodal      | FR-05 (OCR), FR-06 (image embedding)    | ✅     |
| R11-Feedback        | FR-07 (user feedback), FR-08 (moderation) | ✅   |
| R12-Stale           | FR-09 (stale detection), FR-10 (reindexing) | ✅  |
| R13-Conversation    | FR-02 (conversation context), FR-03 (clarifying questions) | ✅ |
