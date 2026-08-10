"""Comprehensive tests for proxy/app/tools/_legacy.py.

Covers the deprecated ToolRegistry + ToolDefinition + ToolResult dataclasses,
format_tools_for_llm, execute_tool, handle_function_call, built-in
search helpers, and get_tool_registry singleton.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from proxy.app.tools._legacy import (
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    _get_document_metadata,
    _search_by_version,
    _search_documents,
    execute_tool,
    format_tools_for_llm,
    get_tool_registry,
    handle_function_call,
)

# ---------------------------------------------------------------------------
# ToolDefinition + ToolResult dataclasses
# ---------------------------------------------------------------------------


class TestToolDefinition:
    def test_minimal(self):
        t = ToolDefinition(
            name="t",
            description="d",
            parameters_schema={"type": "object"},
            handler=lambda: None,
        )
        assert t.name == "t"
        assert t.category == "general"
        assert t.is_async is False

    def test_full(self):
        async def handler():
            return "x"

        t = ToolDefinition(
            name="t",
            description="d",
            parameters_schema={},
            handler=handler,
            category="cat",
            is_async=True,
        )
        assert t.is_async is True
        assert t.category == "cat"


class TestToolResult:
    def test_defaults(self):
        r = ToolResult(name="t", content="c")
        assert r.tool_call_id == ""
        assert r.error is None

    def test_with_error(self):
        r = ToolResult(name="t", content="", error="e")
        assert r.error == "e"


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_init_empty(self):
        reg = ToolRegistry()
        assert reg.list_tools() == []
        assert reg.get_all() == []

    def test_register(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(name="t", description="d", parameters_schema={}, handler=lambda: None))
        assert "t" in reg.list_tools()

    def test_register_replaces(self):
        reg = ToolRegistry()

        def h1():
            return 1

        def h2():
            return 2

        reg.register(ToolDefinition(name="t", description="d", parameters_schema={}, handler=h1))
        reg.register(ToolDefinition(name="t", description="d", parameters_schema={}, handler=h2))
        assert reg.get_tool("t").handler is h2

    def test_unregister_existing(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(name="t", description="d", parameters_schema={}, handler=lambda: None))
        assert reg.unregister("t") is True
        assert reg.get_tool("t") is None

    def test_unregister_unknown(self):
        reg = ToolRegistry()
        assert reg.unregister("ghost") is False

    def test_get_tool_unknown(self):
        reg = ToolRegistry()
        assert reg.get_tool("ghost") is None

    def test_list_tools(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(name="a", description="d", parameters_schema={}, handler=lambda: None))
        reg.register(ToolDefinition(name="b", description="d", parameters_schema={}, handler=lambda: None))
        assert set(reg.list_tools()) == {"a", "b"}

    def test_get_all(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(name="a", description="d", parameters_schema={}, handler=lambda: None))
        assert len(reg.get_all()) == 1


# ---------------------------------------------------------------------------
# format_tools_for_llm
# ---------------------------------------------------------------------------


class TestFormatToolsForLLM:
    def test_empty(self):
        assert format_tools_for_llm([]) == []

    def test_single_tool(self):
        t = ToolDefinition(
            name="t",
            description="d",
            parameters_schema={"type": "object"},
            handler=lambda: None,
        )
        out = format_tools_for_llm([t])
        assert len(out) == 1
        assert out[0]["type"] == "function"
        assert out[0]["function"]["name"] == "t"
        assert out[0]["function"]["description"] == "d"


# ---------------------------------------------------------------------------
# execute_tool
# ---------------------------------------------------------------------------


class TestExecuteTool:
    def test_unknown_tool(self):
        reg = ToolRegistry()
        result = execute_tool("missing", {}, reg)
        assert "not found" in (result.error or "")

    def test_happy_path(self):
        reg = ToolRegistry()

        def handler(x: int) -> str:
            return f"got {x}"

        reg.register(
            ToolDefinition(
                name="t",
                description="d",
                parameters_schema={},
                handler=handler,
            ),
        )
        result = execute_tool("t", {"x": 5}, reg)
        assert result.content == "got 5"
        assert result.error is None

    def test_handler_exception(self):
        reg = ToolRegistry()

        def bad():
            raise RuntimeError("boom")

        reg.register(
            ToolDefinition(name="t", description="d", parameters_schema={}, handler=bad),
        )
        result = execute_tool("t", {}, reg)
        assert "boom" in (result.error or "")

    def test_stringifies_non_str(self):
        reg = ToolRegistry()

        def handler():
            return {"key": "value"}

        reg.register(
            ToolDefinition(name="t", description="d", parameters_schema={}, handler=handler),
        )
        result = execute_tool("t", {}, reg)
        assert "key" in result.content


# ---------------------------------------------------------------------------
# handle_function_call
# ---------------------------------------------------------------------------


class TestHandleFunctionCall:
    def test_missing_function_name(self):
        reg = ToolRegistry()
        call = {"id": "c1", "function": {"name": ""}}
        result = handle_function_call(call, reg)
        assert "Missing function name" in (result.error or "")

    def test_invalid_json_arguments(self):
        reg = ToolRegistry()
        call = {"id": "c1", "function": {"name": "t", "arguments": "{bad json"}}
        result = handle_function_call(call, reg)
        assert "Invalid JSON" in (result.error or "")

    def test_dict_arguments(self):
        reg = ToolRegistry()

        def handler(x):
            return f"got {x}"

        reg.register(
            ToolDefinition(name="t", description="d", parameters_schema={}, handler=handler),
        )
        call = {
            "id": "c1",
            "function": {"name": "t", "arguments": {"x": 1}},
        }
        result = handle_function_call(call, reg)
        assert result.tool_call_id == "c1"
        assert result.content == "got 1"

    def test_valid_json_arguments_string(self):
        reg = ToolRegistry()

        def handler():
            return "ok"

        reg.register(
            ToolDefinition(name="t", description="d", parameters_schema={}, handler=handler),
        )
        call = {"id": "c1", "function": {"name": "t", "arguments": "{}"}}
        result = handle_function_call(call, reg)
        assert result.content == "ok"


# ---------------------------------------------------------------------------
# Built-in search tools
# ---------------------------------------------------------------------------


class TestSearchDocuments:
    def test_no_results(self):
        with patch("proxy.app.core.retrieval.hybrid_search", return_value=[]) as mock_search:
            result = _search_documents("query")
        assert "No documents" in result
        mock_search.assert_called_once()

    def test_with_results(self):
        class Hit:
            def __init__(self, payload, score):
                self.payload = payload
                self.score = score

        hits = [
            Hit({"title": "Doc1", "text": "Body text", "source_type": "confluence"}, 0.9),
        ]
        with patch("proxy.app.core.retrieval.hybrid_search", return_value=hits):
            result = _search_documents("query")
        assert "Doc1" in result
        assert "Body text" in result

    def test_search_failure(self):
        with patch(
            "proxy.app.core.retrieval.hybrid_search",
            side_effect=RuntimeError("boom"),
        ):
            result = _search_documents("query")
        assert "Search failed" in result

    def test_falls_back_to_doc_title(self):
        class Hit:
            def __init__(self, payload, score):
                self.payload = payload
                self.score = score

        hits = [
            Hit({"doc_title": "Title", "text": "Body", "source_type": "wiki"}, 0.5),
        ]
        with patch("proxy.app.core.retrieval.hybrid_search", return_value=hits):
            result = _search_documents("q")
        assert "Title" in result


class TestSearchByVersion:
    def test_no_results(self):
        with patch("proxy.app.core.retrieval.hybrid_search", return_value=[]):
            result = _search_by_version("v1")
        assert "No documents found for version 'v1'" in result

    def test_with_results(self):
        class Hit:
            def __init__(self, payload, score):
                self.payload = payload
                self.score = score

        hits = [Hit({"title": "Doc", "text": "Body", "version": "1.2"}, 0.9)]
        with patch("proxy.app.core.retrieval.hybrid_search", return_value=hits):
            result = _search_by_version("v1")
        assert "Doc" in result

    def test_search_failure(self):
        with patch(
            "proxy.app.core.retrieval.hybrid_search",
            side_effect=RuntimeError("bad"),
        ):
            result = _search_by_version("v1")
        assert "Version search failed" in result

    def test_uses_default_query_when_none(self):
        with patch("proxy.app.core.retrieval.hybrid_search", return_value=[]) as mock:
            _search_by_version("v1", query=None)
        # First positional arg should be 'v1' (used as default query)
        args, kwargs = mock.call_args
        assert "v1" in (args[0] if args else kwargs.get("query", ""))


class TestGetDocumentMetadata:
    def test_document_not_found(self):
        with patch("qdrant_client.QdrantClient") as mock_cls:
            client = mock_cls.return_value
            client.retrieve.return_value = []
            result = _get_document_metadata("doc-1")
        assert "Document 'doc-1' not found" in result

    def test_metadata_returned(self):
        with patch("qdrant_client.QdrantClient") as mock_cls:
            client = mock_cls.return_value
            point = MagicMock()
            point.payload = {
                "title": "Title",
                "source_type": "wiki",
                "version": "1.0",
                "text": "Some body content for size calculation",
            }
            client.retrieve.return_value = [point]
            result = _get_document_metadata("doc-1")
        parsed = json.loads(result)
        assert parsed["id"] == "doc-1"
        assert parsed["title"] == "Title"
        assert parsed["source"] == "wiki"

    def test_metadata_lookup_failure(self):
        with patch("qdrant_client.QdrantClient", side_effect=ImportError("no qdrant")):
            result = _get_document_metadata("doc-1")
        assert "Metadata lookup failed" in result


# ---------------------------------------------------------------------------
# get_tool_registry singleton
# ---------------------------------------------------------------------------


class TestGetToolRegistry:
    def test_returns_registry(self, monkeypatch):
        # Reset the global registry inside the tools package
        import proxy.app.tools as tools_pkg

        monkeypatch.setattr(tools_pkg, "_global_registry", None)
        monkeypatch.setattr(tools_pkg, "TOOLS_ENABLED", False)

        reg = get_tool_registry()
        assert isinstance(reg, ToolRegistry)

    def test_singleton(self, monkeypatch):
        import proxy.app.tools as tools_pkg

        monkeypatch.setattr(tools_pkg, "_global_registry", None)
        monkeypatch.setattr(tools_pkg, "TOOLS_ENABLED", False)

        a = get_tool_registry()
        b = get_tool_registry()
        assert a is b

    def test_tools_disabled_no_builtins(self, monkeypatch):
        import proxy.app.tools as tools_pkg

        monkeypatch.setattr(tools_pkg, "_global_registry", None)
        monkeypatch.setattr(tools_pkg, "TOOLS_ENABLED", False)
        reg = get_tool_registry()
        # TOOLS_ENABLED=False → no builtins registered
        assert reg.list_tools() == []

    def test_tools_enabled_registers_builtins(self, monkeypatch):
        import proxy.app.tools as tools_pkg

        monkeypatch.setattr(tools_pkg, "_global_registry", None)
        monkeypatch.setattr(tools_pkg, "TOOLS_ENABLED", True)
        reg = get_tool_registry()
        names = reg.list_tools()
        assert "search_documents" in names
        assert "search_by_version" in names
        assert "get_document_metadata" in names
