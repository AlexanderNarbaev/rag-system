# Справка по API

RAG-прокси предоставляет **OpenAI-совместимый API** на порту `8080`. Любой OpenAI-клиент может использовать его как замену — достаточно указать `base_url` как `http://<host>:8080/v1`. Прокси также добавляет RAG-специфичные расширения для обратной связи, оценки уверенности и прослеживаемости источников.

---

## Базовый URL

```
http://<proxy-host>:8080/v1
```

Все эндпоинты используют префикс `/v1` в соответствии с соглашением OpenAI API. Эндпоинт `/metrics` доступен на корневом уровне.

---

## Аутентификация

### Обзор

Аутентификация реализована через JWT-токены. Если отключена (`AUTH_ENABLED=false`, по умолчанию), прокси принимает все запросы без аутентификации. При включении все эндпоинты, кроме `/v1/auth/login`, `/v1/health` и `/metrics`, требуют валидный JWT.

### Жизненный цикл токена

```
Клиент                    Прокси                    Keycloak/LDAP
  |                          |                           |
  |-- POST /v1/auth/login -->|                           |
  |   {username, password}   |-- валидация уч. данных -->|
  |                          |<---- контекст польз. -----|
  |<--- JWT токен ----------|                           |
  |                          |                           |
  |-- API запрос ----------->|                           |
  |   Authorization: Bearer  |-- проверка JWT ---------->|
  |                          |<---- валиден -------------|
  |<--- ответ ---------------|                           |
  |                          |                           |
  |-- POST /v1/auth/refresh >|                           |
  |   (до истечения)         |-- обновление JWT -------->|
  |                          |<---- новый токен ---------|
  |<--- новый JWT -----------|                           |
```

### Настройка

```bash
# Включить аутентификацию
AUTH_ENABLED=true

# Секрет подписи JWT (сгенерируйте: openssl rand -hex 32)
JWT_SECRET=your-256-bit-secret

# Для автономных развёртываний (без Keycloak):
# Список пар user:password_hash:role через запятую
AUTH_VALID_USERS=admin:$2b$12$...:admin,viewer:$2b$12$...:viewer

# Настройки токена
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24
```

---

## Эндпоинты

### `POST /v1/chat/completions`

Чат-завершение с RAG-дополнением. Принимает стандартные параметры OpenAI и RAG-расширения.

#### Схема запроса

```json
{
  "model": "string (обязательно)",
  "messages": [
    {
      "role": "string (system | user | assistant | tool)",
      "content": "string | array (обязательно)",
      "name": "string (опционально)",
      "tool_call_id": "string (обязательно для роли tool)",
      "tool_calls": [
        {
          "id": "string",
          "type": "function",
          "function": {
            "name": "string",
            "arguments": "string (JSON-строка)"
          }
        }
      ]
    }
  ],
  "temperature": "number (0-2, по умолчанию: 0.2)",
  "top_p": "number (0-1, по умолчанию: 0.95)",
  "max_tokens": "integer (по умолчанию: 4096)",
  "stream": "boolean (по умолчанию: false)",
  "stop": ["string (опционально)"],
  "presence_penalty": "number (-2.0 до 2.0, опционально)",
  "frequency_penalty": "number (-2.0 до 2.0, опционально)",
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "string",
        "description": "string",
        "parameters": "object (JSON Schema)"
      }
    }
  ],
  "tool_choice": "string | object (none | auto | {type: 'function', function: {name: '...'}})",
  "rag_version": "string (опционально)",
  "rag_force_refresh": "boolean (по умолчанию: false)"
}
```

#### Стандартные параметры

| Поле | Тип | Обязательное | По умолчанию | Описание |
|-------|------|----------|---------|-------------|
| `model` | string | Да | — | ID модели. Используйте настроенный `LLM_MODEL_NAME` или виртуальную модель `rag-proxy` для полного RAG-конвейера |
| `messages` | array | Да | — | Сообщения чата. Системный промпт включается в RAG-контекст |
| `temperature` | number | Нет | `0.2` | Температура сэмплирования (0–2). Ниже = детерминированнее |
| `top_p` | number | Нет | `0.95` | Порог nucleus-сэмплирования |
| `max_tokens` | number | Нет | `4096` | Максимум токенов в сгенерированном ответе |
| `stream` | boolean | Нет | `false` | Включить потоковую передачу Server-Sent Events |
| `stop` | array | Нет | `null` | До 4 стоп-последовательностей |
| `presence_penalty` | number | Нет | `null` | Штраф за повторение токенов (-2.0 до 2.0) |
| `frequency_penalty` | number | Нет | `null` | Штраф за частые токены (-2.0 до 2.0) |
| `tools` | array | Нет | `null` | Определения доступных инструментов/функций |
| `tool_choice` | string/object | Нет | `"auto"` | Выбор инструмента: `"none"`, `"auto"` или конкретная функция |

#### RAG-специфичные параметры

Эти параметры расширяют стандартную схему OpenAI. Они игнорируются стандартными OpenAI-клиентами и влияют на поведение только при прохождении запроса через RAG-прокси.

| Поле | Тип | Обязательное | По умолчанию | Описание |
|-------|------|----------|---------|-------------|
| `rag_version` | string | Нет | `null` | Запросить контекст конкретной версии документа. Принимает дату ISO (`"2026-01-15"`), префикс SHA-256 (`"a1b2c3d4"`) или тег версии (`"v2.1"`). Фильтрует найденные чанки по указанной версии. |
| `rag_force_refresh` | boolean | Нет | `false` | Пропустить кэш ответов Redis. Принудительно выполняет новый поиск, реранкинг, сборку контекста и генерацию LLM. Полезно, когда документы обновлены, а кэшированные ответы устарели. |

#### Схема ответа (без потока, 200 OK)

```json
{
  "id": "string",
  "object": "chat.completion",
  "created": "integer (unix timestamp)",
  "model": "string",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "string | null (null при наличии tool_calls)",
        "tool_calls": [
          {
            "id": "string",
            "type": "function",
            "function": {
              "name": "string",
              "arguments": "string (JSON-строка)"
            }
          }
        ]
      },
      "finish_reason": "string (stop | length | tool_calls | content_filter)"
    }
  ],
  "usage": {
    "prompt_tokens": "integer",
    "completion_tokens": "integer",
    "total_tokens": "integer"
  },
  "rag_feedback_id": "string | null",
  "rag_confidence": "float (0.0–1.0) | null",
  "rag_sources": [
    {
      "chunk_id": "string (SHA-256 хеш)",
      "source": "string (название документа)",
      "source_type": "string (confluence | jira | gitlab | document | book | chat)",
      "version": "string (форматированная дата)",
      "relevance_score": "float",
      "url": "string | null"
    }
  ]
}
```

#### RAG-расширения ответа

| Поле | Тип | Описание |
|-------|------|-------------|
| `rag_feedback_id` | string | Уникальный ID для отправки экспертной обратной связи через `/v1/feedback`. Генерируется для каждого ответа. |
| `rag_confidence` | float | Оценка уверенности (0.0–1.0). На основе достаточности контекста, соотношения длины ответа к контексту и обнаружения фраз неуверенности. Значения ниже 0.5 активируют флаг `needs_review`. |
| `rag_sources` | array | Найденные чанки, использованные для генерации ответа. Каждая запись включает ID чанка, исходный документ, тип, версию, оценку релевантности и опциональный URL. Полезно для цитирования и аудита. |

#### Ответ с вызовом инструментов

Когда LLM запрашивает вызов инструмента, `content` равен `null`, а `tool_calls` заполнен:

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
              "name": "search_knowledge_base",
              "arguments": "{\"query\":\"процесс развёртывания\",\"max_results\":5}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "rag_feedback_id": "fbk_1719057600_d4e5f6g7",
  "rag_confidence": 0.85
}
```

Для продолжения диалога с результатами инструмента отправьте последующее сообщение с ролью `tool`:

```json
{
  "model": "your-model-name",
  "messages": [
    {"role": "user", "content": "Как развернуть прокси?"},
    {"role": "assistant", "content": null, "tool_calls": [
      {"id": "call_abc123", "type": "function", "function": {"name": "search_knowledge_base", "arguments": "{\"query\":\"развёртывание\"}"}}
    ]},
    {"role": "tool", "tool_call_id": "call_abc123", "name": "search_knowledge_base", "content": "Прокси разворачивается через docker-compose up -d из директории proxy/..."}
  ]
}
```

#### Потоковый ответ (SSE)

При `"stream": true` ответ передаётся через Server-Sent Events с типом содержимого `text/event-stream`:

```
data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"content":"Прокси"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{"content":" разворачивается"},"finish_reason":null}]}

data: {"id":"rag_1719057600_a1b2c3d4","object":"chat.completion.chunk","created":1719057600,"model":"your-model-name","choices":[{"index":0,"delta":{},"finish_reason":"stop","rag_feedback_id":"fbk_1719057600_d4e5f6g7","rag_confidence":0.82,"rag_sources":[...]}]}

data: [DONE]
```

**Особенности потоковой передачи:**

- `delta` содержит инкрементальный контент (вместо `message`)
- `finish_reason` равен `null` до финального чанка
- RAG-расширения (`rag_feedback_id`, `rag_confidence`, `rag_sources`) появляются только в **финальном чанке**
- Сигнал `[DONE]` завершает поток
- При потоковой передаче вызовов инструментов `delta.tool_calls` заполняется инкрементально

#### RAG-конвейер (под капотом)

При поступлении запроса чат-завершения прокси выполняет:

1. **Анализ запроса** — SLM классифицирует интент (5 классов: фактический, процедурный, сравнение, устранение неполадок, мета), опционально декомпозирует на подзапросы, извлекает сущности
2. **Гибридный поиск** — Плотные (BGE-M3 1024-dim) + разреженные (лексические BM25-style) векторы ищутся в Qdrant с RRF-фьюжном (k=60). Возвращает до `MAX_CHUNKS_RETRIEVAL` (по умолчанию 50) чанков
3. **Оценка качества поиска** — `RetrievalEvaluator` оценивает результаты (уверенность 0.0–1.0) на основе распределения score, коэффициента покрытия и количества результатов. Определяет действие: `USE`, `REWRITE`, `EXPAND` или `FALLBACK`
4. **Переписывание запроса** (при необходимости) — SLM или LLM переписывает неоднозначные/неудачные запросы; до `MAX_RETRIEVAL_LOOPS=3` итераций
5. **Cross-Encoder реранкинг** — MiniLM-L-6-v2 оценивает top-N кандидатов, отбирает верхние `MAX_CHUNKS_AFTER_RERANK` (по умолчанию 20)
6. **Расширение графа** (опционально, `USE_GRAPH_EXPANSION=true`) — многошаговый обход Neo4j обогащает контекст связанными сущностями
7. **Дедупликация и фильтрация версий** — чанки дедуплицируются по SHA-256 хешу; фильтруются по `rag_version`, если указана
8. **Сборка контекста** — `TokenOptimizer` распределяет бюджет токенов между системным промптом, контекстом, историей и ответом. Применяет до 4 стратегий сжатия
9. **Генерация LLM** — собранный промпт отправляется настроенному LLM-провайдеру (vLLM, llama.cpp, Anthropic, Ollama или generic OpenAI-compatible)
10. **Оценка уверенности** — эвристика `compute_confidence()`: достаточность контекста (вес 0.4), соотношение контекст/ответ (0.3), обнаружение фраз неуверенности (0.2), проверка длины ответа (0.1)
11. **Кэширование ответа** — ответ кэшируется в Redis (1ч TTL), если не установлен `rag_force_refresh=true`

---

### `GET /v1/models`

Список доступных моделей.

#### Ответ (200 OK)

```json
{
  "object": "list",
  "data": [
    {
      "id": "string",
      "object": "model",
      "created": "integer (unix timestamp)",
      "owned_by": "string"
    }
  ]
}
```

- `llama-3-70b-instruct` — фактическая LLM, настроенная через `LLM_MODEL_NAME`
- `rag-proxy` — виртуальный псевдоним модели. При использовании прокси применяет полный RAG-конвейер перед вызовом LLM

---

### `GET /v1/health`

Проверка работоспособности прокси и его зависимостей.

#### Ответ (200 OK — Здоров)

```json
{
  "status": "ok",
  "timestamp": "string (ISO 8601)",
  "version": "string",
  "components": {
    "qdrant": "ok",
    "llm": "ok",
    "neo4j": "ok | disabled",
    "redis": "ok | disabled",
    "slm": "ok | disabled"
  }
}
```

#### Ответ (503 — Деградация)

```json
{
  "status": "degraded",
  "timestamp": "string (ISO 8601)",
  "version": "string",
  "components": {
    "qdrant": "ok",
    "llm": "error: Connection refused",
    "neo4j": "disabled",
    "redis": "ok",
    "slm": "error: timeout"
  },
  "degraded_reason": "LLM backend unreachable"
}
```

**Значения статуса компонентов:**

| Значение | Описание |
|----------|----------|
| `ok` | Компонент ответил в пределах таймаута |
| `error: <сообщение>` | Компонент недоступен или вернул ошибку |
| `disabled` | Компонент не настроен (например, `USE_REDIS=false`) |

**Graceful degradation:** Прокси никогда не падает при отказе компонентов. Если Qdrant недоступен, поиск возвращает пустые результаты. Если LLM недоступен, прокси возвращает 503 на `/v1/chat/completions`.

---

### `GET /metrics`

Prometheus-метрики в формате OpenMetrics.

#### Доступные метрики

| Метрика | Тип | Метки | Описание |
|--------|------|--------|-------------|
| `rag_requests_total` | Counter | `endpoint`, `status` | Всего запросов по эндпоинтам и HTTP-статусам |
| `rag_request_duration_seconds` | Histogram | `endpoint` | Распределение задержки запросов |
| `rag_retrieval_chunks` | Histogram | — | Чанков найдено за запрос |
| `rag_retrieval_duration_seconds` | Histogram | — | Задержка гибридного поиска + реранка |
| `rag_rerank_duration_seconds` | Histogram | — | Задержка cross-encoder реранкера |
| `rag_llm_duration_seconds` | Histogram | `provider` | Задержка генерации LLM по типу провайдера |
| `rag_llm_tokens_total` | Counter | `type` (`prompt` \| `completion` \| `total`) | Всего потреблено токенов |
| `rag_cache_hit_ratio` | Gauge | `cache_type` (`embedding` \| `rerank` \| `response`) | Коэффициент попадания в кэш |
| `rag_errors_total` | Counter | `type` (`llm` \| `qdrant` \| `neo4j` \| `validation` \| `timeout` \| `internal`) | Количество ошибок по типам |
| `rag_active_requests` | Gauge | — | Текущие выполняемые запросы |
| `rag_confidence_score` | Histogram | — | Распределение оценок уверенности |
| `rag_feedback_total` | Counter | `rating` (`positive` \| `negative`) | Всего отправлено отзывов |
| `rag_rate_limit_hits_total` | Counter | `endpoint` | Превышений лимита запросов |

---

### `POST /v1/auth/login`

Генерация JWT-токена по учётным данным.

#### Схема запроса

```json
{
  "username": "string (обязательно)",
  "password": "string (обязательно)",
  "expires_in_hours": "integer (опционально, по умолчанию: 24)"
}
```

#### Схема ответа (200 OK)

```json
{
  "access_token": "string (JWT)",
  "token_type": "bearer",
  "expires_in": "integer (секунд)",
  "user_id": "string",
  "username": "string",
  "roles": ["string"],
  "groups": ["string"]
}
```

### `POST /v1/auth/refresh`

Обновление существующего JWT-токена.

**Заголовки:** `Authorization: Bearer <текущий-токен>`

```json
{
  "token": "string (обязательно)"
}
```

### `GET /v1/auth/me`

Контекст текущего аутентифицированного пользователя.

```json
{
  "user_id": "string",
  "username": "string",
  "roles": ["string"],
  "groups": ["string"],
  "access_level": "string (internal | external | restricted)",
  "is_admin": "boolean",
  "is_authenticated": "boolean"
}
```

---

### `POST /v1/feedback`

Отправка экспертной обратной связи на ответ RAG.

#### Схема запроса

```json
{
  "feedback_id": "string (обязательно)",
  "rating": "string (positive | negative)",
  "correction": "string (опционально)",
  "comment": "string (опционально)"
}
```

| Поле | Тип | Обязательное | Описание |
|-------|------|----------|-------------|
| `feedback_id` | string | Да | `rag_feedback_id` из исходного ответа чат-завершения |
| `rating` | string | Да | `"positive"` или `"negative"` |
| `correction` | string | Нет | Исправленный текст ответа. При `rating: "positive"` запускает индексацию обогащения |
| `comment` | string | Нет | Свободный комментарий эксперта |

#### Ответ (200 OK)

```json
{
  "status": "ok",
  "message": "Feedback recorded"
}
```

---

## Коды ошибок

| HTTP Status | Тип ошибки | Значение | Действие |
|-------------|-----------|----------|----------|
| **200** | — | Успех | — |
| **400** | `bad_request` | Неверный запрос | Проверить тело запроса по схеме |
| **400** | `validation_error` | Ошибка валидации ввода | Проверить входные поля |
| **401** | `unauthorized` | Отсутствуют или неверные учётные данные | Повторный вход через `/v1/auth/login` |
| **403** | `forbidden` | Недостаточно прав | Запросить доступ у администратора |
| **404** | `not_found` | Ресурс не найден | Проверить `rag_feedback_id` из ответа |
| **413** | `payload_too_large` | Тело запроса слишком велико | Уменьшить количество сообщений или длину контента |
| **429** | `rate_limited` | Слишком много запросов | Подождать `Retry-After` секунд |
| **500** | `internal_error` | Необработанное исключение | Проверить логи прокси; сообщить об ошибке |
| **502** | `upstream_error` | LLM-бэкенд вернул невалидный ответ | Проверить здоровье LLM-бэкенда |
| **503** | `service_unavailable` | Деградация компонентов | Проверить сервисы Docker; верифицировать сетевое подключение |
| **504** | `timeout` | Таймаут запроса к LLM | Увеличить `REQUEST_TIMEOUT` или уменьшить `max_tokens` |

---

## Ограничение частоты запросов

При включении (`RATE_LIMIT_ENABLED=true`) используется алгоритм token bucket на IP:

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `RATE_LIMIT_PER_MINUTE` | `60` | Устойчивых запросов в минуту на IP |
| `RATE_LIMIT_BURST` | `10` | Ёмкость всплеска сверх устойчивой скорости |

HTTP-заголовки в каждом ответе (при активном ограничении):

| Заголовок | Описание |
|-----------|----------|
| `X-RateLimit-Limit` | Максимум запросов в минуту |
| `X-RateLimit-Remaining` | Оставшиеся токены в текущем окне |
| `X-RateLimit-Reset` | Unix timestamp сброса окна |
| `Retry-After` | Секунд до следующего разрешённого запроса (только для 429) |

---

## Поддержка нескольких провайдеров

### Поддерживаемые провайдеры

| Провайдер | `LLM_PROVIDER_TYPE` | Описание |
|-----------|---------------------|----------|
| **OpenAI-совместимый** | `openai` | vLLM, llama.cpp, Ollama, LiteLLM и любые OpenAI-совместимые эндпоинты |
| **Anthropic** | `anthropic` | Claude API через Anthropic Messages API |
| **Ollama** | `ollama` | Нативный API Ollama |
| **Generic** | `generic` | Пользовательский REST API с настраиваемыми преобразованиями |

### Матрица трансляции провайдеров

| Формат | OpenAI | Anthropic | Ollama |
|--------|--------|-----------|--------|
| Системный промпт | `messages[].role: "system"` | Верхнеуровневое поле `system` | `messages[].role: "system"` |
| Определение инструмента | `tools[].function` | `tools[].input_schema` | `tools[].function` |
| ID вызова | `tool_calls[].id` | `content[].id` | `tool_calls[].id` |
| Аргументы вызова | JSON-строка | JSON-объект | JSON-строка |
| Результат инструмента | `role: "tool"`, `tool_call_id` | `role: "user"`, `content: [{type: "tool_result"}]` | `role: "tool"`, `tool_call_id` |
| Потоковые события | `chat.completion.chunk` | `content_block_delta` | `chat.completion.chunk` |
| Путь эндпоинта | `/v1/chat/completions` | `/v1/messages` | `/api/chat` |

---

## Справочник переменных окружения

### Обязательные

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `QDRANT_HOST` | `localhost` | Хост сервера Qdrant |
| `QDRANT_PORT` | `6333` | gRPC-порт Qdrant |
| `LLM_ENDPOINT` | `http://localhost:8000/v1` | URL эндпоинта LLM-провайдера |
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
| `METRICS_ENABLED` | `true` | Открыть эндпоинт `/metrics` Prometheus |
| `RATE_LIMIT_ENABLED` | `false` | Включить ограничение по IP |
| `LOG_FORMAT` | `text` | Формат логов: `text` или структурированный `json` |
| `AUTH_ENABLED` | `false` | Включить JWT-аутентификацию |
| `LLM_API_KEY` | (пусто) | API-ключ для LLM-провайдера |
| `ENRICHMENT_ENABLED` | `false` | Индексировать исправленные Q&A пары из обратной связи |

### Настройка

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `MAX_CHUNKS_RETRIEVAL` | `50` | Чанков для поиска в Qdrant |
| `MAX_CHUNKS_AFTER_RERANK` | `20` | Чанков после реранжирования |
| `MAX_RETRIEVAL_LOOPS` | `3` | Максимум итераций переписывания в LangGraph |
| `SUFFICIENCY_THRESHOLD` | `0.6` | Порог оценки достаточности контекста |
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
| `SLM_ENDPOINT` | (пусто) | Эндпоинт SLM для маршрутизации. Оставьте пустым для отключения (fallback к regex-эвристикам). |
| `SLM_MODEL_NAME` | (пусто) | Имя SLM-модели |
| `SLM_API_KEY` | (пусто) | API-ключ для SLM |
| `SLM_MAX_TOKENS` | `256` | Максимум токенов для ответов SLM |

---

## Сводка эндпоинтов

| Метод | Эндпоинт | Auth | Ограничение | Описание |
|--------|----------|------|-------------|----------|
| `POST` | `/v1/chat/completions` | Опционально | Да | Чат-завершение с RAG (потоковое и без) |
| `GET` | `/v1/models` | Нет | Нет | Список моделей |
| `GET` | `/v1/health` | Нет | Нет | Проверка здоровья |
| `GET` | `/metrics` | Нет | Нет | Prometheus-метрики |
| `POST` | `/v1/auth/login` | Нет | Да | Генерация JWT-токена |
| `POST` | `/v1/auth/refresh` | Да | Нет | Обновление токена |
| `GET` | `/v1/auth/me` | Да | Нет | Контекст пользователя |
| `POST` | `/v1/feedback` | Нет | Нет | Отправка обратной связи |

---

## Примеры использования SDK

### Python (пакет openai)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed"  # заглушка, если аутентификация отключена
)

# Без потоковой передачи с RAG-расширениями
response = client.chat.completions.create(
    model="rag-proxy",
    messages=[
        {"role": "system", "content": "Ты — ассистент технической документации."},
        {"role": "user", "content": "Какова структура проекта и как работает ETL-пайплайн?"}
    ],
    temperature=0.2,
    max_tokens=4096,
    extra_body={
        "rag_version": "2026-01-15",
        "rag_force_refresh": False
    }
)

print(f"Ответ: {response.choices[0].message.content}")
print(f"Уверенность: {response.rag_confidence}")
print(f"ID обратной связи: {response.rag_feedback_id}")

# Потоковая передача
stream = client.chat.completions.create(
    model="your-model-name",
    messages=[{"role": "user", "content": "Опиши процесс развёртывания."}],
    stream=True
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")

# Отправка обратной связи
import requests
requests.post("http://localhost:8080/v1/feedback", json={
    "feedback_id": response.rag_feedback_id,
    "rating": "positive",
    "comment": "Точный ответ с хорошими ссылками на источники."
})
```

### cURL

```bash
# Чат-завершение без потока
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-proxy",
    "messages": [
      {"role": "system", "content": "Ты — ассистент документации."},
      {"role": "user", "content": "Сколько ADR и что они охватывают?"}
    ],
    "temperature": 0.2,
    "max_tokens": 1024,
    "rag_version": "2026-03",
    "rag_force_refresh": false
  }' | jq '.'

# Проверка здоровья
curl -s http://localhost:8080/v1/health | jq '.'

# Список моделей
curl -s http://localhost:8080/v1/models | jq '.'

# Метрики
curl -s http://localhost:8080/metrics | head -20

# Вход
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "securepass"}' | jq '.'

# Отправка обратной связи
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "feedback_id": "fbk_1719057600_a1b2c3d4",
    "rating": "positive",
    "comment": "Ответ точный и хорошо цитирован."
  }' | jq '.'
```

### JavaScript / TypeScript

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "not-needed",
});

const completion = await client.chat.completions.create({
  model: "rag-proxy",
  messages: [
    { role: "system", content: "Ты — ассистент документации." },
    { role: "user", content: "Какую БД использует система для векторного поиска?" },
  ],
  temperature: 0.2,
  max_tokens: 1024,
});

console.log("Ответ:", completion.choices[0].message.content);
// @ts-expect-error — RAG-расширения
console.log("Уверенность:", completion.rag_confidence);
// @ts-expect-error — RAG-расширения
console.log("Источники:", completion.rag_sources);
```
