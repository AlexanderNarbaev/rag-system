# ADR-009: Архитектура расширения системы инструментов

**Статус:** Принято  
**Дата:** 2026-07-05  
**Автор:** Architecture Design  
**Область:** Редизайн системы инструментов — SDK, декларативные, OpenAPI, оркестрация  

---

## Содержание

1. [Обзор архитектуры](#1-обзор-архитектуры)
2. [Модули и компоненты](#2-модули-и-компоненты)
3. [Интерфейсы и контракты](#3-интерфейсы-и-контракты)
4. [Потоки данных](#4-потоки-данных)
5. [Записи решений по архитектуре](#5-записи-решений-по-архитектуре)
6. [Карта зависимостей](#6-карта-зависимостей)
7. [Последовательность реализации](#7-последовательность-реализации)
8. [Риски и смягчения](#8-риски-и-смягчения)
9. [Структура файлов](#9-структура-файлов)
10. [Путь миграции](#10-путь-миграции)

---

## 1. Обзор архитектуры

### 1.1 Архитектура верхнего уровня

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Main App                          │
│  GET /v1/tools            POST /v1/chat/completions          │
│  GET /v1/tools/{name}     (existing, enhanced)               │
└───────────┬─────────────────────────┬───────────────────────┘
            │                         │
            ▼                         ▼
┌───────────────────────┐  ┌──────────────────────────────────┐
│  Tool Discovery API   │  │   LangGraph Orchestrator          │
│  - List/filter tools  │  │   (orchestrator.py)               │
│  - Get tool details   │  │   ┌─────────────────────────┐     │
└───────────┬───────────┘  │   │  call_tools (enhanced)  │     │
            │              │   │  ┌───────────────────┐  │     │
            ▼              │   │  │ParallelExecutor   │  │     │
┌───────────────────────┐  │   │  │ (asyncio.gather)  │  │     │
│  Enhanced Registry    │  │   │  ├───────────────────┤  │     │
│  (tools/registry.py)  │  │   │  │StreamingExecutor  │  │     │
│  ┌─────────────────┐  │  │   │  │ (SSE/async iter)  │  │     │
│  │ ToolProvider    │◄─┼──┼───┤  ├───────────────────┤  │     │
│  │ Interface       │  │  │   │  │Composer (chain,   │  │     │
│  ├─────────────────┤  │  │   │  │ fanout, cond.)    │  │     │
│  │ SDKProvider     │  │  │   │  └───────────────────┘  │     │
│  │ DeclarativeProv │  │  │   └─────────────────────────┘     │
│  │ OpenAPIProvider │  │  └──────────────────────────────────┘
│  └─────────────────┘  │
└───────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Tool Providers                             │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────────┐  │
│  │  SDK Tools    │ │  Declarative  │ │  OpenAPI Tools    │  │
│  │  @tool(...)   │ │  YAML/JSON    │ │  GET→search       │  │
│  │  ToolBuilder  │ │  HTTP + Shell │ │  POST→action      │  │
│  └───────────────┘ └───────────────┘ └───────────────────┘  │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│               Cross-Cutting Concerns                         │
│  ┌───────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Security  │ │  Metrics  │ │  Audit   │ │  Error Tax   │ │
│  │ RBAC vis  │ │ Prometheus│ │  Logger  │ │  RetryPolicy │ │
│  └───────────┘ └───────────┘ └──────────┘ └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Поток регистрации инструментов

```
┌──────────┐    ┌────────────────┐    ┌──────────────────┐
│ Source   │───►│ ToolProvider   │───►│ EnhancedRegistry │───► LLM Tools
│          │    │ .discover()    │    │ .register()      │    │
│ Python   │    │                │    │                  │    │ /v1/tools
│ @tool    │    │ returns:       │    │ stores:          │    │ endpoint
│          │    │ list[ToolDef]  │    │ dict[name,Tool]  │    │
│ YAML/JSON│    │                │    │                  │    │
│          │    │                │    │                  │    │
│ OpenAPI  │    │                │    │                  │    │
└──────────┘    └────────────────┘    └──────────────────┘
```

---

## 2. Модули и компоненты

### 2.1 Новый пакет: `proxy/app/tools/`

| Модуль | Ответственность | Ключевые классы |
|--------|----------------|-----------------|
| `definition.py` | Единые модели данных, генерация JSON Schema | `ToolDefinition`, `ToolResult`, `ToolParam`, `ToolError`, `RetryPolicy`, `ToolVisibility` |
| `registry.py` | Расширенный реестр с паттерном провайдера, обратная совместимость | `EnhancedToolRegistry`, `ToolProvider` (ABC), `SDKProvider`, `DeclarativeProvider`, `OpenAPIProvider` |
| `sdk.py` | Python декораторный API и builder API | `tool` (декоратор), `ToolBuilder`, `ToolContext`, `json_schema_from_func` |
| `declarative.py` | YAML/JSON загрузчик декларативных инструментов с валидацией | `DeclarativeToolLoader`, `DeclarativeToolSchema`, `HttpToolConfig`, `ShellToolConfig` |
| `openapi_discovery.py` | Парсер спецификаций OpenAPI → генератор инструментов | `OpenAPIDiscovery`, `OpenAPIToolGenerator`, `DiscoveryMode` (AUTO, LLM_DRIVEN) |
| `orchestrator.py` | Параллельное/потоковое исполнение, паттерны композиции | `ParallelExecutor`, `StreamingExecutor`, `ToolComposer`, `CompositionPattern` |
| `errors.py` | Таксономия и классификация ошибок | `ToolNotFoundError`, `ToolExecutionError`, `ToolTimeoutError`, `ToolPermissionError`, `ToolValidationError` |
| `security.py` | Фильтр видимости RBAC, санитайзер ввода | `ToolVisibilityFilter`, `ToolInputSanitizer` |
| `metrics.py` | Prometheus-инструментирование | `ToolMetrics` (счётчики, гистограммы, gauge) |
| `audit.py` | Структурированное аудиторское логирование | `ToolAuditLogger` |
| `__init__.py` | Переэкспорт публичного API, shim обратной совместимости | Переэкспорт всех публичных символов, алиас `ToolRegistry` |

### 2.2 Изменённые файлы

| Файл | Изменения |
|------|-----------|
| `proxy/app/tools.py` | **Устаревает.** Становится тонким shim-ом переэкспорта, указывающим на `proxy/app/tools/__init__.py`. Все существующие импорты продолжают работать. |
| `proxy/app/orchestrator.py` | Узел `call_tools` обновлён: параллельное исполнение через `ParallelExecutor`, поддержка асинхронных инструментов, потоковая передача результатов. |
| `proxy/app/provider_adapter.py` | Консолидация `ToolDefinition`/`ToolResult`/`ToolCall` — импорт из `proxy.app.tools.definition` вместо локальных dataclass-ов. |
| `proxy/app/main.py` | Добавлены эндпоинты: `GET /v1/tools`, `GET /v1/tools/{name}`. Обнаружение инструментов при запуске. |
| `proxy/app/config.py` | Добавлена конфигурация: `TOOLS_PARALLEL_EXECUTION`, `TOOLS_MAX_CONCURRENCY`, `TOOLS_DECLARATIVE_DIR`, `TOOLS_OPENAPI_SPECS` |

### 2.3 Описания компонентов

#### 2.3.1 `definition.py` — Единая модель данных

Консолидирует и расширяет три отдельных класса `ToolDefinition`:
- `proxy/app/tools.py::ToolDefinition` (текущий реестр)
- `proxy/app/provider_adapter.py::ToolDefinition` (формат LLM)
- `proxy/app/provider_adapter.py::ToolResult` / `ToolCall` (исполнение)

Новый единый `ToolDefinition`:

```python
@dataclass
class ToolDefinition:
    """Unified tool definition — canonical representation."""
    name: str
    description: str
    parameters: list[ToolParam]                          # Replaces raw dict
    handler: Callable[..., Any] | None = None            # Sync handler
    async_handler: Callable[..., Any] | None = None      # Async handler
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    visibility: ToolVisibility = ToolVisibility.PUBLIC   # PUBLIC, ADMIN, EXPERT, USER
    timeout_seconds: float = 30.0
    retry_policy: RetryPolicy | None = None
    depends_on: list[str] = field(default_factory=list)  # Tool dependency graph
    output_schema: dict | None = None                    # JSON Schema for return value
    provider: str = "sdk"                                # "sdk", "declarative", "openapi"
    metadata: dict = field(default_factory=dict)

    def to_openai_format(self) -> dict: ...
    def to_anthropic_format(self) -> dict: ...
    def to_json_schema(self) -> dict: ...

@dataclass
class ToolParam:
    """Single tool parameter with JSON Schema generation."""
    name: str
    type: type | str
    description: str = ""
    required: bool = True
    default: Any = _UNSET
    enum: list[str] | None = None
    items_type: type | None = None       # For array params
    
    def to_json_schema_property(self) -> dict: ...
```

#### 2.3.2 `sdk.py` — Python SDK для инструментов

**Декораторный API:**

```python
@tool(
    name=None,                    # Auto-derived from func name
    description=None,             # Auto-derived from docstring
    category="general",
    tags=None,
    version="1.0.0",
    timeout=30.0,
    retry_policy=None,
    visibility=ToolVisibility.PUBLIC,
    depends_on=None,
)
async def my_tool(param1: str, param2: int = 5, ctx: ToolContext = None) -> str:
    """Optional docstring becomes description if not overridden."""
    ...
```

Декоратор:
1. Считывает аннотации типов через `typing.get_type_hints()`
2. Считывает docstring для описания
3. Генерирует JSON Schema из типов параметров
4. Регистрирует инструмент в глобальном реестре
5. Поддерживает как `async def`, так и `def`

**ToolContext (внедряется автоматически):**

```python
@dataclass
class ToolContext:
    """Context injected into tool handlers automatically."""
    user_id: str | None
    user_role: str | None
    request_id: str
    tool_call_id: str
    metrics: "ToolMetrics"
    
    async def get_state(self, key: str) -> Any: ...     # Cross-tool shared state
    async def set_state(self, key: str, value: Any): ... 
    async def stream_partial(self, data: str) -> None: ...  # For streaming tools
```

**Builder API:**

```python
tool = (ToolBuilder("search_confluence")
    .with_description("Search Confluence pages by CQL query")
    .with_param("query", str, "CQL query text", required=True)
    .with_param("max_results", int, "Max results", default=5)
    .with_param("space_key", str, "Optional space filter", default=None)
    .with_handler(lambda query, max_results, space_key: ...)
    .with_async_handler(async_handler)
    .with_category("live_source")
    .with_tags(["confluence", "live"])
    .with_timeout(15.0)
    .with_retry_policy(RetryPolicy(max_retries=2, backoff="exponential"))
    .with_visibility(ToolVisibility.USER)
    .build())
```

**Генерация JSON Schema:**

```python
def json_schema_from_func(func: Callable) -> dict:
    """Generate JSON Schema from Python function type hints.
    
    Mapping:
    - str → {"type": "string"}
    - int → {"type": "integer"}
    - float → {"type": "number"}
    - bool → {"type": "boolean"}
    - list[X] → {"type": "array", "items": type_of(X)}
    - Optional[X] → allOf: [type_of(X)], not in required
    - Literal["a", "b"] → {"type": "string", "enum": ["a", "b"]}
    - Annotated[T, Field(description="...")] → with description
    - BaseModel subclass → $ref to nested schema
    - dict → {"type": "object"}
    """
```

**Соответствие аннотаций типов и JSON Schema:**

| Тип Python | JSON Schema |
|------------|-------------|
| `str` | `{"type": "string"}` |
| `int` | `{"type": "integer"}` |
| `float` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |
| `list[X]` | `{"type": "array", "items": type_of(X)}` |
| `Optional[X]` | `type_of(X)` + исключение из `required` |
| `Literal["a","b"]` | `{"type": "string", "enum": ["a", "b"]}` |
| `dict[str, X]` | `{"type": "object", "additionalProperties": type_of(X)}` |
| `Annotated[T, desc]` | `type_of(T)` с `description` |
| Подкласс `BaseModel` | `{"type": "object", ...}` рекурсивно |

#### 2.3.3 `declarative.py` — Декларативные инструменты YAML/JSON

**Схема определения инструмента (JSON Schema):**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DeclarativeToolFile",
  "type": "object",
  "properties": {
    "tools": {
      "type": "array",
      "items": { "$ref": "#/$defs/DeclarativeTool" }
    }
  },
  "$defs": {
    "DeclarativeTool": {
      "type": "object",
      "required": ["name", "type", "description"],
      "properties": {
        "name": { "type": "string", "pattern": "^[a-z][a-z0-9_]*$" },
        "type": { "enum": ["http", "shell"] },
        "description": { "type": "string" },
        "category": { "type": "string", "default": "declarative" },
        "tags": { "type": "array", "items": { "type": "string" } },
        "version": { "type": "string", "default": "1.0.0" },
        "visibility": { "enum": ["public", "admin", "expert", "user"], "default": "public" },
        "timeout": { "type": "number", "default": 30 },
        "retry_policy": { "$ref": "#/$defs/RetryPolicy" },
        "parameters": { "$ref": "#/$defs/Parameters" },
        "http": { "$ref": "#/$defs/HttpConfig" },
        "shell": { "$ref": "#/$defs/ShellConfig" }
      }
    },
    "HttpConfig": {
      "type": "object",
      "required": ["method", "url_template"],
      "properties": {
        "method": { "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"] },
        "url_template": { "type": "string" },
        "headers": { "type": "object" },
        "body_template": { "type": "string" },
        "response_path": { "type": "string", "description": "JSONPath to extract from response" },
        "allowed_hosts": { "type": "array", "items": { "type": "string" }, "description": "Security: restrict to these hosts" }
      }
    },
    "ShellConfig": {
      "type": "object",
      "required": ["command"],
      "properties": {
        "command": { "type": "string" },
        "working_dir": { "type": "string", "default": "/tmp" },
        "allowed_commands": { "type": "array", "items": { "type": "string" }, "description": "Whitelist of allowed binaries" },
        "allowed_paths": { "type": "array", "items": { "type": "string" }, "description": "Whitelist of accessible paths" },
        "env_whitelist": { "type": "array", "items": { "type": "string" }, "description": "Environment variables to pass through" }
      }
    },
    "Parameters": {
      "type": "object",
      "additionalProperties": { "$ref": "#/$defs/Parameter" }
    },
    "Parameter": {
      "type": "object",
      "required": ["type"],
      "properties": {
        "type": { "type": "string" },
        "description": { "type": "string" },
        "default": {},
        "enum": { "type": "array" },
        "required": { "type": "boolean", "default": false }
      }
    },
    "RetryPolicy": {
      "type": "object",
      "properties": {
        "max_retries": { "type": "integer", "default": 3 },
        "backoff": { "enum": ["fixed", "exponential"], "default": "exponential" },
        "initial_delay_seconds": { "type": "number", "default": 1.0 },
        "retryable_errors": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

**Пример YAML:**

```yaml
tools:
  - name: "jira_search_live"
    type: "http"
    description: "Search Jira issues live via REST API"
    category: "live_source"
    tags: ["jira", "live"]
    visibility: "user"
    timeout: 15
    retry_policy:
      max_retries: 2
      backoff: "exponential"
      initial_delay_seconds: 0.5
    parameters:
      query:
        type: "string"
        description: "JQL search text"
        required: true
      max_results:
        type: "integer"
        description: "Max results"
        default: 5
    http:
      method: "GET"
      url_template: "{{JIRA_API_URL}}/search"
      headers:
        Authorization: "Basic {{JIRA_AUTH_B64}}"
        Accept: "application/json"
      allowed_hosts:
        - "{{JIRA_API_HOST}}"

  - name: "system_stats"
    type: "shell"
    description: "Get system resource usage"
    category: "admin"
    visibility: "admin"
    timeout: 5
    shell:
      command: "echo 'Disk: $(df -h / | tail -1)' && echo 'Memory: $(free -h | grep Mem)'"
      allowed_commands: ["echo", "df", "free", "grep", "tail"]
      working_dir: "/tmp"
```

**Интерполяция переменных:**
- `{{ENV_VAR}}` — переменная окружения на этапе загрузки
- `{{param_name}}` — параметр инструмента на этапе вызова
- `{{CONTEXT.user_id}}` — поля ToolContext на этапе вызова

**Валидация при загрузке:**
- Проверка схемы по JSON Schema
- Проверка уникальности имён
- Проверка белых списков разрешённых хостов/команд
- Валидация переменных шаблона (все ссылочные переменные существуют)

#### 2.3.4 `openapi_discovery.py` — Автообнаружение OpenAPI

**Режимы обнаружения:**

| Режим | Поведение | Когда использовать |
|-------|-----------|-------------------|
| `AUTO` | Парсинг спецификации → регистрация всех GET как инструментов поиска, всех POST/PUT/DELETE как инструментов действий | Известные, хорошо структурированные API |
| `LLM_DRIVEN` | Передача спецификации LLM, позволяющая решить, какие эндпоинты暴露ировать, с интерактивным подтверждением | Сложные или незнакомые API |

**Алгоритм режима AUTO:**

```python
class OpenAPIDiscovery:
    def discover(self, spec: dict, mode: DiscoveryMode) -> list[ToolDefinition]:
        """Parse OpenAPI spec and generate tool definitions."""
    
    def _endpoint_to_tool(self, path: str, method: str, operation: dict) -> ToolDefinition:
        """Convert a single OpenAPI operation to a tool definition.
        
        Rules:
        - GET → "search" category, idempotent
        - POST → "action" category, non-idempotent
        - PUT/PATCH → "action" category, idempotent
        - DELETE → "action" category, confirmable
        - Tool name: {operationId} or {method}_{path_slug}
        - Parameters from path/query/header → ToolParam
        - Request body (JSON) → ToolParam type "object"
        - Security schemes → injected via ToolContext
        """
```

**Конфигурация:**

```python
# In config.py
TOOLS_OPENAPI_SPECS: list[dict] = [
    {
        "name": "internal_hr_api",
        "url": "https://hr.internal/api/openapi.json",
        "mode": "auto",                    # or "llm_driven"
        "include_tags": ["employee"],      # Filter: only include these tags
        "exclude_tags": ["admin"],         # Filter: exclude these tags
        "visibility": "user",
        "auth_header": "{{HR_API_TOKEN}}",
    },
]
```

#### 2.3.5 `orchestrator.py` — Оркестрация инструментов

**Параллельное исполнение:**

```python
class ParallelExecutor:
    """Execute multiple tool calls in parallel with concurrency control."""
    
    def __init__(self, max_concurrency: int = 10, timeout: float = 120.0):
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout
    
    async def execute_all(
        self,
        tool_calls: list[ToolCall],
        registry: EnhancedToolRegistry,
        context: ToolContext,
    ) -> list[ToolResult]:
        """Execute all tool calls concurrently.
        
        Algorithm:
        1. Group tool calls by dependencies (respect depends_on)
        2. Execute independent groups in parallel
        3. Within each group, use asyncio.gather with semaphore
        4. Collect results, preserving order
        5. Handle individual failures gracefully (one failure ≠ all failure)
        """
    
    async def execute_single(
        self, tool_call: ToolCall, registry, context
    ) -> ToolResult:
        """Execute one tool call with retry + error handling."""
```

**Потоковое исполнение:**

```python
class StreamingExecutor:
    """Execute tools that produce streaming results (SSE)."""
    
    async def execute_streaming(
        self, tool_call: ToolCall, registry, context
    ) -> AsyncIterator[str]:
        """Yields partial results as they become available.
        
        Used for long-running tools (e.g., large data exports, progressive search).
        """
```

**Паттерны композиции:**

```python
class ToolComposer:
    """Compose tools into workflows."""
    
    @staticmethod
    def chain(tools: list[str], input_mapper: Callable) -> CompositionPattern:
        """Sequential chain: Tool A output → Tool B input.
        
        Example:
            chain(["search_documents", "get_document_metadata"],
                  lambda prev_result: {"doc_id": prev_result["id"]})
        """
    
    @staticmethod
    def fan_out(tool: str, inputs: list[dict]) -> CompositionPattern:
        """Run same tool with N different inputs in parallel.
        
        Example:
            fan_out("get_document_metadata", [{"doc_id": i} for i in ids])
        """
    
    @staticmethod
    def conditional(condition: Callable, true_tool: str, false_tool: str) -> CompositionPattern:
        """Conditional branching based on context.
        
        Example:
            conditional(lambda ctx: ctx.get_state("has_jira"),
                       "search_jira", "search_documents")
        """
```

**Интеграция исполнителя с `call_tools` в LangGraph:**

```python
# In orchestrator.py (updated)
async def call_tools_async(state: RAGState) -> dict[str, Any]:
    """Async parallel tool execution node."""
    tool_calls = state.get("tool_calls", [])
    tool_results = state.get("tool_results", [])
    tool_loop_count = state.get("tool_loop_count", 0)
    
    registry = get_tool_registry()
    context = ToolContext(
        user_id=state.get("user_id"),
        user_role=state.get("user_role"),
        request_id=state.get("request_id", ""),
        tool_call_id="",
    )
    
    executor = ParallelExecutor(max_concurrency=TOOLS_MAX_CONCURRENCY)
    
    # Parse ToolCall objects from state
    calls = [_tool_call_from_dict(tc) for tc in tool_calls]
    
    # Execute in parallel (respecting dependencies)
    results = await executor.execute_all(calls, registry, context)
    
    tool_results = [
        {
            "tool_call_id": r.tool_call_id,
            "name": r.tool_name,
            "content": r.content,
            "error": r.error,
        }
        for r in results
    ]
    
    return {
        "tool_results": tool_results,
        "tool_loop_count": tool_loop_count + 1,
        "tool_calls": [],
    }
```

#### 2.3.6 `errors.py` — Таксономия ошибок

```python
class ToolError(RAGError):
    """Base class for all tool-related errors."""
    tool_name: str
    tool_call_id: str
    retryable: bool = False

class ToolNotFoundError(ToolError):
    """Tool not found in registry."""
    retryable: bool = False

class ToolExecutionError(ToolError):
    """Tool handler raised an exception."""
    original_error: str
    retryable: bool = True

class ToolTimeoutError(ToolError):
    """Tool exceeded its timeout."""
    timeout_seconds: float
    retryable: bool = True

class ToolPermissionError(ToolError):
    """User lacks permission to call this tool."""
    required_visibility: str
    user_role: str
    retryable: bool = False

class ToolValidationError(ToolError):
    """Tool parameters failed validation."""
    validation_errors: list[str]
    retryable: bool = False

class ToolDependencyError(ToolError):
    """A tool dependency returned an error."""
    dependency_name: str
    retryable: bool = False
```

**Функция классификации ошибок:**

```python
def classify_error(tool_name: str, error: Exception) -> ToolError:
    """Map Python exceptions to tool error types."""
```

#### 2.3.7 `security.py` — RBAC-видимость

```python
class ToolVisibilityFilter:
    """Filter tools based on user role."""
    
    ROLE_HIERARCHY = {
        "admin": ["public", "admin", "expert", "user"],
        "expert": ["public", "expert", "user"],
        "user": ["public", "user"],
        "read_only": ["public"],
    }
    
    @staticmethod
    def filter(tools: list[ToolDefinition], user_role: str) -> list[ToolDefinition]:
        """Return tools visible to the given role."""
        allowed = ROLE_HIERARCHY.get(user_role, ["public"])
        return [t for t in tools if t.visibility.value in allowed]

class ToolInputSanitizer:
    """Sanitize tool input parameters."""
    
    MAX_STRING_LENGTH = 10_000
    MAX_ARRAY_LENGTH = 1_000
    
    @staticmethod
    def sanitize(tool: ToolDefinition, params: dict) -> dict:
        """Validate and sanitize parameters. Truncate oversized strings."""
```

#### 2.3.8 `metrics.py` — Prometheus-инструментирование

```python
class ToolMetrics:
    """Prometheus metrics for tool calls.
    
    Metrics emitted:
    - tool_calls_total{tool_name, category, status}          # Counter
    - tool_call_duration_seconds{tool_name, category}        # Histogram
    - tool_call_active{tool_name}                            # Gauge
    - tool_call_retries_total{tool_name}                     # Counter
    - tool_call_input_bytes{tool_name}                       # Histogram
    - tool_call_output_bytes{tool_name}                      # Histogram
    """
    
    TOOL_CALL_COUNTER = Counter("tool_calls_total", "...", ["tool_name", "category", "status"])
    TOOL_CALL_DURATION = Histogram("tool_call_duration_seconds", "...", ["tool_name", "category"])
    TOOL_CALL_ACTIVE = Gauge("tool_call_active", "...", ["tool_name"])
    TOOL_CALL_RETRIES = Counter("tool_call_retries_total", "...", ["tool_name"])
    TOOL_CALL_INPUT_BYTES = Histogram("tool_call_input_bytes", "...", ["tool_name"])
    TOOL_CALL_OUTPUT_BYTES = Histogram("tool_call_output_bytes", "...", ["tool_name"])
    
    @contextmanager
    def measure(self, tool_name: str, category: str): ...
```

#### 2.3.9 `audit.py` — Аудиторское логирование

```python
class ToolAuditLogger:
    """Structured audit logging for tool calls.
    
    Log format (JSON):
    {
        "timestamp": "2026-07-05T12:00:00Z",
        "event": "tool_call",
        "tool_name": "search_documents",
        "tool_category": "search",
        "tool_version": "1.0.0",
        "user_id": "user@corp.com",
        "user_role": "expert",
        "request_id": "req-abc123",
        "tool_call_id": "call-xyz789",
        "params_hash": "sha256:abc...",
        "result_hash": "sha256:def...",
        "duration_ms": 150,
        "status": "success" | "error" | "timeout",
        "error_type": "ToolTimeoutError" | null,
        "retry_count": 0,
        "input_bytes": 42,
        "output_bytes": 1024
    }
    
    Note: params_hash and result_hash use SHA-256 for verifiability
    without storing sensitive parameter values directly.
    """
```

---

## 3. Интерфейсы и контракты

### 3.1 Публичный API `EnhancedToolRegistry`

```python
class EnhancedToolRegistry:
    """Enhanced tool registry with multi-provider support."""
    
    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
    
    def unregister(self, name: str) -> bool:
        """Unregister a tool."""
    
    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool by name."""
    
    def list_tools(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        visibility_filter: str | None = None,  # user role
        provider: str | None = None,
    ) -> list[ToolDefinition]:
        """Filter tools by criteria."""
    
    def discover(self, provider: ToolProvider) -> list[ToolDefinition]:
        """Discover tools from a provider and register them."""
    
    def reload_provider(self, provider_name: str) -> list[ToolDefinition]:
        """Reload tools from a specific provider (hot-reload)."""
    
    def get_tools_for_llm(
        self, provider_type: str = "openai", user_role: str | None = None
    ) -> list[dict]:
        """Get tools formatted for LLM provider."""
    
    def execute(
        self, name: str, params: dict, context: ToolContext | None = None
    ) -> ToolResult:
        """Execute a tool synchronously (backward compat)."""
    
    async def execute_async(
        self, name: str, params: dict, context: ToolContext | None = None
    ) -> ToolResult:
        """Execute a tool asynchronously."""
    
    def validate_tool(self, tool: ToolDefinition) -> list[str]:
        """Validate tool definition, returns list of issues."""
    
    def get_dependency_graph(self) -> dict[str, list[str]]:
        """Return the tool dependency DAG."""
```

### 3.2 Абстрактный интерфейс `ToolProvider`

```python
class ToolProvider(ABC):
    """Abstract base for tool providers."""
    
    @abstractmethod
    async def discover(self) -> list[ToolDefinition]:
        """Discover and return tool definitions."""
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier."""
    
    async def validate(self) -> list[str]:
        """Validate all tools from this provider. Returns issues."""
        return []
    
    async def reload(self) -> list[ToolDefinition]:
        """Reload (hot-reload) tools."""
        return await self.discover()
```

**Конкретные провайдеры:**

| Провайдер | `provider_name` | Источник |
|-----------|-----------------|----------|
| `SDKProvider` | `"sdk"` | Декорированные функции и builders |
| `DeclarativeProvider` | `"declarative"` | YAML/JSON файлы в `TOOLS_DECLARATIVE_DIR` |
| `OpenAPIProvider` | `"openapi"` | Спецификации OpenAPI из `TOOLS_OPENAPI_SPECS` |

### 3.3 Новые эндпоинты FastAPI

#### `GET /v1/tools`

Параметры запроса: `category`, `tag`, `provider`

Ответ:
```json
{
  "count": 12,
  "tools": [
    {
      "name": "search_documents",
      "description": "Search indexed documents",
      "category": "search",
      "tags": ["search", "internal"],
      "version": "1.0.0",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "Search query"},
          "top_k": {"type": "integer", "description": "Max results", "default": 5}
        },
        "required": ["query"]
      },
      "provider": "sdk"
    }
  ]
}
```

#### `GET /v1/tools/{name}`

Ответ:
```json
{
  "name": "search_documents",
  "description": "Search indexed documents using hybrid search",
  "category": "search",
  "tags": ["search", "internal"],
  "version": "1.0.0",
  "visibility": "public",
  "timeout_seconds": 30,
  "parameters": { ... },
  "provider": "sdk",
  "depends_on": []
}
```

**Примечание:** Сырые функции-обработчики никогда не раскрываются через API (безопасность).

### 3.4 Авторизация `GET /v1/tools`

| Роль пользователя | Видимые инструменты (по полю visibility) |
|-------------------|------------------------------------------|
| `admin` | `public`, `admin`, `expert`, `user` |
| `expert` | `public`, `expert`, `user` |
| `user` | `public`, `user` |
| `read_only` | `public` |
| Неаутентифицированный | Только `public` |

---

## 4. Потоки данных

### 4.1 Поток регистрации инструментов

```
STARTUP
  │
  ├─► SDKProvider.discover()
  │     Сканирование декорированных @tool функций
  │     Возвращает list[ToolDefinition]
  │     → registry.register() для каждого
  │
  ├─► DeclarativeProvider.discover()
  │     Загрузка YAML/JSON из TOOLS_DECLARATIVE_DIR
  │     Валидация по DeclarativeToolSchema
  │     Возвращает list[ToolDefinition]
  │     → registry.register() для каждого
  │
  └─► OpenAPIProvider.discover()
        Получение спецификаций OpenAPI из TOOLS_OPENAPI_SPECS
        Парсинг эндпоинтов в ToolDefinitions
        Возвращает list[ToolDefinition]
        → registry.register() для каждого

HOT RELOAD (опционально)
  │
  ├─► POST /v1/admin/tools/reload?provider=declarative
  │     → DeclarativeProvider.reload()
  │     → Атомарная перерегистрация инструментов
   
  └─► File watcher на TOOLS_DECLARATIVE_DIR
        → Автоперезагрузка при изменении файла (opt-in)
```

### 4.2 Поток исполнения инструментов

```
LLM генерирует tool_calls
  │
  ▼
LangGraph: узел call_tools
  │
  ├─► 1. Парсинг вызовов инструментов из ответа LLM
  │
  ├─► 2. Построение DAG зависимостей (топологическая сортировка по depends_on)
  │
  ├─► 3. Исполнение в порядке зависимостей
  │     Для каждого уровня зависимостей:
  │       ├─► Проверка прав пользователя (ToolVisibilityFilter)
  │       ├─► Санитизация ввода (ToolInputSanitizer)
  │       ├─► asyncio.gather(*coroutines)  ← параллельно внутри уровня
  │       │     │
  │       │     ├─► ToolMetrics.measure() контекстный менеджер
  │       │     ├─► Try: handler(**params) или async_handler(**params)
  │       │     │     ├─► Успех → ToolResult(content=...)
  │       │     │     └─► Исключение → classify_error() → RetryPolicy?
  │       │     │           ├─► Повторяемый → повтор с backoff
  │       │     │           └─► Неповторяемый → ToolResult(error=...)
  │       │     └─► ToolAuditLogger.log()
  │       │
  │       └─► Сбор всех результатов
  │
  ├─► 4. Передача результатов обратно в диалог LLM
  │
  └─► 5. Продолжение или цикл (max_tool_loops=5)
```

### 4.3 Поток разрешения зависимостей

```
Инструменты с зависимостями:
  search_documents (нет зависимостей)
  get_document_metadata (depends_on: ["search_documents"])
  summarize_document (depends_on: ["get_document_metadata"])
  search_jira (нет зависимостей)
  cross_reference (depends_on: ["search_documents", "search_jira"])

План исполнения:
  Уровень 0: [search_documents, search_jira]     ← параллельно
  Уровень 1: [get_document_metadata]              ← после уровня 0
  Уровень 2: [cross_reference, summarize_document] ← после уровня 1
```

---

## 5. Записи решений по архитектуре

### ADR-009-1: Консолидация определений инструментов

**Контекст:** В кодовой базе существуют три отдельных класса `ToolDefinition`:
- `proxy/app/tools.py::ToolDefinition` (dataclass реестра)
- `proxy/app/provider_adapter.py::ToolDefinition` (формат LLM)
- `proxy/app/provider_adapter.py::ToolResult` / `ToolCall` (исполнение)

**Варианты:**
1. Оставить все три, добавить четвёртый для расширения
2. Консолидировать в один канонический `ToolDefinition` с методами конвертации форматов
3. Консолидировать, но сохранить упрощённую версию из provider_adapter для производительности

**Выбрано:** Вариант 2 — Консолидация в `proxy/app/tools/definition.py` с методами форматов.

**Обоснование:** Единый источник правды уменьшает рассогласование. Методы конвертации форматов (`to_openai_format()`, `to_anthropic_format()`) обрабатывают сериализацию, специфичную для провайдера. Разделение между канонической моделью и форматом LLM сохраняется через методы, а не отдельные классы.

**Компромиссы:** Немного больший dataclass (но поля опциональны там, где не универсально необходимы). provider_adapter должен импортировать из пакета tools (новая зависимость, допустимо).

**Риски:** Необходимо избежать циклических импортов. Смягчение: `definition.py` не имеет внутренних зависимостей.

---

### ADR-009-2: Субпакет против плоского модуля

**Контекст:** Функциональность системы инструментов охватывает 10+ аспектов (SDK, декларативные, OpenAPI, оркестрация, ошибки, безопасность, метрики, аудит, реестр, определение).

**Варианты:**
1. Оставить всё в одном `tools.py` (монолит)
2. Создать субпакет `proxy/app/tools/` с отдельными модулями
3. Создать `tools/` на верхнем уровне (отдельный пакет)

**Выбрано:** Вариант 2 — Субпакет `proxy/app/tools/`.

**Обоснование:** `tools.py` уже содержит 257 строк и продолжает расти. Расширение добавляет тысячи строк. Отдельные модули обеспечивают независимое тестирование и сопровождение. Скопировано из существующего паттерна проекта (ETL имеет `extractors/`, `chunker/` и т.д.).

**Компромиссы:** Больше файлов, но каждый сфокусирован (< 300 строк целевой). Пути импортов меняются. Смягчение: `__init__.py` переэкспортирует все публичные символы. Старый `tools.py` становится shim-ом устаревания.

---

### ADR-009-3: Стратегия асинхронного исполнения

**Контекст:** Текущий `call_tools` синхронный последовательный (`for tc in tool_calls: handle_function_call(tc, registry)`). Живые источники асинхронны, но не зарегистрированы как инструменты.

**Варианты:**
1. Оставить последовательным, добавить асинхронную поддержку при необходимости
2. `asyncio.gather` с семафором для неконтролируемого параллелизма
3. Параллельное исполнение с учётом зависимостей (топологическая сортировка + gather по уровням)

**Выбрано:** Вариант 3 — Параллельное исполнение с учётом зависимостей.

**Обоснование:** Живые источники (Confluence, Jira, GitLab) — независимые операции ввода-вывода. Последовательное выполнение добавляет ненужную задержку. При таймауте 15с на каждый, 3 последовательных вызова = 45с против 15с параллельных. Учёт зависимостей предотвращает ошибки порядка.

**Компромиссы:** Добавлена сложность в исполнителе. Для обратной совместимости синхронный путь сохранён для режима `USE_LANGGRAPH=false`.

---

### ADR-009-4: Стратегия генерации JSON Schema

**Контекст:** Текущие инструменты требуют ручного написания JSON Schema (словарь `parameters_schema`). Подвержено ошибкам и многословно.

**Варианты:**
1. Оставить ручной JSON Schema (без изменений)
2. Использовать `inspect.signature()` + `typing.get_type_hints()` для автогенерации
3. Требовать Pydantic-модели для параметров инструментов

**Выбрано:** Вариант 2 с опциональным вариантом 3.

**Обоснование:** Автогенерация из аннотаций типов покрывает 90%+ инструментов. Функция `json_schema_from_func()` обрабатывает все распространённые типы Python. Для сложных вложенных схем поддерживаются параметры Pydantic `BaseModel` как запасной вариант. Ручное переопределение по-прежнему доступно.

**Компромиссы:** Сложные аннотации типов (например, `Annotated[list[dict[str, int]], Field(...)]`) могут отображаться не идеально. Смягчение: ручное переопределение через `parameters_schema` имеет приоритет.

---

### ADR-009-5: Стратегия обратной совместимости

**Контекст:** Существующие 3 встроенных инструмента, существующий API `ToolRegistry`, существующие функции `execute_tool()` и `handle_function_call()` должны продолжать работать.

**Варианты:**
1. Заменить всё, ломающие изменения
2. Оставить старый API, добавить новый рядом
3. Shim устаревания + постепенная миграция

**Выбрано:** Вариант 3 — Shim устаревания.

**Обоснование:** Старый `tools.py` становится:
```python
# proxy/app/tools.py (deprecated shim)
"""DEPRECATED: Import from proxy.app.tools instead."""
import warnings
from proxy.app.tools import (
    ToolDefinition, ToolResult, ToolRegistry, ToolError,
    execute_tool, handle_function_call, format_tools_for_llm,
    get_tool_registry,
)
warnings.warn("proxy.app.tools is deprecated, use proxy.app.tools package", DeprecationWarning)
```

Существующие импорты продолжают работать. Тесты проходят. Без поломок.

---

### ADR-009-6: Безопасность shell-инструментов

**Контекст:** Декларативные инструменты включают поддержку shell-команд. Это потенциально опасно.

**Варианты:**
1. Без shell-инструментов (отклонить требование)
2. Разрешить shell с безопасностью на основе белых списков
3. Разрешить shell с изоляцией в контейнере/песочнице

**Выбрано:** Вариант 2 — Безопасность на основе белых списков.

**Обоснование:** Декларативные инструменты ориентированы на администраторов, которым нужны системные диагностика (диск, память, логи). Белый список (`allowed_commands`, `allowed_paths`) обеспечивает многоуровневую защиту. Shell-инструменты доступны только с `visibility: admin` по соглашению (обеспечивается при валидации).

**Ограничения безопасности:**
- `allowed_commands`: Regex-совпадение разрешённых бинарных файлов (например, `["echo", "df", "free", "systemctl"]`)
- `allowed_paths`: Ограничение доступа к файлам конкретными директориями
- `env_whitelist`: Передача только конкретных переменных окружения (никогда не секретов)
- `timeout`: Обязательный, максимум 30с для shell-инструментов
- `no_shell_metacharacters`: Блокировка `;`, `&&`, `|`, `$()`, обратных кавычек в значениях параметров
- Логирование всех shell-команд на уровне WARNING

**Компромиссы:** Белые списки можно обойти, если они слишком свободные. Смягчение: валидация отклоняет инструменты без `allowed_commands`.

---

### ADR-009-7: Кэширование обнаружения инструментов

**Контекст:** Спецификации OpenAPI могут быть удалёнными. Декларативных файлов может быть много. Регистрация происходит при запуске.

**Варианты:**
1. Загружать всё при запуске, хранить в памяти (текущий подход)
2. Ленивая загрузка при первом вызове инструмента
3. Периодическое обновление с TTL-кэшем

**Выбрано:** Вариант 1 с опциональным вариантом 3.

**Обоснование:** Инструменты критичны для обработки запросов. Ленивая загрузка добавляет задержку при первом вызове. В большинстве развёртываний < 100 инструментов, что легко помещается в память. Для динамических окружений `reload_adapter()` обеспечивает горячую перезагрузку без перезапуска.

---

## 6. Карта зависимостей

### 6.1 Зависимости модулей (слоистая, сверху вниз)

```
Слой 0: Стандартная библиотека + сторонние пакеты
  typing, inspect, asyncio, dataclasses, logging, yaml, json, aiohttp, prometheus_client

Слой 1: Фундаментальные модули (без внутренних зависимостей)
  definition.py → (нет внутренних зависимостей)
  errors.py → exceptions.py (RAGError)
  config.py → (нет внутренних зависимостей)

Слой 2: Инфраструктура
  metrics.py → prometheus_client
  audit.py → logging_config.py
  security.py → rbac.py, config.py

Слой 3: Провайдеры
  sdk.py → definition.py, registry.py, errors.py
  declarative.py → definition.py, registry.py, errors.py, security.py
  openapi_discovery.py → definition.py, registry.py, errors.py

Слой 4: Оркестрация
  orchestrator.py → definition.py, registry.py, errors.py, security.py, metrics.py, audit.py

Слой 5: Реестр (зависит от провайдеров для определения интерфейса)
  registry.py → definition.py, errors.py

Слой 6: Публичный API
  __init__.py → все модули выше
  tools.py (shim) → __init__.py

Слой 7: Интеграция приложения
  main.py → registry.py, orchestrator.py
  orchestrator.py → orchestrator.py (tools), registry.py
  provider_adapter.py → definition.py
```

### 6.2 Предотвращение циклических зависимостей

- `definition.py` имеет **нулевые** внутренние импорты — чистые структуры данных
- `registry.py` зависит только от `definition.py` и `errors.py`
- `orchestrator.py` зависит от `registry.py`, но НЕ наоборот
- Ни один модуль не экспортирует циклические ссылки

### 6.3 Внешние зависимости

| Пакет | Назначение | Обязателен? |
|-------|-----------|-------------|
| `pyyaml` | Загрузка YAML-декларативных инструментов | Опционально (только при использовании декларативных инструментов) |
| `jsonschema` | Валидация декларативных инструментов | Опционально |
| `openapi-spec-validator` | Валидация спецификаций OpenAPI | Опционально (только при использовании OpenAPI discovery) |
| `prometheus_client` | Уже присутствует, используется для метрик инструментов | Опционально (METRICS_ENABLED) |
| `aiohttp` | Уже присутствует, HTTP-декларативные инструменты | Уже присутствует |

---

## 7. Последовательность реализации

### Фаза 1: Фундамент (2-3 дня)
**Цель:** Закладка основы, нулевые ломающие изменения.

| Шаг | Файл | Описание |
|-----|------|----------|
| 1.1 | `proxy/app/tools/definition.py` | Создание унифицированных dataclass-ов `ToolDefinition`, `ToolResult`, `ToolParam`, `RetryPolicy`, `ToolVisibility` с методами `to_openai_format()`, `to_anthropic_format()` |
| 1.2 | `proxy/app/tools/errors.py` | Создание иерархии `ToolError`, функции `classify_error()` |
| 1.3 | `proxy/app/tools/__init__.py` | Переэкспорт всех публичных символов. Пустой реестр (пока без встроенных инструментов). |
| 1.4 | `proxy/app/tools.py` (изменение) | Конвертация в shim устаревания, переэкспорт из `proxy.app.tools` |
| 1.5 | Тесты | Юнит-тесты для definition.py, errors.py |

**Критерий приёмки:** Существующие тесты проходят. Функциональных изменений нет. Импорты из `proxy.app.tools` работают.

### Фаза 2: Расширенный реестр (2-3 дня)
**Цель:** Замена синглтон-реестра на реестр на основе провайдеров.

| Шаг | Файл | Описание |
|-----|------|----------|
| 2.1 | `proxy/app/tools/registry.py` | Реализация `EnhancedToolRegistry` с `ToolProvider` ABC, `register()`, `unregister()`, `list_tools()` с фильтрами, `execute()`, `execute_async()`, `validate_tool()` |
| 2.2 | — | Миграция 3 встроенных инструментов (search_documents, search_by_version, get_document_metadata) в `SDKProvider` |
| 2.3 | `proxy/app/tools/__init__.py` (изменение) | Инициализация глобального реестра со встроенными инструментами при первом доступе |
| 2.4 | Тесты | Юнит-тесты операций реестра, фильтрации, исполнения |

**Критерий приёмки:** Встроенные инструменты работают через новый реестр. `get_tool_registry()` возвращает `EnhancedToolRegistry`.

### Фаза 3: Python SDK (3-4 дня)
**Цель:** Полностью функциональный декораторный и builder API.

| Шаг | Файл | Описание |
|-----|------|----------|
| 3.1 | `proxy/app/tools/sdk.py` | Реализация `json_schema_from_func()`, декоратора `@tool`, `ToolBuilder`, `ToolContext` |
| 3.2 | — | Реализация поддержки асинхронных инструментов в декораторе (определение корутинных функций) |
| 3.3 | — | Реализация `SDKProvider.discover()` — сканирование декорированных функций |
| 3.4 | — | Регистрация живых источников (ConfluenceLiveClient, JiraLiveClient, GitLabLiveClient) как асинхронных SDK-инструментов |
| 3.5 | Тесты | Юнит-тесты генерации JSON Schema, декоратора, builder, асинхронного исполнения |

**Критерий приёмки:** `@tool async def my_tool(...)` работает end-to-end. Живые источники вызываются как инструменты.

### Фаза 4: Декларативные инструменты (2-3 дня)
**Цель:** YAML/JSON-инструменты загружаются и исполняются.

| Шаг | Файл | Описание |
|-----|------|----------|
| 4.1 | `proxy/app/tools/declarative.py` | Реализация `DeclarativeToolLoader`, валидация JSON Schema, интерполяция переменных, HTTP-исполнитель, shell-исполнитель с ограничениями безопасности |
| 4.2 | `proxy/app/config.py` (изменение) | Добавление конфигурации `TOOLS_DECLARATIVE_DIR` |
| 4.3 | — | Примеры файлов декларативных инструментов для документации |
| 4.4 | Тесты | Юнит-тесты загрузки YAML, валидации, HTTP-исполнения (mock), shell-исполнения, отклонения по безопасности |

**Критерий приёмки:** Декларативные инструменты загружаются из `TOOLS_DECLARATIVE_DIR`. Ограничения безопасности shell соблюдаются.

### Фаза 5: Автообнаружение OpenAPI (2-3 дня)
**Цель:** Спецификации OpenAPI автоматически конвертируются в инструменты.

| Шаг | Файл | Описание |
|-----|------|----------|
| 5.1 | `proxy/app/tools/openapi_discovery.py` | Реализация `OpenAPIDiscovery`, `OpenAPIToolGenerator`, режимов AUTO и LLM_DRIVEN |
| 5.2 | `proxy/app/config.py` (изменение) | Добавление конфигурации `TOOLS_OPENAPI_SPECS` |
| 5.3 | Тесты | Юнит-тесты с мок-спецификациями OpenAPI, оба режима |

**Критерий приёмки:** Спецификация OpenAPI → зарегистрированные инструменты. Параметры эндпоинтов отображаются корректно.

### Фаза 6: Оркестрация (3-4 дня)
**Цель:** Параллельное исполнение, потоковая передача, паттерны композиции.

| Шаг | Файл | Описание |
|-----|------|----------|
| 6.1 | `proxy/app/tools/orchestrator.py` | Реализация `ParallelExecutor`, `StreamingExecutor`, `ToolComposer` |
| 6.2 | `proxy/app/tools/security.py` | Реализация `ToolVisibilityFilter`, `ToolInputSanitizer` |
| 6.3 | `proxy/app/tools/metrics.py` | Реализация `ToolMetrics` со счётчиками/гистограммами/gauge Prometheus |
| 6.4 | `proxy/app/tools/audit.py` | Реализация `ToolAuditLogger` со структурированным JSON-логированием |
| 6.5 | `proxy/app/orchestrator.py` (изменение) | Обновление `call_tools` для использования `ParallelExecutor`. Перевод в async. |
| 6.6 | `proxy/app/config.py` (изменение) | Добавление `TOOLS_PARALLEL_EXECUTION`, `TOOLS_MAX_CONCURRENCY` |
| 6.7 | Тесты | Юнит-тесты параллельного исполнения, обработки ошибок, повторов, композиции, генерации метрик |

**Критерий приёмки:** Несколько вызовов инструментов исполняются параллельно. Сбой одного инструмента не крашит другие. Метрики генерируются.

### Фаза 7: API + Интеграция (2 дня)
**Цель:** Эндпоинт обнаружения инструментов, консолидация.

| Шаг | Файл | Описание |
|-----|------|----------|
| 7.1 | `proxy/app/main.py` (изменение) | Добавление эндпоинтов `GET /v1/tools`, `GET /v1/tools/{name}` |
| 7.2 | `proxy/app/provider_adapter.py` (изменение) | Переключение импортов `ToolDefinition`/`ToolResult`/`ToolCall` на `proxy.app.tools.definition` |
| 7.3 | — | Добавление обнаружения инструментов при запуске (загрузка всех провайдеров) |
| 7.4 | Тесты | Интеграционные тесты эндпоинта /v1/tools, E2E вызов инструмента через оркестратор |

**Критерий приёмки:** `/v1/tools` возвращает все зарегистрированные инструменты. provider_adapter использует консолидированные типы.

### Фаза 8: Документация + Полировка (1-2 дня)
**Цель:** Документация для разработчиков, руководство по миграции.

| Шаг | Описание |
|-----|----------|
| 8.1 | Написание руководства разработчика SDK с примерами |
| 8.2 | Написание справочника по декларативным инструментам |
| 8.3 | Написание руководства по автообнаружению OpenAPI |
| 8.4 | Обновление AGENTS.md с новой архитектурой системы инструментов |
| 8.5 | Руководство по миграции для существующих авторов инструментов |

**Общая оценка:** 17-24 дня для старшего разработчика.

---

## 8. Риски и смягчения

| Риск | Влияние | Вероятность | Смягчение |
|------|---------|-------------|-----------|
| Циклические импорты с provider_adapter | ВЫСОКОЕ — приложение не запустится | НИЗКАЯ | `definition.py` не имеет внутренних импортов. Все методы конвертации форматов находятся непосредственно в `ToolDefinition`, избегая импорта LLM-адаптера. |
| Нарушение безопасности shell-инструментов | ВЫСОКОЕ — RCE | СРЕДНЯЯ | Обязательная валидация белого списка при загрузке. Отклонение инструментов без `allowed_commands`. Блокировка shell-метасимволов в значениях параметров. Логирование всех shell-исполнений на уровне WARNING. |
| Ошибка парсинга спецификации OpenAPI | СРЕДНЕЕ — инструменты отсутствуют | СРЕДНЯЯ | Graceful degradation. Неудачные спецификации логируют предупреждение, не крашат запуск. Частичная регистрация, если некоторые эндпоинты парсятся корректно. |
| Снижение производительности при параллельном исполнении | СРЕДНЕЕ — скачок CPU/памяти | НИЗКАЯ | Семафор `TOOLS_MAX_CONCURRENCY` ограничивает параллельные исполнения. По умолчанию 10, настраивается. |
| Путаница авторов существующих инструментов из-за устаревания | НИЗКОЕ — тикеты поддержки | СРЕДНЯЯ | Сохранение 100% обратной совместимости через shim-ы. DeprecationWarning с чётким путём миграции. Руководство по миграции в документации. |
| Несоответствие async/sync в LangGraph | СРЕДНЕЕ — ошибка рантайма | СРЕДНЯЯ | LangGraph поддерживает асинхронные узлы. `call_tools` становится `async def call_tools_async`. Синхронный путь сохранён для режима без LangGraph. |
| Граничные случаи генерации схем | НИЗКОЕ — ручное переопределение доступно | СРЕДНЯЯ | `json_schema_from_func()` покрывает 90%+ паттернов. Оставшиеся 10% используют словарь `parameters_schema` для переопределения (тот же API, что и сейчас). |

---

## 9. Структура файлов

### Новые файлы

```
proxy/app/tools/
├── __init__.py                 # Public API re-exports, backward compat
├── definition.py               # ToolDefinition, ToolResult, ToolParam, RetryPolicy, ToolVisibility
├── registry.py                 # EnhancedToolRegistry, ToolProvider (ABC), SDKProvider
├── sdk.py                      # @tool decorator, ToolBuilder, ToolContext, json_schema_from_func
├── declarative.py              # DeclarativeToolLoader, DeclarativeToolSchema, HTTP/Shell executors
├── openapi_discovery.py        # OpenAPIDiscovery, OpenAPIToolGenerator
├── orchestrator.py             # ParallelExecutor, StreamingExecutor, ToolComposer
├── errors.py                   # ToolError hierarchy, classify_error
├── security.py                 # ToolVisibilityFilter, ToolInputSanitizer
├── metrics.py                  # ToolMetrics (Prometheus)
└── audit.py                    # ToolAuditLogger
```

### Изменённые файлы

```
proxy/app/tools.py              → Deprecation shim (re-exports from tools package)
proxy/app/orchestrator.py       → call_tools upgraded to async parallel execution
proxy/app/provider_adapter.py   → Consolidate ToolDefinition imports
proxy/app/main.py               → Add GET /v1/tools, GET /v1/tools/{name}
proxy/app/config.py             → Add tool system configuration
```

### Тестовые файлы

```
tests/proxy/tools/
├── test_definition.py
├── test_registry.py
├── test_sdk.py
├── test_declarative.py
├── test_openapi_discovery.py
├── test_orchestrator.py
├── test_errors.py
├── test_security.py
├── test_metrics.py
└── test_audit.py
```

---

## 10. Путь миграции

### 10.1 Для существующих авторов инструментов (Ломающих изменений нет)

**До (текущее состояние):**
```python
from proxy.app.tools import ToolRegistry, ToolDefinition, get_tool_registry

registry = get_tool_registry()
registry.register(ToolDefinition(
    name="my_tool",
    description="My tool",
    parameters_schema={"type": "object", "properties": {...}},
    handler=my_handler,
    category="custom",
))
```

**После (рекомендуемое):**
```python
from proxy.app.tools.sdk import tool

@tool(name="my_tool", description="My tool", category="custom")
def my_tool(param1: str, param2: int = 5) -> str:
    """Tool description."""
    ...
```

**После (работает, предупреждение об устаревании):**
```python
# Old import path still works, emits DeprecationWarning
from proxy.app.tools import ToolRegistry, ToolDefinition, get_tool_registry
```

### 10.2 Для существующих потребителей инструментов

Изменения не требуются. `get_tool_registry()` возвращает `EnhancedToolRegistry`, совместимый по API со старым `ToolRegistry`. Все методы (`register`, `unregister`, `get_tool`, `list_tools`, `get_all`) имеют идентичные сигнатуры.

### 10.3 Консолидация provider adapter

До:
```python
from proxy.app.provider_adapter import ToolDefinition as PDToolDef  # local dataclass
```

После:
```python
from proxy.app.tools.definition import ToolDefinition  # canonical dataclass
```

`provider_adapter.py::ToolDefinition` становится устаревшим алиасом.

### 10.4 План отката

Если расширение вызовет проблемы:
1. Удалить директорию `proxy/app/tools/`
2. Восстановить оригинальный `proxy/app/tools.py` из git
3. Откатить `orchestrator.py` `call_tools` к оригинальной последовательной версии
4. Удалить эндпоинты `/v1/tools` из `main.py`

Все изменения аддитивные — существующие файлы не удаляются (только модифицируются с shim-ами обратной совместимости).

---

## Приложение A: Соответствие аннотаций типов и JSON Schema

```python
# Complete mapping table
TYPE_MAP = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    type(None): {"type": "null"},
    list: {"type": "array"},
    dict: {"type": "object"},
}

# Special handling:
# None | str | int → {"anyOf": [{"type": "null"}, {"type": "string"}, ...]}
# Optional[str] → {"type": "string"} + omit from "required"
# Literal["a", "b", "c"] → {"type": "string", "enum": ["a", "b", "c"]}
# list[str] → {"type": "array", "items": {"type": "string"}}
# BaseModel subclass → recursive schema generation
# Annotated[str, Field(description="...")] → {"type": "string", "description": "..."}
# Enum subclass → {"type": "string", "enum": [...members...]}
```

## Приложение B: Значения по умолчанию для RetryPolicy

```python
@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff: str = "exponential"       # "fixed" | "exponential"
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    retryable_errors: list[str] = field(default_factory=lambda: [
        "ToolExecutionError",
        "ToolTimeoutError",
    ])
    jitter: bool = True                 # Random jitter to prevent thundering herd
```

## Приложение C: CompositionPatterns

```python
@dataclass
class ChainPattern:
    """Chain: A → B → C. Each step receives previous step's output."""
    steps: list[str]
    input_mapper: Callable[[ToolResult], dict] | None  # Transform output→input

@dataclass
class FanOutPattern:
    """Fan-out: Run same tool with N different inputs, merge results."""
    tool_name: str
    inputs: list[dict]
    merge_strategy: str = "concat"  # "concat" | "first" | "best_score"

@dataclass
class FanInPattern:
    """Fan-in: Run N different tools with same input, merge results."""
    tool_names: list[str]
    input_params: dict
    merge_strategy: str = "concat"

@dataclass
class ConditionalPattern:
    """Conditional: If condition → tool_a else tool_b."""
    condition: Callable[[ToolContext], bool]
    true_tool: str
    false_tool: str

CompositionPattern = ChainPattern | FanOutPattern | FanInPattern | ConditionalPattern
```
