# Часть 2. Нефункциональные требования (NFR)

---

## NFR-P: Производительность

### NFR-P01. End-to-end latency p95 < 5s

**Описание:**
Общее время от запроса до ответа (p95) < 5 секунд для обычного запроса,
< 2 секунд для простого, < 8 секунд для агентского (с tool calls).

**Критерий приёмки:**
1. Prometheus histogram `rag_request_duration_seconds` p95 < 5s
2. Нагрузочный тест: 50 concurrent users, p95 < 5s

**Статус:** ⚠️ Нужен нагрузочный тест
**Связь:** SLI/SLO

---

### NFR-P02. Retrieval latency p95 < 200ms

**Описание:**
Время гибридного поиска в Qdrant (p95) < 200ms через HTTP, < 130ms через gRPC.

**Критерий приёмки:**
1. Prometheus `retrieval_duration_seconds` p95 < 0.2s
2. С gRPC — p95 < 0.13s

**Статус:** ⚠️ Нужен бенчмарк
**Связь:** NFR-P02

---

### NFR-P03. TTFT p50 < 1s (cached)

**Описание:**
Time To First Token (p50) < 1s для кэшированных ответов, < 2s для некэшированных.

**Критерий приёмки:**
1. Prometheus `rag_ttft_seconds` p50 < 1s (cached)
2. Prometheus `rag_ttft_seconds` p50 < 2s (uncached)

**Статус:** ⚠️ Нужен бенчмарк
**Связь:** SLI/SLO

---

### NFR-P04. Embedding cache hit ratio ≥ 60%

**Описание:**
≥ 60% запросов должны попадать в embedding cache.

**Критерий приёмки:**
1. Prometheus `rag_cache_hit_ratio{cache_type="embedding"}` ≥ 0.6

**Статус:** ⚠️ Нужна метрика
**Связь:** NFR-P04

---

### NFR-P05. Response cache hit ratio ≥ 30%

**Описание:**
≥ 30% запросов должны попадать в response cache.

**Критерий приёмки:**
1. Prometheus counter ≥ 30% hit ratio

**Статус:** ⚠️ Нужна метрика
**Связь:** NFR-P05

---

### NFR-P06. Reranker latency p95 < 200ms

**Описание:**
Reranking top-50 → top-20 (p95) < 200ms.

**Критерий приёмки:**
1. Prometheus `rag_rerank_duration_seconds` p95 < 0.2s

**Статус:** ⚠️ Нужен бенчмарк
**Связь:** NFR-P06

---

### NFR-P07. Qdrant memory (quantized) ≤ 50%

**Описание:**
С INT8 квантизацией потребление памяти ≤ 50% от неквантизированного.

**Критерий приёмки:**
1. Qdrant /metrics показывает ≤ 50% memory usage

**Статус:** ❌ Нужно проверить
**Связь:** NFR-P07

---

### NFR-P08. vLLM prefix cache hit ≥ 40%

**Описание:**
≥ 40% system prompt tokens должны попадать в prefix cache.

**Критерий приёмки:**
1. vLLM metrics endpoint показывает ≥ 40% hit rate

**Статус:** ❌ Нужно проверить
**Связь:** NFR-P08

---

### NFR-P09. ETL OCR throughput ≤ 5min/100 pages

**Описание:**
OCR 100-страничного PDF ≤ 5 минут.

**Критерий приёмки:**
1. 100-страничный PDF — обработка ≤ 5 мин

**Статус:** ❌ Нужен бенчмарк
**Связь:** NFR-P09

---

### NFR-P10. ETL streaming latency < 5s

**Описание:**
От webhook-события до searchable chunk — < 5 секунд.

**Критерий приёмки:**
1. Prometheus `rag_etl_stream_processing_duration_seconds` < 5s

**Статус:** ⚠️ Нужен бенчмарк
**Связь:** NFR-P10

---

### NFR-P11. Response compression ≥ 60% ✅

**Описание:**
Gzip/Brotli сжимает JSON-ответы на ≥ 60%.

**Критерий приёмки:**
1. Content-Length comparison: compressed ≤ 40% of original

**Статус:** ✅ Подтверждено
**Связь:** NFR-P11

---

### NFR-P12. Warm-up duration < 30s

**Описание:**
Прогрев всех моделей (embedder + reranker + SLM) < 30 секунд.

**Критерий приёмки:**
1. Prometheus `rag_warmup_duration_seconds` < 30s

**Статус:** ⚠️ Нужен бенчмарк
**Связь:** NFR-P12

---

### NFR-P13. Retrieval quality under quantization — MRR drop ≤ 2%

**Описание:**
INT8 квантизация не должна снижать MRR более чем на 2%.

**Критерий приёмки:**
1. MRR(quantized) ≥ MRR(full) - 0.02

**Статус:** ❌ Нужен бенчмарк
**Связь:** NFR-P13

---

## NFR-A: Доступность

### NFR-A01. Service availability 99.5%

**Описание:**
Система доступна 99.5% времени (~3.6 часа простоя/месяц).

**Критерий приёмки:**
1. Prometheus `up{job="rag-proxy"}` ≥ 99.5%

**Статус:** ⚠️ Нужен мониторинг
**Связь:** SLI/SLO

---

### NFR-A02. Error rate 5xx < 1%

**Описание:**
< 1% запросов возвращают 5xx.

**Критерий приёмки:**
1. Prometheus `rag_requests_total{status=~"5.."}` / total < 0.01

**Статус:** ⚠️ Нужен мониторинг
**Связь:** SLI/SLO

---

### NFR-A03. Backup RPO < 1 hour

**Описание:**
Максимальная потеря данных при сбое — 1 час.

**Критерий приёмки:**
1. Backup schedule: Qdrant 6h, Neo4j 6h, Redis 1h, WAL 30min
2. Redis backup — RPO < 1h

**Статус:** ⚠️ Нужно проверить cron
**Связь:** SLI/SLO

---

### NFR-A04. Backup RTO < 30 min

**Описание:**
Восстановление из бэкапа — < 30 минут.

**Критерий приёмки:**
1. DR drill: restore_all.sh — завершается за < 30 мин

**Статус:** ❌ Нужен DR drill
**Связь:** SLI/SLO

---

### NFR-A05. Graceful degradation

**Описание:**
Прокси НЕ падает при недоступности любого компонента. Neo4j down → skip graph.
Reranker OOM → use raw scores. Redis down → in-memory cache.

**Критерий приёмки:**
1. Chaos test: каждый компонент down — прокси отвечает 200

**Статус:** ⚠️ Нужен chaos test
**Связь:** CON-02

---

### NFR-A06. ETL WAL survival

**Описание:**
ETL возобновляется с последнего checkpoint после сбоя.

**Критерий приёмки:**
1. Kill ETL на этапе embedding — restart начинается с embedding

**Статус:** ⚠️ Нужен интеграционный тест
**Связь:** CON-09

---

## NFR-S: Безопасность

### NFR-S01. 4 auth methods

**Описание:**
Система поддерживает: JWT, Keycloak OIDC, LDAP/AD, API keys.

**Критерий приёмки:**
1. Каждый метод — успешная аутентификация

**Статус:** ⚠️ Нужен интеграционный тест
**Связь:** access-control-rbac

---

### NFR-S02. RBAC enforcement

**Описание:**
4 роли, 5 access levels. Unauthorized → 403.

**Критерий приёмки:**
1. Unauthorized request → 403

**Статус:** ⚠️ Нужен интеграционный тест
**Связь:** access-control-rbac

---

### NFR-S03. ACL in Qdrant queries

**Описание:**
Каждый Qdrant-запрос включает ACL filter.

**Критерий приёмки:**
1. Restricted user — не видит restricted чанки

**Статус:** ⚠️ Нужен интеграционный тест
**Связь:** NFR-S03

---

### NFR-S04. RBAC by default

**Описание:**
Все эндпоинты требуют auth если не явно public.

**Критерий приёмки:**
1. Без токена → 401 на protected endpoints

**Статус:** ⚠️ Нужен интеграционный тест
**Связь:** NFR-S04

---

### NFR-S05. Secret masking in logs

**Описание:**
Все credentials маскируются в логах (заменяются на `***`).

**Критерий приёмки:**
1. grep logs — нет секретов в открытом виде

**Статус:** ⚠️ Нужна проверка
**Связь:** best-practices-checklist 3.1

---

### NFR-S09. HTTPS/TLS

**Описание:**
TLS 1.3 на reverse proxy, HSTS header, HTTP → HTTPS redirect.

**Критерий приёмки:**
1. HSTS header present
2. HTTP redirect → HTTPS

**Статус:** ❌ Нужно настроить nginx
**Связь:** best-practices-checklist 3.7

---

### NFR-S10. Audit logging

**Описание:**
Все auth events, admin actions, config changes логируются.

**Критерий приёмки:**
1. audit.jsonl содержит записи

**Статус:** ⚠️ Нужна проверка
**Связь:** best-practices-checklist 3.10

---

### NFR-S11. K8s Secrets

**Описание:**
Credentials в K8s Secrets, не в ConfigMaps.

**Критерий приёмки:**
1. Helm template: secret refs, не literals

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-S11

---

### NFR-S12. Feedback abuse prevention

**Описание:**
100 feedback submissions/user/hour.

**Критерий приёмки:**
1. 101st submission → 429

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-S12

---

### NFR-S13. Shell tool safety

**Описание:**
Shell tools — whitelist-based validation.

**Критерий приёмки:**
1. Unsafe command → rejected at validation

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-S13

---

### NFR-S14. Tool handlers hidden

**Описание:**
Raw tool callables не exposed via API.

**Критерий приёмки:**
1. `/v1/tools/{name}` — нет handler field в response

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-S14

---

## NFR-D: Деплой

### NFR-D01. Docker Compose — one command

**Описание:**
`docker compose up -d` запускает все сервисы.

**Критерий приёмки:**
1. All health checks pass

**Статус:** ⚠️ Нужен smoke test
**Связь:** NFR-D01

---

### NFR-D02. Helm chart completeness

**Описание:**
Helm chart покрывает: proxy, ETL, Qdrant, Redis, Neo4j, MinIO, PostgreSQL, vLLM.

**Критерий приёмки:**
1. `helm template` рендерит все компоненты

**Статус:** ⚠️ Нужен smoke test
**Связь:** NFR-D02

---

### NFR-D03. Distributed Compose

**Описание:**
Single `docker-compose.distributed.yml` для multi-machine.

**Критерий приёмки:**
1. `docker-compose config` validates

**Статус:** ⚠️ Нужен smoke test
**Связь:** NFR-D03

---

### NFR-D04. Zero-downtime K8s deployment

**Описание:**
Rolling update: start new, wait healthy, drain old.

**Критерий приёмки:**
1. ab test: 0 failures during deploy

**Статус:** ❌ Нужна проверка
**Связь:** NFR-D04

---

### NFR-D05. Env-based configuration

**Описание:**
Все настройки через env vars, no hardcoded hostnames/ports.

**Критерий приёмки:**
1. grep: no hardcoded localhost in config

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-D05

---

### NFR-D06. Air-gapped compatibility

**Описание:**
Все модели и зависимости pre-downloadable.

**Критерий приёмки:**
1. `download_models_offline.py` — все модели скачиваются

**Статус:** ⚠️ Нужна проверка
**Связь:** CON-01

---

## NFR-M: Поддерживаемость

### NFR-M01. Runtime configuration hot-reload

**Описание:**
Non-secret settings можно менять без restart.

**Критерий приёмки:**
1. PATCH config → effect without restart

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-M01

---

### NFR-M02. Stale document monitoring

**Описание:**
Автоматическое обнаружение устаревших документов каждые 24 часа.

**Критерий приёмки:**
1. Cron job выполняется каждые 24h
2. Stale documents flagged

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-M02

---

### NFR-M03. Reindexing resilience

**Описание:**
3 retry с exponential backoff при ошибках переиндексации.

**Критерий приёмки:**
1. Ошибка → 3 retry → DLQ

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-M03

---

### NFR-M04. Cache key namespacing ✅

**Описание:**
Proxy и OpenWebUI используют разные namespace prefix для Redis keys.

**Критерий приёмки:**
1. Proxy keys: `proxy:*`
2. OpenWebUI keys: `openwebui:*`
3. No collisions

**Статус:** ✅ Подтверждено
**Связь:** NFR-M04

---

### NFR-M05. Feedback preservation through reindex

**Описание:**
Feedback сохраняется при переиндексации документов.

**Критерий приёмки:**
1. Reindex → feedback привязан к новому chunk_id

**Статус:** ⚠️ Нужен интеграционный тест
**Связь:** NFR-M05

---

### NFR-M06. Code quality ✅

**Описание:**
ruff lint 0 warnings, ruff format clean, mypy strict 0 errors, 80% coverage.

**Критерий приёмки:**
1. `make lint && make typecheck && make test` — all green

**Статус:** ✅ Подтверждено
**Связь:** NFR-M06

---

### NFR-M07. Test suite — 80% coverage ✅

**Описание:**
≥ 5000 tests, ≥ 80% coverage, CI green.

**Критерий приёмки:**
1. `make test` exits 0
2. Coverage ≥ 80%

**Статус:** ✅ Подтверждено
**Связь:** NFR-M07

---

### NFR-M08. Log rotation

**Описание:**
100MB per file, keep 10 files, compress old.

**Критерий приёмки:**
1. LOG_DIR files under limits

**Статус:** ⚠️ Нужна проверка
**Связь:** NFR-M08

---

## NFR-Q: Качество RAG

### NFR-Q01. Retrieval MRR > 0.80

**Описание:**
Mean Reciprocal Rank > 0.80 на evaluation dataset.

**Критерий приёмки:**
1. `evaluate_retrieval.py` — MRR > 0.80

**Статус:** ❌ Нужно запустить eval pipeline
**Связь:** rag-maturity-assessment

---

### NFR-Q02. Recall@20 > 0.90

**Описание:**
Recall при top-20 > 0.90.

**Критерий приёмки:**
1. `evaluate_retrieval.py` — Recall@20 > 0.90

**Статус:** ❌ Нужно запустить eval pipeline
**Связь:** rag-maturity-assessment

---

### NFR-Q03. nDCG@10 > 0.85

**Описание:**
Normalized Discounted Cumulative Gain при top-10 > 0.85.

**Критерий приёмки:**
1. `evaluate_retrieval.py` — nDCG@10 > 0.85

**Статус:** ❌ Нужно запустить eval pipeline
**Связь:** rag-maturity-assessment

---

### NFR-Q04. Precision@5 > 0.70

**Описание:**
Precision при top-5 > 0.70.

**Критерий приёмки:**
1. `evaluate_retrieval.py` — Precision@5 > 0.70

**Статус:** ❌ Нужно запустить eval pipeline
**Связь:** rag-maturity-assessment

---

### NFR-Q05. Context grounding score > 0.70

**Описание:**
Косинусное сходство ответа и контекста > 0.70 для well-grounded ответов.

**Критерий приёмки:**
1. Cosine similarity(embed(answer), embed(context)) > 0.70

**Статус:** ⚠️ Нужна проверка
**Связь:** rag-maturity-assessment

---

### NFR-Q06. Hallucination rate < 5%

**Описание:**
< 5% ответов содержат галлюцинации (unsupported claims).

**Критерий приёмки:**
1. NLI entailment check — hallucination rate < 5%

**Статус:** ⚠️ Нужна проверка
**Связь:** rag-maturity-assessment

---

### NFR-Q07. Chunker semantic coherence > 0.75

**Описание:**
Intra-chunk cosine similarity > 0.75.

**Критерий приёмки:**
1. Chunker evaluation — coherence > 0.75

**Статус:** ❌ Нужен бенчмарк
**Связь:** performance-quality

---

### NFR-Q08. Chunker boundary precision > 0.85

**Описание:**
Границы чанков совпадают с section/heading breaks в > 85% случаев.

**Критерий приёмки:**
1. Chunker evaluation — boundary precision > 0.85

**Статус:** ❌ Нужен бенчмарк
**Связь:** performance-quality

---

### NFR-Q09. Confidence > 0.5 rate > 70%

**Описание:**
> 70% ответов имеют confidence > 0.5.

**Критерий приёмки:**
1. Prometheus `rag_confidence_score_high_ratio` > 0.7

**Статус:** ⚠️ Нужна метрика
**Связь:** SLI/SLO

---

### NFR-Q10. Self-reflection correlation with expert feedback

**Описание:**
Self-reflection score коррелирует с expert feedback (статистически значимо).

**Критерий приёмки:**
1. A/B comparison — correlation significant

**Статус:** ❌ Нужен A/B тест
**Связь:** rag-maturity-assessment

---

### NFR-Q11. Eval gate thresholds

**Описание:**
- SLM: F1 ≥ 0.85
- LLM: BertScore ≥ 0.70, hallucination ≤ 0.05
- Reranker: MRR ≥ baseline + 0.02, Rouge-L ≥ 0.35

**Критерий приёмки:**
1. EvalGate run — thresholds enforced

**Статус:** ⚠️ Нужна проверка
**Связь:** ADR-010

---

## NFR-C: Ёмкость и масштабируемость

### NFR-C01. 50 concurrent users (p95 < 5s)

**Описание:**
Система обрабатывает 50 одновременных пользователей с p95 < 5s.

**Критерий приёмки:**
1. Load test: 50 concurrent — p95 < 5s

**Статус:** ❌ Нужен нагрузочный тест
**Связь:** roadmap Phase 7.2

---

### NFR-C02. Qdrant collection size < 1M vectors

**Описание:**
Default HNSW для < 1M vectors. Quantization для > 1M.

**Критерий приёмки:**
1. Collection stats — correct config for size

**Статус:** ⚠️ Нужна проверка
**Связь:** performance-quality

---

### NFR-C03. Qdrant sharding

**Описание:**
4 shards для 10M-50M, 8 shards > 50M vectors.

**Критерий приёмки:**
1. Collection config — correct shards

**Статус:** ⚠️ Нужна проверка
**Связь:** performance-quality

---

### NFR-C04. ETL parallel extraction

**Описание:**
3 Confluence workers, 5 Jira workers, 3 GitLab workers.

**Критерий приёмки:**
1. Thread count monitoring — correct workers

**Статус:** ⚠️ Нужна проверка
**Связь:** performance-quality

---

### NFR-C05. Cold storage

**Описание:**
Current + 1 prior version in Qdrant, older in Parquet.

**Критерий приёмки:**
1. Version manifest — correct stratification

**Статус:** ⚠️ Нужна проверка
**Связь:** performance-quality

---

# Часть 3. Constraints (ограничения)

| ID | Описание | Рационал |
|----|----------|----------|
| CON-01 | **Air-gapped first.** Все модели pre-downloaded. Нет внешних API вызовов. | Корпоративная безопаcность |
| CON-02 | **Graceful degradation.** Каждый компонент может упасть независимо. | Resilience |
| CON-03 | **Single worker proxy.** `WORKERS=1` для защиты shared state. | Race condition prevention |
| CON-04 | **Python/FastAPI for proxy.** Java/Quarkus rejected. | ML ecosystem |
| CON-05 | **BAAI/bge-m3 as sole embedder.** 1024-dim, 100+ languages. | Single model |
| CON-06 | **Qdrant as primary vector store.** RRF fusion. | Single deployment |
| CON-07 | **OpenAI-compatible API.** RAG extensions additive. | Drop-in replacement |
| CON-08 | **Content-addressable chunks.** SHA-256 hashing. | Dedup + versioning |
| CON-09 | **WAL-based incremental ETL.** Checkpointing per stage. | Resume after failure |
| CON-10 | **Optional complexity.** LangGraph/Neo4j/Redis optional. | Low barrier |
| CON-11 | **Dual-model routing.** SLM for routing, LLM for generation. | Latency + quality |
| CON-12 | **Multi-provider LLM backend.** Pluggable adapters. | No vendor lock-in |
| CON-13 | **Token economy.** BPE-aware counting, 4 strategies. | Cost optimization |
| CON-14 | **Python 3.11+.** Minimum version. | Language constraint |
| CON-15 | **Ruff for linting.** line-length=120. | Code style |
| CON-16 | **mypy strict mode** for proxy/app/. | Type safety |
| CON-17 | **Coverage ≥ 80%.** | Testing quality |
| CON-18 | **granian ASGI server** (not uvicorn). | Performance |
| CON-19 | **MinIO for object storage.** S3-compatible. | Air-gapped |
| CON-20 | **MLflow for experiment tracking.** Self-hosted. | Reproducibility |
| CON-21 | **LoRA/QLoRA for fine-tuning.** Not full fine-tune. | Small adapters |
| CON-22 | **Application-layer canary.** Weighted random split. | Simple rollback |
| CON-23 | **Hot-reload via file watcher + SIGHUP.** | Process-local swap |
| CON-24 | **HITL feedback → fine-tuning closed loop.** | Continuous improvement |
| CON-25 | **English for code.** Docs bilingual (RU + EN). | Team policy |
| CON-26 | **FastMCP for MCP server.** Dual transport. | Standard protocol |
| CON-27 | **Streamlit for HITL dashboard.** | Lightweight |
| CON-28 | **SQLite for user DB.** PostgreSQL optional. | Simplicity |
