# Block I. Knowledge Base Management and Agentic Tools (FR-104 — FR-120)

---

## FR-104. Multiple knowledge bases

**Description:**
The system supports multiple isolated knowledge bases (KBs). Each KB is a
separate collection in Qdrant with its own metadata in SQLite.

Each KB has access settings (roles, departments). Search takes into account
the current user's ACL.

**Acceptance criteria:**

1. Creating a KB — a new collection in Qdrant + a record in SQLite
2. A query to a specific KB — search only within its collection
3. Deleting a KB — the collection is deleted from Qdrant + the record from SQLite

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR104MultipleKBs`)
**Priority:** HIGH
**Reference:** admin_kb.py

---

## FR-105. Admin KB API ✅

**Description:**
RESTful API for managing knowledge bases:

- `POST /v1/admin/kb` — create a KB
- `GET /v1/admin/kb` — list KBs
- `GET /v1/admin/kb/{id}` — KB details
- `DELETE /v1/admin/kb/{id}` — delete a KB
- `POST /v1/admin/kb/{id}/reindex` — reindexing

**Acceptance criteria:**

1. CRUD operations work
2. Reindex triggers ETL for the specified KB
3. Only admin can manage KBs

**Status:** ✅ Confirmed (`proxy/app/api/admin_kb.py`)
**Priority:** HIGH
**Reference:** admin_kb.py

---

## FR-106. Auto-provisioning collections ✅

**Description:**
At proxy startup, the default collection is created automatically if it does not
exist. This allows working "out of the box" without manual initialization.

**Acceptance criteria:**

1. First startup — the collection is created automatically
2. Subsequent startup — the collection already exists, skipped
3. Log: "Qdrant collection 'X' created with indexes"

**Status:** ✅ Confirmed (`proxy/app/main.py:138`)
**Priority:** HIGH
**Reference:** main.py

---

## FR-107. Task tracking (ETL tasks)

**Description:**
The system tracks the status of ETL tasks: pending, running, completed, failed.
Each task has progress (%), start_time, end_time, error_message.

**Acceptance criteria:**

1. POST `/v1/admin/kb/{id}/reindex` — creates a task with pending status
2. GET `/v1/admin/tasks/{id}` — returns status and progress
3. Task completed — status=completed, progress=100%

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR107TaskTracking`)
**Priority:** HIGH
**Reference:** admin_kb.py

---

## FR-108. Configuration validation

**Description:**
At startup, the system checks all required settings:

- QDRANT_HOST — required
- LLM_ENDPOINT — required
- LLM_MODEL_NAME — required
- NEO4J_URI — required if GRAPH_ENABLED=true

Missing settings — warning in the log, degraded mode.

**Acceptance criteria:**

1. QDRANT_HOST missing — warning, degraded mode
2. All settings present — startup succeeds
3. Log: "Configuration validated" or "Missing required setting: X"

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR108ConfigValidation`)
**Priority:** HIGH
**Reference:** config_validator.py

---

## FR-109. Enhanced health checks

**Description:**
The `/v1/health` health check returns a detailed status:

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

**Acceptance criteria:**

1. The response contains all components
2. Latency for each component
3. Vector counts in collections

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR109EnhancedHealth`)
**Priority:** HIGH
**Reference:** health.py

---

## FR-111. Tool SDK — @tool decorator

**Description:**
Developers can create tools using the `@tool` decorator:

```python
@tool (description = "Search Confluence pages")
def search_confluence (query: str, space: str = "DEFAULT") -> list [dict]:
  ...
```

The JSON Schema is generated automatically from type hints.

**Acceptance criteria:**

1. The `@tool` decorator — the function is registered as a tool
2. The JSON Schema is generated from type hints
3. The tool is available via `/v1/tools`

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR111ToolDecorator`)
**Priority:** HIGH
**Reference:** ADR-009

---

## FR-112. ToolBuilder pattern

**Description:**
An alternative way to create tools via the Builder pattern:

```python
tool = (
  ToolBuilder ("search_jira").description ("Search Jira issues").param ("query", str, required = True).param ("project",
                                                                                                              str,
                                                                                                              default = "ALL").handler (
    my_handler).build ())
```

**Acceptance criteria:**

1. ToolBuilder creates a valid ToolDefinition
2. The JSON Schema matches the defined parameters
3. The handler is invoked on a tool call

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR112ToolBuilder`)
**Priority:** HIGH
**Reference:** ADR-009

---

## FR-113. ToolContext injection

**Description:**
When a tool is invoked, a ToolContext is created automatically:

- user_id — user ID
- user_role — user role
- request_id — request ID
- shared_state — shared state between tools
- streaming — streaming mode flag

**Acceptance criteria:**

1. The handler receives the ToolContext as the first argument
2. The ToolContext contains user_id, user_role, request_id
3. shared_state is available between sequential tool calls

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR113ToolContext`)
**Priority:** HIGH
**Reference:** ADR-009 2.3.2

---

## FR-114. Built-in tools (Confluence, Jira, GitLab)

**Description:**
The system ships with built-in tools:

- `confluence_search` — Confluence search
- `jira_search` — Jira search
- `gitlab_search` — GitLab search

The tools call the live APIs of these systems.

**Acceptance criteria:**

1. Tools are registered at startup
2. A tool call — invokes the real API
3. The result is returned in ToolResult format

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR114BuiltinTools`)
**Priority:** HIGH
**Reference:** ADR-009

---

## FR-115. Tool input validation

**Description:**
The input data of each tool is validated against the JSON Schema before invocation.
Invalid data — an error with a description, the handler is not invoked.

**Acceptance criteria:**

1. Valid data — the handler is invoked
2. Invalid data — 400 with an error description
3. Missing required parameters — 400

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR115InputValidation`)
**Priority:** HIGH
**Reference:** ADR-009

---

## FR-116. Declarative tools (YAML/JSON)

**Description:**
Tools can be defined declaratively in YAML/JSON files:

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

**Acceptance criteria:**

1. A YAML file in the directory — the tool is registered at startup
2. The HTTP call is executed with parameters from the YAML
3. A shell tool is executed with whitelist validation

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR116DeclarativeTools`)
**Priority:** HIGH
**Reference:** ADR-009 2.3.3

---

## FR-117. OpenAPI auto-discovery

**Description:**
The system automatically creates tools from OpenAPI/Swagger specs:

- AUTO mode: all endpoints → tools
- LLM_DRIVEN mode: the LLM selects relevant endpoints

**Acceptance criteria:**

1. An OpenAPI spec URL — all endpoints are created as tools
2. LLM-driven mode — the LLM filters endpoints
3. Tools are available via `/v1/tools`

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR117OpenAPIDiscovery`)
**Priority:** HIGH
**Reference:** ADR-009 2.3.4

---

## FR-118. Tool visibility by role

**Description:**
Tools are filtered by user role:

- Admin — sees all tools
- Expert — sees all except admin-only
- User — sees public tools
- Read_only — sees only read-only tools

**Acceptance criteria:**

1. GET `/v1/tools` with role=admin — all tools
2. GET `/v1/tools` with role=user — only public ones
3. A tool with visibility=admin — not visible to a regular user

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR118ToolVisibility`)
**Priority:** HIGH
**Reference:** ADR-009 2.3.7

---

## FR-119. Tool metrics (Prometheus)

**Description:**
Each tool call logs metrics:

- `rag_tool_calls_total` — number of calls
- `rag_tool_duration_seconds` — latency
- `rag_tool_active` — number of active calls
- `rag_tool_retries_total` — number of retries
- `rag_tool_input_bytes` / `rag_tool_output_bytes` — data size

**Acceptance criteria:**

1. All 6 metrics are present on `/metrics`
2. After a tool call — the metrics are updated
3. Labels: tool_name, status

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR119ToolMetrics`)
**Priority:** HIGH
**Reference:** ADR-009 2.3.8

---

## FR-120. Tool audit logging

**Description:**
Each tool call is logged to the audit log:

- tool_name, user_id, request_id, timestamp
- input params (SHA-256 hashed for security)
- output (SHA-256 hashed)
- duration_ms, status

**Acceptance criteria:**

1. The audit log contains a record for each tool call
2. Params are hashed (not in plain text)
3. Secrets are masked

**Status:** ✅ Confirmed (`tests/proxy/test_tools_kb.py::TestFR120ToolAudit`)
**Priority:** HIGH
**Reference:** ADR-009 2.3.9
