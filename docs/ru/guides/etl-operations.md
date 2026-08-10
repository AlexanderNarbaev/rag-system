# Гайд по операциям ETL

**Версия:** v2.3.0

Практический гайд по операциям ETL-пайплайна RAG: streaming vs batch режим, настройка удалённых сервисов, инкрементальная загрузка, WAL-бэкенды, OCR/мультимодальная настройка и решение проблем.

---

## Быстрый старт

```bash
# Streaming режим (default) — extract→chunk→embed→index в один проход, без хранения на диске
make etl-run-streaming

# Batch режим — extract→collect→chunk→index с хранением на диске
make etl-run-batch

# Тест подключения ко всем источникам перед полным запуском
make etl-test-connection

# Очистка raw data и chunk файлов после успешной индексации
make etl-cleanup

# Запуск с кастомной конфигурацией
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode streaming

# Запуск только конкретного источника
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode streaming --source confluence

# Сброс WAL и принудительная полная переиндексация
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode batch --reset-wal --force-reindex

# Запуск только webhook-сервера (real-time ingestion)
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --webhook-only

# Запуск только stream consumer
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --consumer-only
```

---

## Streaming vs Batch режим

ETL-пайплайн имеет два режима работы, настраиваемых через `pipeline.mode` в `etl_config.yaml` или CLI флаг `--mode` (перезаписывает конфиг).

### Streaming режим (Default)

```
Extract → Chunk → Embed → Index
  └────── один документ за раз ──────┘
         (generator, без хранения на диске)
```

- **Поток:** Документы генерируются из директорий источников через генераторы, чанкятся немедленно, эмбеддятся через удалённый API (с semaphore-based backpressure) и индексируются в Qdrant атомарно через `live_upsert()` — всё в один проход.
- **Использование диска:** Нулевое. Ничего не пишется на диск; всё проходит через память.
- **Устойчивость:** WAL-чекпоинты обновляются после каждого документа. При прерывании повторный запуск пропускает уже проиндексированные чанки по SHA-256 хэшам.
- **Backpressure:** `streaming.max_concurrent_api_calls` (default 10) ограничивает concurrent embedder API вызовы через `asyncio.Semaphore`.
- **Логирование прогресса:** Каждые N документов (`streaming.progress_interval`, default 50).

**Когда использовать:**
- Высокообъёмная загрузка (тысячи документов)
- Окружения с ограниченной памятью, где не хотите копить raw data
- Когда удалённый embedder может обрабатывать concurrent запросы

**Конфигурация:**
```yaml
pipeline:
  mode: streaming
  batch_size: 10

streaming:
  progress_interval: 50
  max_concurrent_api_calls: 10
```

### Batch режим

```
Extract (parallel) → Collect → Chunk → Index
  ├── Confluence      └─ все docs в памяти ─┘
  ├── Jira
  └── GitLab
```

- **Поток:** Все источники извлекаются параллельно (ThreadPoolExecutor), затем все документы собираются в память, чанкятся в один проход и индексируются в один проход.
- **Использование диска:** Raw data и чанки сохраняются на диск по умолчанию (настраивается).
- **Устойчивость:** Каждый этап checkpointed. Используйте `--skip-extract`, `--skip-chunk`, `--skip-graph`, `--skip-index` для возобновления с любого этапа.
- **Параллельная загрузка:** Confluence, Jira и GitLab запускаются одновременно с graceful degradation — один сбой не останавливает остальные.

**Когда использовать:**
- Небольшие и средние базы знаний (<10k документов)
- Когда нужны промежуточные артефакты (raw data, чанки) для инспекции
- При запуске на машине с достаточным объёмом RAM

**Конфигурация:**
```yaml
pipeline:
  mode: batch
  save_raw: true
  save_chunks: true
```

### CLI-перезаписи

| Флаг | Эффект |
|------|--------|
| `--mode streaming` | Принудительный streaming режим (перезаписывает конфиг) |
| `--mode batch` | Принудительный batch режим |
| `--timeout 300` | Переопределить request timeout (секунды) |
| `--test-connection` | Протестировать подключения ко всем источникам и выйти |
| `--skip-extract` | Пропустить извлечение (использовать существующие raw data) |
| `--skip-chunk` | Пропустить чанкинг (использовать существующие чанки) |
| `--skip-graph` | Пропустить построение графа |
| `--skip-index` | Пропустить индексацию |
| `--force-reindex` | Игнорировать WAL, переиндексировать всё |
| `--reset-wal` | Сбросить все WAL-чекпоинты перед запуском |
| `--cleanup-after-index` | Очистить raw data после индексации |
| `--dry-run` | Показать, что было бы очищено (с `--cleanup-after-index`) |
| `--webhook-only` | Запустить только webhook-сервер |
| `--consumer-only` | Запустить только stream consumer |
| `--quality-report path.json` | Сгенерировать отчёт качества извлечения |

---

## Настройка удалённых Embedder / Reranker / SLM

ETL-пайплайн может использовать удалённые ML-сервисы вместо загрузки моделей локально. Это критично для air-gapped или ресурсо-ограниченных ETL-машин.

### Конфигурация

Все удалённые сервисы настраиваются в `etl_config.yaml` под `remote_services`:

```yaml
remote_services:
  embedder:
    endpoint: "${EMBEDDER_ENDPOINT:-http://rag-proxy:8080/v1}"
    model: "${EMBEDDER_MODEL:-BAAI/bge-m3}"
    api_key: "${EMBEDDER_API_KEY:-}"
    timeout: 60
    batch_size: 64
    max_retries: 5
    retry_delay: 2.0
    retry_max_delay: 30.0
    connection_pool_size: 16

  reranker:
    endpoint: "${RERANKER_ENDPOINT:-http://rag-proxy:8080/v1}"
    model: "${RERANKER_MODEL:-BAAI/bge-reranker-v2-m3}"
    api_key: "${RERANKER_API_KEY:-}"
    timeout: 30

  slm:
    endpoint: "${SLM_ENDPOINT:-http://rag-proxy:8080/v1}"
    model: "${SLM_MODEL:-qwen2.5-3b}"
    api_key: "${SLM_API_KEY:-}"
    timeout: 30
```

Переменные окружения (`${VAR:-default}`) раскрываются при загрузке конфига.

### Возможности RemoteEmbedder

Класс `RemoteEmbedder` — drop-in замена SentenceTransformer с тем же интерфейсом `encode()`. Он общается через OpenAI-совместимый эндпоинт `/v1/embeddings`.

**Retry логика:**
- Exponential backoff с jitter (настраивается: constant, linear, exponential)
- Retryable HTTP statuses: 429, 500, 502, 503, 504
- Настраиваемые max attempts, base delay и max delay

**Connection pooling:**
- HTTP connection pool через `requests.Session` с `HTTPAdapter`
- Настраиваемый `connection_pool_size` (default 16)

**Async поддержка:**
- `encode_async()` с `aiohttp` для non-blocking embedding
- `asyncio.Semaphore` для управления concurrency (backpressure)
- Используется streaming пайплайном для параллельного embedding чанков

**Graceful degradation:**
- Возвращает `None` для sparse/ColBERT embeddings (не поддерживается удалённо)
- Отслеживает состояние здоровья через `is_healthy` свойство
- При сбое отмечает `_healthy = False` и raises

### Переменные окружения (быстрое переопределение)

```bash
export EMBEDDER_ENDPOINT="http://gpu-server:8080/v1"
export EMBEDDER_MODEL="BAAI/bge-m3"
export EMBEDDER_API_KEY="sk-..."

export RERANKER_ENDPOINT="http://gpu-server:8080/v1"
export RERANKER_MODEL="BAAI/bge-reranker-v2-m3"

export SLM_ENDPOINT="http://gpu-server:8080/v1"
export SLM_MODEL="qwen2.5-3b"
```

### Целевые архитектуры

| Настройка | Embedder | Reranker | SLM | Примечания |
|-----------|----------|----------|-----|------------|
| **Single GPU server** | vLLM на GPU | vLLM на GPU | vLLM на GPU | Один endpoint, разные модели |
| **Separate services** | GPUStack / TEI | GPUStack / TEI | llama.cpp | Разные endpoints |
| **RAG Proxy passthrough** | Proxy → GPU server | Proxy → GPU server | Proxy → SLM server | Централизованный routing |
| **Air-gapped (local)** | `embedder_device: cuda` | `embedder_device: cpu` | (нет) | Загружает SentenceTransformer локально |

---

## Настройка инкрементальной загрузки

ETL-пайплайн использует WAL (Write-Ahead Log) чекпоинты для отслеживания прогресса загрузки, обеспечивая только delta-загрузку без повторной обработки целых источников.

### Как это работает

1. **Извлечение:** Каждый источник записывает `last_run` timestamp в WAL после успешной загрузки.
2. **Индексация:** Каждый чанк content-addressed через SHA-256 хэш. `LiveVectorLake` сравнивает хэши и индексирует только изменённые чанки.
3. **Идемпотентные вставки:** Qdrant point IDs — UUID v5 от chunk hashes, поэтому повторная индексация того же контента produces тот же point ID (идемпотентный upsert).

### Имена WAL Pipeline

| Pipeline | Константа | Что отслеживает |
|----------|-----------|-----------------|
| Confluence extractor | `confluence_extractor` | `last_run`, `space_keys`, `total_pages` |
| Jira extractor | `jira_extractor` | `last_run`, `offset` |
| GitLab extractor | `gitlab_extractor` | `last_run`, `last_id` |
| Indexing | `indexing` | `added`, `deleted`, `hash_map` |
| Graph builder | `graph_builder` | `last_run` |

### Инкрементальная Confluence загрузка

Когда `confluence.incremental: true`:
- Экстрактор получает только страницы, обновлённые с момента последнего `last_run` timestamp.
- Per-space delta tracking предотвращает повторную обработку неизменённых spaces.
- Параметр `since_date` автоматически заполняется из WAL-чекпоинта.

### Возобновление после прерывания

```bash
# WAL-снапшоты сохраняются на SIGTERM/SIGINT через atexit handler
# Возобновить с места остановки:
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml

# Сбросить конкретный pipeline checkpoint, сохранив last_run:
wal = WALManager(Path("./wal/etl_wal.json"))
wal.reset_pipeline("indexing", keep_last_run=True)

# Полный сброс:
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --reset-wal
```

---

## Варианты WAL Backend

WAL поддерживает три backend хранения, настраиваемых через `wal.wal_backend` или переменную окружения `WAL_BACKEND`.

### File Backend (Default)

```yaml
wal:
  wal_backend: "file"
  wal_file: "./wal/etl_wal.json"
  use_lock: true
  lock_timeout: 30
```

- **Хранилище:** Локальный JSON файл с file-based locking (`filelock` пакет, опционально).
- **Восстановление устаревших блокировок:** Блокировки старше 10 минут автоматически освобождаются.
- **Восстановление от повреждений:** Повреждённые JSON файлы переинициализируются как пустые.
- **Лучше для:** Одномашинный ETL, air-gapped окружения, простые деплои.

```bash
export WAL_BACKEND=file
```

### Redis Backend

```yaml
wal:
  wal_backend: "redis"
  redis_host: "redis.internal"
  redis_port: 6379
```

- **Хранилище:** Каждый чекпоинт хранится как Redis key под `etl:wal:{checkpoint_name}`.
- **Преимущества:** Нет file locking, multi-worker safe, централизованное хранилище чекпоинтов.
- **Ограничения:** Требует Redis connectivity; fallback на пустое state при сбое подключения.
- **Лучше для:** Multi-worker ETL, distributed деплои, Kubernetes.

```bash
export WAL_BACKEND=redis
export REDIS_HOST=redis.internal
export REDIS_PORT=6379
```

### Proxy Backend

```yaml
wal:
  wal_backend: "proxy"
  proxy_url: "http://proxy.internal:8080"
```

- **Хранилище:** Чекпоинты POSTed/GETed к proxy API `/v1/admin/etl/wal`.
- **Преимущества:** Централизованное state в RAG proxy, без дополнительной инфраструктуры.
- **Ограничения:** Требует запущенного proxy; single point of failure для хранилища чекпоинтов.
- **Лучше для:** Деплои где proxy всегда доступен, простое централизованное state.

```bash
export WAL_BACKEND=proxy
export PROXY_URL=http://proxy.internal:8080
```

### Миграция между backend

В настоящее время нет автоматической миграции. Для смены backend:

1. Экспортировать существующие чекпоинты из file WAL:
   ```bash
   python -c "
   import json
   with open('./wal/etl_wal.json') as f:
       print(json.dumps(json.load(f), indent=2))
   "
   ```
2. Переключить backend в конфиге.
3. Первый запуск создаст свежее WAL state в новом backend.

---

## OCR и мультимодальная загрузка

ETL-пайплайн поддерживает извлечение текста из изображений и PDF через OCR, создание подписей к изображениям через CLIP/BLIP и измерение качества извлечения.

### Конфигурация

```yaml
multimodal:
  # FR-09: OCR pipeline
  ocr_enabled: true
  ocr_languages: "rus+eng"
  ocr_confidence_threshold: 60
  ocr_primary_engine: "tesseract"

  # FR-10: Image embedding
  image_extraction_enabled: false
  clip_model: "openai/clip-vit-base-patch32"
  blip_model: "Salesforce/blip-image-captioning-base"
  image_collection_suffix: "_images"

  # FR-11: PDF embedded image extraction
  pdf_image_extraction_enabled: false

  # FR-12: Quality metrics
  quality_report_enabled: false
```

### OCR Pipeline (FR-09)

- **Основной движок:** Tesseract (`pytesseract`) — лучше для документов, поддерживает 100+ языков.
- **Запасной движок:** EasyOCR — лучше для не-латинских скриптов и сложных layouts.
- **Порог уверенности:** Только текст с confidence >= `ocr_confidence_threshold` включается.
- **Multi-page:** Поддерживает TIFF фреймы и отрендеренные PDF страницы через `process_multi_page_ocr()`.

```bash
# Установить OCR зависимости
apt-get install tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
pip install pytesseract easyocr Pillow

# Включить в конфиге
export OCR_ENABLED=true
export OCR_LANGUAGES="rus+eng"
export OCR_PRIMARY_ENGINE="tesseract"
```

### PDF Embedded Image Extraction (FR-11)

Когда `pdf_image_extraction_enabled: true`, doc extractor:
1. Извлекает embedded images из PDF.
2. Запускает OCR на каждом изображении.
3. Добавляет OCR текст к извлечённому контенту под маркерами `[OCR from embedded images]`.

### Quality Report (FR-12)

Сгенерировать отчёт качества извлечения для оценки точности OCR и извлечения таблиц:

```bash
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --quality-report quality_report.json
```

Отчёт включает:
- Per-document OCR confidence скоры и количество страниц
- Метрики качества извлечения таблиц
- Общий скор качества извлечения

---

## Решение проблем

### Несовпадение UUID Point ID

**Симптом:** Дублирующиеся points в Qdrant, или чанки которые должны дедуплицироваться не дедуплицируются.

**Причина:** Qdrant point IDs — UUID v5 от SHA-256 chunk hashes через `uuid.uuid5(uuid.NAMESPACE_OID, chunk_hash)`. Если chunk hash изменяется (например, другие параметры чанкинга), UUID изменяется.

**Исправление:**
```bash
# Проверить количество points в коллекции
curl http://localhost:6333/collections/knowledge_base | python3 -m json.tool

# Принудительная полная переиндексация если параметры чанкинга изменились
python etl/scheduler/run_etl.py --mode batch --reset-wal --force-reindex
```

### Проблемы с WAL-блокировками

**Симптом:** `OSError: Cannot create lock file` или pipeline зависает при старте.

**Причины:**
1. Устаревший lock файл от упавшего процесса.
2. Проблемы с правами доступа к WAL директории.
3. Конкурентные ETL процессы, борющиеся за одну блокировку.

**Исправления:**
```bash
# Проверить наличие устаревшего lock файла
ls -la ./wal/etl_wal.json.lock

# Удалить устаревший lock вручную (только если ETL не запущен)
rm -f ./wal/etl_wal.json.lock

# Проверить права директории
ls -la ./wal/
chmod 755 ./wal/

# Включить автоматическое восстановление устаревших блокировок (default: 10 мин)
# В etl_config.yaml:
# wal:
#   use_lock: true
#   lock_timeout: 30

# Для multi-worker настроек переключиться на Redis WAL backend
export WAL_BACKEND=redis
```

**Профилактика:**
- WAL-чекпоинты сохраняются на SIGTERM/SIGINT через `atexit` handler. Блокировка освобождается при чистом завершении процесса.
- Устаревшие блокировки (>10 минут) автоматически обнаруживаются и освобождаются.
- Используйте Redis WAL backend для multi-worker деплоев.

### Ошибки эмбеддинга

**Симптом:** `RetryExhaustedError: All 5 retry attempts exhausted` или эмбеддинг возвращает пустые векторы.

**Причины:**
1. Удалённый embedder сервис недоступен.
2. Сетевой таймаут.
3. API key истёк или отсутствует.
4. Модель не загружена на удалённом сервисе.

**Диагностика:**
```bash
# Протестировать embedder endpoint напрямую
curl -X POST http://rag-proxy:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${EMBEDDER_API_KEY}" \
  -d '{"input": ["test"], "model": "BAAI/bge-m3", "encoding_format": "float"}'

# Проверить здоровье embedder через proxy
curl http://localhost:8080/v1/health | python3 -m json.tool | grep embedder
```

**Исправления:**
```yaml
# Увеличить толерантность к retry
remote_services:
  embedder:
    max_retries: 10       # больше попыток
    retry_delay: 5.0      # более длинная base delay
    retry_max_delay: 120.0 # более высокий cap
    timeout: 120           # более длинный timeout для больших батчей
    batch_size: 32         # меньшие батчи если OOM на стороне embedder

# Откатиться на локальный embedder (закомментировать remote_services.embedder.endpoint)
# Pipeline загрузит SentenceTransformer локально:
# remote_services:
#   embedder:
#     endpoint: ""  # пусто → local
```

### Сбои извлечения

**Симптом:** `All extractors failed — pipeline cannot continue`.

**Причины:**
1. Все source URLs недоступны.
2. Невалидные API токены.
3. Ошибки SSL сертификатов в корпоративных окружениях.

**Исправления:**
```yaml
# Отключить SSL верификацию (корпоративные самоподписанные сертификаты)
confluence:
  verify_ssl: false
  ca_bundle: "/etc/ssl/certs/corporate.pem"  # или использовать CA bundle

# Протестировать каждый источник по отдельности
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --test-connection

# Запустить только один источник для изоляции
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode batch \
  --skip-jira --skip-gitlab
```

### Ошибка "Collection not found"

**Симптом:** `qdrant_client.http.exceptions.UnexpectedResponse: Not found: Collection knowledge_base doesn't exist!`

**Исправление:**
```bash
# Создать коллекцию явно
python etl/scheduler/run_etl.py --mode batch --skip-extract --skip-chunk --skip-graph

# Или использовать init скрипт
python scripts/init_collections.py
```

### Зависания Streaming Pipeline

**Симптом:** Streaming режим не показывает прогресса, CPU/network idle.

**Причины:**
1. Embedder сервис rate-limiting (429 ответы триггерят backoff).
2. Все concurrent API слоты насыщены (semaphore исчерпан).
3. Проблемы сетевой связности.

**Исправления:**
```yaml
# Снизить concurrency
streaming:
  max_concurrent_api_calls: 3  # вместо 10

# Увеличить толерантность к retry
remote_services:
  embedder:
    max_retries: 10
    retry_delay: 5.0
```

---

## Хранение данных и очистка

После успешной индексации raw data и chunk файлы могут быть очищены:

```yaml
etl:
  data_retention:
    raw_data_days: 7         # auto-delete raw extracts после N дней (0 = хранить вечно)
    cleanup_after_run: false  # очистить сразу после индексации
    keep_cold_storage: true   # сохранить cold storage для версионирования
```

```bash
# Ручная очистка после индексации (сначала dry-run)
python etl/scheduler/run_etl.py --mode batch --cleanup-after-index --dry-run

# Фактическая очистка
python etl/scheduler/run_etl.py --mode batch --cleanup-after-index

# Или через Makefile
make etl-cleanup
```

Очистка удаляет:
- Raw data директории (`confluence/`, `jira/`, `gitlab/`)
- Chunks output директория
- Опционально cold storage (если `keep_cold_storage: false`)
- Удаляет полный текст из hot chunk JSONs (сохраняет только хэши и метаданные)

---

## Ссылочный справочник переменных окружения

| Переменная | Config Path | Default | Описание |
|------------|------------|---------|----------|
| `EMBEDDER_ENDPOINT` | `remote_services.embedder.endpoint` | `http://rag-proxy:8080/v1` | Embedding API endpoint |
| `EMBEDDER_MODEL` | `remote_services.embedder.model` | `BAAI/bge-m3` | Имя модели эмбеддинга |
| `EMBEDDER_API_KEY` | `remote_services.embedder.api_key` | (пусто) | Bearer token для embedder |
| `RERANKER_ENDPOINT` | `remote_services.reranker.endpoint` | `http://rag-proxy:8080/v1` | Reranker API endpoint |
| `RERANKER_MODEL` | `remote_services.reranker.model` | `BAAI/bge-reranker-v2-m3` | Имя модели реранкера |
| `SLM_ENDPOINT` | `remote_services.slm.endpoint` | `http://rag-proxy:8080/v1` | SLM API endpoint |
| `SLM_MODEL` | `remote_services.slm.model` | `qwen2.5-3b` | Имя SLM модели |
| `WAL_BACKEND` | `wal.wal_backend` | `file` | WAL storage backend (`file`/`redis`/`proxy`) |
| `REDIS_HOST` | `wal.redis_host` / `streaming.redis_host` | `localhost` | Redis host |
| `REDIS_PORT` | `wal.redis_port` / `streaming.redis_port` | `6379` | Redis port |
| `PROXY_URL` | `wal.proxy_url` | `http://localhost:8080` | Proxy URL для WAL backend |
| `OCR_ENABLED` | `multimodal.ocr_enabled` | `true` | Включить OCR pipeline |
| `OCR_LANGUAGES` | `multimodal.ocr_languages` | `rus+eng` | Tesseract language codes |
| `OCR_PRIMARY_ENGINE` | `multimodal.ocr_primary_engine` | `tesseract` | Основной OCR движок |

---

## См. также

- [ETL Pipeline Guide](etl-guide.md) — архитектура и обзор дизайна
- [Extensibility & Data Sources](extensibility-data-sources.md) — добавление новых источников
- [Configuration Reference](configuration-reference.md) — все опции конфигурации
- [Troubleshooting](troubleshooting.md) — общее решение проблем системы
- [Index](index.md) — полный индекс документации
