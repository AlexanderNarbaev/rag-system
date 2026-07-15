# ruff: noqa: E501, E402
"""Tests for proxy/app/tools/registry.py — additional coverage."""

from unittest.mock import AsyncMock

import pytest

from proxy.app.tools.definition import ToolDefinition, ToolParam, ToolVisibility
from proxy.app.tools.registry import (
  DeclarativeProvider,
  EnhancedToolRegistry,
  OpenAPIProvider,
  SDKProvider,
  _visible_for_role,
  get_enhanced_registry,
)


class TestVisibleForRole:
  def test_public_visible_to_none (self):
    assert _visible_for_role (ToolVisibility.PUBLIC, None) is True

  def test_admin_visible_to_none (self):
    assert _visible_for_role (ToolVisibility.ADMIN, None) is False

  def test_public_visible_to_admin (self):
    assert _visible_for_role (ToolVisibility.PUBLIC, "admin") is True

  def test_admin_visible_to_admin (self):
    assert _visible_for_role (ToolVisibility.ADMIN, "admin") is True

  def test_admin_not_visible_to_user (self):
    assert _visible_for_role (ToolVisibility.ADMIN, "user") is False

  def test_expert_visible_to_expert (self):
    assert _visible_for_role (ToolVisibility.EXPERT, "expert") is True

  def test_read_only_sees_only_public (self):
    assert _visible_for_role (ToolVisibility.PUBLIC, "read_only") is True
    assert _visible_for_role (ToolVisibility.USER, "read_only") is False


class TestEnhancedToolRegistry:
  def setup_method (self):
    self.registry = EnhancedToolRegistry ()

  def test_register_and_get (self):
    tool = ToolDefinition (name = "test_tool", description = "desc", handler = lambda: "ok")
    self.registry.register (tool)
    assert self.registry.get_tool ("test_tool") is not None

  def test_get_alias (self):
    tool = ToolDefinition (name = "alias_tool", description = "desc", handler = lambda: "ok")
    self.registry.register (tool)
    assert self.registry.get ("alias_tool") is not None

  def test_unregister (self):
    tool = ToolDefinition (name = "del_tool", description = "desc", handler = lambda: "ok", provider = "test")
    self.registry.register (tool)
    assert self.registry.unregister ("del_tool") is True
    assert self.registry.get_tool ("del_tool") is None

  def test_unregister_nonexistent (self):
    assert self.registry.unregister ("no_such_tool") is False

  def test_get_all (self):
    self.registry.register (ToolDefinition (name = "t1", description = "d", handler = lambda: ""))
    self.registry.register (ToolDefinition (name = "t2", description = "d", handler = lambda: ""))
    assert len (self.registry.get_all ()) == 2

  def test_list_all (self):
    self.registry.register (ToolDefinition (name = "t3", description = "d", handler = lambda: ""))
    assert len (self.registry.list_all ()) >= 1

  def test_list_tools_by_category (self):
    self.registry.register (ToolDefinition (name = "c1", description = "d", handler = lambda: "", category = "search"))
    self.registry.register (ToolDefinition (name = "c2", description = "d", handler = lambda: "", category = "action"))
    result = self.registry.list_tools (category = "search")
    assert len (result) == 1

  def test_list_tools_by_tags (self):
    self.registry.register (ToolDefinition (name = "tag1", description = "d", handler = lambda: "", tags = ["a", "b"]))
    result = self.registry.list_tools (tags = ["a"])
    assert len (result) == 1

  def test_list_tools_by_provider (self):
    self.registry.register (ToolDefinition (name = "p1", description = "d", handler = lambda: "", provider = "sdk"))
    result = self.registry.list_tools (provider = "sdk")
    assert len (result) >= 1

  def test_list_tools_by_visibility (self):
    self.registry.register (
        ToolDefinition (name = "v1", description = "d", handler = lambda: "", visibility = ToolVisibility.PUBLIC))
    result = self.registry.list_tools (visibility_filter = "user")
    assert len (result) >= 1

  def test_execute_success (self):
    def handler (x: str):
      return f"result: {x}"

    tool = ToolDefinition (name = "exec", description = "d", handler = handler,
        parameters = [ToolParam (name = "x", type = str, description = "input", required = True)], )
    self.registry.register (tool)
    result = self.registry.execute ("exec", {"x": "hello"})
    assert result.content == "result: hello"
    assert result.duration_ms > 0

  def test_execute_not_found (self):
    result = self.registry.execute ("nope", {})
    assert "not found" in result.error

  def test_execute_missing_param (self):
    tool = ToolDefinition (name = "req", description = "d", handler = lambda x: x,
        parameters = [ToolParam (name = "x", type = str, description = "input", required = True)], )
    self.registry.register (tool)
    result = self.registry.execute ("req", {})
    assert "Missing" in result.error

  def test_execute_no_handler (self):
    tool = ToolDefinition (name = "noh", description = "d")
    self.registry.register (tool)
    result = self.registry.execute ("noh", {})
    assert "no handler" in result.error

  def test_execute_exception (self):
    def bad_handler ():
      raise ValueError ("boom")

    tool = ToolDefinition (name = "bad", description = "d", handler = bad_handler)
    self.registry.register (tool)
    result = self.registry.execute ("bad", {})
    assert "boom" in result.error

  @pytest.mark.asyncio
  async def test_execute_async_success (self):
    async def ah (x: str):
      return f"async: {x}"

    tool = ToolDefinition (name = "async_t", description = "d", async_handler = ah,
        parameters = [ToolParam (name = "x", type = str, description = "input", required = True)], )
    self.registry.register (tool)
    result = await self.registry.execute_async ("async_t", {"x": "world"})
    assert result.content == "async: world"

  @pytest.mark.asyncio
  async def test_execute_async_not_found (self):
    result = await self.registry.execute_async ("none", {})
    assert "not found" in result.error

  @pytest.mark.asyncio
  async def test_execute_async_missing_param (self):
    tool = ToolDefinition (name = "async_req", description = "d", async_handler = AsyncMock (),
        parameters = [ToolParam (name = "x", type = str, description = "input", required = True)], )
    self.registry.register (tool)
    result = await self.registry.execute_async ("async_req", {})
    assert "Missing" in result.error

  @pytest.mark.asyncio
  async def test_execute_async_no_handler (self):
    tool = ToolDefinition (name = "async_noh", description = "d")
    self.registry.register (tool)
    result = await self.registry.execute_async ("async_noh", {})
    assert "no handler" in result.error

  @pytest.mark.asyncio
  async def test_execute_async_fallback_to_sync (self):
    def sync_handler ():
      return "sync fallback"

    tool = ToolDefinition (name = "sync_fb", description = "d", handler = sync_handler)
    self.registry.register (tool)
    result = await self.registry.execute_async ("sync_fb", {})
    assert result.content == "sync fallback"

  @pytest.mark.asyncio
  async def test_execute_async_exception (self):
    async def bad ():
      raise RuntimeError ("async boom")

    tool = ToolDefinition (name = "async_bad", description = "d", async_handler = bad)
    self.registry.register (tool)
    result = await self.registry.execute_async ("async_bad", {})
    assert "async boom" in result.error

  def test_get_tools_for_llm_openai (self):
    self.registry.register (
        ToolDefinition (name = "llm1", description = "d", handler = lambda: "", visibility = ToolVisibility.PUBLIC))
    tools = self.registry.get_tools_for_llm (provider_type = "openai", user_role = "user")
    assert len (tools) >= 1

  def test_get_tools_for_llm_anthropic (self):
    self.registry.register (
        ToolDefinition (name = "llm2", description = "d", handler = lambda: "", visibility = ToolVisibility.PUBLIC))
    tools = self.registry.get_tools_for_llm (provider_type = "anthropic", user_role = "user")
    assert len (tools) >= 1

  def test_validate_tool_valid (self):
    tool = ToolDefinition (name = "valid", description = "desc", handler = lambda: "")
    issues = self.registry.validate_tool (tool)
    assert len (issues) == 0

  def test_validate_tool_no_name (self):
    tool = ToolDefinition (name = "", description = "desc", handler = lambda: "")
    issues = self.registry.validate_tool (tool)
    assert "name" in issues [0].lower ()

  def test_validate_tool_no_description (self):
    tool = ToolDefinition (name = "t", description = "", handler = lambda: "")
    issues = self.registry.validate_tool (tool)
    assert "description" in issues [0].lower ()

  def test_validate_tool_no_handler (self):
    tool = ToolDefinition (name = "t", description = "d")
    issues = self.registry.validate_tool (tool)
    assert "handler" in issues [0].lower ()

  def test_validate_tool_duplicate_params (self):
    tool = ToolDefinition (name = "t", description = "d", handler = lambda: "", parameters = [
        ToolParam (name = "x", type = str, description = "a"), ToolParam (name = "x", type = str, description = "b"),
    ], )
    issues = self.registry.validate_tool (tool)
    assert any ("duplicate" in i.lower () for i in issues)

  def test_get_dependency_graph (self):
    self.registry.register (
      ToolDefinition (name = "dep1", description = "d", handler = lambda: "", depends_on = ["dep2"]))
    graph = self.registry.get_dependency_graph ()
    assert "dep1" in graph

  def test_list_by_category (self):
    self.registry.register (
      ToolDefinition (name = "cat1", description = "d", handler = lambda: "", category = "test_cat"))
    result = self.registry.list_by_category ("test_cat")
    assert len (result) >= 1


class TestProviders:
  @pytest.mark.asyncio
  async def test_sdk_provider (self):
    provider = SDKProvider ()
    tools = await provider.discover ()
    assert isinstance (tools, list)
    assert provider.provider_name == "sdk"

  @pytest.mark.asyncio
  async def test_declarative_provider (self):
    provider = DeclarativeProvider ()
    tools = await provider.discover ()
    assert tools == []
    assert provider.provider_name == "declarative"

  @pytest.mark.asyncio
  async def test_openapi_provider_stub (self):
    provider = OpenAPIProvider ()
    tools = await provider.discover ()
    assert tools == []
    assert provider.provider_name == "openapi"


class TestSingleton:
  def test_get_instance (self):
    r1 = EnhancedToolRegistry.get_instance ()
    r2 = EnhancedToolRegistry.get_instance ()
    assert r1 is r2

  def test_get_enhanced_registry (self):
    r = get_enhanced_registry ()
    assert isinstance (r, EnhancedToolRegistry)
