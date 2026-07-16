"""Tests for proxy/app/tools.py — Tool registry and function calling handler."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


# ── F1: ToolDefinition and ToolRegistry ──


class TestToolDefinition:
    def test_creates_with_required_fields(self):
        from proxy.app.tools import ToolDefinition

        def handler(**kwargs):
            return "result"

        td = ToolDefinition(
            name="search_docs",
            description="Search documents",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=handler,
        )
        assert td.name == "search_docs"
        assert td.description == "Search documents"
        assert td.parameters_schema["required"] == ["query"]
        assert td.handler is handler
        assert callable(td.handler)

    def test_creates_with_optional_fields(self):
        from proxy.app.tools import ToolDefinition

        td = ToolDefinition(
            name="test",
            description="Test tool",
            parameters_schema={},
            handler=lambda: None,
            category="search",
            is_async=False,
        )
        assert td.category == "search"
        assert td.is_async is False


class TestToolRegistry:
    @pytest.fixture
    def registry(self):
        from proxy.app.tools import ToolRegistry

        reg = ToolRegistry()
        return reg

    @pytest.fixture
    def sample_tool(self):
        from proxy.app.tools import ToolDefinition

        return ToolDefinition(
            name="greet",
            description="Greet someone",
            parameters_schema={"type": "object", "properties": {"name": {"type": "string"}}},
            handler=lambda name="World": f"Hello, {name}!",
        )

    def test_register_tool(self, registry, sample_tool):
        registry.register(sample_tool)
        assert "greet" in registry.list_tools()
        assert registry.get_tool("greet") is sample_tool

    def test_register_duplicate_overwrites(self, registry, sample_tool):
        from proxy.app.tools import ToolDefinition

        registry.register(sample_tool)
        new_tool = ToolDefinition(
            name="greet",
            description="Updated",
            parameters_schema={},
            handler=lambda: "new",
        )
        registry.register(new_tool)
        assert registry.get_tool("greet").description == "Updated"

    def test_unregister_tool(self, registry, sample_tool):
        registry.register(sample_tool)
        result = registry.unregister("greet")
        assert result is True
        assert "greet" not in registry.list_tools()

    def test_unregister_nonexistent(self, registry):
        result = registry.unregister("no_such_tool")
        assert result is False

    def test_get_tool_nonexistent(self, registry):
        assert registry.get_tool("no_such_tool") is None

    def test_list_tools_empty(self, registry):
        assert registry.list_tools() == []

    def test_list_tools_returns_names(self, registry, sample_tool):
        registry.register(sample_tool)
        assert registry.list_tools() == ["greet"]


class TestExecuteTool:
    @pytest.fixture
    def registry(self):
        from proxy.app.tools import ToolRegistry

        reg = ToolRegistry()
        return reg

    def test_execute_sync_tool(self, registry):
        from proxy.app.tools import ToolDefinition, execute_tool

        def add(a: int, b: int) -> int:
            return a + b

        registry.register(
            ToolDefinition(
                name="add",
                description="Add two numbers",
                parameters_schema={
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                },
                handler=add,
            ),
        )
        result = execute_tool("add", {"a": 2, "b": 3}, registry)
        assert result.content == "5"

    def test_execute_tool_with_kwargs(self, registry):
        from proxy.app.tools import ToolDefinition, execute_tool

        def search(query: str, top_k: int = 5) -> str:
            return f"Found {top_k} results for '{query}'"

        registry.register(
            ToolDefinition(
                name="search",
                description="Search",
                parameters_schema={},
                handler=search,
            ),
        )
        result = execute_tool("search", {"query": "RAG", "top_k": 3}, registry)
        assert result.content == "Found 3 results for 'RAG'"

    def test_execute_tool_not_found(self, registry):
        from proxy.app.tools import execute_tool

        result = execute_tool("nonexistent", {}, registry)
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_execute_tool_handler_raises(self, registry):
        from proxy.app.tools import ToolDefinition, execute_tool

        def failing(**kwargs):
            raise ValueError("Something went wrong")

        registry.register(
            ToolDefinition(
                name="failing",
                description="Always fails",
                parameters_schema={},
                handler=failing,
            ),
        )
        result = execute_tool("failing", {}, registry)
        assert result.error is not None
        assert "Something went wrong" in result.error


class TestFormatToolsForLLM:
    def test_formats_single_tool(self):
        from proxy.app.tools import ToolDefinition, format_tools_for_llm

        td = ToolDefinition(
            name="search",
            description="Search documents",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            handler=lambda: None,
        )
        formatted = format_tools_for_llm([td])
        assert len(formatted) == 1
        assert formatted[0]["type"] == "function"
        assert formatted[0]["function"]["name"] == "search"
        assert formatted[0]["function"]["description"] == "Search documents"

    def test_formats_multiple_tools(self):
        from proxy.app.tools import ToolDefinition, format_tools_for_llm

        tools = [
            ToolDefinition(name="t1", description="D1", parameters_schema={}, handler=lambda: None),
            ToolDefinition(name="t2", description="D2", parameters_schema={}, handler=lambda: None),
        ]
        formatted = format_tools_for_llm(tools)
        assert len(formatted) == 2

    def test_formats_empty_list(self):
        from proxy.app.tools import format_tools_for_llm

        assert format_tools_for_llm([]) == []


class TestHandleFunctionCall:
    @pytest.fixture
    def registry(self):
        from proxy.app.tools import ToolDefinition, ToolRegistry

        reg = ToolRegistry()
        reg.register(
            ToolDefinition(
                name="echo",
                description="Echoes input",
                parameters_schema={},
                handler=lambda text: f"Echo: {text}",
            ),
        )
        return reg

    def test_handle_valid_function_call(self, registry):
        from proxy.app.tools import handle_function_call

        call = {
            "id": "call_001",
            "function": {"name": "echo", "arguments": '{"text": "hello"}'},
        }
        result = handle_function_call(call, registry)
        assert result.tool_call_id == "call_001"
        assert result.name == "echo"
        assert result.content == "Echo: hello"
        assert result.error is None

    def test_handle_function_call_tool_not_found(self, registry):
        from proxy.app.tools import handle_function_call

        call = {
            "id": "call_002",
            "function": {"name": "nonexistent", "arguments": "{}"},
        }
        result = handle_function_call(call, registry)
        assert result.error is not None
        assert "not found" in result.error.lower()

    def test_handle_function_call_missing_name(self, registry):
        from proxy.app.tools import handle_function_call

        call = {"id": "call_003", "function": {"arguments": "{}"}}
        result = handle_function_call(call, registry)
        assert result.error is not None

    def test_handle_function_call_bad_json_arguments(self, registry):
        from proxy.app.tools import handle_function_call

        call = {
            "id": "call_004",
            "function": {"name": "echo", "arguments": "not json"},
        }
        result = handle_function_call(call, registry)
        assert result.error is not None


# ── Built-in Tools ──


class TestBuiltinSearchDocuments:
    def test_search_documents_handler_returns_string(self):
        from proxy.app.tools import _search_documents

        with patch("proxy.app.core.retrieval.hybrid_search") as mock_hs:
            mock_result = MagicMock()
            mock_result.id = "chunk_1"
            mock_result.score = 0.95
            mock_result.payload = {"text": "This is a test chunk", "title": "Test", "source_type": "confluence"}
            mock_hs.return_value = [mock_result]

            result = _search_documents("test", top_k=3)
            assert "chunk_1" in result or "Test" in result or "test chunk" in result

    def test_search_documents_empty_results(self):
        from proxy.app.tools import _search_documents

        with patch("proxy.app.core.retrieval.hybrid_search", return_value=[]):
            result = _search_documents("nonexistent")
            assert "No documents found" in result

    def test_search_documents_error_graceful(self):
        from proxy.app.tools import _search_documents

        with patch("proxy.app.core.retrieval.hybrid_search", side_effect=Exception("Qdrant unavailable")):
            result = _search_documents("query")
            assert "Search failed" in result

    def test_search_by_version_returns_string(self):
        from proxy.app.tools import _search_by_version

        with patch("proxy.app.core.retrieval.hybrid_search") as mock_hs:
            mock_result = MagicMock()
            mock_result.id = "v1_chunk"
            mock_result.score = 0.9
            mock_result.payload = {"text": "Versioned content", "title": "Doc", "version": "2.0"}
            mock_hs.return_value = [mock_result]

            result = _search_by_version("2.0")
            assert "Versioned content" in result or "v1_chunk" in result

    def test_get_document_metadata_by_id(self):
        from proxy.app.tools import _get_document_metadata

        with patch("qdrant_client.QdrantClient") as mock_qc:
            mock_point = MagicMock()
            mock_point.payload = {"title": "Test Doc", "source_type": "confluence", "version": "1.0", "text": "Content"}
            mock_qc.return_value.retrieve.return_value = [mock_point]

            result = _get_document_metadata("test_id")
            assert "Test Doc" in result
            assert "confluence" in result


class TestGlobalRegistry:
    def test_get_registry_singleton(self):
        from proxy.app.tools import ToolRegistry, get_tool_registry

        r1 = get_tool_registry()
        r2 = get_tool_registry()
        assert r1 is r2
        assert isinstance(r1, ToolRegistry)

    def test_global_registry_has_builtin_tools_when_enabled(self):
        with patch("proxy.app.tools.TOOLS_ENABLED", True):
            # Reset singleton to pick up patched config
            import proxy.app.tools as tmod
            from proxy.app.tools import get_tool_registry

            tmod._global_registry = None

            reg = get_tool_registry()
            tools = reg.list_tools()
            assert "search_documents" in tools
            assert "search_by_version" in tools
            assert "get_document_metadata" in tools
