# Agentic Tools — OpenAPI Discovery Guide

**Implementation Status:** Implemented in Beyond v2.0. The `OpenAPIDiscovery` module automatically converts
OpenAPI/Swagger specs into `ToolDefinition` objects with auto and LLM-driven modes.

---

## 1. Overview

OpenAPI auto-discovery eliminates manual tool definition for REST APIs. Point the discovery engine at an OpenAPI spec
URL or file, and it generates ready-to-use RAG tools for every endpoint.

Two discovery modes are supported:

- **Auto mode** — heuristically maps GET endpoints → search tools, POST/PUT/DELETE → action tools
- **LLM-driven mode** — sends the spec to the LLM for intelligent tool selection (future)

---

## 2. Quick Start

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

## 3. Endpoint Mapping Rules

### 3.1 Auto Mode

| HTTP Method        | Tool Type   | Category     | Description                                   |
|--------------------|-------------|--------------|-----------------------------------------------|
| `GET`              | Search tool | `api_search` | Retrieves data; parameters become tool params |
| `POST`             | Action tool | `api_action` | Creates resources                             |
| `PUT`              | Action tool | `api_action` | Updates resources                             |
| `PATCH`            | Action tool | `api_action` | Partial updates                               |
| `DELETE`           | Action tool | `api_action` | Removes resources                             |
| `HEAD` / `OPTIONS` | Skipped     | —            | Not converted to tools                        |

### 3.2 Naming Convention

Tools are named by slugifying the OpenAPI path:

| OpenAPI Path                             | Tool Name                           |
|------------------------------------------|-------------------------------------|
| `/pets/{petId}`                          | `pets_petId`                        |
| `/store/orders/{orderId}/items/{itemId}` | `store_orders_orderId_items_itemId` |
| `/search`                                | `search`                            |

### 3.3 Parameter Mapping

OpenAPI parameters are mapped to `ToolParam` objects:

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

Parameter location (`in: query`, `in: path`, `in: header`) is reflected in the description but does not change the tool
interface (all become tool parameters).

---

## 4. OpenAPIProvider — Continuous Discovery

For production use, integrate via the `OpenAPIProvider` class which implements `ToolProvider`:

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

The provider automatically:

- Discovers tools at startup
- Periodically refreshes (configurable interval)
- Handles spec URL changes gracefully
- Reports discovery status

### Provider Configuration

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

## 5. Single-Endpoint Conversion

Use `OpenAPIToolGenerator` to convert individual endpoints:

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

## 6. Security & RBAC

Discovered tools respect the visibility setting:

```python
# All discovered tools are ADMIN-only
provider = OpenAPIProvider(
    name="admin_apis",
    spec_url="https://admin.internal/swagger.json",
    visibility=ToolVisibility.ADMIN,
)
```

The `ToolVisibilityFilter` (in `proxy/app/tools/security.py`) enforces this at runtime — non-admin users cannot see or
call admin-visible tools.

---

## 7. LLM-Driven Mode (Future)

When `DiscoveryMode.LLM_DRIVEN` is specified, the spec is sent to the LLM for intelligent tool selection instead of
converting every endpoint. This is a stub in the current implementation — the LLM integration will be provided in a
future release.

```python
provider = OpenAPIProvider(
    name="smart_discovery",
    spec_url="https://api.internal/openapi.json",
    mode=DiscoveryMode.LLM_DRIVEN,
    # Future: llm_params={"max_tools": 10, "min_relevance": 0.7}
)
```

---

## 8. Spec Formats Supported

- **OpenAPI 3.0 / 3.1** (JSON and YAML)
- **Swagger 2.0** (JSON and YAML)
- Local file paths and remote URLs
- `$ref` resolution (local references only)

---

## 9. Error Handling

| Scenario             | Behavior                         |
|----------------------|----------------------------------|
| Spec URL unreachable | Logs warning, returns empty list |
| Invalid spec format  | Logs error, returns empty list   |
| Unresolvable `$ref`  | Skips the endpoint, logs warning |
| Duplicate tool names | Last one wins (warning logged)   |

All errors are logged but non-fatal — the proxy continues to start with zero discovered tools.

---

## 10. Related Documents

- [Python SDK Guide](agentic-tools-sdk.md) — `@tool` decorator and `ToolBuilder`
- [Declarative Tools Reference](agentic-tools-declarative.md) — YAML/JSON tool definitions
- [ADR-009: Agentic Tools Expansion Architecture](../adr/ADR-009-agentic-tools-expansion.md)
