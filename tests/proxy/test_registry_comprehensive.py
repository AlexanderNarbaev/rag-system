"""Comprehensive tests for proxy/app/tools/registry.py.

Covers _visible_for_role, ToolProvider ABC, concrete providers,
EnhancedToolRegistry register/unregister/execute variants, dependency graph,
and get_enhanced_registry singleton.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxy.app.tools.definition import (
    ToolDefinition,
    ToolParam,
    ToolVisibility,
)
from proxy.app.tools.registry import (
    DEFAULT_VISIBILITY,
    ROLE_HIERARCHY,
    DeclarativeProvider,
    EnhancedToolRegistry,
    OpenAPIProvider,
    SDKProvider,
    ToolProvider,
    _visible_for_role,
    get_enhanced_registry,
)

# ---------------------------------------------------------------------------
# ROLE_HIERARCHY + _visible_for_role
# ---------------------------------------------------------------------------


class TestRoleVisibility:
    def test_role_hierarchy_keys(self):
        for role in ("admin", "expert", "user", "read_only"):
            assert role in ROLE_HIERARCHY

    def test_admin_sees_everything(self):
        for v in ("public", "admin", "expert", "user"):
            assert _visible_for_role(ToolVisibility(v), "admin") is True

    def test_expert_sees_subset(self):
        assert _visible_for_role(ToolVisibility.PUBLIC, "expert") is True
        assert _visible_for_role(ToolVisibility.EXPERT, "expert") is True
        assert _visible_for_role(ToolVisibility.USER, "expert") is True

    def test_user_only_sees_public_user(self):
        assert _visible_for_role(ToolVisibility.PUBLIC, "user") is True
        assert _visible_for_role(ToolVisibility.USER, "user") is True
        assert _visible_for_role(ToolVisibility.EXPERT, "user") is False

    def test_read_only_sees_public_only(self):
        assert _visible_for_role(ToolVisibility.PUBLIC, "read_only") is True
        assert _visible_for_role(ToolVisibility.USER, "read_only") is False
        assert _visible_for_role(ToolVisibility.EXPERT, "read_only") is False

    def test_unauthenticated_sees_only_public(self):
        assert _visible_for_role(ToolVisibility.PUBLIC, None) is True
        assert _visible_for_role(ToolVisibility.USER, None) is False
        assert _visible_for_role(ToolVisibility.EXPERT, None) is False

    def test_unknown_role_defaults_to_public(self):
        assert _visible_for_role(ToolVisibility.PUBLIC, "ghost") is True
        assert _visible_for_role(ToolVisibility.USER, "ghost") is False

    def test_default_visibility_constant(self):
        assert DEFAULT_VISIBILITY == ["public"]


# ---------------------------------------------------------------------------
# ToolProvider ABC + concrete providers
# ---------------------------------------------------------------------------


class TestSDKProvider:
    def test_provider_name(self):
        p = SDKProvider()
        assert p.provider_name == "sdk"

    def test_discover_returns_sdk_tools(self):
        SDKProvider._sdk_registered_tools = []
        # Inject a fake tool via class-level state
        t = ToolDefinition(
            name="sdk-tool",
            description="d",
            handler=lambda: "ok",
        )
        SDKProvider._sdk_registered_tools.append(t)
        try:
            tools = asyncio.run(SDKProvider().discover())
            assert any(tool.name == "sdk-tool" for tool in tools)
        finally:
            SDKProvider._sdk_registered_tools = []

    def test_validate_default_no_issues(self):
        p = SDKProvider()
        # Default validation returns no issues (no provider-specific checks)
        result = asyncio.run(p.validate())
        assert result == []

    def test_reload_calls_discover(self):
        p = SDKProvider()
        # Reload is the same as discover
        with patch.object(p, "discover", new_callable=AsyncMock) as mock_disc:
            mock_disc.return_value = [MagicMock()]
            asyncio.run(p.reload())
        mock_disc.assert_called_once()


class TestDeclarativeProvider:
    def test_provider_name(self):
        assert DeclarativeProvider().provider_name == "declarative"


class TestOpenAPIProvider:
    def test_provider_name(self):
        assert OpenAPIProvider().provider_name == "openapi"


class TestToolProviderABC:
    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ToolProvider()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# EnhancedToolRegistry — basics
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> EnhancedToolRegistry:
    # Reset singleton
    EnhancedToolRegistry._instance = None
    return EnhancedToolRegistry()


def _noop_handler(**kwargs):  # noqa: ARG001
    return "ok"


def _make_tool(name="t", description="d", required=None, handler=None, visibility=None):
    params = []
    if required:
        for pname in required:
            params.append(ToolParam(name=pname, type="string", required=True))
    if handler is None:
        handler = _noop_handler
    return ToolDefinition(
        name=name,
        description=description,
        parameters=params,
        handler=handler,
        visibility=visibility or ToolVisibility.PUBLIC,
    )


class TestRegistryBasics:
    def test_init_empty(self, registry):
        assert registry._tools == {}
        assert registry._provider_tools == {}

    def test_register(self, registry):
        tool = _make_tool()
        registry.register(tool)
        assert registry.get_tool("t") is tool

    def test_register_replaces_existing(self, registry):
        t1 = _make_tool(name="x", description="first")
        t2 = _make_tool(name="x", description="second")
        registry.register(t1)
        registry.register(t2)
        assert registry.get_tool("x").description == "second"

    def test_unregister_existing(self, registry):
        registry.register(_make_tool())
        assert registry.unregister("t") is True
        assert registry.get_tool("t") is None

    def test_unregister_unknown(self, registry):
        assert registry.unregister("ghost") is False

    def test_get_tool(self, registry):
        registry.register(_make_tool())
        assert registry.get_tool("t") is not None
        assert registry.get_tool("ghost") is None

    def test_get_alias(self, registry):
        registry.register(_make_tool())
        assert registry.get("t") is not None

    def test_get_all(self, registry):
        registry.register(_make_tool(name="a"))
        registry.register(_make_tool(name="b"))
        assert len(registry.get_all()) == 2

    def test_list_all(self, registry):
        registry.register(_make_tool(name="a"))
        registry.register(_make_tool(name="b"))
        assert len(registry.list_all()) == 2


# ---------------------------------------------------------------------------
# list_tools filtering
# ---------------------------------------------------------------------------


class TestListTools:
    def test_filter_by_category(self, registry):
        t1 = ToolDefinition(
            name="a",
            description="d",
            category="math",
            handler=lambda: None,
        )
        t2 = ToolDefinition(
            name="b",
            description="d",
            category="search",
            handler=lambda: None,
        )
        registry.register(t1)
        registry.register(t2)
        assert [t.name for t in registry.list_tools(category="math")] == ["a"]

    def test_filter_by_tag(self, registry):
        t1 = ToolDefinition(name="a", description="d", tags=["fast"], handler=lambda: None)
        t2 = ToolDefinition(name="b", description="d", tags=["slow"], handler=lambda: None)
        registry.register(t1)
        registry.register(t2)
        names = {t.name for t in registry.list_tools(tags=["fast"])}
        assert names == {"a"}

    def test_filter_by_visibility_admin(self, registry):
        registry.register(_make_tool(name="user-tool", visibility=ToolVisibility.USER, handler=lambda: None))
        registry.register(_make_tool(name="public-tool", visibility=ToolVisibility.PUBLIC, handler=lambda: None))
        names = {t.name for t in registry.list_tools(visibility_filter="admin")}
        assert "user-tool" in names
        assert "public-tool" in names

    def test_filter_by_visibility_unauthenticated(self, registry):
        # visibility_filter=None means show ALL (no filter applied)
        registry.register(_make_tool(name="user-tool", visibility=ToolVisibility.USER, handler=lambda: None))
        registry.register(_make_tool(name="public-tool", visibility=ToolVisibility.PUBLIC, handler=lambda: None))
        # With no visibility_filter, all tools returned
        names = {t.name for t in registry.list_tools(visibility_filter=None)}
        assert names == {"user-tool", "public-tool"}

    def test_list_by_category_alias(self, registry):
        registry.register(ToolDefinition(name="a", description="d", category="cat1", handler=lambda: None))
        assert len(registry.list_by_category("cat1")) == 1


# ---------------------------------------------------------------------------
# execute (sync)
# ---------------------------------------------------------------------------


class TestExecute:
    def test_execute_unknown_tool(self, registry):
        result = registry.execute("missing", {})
        assert result.error and "not found" in result.error

    def test_execute_missing_params(self, registry):
        t = _make_tool(required=["x"])
        registry.register(t)
        result = registry.execute("t", {})
        assert "Missing required" in result.error

    def test_execute_no_handler(self, registry):
        t = ToolDefinition(name="x", description="d", parameters=[], handler=None)
        registry.register(t)
        result = registry.execute("x", {})
        assert "no handler" in result.error

    def test_execute_happy_path(self, registry):
        def handler(x: int) -> str:
            return f"got {x}"

        t = _make_tool(required=["x"], handler=handler)
        registry.register(t)
        result = registry.execute("t", {"x": 5})
        assert result.content == "got 5"
        # No error: either None or empty string is acceptable
        assert not result.error
        assert result.duration_ms >= 0

    def test_execute_handler_raises(self, registry):
        def bad(x):
            raise RuntimeError("boom")

        t = _make_tool(required=["x"], handler=bad)
        registry.register(t)
        result = registry.execute("t", {"x": 1})
        assert "boom" in result.error
        assert result.duration_ms >= 0

    def test_execute_stringifies_non_str(self, registry):
        def handler(x: int) -> int:
            return x * 2

        t = _make_tool(required=["x"], handler=handler)
        registry.register(t)
        result = registry.execute("t", {"x": 3})
        assert result.content == "6"


# ---------------------------------------------------------------------------
# execute_async
# ---------------------------------------------------------------------------


class TestExecuteAsync:
    def test_async_with_async_handler(self, registry):
        async def handler(x: int) -> str:
            return f"async {x}"

        t = ToolDefinition(
            name="a",
            description="d",
            parameters=[ToolParam(name="x", type="int", required=True)],
            async_handler=handler,
        )
        registry.register(t)
        result = asyncio.run(registry.execute_async("a", {"x": 1}))
        assert result.content == "async 1"

    def test_async_with_sync_handler_fallback(self, registry):
        def handler(x: int) -> str:
            return f"sync {x}"

        t = _make_tool(required=["x"], handler=handler)
        registry.register(t)
        result = asyncio.run(registry.execute_async("t", {"x": 1}))
        assert result.content == "sync 1"

    def test_async_unknown(self, registry):
        result = asyncio.run(registry.execute_async("missing", {}))
        assert "not found" in result.error

    def test_async_missing_params(self, registry):
        t = _make_tool(required=["y"])
        registry.register(t)
        result = asyncio.run(registry.execute_async("t", {}))
        assert "Missing" in result.error

    def test_async_no_handler(self, registry):
        t = ToolDefinition(name="x", description="d", parameters=[], handler=None, async_handler=None)
        registry.register(t)
        result = asyncio.run(registry.execute_async("x", {}))
        assert "no handler" in result.error

    def test_async_handler_raises(self, registry):
        async def bad(x):
            raise ValueError("async-boom")

        t = ToolDefinition(
            name="a",
            description="d",
            parameters=[ToolParam(name="x", type="int", required=True)],
            async_handler=bad,
        )
        registry.register(t)
        result = asyncio.run(registry.execute_async("a", {"x": 1}))
        assert "async-boom" in result.error


# ---------------------------------------------------------------------------
# get_tools_for_llm
# ---------------------------------------------------------------------------


class TestGetToolsForLLM:
    def test_openai_format(self, registry):
        registry.register(_make_tool(description="d"))
        tools = registry.get_tools_for_llm(provider_type="openai")
        assert isinstance(tools, list)

    def test_anthropic_format(self, registry):
        registry.register(_make_tool(description="d"))
        tools = registry.get_tools_for_llm(provider_type="anthropic")
        assert isinstance(tools, list)

    def test_unknown_provider_defaults_to_openai(self, registry):
        registry.register(_make_tool(description="d"))
        tools = registry.get_tools_for_llm(provider_type="unknown-llm")
        assert isinstance(tools, list)

    def test_respects_user_role(self, registry):
        registry.register(
            _make_tool(
                name="admin-tool",
                description="d",
                visibility=ToolVisibility.ADMIN,
            ),
        )
        registry.register(_make_tool(name="public-tool"))
        tools = registry.get_tools_for_llm(user_role="user")
        names = {t["function"]["name"] for t in tools}
        assert "public-tool" in names
        assert "admin-tool" not in names


# ---------------------------------------------------------------------------
# validate_tool
# ---------------------------------------------------------------------------


class TestValidateTool:
    def test_valid_tool(self, registry):
        registry.register(_make_tool(description="d"))
        tool = registry.get_tool("t")
        assert registry.validate_tool(tool) == []

    def test_missing_name(self, registry):
        t = ToolDefinition(name="", description="d", handler=lambda: None)
        issues = registry.validate_tool(t)
        assert any("name" in i for i in issues)

    def test_missing_description(self, registry):
        t = ToolDefinition(name="x", description="", handler=lambda: None)
        issues = registry.validate_tool(t)
        assert any("description" in i for i in issues)

    def test_missing_handlers(self, registry):
        t = ToolDefinition(name="x", description="d", handler=None, async_handler=None)
        issues = registry.validate_tool(t)
        assert any("handler" in i for i in issues)

    def test_duplicate_parameters(self, registry):
        params = [
            ToolParam(name="x", type="int"),
            ToolParam(name="x", type="int"),
        ]
        t = ToolDefinition(name="x", description="d", parameters=params, handler=lambda: None)
        issues = registry.validate_tool(t)
        assert any("Duplicate" in i for i in issues)


# ---------------------------------------------------------------------------
# get_dependency_graph
# ---------------------------------------------------------------------------


class TestDependencyGraph:
    def test_empty_when_no_tools(self, registry):
        assert registry.get_dependency_graph() == {}

    def test_reflects_depends_on(self, registry):
        t1 = ToolDefinition(
            name="leaf",
            description="d",
            depends_on=[],
            handler=lambda: None,
        )
        t2 = ToolDefinition(
            name="middle",
            description="d",
            depends_on=["leaf"],
            handler=lambda: None,
        )
        registry.register(t1)
        registry.register(t2)
        graph = registry.get_dependency_graph()
        assert graph["middle"] == ["leaf"]
        assert graph["leaf"] == []


# ---------------------------------------------------------------------------
# discover / discover_all / reload_provider
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_discover_sync(self, registry):
        class P:
            name = "test"

            @property
            def provider_name(self):
                return "test"

            async def discover(self):
                return [_make_tool(name="discovered")]

        result = registry.discover(P())
        assert len(result) == 1
        assert registry.get_tool("discovered") is not None

    def test_discover_provider_failure(self, registry):
        class P:
            @property
            def provider_name(self):
                return "broken"

            async def discover(self):
                raise RuntimeError("nope")

        result = registry.discover(P())
        assert result == []

    def test_discover_from_provider_alias(self, registry):
        class P:
            @property
            def provider_name(self):
                return "t"

            async def discover(self):
                return []

        # should not raise
        registry.discover_from_provider(P())

    def test_reload_provider_unknown(self, registry):
        result = registry.reload_provider("ghost")
        assert result == []

    def test_reload_sdk_provider(self, registry):
        # Reload SDK provider should call discover
        SDKProvider._sdk_registered_tools = []
        try:
            t = _make_tool(name="reload-test")
            SDKProvider._sdk_registered_tools.append(t)
            result = registry.reload_provider("sdk")
            # Either finds it or skips — but call shouldn't crash
            assert isinstance(result, list)
        finally:
            SDKProvider._sdk_registered_tools = []


# ---------------------------------------------------------------------------
# get_enhanced_registry singleton
# ---------------------------------------------------------------------------


class TestGetEnhancedRegistry:
    def test_returns_registry(self):
        EnhancedToolRegistry._instance = None
        reg = get_enhanced_registry()
        assert isinstance(reg, EnhancedToolRegistry)

    def test_returns_singleton(self):
        EnhancedToolRegistry._instance = None
        a = get_enhanced_registry()
        b = get_enhanced_registry()
        assert a is b
