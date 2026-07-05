# Agentic Tools Expansion — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development.

**Goal:** Expand the tool system from 3 built-in synchronous tools to a multi-provider, async-first, declarative, OpenAPI-discoverable, parallel-orchestrated platform with RBAC, metrics, and audit.

**Architecture:** A new `proxy/app/tools/` subpackage with layered modules: zero-dependency foundation (`definition.py`, `errors.py`), provider-based registry (`registry.py`), three provider types (SDK, declarative, OpenAPI), orchestration layer (`orchestrator.py`), and cross-cutting infrastructure (`security.py`, `metrics.py`, `audit.py`). The existing `proxy/app/tools.py` becomes a deprecation shim.

**Tech Stack:** Python 3.12+ dataclasses, `typing.get_type_hints`, `asyncio.gather` + `asyncio.Semaphore`, `pyyaml`, `jsonschema`, `prometheus_client`, `aiohttp`, FastAPI.

## Global Constraints
- Backward-compatible: `proxy.app.tools.ToolRegistry` → re-export shim
- All existing 3 tools continue working
- Air-gapped first, graceful degradation
- TDD: every task writes failing test first

---

### Task 1: `definition.py` — Unified Data Models

**Files:** Create `proxy/app/tools/definition.py`; Create `tests/proxy/tools/__init__.py`; Create `tests/proxy/tools/test_definition.py`

**Dependencies:** None (zero internal imports)

**Coverage:** AC-1 (unified ToolDefinition), AC-2 (backward compat)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_definition.py`
```python
# Tests: ToolVisibility enum, ToolParam.to_json_schema_property() for str/int/enum/array,
# ToolDefinition.to_openai_format() with required/optional params,
# ToolResult.status property, RetryPolicy defaults.
# Expected: ~14 tests covering all dataclasses and format methods.
```

- [ ] Step 2: Verify failure: `python -m pytest tests/proxy/tools/test_definition.py -v` → ModuleNotFoundError

- [ ] Step 3: Implement `proxy/app/tools/definition.py`
```python
# ToolVisibility(str, Enum): PUBLIC="public", ADMIN="admin", EXPERT="expert", USER="user"
# ToolParam(name, type, description, required, default=_UNSET, enum, items_type)
#   .to_json_schema_property() → {"type": ..., "description": ...}
# RetryPolicy(max_retries=3, backoff="exponential", initial_delay_seconds=1.0, jitter=True)
# ToolDefinition(name, description, parameters=list[ToolParam], handler, async_handler,
#   category="general", tags=[], version="1.0.0", visibility=PUBLIC,
#   timeout_seconds=30.0, retry_policy=None, depends_on=[], output_schema=None,
#   provider="sdk", metadata={})
#   .to_openai_format() → {"type":"function","function":{name,description,parameters:{type:"object",properties,required}}}
#   .to_anthropic_format() → {name,description,input_schema:{type:"object",properties,required}}
#   .to_json_schema() → {type:"object", properties, required}
# ToolResult(tool_name, tool_call_id="", content="", error=None, duration_ms=0, retry_count=0)
#   .status → "success"|"error"
#   .name → tool_name (backward compat alias)
# ToolCall(id, name, arguments={})
# ToolErrorBase(Exception): tool_name, tool_call_id, retryable=False
```
*Full implementation: see ADR §2.3.1*

- [ ] Step 4: Run tests: `python -m pytest tests/proxy/tools/test_definition.py -v` → 14 passed

- [ ] Step 5: `git add proxy/app/tools/definition.py tests/proxy/tools/__init__.py tests/proxy/tools/test_definition.py && git commit -m "feat(tools): add definition.py with unified data models"`

---

### Task 2: `errors.py` — Error Taxonomy

**Files:** Create `proxy/app/tools/errors.py`; Create `tests/proxy/tools/test_errors.py`

**Dependencies:** Task 1 (`definition.py`), `proxy.app.exceptions.RAGError`

**Coverage:** AC-8 (error classification)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_errors.py`
```python
# Tests: ToolNotFoundError (retryable=False), ToolExecutionError (retryable=True),
# ToolTimeoutError (has timeout_seconds), ToolPermissionError (has required_visibility, user_role),
# ToolValidationError (has validation_errors list), ToolDependencyError (has dependency_name),
# classify_error() maps asyncio.TimeoutError→ToolTimeoutError, ValueError→ToolValidationError,
# PermissionError→ToolPermissionError, generic Exception→ToolExecutionError
# Expected: ~10 tests
```

- [ ] Step 2: Verify failure: `python -m pytest tests/proxy/tools/test_errors.py -v` → ModuleNotFoundError

- [ ] Step 3: Implement `proxy/app/tools/errors.py`
```python
# ToolError(RAGError): base with tool_name, tool_call_id, component="tools"
# ToolNotFoundError(ToolError): retryable=False
# ToolExecutionError(ToolError): retryable=True, has original_error
# ToolTimeoutError(ToolError): retryable=True, has timeout_seconds
# ToolPermissionError(ToolError): retryable=False, has required_visibility, user_role
# ToolValidationError(ToolError): retryable=False, has validation_errors=[]
# ToolDependencyError(ToolError): retryable=False, has dependency_name
# classify_error(tool_name, error, tool_call_id) → ToolError subclass via isinstance chain:
#   TimeoutError→ToolTimeoutError, (ValueError,TypeError,KeyError,AttributeError)→ToolValidationError,
#   PermissionError→ToolPermissionError, default→ToolExecutionError
```
*Full implementation: see ADR §2.3.6*

- [ ] Step 4: Run tests: `python -m pytest tests/proxy/tools/test_errors.py -v` → 10 passed

- [ ] Step 5: `git add proxy/app/tools/errors.py tests/proxy/tools/test_errors.py && git commit -m "feat(tools): add errors.py with error taxonomy"`

---

### Task 3: `__init__.py` and `tools.py` Deprecation Shim

**Files:** Create `proxy/app/tools/__init__.py`; Modify `proxy/app/tools.py`; Create `tests/proxy/tools/test_backward_compat.py`

**Dependencies:** Tasks 1, 2

**Coverage:** AC-2 (backward compat), AC-10 (old imports still work)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_backward_compat.py`
```python
# Test 1: Import from proxy.app.tools (old path) still works but emits DeprecationWarning
# Test 2: Import from proxy.app.tools.definition (new path) works
# Test 3: format_tools_for_llm still works with old ToolDefinition
# Test 4: get_tool_registry() returns a registry with 3 built-in tools
```

- [ ] Step 2: Verify failure (new imports work, old `tools.py` still needs shim)

- [ ] Step 3: Implement
  - Create `proxy/app/tools/__init__.py` re-exporting from definition.py and errors.py
  - Add lazy `get_tool_registry()` that creates EnhancedToolRegistry (falls back to old ToolRegistry during migration)
  - Add `format_tools_for_llm()` that handles both old (`parameters_schema`) and new (`to_openai_format()`) ToolDefinition
  - Modify `proxy/app/tools.py`: replace entire content with deprecation shim that re-exports from `proxy.app.tools` package, emits DeprecationWarning on import, provides backward-compat `ToolRegistry` class alias, `execute_tool()`, `handle_function_call()` wrappers
*Full implementation: see ADR §5 ADR-008-5*

- [ ] Step 4: Run ALL existing tests: `python -m pytest tests/proxy/test_tools.py tests/proxy/tools/ -v` → all pass

- [ ] Step 5: `git add proxy/app/tools/__init__.py proxy/app/tools.py tests/proxy/tools/test_backward_compat.py && git commit -m "feat(tools): add __init__.py and tools.py deprecation shim"`

---

### Task 4: `registry.py` — Enhanced Registry with Provider Pattern

**Files:** Create `proxy/app/tools/registry.py`; Create `tests/proxy/tools/test_registry.py`

**Dependencies:** Tasks 1, 2

**Coverage:** AC-3 (multi-provider registry), AC-4 (tool filtering), AC-5 (LLM format export)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_registry.py`
```python
# Tests: register/get/unregister, list_tools with category/tags/provider/visibility filters,
# execute sync (success, not-found, missing-required), execute_async,
# get_tools_for_llm() returns OpenAI format, get_dependency_graph(),
# ToolProvider ABC, SDKProvider.discover() scans _sdk_registered_tools,
# visibility: admin sees all, user sees public+user, read_only sees public only
# Expected: ~15 tests
```

- [ ] Step 2: Verify failure

- [ ] Step 3: Implement `proxy/app/tools/registry.py`
```python
# ToolProvider(ABC): @abstractmethod discover()→list[ToolDef], @property provider_name→str,
#   async validate()→[], async reload()→discover()
# SDKProvider(ToolProvider): provider_name="sdk", discover() reads _sdk_registered_tools
# EnhancedToolRegistry:
#   ROLE_HIERARCHY = {admin:[public,admin,expert,user], expert:[public,expert,user], user:[public,user], read_only:[public]}
#   register(tool: ToolDef), unregister(name)→bool, get_tool(name)→ToolDef|None
#   list_tools(category=None, tags=None, visibility_filter=None, provider=None)→list[ToolDef]
#   get_all()→list[ToolDef] (backward compat)
#   discover(provider: ToolProvider)→list[ToolDef] (registers automatically)
#   reload_provider(provider_name)→list[ToolDef] (removes+re-discovers)
#   get_tools_for_llm(provider_type="openai", user_role=None)→list[dict]
#   execute(name, params, context=None)→ToolResult (sync, validates required params)
#   execute_async(name, params, context=None)→ToolResult (async, tries async_handler first, falls back to handler)
#   validate_tool(tool)→list[str] (checks name, description, handler, unique param names)
#   get_dependency_graph()→dict[str, list[str]]
```
*Full implementation: see ADR §2.3.2 registry, §3.1 API*

- [ ] Step 4: `python -m pytest tests/proxy/tools/test_registry.py -v` → 15 passed

- [ ] Step 5: `git add proxy/app/tools/registry.py tests/proxy/tools/test_registry.py && git commit -m "feat(tools): add registry.py with EnhancedToolRegistry"`

---

### Task 5: `sdk.py` — Python Tool SDK (Decorator + Builder)

**Files:** Create `proxy/app/tools/sdk.py`; Create `tests/proxy/tools/test_sdk.py`

**Dependencies:** Tasks 1, 4

**Coverage:** AC-6 (SDK decorator), AC-7 (ToolBuilder), AC-11 (JSON Schema auto-generation)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_sdk.py`
```python
# Tests: json_schema_from_func (str→string, int→integer, float→number, bool→boolean,
#   list[str]→array, Optional[X] omitted from required, default value→not required,
#   Annotated BaseModel→recursive, Union[X,None]→nullable)
# @tool decorator: registers in _sdk_registered_tools, uses docstring for description,
#   auto-derives name from func, generates params from type hints, supports async def,
#   tags/category/visibility passed through
# ToolBuilder: fluent API (with_description, with_param, with_handler,
#   with_async_handler, with_category, with_tags, with_timeout, with_visibility, build)
# ToolContext: get_state/set_state (cross-tool shared), stream_partial
# Expected: ~18 tests
```

- [ ] Step 2: Verify failure

- [ ] Step 3: Implement `proxy/app/tools/sdk.py`
```python
# _sdk_registered_tools: dict[str, ToolDefinition] = {}  # global SDK tool registry
# json_schema_from_func(func)→dict: uses inspect.signature() + typing.get_type_hints(),
#   _TYPE_MAP={str:"string",int:"integer",float:"number",bool:"boolean",list:"array",dict:"object"},
#   handles Optional[X], list[X], dict[str,X], Union[X,None]
# @tool(name=None, description=None, category, tags, version, timeout, retry_policy, visibility, depends_on):
#   reads type hints→ToolParam list, reads docstring→description,
#   detects async via asyncio.iscoroutinefunction, stores in _sdk_registered_tools
# ToolBuilder(name): fluent builder, build()→ToolDefinition
# ToolContext(user_id, user_role, request_id, tool_call_id, metrics):
#   get_state(key)→Any, set_state(key,value), stream_partial(data)
```
*Full implementation: see ADR §2.3.2*

- [ ] Step 4: `python -m pytest tests/proxy/tools/test_sdk.py -v` → 18 passed

- [ ] Step 5: `git add proxy/app/tools/sdk.py tests/proxy/tools/test_sdk.py && git commit -m "feat(tools): add sdk.py with @tool decorator and ToolBuilder"`

---

### Task 6: Migrate 3 Built-in Tools to Enhanced Registry

**Files:** Modify `proxy/app/tools/__init__.py`

**Dependencies:** Tasks 1-5

**Coverage:** AC-2 (all existing 3 tools continue working)

- [ ] Step 1: Verify existing tests still pass: `python -m pytest tests/proxy/test_tools.py -v`

- [ ] Step 2: Update `proxy/app/tools/__init__.py` — `get_tool_registry()` now:
  - Creates `EnhancedToolRegistry`
  - Calls `_register_builtin_tools()` which registers `search_documents`, `search_by_version`, `get_document_metadata` as new-style `ToolDefinition` with `ToolParam` lists
  - Each uses the same handler functions from legacy tools.py

- [ ] Step 3: Update `proxy/app/tools.py` shim's `get_tool_registry()` to delegate to `proxy.app.tools.get_tool_registry()`

- [ ] Step 4: Run comprehensive test suite:
```bash
python -m pytest tests/proxy/test_tools.py tests/proxy/tools/ -v
python -m pytest tests/proxy/test_orchestrator.py -v  # call_tools uses get_tool_registry()
```
→ All existing tests pass

- [ ] Step 5: `git add proxy/app/tools/__init__.py proxy/app/tools.py && git commit -m "feat(tools): migrate 3 built-in tools to EnhancedRegistry"`

---

### Task 7: `declarative.py` — YAML/JSON Declarative Tools

**Files:** Create `proxy/app/tools/declarative.py`; Create `tests/proxy/tools/test_declarative.py`

**Dependencies:** Tasks 1, 4

**Coverage:** AC-12 (declarative loading), AC-13 (shell safety)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_declarative.py`
```python
# Tests: DeclarativeToolLoader.load_file(yaml_path)→list[ToolDef] (parses http+shell tools),
#   _parse_tools rejects unknown type, shell without allowed_commands→None,
#   _interpolate_variables(template, params, env_vars, context)→str,
#   HTTP tool execution via mock aiohttp,
#   Shell tool blocks metacharacters in params,
#   DeclarativeProvider.discover() scans TOOLS_DECLARATIVE_DIR for *.yaml/*.yml/*.json
# Expected: ~9 tests
```

- [ ] Step 2: Verify failure

- [ ] Step 3: Implement `proxy/app/tools/declarative.py`
```python
# TOOLS_DECLARATIVE_DIR = os.getenv("TOOLS_DECLARATIVE_DIR", "./tools_declarative")
# _VAR_PATTERN = re.compile(r'\{\{(\w+(?:\.\w+)*)\}\}')
# _interpolate_variables(template, params, env_vars, context)→str
# DeclarativeToolSchema: class-level _SCHEMA dict for JSON Schema validation
# DeclarativeToolLoader: load_file(filepath)→list[ToolDef],
#   _parse_tools(tools_data)→list[ToolDef] (validates, converts each),
#   _parse_single(raw)→ToolDef|None (builds params, visibility, retry, handler)
# _make_http_handler(tool)→async handler: uses aiohttp, interpolates url/headers/body
# _make_shell_handler(tool)→sync handler: uses subprocess.run, checks allowed_commands,
#   blocks metacharacters (;&&|`$()) in param values
# DeclarativeProvider(ToolProvider): provider_name="declarative",
#   discover()→scans TOOLS_DECLARATIVE_DIR glob **/*.{yaml,yml,json}
```
*Full implementation: see ADR §2.3.3, §5 ADR-008-6*

- [ ] Step 4: `python -m pytest tests/proxy/tools/test_declarative.py -v` → 9 passed

- [ ] Step 5: `git add proxy/app/tools/declarative.py tests/proxy/tools/test_declarative.py && git commit -m "feat(tools): add declarative.py — YAML/JSON tool support"`

---

### Task 8: `openapi_discovery.py` — OpenAPI Auto-Discovery

**Files:** Create `proxy/app/tools/openapi_discovery.py`; Create `tests/proxy/tools/test_openapi_discovery.py`

**Dependencies:** Tasks 1, 4

**Coverage:** AC-14 (OpenAPI→tools), AC-15 (endpoint→ToolParam mapping)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_openapi_discovery.py`
```python
# Tests: OpenAPIDiscovery.discover(spec, AUTO)→4 tools from PetStore spec (listPets, createPet, getPetById, deletePet),
#   GET→category="search", POST→"action", DELETE→"action",
#   path params (petId) in ToolParam, query params mapped,
#   requestBody (JSON) mapped to ToolParam, include_tags/exclude_tags filtering,
#   all tools have provider="openapi",
#   OpenAPIProvider.discover() fetches spec via aiohttp, parses, sets async_handler
# Expected: ~10 tests
```

- [ ] Step 2: Verify failure

- [ ] Step 3: Implement `proxy/app/tools/openapi_discovery.py`
```python
# DiscoveryMode(str, Enum): AUTO="auto", LLM_DRIVEN="llm_driven"
# OpenAPIDiscovery:
#   discover(spec, mode=AUTO, include_tags, exclude_tags, default_visibility, base_url_override)→list[ToolDef]
#   _discover_auto()→iterates paths/{GET,POST,PUT,PATCH,DELETE}, filters by tags
#   _endpoint_to_tool(path, method, operation, base_url, vis)→ToolDef:
#     GET→category="search", others→"action"
#     tool_name=operationId or {method}_{path_slug}
#     description=summary or description
#     extracts parameters from path/query/header + requestBody (JSON)
#   _extract_parameters(operation)→list[ToolParam]
# _slugify_path("/pets/{petId}")→"pets_petId"
# _make_openapi_handler(tool)→async handler: aiohttp.request with path/query/body substitution
# OpenAPIProvider(ToolProvider): provider_name="openapi",
#   discover()→reads TOOLS_OPENAPI_SPECS config, fetches each spec, generates tools
```
*Full implementation: see ADR §2.3.4*

- [ ] Step 4: `python -m pytest tests/proxy/tools/test_openapi_discovery.py -v` → 10 passed

- [ ] Step 5: `git add proxy/app/tools/openapi_discovery.py tests/proxy/tools/test_openapi_discovery.py && git commit -m "feat(tools): add openapi_discovery.py — OpenAPI auto-discovery"`

---

### Task 9: `security.py`, `metrics.py`, `audit.py` — Cross-Cutting

**Files:** Create `proxy/app/tools/security.py`, `proxy/app/tools/metrics.py`, `proxy/app/tools/audit.py`; Create `tests/proxy/tools/test_security.py`, `tests/proxy/tools/test_metrics.py`, `tests/proxy/tools/test_audit.py`

**Dependencies:** Task 1

**Coverage:** AC-16 (RBAC visibility), AC-17 (Prometheus metrics), AC-18 (audit logging)

- [ ] Step 1: Write failing tests
```python
# test_security.py (~6 tests): ToolVisibilityFilter.filter(tools, "admin")→all 4,
#   filter(tools, "user")→public+user only, filter(tools, "read_only")→public only,
#   filter(tools, None)→public only, ToolInputSanitizer.sanitize→fills defaults,
#   sanitize missing required→raises ValueError, sanitize long string→truncated to 10k
# test_metrics.py (~3 tests): ToolMetrics() creates counters/histograms,
#   measure() context manager tracks duration, record_success/error/retry
# test_audit.py (~3 tests): ToolAuditLogger.log_tool_call() emits JSON,
#   success→logger.info, error/timeout→logger.warning, timestamp format ISO 8601
```

- [ ] Step 2: Verify failure

- [ ] Step 3: Implement
```python
# security.py:
#   ToolVisibilityFilter: ROLE_HIERARCHY dict, filter(tools, user_role)→list[ToolDef]
#   ToolInputSanitizer: MAX_STRING_LENGTH=10000, MAX_ARRAY_LENGTH=1000,
#     sanitize(tool, params)→dict (fills defaults, truncates oversized, raises on missing required)
#
# metrics.py (graceful degradation when prometheus_client not installed):
#   Counter: tool_calls_total{tool_name, category, status}
#   Histogram: tool_call_duration_seconds{tool_name, category}, tool_call_input_bytes, tool_call_output_bytes
#   Gauge: tool_call_active{tool_name}
#   Counter: tool_call_retries_total{tool_name}
#   ToolMetrics: measure(tool_name, category)→context manager, record_success, record_error, record_retry
#
# audit.py:
#   ToolAuditLogger: log_tool_call(tool_name, tool_category, tool_version, user_id, user_role,
#     request_id, tool_call_id, params_hash, result_hash, duration_ms, status,
#     error_type, retry_count, input_bytes, output_bytes)
#     → emits JSON log entry at INFO (success) or WARNING (error/timeout)
```
*Full implementation: see ADR §2.3.7-2.3.9*

- [ ] Step 4: `python -m pytest tests/proxy/tools/test_security.py tests/proxy/tools/test_metrics.py tests/proxy/tools/test_audit.py -v` → 12 passed

- [ ] Step 5: `git add proxy/app/tools/security.py proxy/app/tools/metrics.py proxy/app/tools/audit.py tests/proxy/tools/test_security.py tests/proxy/tools/test_metrics.py tests/proxy/tools/test_audit.py && git commit -m "feat(tools): add security, metrics, audit cross-cutting modules"`

---

### Task 10: `tools/orchestrator.py` — Parallel and Streaming Execution

**Files:** Create `proxy/app/tools/orchestrator.py`; Create `tests/proxy/tools/test_orchestrator.py`

**Dependencies:** Tasks 1, 4, 9

**Coverage:** AC-19 (parallel execution), AC-20 (dependency-aware ordering), AC-21 (graceful failure)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_orchestrator.py`
```python
# Tests: ParallelExecutor.execute_all() runs 2 independent tools in parallel→both succeed,
#   failed tool doesn't crash other parallel tools (1 success, 1 error),
#   dependency ordering: get_meta(depends_on=search) runs after search,
#   ToolComposer.chain(["a","b"], mapper)→ChainPattern,
#   ToolComposer.fan_out("tool", [inputs])→FanOutPattern,
#   ToolComposer.conditional(lambda, true, false)→ConditionalPattern
# Expected: ~8 tests
```

- [ ] Step 2: Verify failure

- [ ] Step 3: Implement `proxy/app/tools/orchestrator.py`
```python
# ParallelExecutor(max_concurrency=10, timeout=120.0):
#   execute_all(tool_calls, registry, context)→list[ToolResult]:
#     1. Build dependency DAG (topological sort on depends_on)
#     2. Group into dependency levels
#     3. Within each level, asyncio.gather(*coroutines) with semaphore
#     4. Each coroutine: validate visibility, sanitize inputs, execute, handle errors
#     5. Collect results preserving call order
#   execute_single(tool_call, registry, context)→ToolResult:
#     Retry logic: tries up to retry_policy.max_retries with backoff
#     Catches exceptions→classify_error(), applies RetryPolicy
#     Records metrics, audit log
# StreamingExecutor: execute_streaming(tool_call, registry, context)→AsyncIterator[str]
# ToolComposer:
#   chain(tools, input_mapper)→ChainPattern(steps, input_mapper)
#   fan_out(tool_name, inputs, merge_strategy="concat")→FanOutPattern
#   fan_in(tool_names, input_params, merge_strategy="concat")→FanInPattern
#   conditional(condition, true_tool, false_tool)→ConditionalPattern
# CompositionPattern = ChainPattern | FanOutPattern | FanInPattern | ConditionalPattern
```
*Full implementation: see ADR §2.3.5, §4.3 dependency graph*

- [ ] Step 4: `python -m pytest tests/proxy/tools/test_orchestrator.py -v` → 8 passed

- [ ] Step 5: `git add proxy/app/tools/orchestrator.py tests/proxy/tools/test_orchestrator.py && git commit -m "feat(tools): add orchestrator.py — parallel streaming execution"`

### Task 11: `config.py` — Tool System Configuration

**Files:** Modify `proxy/app/config.py`; Create `tests/proxy/tools/test_config.py`

**Dependencies:** Task 1

**Coverage:** AC-22 (tool system configuration)

- [ ] Step 1: Write failing test `tests/proxy/tools/test_config.py`
```python
# Tests: TOOLS_PARALLEL_EXECUTION default=True, TOOLS_MAX_CONCURRENCY default=10,
#   TOOLS_DECLARATIVE_DIR default="./tools_declarative",
#   TOOLS_OPENAPI_SPECS default=[],
#   env var overrides work
```

- [ ] Step 2: Verify failure (config vars not yet defined)

- [ ] Step 3: Add to `proxy/app/config.py` (after line 239):
```python
# ============ Agentic Tools Expansion ============
TOOLS_PARALLEL_EXECUTION = os.getenv("TOOLS_PARALLEL_EXECUTION", "true").lower() == "true"
TOOLS_MAX_CONCURRENCY = int(os.getenv("TOOLS_MAX_CONCURRENCY", "10"))
TOOLS_DECLARATIVE_DIR = os.getenv("TOOLS_DECLARATIVE_DIR", "./tools_declarative")
TOOLS_OPENAPI_SPECS_RAW = os.getenv("TOOLS_OPENAPI_SPECS", "[]")
try:
    TOOLS_OPENAPI_SPECS: list[dict] = __import__("json").loads(TOOLS_OPENAPI_SPECS_RAW)
except Exception:
    TOOLS_OPENAPI_SPECS = []
```

Also create `proxy/app/tools/config.py` as a re-export proxy:
```python
# proxy/app/tools/config.py — thin re-export from proxy.app.config
from proxy.app.config import (
    TOOLS_PARALLEL_EXECUTION,
    TOOLS_MAX_CONCURRENCY,
    TOOLS_DECLARATIVE_DIR,
    TOOLS_OPENAPI_SPECS,
)
```

- [ ] Step 4: `python -m pytest tests/proxy/tools/test_config.py -v` → passed

- [ ] Step 5: `git add proxy/app/config.py proxy/app/tools/config.py tests/proxy/tools/test_config.py && git commit -m "feat(tools): add tool system configuration (Task 11)"`

---

### Task 12: Update `orchestrator.py` — Parallel `call_tools`

**Files:** Modify `proxy/app/orchestrator.py`; Modify `tests/proxy/test_orchestrator.py`

**Dependencies:** Tasks 4, 6, 10, 11

**Coverage:** AC-23 (LangGraph call_tools uses ParallelExecutor)

- [ ] Step 1: Write failing test in `tests/proxy/test_orchestrator.py`
```python
# Test: call_tools_async with 2 independent tool calls→both executed
# Test: call_tools_async preserves backward-compat synchronous path
# Test: tool_loop_count increments correctly
```

- [ ] Step 2: Verify failure

- [ ] Step 3: In `proxy/app/orchestrator.py`:
  - Replace `def call_tools(state)` with `async def call_tools_async(state)`
  - Import: `from proxy.app.tools.orchestrator import ParallelExecutor`
  - Import: `from proxy.app.tools.sdk import ToolContext`
  - Import: `from proxy.app.tools.definition import ToolCall`
  - Implementation (exact code as in ADR §2.3.5 orchestrator integration):
```python
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
    calls = [ToolCall(id=tc.get("id", ""), name=tc.get("function", {}).get("name", ""),
                     arguments=json.loads(tc.get("function", {}).get("arguments", "{}"))
                     if isinstance(tc.get("function", {}).get("arguments", ""), str)
                     else tc.get("function", {}).get("arguments", {}))
             for tc in tool_calls]
    executor = ParallelExecutor(max_concurrency=TOOLS_MAX_CONCURRENCY)
    results = await executor.execute_all(calls, registry, context)
    tool_results = [
        {"tool_call_id": r.tool_call_id, "name": r.tool_name,
         "content": r.content, "error": r.error}
        for r in results
    ]
    return {"tool_results": tool_results, "tool_loop_count": tool_loop_count + 1, "tool_calls": []}
```
  - Keep `def call_tools(state)` for backward compat (synchronous fallback), delegate to async via `asyncio.run()` when LangGraph is disabled
  - Update graph builder to use `call_tools_async` as the node function

- [ ] Step 4: `python -m pytest tests/proxy/test_orchestrator.py -v` → all pass

- [ ] Step 5: `git add proxy/app/orchestrator.py tests/proxy/test_orchestrator.py && git commit -m "feat(tools): upgrade orchestrator call_tools to async parallel execution"`

---

### Task 13: FastAPI Endpoints — `GET /v1/tools`, `GET /v1/tools/{name}`

**Files:** Modify `proxy/app/main.py`; Modify `tests/proxy/test_main.py`

**Dependencies:** Tasks 4, 6

**Coverage:** AC-24 (tool discovery API), AC-25 (tool detail API), AC-26 (RBAC filtering on endpoints)

- [ ] Step 1: Write failing test in `tests/proxy/test_main.py`
```python
# Test: GET /v1/tools returns {"count": N, "tools": [...]} with correct fields
# Test: GET /v1/tools?category=search filters correctly
# Test: GET /v1/tools?tag=live filters by tag
# Test: GET /v1/tools/{name} returns tool detail with all fields
# Test: GET /v1/tools/{name} returns 404 for unknown tool
# Test: Unauthenticated user sees only public tools; expert sees public+expert+user
```

- [ ] Step 2: Verify failure (endpoints don't exist yet)

- [ ] Step 3: Add to `proxy/app/main.py` (~after line 1206 or before feedback endpoint):
```python
from proxy.app.tools import get_tool_registry
from proxy.app.tools.definition import ToolDefinition as NewToolDef
from proxy.app.tools.security import ToolVisibilityFilter

@app.get("/v1/tools")
async def list_tools(
    category: str | None = None,
    tag: str | None = None,
    provider: str | None = None,
    user: UserContext = Depends(get_auth_context),
):
    """List available tools with optional filters. RBAC: visibility-filtered by user role."""
    registry = get_tool_registry()
    user_role = user.role if hasattr(user, 'role') else None
    tags = [tag] if tag else None
    tools = registry.list_tools(category=category, tags=tags, provider=provider,
                                visibility_filter=user_role)
    return {
        "count": len(tools),
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "tags": t.tags,
                "version": t.version,
                "parameters": t.to_json_schema(),
                "provider": t.provider,
            }
            for t in tools
        ],
    }

@app.get("/v1/tools/{name}")
async def get_tool(
    name: str,
    user: UserContext = Depends(get_auth_context),
):
    """Get a single tool's details by name. Never exposes handler code."""
    registry = get_tool_registry()
    tool = registry.get_tool(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    # RBAC visibility check
    user_role = user.role if hasattr(user, 'role') else None
    visible = ToolVisibilityFilter.filter([tool], user_role)
    if not visible:
        raise HTTPException(status_code=403, detail="Tool not visible to your role")
    return {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "tags": tool.tags,
        "version": tool.version,
        "visibility": tool.visibility.value,
        "timeout_seconds": tool.timeout_seconds,
        "parameters": tool.to_json_schema(),
        "provider": tool.provider,
        "depends_on": tool.depends_on,
    }
```

- [ ] Step 4: `python -m pytest tests/proxy/test_main.py -v -k tools` → all pass

- [ ] Step 5: `git add proxy/app/main.py tests/proxy/test_main.py && git commit -m "feat(tools): add GET /v1/tools and GET /v1/tools/{name} endpoints"`

---

### Task 14: Consolidate `provider_adapter.py`

**Files:** Modify `proxy/app/provider_adapter.py`

**Dependencies:** Task 1

**Coverage:** AC-27 (single ToolDefinition source of truth)

- [ ] Step 1: Update imports in `proxy/app/provider_adapter.py`:

```python
# Remove local ToolDefinition, ToolCall, ToolResult dataclasses (lines 67-93)
# Add import:
from proxy.app.tools.definition import ToolDefinition, ToolCall, ToolResult
```

- [ ] Step 2: Update all internal usages:
  - `ToolDefinition` now has `name`, `description`, `parameters` (list[ToolParam])
  - LLM format conversion uses `t.to_openai_format()`, `t.to_anthropic_format()`
  - The `translate_request()` methods that build `"type":"function"...` dicts can use `t.to_openai_format()` instead of manual dict construction:
```python
# Old (lines 148-158):
payload["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
# New:
payload["tools"] = [t.to_openai_format() for t in tools]
```
  - `ToolResult` fields: `tool_call_id`→`tool_call_id`, `name`→`tool_name` (keep backward compat `.name` property)
  - `ToolCall` stays the same

- [ ] Step 3: Add backward-compat alias at the bottom:
```python
# Keep old import working
class _DeprecatedToolDef(ToolDefinition):
    pass
```

- [ ] Step 4: Run provider_adapter tests: `python -m pytest tests/proxy/test_llm_router.py -v` → all pass

- [ ] Step 5: `git add proxy/app/provider_adapter.py && git commit -m "feat(tools): consolidate provider_adapter ToolDefinition imports"`

---

### Task 15: Tool Discovery on Startup + Integration

**Files:** Modify `proxy/app/main.py` (startup event); Modify `proxy/app/tools/__init__.py`

**Dependencies:** Tasks 6, 7, 8, 11

**Coverage:** AC-28 (startup tool discovery)

- [ ] Step 1: Add startup event to `proxy/app/main.py`:
```python
@app.on_event("startup")
async def discover_tools_on_startup():
    """Discover and register tools from all providers on application startup."""
    registry = get_tool_registry()
    providers_to_load = []
    # SDK tools are auto-registered by @tool decorator imports
    # Declarative
    if os.path.isdir(TOOLS_DECLARATIVE_DIR):
        from proxy.app.tools.declarative import DeclarativeProvider
        providers_to_load.append(DeclarativeProvider())
    # OpenAPI
    if TOOLS_OPENAPI_SPECS:
        from proxy.app.tools.openapi_discovery import OpenAPIProvider
        providers_to_load.append(OpenAPIProvider())
    for provider in providers_to_load:
        try:
            tools = await registry.discover(provider)
            logger.info("Startup: loaded %d tools from provider '%s'", len(tools), provider.provider_name)
        except Exception as e:
            logger.warning("Startup: failed to load tools from provider '%s': %s", provider.provider_name, e)
```

- [ ] Step 2: Integration test: start app, hit `/v1/tools`, verify all providers loaded
```bash
python -m pytest tests/integration/ -v -k tools
```

- [ ] Step 3: `git add proxy/app/main.py proxy/app/tools/__init__.py && git commit -m "feat(tools): add tool discovery on startup"`

---

### Task 16: Run Full Test Suite — Verify Zero Regression

**Files:** None (verification only)

**Dependencies:** Tasks 1-15

**Coverage:** All acceptance criteria

- [ ] Step 1: Run complete proxy test suite:
```bash
python -m pytest tests/proxy/ -v --tb=short 2>&1 | tail -30
# Expected: ALL 282+ tests pass, plus ~80 new tool tests
```

- [ ] Step 2: Run integration tests:
```bash
python -m pytest tests/integration/ -v --tb=short 2>&1 | tail -20
# Expected: ALL 56 tests pass
```

- [ ] Step 3: Run ETL tests (should be unaffected):
```bash
python -m pytest tests/etl/ -v --tb=short 2>&1 | tail -20
# Expected: ALL 121 tests pass
```

- [ ] Step 4: Run full test suite:
```bash
python -m pytest tests/ -v 2>&1 | tail -5
# Expected: 1400+ collected, 1400+ passed, 0 failed
```

- [ ] Step 5: If any test fails, fix and re-run. Do not proceed until 100% pass.

- [ ] Step 6: Commit any fixes. No feature commit needed (verification gate).

---

### Task 17: Documentation + Polish

**Files:** Create `docs/en/guides/tool-sdk-guide.md`; Create `docs/en/guides/declarative-tools-reference.md`; Create `docs/en/guides/openapi-discovery-guide.md`; Modify `AGENTS.md`

**Dependencies:** Tasks 1-16 (all implementation complete)

**Coverage:** AC-29 (developer documentation)

- [ ] Step 1: Create `docs/en/guides/tool-sdk-guide.md` — SDK usage guide with:
  - `@tool` decorator examples (sync and async)
  - `ToolBuilder` fluent API examples
  - `ToolContext` usage (shared state, streaming)
  - `json_schema_from_func` reference table
  - Migration guide from old `ToolRegistry.register()` to new `@tool`

- [ ] Step 2: Create `docs/en/guides/declarative-tools-reference.md` — Reference with:
  - YAML schema reference
  - HTTP tool example (Jira search)
  - Shell tool example with safety constraints
  - Variable interpolation reference (`{{ENV}}`, `{{param}}`, `{{CONTEXT.key}}`)
  - Validation rules and error messages

- [ ] Step 3: Create `docs/en/guides/openapi-discovery-guide.md` — Guide with:
  - Configuration (`TOOLS_OPENAPI_SPECS`)
  - AUTO mode vs LLM_DRIVEN mode
  - Endpoint→tool mapping rules
  - Tag filtering, visibility overrides
  - Troubleshooting (spec fetch failures, partial registration)

- [ ] Step 4: Update `AGENTS.md` — Add to "Key Architectural Principles":
```markdown
8. **Pluggable tool system** — Multi-provider tool registry (SDK, declarative YAML/JSON, OpenAPI auto-discovery)
   with parallel orchestration, RBAC visibility filtering, Prometheus metrics, and structured audit logging.
   Managed via `proxy/app/tools/` subpackage.
```
  - Update "Project Structure" with `tools/` subpackage
  - Update "Tech Stack" with new dependencies (pyyaml, jsonschema)

- [ ] Step 5: `git add docs/en/guides/ AGENTS.md && git commit -m "docs: add tool SDK, declarative, and OpenAPI discovery guides"`

---

## Execution Order

The 17 tasks follow the ADR's 8-phase sequence, ordered by dependency and risk:

| Order | Task | Phase | Rationale |
|-------|------|-------|-----------|
| 1 | Task 1: `definition.py` | Phase 1: Foundation | Zero dependencies. All other modules depend on these data models. Must be first. |
| 2 | Task 2: `errors.py` | Phase 1: Foundation | Depends only on Task 1 + existing `RAGError`. Needed before registry. |
| 3 | Task 3: `__init__.py` + shim | Phase 1: Foundation | Depends on Tasks 1-2. Sets up the package. Enables backward compat from day 0. |
| 4 | Task 4: `registry.py` | Phase 2: Registry | Depends on Tasks 1-2. Core infrastructure. Without it, no tool execution. |
| 5 | Task 5: `sdk.py` | Phase 3: SDK | Depends on Tasks 1, 4. SDK provides decorator that feeds into registry. |
| 6 | Task 6: Migrate built-in tools | Phase 2: Registry | Depends on Tasks 1-5. Gates backward compat — must pass all existing tests. |
| 7 | Task 7: `declarative.py` | Phase 4: Declarative | Depends on Tasks 1, 4. Independent provider. Low risk of breaking existing code. |
| 8 | Task 8: `openapi_discovery.py` | Phase 5: OpenAPI | Depends on Tasks 1, 4. Independent provider. Low risk. |
| 9 | Task 9: `security.py` + `metrics.py` + `audit.py` | Phase 6: Cross-cutting | Depends on Task 1. Needed before orchestrator for instrumentation. |
| 10 | Task 10: `tools/orchestrator.py` | Phase 6: Orchestration | Depends on Tasks 1, 4, 9. High complexity, high risk. Must be tested thoroughly. |
| 11 | Task 11: `config.py` | Phase 6: Config | Depends on Task 1. Low risk, needed for orchestrator and providers. |
| 12 | Task 12: Update `orchestrator.py` | Phase 6: Integration | Depends on Tasks 4, 6, 10, 11. High risk — touches the LangGraph execution path. |
| 13 | Task 13: API endpoints | Phase 7: API | Depends on Tasks 4, 6. Medium risk. Exposes new endpoints. |
| 14 | Task 14: Consolidate `provider_adapter.py` | Phase 7: Consolidation | Depends on Task 1. Medium risk — changes LLM adapter internals. |
| 15 | Task 15: Startup discovery | Phase 7: Integration | Depends on Tasks 6, 7, 8, 11. Glue code, low risk. |
| 16 | Task 16: Full test suite | Phase 7: Verification | Depends on Tasks 1-15. Zero-risk verification gate. |
| 17 | Task 17: Documentation | Phase 8: Polish | Depends on Tasks 1-16. No code changes. |

**Parallelizable groups:**
- Tasks 7 + 8 can run in parallel after Task 4 (declarative and OpenAPI are independent)
- Tasks 9 can run in parallel with Tasks 7 + 8
- Tasks 11 can run in parallel with Tasks 7-10

**Total estimate:** 17-24 days for a senior developer (per ADR §7).

---

## Coverage Map

| Acceptance Criterion | Task IDs | Status |
|---------------------|----------|--------|
| AC-1: Unified ToolDefinition dataclass | 1 | Covered |
| AC-2: 3 existing tools continue working | 1, 3, 6, 16 | Covered |
| AC-3: Multi-provider registry (SDK, declarative, OpenAPI) | 4, 7, 8 | Covered |
| AC-4: Tool filtering (category, tags, provider, visibility) | 4 | Covered |
| AC-5: LLM format export (OpenAI + Anthropic) | 1, 4 | Covered |
| AC-6: `@tool` decorator with auto-schema | 5 | Covered |
| AC-7: `ToolBuilder` fluent API | 5 | Covered |
| AC-8: Error taxonomy with `classify_error()` | 2 | Covered |
| AC-9: Tool execution via registry (sync + async) | 4, 6 | Covered |
| AC-10: Backward-compatible import paths | 3 | Covered |
| AC-11: JSON Schema auto-generation from type hints | 5 | Covered |
| AC-12: YAML/JSON declarative tool loading | 7 | Covered |
| AC-13: Shell tool safety (allowed_commands, metacharacter blocking) | 7 | Covered |
| AC-14: OpenAPI spec → tool generation (AUTO mode) | 8 | Covered |
| AC-15: OpenAPI endpoint parameters → ToolParam mapping | 8 | Covered |
| AC-16: RBAC visibility filtering by user role | 4, 9, 13 | Covered |
| AC-17: Prometheus metrics for tool calls | 9 | Covered |
| AC-18: Structured audit logging (JSON) | 9 | Covered |
| AC-19: Parallel tool execution via `ParallelExecutor` | 10, 12 | Covered |
| AC-20: Dependency-aware execution ordering | 10, 12 | Covered |
| AC-21: Graceful individual tool failure (one failure ≠ all failure) | 10, 12 | Covered |
| AC-22: Tool system configuration (env vars) | 11 | Covered |
| AC-23: LangGraph `call_tools` uses `ParallelExecutor` | 12 | Covered |
| AC-24: `GET /v1/tools` endpoint with filters | 13 | Covered |
| AC-25: `GET /v1/tools/{name}` endpoint | 13 | Covered |
| AC-26: Endpoint RBAC (visibility-filtered response) | 13 | Covered |
| AC-27: Single canonical `ToolDefinition` (consolidated) | 1, 14 | Covered |
| AC-28: Tool discovery on startup (all providers) | 15 | Covered |
| AC-29: Developer documentation (SDK, declarative, OpenAPI) | 17 | Covered |

**All 29 acceptance criteria covered. No gaps.**

---

## Risks and Mitigations

| Risk | Impact | Mitigation | Task |
|------|--------|------------|------|
| **Circular imports** with `definition.py` | HIGH — app won't start | `definition.py` has zero internal imports. All format methods are on `ToolDefinition` itself. Validated by Task 1 being first and independent. | 1 |
| **Existing tests break** due to ToolDefinition API change | HIGH — regression | Deprecation shim preserves 100% backward compat (Task 3). All old tests run as regression gate (Task 16). | 3, 16 |
| **Shell tool security breach** | HIGH — RCE | Mandatory `allowed_commands` whitelist (Task 7). Shell metacharacter blocking in parameter values. `visibility: admin` enforced. | 7 |
| **OpenAPI spec fetch failures** | MEDIUM — tools missing | Graceful degradation: failed specs log warning, don't crash startup. Partial registration if some endpoints parse correctly (Task 8). | 8, 15 |
| **Performance regression** from parallel execution | MEDIUM — CPU spike | `TOOLS_MAX_CONCURRENCY` semaphore (default 10). Configurable via env var (Task 11). | 10, 11 |
| **Async/sync mismatch** in LangGraph | MEDIUM — runtime error | LangGraph supports async nodes. Synchronous fallback path preserved for non-LangGraph mode (Task 12). | 12 |
| **Provider adapter breakage** from tool type change | MEDIUM | `ToolResult` has `.name` property alias for backward compat. `ToolDefinition.to_openai_format()` replaces manual dict construction (Task 14). | 14 |
| **Schema generation edge cases** | LOW | `json_schema_from_func()` covers 90%+ patterns. Remaining 10% use manual `parameters` list override (same as current API). | 5 |

---

## Open Blockers

**None.** All dependencies are internal to this codebase. No external API keys, third-party service approvals, or infrastructure changes required. The plan is self-contained within `proxy/app/tools/` plus modifications to 5 existing files.

### Pre-flight Checklist

- [ ] Install optional dependencies: `pip install pyyaml jsonschema` (air-gapped: pre-download wheels)
- [ ] Verify `prometheus_client` is installed (already in requirements_proxy.txt)
- [ ] Ensure `aiohttp` is installed (already in requirements_proxy.txt)
- [ ] Create `tools_declarative/` directory with `.gitkeep` (for declarative tool files)
- [ ] All 1469 existing tests pass on `main` branch before starting

---

## Review Gates

Each task requires the following review gates before merge:

| Gate | Applies To | Description |
|------|-----------|-------------|
| **Diff review** | All tasks | Code review of changes by another developer |
| **Verifier** | Tasks 6, 12, 14, 16 | Automated test suite must pass (100% pass rate) |
| **Security** | Tasks 7, 13 | Shell tool safety review + endpoint authorization review |
| **Performance** | Tasks 10, 12 | ParallelExecutor concurrency benchmark (≤15s for 3 parallel tools) |
| **Documentation** | Task 17 | SDK guide, declarative reference, OpenAPI guide reviewed for accuracy |

---

## Rollback Plan

If the expansion causes issues at any phase:
1. Remove `proxy/app/tools/` directory
2. Restore original `proxy/app/tools.py` from git (`git checkout HEAD -- proxy/app/tools.py`)
3. Revert `orchestrator.py` `call_tools` to original sequential version
4. Remove `/v1/tools` endpoints from `main.py`
5. Revert `provider_adapter.py` to original imports
6. Revert `config.py` to remove tool system config

All changes are additive — no existing files are deleted (only modified with backward-compat shims).
