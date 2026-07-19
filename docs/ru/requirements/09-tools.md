# Блок I. Knowledge Base Management и Agentic Tools (FR-104 — FR-120)

---

## FR-104. Multiple knowledge bases

**Описание:**
Система поддерживает несколько изолированных knowledge bases (KB). Каждая KB —
отдельная коллекция в Qdrant с собственными метаданными в SQLite.

Каждая KB имеет настройки доступа (roles, departments). При поиске учитываются
ACL текущего пользователя.

**Критерий приёмки:**

1. Создание KB — новая коллекция в Qdrant + запись в SQLite
2. Запрос к конкретной KB — поиск только в её коллекции
3. Удаление KB — коллекция удаляется из Qdrant + запись из SQLite

**Статус:** ⚠️ Код есть (`proxy/app/core/kb_manager.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** admin_kb.py

---

## FR-105. Admin KB API ✅

**Описание:**
RESTful API для управления knowledge bases:

- `POST /v1/admin/kb` — создать KB
- `GET /v1/admin/kb` — список KB
- `GET /v1/admin/kb/{id}` — детали KB
- `DELETE /v1/admin/kb/{id}` — удалить KB
- `POST /v1/admin/kb/{id}/reindex` — переиндексация

**Критерий приёмки:**

1. CRUD-операции работают
2. Reindex запускает ETL для указанной KB
3. Только admin может управлять KB

**Статус:** ✅ Подтверждено (`proxy/app/api/admin_kb.py`)
**Приоритет:** HIGH
**Связь:** admin_kb.py

---

## FR-106. Auto-provisioning collections ✅

**Описание:**
При старте прокси автоматически создаётся коллекция по умолчанию, если она не
существует. Это позволяет работать «из коробки» без ручной инициализации.

**Критерий приёмки:**

1. Первый запуск — коллекция создаётся автоматически
2. Повторный запуск — коллекция уже существует, пропускается
3. Лог: "Qdrant collection 'X' created with indexes"

**Статус:** ✅ Подтверждено (`proxy/app/main.py:138`)
**Приоритет:** HIGH
**Связь:** main.py

---

## FR-107. Task tracking (ETL tasks)

**Описание:**
Система отслеживает статус ETL-задач: pending, running, completed, failed.
Каждая задача имеет progress (%), start_time, end_time, error_message.

**Критерий приёмки:**

1. POST `/v1/admin/kb/{id}/reindex` — создаёт задачу со статусом pending
2. GET `/v1/admin/tasks/{id}` — возвращает статус и progress
3. Задача завершена — status=completed, progress=100%

**Статус:** ⚠️ Код есть, нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** admin_kb.py

---

## FR-108. Configuration validation

**Описание:**
При старте система проверяет все обязательные настройки:

- QDRANT_HOST — обязательно
- LLM_ENDPOINT — обязательно
- LLM_MODEL_NAME — обязательно
- NEO4J_URI — обязательно если GRAPH_ENABLED=true

Отсутствующие настройки — warning в логе, degraded mode.

**Критерий приёмки:**

1. Отсутствует QDRANT_HOST — warning, degraded mode
2. Все настройки present — startup успешен
3. Лог: "Configuration validated" или "Missing required setting: X"

**Статус:** ⚠️ Код есть (`proxy/app/shared/config_validator.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** config_validator.py

---

## FR-109. Enhanced health checks

**Описание:**
Health check `/v1/health` возвращает детальный статус:

```json
{
  "status": "healthy",
  "components": {
    "qdrant": {
      "status": "healthy",
      "latency_ms": 5
    },
    "llm": {
      "status": "healthy",
      "latency_ms": 50
    },
    "neo4j": {
      "status": "healthy",
      "latency_ms": 10
    },
    "redis": {
      "status": "healthy",
      "latency_ms": 2
    },
    "kb_manager": {
      "status": "healthy"
    }
  },
  "collections": {
    "default": {
      "vectors": 1234,
      "indexed": true
    }
  }
}
```

**Критерий приёмки:**

1. Ответ содержит все компоненты
2. Latency для каждого компонента
3. Количество векторов в коллекциях

**Статус:** ⚠️ Код есть (`proxy/app/api/health.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** health.py

---

## FR-111. Tool SDK — @tool decorator

**Описание:**
Разработчики могут создавать инструменты с помощью декоратора `@tool`:

```python
@tool(description="Search Confluence pages")
def search_confluence(query: str, space: str = "DEFAULT") -> list[dict]:
    ...
```

JSON Schema генерируется автоматически из type hints.

**Критерий приёмки:**

1. `@tool` декоратор — функция регистрируется как инструмент
2. JSON Schema генерируется из type hints
3. Инструмент доступен через `/v1/tools`

**Статус:** ⚠️ Код есть (`proxy/app/tools/sdk.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009

---

## FR-112. ToolBuilder pattern

**Описание:**
Альтернативный способ создания инструментов через Builder pattern:

```python
tool = (ToolBuilder("search_jira")
        .description("Search Jira issues")
        .param("query", str, required=True)
        .param("project", str, default="ALL")
        .handler(my_handler)
        .build())
```

**Критерий приёмки:**

1. ToolBuilder создаёт валидный ToolDefinition
2. JSON Schema соответствует определённым параметрам
3. Handler вызывается при tool call

**Статус:** ⚠️ Код есть (`proxy/app/tools/sdk.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009

---

## FR-113. ToolContext injection

**Описание:**
При вызове инструмента автоматически создается ToolContext:

- user_id — ID пользователя
- user_role — роль пользователя
- request_id — ID запроса
- shared_state — общее состояние между инструментами
- streaming — флаг streaming mode

**Критерий приёмки:**

1. Handler получает ToolContext первым аргументом
2. ToolContext содержит user_id, user_role, request_id
3. shared_state доступен между последовательными tool calls

**Статус:** ⚠️ Код есть (`proxy/app/tools/sdk.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009 2.3.2

---

## FR-114. Built-in tools (Confluence, Jira, GitLab)

**Описание:**
Система поставляется с встроенными инструментами:

- `confluence_search` — поиск по Confluence
- `jira_search` — поиск по Jira
- `gitlab_search` — поиск по GitLab

Инструменты вызывают live API этих систем.

**Критерий приёмки:**

1. Инструменты зарегистрированы при старте
2. Tool call — вызывает реальный API
3. Результат возвращается в формате ToolResult

**Статус:** ⚠️ Код есть (`proxy/app/tools/builtin.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009

---

## FR-115. Tool input validation

**Описание:**
Входные данные каждого инструмента валидируются по JSON Schema перед вызовом.
Невалидные данные — ошибка с описанием, handler не вызывается.

**Критерий приёмки:**

1. Валидные данные — handler вызывается
2. Невалидные данные — 400 с описанием ошибки
3. Отсутствующие required параметры — 400

**Статус:** ⚠️ Код есть (`proxy/app/tools/security.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009

---

## FR-116. Declarative tools (YAML/JSON)

**Описание:**
Инструменты можно определять декларативно в YAML/JSON файлах:

```yaml
name: search_docs
description: Search internal documentation
type: http
endpoint: https://docs.internal/search
method: GET
params:
  - name: query
    type: string
    required: true
```

**Критерий приёмки:**

1. YAML-файл в директории — инструмент регистрируется при старте
2. HTTP-вызов выполняется с параметрами из YAML
3. Shell-инструмент выполняется с whitelist validation

**Статус:** ⚠️ Код есть (`proxy/app/tools/declarative.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009 2.3.3

---

## FR-117. OpenAPI auto-discovery

**Описание:**
Система автоматически создаёт инструменты из OpenAPI/Swagger специй:

- AUTO mode: все endpoints → tools
- LLM_DRIVEN mode: LLM выбирает релевантные endpoints

**Критерий приёмки:**

1. OpenAPI spec URL — все endpoints создаются как tools
2. LLM-driven mode — LLM фильтрует endpoints
3. Tools доступны через `/v1/tools`

**Статус:** ⚠️ Код есть (`proxy/app/tools/openapi/`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009 2.3.4

---

## FR-118. Tool visibility by role

**Описание:**
Инструменты фильтруются по роли пользователя:

- Admin — видит все инструменты
- Expert — видит все кроме admin-only
- User — видит публичные инструменты
- Read_only — видит только read-only инструменты

**Критерий приёмки:**

1. GET `/v1/tools` с role=admin — все инструменты
2. GET `/v1/tools` с role=user — только публичные
3. Tool с visibility=admin — не видна обычному пользователю

**Статус:** ⚠️ Код есть (`proxy/app/tools/registry.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009 2.3.7

---

## FR-119. Tool metrics (Prometheus)

**Описание:**
Каждый tool call логирует метрики:

- `rag_tool_calls_total` — количество вызовов
- `rag_tool_duration_seconds` — latency
- `rag_tool_active` — количество активных вызовов
- `rag_tool_retries_total` — количество retry
- `rag_tool_input_bytes` / `rag_tool_output_bytes` — размер данных

**Критерий приёмки:**

1. Все 6 метрик присутствуют на `/metrics`
2. После tool call — метрики обновляются
3. Labels: tool_name, status

**Статус:** ⚠️ Код есть (`proxy/app/tools/metrics.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009 2.3.8

---

## FR-120. Tool audit logging

**Описание:**
Каждый tool call логируется в audit log:

- tool_name, user_id, request_id, timestamp
- input params (SHA-256 hashed для безопасности)
- output (SHA-256 hashed)
- duration_ms, status

**Критерий приёмки:**

1. Audit log содержит запись для каждого tool call
2. Params захешированы (не в открытом виде)
3. Секреты замаскированы

**Статус:** ⚠️ Код есть (`proxy/app/tools/audit.py`), нужен интеграционный тест
**Приоритет:** HIGH
**Связь:** ADR-009 2.3.9
