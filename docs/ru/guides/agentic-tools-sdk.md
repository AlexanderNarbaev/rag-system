# Агентные инструменты — руководство по Python SDK

**Статус реализации:** Реализовано в Beyond v2.0. Python SDK (`@tool` декоратор, `ToolBuilder` fluent API, `ToolContext`) полностью доступен для определения пользовательских инструментов на чистом Python с автоматической генерацией JSON Schema из аннотаций типов.

---

## 1. Обзор

SDK агентных инструментов позволяет разработчикам определять RAG-инструменты на чистом Python. Инструменты автоматически регистрируются, обнаруживаются при запуске прокси и становятся доступны для оркестратора LangGraph при агентной обработке запросов.

Предоставляются два API:
- **`@tool` декоратор** — декларативный, автоматически выводит схему из аннотаций типов
- **`ToolBuilder` fluent API** — программный, явный контроль над каждым полем

---

## 2. Быстрый старт — декоратор `@tool`

### 2.1 Базовый инструмент

```python
from proxy.app.tools.sdk import tool

@tool(category="search", tags=["fast"])
async def search_confluence(query: str, max_results: int = 5) -> str:
    """Search Confluence pages by CQL query."""
    # ... implementation
    return f"Found {max_results} results for '{query}'"
```

Декоратор автоматически:
- Считывает имена параметров, типы и значения по умолчанию из сигнатуры функции
- Использует строку документации как описание инструмента
- Генерирует JSON Schema из аннотаций типов (`str` → `"string"`, `int` → `"integer"`)
- Определяет `async` функции и маршрутизирует их корректно
- Регистрирует инструмент в глобальном реестре SDK

### 2.2 Инструмент с пользовательскими метаданными

```python
from proxy.app.tools.sdk import tool
from proxy.app.tools.definition import ToolVisibility, RetryPolicy

@tool(
    name="jira_search",
    description="Search Jira issues by JQL query",
    category="live_source",
    tags=["jira", "tickets"],
    version="1.0.0",
    timeout=15.0,
    retry_policy=RetryPolicy(max_retries=3, backoff_s=2.0),
    visibility=ToolVisibility.USER,
    depends_on=["jira_auth"],
)
async def search_jira(jql: str, max_results: int = 10) -> str:
    """Search Jira."""
    ...
```

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `name` | `str` | имя функции | Уникальный идентификатор инструмента |
| `description` | `str` | строка документации | Описание инструмента для маршрутизации LLM |
| `category` | `str` | `"general"` | Категория группировки |
| `tags` | `list[str]` | `[]` | Теги для поиска |
| `version` | `str` | `"1.0.0"` | Семантическая версия |
| `timeout` | `float` | `30.0` | Тайм-аут выполнения в секундах |
| `retry_policy` | `RetryPolicy` | `None` | Конфигурация повторных попыток |
| `visibility` | `ToolVisibility` | `PUBLIC` | Уровень видимости RBAC |
| `depends_on` | `list[str]` | `[]` | Имена других инструментов, которые требуются данному |

---

## 3. ToolContext — общее состояние

Каждый обработчик инструмента получает `ToolContext`, если его первый параметр типизирован как `ToolContext`:

```python
from proxy.app.tools.sdk import tool, ToolContext

@tool(category="search")
async def stateful_search(ctx: ToolContext, query: str) -> str:
    """Search with state."""
    user_id = ctx.user_id
    previous = ctx.get_state("last_query")
    ctx.set_state("last_query", query)
    ctx.stream_partial("Searching...")
    return f"User {user_id} searched: {query}"
```

Поля `ToolContext`:

| Поле | Тип | Описание |
|------|-----|----------|
| `user_id` | `str \| None` | Идентификатор аутентифицированного пользователя |
| `user_role` | `str \| None` | Роль пользователя в RBAC |
| `request_id` | `str` | Корреляционный идентификатор |
| `tool_call_id` | `str` | Уникальный идентификатор вызова инструмента |
| `get_state(key)` | метод | Чтение межинструментального состояния |
| `set_state(key, value)` | метод | Запись межинструментального состояния |
| `stream_partial(data)` | метод | Отправка промежуточного результата (стриминг) |

---

## 4. Маппинг типов

Аннотации типов Python автоматически преобразуются в типы JSON Schema:

| Тип Python | JSON Schema |
|------------|-------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list[X]` | `{"type": "array", "items": {"type": "X"}}` |
| `dict` | `"object"` |
| `Optional[X]` | X (необязательный) |
| `Annotated[X, "description"]` | X (описание извлекается) |

### Добавление описаний к параметрам

```python
from typing import Annotated

@tool(category="search")
async def search(
    query: Annotated[str, "The search query text"],
    limit: Annotated[int, "Maximum number of results"] = 10,
) -> str:
    ...
```

---

## 5. ToolBuilder — fluent API

Для программного создания инструментов, когда декораторов недостаточно:

```python
from proxy.app.tools.sdk import ToolBuilder
from proxy.app.tools.definition import ToolVisibility

tool = (
    ToolBuilder("gitlab_search")
    .with_description("Search GitLab merge requests")
    .with_param("query", str, "Search query", required=True)
    .with_param("project_id", int, "GitLab project ID", required=True)
    .with_param("state", str, "MR state", required=False, default="opened",
                enum=["opened", "closed", "merged"])
    .with_param("labels", list, "Filter labels", required=False,
                items_type=str)
    .with_handler(handle_gitlab_search)
    .with_category("live_source")
    .with_tags(["gitlab", "merge-requests"])
    .with_timeout(20.0)
    .with_visibility(ToolVisibility.USER)
    .build()
)
```

Методы `ToolBuilder` поддерживают цепочку вызовов и возвращают `self`:

| Метод | Описание |
|-------|----------|
| `with_description(text)` | Установить описание инструмента |
| `with_param(name, type, desc, required, default, enum, items_type)` | Добавить параметр |
| `with_handler(fn)` | Установить синхронный обработчик |
| `with_async_handler(fn)` | Установить асинхронный обработчик |
| `with_category(cat)` | Установить категорию |
| `with_tags(tags)` | Установить теги |
| `with_timeout(s)` | Установить тайм-аут |
| `with_retry_policy(rp)` | Установить политику повторных попыток |
| `with_visibility(v)` | Установить видимость |
| `build()` | Создать `ToolDefinition` |

---

## 6. Регистрация и обнаружение

Инструменты, определённые через `@tool`, автоматически регистрируются в реестре SDK. При запуске прокси `EnhancedToolRegistry` сканирует и загружает все определения инструментов.

```python
# proxy/app/tools/registry.py
from proxy.app.tools.sdk import _sdk_registered_tools

# All @tool-decorated functions are available here
for name, definition in _sdk_registered_tools.items():
    print(f"Tool: {name} — {definition.description}")
```

Инструменты, созданные через `ToolBuilder`, должны быть зарегистрированы вручную:

```python
from proxy.app.tools.registry import EnhancedToolRegistry

registry = EnhancedToolRegistry()
registry.register(tool)
```

---

## 7. Безопасность и RBAC

Видимость инструмента определяет, какие роли могут получить к нему доступ:

| `ToolVisibility` | Доступно для |
|------------------|--------------|
| `PUBLIC` | Все аутентифицированные пользователи |
| `USER` | `user`, `expert`, `admin` |
| `INTERNAL` | `expert`, `admin` |
| `ADMIN` | Только `admin` |

`ToolVisibilityFilter` и `ToolInputSanitizer` в `proxy/app/tools/security.py` обеспечивают соблюдение этих правил во время выполнения.

---

## 8. Полный пример

```python
from proxy.app.tools.sdk import tool, ToolContext
from proxy.app.tools.definition import ToolVisibility, RetryPolicy

@tool(
    category="live_source",
    tags=["confluence", "live"],
    visibility=ToolVisibility.USER,
    retry_policy=RetryPolicy(max_retries=2, backoff_s=1.0),
)
async def confluence_page(ctx: ToolContext, page_id: str) -> str:
    """Fetch a Confluence page by its page ID."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://confluence.internal/rest/api/content/{page_id}",
            params={"expand": "body.storage"},
        )
        resp.raise_for_status()
        return resp.json()["body"]["storage"]["value"]
```

---

## 9. Связанные документы

- [Справочник по декларативным инструментам](agentic-tools-declarative.md) — определения инструментов в YAML/JSON
- [Руководство по обнаружению через OpenAPI](agentic-tools-openapi.md) — автоматическое обнаружение инструментов из спецификаций OpenAPI
- [ADR-009: Архитектура расширения агентных инструментов](../adr/ADR-009-agentic-tools-expansion.md)
