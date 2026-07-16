"""Targeted coverage tests for registry.py uncovered paths."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy" / "app"))

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.definition import ToolDefinition, ToolParam, ToolVisibility
from tools.registry import EnhancedToolRegistry, SDKProvider


def _make_tool(name, description="Test tool", handler=None, async_handler=None,
               parameters=None, visibility=ToolVisibility.PUBLIC):
    if parameters is None:
        parameters = [ToolParam(name="query", type=str, description="Query")]
    if handler is None:
        def handler(**kw):
            return f"Result: {kw}"
    return ToolDefinition(
        name=name, description=description, parameters=parameters,
        handler=handler, async_handler=async_handler,
        category="general", tags=[], visibility=visibility, provider="sdk",
    )


class TestDiscoverAll:
    """Tests for discover_all method."""

    @pytest.mark.asyncio
    async def test_discover_all_sdk_success(self):
        registry = EnhancedToolRegistry()

        mock_sdk = MagicMock()
        mock_sdk.provider_name = "sdk"
        mock_sdk.discover = AsyncMock(return_value=[])

        with patch("tools.registry.SDKProvider", return_value=mock_sdk):
            with patch("proxy.app.shared.config.TOOLS_DECLARATIVE_DIR", "/nonexistent"):
                with patch("proxy.app.shared.config.TOOLS_OPENAPI_SPECS", []):
                    with patch("os.path.isdir", return_value=False):
                        result = await registry.discover_all()

        assert "sdk" in result

    @pytest.mark.asyncio
    async def test_discover_all_sdk_error(self):
        registry = EnhancedToolRegistry()

        mock_sdk = MagicMock()
        mock_sdk.provider_name = "sdk"
        mock_sdk.discover = AsyncMock(side_effect=RuntimeError("fail"))

        with patch("tools.registry.SDKProvider", return_value=mock_sdk):
            with patch("proxy.app.shared.config.TOOLS_DECLARATIVE_DIR", "/nonexistent"):
                with patch("proxy.app.shared.config.TOOLS_OPENAPI_SPECS", []):
                    with patch("os.path.isdir", return_value=False):
                        result = await registry.discover_all()

        assert result["sdk"] == []


class TestDiscoverFromProvider:
    """Tests for discover/discover_from_provider."""

    def test_discover_from_provider_success(self):
        registry = EnhancedToolRegistry()
        mock_provider = MagicMock()
        mock_provider.provider_name = "mock"
        mock_provider.discover = MagicMock(return_value=[])
        result = registry.discover_from_provider(mock_provider)
        assert result == []

    def test_discover_error_handling(self):
        registry = EnhancedToolRegistry()
        bad_provider = MagicMock()
        bad_provider.provider_name = "bad"
        bad_provider.discover = MagicMock(side_effect=RuntimeError("fail"))
        result = registry.discover(bad_provider)
        assert result == []

    def test_discover_sync_success(self):
        registry = EnhancedToolRegistry()
        tool = _make_tool(name="sdk_tool")
        try:
            SDKProvider._sdk_registered_tools = [tool]
            result = registry.discover(SDKProvider())
            assert len(result) == 1
        finally:
            SDKProvider._sdk_registered_tools = []


class TestGetToolsForLLM:
    """Tests for get_tools_for_llm."""

    def test_anthropic_format(self):
        registry = EnhancedToolRegistry()
        tool = _make_tool(name="search")
        registry.register(tool)
        tools = registry.get_tools_for_llm(provider_type="anthropic")
        assert len(tools) == 1

    def test_unknown_format_defaults_to_openai(self):
        registry = EnhancedToolRegistry()
        tool = _make_tool(name="search")
        registry.register(tool)
        tools = registry.get_tools_for_llm(provider_type="unknown")
        assert len(tools) == 1


class TestExecuteEdgeCases:
    """Tests for execute/execute_async edge cases."""

    def test_execute_non_string_result(self):
        registry = EnhancedToolRegistry()

        def handler(**kw):
            return 42

        tool = _make_tool(name="int_tool", handler=handler, parameters=[])
        registry.register(tool)
        result = registry.execute("int_tool", {})
        assert result.content == "42"

    @pytest.mark.asyncio
    async def test_execute_async_non_string_result(self):
        registry = EnhancedToolRegistry()

        async def handler(**kw):
            return 99

        tool = _make_tool(
            name="async_int", handler=lambda **kw: "sync",
            async_handler=handler, parameters=[],
        )
        registry.register(tool)
        result = await registry.execute_async("async_int", {})
        assert result.content == "99"


class TestValidateToolEdge:
    """Tests for validate_tool."""

    def test_validate_empty_name_and_desc(self):
        registry = EnhancedToolRegistry()
        tool = _make_tool(name="", description="", handler=None, async_handler=None)
        issues = registry.validate_tool(tool)
        assert len(issues) >= 2

    def test_validate_duplicate_params(self):
        registry = EnhancedToolRegistry()
        tool = _make_tool(
            name="dup", description="has dups",
            parameters=[ToolParam(name="q", type=str), ToolParam(name="q", type=int)],
        )
        issues = registry.validate_tool(tool)
        assert "Duplicate" in " ".join(issues)


class TestDependencyGraph:
    """Tests for get_dependency_graph."""

    def test_dependency_graph(self):
        registry = EnhancedToolRegistry()
        t1 = _make_tool(name="tool1")
        t2 = ToolDefinition(
            name="tool2", description="dep tool",
            parameters=[ToolParam(name="q", type=str)],
            handler=lambda **kw: "ok",
            depends_on=["tool1"],
        )
        registry.register(t1)
        registry.register(t2)
        graph = registry.get_dependency_graph()
        assert graph["tool1"] == []
        assert graph["tool2"] == ["tool1"]


class TestReloadProviderEdge:
    """Tests for reload_provider."""

    def test_reload_provider_updates_tools(self):
        registry = EnhancedToolRegistry()
        tool = _make_tool(name="v1_tool")
        try:
            SDKProvider._sdk_registered_tools = [tool]
            registry.discover(SDKProvider())
            tool2 = _make_tool(name="v2_tool")
            SDKProvider._sdk_registered_tools = [tool2]
            result = registry.reload_provider("sdk")
            assert len(result) == 1
            assert result[0].name == "v2_tool"
        finally:
            SDKProvider._sdk_registered_tools = []

    def test_reload_unknown_provider(self):
        registry = EnhancedToolRegistry()
        result = registry.reload_provider("nonexistent")
        assert result == []
