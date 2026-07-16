"""Tests for proxy/app/tools/definition.py — Unified Data Models."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))


class TestToolVisibility:
    def test_enum_values(self):
        from tools.definition import ToolVisibility

        assert ToolVisibility.PUBLIC.value == "public"
        assert ToolVisibility.ADMIN.value == "admin"
        assert ToolVisibility.EXPERT.value == "expert"
        assert ToolVisibility.USER.value == "user"

    def test_enum_is_string_subclass(self):
        from tools.definition import ToolVisibility

        assert isinstance(ToolVisibility.PUBLIC, str)


class TestToolParam:
    def test_to_json_schema_property_str(self):
        from tools.definition import ToolParam

        param = ToolParam(name="query", type=str, description="Search query")
        schema = param.to_json_schema_property()
        assert schema == {"type": "string", "description": "Search query"}

    def test_to_json_schema_property_int(self):
        from tools.definition import ToolParam

        param = ToolParam(name="top_k", type=int, description="Max results")
        schema = param.to_json_schema_property()
        assert schema == {"type": "integer", "description": "Max results"}

    def test_to_json_schema_property_float(self):
        from tools.definition import ToolParam

        param = ToolParam(name="threshold", type=float, description="Score threshold")
        schema = param.to_json_schema_property()
        assert schema == {"type": "number", "description": "Score threshold"}

    def test_to_json_schema_property_bool(self):
        from tools.definition import ToolParam

        param = ToolParam(name="verbose", type=bool, description="Enable verbose output")
        schema = param.to_json_schema_property()
        assert schema == {"type": "boolean", "description": "Enable verbose output"}

    def test_to_json_schema_property_with_enum(self):
        from tools.definition import ToolParam

        param = ToolParam(name="sort", type=str, description="Sort order", enum=["asc", "desc"])
        schema = param.to_json_schema_property()
        assert schema == {"type": "string", "description": "Sort order", "enum": ["asc", "desc"]}

    def test_to_json_schema_property_array_with_items_type(self):
        from tools.definition import ToolParam

        param = ToolParam(name="tags", type=list, description="Filter tags", items_type=str)
        schema = param.to_json_schema_property()
        assert schema == {
            "type": "array",
            "description": "Filter tags",
            "items": {"type": "string"},
        }

    def test_to_json_schema_property_optional_with_default(self):
        from tools.definition import ToolParam

        param = ToolParam(name="top_k", type=int, description="Max results", required=False, default=5)
        schema = param.to_json_schema_property()
        assert schema == {"type": "integer", "description": "Max results", "default": 5}

    def test_to_json_schema_property_no_description(self):
        from tools.definition import ToolParam

        param = ToolParam(name="query", type=str)
        schema = param.to_json_schema_property()
        assert "description" not in schema


class TestToolDefinitionFormats:
    def test_to_openai_format_basic(self):
        from tools.definition import ToolDefinition, ToolParam

        td = ToolDefinition(
            name="search_docs",
            description="Search documents",
            parameters=[ToolParam(name="query", type=str, description="Search query")],
        )
        fmt = td.to_openai_format()
        assert fmt["type"] == "function"
        assert fmt["function"]["name"] == "search_docs"
        assert fmt["function"]["description"] == "Search documents"
        assert fmt["function"]["parameters"]["type"] == "object"
        assert "query" in fmt["function"]["parameters"]["properties"]
        assert fmt["function"]["parameters"]["required"] == ["query"]

    def test_to_openai_format_with_optional_params(self):
        from tools.definition import ToolDefinition, ToolParam

        td = ToolDefinition(
            name="search",
            description="Search",
            parameters=[
                ToolParam(name="query", type=str, description="Query"),
                ToolParam(name="top_k", type=int, description="Max results", required=False, default=5),
            ],
        )
        fmt = td.to_openai_format()
        assert fmt["function"]["parameters"]["required"] == ["query"]
        assert "top_k" in fmt["function"]["parameters"]["properties"]

    def test_to_anthropic_format(self):
        from tools.definition import ToolDefinition, ToolParam

        td = ToolDefinition(
            name="search_docs",
            description="Search documents",
            parameters=[ToolParam(name="query", type=str, description="Search query")],
        )
        fmt = td.to_anthropic_format()
        assert fmt["name"] == "search_docs"
        assert fmt["description"] == "Search documents"
        assert fmt["input_schema"]["type"] == "object"
        assert "query" in fmt["input_schema"]["properties"]
        assert fmt["input_schema"]["required"] == ["query"]

    def test_to_json_schema_standalone(self):
        from tools.definition import ToolDefinition, ToolParam

        td = ToolDefinition(
            name="search",
            description="Search",
            parameters=[ToolParam(name="query", type=str, description="Query")],
        )
        schema = td.to_json_schema()
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_to_openai_format_no_params_produces_empty_properties(self):
        from tools.definition import ToolDefinition

        td = ToolDefinition(name="ping", description="Health check", parameters=[])
        fmt = td.to_openai_format()
        assert fmt["function"]["parameters"]["type"] == "object"
        assert fmt["function"]["parameters"]["properties"] == {}
        assert fmt["function"]["parameters"]["required"] == []


class TestToolResult:
    def test_status_success(self):
        from tools.definition import ToolResult

        result = ToolResult(tool_name="search", content="Found 5 results")
        assert result.status == "success"

    def test_status_error(self):
        from tools.definition import ToolResult

        result = ToolResult(tool_name="search", content="", error="Not found")
        assert result.status == "error"

    def test_name_backward_compat_alias(self):
        from tools.definition import ToolResult

        result = ToolResult(tool_name="search", content="results")
        assert result.name == "search"

    def test_name_setter_raises(self):
        from tools.definition import ToolResult

        result = ToolResult(tool_name="search")
        with pytest.raises(AttributeError):
            result.name = "other"

    def test_defaults(self):
        from tools.definition import ToolResult

        result = ToolResult(tool_name="test")
        assert result.tool_call_id == ""
        assert result.content == ""
        assert result.error is None
        assert result.duration_ms == 0
        assert result.retry_count == 0


class TestToolCall:
    def test_create_with_defaults(self):
        from tools.definition import ToolCall

        tc = ToolCall(id="call_1", name="search")
        assert tc.id == "call_1"
        assert tc.name == "search"
        assert tc.arguments == {}

    def test_create_with_arguments(self):
        from tools.definition import ToolCall

        tc = ToolCall(id="call_2", name="search", arguments={"query": "test"})
        assert tc.arguments == {"query": "test"}


class TestRetryPolicy:
    def test_defaults(self):
        from tools.definition import RetryPolicy

        rp = RetryPolicy()
        assert rp.max_retries == 3
        assert rp.backoff == "exponential"
        assert rp.initial_delay_seconds == 1.0
        assert rp.jitter is True

    def test_custom_values(self):
        from tools.definition import RetryPolicy

        rp = RetryPolicy(max_retries=5, backoff="fixed", initial_delay_seconds=2.0, jitter=False)
        assert rp.max_retries == 5
        assert rp.backoff == "fixed"
        assert rp.initial_delay_seconds == 2.0
        assert rp.jitter is False


class TestToolErrorBase:
    def test_creates_with_defaults(self):
        from tools.definition import ToolErrorBase

        err = ToolErrorBase(tool_name="search", tool_call_id="call_1")
        assert err.tool_name == "search"
        assert err.tool_call_id == "call_1"
        assert err.retryable is False
        assert isinstance(err, Exception)

    def test_creates_retryable(self):
        from tools.definition import ToolErrorBase

        err = ToolErrorBase(tool_name="search", tool_call_id="call_1", retryable=True)
        assert err.retryable is True

    def test_can_be_raised_and_caught(self):
        from tools.definition import ToolErrorBase

        with pytest.raises(ToolErrorBase) as exc_info:
            raise ToolErrorBase(tool_name="search", tool_call_id="call_1", retryable=True)
        assert exc_info.value.tool_name == "search"
        assert exc_info.value.retryable is True
