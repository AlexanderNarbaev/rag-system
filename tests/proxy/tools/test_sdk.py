"""Tests for proxy/app/tools/sdk.py — @tool decorator, ToolBuilder, ToolContext, json_schema_from_func."""

import sys
from pathlib import Path
from typing import Annotated

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))


class TestJsonSchemaFromFunc:
    """Tests for json_schema_from_func — Python type hints → JSON Schema."""

    def test_str_to_string(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(query: str) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert schema["type"] == "object"
        assert schema["properties"]["query"] == {"type": "string"}
        assert "query" in schema.get("required", [])

    def test_int_to_integer(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(count: int) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert schema["properties"]["count"] == {"type": "integer"}
        assert "count" in schema.get("required", [])

    def test_float_to_number(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(score: float) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert schema["properties"]["score"] == {"type": "number"}
        assert "score" in schema.get("required", [])

    def test_bool_to_boolean(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(verbose: bool) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert schema["properties"]["verbose"] == {"type": "boolean"}
        assert "verbose" in schema.get("required", [])

    def test_list_str_to_array(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(tags: list[str]) -> str:
            pass

        schema = json_schema_from_func(fn)
        param = schema["properties"]["tags"]
        assert param["type"] == "array"
        assert param["items"] == {"type": "string"}
        assert "tags" in schema.get("required", [])

    def test_list_int_to_array_with_integer_items(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(ids: list[int]) -> str:
            pass

        schema = json_schema_from_func(fn)
        param = schema["properties"]["ids"]
        assert param["type"] == "array"
        assert param["items"] == {"type": "integer"}

    def test_optional_omitted_from_required(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(query: str, top_k: int | None = 5) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert "query" in schema.get("required", [])
        assert "top_k" not in schema.get("required", [])

    def test_default_value_not_required(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(query: str, limit: int = 10) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert "query" in schema.get("required", [])
        assert "limit" not in schema.get("required", [])
        assert schema["properties"]["limit"].get("default") == 10

    def test_union_none_equals_optional(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(query: str, limit: int | None = None) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert "limit" not in schema.get("required", [])
        assert schema["properties"]["limit"]["type"] == "integer"

    def test_annotated_base_model_not_found_defaults_to_string(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(data: Annotated[str, "Some description"]) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert schema["properties"]["data"]["type"] == "string"

    def test_annotated_with_field_description(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(data: Annotated[str, "A data field"]) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert schema["properties"]["data"]["type"] == "string"
        assert schema["properties"]["data"].get("description") == "A data field"

    def test_multiple_params_with_mixed_requirements(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(query: str, top_k: int = 5, threshold: float = 0.5, verbose: bool = False) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert "query" in schema["required"]
        assert "top_k" not in schema["required"]
        assert "threshold" not in schema["required"]
        assert "verbose" not in schema["required"]
        assert len(schema["properties"]) == 4

    def test_dict_param_to_object(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn(config: dict) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert schema["properties"]["config"]["type"] == "object"

    def test_no_params_returns_empty_schema(self):
        from proxy.app.tools.sdk import json_schema_from_func

        def fn() -> str:
            pass

        schema = json_schema_from_func(fn)
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert schema["required"] == []

    def test_ignores_toolcontext_param(self):
        from proxy.app.tools.sdk import ToolContext, json_schema_from_func

        def fn(query: str, ctx: ToolContext = None) -> str:
            pass

        schema = json_schema_from_func(fn)
        assert "query" in schema["properties"]
        assert "ctx" not in schema["properties"]


class TestToolDecorator:
    """Tests for @tool decorator — registration, docstring, type hints, tags."""

    def test_registers_in_sdk_registered_tools(self):
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool()
        def search_docs(query: str) -> str:
            """Search documents by query."""
            return "results"

        assert "search_docs" in _sdk_registered_tools
        assert _sdk_registered_tools["search_docs"].name == "search_docs"

    def test_uses_docstring_as_description(self):
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool()
        def get_user(user_id: int) -> str:
            """Fetch user by ID."""
            return "user"

        assert _sdk_registered_tools["get_user"].description == "Fetch user by ID."

    def test_auto_derives_name_from_func(self):
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool()
        def my_custom_tool(x: int) -> str:
            pass

        assert "my_custom_tool" in _sdk_registered_tools

    def test_generates_params_from_type_hints(self):
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool()
        def search(query: str, top_k: int = 5) -> str:
            """Search."""
            return "results"

        td = _sdk_registered_tools["search"]
        param_names = [p.name for p in td.parameters]
        assert "query" in param_names
        assert "top_k" in param_names

    def test_supports_async_def(self):
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool()
        async def async_search(query: str) -> str:
            """Async search."""
            return "async results"

        td = _sdk_registered_tools["async_search"]
        assert td.async_handler is not None

    def test_tags_category_visibility_passed_through(self):
        from tools.definition import ToolVisibility

        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool(category="search", tags=["fast", "cached"], visibility=ToolVisibility.USER, version="2.0.0")
        def tagged_tool(query: str) -> str:
            """Tagged tool."""
            return "tagged"

        td = _sdk_registered_tools["tagged_tool"]
        assert td.category == "search"
        assert td.tags == ["fast", "cached"]
        assert td.visibility == ToolVisibility.USER
        assert td.version == "2.0.0"

    def test_custom_name_overrides_func_name(self):
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool(name="renamed_tool")
        def original_name(x: int) -> str:
            return str(x)

        assert "renamed_tool" in _sdk_registered_tools
        assert "original_name" not in _sdk_registered_tools

    def test_custom_description_overrides_docstring(self):
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool(description="Custom description")
        def has_docstring(x: int) -> str:
            """This docstring should be ignored."""
            return str(x)

        assert _sdk_registered_tools["has_docstring"].description == "Custom description"

    def test_decorator_preserves_callable(self):
        from proxy.app.tools.sdk import tool

        @tool()
        def callable_tool(a: int, b: int = 0) -> int:
            return a + b

        result = callable_tool(3, 4)
        assert result == 7

    def test_decorator_preserves_async_callable(self):
        import asyncio

        from proxy.app.tools.sdk import tool

        @tool()
        async def async_callable_tool(a: int, b: int = 0) -> int:
            return a + b

        result = asyncio.run(async_callable_tool(3, 4))
        assert result == 7

    def test_timeout_retry_policy_passed_through(self):
        from tools.definition import RetryPolicy

        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        rp = RetryPolicy(max_retries=5)

        @tool(timeout=10.0, retry_policy=rp)
        def resilient_tool(x: str) -> str:
            return x

        td = _sdk_registered_tools["resilient_tool"]
        assert td.timeout_seconds == 10.0
        assert td.retry_policy is rp

    def test_depends_on_passed_through(self):
        from proxy.app.tools.sdk import _sdk_registered_tools, tool

        @tool(depends_on=["other_tool"])
        def dependent_tool(x: str) -> str:
            return x

        td = _sdk_registered_tools["dependent_tool"]
        assert td.depends_on == ["other_tool"]


class TestToolBuilder:
    """Tests for ToolBuilder fluent API."""

    def test_build_minimal_tool(self):
        from proxy.app.tools.sdk import ToolBuilder

        def handler(query: str) -> str:
            return "done"

        tool_def = ToolBuilder("minimal").with_handler(handler).build()
        assert tool_def.name == "minimal"
        assert tool_def.handler is handler

    def test_with_description(self):
        from proxy.app.tools.sdk import ToolBuilder

        tool_def = ToolBuilder("sample").with_description("Sample tool").build()
        assert tool_def.description == "Sample tool"

    def test_with_param(self):
        from proxy.app.tools.sdk import ToolBuilder

        tool_def = (
            ToolBuilder("sample")
            .with_param("query", str, "Search query", required=True)
            .with_param("top_k", int, "Max results", default=5)
            .build()
        )
        params = {p.name: p for p in tool_def.parameters}
        assert params["query"].required is True
        assert params["top_k"].required is False
        assert params["top_k"].default == 5

    def test_with_handler_sync(self):
        from proxy.app.tools.sdk import ToolBuilder

        def my_handler(x: int) -> str:
            return str(x)

        tool_def = ToolBuilder("sample").with_handler(my_handler).build()
        assert tool_def.handler is my_handler

    def test_with_async_handler(self):
        from proxy.app.tools.sdk import ToolBuilder

        async def my_async_handler(x: int) -> str:
            return str(x)

        tool_def = ToolBuilder("sample").with_async_handler(my_async_handler).build()
        assert tool_def.async_handler is my_async_handler

    def test_with_category(self):
        from proxy.app.tools.sdk import ToolBuilder

        tool_def = ToolBuilder("sample").with_category("live_source").build()
        assert tool_def.category == "live_source"

    def test_with_tags(self):
        from proxy.app.tools.sdk import ToolBuilder

        tool_def = ToolBuilder("sample").with_tags(["confluence", "live"]).build()
        assert tool_def.tags == ["confluence", "live"]

    def test_with_timeout(self):
        from proxy.app.tools.sdk import ToolBuilder

        tool_def = ToolBuilder("sample").with_timeout(15.0).build()
        assert tool_def.timeout_seconds == 15.0

    def test_with_visibility(self):
        from tools.definition import ToolVisibility

        from proxy.app.tools.sdk import ToolBuilder

        tool_def = ToolBuilder("sample").with_visibility(ToolVisibility.ADMIN).build()
        assert tool_def.visibility == ToolVisibility.ADMIN

    def test_builder_fluent_chaining(self):
        from tools.definition import ToolVisibility

        from proxy.app.tools.sdk import ToolBuilder

        def h(query: str) -> str:
            return "result"

        tool_def = (
            ToolBuilder("fluent")
            .with_description("A fluent tool")
            .with_param("query", str, "Query string", required=True)
            .with_handler(h)
            .with_category("utils")
            .with_tags(["test"])
            .with_timeout(5.0)
            .with_visibility(ToolVisibility.PUBLIC)
            .build()
        )
        assert tool_def.name == "fluent"
        assert tool_def.description == "A fluent tool"
        assert len(tool_def.parameters) == 1
        assert tool_def.handler is h
        assert tool_def.category == "utils"
        assert tool_def.tags == ["test"]
        assert tool_def.timeout_seconds == 5.0


class TestToolContext:
    """Tests for ToolContext — state management and streaming."""

    def test_creates_with_fields(self):
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext(
            user_id="user_1",
            user_role="admin",
            request_id="req_1",
            tool_call_id="call_1",
        )
        assert ctx.user_id == "user_1"
        assert ctx.user_role == "admin"
        assert ctx.request_id == "req_1"
        assert ctx.tool_call_id == "call_1"

    def test_get_state_returns_none_for_unknown_key(self):
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext(
            user_id="user_1",
            user_role="user",
            request_id="req_1",
            tool_call_id="call_1",
        )
        result = ctx.get_state("nonexistent")
        assert result is None

    def test_set_and_get_state(self):
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext(
            user_id="user_1",
            user_role="user",
            request_id="req_1",
            tool_call_id="call_1",
        )
        ctx.set_state("shared_key", "shared_value")
        assert ctx.get_state("shared_key") == "shared_value"

    def test_set_state_overwrites(self):
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext(
            user_id="user_1",
            user_role="user",
            request_id="req_1",
            tool_call_id="call_1",
        )
        ctx.set_state("key", "first")
        ctx.set_state("key", "second")
        assert ctx.get_state("key") == "second"

    def test_stream_partial_stores_data(self):
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext(
            user_id="user_1",
            user_role="user",
            request_id="req_1",
            tool_call_id="call_1",
        )
        ctx.stream_partial("chunk1")
        ctx.stream_partial("chunk2")
        ctx.stream_partial("chunk3")
        assert ctx._stream_parts == ["chunk1", "chunk2", "chunk3"]

    def test_stream_partial_get_parts(self):
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext(
            user_id="user_1",
            user_role="user",
            request_id="req_1",
            tool_call_id="call_1",
        )
        ctx.stream_partial("a")
        ctx.stream_partial("b")
        parts = ctx.get_stream_parts()
        assert parts == ["a", "b"]

    def test_defaults_for_optional_fields(self):
        from proxy.app.tools.sdk import ToolContext

        ctx = ToolContext(
            request_id="req_1",
            tool_call_id="call_1",
        )
        assert ctx.user_id is None
        assert ctx.user_role is None
