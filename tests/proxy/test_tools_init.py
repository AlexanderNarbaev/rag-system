"""Tests for proxy/app/tools/__init__.py — tool registry and formatting."""

from proxy.app.tools import (
    EnhancedToolRegistry,
    ToolVisibility,
    _ensure_registries,
    format_tools_for_llm,
    get_enhanced_registry,
    get_tool_registry,
)


class TestToolRegistry:
    """Tests for get_tool_registry."""

    def test_returns_registry(self):
        reg = get_tool_registry()
        assert reg is not None

    def test_registry_has_list(self):
        reg = get_tool_registry()
        tools = reg.list_tools()
        assert isinstance(tools, list)


class TestEnhancedToolRegistry:
    """Tests for EnhancedToolRegistry."""

    def test_init(self):
        reg = EnhancedToolRegistry()
        assert reg.list_tools() == []

    def test_get_all(self):
        reg = EnhancedToolRegistry()
        assert reg.get_all() == []

    def test_get_all_openai(self):
        reg = EnhancedToolRegistry()
        assert reg.get_all_openai() == []

    def test_get_all_anthropic(self):
        reg = EnhancedToolRegistry()
        assert reg.get_all_anthropic() == []

    def test_get_tool_missing(self):
        reg = EnhancedToolRegistry()
        assert reg.get_tool("nonexistent") is None

    def test_unregister_missing(self):
        reg = EnhancedToolRegistry()
        assert reg.unregister("nonexistent") is False


class TestGetEnhancedRegistry:
    """Tests for get_enhanced_registry."""

    def test_returns_registry(self):
        reg = get_enhanced_registry()
        assert reg is not None
        assert isinstance(reg, EnhancedToolRegistry)


class TestEnsureRegistries:
    """Tests for _ensure_registries."""

    def test_returns_tuple(self):
        result = _ensure_registries()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_both_registries(self):
        legacy, enhanced = _ensure_registries()
        assert legacy is not None
        assert enhanced is not None


class TestFormatToolsForLLM:
    """Tests for format_tools_for_llm."""

    def test_empty_list(self):
        result = format_tools_for_llm([])
        assert result == []


class TestToolVisibility:
    """Tests for ToolVisibility enum."""

    def test_public(self):
        assert ToolVisibility.PUBLIC.value == "public"

    def test_admin(self):
        assert ToolVisibility.ADMIN.value == "admin"
