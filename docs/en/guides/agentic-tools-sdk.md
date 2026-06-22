# Agentic Tools — Python SDK Guide

**Implementation Status:** Implemented in Beyond v2.0. The Python SDK (`@tool` decorator, `ToolBuilder` fluent API, `ToolContext`) is fully available for defining custom tools in pure Python with automatic JSON Schema generation from type hints.

---

## 1. Overview

The Agentic Tools SDK enables developers to define RAG tools in pure Python. Tools are automatically registered, discovered at proxy startup, and made available to the LangGraph orchestrator for agentic query processing.

Two APIs are provided:
- **`@tool` decorator** — declarative, auto-infers schema from type hints
- **`ToolBuilder` fluent API** — programmatic, explicit control over every field

---

## 2. Quick Start — `@tool` Decorator

### 2.1 Basic Tool

```python
from proxy.app.tools.sdk import tool

@tool(category="search", tags=["fast"])
async def search_confluence(query: str, max_results: int = 5) -> str:
    """Search Confluence pages by CQL query."""
    # ... implementation
    return f"Found {max_results} results for '{query}'"
```

The decorator automatically:
- Reads parameter names, types, and defaults from the function signature
- Uses the docstring as the tool description
- Generates JSON Schema from type hints (`str` → `"string"`, `int` → `"integer"`)
- Detects `async` functions and routes them correctly
- Registers the tool in the global SDK registry

### 2.2 Tool with Custom Metadata

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

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | function name | Unique tool identifier |
| `description` | `str` | docstring | Tool description for LLM routing |
| `category` | `str` | `"general"` | Grouping category |
| `tags` | `list[str]` | `[]` | Searchable tags |
| `version` | `str` | `"1.0.0"` | Semantic version |
| `timeout` | `float` | `30.0` | Execution timeout in seconds |
| `retry_policy` | `RetryPolicy` | `None` | Retry configuration |
| `visibility` | `ToolVisibility` | `PUBLIC` | RBAC visibility level |
| `depends_on` | `list[str]` | `[]` | Other tool names this tool requires |

---

## 3. ToolContext — Shared State

Each tool handler receives a `ToolContext` if its first parameter is typed as `ToolContext`:

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

`ToolContext` fields:

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | `str \| None` | Authenticated user ID |
| `user_role` | `str \| None` | User's RBAC role |
| `request_id` | `str` | Correlation ID |
| `tool_call_id` | `str` | Unique tool call ID |
| `get_state(key)` | method | Read cross-tool state |
| `set_state(key, value)` | method | Write cross-tool state |
| `stream_partial(data)` | method | Emit streaming partial result |

---

## 4. Type Mapping

Python type hints are automatically mapped to JSON Schema types:

| Python Type | JSON Schema |
|-------------|-------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list[X]` | `{"type": "array", "items": {"type": "X"}}` |
| `dict` | `"object"` |
| `Optional[X]` | X (but not required) |
| `Annotated[X, "description"]` | X (description extracted) |

### Adding descriptions to parameters

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

## 5. ToolBuilder — Fluent API

For programmatic tool creation when decorators are insufficient:

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

`ToolBuilder` methods are chainable and return `self`:

| Method | Description |
|--------|-------------|
| `with_description(text)` | Set tool description |
| `with_param(name, type, desc, required, default, enum, items_type)` | Add a parameter |
| `with_handler(fn)` | Set synchronous handler |
| `with_async_handler(fn)` | Set async handler |
| `with_category(cat)` | Set category |
| `with_tags(tags)` | Set tags |
| `with_timeout(s)` | Set timeout |
| `with_retry_policy(rp)` | Set retry policy |
| `with_visibility(v)` | Set visibility |
| `build()` | Construct the `ToolDefinition` |

---

## 6. Registration & Discovery

Tools defined via `@tool` are auto-registered in the SDK registry. At proxy startup, the `EnhancedToolRegistry` scans and loads all tool definitions.

```python
# proxy/app/tools/registry.py
from proxy.app.tools.sdk import _sdk_registered_tools

# All @tool-decorated functions are available here
for name, definition in _sdk_registered_tools.items():
    print(f"Tool: {name} — {definition.description}")
```

Tools created via `ToolBuilder` must be manually registered:

```python
from proxy.app.tools.registry import EnhancedToolRegistry

registry = EnhancedToolRegistry()
registry.register(tool)
```

---

## 7. Security & RBAC

Tool visibility controls which roles can access each tool:

| `ToolVisibility` | Accessible by |
|------------------|--------------|
| `PUBLIC` | All authenticated users |
| `USER` | `user`, `expert`, `admin` |
| `INTERNAL` | `expert`, `admin` |
| `ADMIN` | `admin` only |

The `ToolVisibilityFilter` and `ToolInputSanitizer` in `proxy/app/tools/security.py` enforce these rules at runtime.

---

## 8. Complete Example

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

## 9. Related Documents

- [Declarative Tools Reference](agentic-tools-declarative.md) — YAML/JSON tool definitions
- [OpenAPI Discovery Guide](agentic-tools-openapi.md) — Auto-discover tools from OpenAPI specs
- [ADR-009: Agentic Tools Expansion Architecture](../adr/ADR-009-agentic-tools-expansion.md)
