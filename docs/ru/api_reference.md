# Справка по API

RAG-прокси предоставляет **OpenAI-совместимый API** на порту `8080`. Любой OpenAI-клиент может использовать его как замену — достаточно указать `base_url` как `http://<host>:8080/v1`.

---

## Базовый URL

```
http://<proxy-host>:8080/v1
```

Все эндпоинты используют префикс `/v1` в соответствии с соглашением OpenAI API.

---

## Поддержка нескольких провайдеров

Прокси поддерживает несколько LLM-провайдеров через переменную окружения `LLM_PROVIDER_TYPE`. Каждый провайдер обрабатывается отдельным адаптером, который прозрачно преобразует внутренний OpenAI-совместимый формат в формат API конкретного провайдера.

### Поддерживаемые провайдеры

| Провайдер | `LLM_PROVIDER_TYPE` | Описание |
|-----------|---------------------|----------|
| **OpenAI-совместимый** | `openai` | vLLM, llama.cpp, Ollama, LiteLLM и любые OpenAI-совместимые эндпоинты |
| **Anthropic** | `anthropic` | Claude API через Anthropic Messages API |
| **Ollama** | `ollama` | Нативный API Ollama (незначительные отличия от OpenAI-совместимого) |
| **Generic** | `generic` | Пользовательский REST API с настраиваемыми преобразованиями запросов/ответов |

### Настройка

Настройте в `proxy/.env`:

```bash
# Тип провайдера (openai, anthropic, ollama, generic)
LLM_PROVIDER_TYPE=openai

# URL эндпоинта LLM
LLM_ENDPOINT=http://localhost:8000/v1

# Имя модели для запроса к провайдеру
LLM_MODEL_NAME=your-model-name

# API-ключ (если требуется провайдером)
LLM_API_KEY=your-api-key
```

### Особенности провайдеров

**Anthropic:**
- Системный промпт передаётся через выделенное поле `system` (не как роль сообщения)
- Вызовы инструментов преобразуются между форматом `tool_calls` OpenAI и блоками `tool_use` Anthropic
- Потоковые SSE-чанки преобразуются из событий `content_block_delta` Anthropic
- Путь эндпоинта — `/messages` (не `/chat/completions`)

**Ollama:**
- Использует поле `options` для параметров температуры и лимита токенов
- Заголовок `Authorization` не требуется по умолчанию
- OpenAI-совместимый эндпоинт доступен через `ollama serve`

**Generic:**
- Поддерживает пользовательские вызываемые объекты `request_transform` и `response_transform`
- Возвращается к OpenAI-совместимому формату для всех провайдер-специфичных полей

---

## Аутентификация

Аутентификация доступна через JWT-токены. Если отключена (`AUTH_ENABLED=false`), прокси принимает все запросы без аутентификации.

Если аутентификация включена, добавляйте токен в запросы:

```http
Authorization: Bearer <your-jwt-token>
```

### `POST /v1/auth/login`

Генерация JWT-токена по учётным данным. В production сценарии валидация выполняется через Keycloak/LDAP. Для автономных развёртываний используется хранилище учётных данных, настраиваемое через переменную `AUTH_VALID_USERS`.

#### Запрос

```json
{
  "username": "user",
  "password": "pass",
  "expires_in_hours": 24
}
```

| Поле | Тип | Обязательное | По умолчанию | Описание |
|------|-----|-------------|--------------|----------|
| `username` | string | Да | — | Имя пользователя |
| `password` | string | Да | — | Пароль |
| `expires_in_hours` | number | Нет | `24` | Срок действия токена в часах |

#### Ответ (200)

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user_id": "user123",
  "username": "user",
  "roles": ["viewer"],
  "groups": ["engineering"]
}
```

### `POST /v1/auth/refresh`

Обновление существующего JWT-токена. Проверяет текущий токен и выдаёт новый с теми же правами, но обновлённым сроком действия.

#### Запрос

```json
{
  "token": "eyJhbGciOi..."
}
```

#### Ответ (200)

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

### `GET /v1/auth/me`

Возвращает контекст текущего аутентифицированного пользователя (роли, группы, уровень доступа).

#### Ответ (200)

```json
{
  "user_id": "user123",
  "username": "user",
  "roles": ["viewer"],
  "groups": ["engineering"],
  "access_level": "internal",
  "is_admin": false,
  "is_authenticated": true
}
```

---

## Эндпоинты

### `POST /v1/chat/completions`

Чат-завершение с RAG-дополнением. Принимает стандартные параметры OpenAI и RAG-расширения.

#### Запрос

```json
{
  "model": "your-model-name",
  "messages": [
    {"role": "system", "content": "You are a technical assistant."},
    {"role": "user", "content": "How is authentication implemented in the backend?"}
  ],
  "temperature": 0.2,
  "top_p": 0.95,
  "max_tokens": 4096,
  "stream": false
}
```

#### Стандартные параметры

| Поле | Тип | Обязательное | По умолчанию | Описание |
|------|-----|-------------|--------------|----------|
| `model` | string | Да | — | ID модели. Используйте настроенный `LLM_MODEL_NAME` или `rag-proxy` |
| `messages` | array | Да | — | Сообщения чата. Системный промпт заменяется RAG-контекстом |
| `temperature` | number | Нет | `0.2` | Температура сэмплирования (0–2) |
| `top_p` | number | Нет | `0.95` | Nucleus-сэмплирование |
| `max_tokens` | number | Нет | `4096` | Максимум токенов в ответе |
| `stream` | boolean | Нет | `false` | Включить потоковую передачу SSE |

#### RAG-параметры

| Поле | Тип | Обязательное | По умолчанию | Описание |
|------|-----|-------------|--------------|----------|
| `rag_version` | string | Нет | `null` | Запросить контекст конкретной версии документа (дата ISO или префикс SHA) |
| `rag_force_refresh` | boolean | Нет | `false` | Пропустить кэш и принудительно выполнить поиск и генерацию |

#### Параметры вызова инструментов/функций

| Поле | Тип | Обязательное | По умолчанию | Описание |
|------|-----|-------------|--------------|----------|
| `tools` | array | Нет | `null` | Список доступных инструментов/функций |
| `tool_choice` | string/object | Нет | `"auto"` | Режим выбора инструмента: `"none"`, `"auto"` или конкретная функция |

Каждый объект инструмента соответствует формату вызова функций OpenAI:

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get current weather for a city",
    "parameters": {
      "type": "object",
      "properties": {
        "city": {
          "type": "string",
          "description": "City name"
        },
        "units": {
          "type": "string",
          "enum": ["celsius", "fahrenheit"],
          "description": "Temperature units"
        }
      },
      "required": ["city"]
    }
  }
}
```

Вызовы инструментов автоматически преобразуются между форматами провайдеров. Когда LLM запрашивает вызов инструмента, ответ содержит массив `tool_calls`. Прокси принимает сообщения с ролью `tool` и результатами для многошагового использования инструментов.

#### Ответ (без потоковой передачи)

```json
{
  "id": "rag_1719057600_a1b2c3d4",
  "object": "chat.completion",
  "created": 1719057600,
  "model": "your-model-name",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Authentication is implemented using JWT tokens with Redis-based session management...\n\nSources: [Confluence: Auth Service ADR], [src/auth/middleware.py:42]"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 1250,
    "completion_tokens": 180,
    "total_tokens": 1430
  }
}
```

#### Ответ с вызовами инструментов

Когда LLM запрашивает вызов инструмента, ответ содержит `tool_calls` в сообщении:

```json
{
  "id": "rag_1719057600_a1b2c3d4",
  "object": "chat.completion",
  "created": 1719057600,
  "model": "your-model-name",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "get_weather",
              "arguments": "{\"city\":\"Moscow\",\"units\":\"celsius\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ]
}
```

Чтобы продолжить диалог с результатами инструмента, отправьте последующее сообщение с ролью `tool`:

```json
{
  "model": "your-model-name",
  "messages": [
    {"role": "user", "content": "What is the weather in Moscow?"},
    {"role": "assistant", "content": null, "tool_calls": [{"id": "call_abc123", "type": "function", "function": {"name": "get_weather", "arguments": "{\"city\":\"Moscow\"}"}}]},
    {"role": "tool", "tool_call_id": "call_abc123", "name": "get_weather", "content": "{\"temperature\": 22, \"condition\": \"sunny\"}"}
  ]
}
```

#### Потоковый ответ (SSE)

При `"stream": true` ответ передаётся через Server-Sent Events:

```
data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"role":"assistant","content":"Auth"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"content":"entication"},"finish_reason":null}]}

...

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Каждый чанк следует формату OpenAI:
- `delta` содержит инкрементальный контент (вместо `message`)
- `finish_reason` равен `null` до финального чанка

#### RAG-конвейер (под капотом)

При поступлении запроса чат-завершения прокси выполняет:

1. **Эмбеддирует** запрос пользователя с помощью настроенной модели эмбеддингов
2. **Ищет** в Qdrant с гибридным поиском (dense + sparse, RRF-фьюжн) — до `MAX_CHUNKS_RETRIEVAL` результатов
3. **Реранжирует** результаты с помощью cross-encoder — отбирает верхние `MAX_CHUNKS_AFTER_RERANK`
4. **Дедуплицирует** чанки по SHA-256 хешу и фильтрует по версии
5. **Оценивает** качество поиска (CRAG-стиль) — может вызвать расширение, fallback или обычную сборку
6. **Собирает** контекст с интеллектуальным распределением бюджета токенов
7. **Генерирует** ответ через настроенного LLM-провайдера
8. **Кэширует** ответ в Redis (если не установлен `rag_force_refresh`)

При включённом LangGraph (`USE_LANGGRAPH=true`) используется 7-узловой агентный граф состояний с многошаговым поиском и самокоррекцией.

---

### `GET /v1/models`

Список доступных моделей.

#### Запрос

```http
GET /v1/models HTTP/1.1
```

#### Ответ

```json
{
  "object": "list",
  "data": [
    {
      "id": "your-model-name",
      "object": "model",
      "created": 1719057600,
      "owned_by": "local"
    },
    {
      "id": "rag-proxy",
      "object": "model",
      "created": 1719057600,
      "owned_by": "local"
    }
  ]
}
```

- `your-model-name` — фактическая LLM
- `rag-proxy` — виртуальный псевдоним модели для полного RAG-конвейера

---

### `GET /v1/health`

Проверка работоспособности прокси и его зависимостей.

#### Запрос

```http
GET /v1/health HTTP/1.1
```

#### Ответ (здоров)

```json
{
  "status": "ok",
  "timestamp": "2026-06-22T10:00:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "ok"
  }
}
```

**HTTP 200** когда все компоненты работают.

#### Ответ (деградация)

```json
{
  "status": "degraded",
  "timestamp": "2026-06-22T10:00:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "error: Connection refused"
  }
}
```

**HTTP 503** когда любой компонент недоступен.

Прокси никогда не падает при отказе компонентов (graceful degradation). Если Qdrant недоступен, поиск возвращает пустые результаты. Если LLM недоступен, прокси возвращает 503 на `/v1/chat/completions`.

---

### `GET /metrics`

Метрики Prometheus в формате OpenMetrics.

#### Запрос

```http
GET /metrics HTTP/1.1
```

#### Ответ (фрагмент)

```
# HELP rag_requests_total Total API requests
# TYPE rag_requests_total counter
rag_requests_total{endpoint="/v1/chat/completions"} 1423
rag_requests_total{endpoint="/v1/models"} 89

# HELP rag_request_duration_seconds Request latency
# TYPE rag_request_duration_seconds histogram
rag_request_duration_seconds_bucket{le="0.1"} 12
rag_request_duration_seconds_bucket{le="0.5"} 87
rag_request_duration_seconds_bucket{le="1.0"} 234
rag_request_duration_seconds_bucket{le="5.0"} 1201
rag_request_duration_seconds_bucket{le="+Inf"} 1423

# HELP rag_llm_tokens_total Total tokens used
# TYPE rag_llm_tokens_total counter
rag_llm_tokens_total{type="prompt"} 1780000
rag_llm_tokens_total{type="completion"} 256000

# HELP rag_cache_hit_ratio Cache hit ratio
# TYPE rag_cache_hit_ratio gauge
rag_cache_hit_ratio 0.62
```

Ключевые метрики:

| Метрика | Тип | Описание |
|--------|------|----------|
| `rag_requests_total` | Counter | Всего запросов по эндпоинтам |
| `rag_request_duration_seconds` | Histogram | Задержка запросов (p50/p95/p99) |
| `rag_retrieval_chunks` | Histogram | Чанков, найденных за запрос |
| `rag_rerank_duration_seconds` | Histogram | Задержка реранкера |
| `rag_llm_duration_seconds` | Histogram | Задержка генерации LLM |
| `rag_llm_tokens_total` | Counter | Использовано токенов (prompt + completion) |
| `rag_cache_hit_ratio` | Gauge | Коэффициент попадания в кэш Redis |
| `rag_errors_total` | Counter | Количество ошибок по типам |

---

## Коды ошибок

| HTTP Status | Значение | Типичная причина |
|-------------|----------|------------------|
| **200** | Успех | Нормальная работа |
| **400** | Неверный запрос | Отсутствует `messages`, пустой запрос, невалидный JSON |
| **401** | Не авторизован | Отсутствует или неверный API-ключ (при включённой аутентификации) |
| **429** | Слишком много запросов | Превышен лимит запросов (при `RATE_LIMIT_ENABLED=true`) |
| **500** | Внутренняя ошибка | Необработанное исключение в конвейере |
| **503** | Сервис недоступен | LLM или Qdrant недоступны |

### Ограничение частоты запросов

При включении (`RATE_LIMIT_ENABLED=true`) используется алгоритм token bucket:

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `RATE_LIMIT_PER_MINUTE` | `60` | Устойчивых запросов в минуту на IP |
| `RATE_LIMIT_BURST` | `10` | Ёмкость всплеска сверх устойчивой скорости |

При превышении лимита прокси возвращает:

```json
{
  "detail": "Rate limit exceeded. Try again later."
}
```

---

## Вызов инструментов и функций

Прокси поддерживает вызов функций/инструментов в формате OpenAI, позволяя LLM запрашивать выполнение внешних функций. Вызовы инструментов прозрачно преобразуются между всеми поддерживаемыми провайдерами.

### Формат определения инструмента

```json
{
  "type": "function",
  "function": {
    "name": "search_documents",
    "description": "Search the knowledge base for relevant documents",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "The search query"
        },
        "max_results": {
          "type": "integer",
          "description": "Maximum number of results",
          "default": 5
        }
      },
      "required": ["query"]
    }
  }
}
```

### Многошаговое использование инструментов

Прокси поддерживает многошаговые диалоги с вызовами инструментов. Процесс:

1. Пользователь отправляет запрос → LLM может вернуть `tool_calls`
2. Клиент выполняет функцию и отправляет результаты с ролью `tool`
3. LLM обрабатывает результаты и может запросить ещё инструменты или вернуть финальный ответ

### Трансляция между провайдерами

Прокси автоматически преобразует определения инструментов и ответы:

| Формат | OpenAI | Anthropic |
|--------|--------|-----------|
| Ключ определения инструмента | `tools[].function` | `tools[].input_schema` |
| ID вызова инструмента | `tool_calls[].id` | `content[].id` |
| Имя вызова инструмента | `tool_calls[].function.name` | `content[].name` |
| Аргументы вызова | `tool_calls[].function.arguments` (строка JSON) | `content[].input` (объект JSON) |
| Результат инструмента | `role: "tool"`, `tool_call_id` | `role: "user"`, `content: [{type: "tool_result", ...}]` |

---

## Справочник переменных окружения

Вся конфигурация прокси через переменные окружения (см. `proxy/.env`).

### Обязательные

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `QDRANT_HOST` | `localhost` | Хост сервера Qdrant |
| `QDRANT_PORT` | `6333` | gRPC-порт Qdrant |
| `LLM_ENDPOINT` | `http://localhost:8000/v1` | Эндпоинт LLM-провайдера |
| `LLM_MODEL_NAME` | (пусто) | Имя модели для запроса к LLM |
| `LLM_PROVIDER_TYPE` | `openai` | Тип провайдера: `openai`, `anthropic`, `ollama`, `generic` |

### Опциональные возможности

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `USE_LANGGRAPH` | `false` | Включить агентную оркестрацию (7-узловой граф состояний) |
| `USE_REDIS` | `false` | Включить кэширование Redis |
| `REDIS_URL` | `redis://localhost:6379` | Строка подключения Redis |
| `GRAPH_ENABLED` | `false` | Включить подключение к Neo4j |
| `USE_GRAPH_EXPANSION` | `false` | Включить обогащение контекста через граф |
| `METRICS_ENABLED` | `true` | Открыть эндпоинт метрик Prometheus |
| `RATE_LIMIT_ENABLED` | `false` | Включить ограничение по IP |
| `LOG_FORMAT` | `text` | Формат логов: `text` или структурированный `json` |
| `AUTH_ENABLED` | `false` | Включить JWT-аутентификацию |
| `LLM_API_KEY` | (пусто) | API-ключ для LLM-провайдера |

### Настройка

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `MAX_CHUNKS_RETRIEVAL` | `50` | Чанков для поиска в Qdrant |
| `MAX_CHUNKS_AFTER_RERANK` | `20` | Чанков после реранжирования |
| `EMBEDDER_DEVICE` | `cpu` | Устройство для модели эмбеддингов: `cpu` или `cuda` |
| `RERANKER_BATCH_SIZE` | `32` | Размер батча для cross-encoder |
| `REQUEST_TIMEOUT` | `120` | Таймаут запроса к LLM в секундах |
| `MAX_RETRIES` | `3` | Попыток повтора при ошибке соединения |
| `RETRY_DELAY` | `1.0` | Задержка между повторами в секундах |
| `WORKERS` | `1` | Процессов-воркеров (держите 1 для общих кэшей) |
| `CORS_ORIGINS` | `*` | Разрешённые источники CORS |

### SLM / Малая языковая модель

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `SLM_ENDPOINT` | (пусто) | Эндпоинт SLM для маршрутизации. Оставьте пустым для отключения. |
| `SLM_MODEL_NAME` | (пусто) | Имя SLM-модели |
| `SLM_API_KEY` | (пусто) | API-ключ для SLM |
| `SLM_MAX_TOKENS` | `256` | Максимум токенов для ответов SLM |

Полный справочник конфигурации: `proxy/app/config.py`

---

## Сводка эндпоинтов

| Метод | Эндпоинт | Auth | Описание |
|-------|----------|------|----------|
| `POST` | `/v1/chat/completions` | Опционально | Чат-завершение с RAG |
| `GET` | `/v1/models` | Нет | Список моделей |
| `GET` | `/v1/health` | Нет | Проверка работоспособности |
| `GET` | `/metrics` | Нет | Метрики Prometheus |
| `POST` | `/v1/auth/login` | Нет | Генерация JWT-токена |
| `POST` | `/v1/auth/refresh` | Да | Обновление токена |
| `GET` | `/v1/auth/me` | Да | Информация о текущем пользователе |

---

## Примеры использования SDK

### Python (пакет openai)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed"  # заглушка, если аутентификация отключена
)

# Без потоковой передачи
response = client.chat.completions.create(
    model="your-model-name",
    messages=[
        {"role": "user", "content": "What is the project structure?"}
    ],
    temperature=0.2,
    max_tokens=4096,
    extra_body={
        "rag_version": "2026-01-15",
        "rag_force_refresh": False
    }
)
print(response.choices[0].message.content)

# Потоковая передача
stream = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Explain the ETL pipeline."}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")

# С вызовом инструментов
response = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "What is the weather in Moscow?"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"}
                },
                "required": ["city"]
            }
        }
    }],
    tool_choice="auto"
)
print(response.choices[0].message.tool_calls)
```

### cURL

```bash
# Без потоковой передачи
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "How many ADRs are there?"}],
    "temperature": 0.2,
    "max_tokens": 1024
  }'

# Потоковая передача
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "Summarize the deployment process."}],
    "stream": true
  }'

# С вызовом инструментов
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "What is 25 + 17?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "calculator",
        "description": "Perform arithmetic operations",
        "parameters": {
          "type": "object",
          "properties": {
            "expression": {"type": "string", "description": "Arithmetic expression"}
          },
          "required": ["expression"]
        }
      }
    }]
  }'

# Проверка работоспособности
curl http://localhost:8080/v1/health

# Список моделей
curl http://localhost:8080/v1/models

# Метрики
curl http://localhost:8080/metrics

# Вход
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "user", "password": "pass"}'

# Обновление токена
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{"token": "<your-token>"}'

# Информация о пользователе
curl http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer <your-token>"
```

### JavaScript / TypeScript

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "not-needed",
});

// Без потоковой передачи
const completion = await client.chat.completions.create({
  model: "your-model-name",
  messages: [
    { role: "user", content: "What database does the system use?" },
  ],
  temperature: 0.2,
});
console.log(completion.choices[0].message.content);

// С вызовом инструментов
const toolCompletion = await client.chat.completions.create({
  model: "your-model-name",
  messages: [
    { role: "user", content: "Search for deployment documentation." },
  ],
  tools: [{
    type: "function",
    function: {
      name: "search_docs",
      description: "Search the knowledge base",
      parameters: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query" },
        },
        required: ["query"],
      },
    },
  }],
});
console.log(toolCompletion.choices[0].message.tool_calls);
```
