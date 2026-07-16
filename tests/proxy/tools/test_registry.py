"""Tests for proxy/app/tools/registry.py — EnhancedToolRegistry + ToolProvider.

TDD for Task 4: registry.py with EnhancedToolRegistry, ToolProvider ABC,
SDKProvider, DeclarativeProvider, OpenAPIProvider stubs.
"""

import asyncio
import sys
from abc import ABC
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))

from tools.definition import (
    ToolDefinition,
    ToolParam,
    ToolResult,
    ToolVisibility,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    name,
    description="Test tool",
    category="general",
    tags=None,
    visibility=ToolVisibility.PUBLIC,
    handler=None,
    provider="sdk",
    depends_on=None,
    parameters=None,
    async_handler=None,
):
    if parameters is None:
        parameters = [ToolParam(name="query", type=str, description="Query")]
    if handler is None:

        def handler(**kw):
            return f"Result: {kw}"

    return ToolDefinition(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
        async_handler=async_handler,
        category=category,
        tags=tags or [],
        visibility=visibility,
        provider=provider,
        depends_on=depends_on or [],
    )


# ---------------------------------------------------------------------------
# Test: ToolProvider ABC
# ---------------------------------------------------------------------------


class TestToolProviderABC:
    def test_toolprovider_is_abc(self):
        from tools.registry import ToolProvider

        assert issubclass(ToolProvider, ABC)

    def test_cannot_instantiate_abstract_provider(self):
        from tools.registry import ToolProvider

        with pytest.raises(TypeError):
            ToolProvider()  # type: ignore[abstract]

    def test_concrete_provider_can_be_instantiated(self):
        from tools.registry import ToolProvider

        class MyProvider(ToolProvider):
            @property
            def provider_name(self) -> str:
                return "my_provider"

            async def discover(self) -> list:
                return []

        provider = MyProvider()
        assert provider.provider_name == "my_provider"
        assert isinstance(provider, ToolProvider)

    def test_provider_validate_default_returns_empty(self):
        from tools.registry import ToolProvider

        class MyProvider(ToolProvider):
            @property
            def provider_name(self) -> str:
                return "test"

            async def discover(self) -> list:
                return []

        provider = MyProvider()
        issues = asyncio.run(provider.validate())
        assert issues == []

    def test_provider_reload_calls_discover(self):
        from tools.registry import ToolProvider

        class MyProvider(ToolProvider):
            @property
            def provider_name(self) -> str:
                return "test"

            async def discover(self) -> list:
                return [object()]

        provider = MyProvider()
        result = asyncio.run(provider.reload())
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Test: SDKProvider
# ---------------------------------------------------------------------------


class TestSDKProvider:
    def test_provider_name_is_sdk(self):
        from tools.registry import SDKProvider

        provider = SDKProvider()
        assert provider.provider_name == "sdk"

    def test_discover_scans_sdk_registered_tools(self):
        from tools.registry import SDKProvider

        tool = _make_tool(name="my_sdk_tool")
        SDKProvider._sdk_registered_tools = [tool]
        try:
            provider = SDKProvider()
            tools = asyncio.run(provider.discover())
            assert len(tools) == 1
            assert tools[0].name == "my_sdk_tool"
        finally:
            SDKProvider._sdk_registered_tools = []

    def test_discover_returns_empty_when_none_registered(self):
        from tools.registry import SDKProvider

        SDKProvider._sdk_registered_tools = []
        provider = SDKProvider()
        tools = asyncio.run(provider.discover())
        assert tools == []


# ---------------------------------------------------------------------------
# Test: EnhancedToolRegistry — register / get / unregister
# ---------------------------------------------------------------------------


class TestRegistryBasicOps:
    def test_register_and_get(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(name="test_tool")
        registry.register(tool)
        retrieved = registry.get_tool("test_tool")
        assert retrieved is tool
        assert retrieved.name == "test_tool"

    def test_register_overwrites_existing(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool1 = _make_tool(name="same", description="First")
        tool2 = _make_tool(name="same", description="Second")
        registry.register(tool1)
        registry.register(tool2)
        assert registry.get_tool("same").description == "Second"

    def test_get_nonexistent_returns_none(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        assert registry.get_tool("nonexistent") is None

    def test_unregister_existing(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(name="to_remove")
        registry.register(tool)
        assert registry.unregister("to_remove") is True
        assert registry.get_tool("to_remove") is None

    def test_unregister_nonexistent(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        assert registry.unregister("ghost") is False

    def test_get_alias(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(name="t")
        registry.register(tool)
        assert registry.get("t") is tool

    def test_get_all_backward_compat(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(_make_tool(name="a"))
        registry.register(_make_tool(name="b"))
        all_tools = registry.get_all()
        assert len(all_tools) == 2
        assert {t.name for t in all_tools} == {"a", "b"}

    def test_list_all_backward_compat(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(_make_tool(name="x"))
        assert len(registry.list_all()) == 1


# ---------------------------------------------------------------------------
# Test: list_tools with filters
# ---------------------------------------------------------------------------


class TestRegistryListTools:
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        from tools.registry import EnhancedToolRegistry

        self.registry = EnhancedToolRegistry()
        self.registry.register(
            _make_tool(
                name="public_tool",
                visibility=ToolVisibility.PUBLIC,
                category="search",
                tags=["fast"],
                provider="sdk",
            ),
        )
        self.registry.register(
            _make_tool(
                name="admin_tool",
                visibility=ToolVisibility.ADMIN,
                category="admin",
                tags=["slow"],
                provider="declarative",
            ),
        )
        self.registry.register(
            _make_tool(
                name="user_tool",
                visibility=ToolVisibility.USER,
                category="search",
                tags=["fast", "beta"],
                provider="openapi",
            ),
        )

    def test_list_tools_all(self):
        assert len(self.registry.list_tools()) == 3

    def test_list_tools_by_category(self):
        result = self.registry.list_tools(category="search")
        assert len(result) == 2
        assert {t.name for t in result} == {"public_tool", "user_tool"}

    def test_list_tools_by_tags(self):
        result = self.registry.list_tools(tags=["fast"])
        assert len(result) == 2
        assert {t.name for t in result} == {"public_tool", "user_tool"}

    def test_list_tools_by_provider(self):
        result = self.registry.list_tools(provider="openapi")
        assert len(result) == 1
        assert result[0].name == "user_tool"

    def test_list_tools_admin_visibility(self):
        result = self.registry.list_tools(visibility_filter="admin")
        assert len(result) == 3  # admin sees all

    def test_list_tools_user_visibility(self):
        result = self.registry.list_tools(visibility_filter="user")
        assert len(result) == 2
        assert {t.name for t in result} == {"public_tool", "user_tool"}

    def test_list_tools_read_only_visibility(self):
        result = self.registry.list_tools(visibility_filter="read_only")
        assert len(result) == 1
        assert result[0].name == "public_tool"

    def test_list_tools_combined_filters(self):
        result = self.registry.list_tools(
            category="search",
            tags=["fast"],
            provider="sdk",
        )
        assert len(result) == 1
        assert result[0].name == "public_tool"


# ---------------------------------------------------------------------------
# Test: execute (sync)
# ---------------------------------------------------------------------------


class TestRegistryExecute:
    def test_execute_success(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(
            name="greet",
            parameters=[
                ToolParam(name="name", type=str, description="Name"),
            ],
            handler=lambda name: f"Hello, {name}!",
        )
        registry.register(tool)

        result = registry.execute("greet", {"name": "World"})
        assert isinstance(result, ToolResult)
        assert result.status == "success"
        assert result.content == "Hello, World!"

    def test_execute_not_found(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        result = registry.execute("ghost", {})
        assert result.status == "error"
        assert "not found" in result.error.lower()

    def test_execute_missing_required_param(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(
            name="search",
            parameters=[
                ToolParam(name="query", type=str, description="Query", required=True),
            ],
            handler=lambda query: f"Results for {query}",
        )
        registry.register(tool)

        result = registry.execute("search", {})
        assert result.status == "error"
        assert "query" in result.error.lower()

    def test_execute_handler_exception(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()

        def bad_handler(**kw):
            raise RuntimeError("boom")

        registry.register(
            _make_tool(
                name="bad",
                parameters=[],  # no required params
                handler=bad_handler,
            ),
        )

        result = registry.execute("bad", {})
        assert result.status == "error"
        assert "boom" in result.error


# ---------------------------------------------------------------------------
# Test: execute_async
# ---------------------------------------------------------------------------


class TestRegistryExecuteAsync:
    @pytest.mark.asyncio
    async def test_execute_async_uses_async_handler(self):
        from tools.registry import EnhancedToolRegistry

        async def async_handler(name: str) -> str:
            return f"Hello, {name}!"

        registry = EnhancedToolRegistry()
        tool = _make_tool(
            name="greet_async",
            parameters=[
                ToolParam(name="name", type=str, description="Name"),
            ],
            handler=lambda name: "sync fallback",
            async_handler=async_handler,
        )
        registry.register(tool)

        result = await registry.execute_async("greet_async", {"name": "World"})
        assert result.status == "success"
        assert result.content == "Hello, World!"

    @pytest.mark.asyncio
    async def test_execute_async_falls_back_to_sync_handler(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(
            name="sync_only",
            parameters=[
                ToolParam(name="x", type=int, description="X"),
            ],
            handler=lambda x: f"Got {x}",
        )
        registry.register(tool)

        result = await registry.execute_async("sync_only", {"x": 42})
        assert result.status == "success"
        assert result.content == "Got 42"

    @pytest.mark.asyncio
    async def test_execute_async_not_found(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        result = await registry.execute_async("ghost", {})
        assert result.status == "error"


# ---------------------------------------------------------------------------
# Test: get_tools_for_llm
# ---------------------------------------------------------------------------


class TestGetToolsForLLM:
    def test_returns_openai_format(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(
            _make_tool(
                name="search",
                parameters=[
                    ToolParam(name="query", type=str, description="Search query"),
                ],
            ),
        )

        tools = registry.get_tools_for_llm(provider_type="openai")
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "search"

    def test_respects_user_role_visibility(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(_make_tool(name="pub", visibility=ToolVisibility.PUBLIC))
        registry.register(_make_tool(name="admin_only", visibility=ToolVisibility.ADMIN))

        tools = registry.get_tools_for_llm(provider_type="openai", user_role="user")
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "pub"

    def test_admin_sees_all(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(_make_tool(name="a", visibility=ToolVisibility.PUBLIC))
        registry.register(_make_tool(name="b", visibility=ToolVisibility.ADMIN))
        registry.register(_make_tool(name="c", visibility=ToolVisibility.USER))

        tools = registry.get_tools_for_llm(provider_type="openai", user_role="admin")
        assert len(tools) == 3


# ---------------------------------------------------------------------------
# Test: validate_tool
# ---------------------------------------------------------------------------


class TestValidateTool:
    def test_valid_tool_passes(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(
            name="valid",
            parameters=[
                ToolParam(name="q", type=str, description="Query"),
            ],
            handler=lambda q: q,
        )
        issues = registry.validate_tool(tool)
        assert issues == []

    def test_missing_name(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = ToolDefinition(name="", description="desc", handler=lambda: None)
        issues = registry.validate_tool(tool)
        assert any("name" in i.lower() for i in issues)

    def test_missing_description(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = ToolDefinition(name="t", description="", handler=lambda: None)
        issues = registry.validate_tool(tool)
        assert any("description" in i.lower() for i in issues)

    def test_missing_handler(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = ToolDefinition(name="t", description="desc", handler=None)
        issues = registry.validate_tool(tool)
        assert any("handler" in i.lower() for i in issues)

    def test_duplicate_param_names(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = ToolDefinition(
            name="t",
            description="desc",
            handler=lambda: None,
            parameters=[
                ToolParam(name="q", type=str),
                ToolParam(name="q", type=int),
            ],
        )
        issues = registry.validate_tool(tool)
        assert any("duplicate" in i.lower() for i in issues)


# ---------------------------------------------------------------------------
# Test: get_dependency_graph
# ---------------------------------------------------------------------------


class TestDependencyGraph:
    def test_returns_dag(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        registry.register(_make_tool(name="a", depends_on=["b"]))
        registry.register(_make_tool(name="b", depends_on=["c"]))
        registry.register(_make_tool(name="c"))

        graph = registry.get_dependency_graph()
        assert graph == {"a": ["b"], "b": ["c"], "c": []}

    def test_empty_registry_returns_empty_dict(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        assert registry.get_dependency_graph() == {}


# ---------------------------------------------------------------------------
# Test: discover / reload_provider
# ---------------------------------------------------------------------------


class TestDiscoverFromProvider:
    def test_discover_registers_tools_from_provider(self):
        from tools.registry import (
            EnhancedToolRegistry,
            SDKProvider,
        )

        tool = _make_tool(name="discovered_tool")
        SDKProvider._sdk_registered_tools = [tool]
        try:
            registry = EnhancedToolRegistry()
            result = registry.discover(SDKProvider())
            assert len(result) == 1
            assert result[0].name == "discovered_tool"
            assert registry.get_tool("discovered_tool") is not None
        finally:
            SDKProvider._sdk_registered_tools = []

    def test_reload_provider_removes_and_rediscovers(self):
        from tools.registry import (
            EnhancedToolRegistry,
            SDKProvider,
        )

        tool = _make_tool(name="reloaded_tool")
        SDKProvider._sdk_registered_tools = [tool]
        try:
            registry = EnhancedToolRegistry()
            registry.discover(SDKProvider())
            # Change what discover returns
            tool2 = _make_tool(name="reloaded_tool_v2")
            SDKProvider._sdk_registered_tools = [tool2]
            result = registry.reload_provider("sdk")
            assert len(result) == 1
            assert result[0].name == "reloaded_tool_v2"
        finally:
            SDKProvider._sdk_registered_tools = []

    def test_reload_provider_unknown_name_returns_empty(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        result = registry.reload_provider("nonexistent")
        assert result == []


# ---------------------------------------------------------------------------
# Test: DeclarativeProvider and OpenAPIProvider stubs
# ---------------------------------------------------------------------------


class TestProviderStubs:
    def test_declarative_provider_provider_name(self):
        from tools.registry import DeclarativeProvider

        provider = DeclarativeProvider()
        assert provider.provider_name == "declarative"

    def test_declarative_provider_discover(self):
        from tools.registry import DeclarativeProvider

        provider = DeclarativeProvider()
        tools = asyncio.run(provider.discover())
        assert tools == []

    def test_openapi_provider_provider_name(self):
        from tools.registry import OpenAPIProvider

        provider = OpenAPIProvider()
        assert provider.provider_name == "openapi"

    def test_openapi_provider_discover(self):
        from tools.registry import OpenAPIProvider

        provider = OpenAPIProvider()
        tools = asyncio.run(provider.discover())
        assert tools == []


class TestGetToolsForLLM:
    """Tests for get_tools_for_llm method."""

    def test_anthropic_format(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(name="search", description="Search tool")
        registry.register(tool)
        tools = registry.get_tools_for_llm(provider_type="anthropic")
        assert len(tools) == 1

    def test_unknown_provider_defaults_to_openai(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(name="search", description="Search tool")
        registry.register(tool)
        tools = registry.get_tools_for_llm(provider_type="unknown")
        assert len(tools) == 1

    def test_respects_role_visibility(self):
        from tools.definition import ToolVisibility
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        public_tool = _make_tool(name="public_search", visibility=ToolVisibility.PUBLIC)
        admin_tool = _make_tool(name="admin_tool", visibility=ToolVisibility.ADMIN)
        registry.register(public_tool)
        registry.register(admin_tool)
        tools = registry.get_tools_for_llm(user_role="admin")
        assert len(tools) == 2
        tools_user = registry.get_tools_for_llm(user_role="user")
        assert len(tools_user) == 1


class TestExecuteNonString:
    """Tests for execute methods when handler returns non-string."""

    def test_execute_returns_non_string(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()

        def int_handler(**kw):
            return 42

        tool = _make_tool(
            name="int_tool",
            handler=int_handler,
            parameters=[],
        )
        registry.register(tool)
        result = registry.execute("int_tool", {})
        assert result.content == "42"

    @pytest.mark.asyncio
    async def test_execute_async_returns_non_string(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()

        async def int_async_handler(**kw):
            return 42

        tool = _make_tool(
            name="async_int_tool",
            handler=lambda **kw: "sync",
            async_handler=int_async_handler,
            parameters=[],
        )
        registry.register(tool)
        result = await registry.execute_async("async_int_tool", {})
        assert result.content == "42"


class TestValidateTool:
    """Tests for validate_tool method."""

    def test_validate_tool_with_issues(self):
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(name="", description="", handler=None, async_handler=None)
        issues = registry.validate_tool(tool)
        assert len(issues) >= 2

    def test_validate_tool_duplicate_params(self):
        from tools.definition import ToolParam
        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        tool = _make_tool(
            name="dup_params",
            description="Has duplicate params",
            parameters=[
                ToolParam(name="q", type=str),
                ToolParam(name="q", type=int),
            ],
        )
        issues = registry.validate_tool(tool)
        assert "Duplicate" in " ".join(issues)


class TestDiscoverSync:
    """Tests for sync discover method."""

    def test_discover_success(self):
        from tools.registry import EnhancedToolRegistry, SDKProvider

        registry = EnhancedToolRegistry()
        tool = _make_tool(name="discovered_tool")
        try:
            SDKProvider._sdk_registered_tools = [tool]
            result = registry.discover(SDKProvider())
            assert len(result) == 1
        finally:
            SDKProvider._sdk_registered_tools = []

    def test_discover_error_handling(self):
        from unittest.mock import MagicMock

        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        bad_provider = MagicMock()
        bad_provider.provider_name = "bad"
        bad_provider.discover = MagicMock(side_effect=RuntimeError("discovery failed"))
        result = registry.discover(bad_provider)
        assert result == []

    def test_discover_from_provider_alias(self):
        from unittest.mock import MagicMock

        from tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.discover = MagicMock(return_value=[])
        result = registry.discover_from_provider(mock_provider)
        assert result == []
