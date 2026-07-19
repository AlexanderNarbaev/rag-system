# Руководство по интеграции с OpenCode

## Обзор архитектуры

RAG-система предоставляет OpenAI-совместимый API на `http://localhost:8080/v1`. OpenCode подключается к ней как к
заменяемому LLM-провайдеру, используя корпоративную базу знаний (Confluence, Jira, GitLab) для контекстно-осведомлённой
помощи по коду.

```
┌──────────┐   OpenAI-совместимый API   ┌──────────────┐
│ OpenCode  │ ──── POST /v1/chat/ ────▶ │  RAG Proxy   │
│  (клиент) │ ◀─── completions ──────── │  (FastAPI)   │
└──────────┘                            └──────┬───────┘
                                                │
                           ┌────────────────────┼────────────────────┐
                           ▼                    ▼                    ▼
                      ┌────────┐          ┌────────┐          ┌────────┐
                       │ Qdrant │          │  Neo4j │          │  LLM   │
                      │ (векторы)│          │ (граф) │          │ Backend│
                      └────────┘          └────────┘          └────────┘
```

Прокси перехватывает каждый запрос чат-завершения, выполняет гибридный поиск в Qdrant, переранжирует результаты,
собирает контекстно-дополненный промпт и направляет его в LLM. OpenCode видит стандартные ответы OpenAI API —
специальный код клиента не требуется.

## Конфигурация MCP-сервера

Настройте OpenCode на использование RAG-системы как провайдера моделей через `opencode.json`:

```json
{
  "providers": {
    "rag-system": {
      "name": "RAG System",
      "base_url": "http://localhost:8080/v1",
      "api_key": "${RAG_API_KEY}",
      "models": ["your-model-name"]
    }
  },
  "model": "rag-system/your-model-name"
}
```

Если RAG-система развёрнута на отдельной машине в автономной сети:

```json
{
  "providers": {
    "rag-system": {
      "name": "RAG System (Internal)",
      "base_url": "http://rag-proxy.internal.company.com:8080/v1",
      "api_key": "${RAG_API_KEY}",
      "models": ["your-model-name"],
      "timeout": 120
    }
  },
  "model": "rag-system/your-model-name",
  "small_model": "rag-system/your-model-name"
}
```

### Переменные окружения

```bash
# Установите перед запуском OpenCode:
export RAG_API_KEY="your-secure-api-key"
# Должен совпадать с --api-key, установленным в конфигурации вашего LLM-бэкенда
```

## Примеры использования

### Стандартный запрос по коду

Когда OpenCode отправляет запрос о коде в репозиториях вашей организации, RAG-система автоматически обогащает его
релевантным контекстом:

```
Пользователь: Как реализован middleware аутентификации в бэкенд-сервисе?

OpenCode → POST /v1/chat/completions
  RAG Proxy:
    1. Эмбеддинг запроса → "authentication middleware backend service"
    2. Гибридный поиск в Qdrant → возвращает чанки из документации GitLab,
       архитектурных страниц Confluence, тикетов реализации Jira
    3. Реранк top 20 из 50 → выбирает наиболее релевантные
    4. Сборка контекстного промпта с атрибуцией источников
    5. LLM генерирует ответ с цитированием

Ответ: Аутентификационный middleware использует JWT-токены с
управлением сессиями на основе Redis (src/auth/middleware.py:42).
Реализация следует дизайну в [Confluence: Auth Service ADR]
и отслеживалась в [Jira: DEV-1423].
```

### Запрос конкретных версий документов

```json
{
  "model": "rag-system/your-model-name",
  "messages": [
    {"role": "user", "content": "Какой была оригинальная схема базы данных?"}
  ],
  "rag_version": "2025-03-15"
}
```

### Обход кэша для актуальных результатов

```json
{
  "model": "rag-system/your-model-name",
  "messages": [
    {"role": "user", "content": "Какие открытые задачи Jira блокируют релиз?"}
  ],
  "rag_force_refresh": true
}
```

## Обогащение знаний

База знаний растёт через ETL-пайплайн, делая OpenCode прогрессивно умнее:

| Цикл            | Источник данных                      | Частота обновления       | Влияние                              |
|-----------------|--------------------------------------|--------------------------|--------------------------------------|
| **Ежедневно**   | Обновления Jira, новые комментарии   | Каждые 4 часа            | Статус задач, решения                |
| **Еженедельно** | Изменения страниц Confluence         | Каждые 24 часа           | Архитектурная документация, runbooks |
| **По push**     | Коммиты GitLab, merge requests       | Почти в реальном времени | Изменения кода, контекст ревью       |
| **Вручную**     | История чатов, загруженные документы | По требованию            | Экспертные знания, заметки встреч    |

### Инкрементальные обновления на основе WAL

```bash
# Планировщик ETL отслеживает прогресс через файлы WAL:
cat etl/wal/etl_wal.json
# {
#   "last_confluence_sync": "2026-06-21T14:00:00Z",
#   "last_jira_sync": "2026-06-21T18:30:00Z",
#   "last_gitlab_sync": "2026-06-22T09:15:00Z",
#   "total_indexed": 48291,
#   "last_successful_run": "2026-06-22T09:15:00Z"
# }

# Только новые/изменённые документы обрабатываются при каждом запуске:
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml
```

## Безопасность

### Управление API-ключами

```bash
# LLM-бэкенд — установите API-ключ (пример для vLLM в docker-compose.yml):
llm-backend:
  command: >
    --model /models/your-model.gguf
    --api-key ${LLM_API_KEY:-change-me-in-production}

# Прокси аутентифицируется в LLM-бэкенде:
LLM_API_KEY=change-me-in-production  # в proxy/.env

# OpenCode аутентифицируется в прокси:
RAG_API_KEY=change-me-in-production  # окружение opencode
```

### Контроль доступа

Прокси может быть размещён за обратным прокси с basic auth:

```nginx
# nginx.conf
server {
    listen 443 ssl;
    server_name rag-proxy.internal.company.com;

    ssl_certificate /etc/ssl/certs/rag-proxy.crt;
    ssl_certificate_key /etc/ssl/private/rag-proxy.key;

    location /v1/ {
        auth_basic "RAG System";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://rag-proxy:8080;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Чувствительность данных

- `LOG_REQUESTS=true` логирует запросы и ответы; установите `SENSITIVE_SECRETS=password,token,key` для маскирования в
  логах
- Метрики Prometheus НЕ содержат текст запросов — только счётчики и задержки
- Qdrant хранит векторные эмбеддинги, а не сырой текст — обратная разработка непрактична
- Neo4j хранит связи сущностей, а не полное содержимое документов

## Производительность

### Ожидаемая задержка

| Операция              | Холодный (без кэша) | Тёплый (попадание в кэш) |
|-----------------------|---------------------|--------------------------|
| Эмбеддинг             | 50–100 ms           | 5–10 ms (Redis)          |
| Поиск Qdrant          | 20–50 ms            | —                        |
| Реранкинг (20 док.)   | 100–200 ms          | 50–100 ms (Redis)        |
| Генерация LLM         | 2–10 s              | 1–5 s (кэш ответов)      |
| **Полный round-trip** | **3–12 s**          | **1–5 s**                |

### Поведение кэширования

Трёхуровневая архитектура кэша:

1. **Кэш эмбеддингов** (Redis): эмбеддинги запросов переиспользуются для похожих запросов, TTL 24h
2. **Кэш реранка** (Redis): (query, doc_id) → оценка релевантности, TTL 1h
3. **Кэш ответов** (Redis): (query_hash, rag_version) → полный ответ LLM, TTL 15min

```bash
# Мониторинг эффективности кэша:
docker exec rag-redis redis-cli INFO stats | grep -E 'keyspace_hits|keyspace_misses'

# Расчёт hit ratio: hits / (hits + misses)
# Цель: >60% hit ratio для production-нагрузок
```

### Конкурентность

```bash
# LLM-бэкенд обрабатывает конкурентные последовательности (пример для vLLM):
--max-num-seqs 16

# Uvicorn-воркеры прокси (docker-compose):
WORKERS=2  # на реплику

# Горизонтальное масштабирование для большей пропускной способности:
docker-compose up -d --scale rag-proxy=3
```

### Пропускная способность

- Каждый запрос: ~5 KB запрос + ~50 KB контекст + ~2 KB ответ
- Приём ETL: ~10 MB на 1000 документов (только текст)
- Обслуживание модели: эмбеддинги ~5 MB на батч, LLM ~50 MB на запрос (стриминг)
- Внутренняя сеть должна иметь >1 Gbps между прокси, Qdrant и LLM-бэкендом

## Устранение неполадок интеграции с OpenCode

```bash
# Проверьте доступность эндпоинта:
curl http://localhost:8080/v1/models

# Протестируйте завершение:
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RAG_API_KEY}" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "Какова структура проекта?"}]
  }'

# Проверьте логи OpenCode на ошибки подключения:
# "Connection refused" → прокси не запущен
# "401 Unauthorized" → несоответствие API-ключа
# "504 Gateway Timeout" → увеличьте REQUEST_TIMEOUT в .env
```
