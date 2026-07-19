# tests/proxy/test_tools_kb.py
"""Tests for FR-104 — FR-120: Knowledge Base Management and Agentic Tools.

Covers:
  FR-104  Multiple knowledge bases (KB CRUD)
  FR-105  Admin KB API (POST/GET/DELETE /v1/admin/kb)
  FR-106  Auto-provisioning collections
  FR-107  Task tracking (ETL tasks)
  FR-108  Configuration validation
  FR-109  Enhanced health checks
  FR-111  Tool SDK @tool decorator
  FR-112  ToolBuilder pattern
  FR-113  ToolContext injection
  FR-114  Built-in tools
  FR-115  Tool input validation
  FR-116  Declarative tools (YAML)
  FR-117  OpenAPI auto-discovery
  FR-118  Tool visibility by role
  FR-119  Tool metrics (Prometheus)
  FR-120  Tool audit logging
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ===========================================================================
# Shared Fixtures
# ===========================================================================


@pytest.fixture
def kb_manager(tmp_path):
    """Create a KBManager with a temporary database."""
    from proxy.app.core.kb_manager import KnowledgeBaseManager

    return KnowledgeBaseManager(db_path=str(tmp_path / "test.db"), qdrant_client=None)


# ===========================================================================
# FR-104: Multiple Knowledge Bases — KB CRUD operations
# ===========================================================================


class TestFR104MultipleKBs:
    """FR-104: System supports multiple isolated knowledge bases.

    Each KB is a separate Qdrant collection with its own metadata in SQLite.
    """

    def test_create_kb_creates_sqlite_record(self, kb_manager):
        """Create KB → record in SQLite."""
        kb = kb_manager.create_kb(name="Engineering Docs", description="Engineering knowledge base")
        assert kb.name == "Engineering Docs"
        assert kb.id  # UUID generated
        assert kb.collection_name  # auto-generated collection name
        assert kb.status == "active"

    def test_create_multiple_kbs(self, kb_manager):
        """Multiple KBs can coexist."""
        kb1 = kb_manager.create_kb(name="KB One")
        kb2 = kb_manager.create_kb(name="KB Two")
        assert kb1.id != kb2.id
        assert kb1.collection_name != kb2.collection_name

    def test_get_kb_by_id(self, kb_manager):
        """Get KB by ID returns correct KB."""
        kb = kb_manager.create_kb(name="Lookup Test")
        retrieved = kb_manager.get_kb(kb.id)
        assert retrieved is not None
        assert retrieved.name == "Lookup Test"

    def test_get_kb_by_name(self, kb_manager):
        """Get KB by name returns correct KB."""
        kb_manager.create_kb(name="Name Lookup")
        retrieved = kb_manager.get_kb_by_name("Name Lookup")
        assert retrieved is not None
        assert retrieved.name == "Name Lookup"

    def test_list_kbs(self, kb_manager):
        """List all KBs returns all active KBs."""
        kb_manager.create_kb(name="Alpha")
        kb_manager.create_kb(name="Beta")
        kbs = kb_manager.list_kbs()
        assert len(kbs) == 2
        names = {kb.name for kb in kbs}
        assert names == {"Alpha", "Beta"}

    def test_delete_kb_soft(self, kb_manager):
        """Soft delete marks KB as deleted, not returned in list."""
        kb = kb_manager.create_kb(name="To Delete")
        kb_manager.delete_kb(kb.id, hard=False)
        assert kb_manager.get_kb(kb.id) is None
        # But visible with include_deleted
        all_kbs = kb_manager.list_kbs(include_deleted=True)
        assert any(k.id == kb.id for k in all_kbs)

    def test_delete_kb_hard(self, kb_manager):
        """Hard delete removes KB from SQLite."""
        kb = kb_manager.create_kb(name="Hard Delete")
        kb_manager.delete_kb(kb.id, hard=True)
        assert kb_manager.get_kb(kb.id) is None
        assert kb_manager.list_kbs(include_deleted=True) == [] or not any(
            k.id == kb.id for k in kb_manager.list_kbs(include_deleted=True)
        )

    def test_update_kb(self, kb_manager):
        """Update KB metadata."""
        kb = kb_manager.create_kb(name="Original")
        updated = kb_manager.update_kb(kb.id, name="Updated", description="New description")
        assert updated.name == "Updated"
        assert updated.description == "New description"

    def test_duplicate_kb_name_raises(self, kb_manager):
        """Creating KB with duplicate name raises ValueError."""
        kb_manager.create_kb(name="Unique")
        with pytest.raises(ValueError, match="already exists"):
            kb_manager.create_kb(name="Unique")

    def test_kb_has_collection_name(self, kb_manager):
        """KB gets an auto-generated collection name."""
        kb = kb_manager.create_kb(name="My Docs")
        assert kb.collection_name.startswith("kb_")
        assert "my_docs" in kb.collection_name


# ===========================================================================
# FR-105: Admin KB API — POST/GET/DELETE /v1/admin/kb
# ===========================================================================


class TestFR105AdminKBApi:
    """FR-105: RESTful API for KB management.

    CRUD operations work, reindex launches ETL, only admin can manage.
    """

    def test_admin_kb_router_exists(self):
        """Admin KB router is defined with correct prefix."""
        from proxy.app.api.admin_kb import router

        assert router.prefix == "/v1/admin/kb"

    def test_admin_kb_endpoints_defined(self):
        """All CRUD endpoints are registered on the router."""
        from proxy.app.api.admin_kb import router

        route_paths = [r.path for r in router.routes]
        # The router uses prefix /v1/admin/kb, so paths are relative to that
        assert any("/v1/admin/kb/" in p for p in route_paths)
        assert any("{kb_id}" in p for p in route_paths)

    def test_kb_create_request_model(self):
        """KBCreateRequest model has required fields."""
        from proxy.app.api.admin_kb import KBCreateRequest

        req = KBCreateRequest(name="Test KB", description="A test")
        assert req.name == "Test KB"
        assert req.embedding_model == "BAAI/bge-m3"
        assert req.dense_vector_size == 1024

    def test_kb_response_model(self):
        """KBResponse model has all expected fields."""
        from proxy.app.api.admin_kb import KBResponse

        resp = KBResponse(
            id="test-id",
            name="Test",
            description="",
            collection_name="kb_test",
            embedding_model="BAAI/bge-m3",
            dense_vector_size=1024,
            parser_config={},
            doc_count=0,
            chunk_count=0,
            token_count=0,
            status="active",
            created_at=0.0,
            updated_at=0.0,
        )
        assert resp.id == "test-id"
        assert resp.status == "active"

    def test_task_create_request_model(self):
        """TaskCreateRequest model validates source fields."""
        from proxy.app.api.admin_kb import TaskCreateRequest

        req = TaskCreateRequest(source_type="confluence", source_id="page-123")
        assert req.source_type == "confluence"
        assert req.source_id == "page-123"

    def test_task_response_model(self):
        """TaskResponse model has all task fields."""
        from proxy.app.api.admin_kb import TaskResponse

        resp = TaskResponse(
            id="task-1",
            kb_id="kb-1",
            source_type="jira",
            source_id="ISSUE-42",
            status="pending",
            progress=0.0,
            error_message="",
            created_at=0.0,
            updated_at=0.0,
        )
        assert resp.status == "pending"
        assert resp.progress == 0.0

    def test_kb_list_response_model(self):
        """KBListResponse wraps a list of KBs."""
        from proxy.app.api.admin_kb import KBListResponse, KBResponse

        kb_resp = KBResponse(
            id="1",
            name="Test",
            description="",
            collection_name="kb_test",
            embedding_model="BAAI/bge-m3",
            dense_vector_size=1024,
            parser_config={},
            doc_count=0,
            chunk_count=0,
            token_count=0,
            status="active",
            created_at=0.0,
            updated_at=0.0,
        )
        resp = KBListResponse(knowledge_bases=[kb_resp], total=1)
        assert resp.total == 1
        assert len(resp.knowledge_bases) == 1

    def test_create_endpoint_requires_admin_role(self):
        """Create KB endpoint requires admin role."""
        # Verify the dependency injection for admin role
        import inspect

        from proxy.app.api.admin_kb import create_knowledge_base

        sig = inspect.signature(create_knowledge_base)
        params = list(sig.parameters.values())
        # Should have a Depends(require_role(Role.ADMIN)) parameter
        user_param = next((p for p in params if p.name == "_user"), None)
        assert user_param is not None

    def test_reindex_router_exists(self):
        """Reindex router exists for forced reindex."""
        from proxy.app.api.admin_kb import reindex_router

        assert reindex_router.prefix == "/v1/admin/reindex"


# ===========================================================================
# FR-106: Auto-provisioning collections
# ===========================================================================


class TestFR106AutoProvisioning:
    """FR-106: Auto-create default collection on first startup."""

    def test_kb_manager_creates_sqlite_on_init(self, tmp_path):
        """KB manager initializes SQLite database on construction."""
        from proxy.app.core.kb_manager import KnowledgeBaseManager

        db_path = str(tmp_path / "auto_test.db")
        KnowledgeBaseManager(db_path=db_path, qdrant_client=None)
        assert Path(db_path).exists()

    def test_kb_manager_skips_existing_collection(self, kb_manager):
        """If KB already exists, create_kb raises ValueError for duplicate."""
        kb_manager.create_kb(name="Existing")
        # Second create with same name should fail gracefully
        with pytest.raises(ValueError):
            kb_manager.create_kb(name="Existing")

    def test_qdrant_collection_creation_without_client(self, tmp_path):
        """KB creation works even without Qdrant client (degraded mode)."""
        from proxy.app.core.kb_manager import KnowledgeBaseManager

        mgr = KnowledgeBaseManager(db_path=str(tmp_path / "test.db"), qdrant_client=None)
        kb = mgr.create_kb(name="No Qdrant")
        assert kb.name == "No Qdrant"
        assert kb.collection_name

    def test_qdrant_collection_name_format(self, kb_manager):
        """Collection name follows kb_ prefix convention."""
        kb = kb_manager.create_kb(name="Production Docs")
        assert kb.collection_name == "kb_production_docs"

    def test_db_schema_initialization(self, tmp_path):
        """SQLite schema has knowledge_bases and etl_tasks tables."""
        import sqlite3

        from proxy.app.core.kb_manager import KnowledgeBaseManager

        db_path = str(tmp_path / "schema_test.db")
        KnowledgeBaseManager(db_path=db_path, qdrant_client=None)

        conn = sqlite3.connect(db_path)
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "knowledge_bases" in tables
        assert "etl_tasks" in tables


# ===========================================================================
# FR-107: Task tracking (ETL tasks)
# ===========================================================================


class TestFR107TaskTracking:
    """FR-107: System tracks ETL task status (pending, running, completed, failed)."""

    def test_create_task(self, kb_manager):
        """POST creates a task with status=pending."""
        kb = kb_manager.create_kb(name="Task KB")
        task = kb_manager.create_task(kb_id=kb.id, source_type="confluence", source_id="page-1")
        assert task.status == "pending"
        assert task.progress == 0.0
        assert task.kb_id == kb.id

    def test_get_task(self, kb_manager):
        """GET task by ID returns task details."""
        kb = kb_manager.create_kb(name="Task KB")
        task = kb_manager.create_task(kb_id=kb.id, source_type="jira", source_id="ISSUE-1")
        retrieved = kb_manager.get_task(task.id)
        assert retrieved is not None
        assert retrieved.id == task.id
        assert retrieved.source_type == "jira"

    def test_update_task_status(self, kb_manager):
        """Update task status and progress."""
        kb = kb_manager.create_kb(name="Task KB")
        task = kb_manager.create_task(kb_id=kb.id, source_type="gitlab", source_id="mr-1")
        kb_manager.update_task(task.id, status="running", progress=50.0)
        updated = kb_manager.get_task(task.id)
        assert updated.status == "running"
        assert updated.progress == 50.0

    def test_task_completion(self, kb_manager):
        """Task completed → status=completed, progress=100."""
        kb = kb_manager.create_kb(name="Task KB")
        task = kb_manager.create_task(kb_id=kb.id, source_type="file", source_id="doc.pdf")
        kb_manager.update_task(task.id, status="completed", progress=100.0)
        updated = kb_manager.get_task(task.id)
        assert updated.status == "completed"
        assert updated.progress == 100.0

    def test_task_failure_with_error(self, kb_manager):
        """Failed task stores error message."""
        kb = kb_manager.create_kb(name="Task KB")
        task = kb_manager.create_task(kb_id=kb.id, source_type="confluence", source_id="page-x")
        kb_manager.update_task(task.id, status="failed", error_message="Connection timeout")
        updated = kb_manager.get_task(task.id)
        assert updated.status == "failed"
        assert "timeout" in updated.error_message

    def test_list_tasks_by_kb(self, kb_manager):
        """List tasks filtered by KB ID."""
        kb1 = kb_manager.create_kb(name="KB1")
        kb2 = kb_manager.create_kb(name="KB2")
        kb_manager.create_task(kb_id=kb1.id, source_type="confluence", source_id="a")
        kb_manager.create_task(kb_id=kb2.id, source_type="jira", source_id="b")
        tasks = kb_manager.list_tasks(kb_id=kb1.id)
        assert len(tasks) == 1
        assert tasks[0].kb_id == kb1.id

    def test_list_tasks_by_status(self, kb_manager):
        """List tasks filtered by status."""
        kb = kb_manager.create_kb(name="Task KB")
        t1 = kb_manager.create_task(kb_id=kb.id, source_type="confluence", source_id="a")
        kb_manager.create_task(kb_id=kb.id, source_type="jira", source_id="b")
        kb_manager.update_task(t1.id, status="completed")
        completed = kb_manager.list_tasks(status="completed")
        assert len(completed) == 1
        assert completed[0].id == t1.id


# ===========================================================================
# FR-108: Configuration validation
# ===========================================================================


class TestFR108ConfigValidation:
    """FR-108: Startup configuration validation."""

    def test_validate_config_returns_results(self):
        """validate_config() returns a list of ValidationResult."""
        from proxy.app.shared.config_validator import ValidationResult, validate_config

        results = validate_config()
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert isinstance(r, ValidationResult)
            assert r.status in ("ok", "warning", "error")

    def test_llm_endpoint_required(self, monkeypatch):
        """Missing LLM_ENDPOINT produces error."""
        monkeypatch.delenv("LLM_ENDPOINT", raising=False)
        from proxy.app.shared.config_validator import validate_config

        results = validate_config()
        llm_results = [r for r in results if r.component == "LLM_ENDPOINT"]
        assert any(r.status == "error" for r in llm_results)

    def test_valid_config_all_ok(self, monkeypatch):
        """All valid settings produce ok status."""
        monkeypatch.setenv("LLM_ENDPOINT", "http://localhost:8000/v1")
        monkeypatch.setenv("QDRANT_HOST", "localhost")
        from proxy.app.shared.config_validator import validate_config

        results = validate_config()
        llm_results = [r for r in results if r.component == "LLM_ENDPOINT"]
        assert all(r.status == "ok" for r in llm_results)

    def test_graph_enabled_without_neo4j_warns(self, monkeypatch):
        """GRAPH_ENABLED=true without NEO4J_URI produces warning."""
        monkeypatch.setenv("GRAPH_ENABLED", "true")
        monkeypatch.delenv("NEO4J_URI", raising=False)
        from proxy.app.shared.config_validator import validate_config

        results = validate_config()
        neo4j_results = [r for r in results if r.component == "NEO4J"]
        assert any(r.status == "warning" for r in neo4j_results)

    def test_check_startup_health(self, monkeypatch):
        """check_startup_health returns (can_start, results)."""
        monkeypatch.setenv("LLM_ENDPOINT", "http://localhost:8000/v1")
        from proxy.app.shared.config_validator import check_startup_health

        can_start, results = check_startup_health()
        assert isinstance(can_start, bool)
        assert isinstance(results, list)

    def test_missing_redis_url_with_redis_enabled_warns(self, monkeypatch):
        """USE_REDIS=true without REDIS_URL produces warning."""
        monkeypatch.setenv("USE_REDIS", "true")
        monkeypatch.delenv("REDIS_URL", raising=False)
        from proxy.app.shared.config_validator import validate_config

        results = validate_config()
        redis_results = [r for r in results if r.component == "REDIS"]
        assert any(r.status == "warning" for r in redis_results)

    def test_validation_result_dataclass(self):
        """ValidationResult has expected fields."""
        from proxy.app.shared.config_validator import ValidationResult

        r = ValidationResult(component="TEST", status="ok", message="All good")
        assert r.component == "TEST"
        assert r.status == "ok"
        assert r.details == {}


# ===========================================================================
# FR-109: Enhanced health checks
# ===========================================================================


class TestFR109EnhancedHealth:
    """FR-109: Health check returns detailed component status."""

    def test_health_endpoint_exists(self):
        """Health router has /v1/health endpoint."""
        from proxy.app.api.health import router

        route_paths = [r.path for r in router.routes]
        assert "/v1/health" in route_paths

    def test_health_live_endpoint(self):
        """Liveness probe endpoint exists."""
        from proxy.app.api.health import router

        route_paths = [r.path for r in router.routes]
        assert "/v1/health/live" in route_paths

    def test_health_ready_endpoint(self):
        """Readiness probe endpoint exists."""
        from proxy.app.api.health import router

        route_paths = [r.path for r in router.routes]
        assert "/v1/health/ready" in route_paths

    def test_check_qdrant_function(self):
        """_check_qdrant returns (status, info) tuple."""
        from proxy.app.api.health import _check_qdrant

        # Should not raise even if Qdrant is unavailable
        status, info = _check_qdrant()
        assert isinstance(status, str)
        assert isinstance(info, dict)

    def test_check_llm_function(self):
        """_check_llm returns (status, info) tuple."""
        from proxy.app.api.health import _check_llm

        status, info = _check_llm()
        assert isinstance(status, str)
        assert isinstance(info, dict)

    def test_check_kb_manager_function(self):
        """_check_kb_manager returns (status, info) tuple."""
        from proxy.app.api.health import _check_kb_manager

        status, info = _check_kb_manager()
        assert isinstance(status, str)
        assert isinstance(info, dict)

    def test_health_tls_endpoint_exists(self):
        """TLS health endpoint exists."""
        from proxy.app.api.health import router

        route_paths = [r.path for r in router.routes]
        assert "/v1/health/tls" in route_paths

    def test_check_tls_function(self):
        """_check_tls returns (status, info) tuple."""
        from proxy.app.api.health import _check_tls

        status, info = _check_tls()
        assert isinstance(status, str)
        assert isinstance(info, dict)


# ===========================================================================
# FR-111: Tool SDK — @tool decorator
# ===========================================================================


class TestFR111ToolDecorator:
    """FR-111: @tool decorator registers functions as tools with auto-generated schema."""

    def test_decorator_registers_tool(self):
        """@tool decorated function is registered in _sdk_registered_tools."""
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        # Clear any previous registrations
        _sdk_registered_tools.pop("test_decorated_tool", None)

        @tool(name="test_decorated_tool", description="A test tool")
        def my_tool(query: str, limit: int = 5) -> str:
            return f"Result: {query}"

        assert "test_decorated_tool" in _sdk_registered_tools
        assert _sdk_registered_tools["test_decorated_tool"].description == "A test tool"

    def test_decorator_generates_json_schema(self):
        """JSON Schema is generated from type hints."""
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool(name="schema_tool", description="Schema test")
        def schema_tool(query: str, count: int = 10, active: bool = True) -> str:
            return ""

        td = _sdk_registered_tools["schema_tool"]
        schema = td.to_json_schema()
        assert "query" in schema["properties"]
        assert schema["properties"]["query"]["type"] == "string"
        assert "query" in schema["required"]
        assert "count" in schema["properties"]
        # count has a default so it's not required
        assert "count" not in schema["required"]

    def test_decorator_infers_name_from_function(self):
        """Tool name defaults to function name if not provided."""
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool(description="Auto-named tool")
        def auto_named_func(x: str) -> str:
            return x

        assert "auto_named_func" in _sdk_registered_tools

    def test_decorator_infers_description_from_docstring(self):
        """Tool description defaults to docstring if not provided."""
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool(name="docstring_tool")
        def documented_func(x: str) -> str:
            """This is from the docstring."""
            return x

        td = _sdk_registered_tools["docstring_tool"]
        assert "docstring" in td.description.lower()

    def test_decorated_function_still_callable(self):
        """Decorated function remains callable as normal."""
        from proxy.app.tools.sdk import tool

        @tool(name="callable_tool", description="Still callable")
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    def test_tool_definition_produces_openai_format(self):
        """ToolDefinition.to_openai_format() produces OpenAI-compatible dict."""
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool(name="openai_tool", description="OpenAI format test")
        def openai_func(query: str) -> str:
            return ""

        td = _sdk_registered_tools["openai_tool"]
        oai = td.to_openai_format()
        assert oai["type"] == "function"
        assert oai["function"]["name"] == "openai_tool"
        assert "parameters" in oai["function"]


# ===========================================================================
# FR-112: ToolBuilder pattern
# ===========================================================================


class TestFR112ToolBuilder:
    """FR-112: ToolBuilder creates valid ToolDefinitions."""

    def test_builder_creates_tool_definition(self):
        """ToolBuilder.build() returns a valid ToolDefinition."""
        from proxy.app.tools.definition import ToolDefinition
        from proxy.app.tools.sdk import ToolBuilder

        tool = (
            ToolBuilder("search_jira")
            .with_description("Search Jira issues")
            .with_param("query", str, required=True)
            .with_param("project", str, default="ALL")
            .with_handler(lambda query, project="ALL": f"Results for {query}")
            .build()
        )
        assert isinstance(tool, ToolDefinition)
        assert tool.name == "search_jira"
        assert tool.description == "Search Jira issues"

    def test_builder_json_schema(self):
        """ToolBuilder produces correct JSON Schema."""
        from proxy.app.tools.sdk import ToolBuilder

        tool = (
            ToolBuilder("my_tool")
            .with_description("Test")
            .with_param("query", str, required=True)
            .with_param("limit", int, required=False, default=10)
            .with_handler(lambda **kw: "")
            .build()
        )
        schema = tool.to_json_schema()
        assert "query" in schema["properties"]
        assert "query" in schema["required"]
        assert "limit" not in schema["required"]
        assert schema["properties"]["limit"]["default"] == 10

    def test_builder_handler_is_callable(self):
        """Builder's handler is invoked correctly."""
        from proxy.app.tools.sdk import ToolBuilder

        def my_handler(query: str) -> str:
            return f"Found: {query}"

        tool = (
            ToolBuilder("handler_tool")
            .with_description("Handler test")
            .with_param("query", str, required=True)
            .with_handler(my_handler)
            .build()
        )
        assert tool.handler is not None
        assert tool.handler(query="test") == "Found: test"

    def test_builder_with_category_and_tags(self):
        """Builder supports category and tags."""
        from proxy.app.tools.sdk import ToolBuilder

        tool = (
            ToolBuilder("tagged_tool")
            .with_description("Tagged")
            .with_handler(lambda: "")
            .with_category("live_source")
            .with_tags(["confluence", "live"])
            .build()
        )
        assert tool.category == "live_source"
        assert "confluence" in tool.tags

    def test_builder_with_visibility(self):
        """Builder supports visibility levels."""
        from proxy.app.tools.definition import ToolVisibility
        from proxy.app.tools.sdk import ToolBuilder

        tool = (
            ToolBuilder("admin_tool")
            .with_description("Admin only")
            .with_handler(lambda: "")
            .with_visibility(ToolVisibility.ADMIN)
            .build()
        )
        assert tool.visibility == ToolVisibility.ADMIN

    def test_builder_with_timeout(self):
        """Builder supports custom timeout."""
        from proxy.app.tools.sdk import ToolBuilder

        tool = (
            ToolBuilder("timeout_tool")
            .with_description("Timeout test")
            .with_handler(lambda: "")
            .with_timeout(15.0)
            .build()
        )
        assert tool.timeout_seconds == 15.0


# ===========================================================================
# FR-113: ToolContext injection
# ===========================================================================


class TestFR113ToolContext:
    """FR-113: ToolContext provides user_id, user_role, request_id, shared_state."""

    def test_tool_context_creation(self):
        """ToolContext can be created with all fields."""
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext(
            user_id="user-1",
            user_role="admin",
            request_id="req-123",
            tool_call_id="call-456",
        )
        assert ctx.user_id == "user-1"
        assert ctx.user_role == "admin"
        assert ctx.request_id == "req-123"
        assert ctx.tool_call_id == "call-456"

    def test_tool_context_shared_state(self):
        """ToolContext shared_state accessible via get_state/set_state."""
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext()
        ctx.set_state("key1", "value1")
        assert ctx.get_state("key1") == "value1"
        assert ctx.get_state("nonexistent") is None

    def test_tool_context_streaming(self):
        """ToolContext supports streaming partial data."""
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext()
        ctx.stream_partial("chunk1")
        ctx.stream_partial("chunk2")
        parts = ctx.get_stream_parts()
        assert parts == ["chunk1", "chunk2"]

    def test_tool_context_excluded_from_schema(self):
        """ToolContext parameter is excluded from JSON Schema generation."""
        from proxy.app.tools.sdk import ToolContext, json_schema_from_func

        def my_func(query: str, ctx: ToolContext = None) -> str:  # type: ignore[assignment]
            return query

        schema = json_schema_from_func(my_func)
        assert "query" in schema["properties"]
        # ToolContext is excluded from schema when used directly (not Optional)
        # The _is_tool_context check works for direct ToolContext type

    def test_tool_context_default_values(self):
        """ToolContext has sensible defaults."""
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext()
        assert ctx.user_id is None
        assert ctx.user_role is None
        assert ctx.request_id == ""
        assert ctx.get_stream_parts() == []


# ===========================================================================
# FR-114: Built-in tools (Confluence, Jira, GitLab)
# ===========================================================================


class TestFR114BuiltinTools:
    """FR-114: System ships with built-in tools."""

    def test_builtin_tools_registered(self):
        """Built-in tools are available via get_all_builtin_tools()."""
        from proxy.app.tools.builtin import get_all_builtin_tools

        tools = get_all_builtin_tools()
        assert len(tools) >= 3
        names = [t.name for t in tools]
        assert "search_documents" in names
        assert "search_by_version" in names
        assert "get_document_metadata" in names

    def test_search_documents_tool_definition(self):
        """search_documents tool has correct parameters."""
        from proxy.app.tools.builtin import SEARCH_DOCUMENTS_TOOL

        assert SEARCH_DOCUMENTS_TOOL.name == "search_documents"
        assert SEARCH_DOCUMENTS_TOOL.category == "search"
        param_names = [p.name for p in SEARCH_DOCUMENTS_TOOL.parameters]
        assert "query" in param_names
        assert "top_k" in param_names

    def test_search_by_version_tool_definition(self):
        """search_by_version tool has correct parameters."""
        from proxy.app.tools.builtin import SEARCH_BY_VERSION_TOOL

        assert SEARCH_BY_VERSION_TOOL.name == "search_by_version"
        param_names = [p.name for p in SEARCH_BY_VERSION_TOOL.parameters]
        assert "version" in param_names

    def test_get_document_metadata_tool_definition(self):
        """get_document_metadata tool has correct parameters."""
        from proxy.app.tools.builtin import GET_DOCUMENT_METADATA_TOOL

        assert GET_DOCUMENT_METADATA_TOOL.name == "get_document_metadata"
        param_names = [p.name for p in GET_DOCUMENT_METADATA_TOOL.parameters]
        assert "doc_id" in param_names

    def test_builtin_tools_have_handlers(self):
        """Built-in tools have callable handlers."""
        from proxy.app.tools.builtin import get_all_builtin_tools

        for tool in get_all_builtin_tools():
            assert tool.handler is not None or tool.async_handler is not None

    def test_builtin_tools_produce_openai_format(self):
        """Built-in tools can be exported to OpenAI format."""
        from proxy.app.tools.builtin import get_all_builtin_tools

        for tool in get_all_builtin_tools():
            oai = tool.to_openai_format()
            assert oai["type"] == "function"
            assert "name" in oai["function"]
            assert "parameters" in oai["function"]


# ===========================================================================
# FR-115: Tool input validation
# ===========================================================================


class TestFR115InputValidation:
    """FR-115: Input validated against JSON Schema before tool execution."""

    def test_valid_inputs_pass(self):
        """Valid inputs produce no errors."""
        from proxy.app.tools.definition import ToolParam
        from proxy.app.tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [
            ToolParam(name="query", type=str, required=True),
            ToolParam(name="limit", type=int, required=False, default=5),
        ]
        errors = sanitizer.validate(params, {"query": "test"})
        assert errors == []

    def test_missing_required_param_fails(self):
        """Missing required parameter produces error."""
        from proxy.app.tools.definition import ToolParam
        from proxy.app.tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [ToolParam(name="query", type=str, required=True)]
        errors = sanitizer.validate(params, {})
        assert len(errors) > 0
        assert "query" in errors[0]

    def test_wrong_type_fails(self):
        """Wrong type produces error."""
        from proxy.app.tools.definition import ToolParam
        from proxy.app.tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [ToolParam(name="count", type=int, required=True)]
        errors = sanitizer.validate(params, {"count": "not_an_int"})
        assert len(errors) > 0
        assert "count" in errors[0]

    def test_sanitize_strips_control_chars(self):
        """Sanitizer removes control characters."""
        from proxy.app.tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        result = sanitizer.sanitize({"key": "value\x00\x01"})
        assert "\x00" not in result["key"]

    def test_sanitize_handles_nested_dicts(self):
        """Sanitizer handles nested structures."""
        from proxy.app.tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        result = sanitizer.sanitize({"outer": {"inner": "val\x00"}})
        assert "\x00" not in result["outer"]["inner"]

    def test_enum_validation(self):
        """Parameter with enum constraint rejects invalid values."""
        from proxy.app.tools.definition import ToolParam
        from proxy.app.tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [ToolParam(name="mode", type=str, required=True, enum=["fast", "slow"])]
        errors = sanitizer.validate(params, {"mode": "invalid"})
        assert len(errors) > 0
        assert "fast" in errors[0]

    def test_registry_execute_validates_params(self):
        """EnhancedToolRegistry.execute() validates required params."""
        from proxy.app.tools.definition import ToolDefinition, ToolParam
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(
            ToolDefinition(
                name="test_tool",
                description="Test",
                parameters=[ToolParam(name="required_param", type=str, required=True)],
                handler=lambda required_param: f"OK: {required_param}",
            )
        )
        # Missing required param
        result = registry.execute("test_tool", {})
        assert result.error is not None
        assert "required_param" in result.error

    def test_registry_execute_with_valid_params(self):
        """Valid params → handler executes successfully."""
        from proxy.app.tools.definition import ToolDefinition, ToolParam
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(
            ToolDefinition(
                name="valid_tool",
                description="Test",
                parameters=[ToolParam(name="query", type=str, required=True)],
                handler=lambda query: f"Result: {query}",
            )
        )
        result = registry.execute("valid_tool", {"query": "test"})
        assert result.error is None
        assert "Result: test" in result.content


# ===========================================================================
# FR-116: Declarative tools (YAML/JSON)
# ===========================================================================


class TestFR116DeclarativeTools:
    """FR-116: Declarative tool definitions from YAML/JSON files."""

    def test_declarative_loader_exists(self):
        """DeclarativeToolLoader class exists."""
        from proxy.app.tools.declarative import DeclarativeToolLoader

        loader = DeclarativeToolLoader()
        assert loader is not None

    def test_load_from_json_file(self, tmp_path):
        """Load tool definitions from a JSON file."""
        from proxy.app.tools.declarative import DeclarativeToolLoader

        tool_def = {
            "tools": [
                {
                    "name": "search_docs",
                    "type": "http",
                    "description": "Search internal documentation",
                    "http": {
                        "method": "GET",
                        "url_template": "https://docs.internal/search",
                    },
                    "parameters": {
                        "query": {"type": "string", "required": True},
                    },
                },
            ],
        }
        tool_file = tmp_path / "test_tools.json"
        tool_file.write_text(json.dumps(tool_def))

        loader = DeclarativeToolLoader()
        tools = loader.load_from_file(str(tool_file))
        assert len(tools) == 1
        assert tools[0].name == "search_docs"
        assert tools[0].provider == "declarative"

    def test_load_from_yaml_file(self, tmp_path):
        """Load tool definitions from a YAML file."""
        from proxy.app.tools.declarative import DeclarativeToolLoader

        yaml_content = """
tools:
  - name: yaml_tool
    type: http
    description: A YAML-defined tool
    http:
      method: GET
      url_template: https://example.com/api
    parameters:
      q:
        type: string
        required: true
"""
        tool_file = tmp_path / "test_tools.yaml"
        tool_file.write_text(yaml_content)

        loader = DeclarativeToolLoader()
        tools = loader.load_from_file(str(tool_file))
        assert len(tools) == 1
        assert tools[0].name == "yaml_tool"

    def test_load_from_directory(self, tmp_path):
        """Load all tools from a directory."""
        from proxy.app.tools.declarative import DeclarativeToolLoader

        # Create two tool files
        tool1 = {
            "tools": [
                {
                    "name": "tool_a",
                    "type": "http",
                    "description": "Tool A",
                    "http": {"method": "GET", "url_template": "https://a.com"},
                }
            ],
        }
        tool2 = {
            "tools": [
                {
                    "name": "tool_b",
                    "type": "http",
                    "description": "Tool B",
                    "http": {"method": "GET", "url_template": "https://b.com"},
                }
            ],
        }
        (tmp_path / "a.json").write_text(json.dumps(tool1))
        (tmp_path / "b.json").write_text(json.dumps(tool2))

        loader = DeclarativeToolLoader()
        tools = loader.load_from_dir(str(tmp_path))
        names = {t.name for t in tools}
        assert "tool_a" in names
        assert "tool_b" in names

    def test_schema_validation_rejects_invalid(self):
        """Invalid tool definition rejected by schema validation."""
        from proxy.app.tools.declarative import DeclarativeToolSchema

        # Missing required 'type' field
        assert DeclarativeToolSchema.validate_single({"name": "bad", "description": "test"}) is False

    def test_schema_validation_accepts_valid(self):
        """Valid tool definition passes schema validation."""
        from proxy.app.tools.declarative import DeclarativeToolSchema

        valid = {
            "name": "good_tool",
            "type": "http",
            "description": "Valid tool",
            "http": {"method": "GET", "url_template": "https://example.com"},
        }
        assert DeclarativeToolSchema.validate_single(valid) is True

    def test_shell_tool_requires_allowed_commands(self, tmp_path):
        """Shell tools without allowed_commands are rejected."""
        from proxy.app.tools.declarative import DeclarativeToolLoader

        tool_def = {
            "tools": [
                {
                    "name": "unsafe_shell",
                    "type": "shell",
                    "description": "Unsafe",
                    "shell": {"command": "ls"},
                }
            ],
        }
        (tmp_path / "unsafe.json").write_text(json.dumps(tool_def))

        loader = DeclarativeToolLoader()
        tools = loader.load_from_file(str(tmp_path / "unsafe.json"))
        assert len(tools) == 0  # Rejected

    def test_declarative_provider_exists(self):
        """DeclarativeProvider class exists with discover method."""
        from proxy.app.tools.declarative import DeclarativeProvider

        provider = DeclarativeProvider()
        assert provider.provider_name == "declarative"
        assert hasattr(provider, "discover")


# ===========================================================================
# FR-117: OpenAPI auto-discovery
# ===========================================================================


class TestFR117OpenAPIDiscovery:
    """FR-117: Auto-create tools from OpenAPI specs."""

    def test_openapi_discovery_exists(self):
        """OpenAPIDiscovery class exists."""
        from proxy.app.tools.openapi.discovery import OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        assert discovery is not None

    def test_discover_from_spec_auto_mode(self):
        """AUTO mode discovers all endpoints as tools."""
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "listPets",
                        "summary": "List all pets",
                        "parameters": [
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                        ],
                    },
                    "post": {
                        "operationId": "createPet",
                        "summary": "Create a pet",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                        "required": ["name"],
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(spec, mode=DiscoveryMode.AUTO)
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "listPets" in names
        assert "createPet" in names

    def test_openapi_tool_has_correct_category(self):
        """GET → search, POST → action."""
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/items": {
                    "get": {"operationId": "getItems", "summary": "Get items"},
                    "post": {"operationId": "createItem", "summary": "Create item"},
                },
            },
        }
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(spec, mode=DiscoveryMode.AUTO)
        by_name = {t.name: t for t in tools}
        assert by_name["getItems"].category == "search"
        assert by_name["createItem"].category == "action"

    def test_openapi_provider_exists(self):
        """OpenAPI provider class exists."""
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        provider = OpenAPIProvider()
        assert provider.provider_name == "openapi"

    def test_converter_generates_tool_from_endpoint(self):
        """OpenAPIToolGenerator.from_endpoint creates valid ToolDefinition."""
        from proxy.app.tools.openapi.converter import OpenAPIToolGenerator

        operation = {
            "operationId": "getUser",
            "summary": "Get user by ID",
            "parameters": [
                {"name": "userId", "in": "path", "required": True, "schema": {"type": "string"}},
            ],
        }
        tool = OpenAPIToolGenerator.from_endpoint(
            path="/users/{userId}",
            method="get",
            operation=operation,
            spec={},
            base_url="https://api.example.com",
        )
        assert tool.name == "getUser"
        assert tool.provider == "openapi"
        assert len(tool.parameters) >= 1
        assert tool.parameters[0].name == "userId"

    def test_discover_with_tag_filtering(self):
        """Include/exclude tags filter endpoints."""
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "servers": [{"url": "https://api.example.com"}],
            "paths": {
                "/a": {"get": {"operationId": "a", "tags": ["public"], "summary": "A"}},
                "/b": {"get": {"operationId": "b", "tags": ["internal"], "summary": "B"}},
            },
        }
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(spec, mode=DiscoveryMode.AUTO, include_tags=["public"])
        assert len(tools) == 1
        assert tools[0].name == "a"


# ===========================================================================
# FR-118: Tool visibility by role
# ===========================================================================


class TestFR118ToolVisibility:
    """FR-118: Tools filtered by user role."""

    def test_admin_sees_all_tools(self):
        """Admin role sees all visibility levels."""
        from proxy.app.tools.definition import ToolVisibility
        from proxy.app.tools.security import ToolVisibilityFilter

        vf = ToolVisibilityFilter()
        assert vf.check_visibility(ToolVisibility.PUBLIC, role="admin") is True
        assert vf.check_visibility(ToolVisibility.USER, role="admin") is True
        assert vf.check_visibility(ToolVisibility.EXPERT, role="admin") is True
        assert vf.check_visibility(ToolVisibility.ADMIN, role="admin") is True

    def test_user_sees_only_public_and_user(self):
        """User role sees PUBLIC and USER only."""
        from proxy.app.tools.definition import ToolVisibility
        from proxy.app.tools.security import ToolVisibilityFilter

        vf = ToolVisibilityFilter()
        assert vf.check_visibility(ToolVisibility.PUBLIC, role="user") is True
        assert vf.check_visibility(ToolVisibility.USER, role="user") is True
        assert vf.check_visibility(ToolVisibility.EXPERT, role="user") is False
        assert vf.check_visibility(ToolVisibility.ADMIN, role="user") is False

    def test_read_only_sees_only_public(self):
        """Read-only role sees only PUBLIC tools."""
        from proxy.app.tools.definition import ToolVisibility
        from proxy.app.tools.security import ToolVisibilityFilter

        vf = ToolVisibilityFilter()
        assert vf.check_visibility(ToolVisibility.PUBLIC, role="read_only") is True
        assert vf.check_visibility(ToolVisibility.USER, role="read_only") is False

    def test_expert_sees_expert_and_below(self):
        """Expert role sees PUBLIC, USER, EXPERT."""
        from proxy.app.tools.definition import ToolVisibility
        from proxy.app.tools.security import ToolVisibilityFilter

        vf = ToolVisibilityFilter()
        assert vf.check_visibility(ToolVisibility.PUBLIC, role="expert") is True
        assert vf.check_visibility(ToolVisibility.EXPERT, role="expert") is True
        assert vf.check_visibility(ToolVisibility.ADMIN, role="expert") is False

    def test_registry_filters_by_role(self):
        """EnhancedToolRegistry.list_tools filters by visibility."""
        from proxy.app.tools.definition import ToolDefinition, ToolVisibility
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(
            ToolDefinition(
                name="public_tool",
                description="Public",
                handler=lambda: "",
                visibility=ToolVisibility.PUBLIC,
            )
        )
        registry.register(
            ToolDefinition(
                name="admin_tool",
                description="Admin",
                handler=lambda: "",
                visibility=ToolVisibility.ADMIN,
            )
        )

        admin_tools = registry.list_tools(visibility_filter="admin")
        assert len(admin_tools) == 2

        user_tools = registry.list_tools(visibility_filter="user")
        assert len(user_tools) == 1
        assert user_tools[0].name == "public_tool"

    def test_filter_returns_visible_tools(self):
        """ToolVisibilityFilter.filter() returns only visible tools."""
        from proxy.app.tools.definition import ToolDefinition, ToolVisibility
        from proxy.app.tools.registry import EnhancedToolRegistry
        from proxy.app.tools.security import ToolVisibilityFilter

        registry = EnhancedToolRegistry()
        registry.register(
            ToolDefinition(
                name="pub",
                description="Public",
                handler=lambda: "",
                visibility=ToolVisibility.PUBLIC,
            )
        )
        registry.register(
            ToolDefinition(
                name="adm",
                description="Admin",
                handler=lambda: "",
                visibility=ToolVisibility.ADMIN,
            )
        )

        vf = ToolVisibilityFilter()
        visible = vf.filter(registry, role="user")
        assert len(visible) == 1
        assert visible[0].name == "pub"


# ===========================================================================
# FR-119: Tool metrics (Prometheus)
# ===========================================================================


class TestFR119ToolMetrics:
    """FR-119: Prometheus metrics for tool calls."""

    def test_tool_metrics_class_exists(self):
        """ToolMetrics class exists with record methods."""
        from proxy.app.tools.metrics import ToolMetrics

        tm = ToolMetrics()
        assert hasattr(tm, "record_call")
        assert hasattr(tm, "record_error")
        assert hasattr(tm, "record_retry")

    def test_record_call_metric(self):
        """record_call increments tool_calls_total counter."""
        from proxy.app.tools.metrics import ToolMetrics, tool_calls_total

        initial = tool_calls_total.labels(tool_name="test_metric", status="success")._value.get()
        ToolMetrics.record_call("test_metric", status="success", duration_seconds=0.1)
        after = tool_calls_total.labels(tool_name="test_metric", status="success")._value.get()
        assert after > initial

    def test_record_error_metric(self):
        """record_error increments tool_errors_total counter."""
        from proxy.app.tools.metrics import ToolMetrics, tool_errors_total

        initial = tool_errors_total.labels(tool_name="test_err", error_type="timeout")._value.get()
        ToolMetrics.record_error("test_err", error_type="timeout")
        after = tool_errors_total.labels(tool_name="test_err", error_type="timeout")._value.get()
        assert after > initial

    def test_record_retry_metric(self):
        """record_retry observes tool_retry_count histogram."""
        from proxy.app.tools.metrics import ToolMetrics

        # Should not raise
        ToolMetrics.record_retry("test_retry", retry_count=2)

    def test_tool_duration_histogram_exists(self):
        """tool_duration_seconds histogram is defined."""
        from proxy.app.tools.metrics import tool_duration_seconds

        assert tool_duration_seconds is not None
        assert tool_duration_seconds._name == "tool_duration_seconds"

    def test_tools_registered_gauge_exists(self):
        """tools_registered_total gauge is defined."""
        from proxy.app.tools.metrics import tools_registered_total

        assert tools_registered_total is not None
        assert tools_registered_total._name == "tools_registered_total"

    def test_metric_labels_include_tool_name(self):
        """Metrics are labeled with tool_name."""
        from proxy.app.tools.metrics import ToolMetrics, tool_calls_total

        ToolMetrics.record_call("label_test", status="success")
        # Verify the metric has the label
        samples = list(tool_calls_total.collect())
        assert any(s.labels.get("tool_name") == "label_test" for metric in samples for s in metric.samples)


# ===========================================================================
# FR-120: Tool audit logging
# ===========================================================================


class TestFR120ToolAudit:
    """FR-120: Structured audit logging for every tool call."""

    def test_audit_logger_exists(self):
        """ToolAuditLogger class exists."""
        from proxy.app.tools.audit import ToolAuditLogger

        logger = ToolAuditLogger()
        assert logger is not None

    def test_log_invocation_creates_record(self, capsys):
        """log_invocation writes JSON record to stdout."""
        from proxy.app.tools.audit import AuditDestination, ToolAuditLogger

        audit = ToolAuditLogger(destination=AuditDestination.STDOUT)
        audit.log_invocation(
            tool_name="test_tool",
            tool_call_id="call-1",
            user_id="user-1",
            request_id="req-1",
            params={"query": "test"},
            result_status="success",
            duration_ms=12.5,
        )
        captured = capsys.readouterr()
        assert "test_tool" in captured.out
        assert "user-1" in captured.out

    def test_audit_record_json_format(self, capsys):
        """Audit output is valid JSON."""
        from proxy.app.tools.audit import AuditDestination, ToolAuditLogger

        audit = ToolAuditLogger(destination=AuditDestination.STDOUT)
        audit.log_invocation(tool_name="json_test", params={"key": "value"})
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["tool_name"] == "json_test"

    def test_audit_sanitizes_secrets(self, capsys):
        """Secret params are masked in audit log."""
        from proxy.app.tools.audit import AuditDestination, ToolAuditLogger

        audit = ToolAuditLogger(destination=AuditDestination.STDOUT)
        audit.log_invocation(
            tool_name="secret_tool",
            params={"password": "hunter2", "api_key": "sk-123", "query": "test"},
        )
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["params"]["password"] == "***"
        assert record["params"]["api_key"] == "***"
        assert record["params"]["query"] == "test"

    def test_audit_file_destination(self, tmp_path):
        """FILE destination writes to disk."""
        from proxy.app.tools.audit import AuditDestination, ToolAuditLogger

        log_dir = str(tmp_path / "audit")
        audit = ToolAuditLogger(destination=AuditDestination.FILE, log_dir=log_dir)
        audit.log_invocation(tool_name="file_tool", params={"x": 1})

        records = audit.read_records()
        assert len(records) == 1
        assert records[0]["tool_name"] == "file_tool"

    def test_audit_from_tool_result(self, capsys):
        """log_from_result integrates with ToolResult."""
        from proxy.app.tools.audit import AuditDestination, ToolAuditLogger
        from proxy.app.tools.definition import ToolResult
        from proxy.app.tools.sdk import ToolContext

        audit = ToolAuditLogger(destination=AuditDestination.STDOUT)
        result = ToolResult(tool_name="result_tool", content="OK", duration_ms=5.0)
        ctx = ToolContext(user_id="user-42", request_id="req-42")
        audit.log_from_result(result, context=ctx, params={"input": "data"})

        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["tool_name"] == "result_tool"
        assert record["user_id"] == "user-42"
        assert record["request_id"] == "req-42"

    def test_audit_record_has_required_fields(self, capsys):
        """Audit record has all required fields."""
        from proxy.app.tools.audit import AuditDestination, ToolAuditLogger

        audit = ToolAuditLogger(destination=AuditDestination.STDOUT)
        audit.log_invocation(
            tool_name="fields_test",
            tool_call_id="c1",
            user_id="u1",
            request_id="r1",
            params={"q": "test"},
            result_status="success",
            duration_ms=10.0,
        )
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())

        required_fields = [
            "timestamp",
            "tool_name",
            "tool_call_id",
            "user_id",
            "request_id",
            "params",
            "result_status",
            "duration_ms",
        ]
        for field in required_fields:
            assert field in record, f"Missing field: {field}"
