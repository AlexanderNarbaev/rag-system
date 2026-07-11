# proxy/app/tools/sdk.py
"""Python Tool SDK — @tool decorator, ToolBuilder, ToolContext, json_schema_from_func.

Provides a developer-friendly API for defining tools in pure Python with
automatic JSON Schema generation from type hints, fluent builder API, and
a shared execution context injected into tool handlers.
"""

from __future__ import annotations

import inspect
import types
import typing
from dataclasses import dataclass, field
from typing import Annotated, Any, Union, get_args, get_origin

from .definition import (
    _UNSET,
    RetryPolicy,
    ToolDefinition,
    ToolParam,
    ToolVisibility,
)

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

_sdk_registered_tools: dict[str, ToolDefinition] = {}


def _unwrap_annotated(typ: type) -> type:
    """Unwrap Annotated[T, ...] to T."""
    origin = get_origin(typ)
    if origin is Annotated:
        args = get_args(typ)
        if args:
            return args[0]
    return typ


def _resolve_type(typ: type) -> str:
    """Map a Python type to its JSON Schema type string.

    Falls back to "string" for unrecognized types.
    Handles both typing.Union and types.UnionType (Python 3.10+).
    """
    typ = _unwrap_annotated(typ)
    origin = get_origin(typ)

    # Handle Union types (typing.Union and types.UnionType)
    if origin is Union or isinstance(typ, types.UnionType):
        args = get_args(typ)
        non_none = [a for a in args if a is not type(None)]
        return _resolve_type(non_none[0]) if non_none else "string"

    if origin is not None:
        if origin is list:
            return "array"
        if origin is dict:
            return "object"
        return _TYPE_MAP.get(origin, "string")
    return _TYPE_MAP.get(typ, "string")


def _extract_annotated_description(typ: type) -> str | None:
    """Extract description from Annotated[..., <string>] annotations."""
    origin = get_origin(typ)
    if origin is Annotated or origin is typing.Annotated:
        args = get_args(typ)
        if len(args) >= 2:
            for arg in args[1:]:
                if isinstance(arg, str):
                    return arg
    return None


def _extract_items_type(typ: type) -> type | None:
    """Extract the inner type from list[X]."""
    origin = get_origin(typ)
    if origin is list:
        args = get_args(typ)
        if args:
            return args[0]
    return None


def _is_optional(typ: type) -> bool:
    """Check if a type represents Optional[X] or Union[X, None]."""
    origin = get_origin(typ)
    if origin is Union:
        args = get_args(typ)
        return type(None) in args and len(args) == 2
    return False


def _is_tool_context(typ: type) -> bool:
    """Check if a type is ToolContext."""
    try:
        return typ is ToolContext or (hasattr(typ, "__name__") and typ.__name__ == "ToolContext")
    except Exception:
        return False


def json_schema_from_func(func: typing.Callable) -> dict[str, Any]:
    """Generate JSON Schema from Python function type hints.

    Mapping:
    - str → {"type": "string"}
    - int → {"type": "integer"}
    - float → {"type": "number"}
    - bool → {"type": "boolean"}
    - list[X] → {"type": "array", "items": type_of(X)}
    - Optional[X] → allOf: [type_of(X)], not in required
    - Annotated[T, "description"] → type_of(T) with description
    - dict → {"type": "object"}
    """
    sig = inspect.signature(func)
    try:
        hints = typing.get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name == "self" or param_name == "cls":
            continue

        hint = hints.get(param_name, str)

        if _is_tool_context(hint):
            continue

        json_type = _resolve_type(hint)
        is_optional = _is_optional(hint)
        has_default = param.default is not inspect.Parameter.empty

        prop: dict[str, Any] = {"type": json_type}

        description = _extract_annotated_description(hint)
        if description:
            prop["description"] = description

        if has_default:
            prop["default"] = param.default

        if json_type == "array":
            items_type = _extract_items_type(hint)
            if items_type is not None:
                items_json_type = _resolve_type(items_type)
                prop["items"] = {"type": items_json_type}

        properties[param_name] = prop

        if not is_optional and not has_default:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


@dataclass
class ToolContext:
    """Context injected into tool handlers automatically.

    Provides cross-tool shared state and streaming support.
    """

    user_id: str | None = None
    user_role: str | None = None
    request_id: str = ""
    tool_call_id: str = ""

    _state: dict[str, Any] = field(default_factory=dict)
    _stream_parts: list[str] = field(default_factory=list)

    def get_state(self, key: str) -> Any:
        return self._state.get(key)

    def set_state(self, key: str, value: Any) -> None:
        self._state[key] = value

    def stream_partial(self, data: str) -> None:
        self._stream_parts.append(data)

    def get_stream_parts(self) -> list[str]:
        return list(self._stream_parts)


def tool(
    name: str | None = None,
    description: str | None = None,
    category: str = "general",
    tags: list[str] | None = None,
    version: str = "1.0.0",
    timeout: float = 30.0,
    retry_policy: RetryPolicy | None = None,
    visibility: ToolVisibility = ToolVisibility.PUBLIC,
    depends_on: list[str] | None = None,
):
    """Decorator to register a function as a tool.

    Usage::

        @tool(category="search", tags=["fast"])
        async def search_confluence(query: str, max_results: int = 5) -> str:
            '''Search Confluence pages.'''
            ...

    - Type hints are read to generate ToolParam list
    - Docstring becomes description if not explicitly provided
    - The function name becomes the tool name if not explicitly provided
    - Async functions are detected automatically
    - The decorated function remains callable as normal
    """

    def decorator(func: typing.Callable) -> typing.Callable:
        tool_name = name or func.__name__
        tool_description = description or ""
        if not tool_description and func.__doc__:
            tool_description = inspect.cleandoc(func.__doc__)

        is_async = inspect.iscoroutinefunction(func)

        parameters: list[ToolParam] = []
        try:
            sig = inspect.signature(func)
            hints = typing.get_type_hints(func, include_extras=True)
        except Exception:
            hints = {}
            sig = inspect.signature(func)

        for param_name, param in sig.parameters.items():
            if param_name == "self" or param_name == "cls":
                continue

            hint = hints.get(param_name, str)

            if _is_tool_context(hint):
                continue

            json_type_name = _resolve_type(hint)
            param_optional = _is_optional(hint)
            has_default = param.default is not inspect.Parameter.empty

            items_type = None
            if get_origin(hint) is list:
                items_type = _extract_items_type(hint)

            tool_param = ToolParam(
                name=param_name,
                type=json_type_name,
                required=not param_optional and not has_default,
                default=_UNSET if not has_default else param.default,
                items_type=items_type,
            )
            parameters.append(tool_param)

        tool_def = ToolDefinition(
            name=tool_name,
            description=tool_description,
            parameters=parameters,
            handler=None if is_async else func,
            async_handler=func if is_async else None,
            category=category,
            tags=tags or [],
            version=version,
            visibility=visibility,
            timeout_seconds=timeout,
            retry_policy=retry_policy,
            depends_on=depends_on or [],
            provider="sdk",
        )

        _sdk_registered_tools[tool_name] = tool_def

        return func

    return decorator


class ToolBuilder:
    """Fluent API for building tool definitions programmatically.

    Usage::

        tool = (
            ToolBuilder("search_confluence")
            .with_description("Search Confluence pages by CQL query")
            .with_param("query", str, "CQL query text", required=True)
            .with_param("max_results", int, "Max results", default=5)
            .with_handler(lambda query, max_results: ...)
            .with_category("live_source")
            .with_tags(["confluence", "live"])
            .with_timeout(15.0)
            .with_visibility(ToolVisibility.USER)
            .build()
        )
    """

    def __init__(self, name: str):
        self._name = name
        self._description: str = ""
        self._parameters: list[ToolParam] = []
        self._handler: typing.Callable | None = None
        self._async_handler: typing.Callable | None = None
        self._category: str = "general"
        self._tags: list[str] = []
        self._timeout: float = 30.0
        self._retry_policy: RetryPolicy | None = None
        self._visibility: ToolVisibility = ToolVisibility.PUBLIC

    def with_description(self, description: str) -> ToolBuilder:
        self._description = description
        return self

    def with_param(
        self,
        name: str,
        typ: type | str,
        description: str = "",
        required: bool = True,
        default: Any = _UNSET,
        enum: list[str] | None = None,
        items_type: type | str | None = None,
    ) -> ToolBuilder:
        effective_required = required and default is _UNSET
        self._parameters.append(
            ToolParam(
                name=name,
                type=typ,
                description=description,
                required=effective_required,
                default=default,
                enum=enum,
                items_type=items_type,
            )
        )
        return self

    def with_handler(self, handler: typing.Callable) -> ToolBuilder:
        self._handler = handler
        return self

    def with_async_handler(self, handler: typing.Callable) -> ToolBuilder:
        self._async_handler = handler
        return self

    def with_category(self, category: str) -> ToolBuilder:
        self._category = category
        return self

    def with_tags(self, tags: list[str]) -> ToolBuilder:
        self._tags = tags
        return self

    def with_timeout(self, timeout: float) -> ToolBuilder:
        self._timeout = timeout
        return self

    def with_retry_policy(self, retry_policy: RetryPolicy) -> ToolBuilder:
        self._retry_policy = retry_policy
        return self

    def with_visibility(self, visibility: ToolVisibility) -> ToolBuilder:
        self._visibility = visibility
        return self

    def build(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description=self._description,
            parameters=self._parameters,
            handler=self._handler,
            async_handler=self._async_handler,
            category=self._category,
            tags=self._tags,
            timeout_seconds=self._timeout,
            retry_policy=self._retry_policy,
            visibility=self._visibility,
            provider="sdk",
        )
