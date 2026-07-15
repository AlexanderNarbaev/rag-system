# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/tools backward compatibility — Task 3 TDD.

Verifies that:
1. Old-style import from proxy.app.tools package works for legacy ToolDefinition
2. New import path (proxy.app.tools.definition) works
3. format_tools_for_llm handles both old and new ToolDefinition styles
4. get_tool_registry() returns a registry singleton
5. tools package re-exports all public symbols from errors.py
"""

from proxy.app.tools import (
  ToolDefinition,
  ToolRegistry,
  format_tools_for_llm,
  get_tool_registry,
)
from proxy.app.tools.definition import (
  ToolDefinition as NewToolDefinition,
)
from proxy.app.tools.definition import (
  ToolParam,
)


class TestNewImportPath:
  """Test 2: Import from proxy.app.tools.definition (new path) works."""

  def test_import_tool_definition_from_definition_module (self):
    from proxy.app.tools.definition import ToolDefinition as TD

    td = TD (name = "test", description = "Test tool",
        parameters = [ToolParam (name = "query", type = str, description = "Query")], )
    assert td.name == "test"
    assert td.to_openai_format () ["type"] == "function"

  def test_import_tool_param (self):
    from proxy.app.tools.definition import ToolParam as TP

    p = TP (name = "x", type = int, description = "An integer")
    schema = p.to_json_schema_property ()
    assert schema ["type"] == "integer"

  def test_import_tool_result (self):
    from proxy.app.tools.definition import ToolResult

    r = ToolResult (tool_name = "test", content = "done")
    assert r.status == "success"
    assert r.name == "test"

  def test_import_tool_call (self):
    from proxy.app.tools.definition import ToolCall

    tc = ToolCall (id = "call_1", name = "search", arguments = {"q": "test"})
    assert tc.id == "call_1"
    assert tc.arguments == {"q": "test"}

  def test_import_errors_from_package (self):
    from proxy.app.tools import (
      ToolError,
      ToolNotFoundError,
      ToolValidationError,
      classify_error,
    )

    err = ToolNotFoundError (tool_name = "missing")
    assert err.retryable is False
    assert isinstance (err, ToolError)

    classified = classify_error (tool_name = "t", error = ValueError ("bad"), tool_call_id = "c1")
    assert isinstance (classified, ToolValidationError)


class TestOldImportPath:
  """Test 1: Import from proxy.app.tools (package) with old-style ToolDefinition."""

  def test_import_tool_definition_from_package (self):
    td = ToolDefinition (name = "test", description = "Test", parameters_schema = {
        "type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"],
    }, handler = lambda q: f"Result: {q}", )
    assert td.name == "test"
    assert td.parameters_schema ["required"] == ["q"]

  def test_import_tool_registry_from_package (self):
    reg = ToolRegistry ()
    assert isinstance (reg, ToolRegistry)
    assert reg.list_tools () == []


class TestFormatToolsForLLM:
  """Test 3: format_tools_for_llm works with old and new ToolDefinition."""

  def test_format_old_style_tool_definition (self):
    td = ToolDefinition (name = "search", description = "Search documents", parameters_schema = {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
    }, handler = lambda query: f"Found: {query}", )
    formatted = format_tools_for_llm ([td])
    assert len (formatted) == 1
    assert formatted [0] ["type"] == "function"
    assert formatted [0] ["function"] ["name"] == "search"
    assert "query" in formatted [0] ["function"] ["parameters"] ["properties"]

  def test_format_handles_new_style_tool_definition (self):
    td = NewToolDefinition (name = "greet", description = "Greet someone",
        parameters = [ToolParam (name = "name", type = str, description = "Name")], )
    formatted = format_tools_for_llm ([td])
    assert len (formatted) == 1
    assert formatted [0] ["type"] == "function"
    assert formatted [0] ["function"] ["name"] == "greet"
    assert formatted [0] ["function"] ["parameters"] ["required"] == ["name"]


class TestGetToolRegistry:
  """Test 4: get_tool_registry() returns a registry singleton."""

  def test_registry_returns_valid_registry (self):
    reg = get_tool_registry ()
    assert isinstance (reg, ToolRegistry)

  def test_registry_singleton (self):
    import proxy.app.tools as pkg

    pkg._global_registry = None
    r1 = get_tool_registry ()
    r2 = get_tool_registry ()
    assert r1 is r2
    pkg._global_registry = None

  def test_registry_has_builtin_tools_when_enabled (self):
    import proxy.app.tools as pkg

    pkg._global_registry = None
    pkg.TOOLS_ENABLED = True
    try:
      reg = get_tool_registry ()
      tools = reg.list_tools ()
      assert "search_documents" in tools
      assert "search_by_version" in tools
      assert "get_document_metadata" in tools
    finally:
      pkg._global_registry = None
      pkg.TOOLS_ENABLED = False
