# Агентные инструменты — руководство по обнаружению через OpenAPI

**Статус реализации:** Реализовано в Beyond v2.0. Модуль `OpenAPIDiscovery` автоматически преобразует спецификации
OpenAPI/Swagger в объекты `ToolDefinition` в автоматическом и управляемом LLM режимах.

---

## 1. Обзор

Автообнаружение OpenAPI устраняет необходимость ручного определения инструментов для REST API. Укажите движку
обнаружения URL или файл спецификации OpenAPI — и он сгенерирует готовые к использованию RAG-инструменты для каждого
эндпоинта.

Поддерживаются два режима обнаружения:

- **Автоматический режим** — эвристически отображает GET-эндпоинты → инструменты поиска, POST/PUT/DELETE → инструменты
  действий
- **Управляемый LLM режим** — отправляет спецификацию LLM для интеллектуального выбора инструментов (в будущем)

---

## 2. Быстрый старт

```python
from proxy.app.tools.openapi_discovery import OpenAPIDiscovery

discovery = OpenAPIDiscovery()

# Auto-discover from a spec URL
tools = await discovery.discover("https://api.internal/openapi.json")

# Auto-discover from a local file
tools = await discovery.discover("/etc/rag/specs/confluence-v2.json")

# Filter by tag
tools = await discovery.discover(
    "https://api.internal/openapi.json",
    tags=["search", "query"],
)

# Register discovered tools
from proxy.app.tools.registry import EnhancedToolRegistry
registry = EnhancedToolRegistry()
for tool in tools:
    registry.register(tool)
```

---

## 3. Правила отображения эндпоинтов

### 3.1 Автоматический режим

| HTTP-метод         | Тип инструмента     | Категория    | Описание                                                       |
|--------------------|---------------------|--------------|----------------------------------------------------------------|
| `GET`              | Инструмент поиска   | `api_search` | Извлекает данные; параметры становятся параметрами инструмента |
| `POST`             | Инструмент действий | `api_action` | Создаёт ресурсы                                                |
| `PUT`              | Инструмент действий | `api_action` | Обновляет ресурсы                                              |
| `PATCH`            | Инструмент действий | `api_action` | Частичное обновление                                           |
| `DELETE`           | Инструмент действий | `api_action` | Удаляет ресурсы                                                |
| `HEAD` / `OPTIONS` | Пропускаются        | —            | Не преобразуются в инструменты                                 |

### 3.2 Соглашение об именовании

Инструменты именуются путём преобразования пути OpenAPI в slug:

| Путь OpenAPI                             | Имя инструмента                     |
|------------------------------------------|-------------------------------------|
| `/pets/{petId}`                          | `pets_petId`                        |
| `/store/orders/{orderId}/items/{itemId}` | `store_orders_orderId_items_itemId` |
| `/search`                                | `search`                            |

### 3.3 Маппинг параметров

Параметры OpenAPI отображаются в объекты `ToolParam`:

```yaml
# OpenAPI spec
parameters:
  - name: query
    in: query
    required: true
    schema:
      type: string
      description: Search query text
  - name: limit
    in: query
    schema:
      type: integer
      default: 10
```

```python
# Generated ToolParams
ToolParam(name="query", type="string", required=True, description="Search query text")
ToolParam(name="limit", type="integer", required=False, default=10)
```

Расположение параметра (`in: query`, `in: path`, `in: header`) отражается в описании, но не изменяет интерфейс
инструмента (все становятся параметрами инструмента).

---

## 4. OpenAPIProvider — непрерывное обнаружение

Для использования в продакшене интеграция осуществляется через класс `OpenAPIProvider`, реализующий `ToolProvider`:

```python
from proxy.app.tools.openapi_discovery import OpenAPIProvider

provider = OpenAPIProvider(
    name="confluence_api",
    spec_url="https://confluence.internal/rest/api/swagger.json",
    refresh_interval_s=3600,   # Re-discover every hour
    tags=["public"],
)

# Attach to the registry
registry.add_provider(provider)
```

Провайдер автоматически:

- Обнаруживает инструменты при запуске
- Периодически обновляет список (настраиваемый интервал)
- Корректно обрабатывает изменения URL спецификации
- Сообщает статус обнаружения

### Конфигурация провайдера

```python
OpenAPIProvider(
    name="unique_provider_id",
    spec_url="https://...",
    spec_file=None,            # Alternative: local file path
    refresh_interval_s=0,      # 0 = no periodic refresh
    timeout_s=30,              # HTTP timeout for spec fetching
    auth_header=None,          # "Bearer xxx" or "Basic xxx"
    tags=None,                 # Filter endpoints by OpenAPI tag
    mode=DiscoveryMode.AUTO,   # AUTO or LLM_DRIVEN
    include_methods=["get", "post"],  # Restrict HTTP methods
    visibility=ToolVisibility.USER,   # Default visibility for all tools
)
```

---

## 5. Преобразование отдельных эндпоинтов

Используйте `OpenAPIToolGenerator` для преобразования отдельных эндпоинтов:

```python
from proxy.app.tools.openapi_discovery import OpenAPIToolGenerator

spec = {
    "openapi": "3.0.0",
    "info": {"title": "My API", "version": "1.0.0"},
    "paths": {
        "/users/search": {
            "get": {
                "summary": "Search users",
                "parameters": [
                    {"name": "q", "in": "query", "schema": {"type": "string"}}
                ],
            }
        }
    }
}

generator = OpenAPIToolGenerator(spec)
tool = generator.generate_tool("/users/search", "get")
assert tool.name == "users_search"
assert tool.description == "Search users"
```

---

## 6. Безопасность и RBAC

Обнаруженные инструменты соблюдают настройку видимости:

```python
# All discovered tools are ADMIN-only
provider = OpenAPIProvider(
    name="admin_apis",
    spec_url="https://admin.internal/swagger.json",
    visibility=ToolVisibility.ADMIN,
)
```

`ToolVisibilityFilter` (в `proxy/app/tools/security.py`) обеспечивает соблюдение этих правил во время выполнения —
пользователи без прав администратора не могут видеть или вызывать инструменты с видимостью admin.

---

## 7. Управляемый LLM режим (в будущем)

При указании `DiscoveryMode.LLM_DRIVEN` спецификация отправляется LLM для интеллектуального выбора инструментов вместо
преобразования каждого эндпоинта. В текущей реализации это заглушка — интеграция с LLM будет предоставлена в будущем
релизе.

```python
provider = OpenAPIProvider(
    name="smart_discovery",
    spec_url="https://api.internal/openapi.json",
    mode=DiscoveryMode.LLM_DRIVEN,
    # Future: llm_params={"max_tools": 10, "min_relevance": 0.7}
)
```

---

## 8. Поддерживаемые форматы спецификаций

- **OpenAPI 3.0 / 3.1** (JSON и YAML)
- **Swagger 2.0** (JSON и YAML)
- Локальные файловые пути и удалённые URL
- Разрешение `$ref` (только локальные ссылки)

---

## 9. Обработка ошибок

| Сценарий                         | Поведение                                             |
|----------------------------------|-------------------------------------------------------|
| URL спецификации недоступен      | Логируется предупреждение, возвращается пустой список |
| Невалидный формат спецификации   | Логируется ошибка, возвращается пустой список         |
| Неразрешимый `$ref`              | Эндпоинт пропускается, логируется предупреждение      |
| Дублирующиеся имена инструментов | Побеждает последний (логируется предупреждение)       |

Все ошибки логируются, но не являются фатальными — прокси продолжает запуск с нулём обнаруженных инструментов.

---

## 10. Связанные документы

- [Руководство по Python SDK](agentic-tools-sdk.md) — декоратор `@tool` и `ToolBuilder`
- [Справочник по декларативным инструментам](agentic-tools-declarative.md) — определения инструментов в YAML/JSON
- [ADR-009: Архитектура расширения агентных инструментов](../adr/ADR-009-agentic-tools-expansion.md)
