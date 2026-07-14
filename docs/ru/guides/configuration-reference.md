# Справочник конфигурации

**Версия:** v2.0.0 | **Обновлено:** 2026-07-12

Полный справочник всех параметров конфигурации RAG-системы. Включает переменные окружения прокси (`proxy/.env`),
настройки ETL-пайплайна (`etl/config/etl_config.yaml`) и переопределения Docker Compose.

---

## Конфигурация прокси (proxy/.env)

Все настройки прокси загружаются из переменных окружения. Скопируйте пример для начала:

```bash
cp .env.example proxy/.env
```

### Qdrant (векторная база данных)

| Переменная        | Тип    | По умолчанию     | Описание                                                 |
|-------------------|--------|------------------|----------------------------------------------------------|
| `QDRANT_HOST`     | string | `localhost`      | Имя хоста Qdrant. Используйте `qdrant` в Docker Compose. |
| `QDRANT_PORT`     | int    | `6333`           | Порт HTTP API Qdrant.                                    |
| `COLLECTION_NAME` | string | `knowledge_base` | Основная коллекция для гибридного поиска.                |

**Пример:**

```ini
QDRANT_HOST=qdrant
QDRANT_PORT=6333
COLLECTION_NAME=knowledge_base
```

---

### Модель эмбеддингов

| Переменная                | Тип    | По умолчанию | Описание                                                                                            |
|---------------------------|--------|--------------|-----------------------------------------------------------------------------------------------------|
| `EMBEDDER_MODEL`          | string | `""`         | **ОБЯЗАТЕЛЬНО.** ID модели HuggingFace или локальный путь.                                          |
| `EMBEDDER_DEVICE`         | string | `cpu`        | Устройство: `cpu` или `cuda`.                                                                       |
| `EMBEDDER_ENDPOINT`       | string | `""`         | URL удалённого сервиса эмбеддингов (совместим с OpenAI `/v1/embeddings`). Пусто = локальная модель. |
| `EMBEDDER_API_KEY`        | string | `""`         | API-ключ для удалённого эмбеддера.                                                                  |
| `EMBEDDER_FALLBACK_LOCAL` | bool   | `true`       | Откат на локальный SentenceTransformer при недоступности удалённого.                                |

**Рекомендуемые модели:**

| Модель                                   | Размерность | Контекст | Размер  | Назначение                                     |
|------------------------------------------|-------------|----------|---------|------------------------------------------------|
| `BAAI/bge-m3`                            | 1024        | 8192     | ~2 ГБ   | Продакшн (мультиязычная, dense+sparse+ColBERT) |
| `intfloat/multilingual-e5-large`         | 1024        | 512      | ~1.3 ГБ | Хорошее мультиязычное качество                 |
| `sentence-transformers/all-MiniLM-L6-v2` | 384         | 256      | ~90 МБ  | Лёгкая / для тестирования                      |

**Пример:**

```ini
EMBEDDER_MODEL=BAAI/bge-m3
EMBEDDER_DEVICE=cpu
```

**Пример удалённого эмбеддера:**

```ini
EMBEDDER_ENDPOINT=http://embedder-service:8080/v1
EMBEDDER_API_KEY=your-api-key
EMBEDDER_FALLBACK_LOCAL=true
```

---

### Реранкер (кросс-энкодер)

| Переменная                | Тип    | По умолчанию | Описание                                                      |
|---------------------------|--------|--------------|---------------------------------------------------------------|
| `RERANKER_MODEL`          | string | `""`         | **ОБЯЗАТЕЛЬНО.** ID модели HuggingFace или локальный путь.    |
| `RERANKER_MAX_LENGTH`     | int    | `512`        | Максимальная длина чанка в токенах для реранкинга.            |
| `RERANKER_BATCH_SIZE`     | int    | `32`         | Размер батча. Уменьшите при OOM.                              |
| `RERANKER_ENDPOINT`       | string | `""`         | URL удалённого реранкера (совместим с Cohere `/v1/rerank`).   |
| `RERANKER_API_KEY`        | string | `""`         | API-ключ для удалённого реранкера.                            |
| `RERANKER_FALLBACK_LOCAL` | bool   | `true`       | Откат на локальный CrossEncoder при недоступности удалённого. |

**Рекомендуемые модели:**

| Модель                                 | Контекст | Размер  | Назначение                      |
|----------------------------------------|----------|---------|---------------------------------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 512      | ~90 МБ  | Быстрый, английский             |
| `BAAI/bge-reranker-v2-m3`              | 8192     | ~1.5 ГБ | Мультиязычный, высокое качество |
| `mixedbread-ai/mxbai-rerank-large-v1`  | 512      | ~1.3 ГБ | Высокая точность                |

**Пример:**

```ini
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_MAX_LENGTH=512
RERANKER_BATCH_SIZE=32
```

---

### LLM (основная языковая модель)

| Переменная          | Тип    | По умолчанию               | Описание                                                |
|---------------------|--------|----------------------------|---------------------------------------------------------|
| `LLM_ENDPOINT`      | string | `http://localhost:8000/v1` | **ОБЯЗАТЕЛЬНО.** URL OpenAI-совместимого эндпоинта.     |
| `LLM_MODEL_NAME`    | string | `""`                       | **ОБЯЗАТЕЛЬНО.** Идентификатор модели для API-запросов. |
| `LLM_API_KEY`       | string | `None`                     | API-ключ (только если бэкенд требует).                  |
| `LLM_PROVIDER_TYPE` | string | `openai`                   | Тип провайдера: `openai`, `anthropic`, `generic`.       |
| `REQUEST_TIMEOUT`   | int    | `120`                      | Таймаут вызовов LLM в секундах.                         |
| `MAX_RETRIES`       | int    | `3`                        | Количество повторных попыток.                           |
| `RETRY_DELAY`       | float  | `1.0`                      | Задержка между попытками в секундах.                    |

**Пример (vLLM):**

```ini
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=Llama-3.1-70B-Instruct
LLM_API_KEY=
REQUEST_TIMEOUT=120
```

**Пример (Ollama):**

```ini
LLM_ENDPOINT=http://localhost:11434/v1
LLM_MODEL_NAME=llama3.1:70b
LLM_PROVIDER_TYPE=generic
```

**Пример (OpenAI API):**

```ini
LLM_ENDPOINT=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o
LLM_API_KEY=sk-...
LLM_PROVIDER_TYPE=openai
```

---

### SLM (малая языковая модель)

SLM обрабатывает лёгкие задачи: классификация намерений, декомпозиция запросов, извлечение сущностей. Оставьте
`SLM_ENDPOINT` пустым для отключения (используется эвристический фолбэк).

| Переменная       | Тип    | По умолчанию | Описание                        |
|------------------|--------|--------------|---------------------------------|
| `SLM_ENDPOINT`   | string | `""`         | URL API SLM. Пусто = отключено. |
| `SLM_MODEL_NAME` | string | `""`         | Идентификатор модели SLM.       |
| `SLM_API_KEY`    | string | `None`       | API-ключ SLM.                   |
| `SLM_MAX_TOKENS` | int    | `256`        | Максимум токенов в ответах SLM. |

**Рекомендуемые модели SLM:**

| Модель                             | Параметры | Контекст | Назначение                        |
|------------------------------------|-----------|----------|-----------------------------------|
| `Qwen/Qwen2.5-3B-Instruct`         | 3B        | 32K      | Лучший баланс скорости и качества |
| `gemma-2b-it`                      | 2B        | 8K       | Самая быстрая, лёгкая             |
| `microsoft/Phi-3-mini-4k-instruct` | 3.8B      | 4K       | Сильная аналитика                 |

**Пример:**

```ini
SLM_ENDPOINT=http://slm:8000/v1
SLM_MODEL_NAME=Qwen/Qwen2.5-3B-Instruct
SLM_MAX_TOKENS=256
```

---

### SLM Local (подпроцесс llama.cpp)

Для автономных развёртываний — запуск SLM локально через подпроцесс llama.cpp.

| Переменная                  | Тип    | По умолчанию                       | Описание                                      |
|-----------------------------|--------|------------------------------------|-----------------------------------------------|
| `SLM_LOCAL_ENABLED`         | bool   | `false`                            | Включить локальный режим llama.cpp.           |
| `SLM_LOCAL_BINARY`          | string | `llama.cpp/build/bin/llama-server` | Путь к бинарнику llama-server.                |
| `SLM_LOCAL_MODEL_PATH`      | string | `""`                               | Путь к файлу модели `.gguf`.                  |
| `SLM_LOCAL_CONTEXT_SIZE`    | int    | `4096`                             | Размер контекста в токенах.                   |
| `SLM_LOCAL_THREADS`         | int    | `4`                                | Потоки CPU для инференса.                     |
| `SLM_LOCAL_PORT`            | int    | `8081`                             | Порт для локального llama-server. `0` = авто. |
| `SLM_LOCAL_STARTUP_TIMEOUT` | int    | `60`                               | Макс. секунд ожидания готовности сервера.     |

**Пример:**

```ini
SLM_LOCAL_ENABLED=true
SLM_LOCAL_BINARY=/usr/local/bin/llama-server
SLM_LOCAL_MODEL_PATH=/opt/models/slm-model.gguf
SLM_LOCAL_CONTEXT_SIZE=4096
SLM_LOCAL_THREADS=8
SLM_LOCAL_PORT=8081
```

---

### Параметры поиска

| Переменная                | Тип | По умолчанию | Описание                                             |
|---------------------------|-----|--------------|------------------------------------------------------|
| `MAX_CHUNKS_RETRIEVAL`    | int | `50`         | Чанки, извлекаемые из Qdrant до реранкинга.          |
| `MAX_CHUNKS_AFTER_RERANK` | int | `20`         | Чанки, передаваемые в контекст LLM после реранкинга. |

**Пример:**

```ini
MAX_CHUNKS_RETRIEVAL=50
MAX_CHUNKS_AFTER_RERANK=20
```

!!! tip
Уменьшите `MAX_CHUNKS_RETRIEVAL` до 20 и `MAX_CHUNKS_AFTER_RERANK` до 10 при ошибках OOM на прокси.

---

### Кэш Redis

| Переменная  | Тип    | По умолчанию             | Описание                                                |
|-------------|--------|--------------------------|---------------------------------------------------------|
| `USE_REDIS` | bool   | `false`                  | Включить семантический кэш на Redis.                    |
| `REDIS_URL` | string | `redis://localhost:6379` | URL подключения к Redis. `redis://redis:6379` в Docker. |

**Пример:**

```ini
USE_REDIS=true
REDIS_URL=redis://redis:6379
```

---

### Агентная оркестрация LangGraph

| Переменная            | Тип  | По умолчанию | Описание                                     |
|-----------------------|------|--------------|----------------------------------------------|
| `USE_LANGGRAPH`       | bool | `false`      | Включить многошаговые агентные циклы поиска. |
| `MAX_RETRIEVAL_LOOPS` | int  | `3`          | Макс. количество итераций агента LangGraph.  |

**Пример:**

```ini
USE_LANGGRAPH=true
MAX_RETRIEVAL_LOOPS=3
```

---

### Граф знаний Neo4j

| Переменная            | Тип    | По умолчанию            | Описание                                      |
|-----------------------|--------|-------------------------|-----------------------------------------------|
| `GRAPH_ENABLED`       | bool   | `false`                 | Включить расширение GraphRAG.                 |
| `NEO4J_URI`           | string | `bolt://localhost:7687` | URI Bolt-протокола Neo4j.                     |
| `NEO4J_USER`          | string | `neo4j`                 | Имя пользователя Neo4j.                       |
| `NEO4J_PASSWORD`      | string | `neo4j`                 | Пароль Neo4j. **Смените в продакшне.**        |
| `USE_GRAPH_EXPANSION` | bool   | `false`                 | Включить обход графа по сущностям при поиске. |

**Пример:**

```ini
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change-this-password
USE_GRAPH_EXPANSION=true
```

---

### Аутентификация и JWT

| Переменная                    | Тип    | По умолчанию | Описание                                                                    |
|-------------------------------|--------|--------------|-----------------------------------------------------------------------------|
| `AUTH_ENABLED`                | bool   | `false`      | Включить JWT-аутентификацию.                                                |
| `JWT_SECRET`                  | string | `""`         | Секрет для подписи HS256. Мин. 32 байта. Генерация: `openssl rand -hex 32`. |
| `JWT_ALGORITHM`               | string | `HS256`      | Алгоритм: `HS256` (локальный) или `RS256` (Keycloak/OIDC).                  |
| `JWT_PUBLIC_KEY`              | string | `""`         | Публичный ключ PEM для RS256.                                               |
| `TOKEN_EXPIRE_HOURS`          | int    | `24`         | Время жизни токена в часах.                                                 |
| `ACCESS_TOKEN_MINUTES`        | int    | `60`         | Время жизни access-токена в минутах.                                        |
| `REFRESH_TOKEN_DAYS`          | int    | `7`          | Время жизни refresh-токена в днях.                                          |
| `TOKEN_BLACKLIST_MAX_ENTRIES` | int    | `10000`      | Макс. записей в чёрном списке (LRU).                                        |
| `AUTH_VALID_USERS`            | string | `"{}"`       | JSON-словарь допустимых пользователей.                                      |

**Пример:**

```ini
AUTH_ENABLED=true
JWT_SECRET=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
ACCESS_TOKEN_MINUTES=60
REFRESH_TOKEN_DAYS=7
```

---

### База пользователей (SQLite)

| Переменная      | Тип    | По умолчанию      | Описание                                                    |
|-----------------|--------|-------------------|-------------------------------------------------------------|
| `USER_DB_PATH`  | string | `./data/users.db` | Путь к SQLite базе данных пользователей.                    |
| `BCRYPT_ROUNDS` | int    | `12`              | Раунды хеширования паролей. Больше = медленнее, безопаснее. |

---

### RBAC (контроль доступа на основе ролей)

| Переменная     | Тип  | По умолчанию | Описание       |
|----------------|------|--------------|----------------|
| `RBAC_ENABLED` | bool | `false`      | Включить RBAC. |

Роли: `admin`, `expert`, `user`, `read_only`.

---

### Keycloak OIDC

| Переменная           | Тип    | По умолчанию | Описание                                         |
|----------------------|--------|--------------|--------------------------------------------------|
| `KEYCLOAK_URL`       | string | `""`         | Базовый URL Keycloak. Включает режим RS256 OIDC. |
| `KEYCLOAK_REALM`     | string | `master`     | Имя realm Keycloak.                              |
| `KEYCLOAK_CLIENT_ID` | string | `rag-proxy`  | ID клиента Keycloak.                             |

**Пример:**

```ini
KEYCLOAK_URL=https://keycloak.company.com
KEYCLOAK_REALM=rag
KEYCLOAK_CLIENT_ID=rag-proxy
```

---

### LDAP / Active Directory

| Переменная            | Тип    | По умолчанию              | Описание                          |
|-----------------------|--------|---------------------------|-----------------------------------|
| `AD_ENABLED`          | bool   | `false`                   | Включить LDAP/AD аутентификацию.  |
| `AD_URL`              | string | `""`                      | URL LDAP-сервера.                 |
| `AD_BASE_DN`          | string | `""`                      | Base DN для поиска пользователей. |
| `AD_USER_DN_TEMPLATE` | string | `cn={username},{base_dn}` | Шаблон DN пользователя.           |
| `AD_GROUP_DN`         | string | `""`                      | DN группы для авторизации.        |

---

### Ограничение частоты запросов

| Переменная              | Тип  | По умолчанию | Описание                                   |
|-------------------------|------|--------------|--------------------------------------------|
| `RATE_LIMIT_ENABLED`    | bool | `false`      | Включить ограничение по IP (token bucket). |
| `RATE_LIMIT_PER_MINUTE` | int  | `60`         | Запросов в минуту на IP.                   |
| `RATE_LIMIT_BURST`      | int  | `10`         | Запас над лимитом.                         |

**Пример:**

```ini
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10
```

---

### Наблюдаемость

| Переменная        | Тип    | По умолчанию | Описание                                                  |
|-------------------|--------|--------------|-----------------------------------------------------------|
| `METRICS_ENABLED` | bool   | `true`       | Включить эндпоинт Prometheus `/metrics`.                  |
| `LOG_FORMAT`      | string | `text`       | Формат логов: `text` или `json`.                          |
| `LOG_LEVEL`       | string | `INFO`       | Уровень: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LOG_REQUESTS`    | bool   | `true`       | Логировать входящие HTTP-запросы.                         |
| `LOG_DIR`         | string | `./logs`     | Директория для файлов логов.                              |

**Пример (продакшн):**

```ini
METRICS_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
LOG_REQUESTS=true
```

---

### Трассировка OpenTelemetry

| Переменная                     | Тип    | По умолчанию                      | Описание                             |
|--------------------------------|--------|-----------------------------------|--------------------------------------|
| `OTEL_ENABLED`                 | bool   | `false`                           | Включить распределённую трассировку. |
| `OTEL_EXPORTER_ENDPOINT`       | string | `http://localhost:4318/v1/traces` | Эндпоинт OTLP HTTP коллектора.       |
| `OTEL_SERVICE_NAME`            | string | `rag-proxy`                       | Имя сервиса в трассировках.          |
| `OTEL_BATCH_TIMEOUT`           | int    | `5`                               | Таймаут пакетного экспорта (сек).    |
| `OTEL_MAX_ATTRIBUTES_PER_SPAN` | int    | `128`                             | Макс. атрибутов на спан.             |

---

### CORS

| Переменная     | Тип    | По умолчанию | Описание                                           |
|----------------|--------|--------------|----------------------------------------------------|
| `CORS_ORIGINS` | string | `*`          | Разрешённые источники CORS. Через запятую или `*`. |

**Пример:**

```ini
CORS_ORIGINS=https://app.company.com,https://dashboard.company.com
```

---

### Безопасность ввода

| Переменная                    | Тип    | По умолчанию | Описание                                                      |
|-------------------------------|--------|--------------|---------------------------------------------------------------|
| `SANITIZE_INPUT`              | bool   | `true`       | Санитизация входных данных (SQL-инъекции, XSS, лимиты длины). |
| `SENSITIVE_SECRETS`           | string | `""`         | Через запятую: секреты для маскировки в логах.                |
| `AUDIT_ENABLED`               | bool   | `true`       | Включить аудит-логирование событий безопасности.              |
| `NAMESPACE_ISOLATION_ENABLED` | bool   | `false`      | Включить изоляцию данных по пространствам имён.               |

---

### Оценка уверенности

| Переменная                        | Тип   | По умолчанию | Описание                                           |
|-----------------------------------|-------|--------------|----------------------------------------------------|
| `CONFIDENCE_THRESHOLD`            | float | `0.5`        | Мин. уверенность перед эскалацией или «я не знаю». |
| `CONFIDENCE_THRESHOLD_CALIBRATED` | float | `0`          | Калиброванный порог. `0` = эвристика.              |
| `MAX_VERIFY_LOOPS`                | int   | `2`          | Макс. циклов верификации.                          |
| `NLI_GROUNDING_ENABLED`           | bool  | `true`       | NLI-верификация фактов against контекст.           |

---

### Самокоррекция (CRAG)

| Переменная                   | Тип    | По умолчанию | Описание                                           |
|------------------------------|--------|--------------|----------------------------------------------------|
| `SELF_CRITIQUE_ENABLED`      | bool   | `true`       | Самокритика сгенерированных ответов.               |
| `COMPRESSION_STRATEGY`       | string | `keyword`    | Сжатие контекста: `perplexity`, `keyword`, `none`. |
| `REORDER_ENABLED`            | bool   | `true`       | Пересортировка чанков по релевантности.            |
| `CRAG_DECOMPOSITION_ENABLED` | bool   | `true`       | Декомпозиция запросов для корректирующего RAG.     |
| `NLI_MODEL_ENABLED`          | bool   | `false`      | Использовать NLI-модель (больше VRAM).             |

---

### HyDE и рефлексия (уровень 5 RAG)

| Переменная                    | Тип  | По умолчанию | Описание                                          |
|-------------------------------|------|--------------|---------------------------------------------------|
| `HYDE_ENABLED`                | bool | `true`       | Гипотетические документы для расширения запросов. |
| `REFLECTION_ENABLED`          | bool | `true`       | Саморефлексия и перегенерация ответов.            |
| `REFLECTION_DEPTH`            | int  | `2`          | Количество итераций рефлексии.                    |
| `HALLUCINATION_CHECK_ENABLED` | bool | `false`      | Полный пайплайн детекции галлюцинаций.            |

---

### Самообогащение

| Переменная           | Тип  | По умолчанию | Описание                                    |
|----------------------|------|--------------|---------------------------------------------|
| `ENRICHMENT_ENABLED` | bool | `false`      | Возврат принятых Q&A обратно в базу знаний. |

---

### Мультимодальный RAG

| Переменная                  | Тип    | По умолчанию             | Описание                                      |
|-----------------------------|--------|--------------------------|-----------------------------------------------|
| `MULTI_MODAL_ENABLED`       | bool   | `true`                   | Поддержка мультимодального поиска.            |
| `COLBERT_ENABLED`           | bool   | `true`                   | Векторы ColBERT late-interaction.             |
| `IMAGE_MODEL`               | string | `clip-ViT-B-32`          | CLIP-модель для эмбеддингов изображений.      |
| `IMAGE_EXTRACTION_ENABLED`  | bool   | `false`                  | Извлечение и индексация изображений.          |
| `AST_LANGUAGES`             | string | `python,javascript,java` | Языки для AST-чанкинга кода.                  |
| `TABLE_EXTRACTION_ENABLED`  | bool   | `false`                  | Извлечение таблиц из документов.              |
| `CODE_CHUNKING_ENABLED`     | bool   | `false`                  | AST-чанкинг кода.                             |
| `COLD_STORAGE_MAX_VERSIONS` | int    | `5`                      | Макс. версий документов в холодном хранилище. |

---

### Оптимизатор токенов

| Переменная                | Тип  | По умолчанию | Описание                                     |
|---------------------------|------|--------------|----------------------------------------------|
| `TOKEN_OPTIMIZER_ENABLED` | bool | `true`       | BPE-подсчёт токенов и распределение бюджета. |

---

### Кэширование префиксов vLLM

| Переменная               | Тип  | По умолчанию | Описание                                                                    |
|--------------------------|------|--------------|-----------------------------------------------------------------------------|
| `PREFIX_CACHING_ENABLED` | bool | `false`      | Поддержка кэширования префиксов (требует `--enable-prefix-caching` в vLLM). |

---

### Сжатие ответов

| Переменная             | Тип  | По умолчанию | Описание                               |
|------------------------|------|--------------|----------------------------------------|
| `COMPRESSION_ENABLED`  | bool | `true`       | Включить gzip/brotli сжатие.           |
| `COMPRESSION_MIN_SIZE` | int  | `500`        | Мин. размер ответа для сжатия (байты). |
| `COMPRESSION_LEVEL`    | int  | `6`          | Уровень gzip (1-9).                    |

---

### SSE-стриминг

| Переменная           | Тип | По умолчанию | Описание              |
|----------------------|-----|--------------|-----------------------|
| `SSE_CHUNK_SIZE`     | int | `4`          | Токенов на SSE-чанк.  |
| `STREAM_BUFFER_SIZE` | int | `1`          | Размер буфера стрима. |

---

### Прогрев моделей

| Переменная          | Тип  | По умолчанию | Описание                            |
|---------------------|------|--------------|-------------------------------------|
| `WARMUP_ENABLED`    | bool | `true`       | Прогрев моделей при первом запросе. |
| `WARMUP_ON_STARTUP` | bool | `true`       | Прогрев при запуске приложения.     |

---

### Инструменты / Function Calling

| Переменная                 | Тип    | По умолчанию          | Описание                                          |
|----------------------------|--------|-----------------------|---------------------------------------------------|
| `TOOLS_ENABLED`            | bool   | `false`               | Включить поддержку вызова инструментов.           |
| `LIVE_SOURCES_ENABLED`     | bool   | `false`               | Включить инструменты живых источников.            |
| `TOOLS_PARALLEL_EXECUTION` | bool   | `true`                | Параллельное выполнение независимых инструментов. |
| `TOOLS_MAX_CONCURRENCY`    | int    | `10`                  | Макс. одновременных выполнений.                   |
| `TOOLS_DECLARATIVE_DIR`    | string | `./tools/declarative` | Директория YAML/JSON определений инструментов.    |
| `TOOLS_OPENAPI_SPECS`      | string | `""`                  | JSON-массив URL OpenAPI-спецификаций.             |

**Пример:**

```ini
TOOLS_ENABLED=true
LIVE_SOURCES_ENABLED=true
TOOLS_PARALLEL_EXECUTION=true
TOOLS_MAX_CONCURRENCY=10
TOOLS_OPENAPI_SPECS='[{"name":"petstore","url":"https://example.com/openapi.json","mode":"auto"}]'
```

---

### API живых источников

| Переменная             | Тип    | По умолчанию | Описание                     |
|------------------------|--------|--------------|------------------------------|
| `CONFLUENCE_API_URL`   | string | `""`         | Базовый URL Confluence.      |
| `CONFLUENCE_API_TOKEN` | string | `""`         | API-токен Confluence.        |
| `CONFLUENCE_API_USER`  | string | `""`         | Имя пользователя Confluence. |
| `JIRA_API_URL`         | string | `""`         | Базовый URL Jira.            |
| `JIRA_API_TOKEN`       | string | `""`         | API-токен Jira.              |
| `JIRA_API_USER`        | string | `""`         | Имя пользователя Jira.       |
| `GITLAB_API_URL`       | string | `""`         | Базовый URL GitLab.          |
| `GITLAB_API_TOKEN`     | string | `""`         | Персональный токен GitLab.   |

---

### I18N / мультиязычность

| Переменная                    | Тип    | По умолчанию     | Описание                               |
|-------------------------------|--------|------------------|----------------------------------------|
| `I18N_ENABLED`                | bool   | `true`           | Поддержка интернационализации.         |
| `DEFAULT_LANGUAGE`            | string | `en`             | Код языка по умолчанию.                |
| `SUPPORTED_LANGUAGES`         | string | `en,ru,de,fr,zh` | Поддерживаемые языки через запятую.    |
| `MULTILINGUAL_INTENT_ENABLED` | bool   | `true`           | Мультиязычная классификация намерений. |
| `CROSS_LINGUAL_ENABLED`       | bool   | `true`           | Кросслингвальный поиск.                |

---

### Эволюция моделей

| Переменная                | Тип  | По умолчанию | Описание                         |
|---------------------------|------|--------------|----------------------------------|
| `MODEL_EVOLUTION_ENABLED` | bool | `false`      | Включить эндпоинты файн-тюнинга. |

#### MLflow

| Переменная               | Тип    | По умолчанию            | Описание                               |
|--------------------------|--------|-------------------------|----------------------------------------|
| `MLFLOW_TRACKING_URI`    | string | `http://localhost:5000` | URL сервера MLflow.                    |
| `MLFLOW_EXPERIMENT_NAME` | string | `rag-system`            | Имя эксперимента MLflow.               |
| `MLFLOW_ARTIFACT_ROOT`   | string | `s3://rag-artifacts`    | Корень хранения артефактов (S3/MinIO). |

#### MinIO

| Переменная          | Тип    | По умолчанию     | Описание                                       |
|---------------------|--------|------------------|------------------------------------------------|
| `MINIO_ENDPOINT`    | string | `localhost:9000` | Эндпоинт S3 API MinIO.                         |
| `MINIO_ACCESS_KEY`  | string | `minioadmin`     | Ключ доступа MinIO. **Смените в продакшне.**   |
| `MINIO_SECRET_KEY`  | string | `minioadmin`     | Секретный ключ MinIO. **Смените в продакшне.** |
| `MINIO_BUCKET`      | string | `rag-artifacts`  | Бакет для артефактов моделей.                  |
| `MINIO_DOCS_BUCKET` | string | `rag-documents`  | Бакет для загруженных документов.              |
| `MINIO_SECURE`      | bool   | `false`          | HTTPS для подключения к MinIO.                 |

#### Обучение

| Переменная         | Тип    | По умолчанию | Описание                           |
|--------------------|--------|--------------|------------------------------------|
| `TRAINING_PROFILE` | string | `dev`        | Профиль: `dev`, `staging`, `prod`. |

#### Горячая перезагрузка

| Переменная                  | Тип  | По умолчанию | Описание                                  |
|-----------------------------|------|--------------|-------------------------------------------|
| `HOT_RELOAD_ENABLED`        | bool | `false`      | Горячая перезагрузка обученных адаптеров. |
| `HOT_RELOAD_WATCH_INTERVAL` | int  | `5`          | Проверка новых адаптеров каждые N секунд. |
| `HOT_RELOAD_SIGNAL_ENABLED` | bool | `true`       | Принимать SIGHUP для ручной перезагрузки. |

#### Канареечное развёртывание

| Переменная                 | Тип  | По умолчанию | Описание                            |
|----------------------------|------|--------------|-------------------------------------|
| `CANARY_ENABLED`           | bool | `false`      | Включить канареечное развёртывание. |
| `CANARY_PHASE_DURATION_5`  | int  | `300`        | Длительность при 5% трафика (сек).  |
| `CANARY_PHASE_DURATION_25` | int  | `600`        | Длительность при 25% трафика (сек). |
| `CANARY_PHASE_DURATION_50` | int  | `900`        | Длительность при 50% трафика (сек). |
| `CANARY_PHASE_DURATION_75` | int  | `1200`       | Длительность при 75% трафика (сек). |
| `CANARY_COOLDOWN_SECONDS`  | int  | `3600`       | Пауза между развёртываниями (сек).  |

#### Пороги EvalGate

| Переменная                        | Тип   | По умолчанию | Описание                             |
|-----------------------------------|-------|--------------|--------------------------------------|
| `EVAL_GATE_LLM_BERTSCORE_MIN`     | float | `0.70`       | Мин. BERTScore для продвижения LLM.  |
| `EVAL_GATE_LLM_HALLUCINATION_MAX` | float | `0.05`       | Макс. доля галлюцинаций LLM.         |
| `EVAL_GATE_LLM_ROUGE_L_MIN`       | float | `0.35`       | Мин. ROUGE-L для продвижения LLM.    |
| `EVAL_GATE_SLM_F1_MIN`            | float | `0.85`       | Мин. F1 для продвижения SLM.         |
| `EVAL_GATE_SLM_ACCURACY_MIN`      | float | `0.90`       | Мин. точность для продвижения SLM.   |
| `EVAL_GATE_RERANKER_MRR_MIN`      | float | `0.75`       | Мин. MRR для продвижения реранкера.  |
| `EVAL_GATE_RERANKER_NDCG_MIN`     | float | `0.70`       | Мин. nDCG для продвижения реранкера. |

---

### SSL / TLS

| Переменная      | Тип    | По умолчанию | Описание                                                |
|-----------------|--------|--------------|---------------------------------------------------------|
| `SSL_VERIFY`    | bool   | `true`       | Проверять SSL-сертификаты. `false` для самоподписанных. |
| `SSL_CERT_PATH` | string | `""`         | Путь к корпоративному CA-бандлу.                        |

---

### Настройки сервера

| Переменная | Тип    | По умолчанию | Описание                                           |
|------------|--------|--------------|----------------------------------------------------|
| `HOST`     | string | `0.0.0.0`    | Адрес привязки.                                    |
| `PORT`     | int    | `8080`       | Порт прослушивания.                                |
| `RELOAD`   | bool   | `false`      | Горячая перезагрузка (только разработка).          |
| `WORKERS`  | int    | `1`          | Количество воркеров Uvicorn. Держите 1 на реплику. |

---

### Корректное завершение

| Переменная                  | Тип  | По умолчанию | Описание                                   |
|-----------------------------|------|--------------|--------------------------------------------|
| `GRACEFUL_SHUTDOWN_ENABLED` | bool | `true`       | Корректное завершение по SIGTERM.          |
| `SHUTDOWN_TIMEOUT`          | int  | `30`         | Макс. секунд ожидания завершения запросов. |

---

### A/B-тестирование

| Переменная        | Тип  | По умолчанию | Описание                             |
|-------------------|------|--------------|--------------------------------------|
| `AB_TEST_ENABLED` | bool | `false`      | Включить A/B-тестирование пайплайна. |

---

### Алерты администратора

| Переменная             | Тип    | По умолчанию | Описание                                  |
|------------------------|--------|--------------|-------------------------------------------|
| `ADMIN_ALERT_ENABLED`  | bool   | `false`      | Алерты при ответах с низкой уверенностью. |
| `ADMIN_ALERT_ENDPOINT` | string | `""`         | Webhook-URL для алертов.                  |

---

### Оценка поиска

| Переменная          | Тип    | По умолчанию               | Описание                |
|---------------------|--------|----------------------------|-------------------------|
| `EVAL_DATASET_PATH` | string | `./data/eval_dataset.json` | Путь к датасету оценки. |

---

### Сканирование зависимостей

| Переменная                | Тип  | По умолчанию | Описание                               |
|---------------------------|------|--------------|----------------------------------------|
| `DEPENDENCY_SCAN_ENABLED` | bool | `false`      | Сканирование уязвимостей зависимостей. |

---

## Конфигурация ETL (etl/config/etl_config.yaml)

ETL-пайплайн настраивается через YAML. Скопируйте и отредактируйте:

```bash
cp etl/config/etl_config.yaml etl/config/etl_config.local.yaml
```

### Глобальные настройки

```yaml
global:
  timeout: 30              # Глобальный таймаут запросов (сек)
  connect_timeout: 10      # Таймаут подключения (сек)
  max_retries: 3           # Макс. количество повторов
  retry_delay: 2           # Задержка между повторами (сек)
```

### WAL (журнал предзаписи)

```yaml
wal:
  wal_file: "./wal/etl_wal.json"   # Путь к файлу WAL
  use_lock: true                    # Файловая блокировка
  lock_timeout: 30                  # Таймаут блокировки (сек)
```

### Confluence

```yaml
confluence:
  url: "https://confluence.internal.company.com"
  username: ""                       # Пусто для Bearer token
  token: "your_personal_access_token"
  verify_ssl: false                  # False для самоподписанных сертификатов
  ca_bundle: ""                      # Путь к корпоративному CA bundle
  space_keys:                        # Список пространств (null = все)
    - "DEV"
    - "OPS"
  output_dir: "./raw_data/confluence"
  incremental: true
  download_attachments: true
  max_versions: 0                    # 0 = все версии
  api_version: "2"                   # "2" или "1"
```

### Jira

```yaml
jira:
  url: "https://jira.internal.company.com"
  username: ""
  token: "your_api_token"
  verify_ssl: false
  ca_bundle: ""
  jql: "project in (DEV, OPS) ORDER BY updated DESC"
  output_dir: "./raw_data/jira"
  incremental: true
  download_attachments: true
  max_issues_per_run: 0              # 0 = без ограничений
  fields: "*all"
  expand: "changelog,renderedBody"
```

### GitLab

```yaml
gitlab:
  url: "https://gitlab.internal.company.com"
  token: "your_personal_access_token"
  verify_ssl: false
  ca_bundle: ""
  project_ids: null                  # null = все проекты, или [1,2,3]
  output_dir: "./raw_data/gitlab"
  incremental: true
  fetch_commits: true
  fetch_files: true
  fetch_merge_requests: true
  max_commits_per_project: 1000
  since_date: null                   # ISO дата, например "2025-01-01T00:00:00Z"
  file_paths_filter:
    - "*.py"
    - "*.md"
    - "Dockerfile"
    - "*.yaml"
    - "*.yml"
    - "*.sql"
```

### Чанкинг

```yaml
chunking:
  max_tokens: 8000                   # Макс. размер чанка
  overlap_tokens: 200                # Перекрытие между чанками
  min_chunk_tokens: 100              # Мин. размер (будет объединён)
  use_slm: false                     # SLM для обогащения
  slm_endpoint: "http://localhost:8080/v1/completions"
  output_dir: "./chunks"
```

### Индексация

```yaml
indexing:
  qdrant_host: "localhost"
  qdrant_port: 6333
  collection_name: "knowledge_base"
  embedder_model: ""                 # ОБЯЗАТЕЛЬНО — напр. BAAI/bge-m3
  embedder_device: "cpu"             # или "cuda"
  batch_size: 100
  hot_dir: "./hot_chunks"
  cold_dir: "./cold_chunks"
  lake_dir: "./cold_lake"
  use_delta: false                   # Delta Lake (требуется deltalake)
  version_wal: "./wal/version_wal.json"
  live_upsert_enabled: true
```

### Стриминговый ETL

```yaml
streaming:
  streaming_enabled: false
  webhook_enabled: true
  webhook_host: "0.0.0.0"
  webhook_port: 9000
  webhook_secret: ""                 # ОБЯЗАТЕЛЬНО — общий секрет HMAC
  redis_host: "localhost"
  redis_port: 6379
  redis_stream_key: "etl:events"
  redis_consumer_group: "etl-workers"
```

### Расписание

```yaml
schedule:
  enabled: false
  cron_expression: "0 2 * * *"       # Ежедневно в 02:00
  timezone: "UTC"
  retry_on_failure: true
  max_retries: 3
  notify_on_failure: true
```

### Граф (Neo4j)

```yaml
graph:
  enabled: false
  use_spacy: true
  spacy_model: ""                    # ОБЯЗАТЕЛЬНО — напр. ru_core_news_sm
  use_slm: false
  slm_endpoint: "http://localhost:8080/v1/completions"
  cache_dir: "./entity_cache"
  neo4j:
    enabled: false
    uri: "bolt://localhost:7687"
    user: "neo4j"
    password: "your_neo4j_password"
    database: "neo4j"
```

### SSL

```yaml
ssl:
  verify: true
  cert_path: ""                      # Путь к корпоративному CA bundle
```

---

## Переменные окружения Docker Compose

При запуске через Docker Compose некоторые переменные переопределяются для сетевого взаимодействия контейнеров:

```yaml
# proxy/docker-compose.yml — сервис rag-proxy
environment:
  - QDRANT_HOST=qdrant              # Имя контейнера, не localhost
  - QDRANT_PORT=6333
  - NEO4J_URI=bolt://neo4j:7687     # Имя контейнера
  - REDIS_URL=redis://redis:6379    # Имя контейнера
  - MINIO_ENDPOINT=minio:9000       # Имя контейнера
```

Эти значения переопределяют `.env` при запуске внутри Docker Compose.

---

## Рецепты быстрой конфигурации

### Минимальная настройка для разработки

```ini
# proxy/.env — минимально, без auth, без графа, без кэша
QDRANT_HOST=localhost
EMBEDDER_MODEL=BAAI/bge-m3
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
LLM_ENDPOINT=http://localhost:8000/v1
LLM_MODEL_NAME=your-model-name
```

### Полная продакшн-настройка

```ini
# proxy/.env — все функции включены
QDRANT_HOST=qdrant
EMBEDDER_MODEL=BAAI/bge-m3
EMBEDDER_DEVICE=cuda
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=Llama-3.1-70B-Instruct
SLM_ENDPOINT=http://slm:8000/v1
SLM_MODEL_NAME=Qwen/Qwen2.5-3B-Instruct
USE_REDIS=true
REDIS_URL=redis://redis:6379
USE_LANGGRAPH=true
GRAPH_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_PASSWORD=change-this
AUTH_ENABLED=true
JWT_SECRET=<generate-with-openssl>
RBAC_ENABLED=true
RATE_LIMIT_ENABLED=true
METRICS_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
TOOLS_ENABLED=true
MODEL_EVOLUTION_ENABLED=true
```

### Автономная настройка

```ini
# proxy/.env — полностью офлайн
EMBEDDER_MODEL=/opt/models/bge-m3
RERANKER_MODEL=/opt/models/ms-marco-MiniLM-L-6-v2
LLM_ENDPOINT=http://llama-cpp:8000/v1
LLM_MODEL_NAME=/opt/models/llama-3.1-8b-Q4_K_M.gguf
SLM_LOCAL_ENABLED=true
SLM_LOCAL_MODEL_PATH=/opt/models/slm-model.gguf
SSL_VERIFY=false
```

---

## Связанные документы

| Документ                                                                              | Описание                                         |
|---------------------------------------------------------------------------------------|--------------------------------------------------|
| [Руководство по развёртыванию](deployment-guide.md)                                   | Docker Compose, K8s, автономное развёртывание    |
| [Руководство по эксплуатации](operations-guide.md)                                    | Ежедневные операции, мониторинг, масштабирование |
| [Устранение проблем](troubleshooting.md)                                              | Типовые проблемы и решения                       |
| [Примеры API](api-examples.md)                                                        | curl, Python, JavaScript примеры                 |
| [.env.example](https://github.com/AlexanderNarbaev/rag-system/blob/main/.env.example) | Шаблон со всеми переменными                      |
