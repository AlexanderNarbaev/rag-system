# ADR-009: Agentic Tools Expansion Architecture

**Status:** Accepted  
**Date:** 2026-07-05  
**Author:** Architecture Design  
**Scope:** Tool system redesign — SDK, declarative, OpenAPI, orchestration

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Modules and Components](#2-modules-and-components)
3. [Interfaces and Contracts](#3-interfaces-and-contracts)
4. [Data Flow](#4-data-flow)
5. [Architecture Decision Records](#5-architecture-decision-records)
6. [Dependency Map](#6-dependency-map)
7. [Implementation Sequence](#7-implementation-sequence)
8. [Risks and Mitigations](#8-risks-and-mitigations)
9. [File Structure](#9-file-structure)
10. [Migration Path](#10-migration-path)

---

## 1. Architecture Overview

### 1.1 High-Level Architecture

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

### 1.2 Tool Registration Flow

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

## 2. Modules and Components

### 2.1 New Package: `proxy/app/tools/`

| Module                 | Responsibility                                           | Key Classes                                                                                                 |
|------------------------|----------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| `definition.py`        | Unified data models, JSON Schema generation              | `ToolDefinition`, `ToolResult`, `ToolParam`, `ToolError`, `RetryPolicy`, `ToolVisibility`                   |
| `registry.py`          | Enhanced registry with provider pattern, backward compat | `EnhancedToolRegistry`, `ToolProvider` (ABC), `SDKProvider`, `DeclarativeProvider`, `OpenAPIProvider`       |
| `sdk.py`               | Python decorator API and builder API                     | `tool` (decorator), `ToolBuilder`, `ToolContext`, `json_schema_from_func`                                   |
| `declarative.py`       | YAML/JSON declarative tool loader with validation        | `DeclarativeToolLoader`, `DeclarativeToolSchema`, `HttpToolConfig`, `ShellToolConfig`                       |
| `openapi_discovery.py` | OpenAPI spec parser → tool generator                     | `OpenAPIDiscovery`, `OpenAPIToolGenerator`, `DiscoveryMode` (AUTO, LLM_DRIVEN)                              |
| `orchestrator.py`      | Parallel/streaming execution, composition patterns       | `ParallelExecutor`, `StreamingExecutor`, `ToolComposer`, `CompositionPattern`                               |
| `errors.py`            | Error taxonomy and classification                        | `ToolNotFoundError`, `ToolExecutionError`, `ToolTimeoutError`, `ToolPermissionError`, `ToolValidationError` |
| `security.py`          | RBAC visibility filter, input sanitizer                  | `ToolVisibilityFilter`, `ToolInputSanitizer`                                                                |
| `metrics.py`           | Prometheus instrumentation                               | `ToolMetrics` (counters, histograms, gauges)                                                                |
| `audit.py`             | Structured audit logging                                 | `ToolAuditLogger`                                                                                           |
| `__init__.py`          | Public API re-exports, backward-compat shim              | Re-exports all public symbols, `ToolRegistry` alias                                                         |

### 2.2 Modified Files

| File                            | Changes                                                                                                                         |
|---------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| `proxy/app/tools.py`            | **Deprecated.** Becomes a thin re-export shim pointing to `proxy/app/tools/__init__.py`. All existing imports continue working. |
| `proxy/app/orchestrator.py`     | `call_tools` node upgraded: parallel execution via `ParallelExecutor`, async tool support, tool result streaming.               |
| `proxy/app/provider_adapter.py` | Consolidate `ToolDefinition`/`ToolResult`/`ToolCall` to import from `proxy.app.tools.definition` instead of local dataclasses.  |
| `proxy/app/main.py`             | Add endpoints: `GET /v1/tools`, `GET /v1/tools/{name}`. Add tool discovery on startup.                                          |
| `proxy/app/config.py`           | Add configuration: `TOOLS_PARALLEL_EXECUTION`, `TOOLS_MAX_CONCURRENCY`, `TOOLS_DECLARATIVE_DIR`, `TOOLS_OPENAPI_SPECS`          |

### 2.3 Component Descriptions

#### 2.3.1 `definition.py` — Unified Data Model

Consolidates and extends three currently separate `ToolDefinition` classes:

- `proxy/app/tools.py::ToolDefinition` (current registry)
- `proxy/app/provider_adapter.py::ToolDefinition` (LLM format)
- `proxy/app/provider_adapter.py::ToolResult` / `ToolCall` (execution)

New unified `ToolDefinition`:

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

#### 2.3.2 `sdk.py` — Python Tool SDK

**Decorator API:**

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

The decorator:

1. Reads type hints via `typing.get_type_hints()`
2. Reads docstring for description
3. Generates JSON Schema from parameter types
4. Registers the tool in the global registry
5. Supports both `async def` and `def`

**ToolContext (injected automatically):**

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

**JSON Schema Generation:**

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

**Type Hint → JSON Schema Mapping:**

| Python Type          | JSON Schema                                              |
|----------------------|----------------------------------------------------------|
| `str`                | `{"type": "string"}`                                     |
| `int`                | `{"type": "integer"}`                                    |
| `float`              | `{"type": "number"}`                                     |
| `bool`               | `{"type": "boolean"}`                                    |
| `list[X]`            | `{"type": "array", "items": type_of(X)}`                 |
| `Optional[X]`        | `type_of(X)` + omit from `required`                      |
| `Literal["a","b"]`   | `{"type": "string", "enum": ["a", "b"]}`                 |
| `dict[str, X]`       | `{"type": "object", "additionalProperties": type_of(X)}` |
| `Annotated[T, desc]` | `type_of(T)` with `description`                          |
| `BaseModel` subclass | `{"type": "object", ...}` recursive                      |

#### 2.3.3 `declarative.py` — YAML/JSON Declarative Tools

**Tool Definition Schema (JSON Schema):**

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

**YAML Example:**

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

**Variable Interpolation:**

- `{{ENV_VAR}}` — environment variable at load time
- `{{param_name}}` — tool parameter at call time
- `{{CONTEXT.user_id}}` — ToolContext fields at call time

**Validation on Load:**

- Schema validation against JSON Schema
- Name uniqueness check
- Allowed hosts/commands whitelist check
- Template variable validation (all referenced vars exist)

#### 2.3.4 `openapi_discovery.py` — OpenAPI Auto-Discovery

**Discovery Modes:**

| Mode         | Behavior                                                                             | When to Use                 |
|--------------|--------------------------------------------------------------------------------------|-----------------------------|
| `AUTO`       | Parse spec → register all GET as search tools, all POST/PUT/DELETE as action tools   | Known, well-structured APIs |
| `LLM_DRIVEN` | Give LLM the spec, let it decide which endpoints to expose, interactive confirmation | Complex or unfamiliar APIs  |

**Auto Mode Algorithm:**

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

**Configuration:**

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

#### 2.3.5 `orchestrator.py` — Tool Orchestration

**Parallel Execution:**

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

**Streaming Execution:**

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

**Composition Patterns:**

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

**Executor Integration with LangGraph's `call_tools`:**

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

#### 2.3.6 `errors.py` — Error Taxonomy

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

**Error Classification Function:**

```python
def classify_error(tool_name: str, error: Exception) -> ToolError:
    """Map Python exceptions to tool error types."""
```

#### 2.3.7 `security.py` — RBAC Visibility

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

#### 2.3.8 `metrics.py` — Prometheus Instrumentation

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

#### 2.3.9 `audit.py` — Audit Logging

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

## 3. Interfaces and Contracts

### 3.1 `EnhancedToolRegistry` Public API

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

### 3.2 `ToolProvider` Abstract Interface

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

**Concrete Providers:**

| Provider              | `provider_name` | Source                                     |
|-----------------------|-----------------|--------------------------------------------|
| `SDKProvider`         | `"sdk"`         | Decorated functions and builders           |
| `DeclarativeProvider` | `"declarative"` | YAML/JSON files in `TOOLS_DECLARATIVE_DIR` |
| `OpenAPIProvider`     | `"openapi"`     | OpenAPI specs from `TOOLS_OPENAPI_SPECS`   |

### 3.3 New FastAPI Endpoints

#### `GET /v1/tools`

Query parameters: `category`, `tag`, `provider`

Response:

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

Response:

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

**Note:** Raw handler functions are never exposed via API (security).

### 3.4 `GET /v1/tools` Authorization

| User Role       | Visible Tools (by visibility field) |
|-----------------|-------------------------------------|
| `admin`         | `public`, `admin`, `expert`, `user` |
| `expert`        | `public`, `expert`, `user`          |
| `user`          | `public`, `user`                    |
| `read_only`     | `public`                            |
| Unauthenticated | `public` only                       |

---

## 4. Data Flow

### 4.1 Tool Registration Flow

```
STARTUP
  │
  ├─► SDKProvider.discover()
  │     Scans for @tool decorated functions
  │     Returns list[ToolDefinition]
  │     → registry.register() for each
  │
  ├─► DeclarativeProvider.discover()
  │     Loads YAML/JSON from TOOLS_DECLARATIVE_DIR
  │     Validates against DeclarativeToolSchema
  │     Returns list[ToolDefinition]
  │     → registry.register() for each
  │
  └─► OpenAPIProvider.discover()
        Fetches OpenAPI specs from TOOLS_OPENAPI_SPECS
        Parses endpoints into ToolDefinitions
        Returns list[ToolDefinition]
        → registry.register() for each

HOT RELOAD (optional)
  │
  ├─► POST /v1/admin/tools/reload?provider=declarative
  │     → DeclarativeProvider.reload()
  │     → Re-registers tools atomically
  
  └─► File watcher on TOOLS_DECLARATIVE_DIR
        → Auto-reload on file change (opt-in)
```

### 4.2 Tool Execution Flow

```
LLM generates tool_calls
  │
  ▼
LangGraph: call_tools node
  │
  ├─► 1. Parse tool calls from LLM response
  │
  ├─► 2. Build dependency DAG (topological sort on depends_on)
  │
  ├─► 3. Execute in dependency order
  │     For each dependency level:
  │       ├─► Validate user permissions (ToolVisibilityFilter)
  │       ├─► Sanitize inputs (ToolInputSanitizer)
  │       ├─► asyncio.gather(*coroutines)  ← parallel within level
  │       │     │
  │       │     ├─► ToolMetrics.measure() context manager
  │       │     ├─► Try: handler(**params) or async_handler(**params)
  │       │     │     ├─► Success → ToolResult(content=...)
  │       │     │     └─► Exception → classify_error() → RetryPolicy?
  │       │     │           ├─► Retryable → retry with backoff
  │       │     │           └─► Non-retryable → ToolResult(error=...)
  │       │     └─► ToolAuditLogger.log()
  │       │
  │       └─► Collect all results
  │
  ├─► 4. Feed results back into LLM conversation
  │
  └─► 5. Continue or loop (max_tool_loops=5)
```

### 4.3 Dependency Resolution Flow

```
Tools with dependencies:
  search_documents (no deps)
  get_document_metadata (depends_on: ["search_documents"])
  summarize_document (depends_on: ["get_document_metadata"])
  search_jira (no deps)
  cross_reference (depends_on: ["search_documents", "search_jira"])

Execution plan:
  Level 0: [search_documents, search_jira]     ← parallel
  Level 1: [get_document_metadata]              ← after Level 0
  Level 2: [cross_reference, summarize_document] ← after Level 1
```

---

## 5. Architecture Decision Records

### ADR-009-1: Tool Definition Consolidation

**Context:** Three separate `ToolDefinition` classes exist in the codebase:

- `proxy/app/tools.py::ToolDefinition` (registry dataclass)
- `proxy/app/provider_adapter.py::ToolDefinition` (LLM format)
- `proxy/app/provider_adapter.py::ToolResult` / `ToolCall` (execution)

**Options:**

1. Keep all three, add a fourth for the expansion
2. Consolidate into one canonical `ToolDefinition` with format conversion methods
3. Consolidate but keep provider_adapter's simple version for performance

**Chosen:** Option 2 — Consolidate into `proxy/app/tools/definition.py` with format methods.

**Rationale:** Single source of truth reduces drift. Format conversion methods (`to_openai_format()`,
`to_anthropic_format()`) handle provider-specific serialization. The decoupling between the canonical model and LLM
format is preserved via methods, not separate classes.

**Tradeoffs:** Slightly larger dataclass (but fields are optional where not universally needed). Provider_adapter must
import from tools package (new dependency, acceptable).

**Risks:** Must ensure no circular imports. Mitigation: definition.py has zero internal dependencies.

---

### ADR-009-2: Subpackage vs. Flat Module

**Context:** The tool system functionality spans 10+ concerns (SDK, declarative, OpenAPI, orchestration, errors,
security, metrics, audit, registry, definition).

**Options:**

1. Keep everything in a single `tools.py` (monolithic)
2. Create `proxy/app/tools/` subpackage with separate modules
3. Create `tools/` at the top level (separate package)

**Chosen:** Option 2 — `proxy/app/tools/` subpackage.

**Rationale:** `tools.py` is already 257 lines and growing. The expansion adds thousands of lines. Separate modules
enable independent testing and maintenance. Copied from existing project pattern (ETL has `extractors/`, `chunker/`,
etc.).

**Tradeoffs:** More files, but each focused (< 300 lines target). Import paths change. Mitigation: `__init__.py`
re-exports all public symbols. Old `tools.py` becomes a deprecation shim.

---

### ADR-009-3: Async Execution Strategy

**Context:** Current `call_tools` is synchronous sequential (
`for tc in tool_calls: handle_function_call(tc, registry)`). Live sources are async but not registered as tools.

**Options:**

1. Keep sequential, add async support when needed
2. `asyncio.gather` with semaphore for uncontrolled parallelism
3. Dependency-aware parallel execution (topological sort + gather per level)

**Chosen:** Option 3 — Dependency-aware parallel execution.

**Rationale:** Live sources (Confluence, Jira, GitLab) are independent I/O operations. Running them sequentially adds
unnecessary latency. At 15s timeout each, 3 sequential calls = 45s vs 15s parallel. Dependency-awareness prevents
ordering bugs.

**Tradeoffs:** Added complexity in executor. For backward compat, synchronous path preserved for when
`USE_LANGGRAPH=false`.

---

### ADR-009-4: JSON Schema Generation Strategy

**Context:** Current tools require manual JSON Schema writing (`parameters_schema` dict). Error-prone and verbose.

**Options:**

1. Keep manual JSON Schema (no change)
2. Use `inspect.signature()` + `typing.get_type_hints()` auto-generation
3. Require Pydantic models for tool parameters

**Chosen:** Option 2 with optional Option 3.

**Rationale:** Auto-generation from type hints covers 90%+ of tools. The `json_schema_from_func()` function handles all
common Python types. For complex nested schemas, Pydantic `BaseModel` parameters are supported as an escape hatch.
Manual override still available.

**Tradeoffs:** Complex type hints (e.g., `Annotated[list[dict[str, int]], Field(...)]`) may not map perfectly.
Mitigation: manual `parameters_schema` override takes precedence.

---

### ADR-009-5: Backward Compatibility Strategy

**Context:** Existing 3 built-in tools, existing `ToolRegistry` API, existing `execute_tool()` and
`handle_function_call()` functions must continue working.

**Options:**

1. Replace everything, breaking changes
2. Keep old API, add new alongside
3. Deprecation shim + gradual migration

**Chosen:** Option 3 — Deprecation shim.

**Rationale:** The old `tools.py` becomes:

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

Existing imports continue working. Tests pass. No breakage.

---

### ADR-009-6: Shell Tool Safety

**Context:** Declarative tools include shell command support. This is inherently dangerous.

**Options:**

1. No shell tools (reject requirement)
2. Allow shell with whitelist-based safety
3. Allow shell with sandbox/container isolation

**Chosen:** Option 2 — Whitelist-based safety.

**Rationale:** Declarative tools target administrators who need system diagnostics (disk, memory, logs). Whitelist (
`allowed_commands`, `allowed_paths`) provides defense-in-depth. Shell tools are `visibility: admin` only by convention (
enforced at validation).

**Safety Constraints:**

- `allowed_commands`: Regex-matched allowed binaries (e.g., `["echo", "df", "free", "systemctl"]`)
- `allowed_paths`: Restrict file access to specific directories
- `env_whitelist`: Only pass specific env vars (never secrets)
- `timeout`: Mandatory, max 30s for shell tools
- `no_shell_metacharacters`: Block `;`, `&&`, `|`, `$()`, backticks in parameter values
- Log all shell commands at WARNING level

**Tradeoffs:** Whitelists can be circumvented if too permissive. Mitigation: validation rejects tools with no
`allowed_commands`.

---

### ADR-009-7: Tool Discovery Caching

**Context:** OpenAPI specs may be remote. Declarative files may be numerous. Registration happens at startup.

**Options:**

1. Load all at startup, keep in memory (current approach)
2. Lazy-load on first tool call
3. Periodic refresh with TTL cache

**Chosen:** Option 1 with optional Option 3.

**Rationale:** Tools are critical to request processing. Lazy loading adds latency on first call. Most deployments
have < 100 tools, fitting easily in memory. For dynamic environments, `reload_provider()` enables hot reload without
restart.

---

## 6. Dependency Map

### 6.1 Module Dependencies (Layered, top-down)

```
Layer 0: Standard library + third-party
  typing, inspect, asyncio, dataclasses, logging, yaml, json, aiohttp, prometheus_client

Layer 1: Foundation modules (no internal deps)
  definition.py → (zero internal deps)
  errors.py → exceptions.py (RAGError)
  config.py → (zero internal deps)

Layer 2: Infrastructure
  metrics.py → prometheus_client
  audit.py → logging_config.py
  security.py → rbac.py, config.py

Layer 3: Providers
  sdk.py → definition.py, registry.py, errors.py
  declarative.py → definition.py, registry.py, errors.py, security.py
  openapi_discovery.py → definition.py, registry.py, errors.py

Layer 4: Orchestration
  orchestrator.py → definition.py, registry.py, errors.py, security.py, metrics.py, audit.py

Layer 5: Registry (depends on providers for interface definition)
  registry.py → definition.py, errors.py

Layer 6: Public API
  __init__.py → all modules above
  tools.py (shim) → __init__.py

Layer 7: Application integration
  main.py → registry.py, orchestrator.py
  orchestrator.py → orchestrator.py (tools), registry.py
  provider_adapter.py → definition.py
```

### 6.2 Circular Dependency Prevention

- `definition.py` has **zero** internal imports — pure data structures
- `registry.py` depends on `definition.py` and `errors.py` only
- `orchestrator.py` depends on `registry.py` but NOT vice versa
- No module exports circular references

### 6.3 External Dependencies

| Package                  | Purpose                                 | Required?                                 |
|--------------------------|-----------------------------------------|-------------------------------------------|
| `pyyaml`                 | YAML declarative tool loading           | Optional (only if declarative tools used) |
| `jsonschema`             | Declarative tool validation             | Optional                                  |
| `openapi-spec-validator` | OpenAPI spec validation                 | Optional (only if OpenAPI discovery used) |
| `prometheus_client`      | Already present, used for tool metrics  | Optional (METRICS_ENABLED)                |
| `aiohttp`                | Already present, HTTP declarative tools | Already present                           |

---

## 7. Implementation Sequence

### Phase 1: Foundation (2-3 days)

**Goal:** Laying groundwork, zero breaking changes.

| Step | File                            | Description                                                                                                                                                        |
|------|---------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1.1  | `proxy/app/tools/definition.py` | Create unified `ToolDefinition`, `ToolResult`, `ToolParam`, `RetryPolicy`, `ToolVisibility` dataclasses with `to_openai_format()`, `to_anthropic_format()` methods |
| 1.2  | `proxy/app/tools/errors.py`     | Create `ToolError` hierarchy, `classify_error()` function                                                                                                          |
| 1.3  | `proxy/app/tools/__init__.py`   | Re-export all public symbols. Empty registry (no built-in tools yet).                                                                                              |
| 1.4  | `proxy/app/tools.py` (modify)   | Convert to deprecation shim, re-export from `proxy.app.tools`                                                                                                      |
| 1.5  | Tests                           | Unit tests for definition.py, errors.py                                                                                                                            |

**Acceptance:** Existing tests pass. No functional change. Imports from `proxy.app.tools` still work.

### Phase 2: Enhanced Registry (2-3 days)

**Goal:** Replace singleton registry with provider-based registry.

| Step | File                                   | Description                                                                                                                                                            |
|------|----------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 2.1  | `proxy/app/tools/registry.py`          | Implement `EnhancedToolRegistry` with `ToolProvider` ABC, `register()`, `unregister()`, `list_tools()` with filters, `execute()`, `execute_async()`, `validate_tool()` |
| 2.2  | —                                      | Migrate 3 built-in tools (search_documents, search_by_version, get_document_metadata) to `SDKProvider`                                                                 |
| 2.3  | `proxy/app/tools/__init__.py` (modify) | Initialize global registry with built-in tools on first access                                                                                                         |
| 2.4  | Tests                                  | Unit tests for registry operations, filtering, execution                                                                                                               |

**Acceptance:** Built-in tools work through new registry. `get_tool_registry()` returns `EnhancedToolRegistry`.

### Phase 3: Python SDK (3-4 days)

**Goal:** Decorator and builder API fully functional.

| Step | File                     | Description                                                                                       |
|------|--------------------------|---------------------------------------------------------------------------------------------------|
| 3.1  | `proxy/app/tools/sdk.py` | Implement `json_schema_from_func()`, `@tool` decorator, `ToolBuilder`, `ToolContext`              |
| 3.2  | —                        | Implement async tool support in decorator (detects coroutine functions)                           |
| 3.3  | —                        | Implement `SDKProvider.discover()` — scans for decorated functions                                |
| 3.4  | —                        | Register live sources (ConfluenceLiveClient, JiraLiveClient, GitLabLiveClient) as async SDK tools |
| 3.5  | Tests                    | Unit tests for JSON Schema generation, decorator, builder, async execution                        |

**Acceptance:** `@tool async def my_tool(...)` works end-to-end. Live sources callable as tools.

### Phase 4: Declarative Tools (2-3 days)

**Goal:** YAML/JSON tools loadable and executable.

| Step | File                             | Description                                                                                                                              |
|------|----------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| 4.1  | `proxy/app/tools/declarative.py` | Implement `DeclarativeToolLoader`, JSON Schema validation, variable interpolation, HTTP executor, shell executor with safety constraints |
| 4.2  | `proxy/app/config.py` (modify)   | Add `TOOLS_DECLARATIVE_DIR` config                                                                                                       |
| 4.3  | —                                | Sample declarative tool files for documentation                                                                                          |
| 4.4  | Tests                            | Unit tests for YAML loading, validation, HTTP execution (mock), shell execution, safety rejection                                        |

**Acceptance:** Declarative tools load from `TOOLS_DECLARATIVE_DIR`. Shell safety constraints enforced.

### Phase 5: OpenAPI Auto-Discovery (2-3 days)

**Goal:** OpenAPI specs auto-converted to tools.

| Step | File                                   | Description                                                                     |
|------|----------------------------------------|---------------------------------------------------------------------------------|
| 5.1  | `proxy/app/tools/openapi_discovery.py` | Implement `OpenAPIDiscovery`, `OpenAPIToolGenerator`, AUTO and LLM_DRIVEN modes |
| 5.2  | `proxy/app/config.py` (modify)         | Add `TOOLS_OPENAPI_SPECS` config                                                |
| 5.3  | Tests                                  | Unit tests with mock OpenAPI specs, both modes                                  |

**Acceptance:** OpenAPI spec → registered tools. Endpoint parameters mapped correctly.

### Phase 6: Orchestration (3-4 days)

**Goal:** Parallel execution, streaming, composition patterns.

| Step | File                                 | Description                                                                             |
|------|--------------------------------------|-----------------------------------------------------------------------------------------|
| 6.1  | `proxy/app/tools/orchestrator.py`    | Implement `ParallelExecutor`, `StreamingExecutor`, `ToolComposer`                       |
| 6.2  | `proxy/app/tools/security.py`        | Implement `ToolVisibilityFilter`, `ToolInputSanitizer`                                  |
| 6.3  | `proxy/app/tools/metrics.py`         | Implement `ToolMetrics` with Prometheus counters/histograms/gauges                      |
| 6.4  | `proxy/app/tools/audit.py`           | Implement `ToolAuditLogger` with structured JSON logging                                |
| 6.5  | `proxy/app/orchestrator.py` (modify) | Upgrade `call_tools` to use `ParallelExecutor`. Make it async.                          |
| 6.6  | `proxy/app/config.py` (modify)       | Add `TOOLS_PARALLEL_EXECUTION`, `TOOLS_MAX_CONCURRENCY`                                 |
| 6.7  | Tests                                | Unit tests for parallel execution, error handling, retry, composition, metrics emission |

**Acceptance:** Multiple tool calls execute in parallel. Failed tool doesn't crash other tools. Metrics emitted.

### Phase 7: API + Integration (2 days)

**Goal:** Tool discovery endpoint, consolidations.

| Step | File                                     | Description                                                                             |
|------|------------------------------------------|-----------------------------------------------------------------------------------------|
| 7.1  | `proxy/app/main.py` (modify)             | Add `GET /v1/tools`, `GET /v1/tools/{name}` endpoints                                   |
| 7.2  | `proxy/app/provider_adapter.py` (modify) | Switch `ToolDefinition`/`ToolResult`/`ToolCall` imports to `proxy.app.tools.definition` |
| 7.3  | —                                        | Add tool discovery on startup (load all providers)                                      |
| 7.4  | Tests                                    | Integration tests for /v1/tools endpoint, E2E tool call through orchestrator            |

**Acceptance:** `/v1/tools` returns all registered tools. Provider_adapter uses consolidated types.

### Phase 8: Documentation + Polish (1-2 days)

**Goal:** Developer docs, migration guide.

| Step | Description                                        |
|------|----------------------------------------------------|
| 8.1  | Write SDK developer guide with examples            |
| 8.2  | Write declarative tools reference                  |
| 8.3  | Write OpenAPI discovery guide                      |
| 8.4  | Update AGENTS.md with new tool system architecture |
| 8.5  | Migration guide for existing tool authors          |

**Total estimate:** 17-24 days for a senior developer.

---

## 8. Risks and Mitigations

| Risk                                           | Impact                          | Likelihood | Mitigation                                                                                                                                                                 |
|------------------------------------------------|---------------------------------|------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Circular imports with provider_adapter         | HIGH — app won't start          | LOW        | `definition.py` has zero internal imports. All format conversion methods are on `ToolDefinition` itself, avoiding import of LLM adapter.                                   |
| Shell tool security breach                     | HIGH — RCE                      | MEDIUM     | Mandatory whitelist validation at load time. Reject tools without `allowed_commands`. Block shell metacharacters in parameter values. Log all shell executions at WARNING. |
| OpenAPI spec parsing failure                   | MEDIUM — tools missing          | MEDIUM     | Graceful degradation. Failed specs log warning, don't crash startup. Partial registration if some endpoints parse correctly.                                               |
| Performance regression with parallel execution | MEDIUM — CPU/memory spike       | LOW        | `TOOLS_MAX_CONCURRENCY` semaphore limits concurrent executions. Default 10, configurable.                                                                                  |
| Existing tool authors confused by deprecation  | LOW — support ticket            | MEDIUM     | Shims preserve 100% backward compat. DeprecationWarning with clear migration path. Migration guide in docs.                                                                |
| Async/sync mismatch in LangGraph               | MEDIUM — runtime error          | MEDIUM     | LangGraph supports async nodes. `call_tools` becomes `async def call_tools_async`. Synchronous path preserved for non-LangGraph mode.                                      |
| Schema generation edge cases                   | LOW — manual override available | MEDIUM     | `json_schema_from_func()` covers 90%+ patterns. Remaining 10% use `parameters_schema` dictionary override (same as current API).                                           |

---

## 9. File Structure

### New Files

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

### Modified Files

```
proxy/app/tools.py              → Deprecation shim (re-exports from tools package)
proxy/app/orchestrator.py       → call_tools upgraded to async parallel execution
proxy/app/provider_adapter.py   → Consolidate ToolDefinition imports
proxy/app/main.py               → Add GET /v1/tools, GET /v1/tools/{name}
proxy/app/config.py             → Add tool system configuration
```

### Test Files

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

## 10. Migration Path

### 10.1 For Existing Tool Authors (Breaking Change: None)

**Before (current):**

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

**After (recommended):**

```python
from proxy.app.tools.sdk import tool

@tool(name="my_tool", description="My tool", category="custom")
def my_tool(param1: str, param2: int = 5) -> str:
    """Tool description."""
    ...
```

**After (still works, deprecation warning):**

```python
# Old import path still works, emits DeprecationWarning
from proxy.app.tools import ToolRegistry, ToolDefinition, get_tool_registry
```

### 10.2 For Existing Tool Consumers

No changes needed. `get_tool_registry()` returns an `EnhancedToolRegistry` that is API-compatible with old
`ToolRegistry`. All methods (`register`, `unregister`, `get_tool`, `list_tools`, `get_all`) have identical signatures.

### 10.3 Provider Adapter Consolidation

Before:

```python
from proxy.app.provider_adapter import ToolDefinition as PDToolDef  # local dataclass
```

After:

```python
from proxy.app.tools.definition import ToolDefinition  # canonical dataclass
```

`provider_adapter.py::ToolDefinition` becomes a deprecated alias.

### 10.4 Rollback Plan

If the expansion causes issues:

1. Remove `proxy/app/tools/` directory
2. Restore original `proxy/app/tools.py` from git
3. Revert `orchestrator.py` `call_tools` to original sequential version
4. Remove `/v1/tools` endpoints from `main.py`

All changes are additive — no existing files are deleted (only modified with backward-compat shims).

---

## Appendix A: Type Hint → JSON Schema Reference

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

## Appendix B: RetryPolicy Defaults

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

## Appendix C: CompositionPatterns

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
