# Agentic Tools — Declarative Tools Reference (YAML/JSON)

**Implementation Status:** Implemented in Beyond v2.0. Tools can be defined declaratively in YAML or JSON files, loaded at startup from `TOOLS_DECLARATIVE_DIR`, with schema validation, variable interpolation, and built-in HTTP/shell handlers.

---

## 1. Overview

Declarative tools allow defining tools without writing Python code. Tool definitions are stored as YAML or JSON files and automatically loaded at proxy startup. This is ideal for:

- Non-developer tool configuration
- Infrastructure automation (shell commands)
- External API integration (HTTP endpoints)
- Configuration-as-code workflows
- RPM/Helm-deployed tool bundles

---

## 2. Tool Definition Schema

### 2.1 Minimal Example (YAML)

```yaml
# tools_declarative/check_service.yaml
name: check_service
description: Check health of a service by HTTP endpoint
category: monitoring
type: http
visibility: public

parameters:
  - name: service_name
    type: string
    description: Name of the service to check
    required: true

http:
  method: GET
  url_template: "https://{{service_name}}.internal/health"
  allowed_hosts:
    - "*.internal"

timeout: 10
```

### 2.2 Shell Tool Example

```yaml
# tools_declarative/disk_usage.yaml
name: disk_usage
description: Check disk usage on the server
category: monitoring
type: shell
visibility: admin

parameters:
  - name: path
    type: string
    description: Filesystem path to check
    required: true
    default: "/var/log"

shell:
  command: "df -h {{path}}"
  allowed_commands: ["df", "du"]
  allowed_paths: ["/var/log", "/data"]
  timeout: 15
```

---

## 3. Full Schema Reference

### 3.1 Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Unique tool identifier |
| `description` | `string` | Yes | Tool description for LLM routing |
| `category` | `string` | No | Grouping category (default: `"general"`) |
| `type` | `string` | Yes | Handler type: `"http"`, `"shell"` |
| `parameters` | `array` | No | List of parameter definitions |
| `tags` | `array<string>` | No | Searchable tags |
| `version` | `string` | No | Semantic version (default: `"1.0.0"`) |
| `timeout` | `number` | No | Execution timeout in seconds (default: `30`) |
| `visibility` | `string` | No | RBAC level: `"public"`, `"user"`, `"internal"`, `"admin"` |
| `depends_on` | `array<string>` | No | Tool dependencies |
| `retry` | `object` | No | Retry policy configuration |
| `http` | `object` | Required for `type: http` | HTTP handler config |
| `shell` | `object` | Required for `type: shell` | Shell handler config |

### 3.2 Parameter Definition

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Parameter name |
| `type` | `string` | Yes | JSON Schema type: `"string"`, `"integer"`, `"number"`, `"boolean"`, `"array"`, `"object"` |
| `description` | `string` | No | Parameter description |
| `required` | `boolean` | No | Whether the parameter is required (default: `false` if `default` is set) |
| `default` | `any` | No | Default value |
| `enum` | `array<string>` | No | Allowed values |
| `items_type` | `string` | No | For `array` type: inner element type |

### 3.3 Retry Policy

```yaml
retry:
  max_retries: 3
  backoff_s: 2.0
  retry_on: ["timeout", "http_5xx"]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_retries` | `number` | `1` | Maximum retry attempts |
| `backoff_s` | `number` | `1.0` | Backoff multiplier in seconds |
| `retry_on` | `array<string>` | `["timeout"]` | Error types: `"timeout"`, `"http_5xx"`, `"all"` |

---

## 4. HTTP Tool Configuration

```yaml
http:
  method: POST
  url_template: "https://api.internal/{{CONTEXT.namespace}}/search"
  headers:
    Authorization: "Bearer {{api_token}}"
    Content-Type: "application/json"
  body_template: '{"query": "{{query}}", "limit": {{limit}}}'
  allowed_hosts:
    - "api.internal"
    - "*.corp.example.com"
  follow_redirects: false
  verify_ssl: true
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `method` | `string` | Yes | HTTP method: `GET`, `POST`, `PUT`, `DELETE`, `PATCH` |
| `url_template` | `string` | Yes | URL with `{{variable}}` placeholders |
| `headers` | `object` | No | HTTP headers to send |
| `body_template` | `string` | No | Request body template (for POST/PUT/PATCH) |
| `allowed_hosts` | `array<string>` | Yes | Host whitelist (glob patterns supported) |
| `follow_redirects` | `boolean` | No | Follow HTTP redirects (default: `false`) |
| `verify_ssl` | `boolean` | No | Verify SSL certificates (default: `true`) |

---

## 5. Shell Tool Configuration

```yaml
shell:
  command: "grep {{pattern}} {{path}} | tail -{{lines}}"
  working_dir: "/var/log"
  allowed_commands:
    - "grep"
    - "cat"
    - "tail"
    - "head"
  allowed_paths:
    - "/var/log"
    - "/tmp"
  timeout: 10
  env:
    PATH: "/usr/bin:/bin"
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | `string` | Yes | Shell command with `{{variable}}` placeholders |
| `working_dir` | `string` | No | Working directory for the command |
| `allowed_commands` | `array<string>` | Yes | Command whitelist (first word only) |
| `allowed_paths` | `array<string>` | No | Path whitelist for arguments |
| `timeout` | `number` | No | Per-command timeout override |
| `env` | `object` | No | Environment variables |

### Security Notes

- Shell commands are checked for metacharacters (`;`, `&&`, `|`, `$()`, backticks) in parameter values
- Only whitelisted commands and paths pass validation
- Use `allowed_commands` to restrict available executables
- Use `allowed_paths` to restrict filesystem access

---

## 6. Variable Interpolation

All string fields support `{{VARIABLE}}` placeholders resolved at runtime:

```yaml
http:
  url_template: "https://{{CONTEXT.namespace}}.internal/api/v1/{{resource}}"
  headers:
    X-User: "{{CONTEXT.user_id}}"
    X-Request-Id: "{{request_id}}"
```

Resolution order:
1. **Tool parameters** — values passed at call time
2. **CONTEXT.*** — shared execution context (`user_id`, `namespace`, `request_id`, etc.)
3. **Environment variables** — `os.environ`
4. Unresolved placeholders are left as-is (e.g., `{{unknown}}` stays `"{{unknown}}"`)

---

## 7. Schema Validation

Each file is validated on load:

- Required top-level fields (`name`, `description`, `type`)
- Type-specific config sections present (`http` or `shell`)
- Parameter types are valid JSON Schema types
- File format is valid YAML or JSON

Invalid files are logged as warnings and skipped — other tools continue loading.

---

## 8. File Discovery

Tools are loaded from `TOOLS_DECLARATIVE_DIR` (default: `./tools_declarative/`):

```bash
TOOLS_DECLARATIVE_DIR=/etc/rag/tools python -m proxy.app.main
```

Files with `.yaml`, `.yml`, or `.json` extensions are loaded. Subdirectories are searched recursively.

### Production Directory Layout

```
tools_declarative/
├── monitoring/
│   ├── check_service.yaml
│   ├── disk_usage.yaml
│   └── tail_logs.yaml
├── external_apis/
│   ├── slack_notify.json
│   └── pagerduty_incident.yaml
└── db_queries/
    └── psql_query.yaml
```

---

## 9. JSON Format

All the above examples also work in JSON:

```json
{
  "name": "check_service",
  "description": "Check service health",
  "category": "monitoring",
  "type": "http",
  "parameters": [
    {
      "name": "service_name",
      "type": "string",
      "description": "Service to check",
      "required": true
    }
  ],
  "http": {
    "method": "GET",
    "url_template": "https://{{service_name}}.internal/health",
    "allowed_hosts": ["*.internal"]
  }
}
```

---

## 10. Related Documents

- [Python SDK Guide](agentic-tools-sdk.md) — `@tool` decorator and `ToolBuilder`
- [OpenAPI Discovery Guide](agentic-tools-openapi.md) — Auto-discover tools from OpenAPI specs
- [ADR-009: Agentic Tools Expansion Architecture](../adr/ADR-009-agentic-tools-expansion.md)
