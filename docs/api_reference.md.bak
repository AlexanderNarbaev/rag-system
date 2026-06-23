# API Reference / Справка по API

The RAG Proxy exposes an **OpenAI-compatible API** on port `8080`. Any OpenAI client can use it as a drop-in replacement — just point `base_url` to `http://<host>:8080/v1`.

RAG-прокси предоставляет **OpenAI-совместимый API** на порту `8080`. Любой OpenAI-клиент может использовать его как замену — достаточно указать `base_url` как `http://<host>:8080/v1`.

---

## Base URL / Базовый URL

```
http://<proxy-host>:8080/v1
```

All endpoints are prefixed with `/v1` to match the OpenAI API convention.

Все эндпоинты используют префикс `/v1` в соответствии с соглашением OpenAI API.

---

## Multi-Provider Support / Поддержка нескольких провайдеров

The proxy supports multiple LLM providers through the `LLM_PROVIDER_TYPE` environment variable. Each provider is handled by a dedicated adapter that transparently translates between the internal OpenAI-compatible format and the provider-specific API format.

Прокси поддерживает несколько LLM-провайдеров через переменную окружения `LLM_PROVIDER_TYPE`. Каждый провайдер обрабатывается отдельным адаптером, который прозрачно преобразует внутренний OpenAI-совместимый формат в формат API конкретного провайдера.

### Supported Providers / Поддерживаемые провайдеры

| Provider / Провайдер | `LLM_PROVIDER_TYPE` | Description / Описание |
|----------------------|---------------------|------------------------|
| **OpenAI-compatible** | `openai` | vLLM, llama.cpp, Ollama, LiteLLM, and any OpenAI-compatible endpoint |
| **Anthropic** | `anthropic` | Claude API via Anthropic Messages API |
| **Ollama** | `ollama` | Native Ollama API (minor differences from OpenAI-compatible) |
| **Generic** | `generic` | Custom REST API with configurable request/response transforms |

### Configuration / Настройка

Set in `proxy/.env`:

```bash
# Provider type (openai, anthropic, ollama, generic)
LLM_PROVIDER_TYPE=openai

# LLM endpoint URL
LLM_ENDPOINT=http://localhost:8000/v1

# Model name to request from the provider
LLM_MODEL_NAME=your-model-name

# API key (if required by the provider)
LLM_API_KEY=your-api-key
```

### Provider-Specific Notes / Особенности провайдеров

**Anthropic:**
- System prompt is passed via the dedicated `system` field (not as a message role)
- Tool calls are translated between OpenAI `tool_calls` format and Anthropic `tool_use` blocks
- Streaming SSE chunks are translated from Anthropic `content_block_delta` events
- Endpoint path is `/messages` (not `/chat/completions`)

**Ollama:**
- Uses `options` field for temperature and token limit parameters
- No `Authorization` header required by default
- OpenAI-compatible endpoint is available via `ollama serve`

**Generic:**
- Supports custom `request_transform` and `response_transform` callables
- Falls back to OpenAI-compatible format for all provider-specific fields

---

## Authentication / Аутентификация

Authentication is available via JWT tokens. When disabled (`AUTH_ENABLED=false`), the proxy accepts all requests without authentication.

Аутентификация доступна через JWT-токены. Если отключена (`AUTH_ENABLED=false`), прокси принимает все запросы без аутентификации.

When auth is enabled, include the API key in requests:

Если аутентификация включена, добавляйте токен в запросы:

```http
Authorization: Bearer <your-jwt-token>
```

### `POST /v1/auth/login`

Generate a JWT token for the given credentials. In production, this would validate against Keycloak/LDAP. For air-gapped deployments, it uses a credential store configured via `AUTH_VALID_USERS` environment variable.

Генерация JWT-токена по учётным данным. В production сценарии валидация выполняется через Keycloak/LDAP. Для автономных развёртываний используется хранилище учётных данных, настраиваемое через переменную `AUTH_VALID_USERS`.

#### Request / Запрос

```json
{
  "username": "user",
  "password": "pass",
  "expires_in_hours": 24
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `username` | string | Yes | — | Username / Имя пользователя |
| `password` | string | Yes | — | Password / Пароль |
| `expires_in_hours` | number | No | `24` | Token expiry in hours / Срок действия токена в часах |

#### Response / Ответ (200)

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

Refresh an existing JWT token. Validates the current token and issues a new one with the same claims but a fresh expiration timestamp.

Обновление существующего JWT-токена. Проверяет текущий токен и выдаёт новый с теми же правами, но обновлённым сроком действия.

#### Request / Запрос

```json
{
  "token": "eyJhbGciOi..."
}
```

#### Response / Ответ (200)

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

### `GET /v1/auth/me`

Return the current authenticated user's context (roles, groups, access level).

Возвращает контекст текущего аутентифицированного пользователя (роли, группы, уровень доступа).

#### Response / Ответ (200)

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

## Endpoints / Эндпоинты

### `POST /v1/chat/completions`

Chat completion with RAG augmentation. Accepts standard OpenAI parameters plus RAG-specific extensions.

Чат-завершение с RAG-дополнением. Принимает стандартные параметры OpenAI и RAG-расширения.

#### Request / Запрос

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

#### Standard Parameters / Стандартные параметры

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | string | Yes | — | Model ID. Use your configured `LLM_MODEL_NAME` or `rag-proxy` |
| `messages` | array | Yes | — | Chat messages. System prompt is replaced with RAG context |
| `temperature` | number | No | `0.2` | Sampling temperature (0–2) / Температура сэмплирования |
| `top_p` | number | No | `0.95` | Nucleus sampling / Nucleus-сэмплирование |
| `max_tokens` | number | No | `4096` | Maximum tokens in response / Максимум токенов в ответе |
| `stream` | boolean | No | `false` | Enable SSE streaming / Включить потоковую передачу SSE |

#### RAG-Specific Parameters / RAG-параметры

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `rag_version` | string | No | `null` | Request context from a specific document version (ISO date or SHA prefix) / Запросить контекст конкретной версии документа (дата ISO или префикс SHA) |
| `rag_force_refresh` | boolean | No | `false` | Bypass response cache and force fresh retrieval + generation / Пропустить кэш и принудительно выполнить поиск и генерацию |

#### Tool/Function Calling Parameters / Параметры вызова инструментов/функций

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `tools` | array | No | `null` | List of available tools/functions / Список доступных инструментов/функций |
| `tool_choice` | string/object | No | `"auto"` | Tool selection mode: `"none"`, `"auto"`, or specific function / Режим выбора инструмента |

Each tool object follows the OpenAI function calling format:

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

Tool calls are automatically translated between provider formats. When the LLM requests a tool call, the response includes a `tool_calls` array. The proxy accepts `tool` role messages with results for multi-turn tool use.

Вызовы инструментов автоматически преобразуются между форматами провайдеров. Когда LLM запрашивает вызов инструмента, ответ содержит массив `tool_calls`. Прокси принимает сообщения с ролью `tool` и результатами для многошагового использования инструментов.

#### Response (Non-Streaming) / Ответ (без потоковой передачи)

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

#### Response with Tool Calls / Ответ с вызовами инструментов

When the LLM requests a tool call, the response contains `tool_calls` in the message:

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

To continue the conversation with tool results, send a follow-up message with role `tool`:

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

#### Streaming Response (SSE) / Потоковый ответ (SSE)

When `"stream": true`, the response uses Server-Sent Events:

При `"stream": true` ответ передаётся через Server-Sent Events:

```
data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"role":"assistant","content":"Auth"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"content":"entication"},"finish_reason":null}]}

...

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

Each chunk follows the OpenAI streaming format:
- `delta` contains incremental content (instead of `message`)
- `finish_reason` is `null` until the final chunk

Каждый чанк следует формату OpenAI:
- `delta` содержит инкрементальный контент (вместо `message`)
- `finish_reason` равен `null` до финального чанка

#### RAG Pipeline (Under the Hood) / RAG-конвейер (под капотом)

When a chat completion request arrives, the proxy:

При поступлении запроса чат-завершения прокси выполняет:

1. **Embeds** the user query with the configured embedding model
2. **Searches** Qdrant with hybrid retrieval (dense + sparse, RRF fusion) — up to `MAX_CHUNKS_RETRIEVAL` results
3. **Reranks** results with cross-encoder — selects top `MAX_CHUNKS_AFTER_RERANK`
4. **Deduplicates** chunks by SHA-256 hash and filters by version
5. **Evaluates** retrieval quality (CRAG-style) — may trigger expansion, fallback, or normal assembly
6. **Assembles** context with smart token budget allocation
7. **Generates** response via the configured LLM provider
8. **Caches** response in Redis (unless `rag_force_refresh` is set)

1. **Эмбеддирует** запрос пользователя с помощью настроенной модели эмбеддингов
2. **Ищет** в Qdrant с гибридным поиском (dense + sparse, RRF-фьюжн) — до `MAX_CHUNKS_RETRIEVAL` результатов
3. **Реранжирует** результаты с помощью cross-encoder — отбирает верхние `MAX_CHUNKS_AFTER_RERANK`
4. **Дедуплицирует** чанки по SHA-256 хешу и фильтрует по версии
5. **Оценивает** качество поиска (CRAG-стиль) — может вызвать расширение, fallback или обычную сборку
6. **Собирает** контекст с интеллектуальным распределением бюджета токенов
7. **Генерирует** ответ через настроенного LLM-провайдера
8. **Кэширует** ответ в Redis (если не установлен `rag_force_refresh`)

With LangGraph enabled (`USE_LANGGRAPH=true`), the pipeline uses a 7-node agentic state graph with multi-step retrieval and self-correction.

При включённом LangGraph (`USE_LANGGRAPH=true`) используется 7-узловой агентный граф состояний с многошаговым поиском и самокоррекцией.

---

### `GET /v1/models`

List available models.

Список доступных моделей.

#### Request / Запрос

```http
GET /v1/models HTTP/1.1
```

#### Response / Ответ

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

- `your-model-name` — the actual LLM / фактическая LLM
- `rag-proxy` — virtual model alias for the full RAG pipeline / виртуальный псевдоним модели для полного RAG-конвейера

---

### `GET /v1/health`

Health check for the proxy and its dependencies.

Проверка работоспособности прокси и его зависимостей.

#### Request / Запрос

```http
GET /v1/health HTTP/1.1
```

#### Response (Healthy) / Ответ (здоров)

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

**HTTP 200** when all components are healthy.
**HTTP 200** когда все компоненты работают.

#### Response (Degraded) / Ответ (деградация)

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

**HTTP 503** when any component is unreachable.
**HTTP 503** когда любой компонент недоступен.

The proxy never crashes on component failure (graceful degradation). If Qdrant is down, retrieval returns empty results. If the LLM is down, the proxy returns a 503 on `/v1/chat/completions`.

Прокси никогда не падает при отказе компонентов (graceful degradation). Если Qdrant недоступен, поиск возвращает пустые результаты. Если LLM недоступен, прокси возвращает 503 на `/v1/chat/completions`.

---

### `GET /metrics`

Prometheus metrics in OpenMetrics format.

Метрики Prometheus в формате OpenMetrics.

#### Request / Запрос

```http
GET /metrics HTTP/1.1
```

#### Response (excerpt) / Ответ (фрагмент)

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

Key metrics / Ключевые метрики:

| Metric | Type | Description |
|--------|------|-------------|
| `rag_requests_total` | Counter | Total API requests by endpoint / Всего запросов по эндпоинтам |
| `rag_request_duration_seconds` | Histogram | Request latency (p50/p95/p99) / Задержка запросов |
| `rag_retrieval_chunks` | Histogram | Chunks retrieved per query / Чанков, найденных за запрос |
| `rag_rerank_duration_seconds` | Histogram | Reranker latency / Задержка реранкера |
| `rag_llm_duration_seconds` | Histogram | LLM generation latency / Задержка генерации LLM |
| `rag_llm_tokens_total` | Counter | Tokens used (prompt + completion) / Использовано токенов |
| `rag_cache_hit_ratio` | Gauge | Redis cache hit ratio / Коэффициент попадания в кэш Redis |
| `rag_errors_total` | Counter | Error count by type / Количество ошибок по типам |

---

## Error Codes / Коды ошибок

| HTTP Status | Meaning / Значение | Typical Cause / Типичная причина |
|-------------|-------------------|-----------------------------------|
| **200** | Success / Успех | Normal operation / Нормальная работа |
| **400** | Bad Request / Неверный запрос | Missing `messages`, empty user query, invalid JSON / Отсутствует `messages`, пустой запрос, невалидный JSON |
| **401** | Unauthorized / Не авторизован | Missing or invalid API key (when auth is enabled) / Отсутствует или неверный API-ключ |
| **429** | Too Many Requests / Слишком много запросов | Rate limit exceeded (when `RATE_LIMIT_ENABLED=true`) / Превышен лимит запросов |
| **500** | Internal Error / Внутренняя ошибка | Unhandled exception in the pipeline / Необработанное исключение в конвейере |
| **503** | Service Unavailable / Сервис недоступен | LLM or Qdrant unreachable, health check degraded / LLM или Qdrant недоступны |

### Rate Limiting / Ограничение частоты запросов

When enabled (`RATE_LIMIT_ENABLED=true`), a token bucket algorithm limits requests:

При включении (`RATE_LIMIT_ENABLED=true`) используется алгоритм token bucket:

| Config Variable | Default | Description |
|-----------------|---------|-------------|
| `RATE_LIMIT_PER_MINUTE` | `60` | Sustained requests per minute per IP / Устойчивых запросов в минуту на IP |
| `RATE_LIMIT_BURST` | `10` | Burst capacity above the sustained rate / Ёмкость всплеска сверх устойчивой скорости |

On rate limit exceed, the proxy returns:

При превышении лимита прокси возвращает:

```json
{
  "detail": "Rate limit exceeded. Try again later."
}
```

---

## Tool/Function Calling / Вызов инструментов и функций

The proxy supports OpenAI-compatible function/tool calling, allowing the LLM to request external function execution. Tool calls are transparently translated across all supported providers (OpenAI, Anthropic, Ollama, Generic).

Прокси поддерживает вызов функций/инструментов в формате OpenAI, позволяя LLM запрашивать выполнение внешних функций. Вызовы инструментов прозрачно преобразуются между всеми поддерживаемыми провайдерами.

### Tool Definition Format / Формат определения инструмента

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

### Multi-Turn Tool Use / Многошаговое использование инструментов

The proxy supports multi-turn conversations with tool calls. The flow is:

Прокси поддерживает многошаговые диалоги с вызовами инструментов. Процесс:

1. User sends a query → LLM may return `tool_calls`
2. Client executes the function and sends results back with role `tool`
3. LLM processes results and may request more tools or return final answer

1. Пользователь отправляет запрос → LLM может вернуть `tool_calls`
2. Клиент выполняет функцию и отправляет результаты с ролью `tool`
3. LLM обрабатывает результаты и может запросить ещё инструменты или вернуть финальный ответ

### Provider Translation / Трансляция между провайдерами

The proxy automatically translates tool definitions and responses:

Прокси автоматически преобразует определения инструментов и ответы:

| Format | OpenAI | Anthropic |
|--------|--------|-----------|
| Tool definition key | `tools[].function` | `tools[].input_schema` |
| Tool call ID | `tool_calls[].id` | `content[].id` |
| Tool call name | `tool_calls[].function.name` | `content[].name` |
| Tool call args | `tool_calls[].function.arguments` (JSON string) | `content[].input` (JSON object) |
| Tool result | `role: "tool"`, `tool_call_id` | `role: "user"`, `content: [{type: "tool_result", ...}]` |

---

## Environment Variable Reference / Справочник переменных окружения

All proxy configuration via environment variables (see `proxy/.env`).

Вся конфигурация прокси через переменные окружения (см. `proxy/.env`).

### Required / Обязательные

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_HOST` | `localhost` | Qdrant server hostname / Хост сервера Qdrant |
| `QDRANT_PORT` | `6333` | Qdrant gRPC port / gRPC-порт Qdrant |
| `LLM_ENDPOINT` | `http://localhost:8000/v1` | LLM provider endpoint / Эндпоинт LLM-провайдера |
| `LLM_MODEL_NAME` | (empty) | Model name to request from LLM endpoint / Имя модели для запроса к LLM |
| `LLM_PROVIDER_TYPE` | `openai` | Provider type: `openai`, `anthropic`, `ollama`, `generic` / Тип провайдера |

### Optional Features / Опциональные возможности

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_LANGGRAPH` | `false` | Enable agentic orchestration (7-node state graph) / Включить агентную оркестрацию |
| `USE_REDIS` | `false` | Enable Redis caching / Включить кэширование Redis |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string / Строка подключения Redis |
| `GRAPH_ENABLED` | `false` | Enable Neo4j connectivity / Включить подключение к Neo4j |
| `USE_GRAPH_EXPANSION` | `false` | Enable graph context enrichment / Включить обогащение контекста через граф |
| `METRICS_ENABLED` | `true` | Expose Prometheus `/metrics` endpoint / Открыть эндпоинт метрик Prometheus |
| `RATE_LIMIT_ENABLED` | `false` | Enable IP-based rate limiting / Включить ограничение по IP |
| `LOG_FORMAT` | `text` | Log format: `text` or structured `json` / Формат логов |
| `AUTH_ENABLED` | `false` | Enable JWT authentication / Включить JWT-аутентификацию |
| `LLM_API_KEY` | (empty) | API key for the LLM provider / API-ключ для LLM-провайдера |

### Tuning / Настройка

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_CHUNKS_RETRIEVAL` | `50` | Chunks to retrieve from Qdrant / Чанков для поиска в Qdrant |
| `MAX_CHUNKS_AFTER_RERANK` | `20` | Chunks after cross-encoder reranking / Чанков после реранжирования |
| `EMBEDDER_DEVICE` | `cpu` | Device for embedding model: `cpu` or `cuda` / Устройство для модели эмбеддингов |
| `RERANKER_BATCH_SIZE` | `32` | Batch size for cross-encoder / Размер батча для cross-encoder |
| `REQUEST_TIMEOUT` | `120` | LLM request timeout in seconds / Таймаут запроса к LLM в секундах |
| `MAX_RETRIES` | `3` | Retry attempts on LLM connection failure / Попыток повтора при ошибке соединения |
| `RETRY_DELAY` | `1.0` | Delay between retries in seconds / Задержка между повторами в секундах |
| `WORKERS` | `1` | Uvicorn worker processes (keep at 1 for shared caches) / Процессов-воркеров (держите 1 для общих кэшей) |
| `CORS_ORIGINS` | `*` | Allowed CORS origins / Разрешённые источники CORS |

### SLM / Small Language Model

| Variable | Default | Description |
|----------|---------|-------------|
| `SLM_ENDPOINT` | (empty) | SLM endpoint for routing/decomposition. Leave empty to disable SLM. / Эндпоинт SLM для маршрутизации. Оставьте пустым для отключения. |
| `SLM_MODEL_NAME` | (empty) | SLM model name / Имя SLM-модели |
| `SLM_API_KEY` | (empty) | API key for SLM / API-ключ для SLM |
| `SLM_MAX_TOKENS` | `256` | Max tokens for SLM responses / Максимум токенов для ответов SLM |

Full configuration reference: `proxy/app/config.py`

Полный справочник конфигурации: `proxy/app/config.py`

---

## Endpoint Summary / Сводка эндпоинтов

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/v1/chat/completions` | Optional | Chat completion with RAG / Чат-завершение с RAG |
| `GET` | `/v1/models` | No | List available models / Список моделей |
| `GET` | `/v1/health` | No | Health check / Проверка работоспособности |
| `GET` | `/metrics` | No | Prometheus metrics / Метрики Prometheus |
| `POST` | `/v1/auth/login` | No | JWT token generation / Генерация JWT-токена |
| `POST` | `/v1/auth/refresh` | Yes | Token refresh / Обновление токена |
| `GET` | `/v1/auth/me` | Yes | Current user info / Информация о текущем пользователе |

---

## SDK Usage Examples / Примеры использования SDK

### Python (openai package)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed"  # placeholder when auth is disabled / заглушка, если аутентификация отключена
)

# Non-streaming / Без потоковой передачи
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

# Streaming / Потоковая передача
stream = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Explain the ETL pipeline."}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")

# With tool calling / С вызовом инструментов
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
# Non-streaming / Без потоковой передачи
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "How many ADRs are there?"}],
    "temperature": 0.2,
    "max_tokens": 1024
  }'

# Streaming / Потоковая передача
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "model": "your-model-name",
    "messages": [{"role": "user", "content": "Summarize the deployment process."}],
    "stream": true
  }'

# With tool calling / С вызовом инструментов
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

# Health check / Проверка работоспособности
curl http://localhost:8080/v1/health

# List models / Список моделей
curl http://localhost:8080/v1/models

# Metrics / Метрики
curl http://localhost:8080/metrics

# Auth login / Вход
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "user", "password": "pass"}'

# Token refresh / Обновление токена
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{"token": "<your-token>"}'

# User info / Информация о пользователе
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

// Non-streaming
const completion = await client.chat.completions.create({
  model: "your-model-name",
  messages: [
    { role: "user", content: "What database does the system use?" },
  ],
  temperature: 0.2,
});
console.log(completion.choices[0].message.content);

// With tool calling
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
