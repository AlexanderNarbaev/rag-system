# proxy/app/tools/definition.py
"""Unified data models for the tools package.

Zero internal dependencies — pure data structures with format conversion
methods for OpenAI, Anthropic, and JSON Schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from proxy.app.tools.errors import ToolError as ToolErrorBase  # noqa: E402, F401

_UNSET: Any = object()


_TYPE_MAP: dict[type | str, str] = {
    str: "string",
    "str": "string",
    int: "integer",
    "int": "integer",
    float: "number",
    "float": "number",
    bool: "boolean",
    "bool": "boolean",
    list: "array",
    "list": "array",
    dict: "object",
    "dict": "object",
}


class ToolVisibility(StrEnum):
    """Access level for tool visibility (role-based filtering)."""

    PUBLIC = "public"
    ADMIN = "admin"
    EXPERT = "expert"
    USER = "user"


@dataclass
class ToolParam:
    """Single tool parameter definition with type, description, and validation."""

    name: str
    type: type | str
    description: str = ""
    required: bool = True
    default: Any = _UNSET
    enum: list[str] | None = None
    items_type: type | str | None = None

    def to_json_schema_property(self) -> dict[str, Any]:
        json_type = _TYPE_MAP.get(self.type, "string")
        schema: dict[str, Any] = {"type": json_type}

        if self.description:
            schema["description"] = self.description

        if self.enum is not None:
            schema["enum"] = self.enum

        if self.default is not _UNSET:
            schema["default"] = self.default

        if json_type == "array" and self.items_type is not None:
            items_type_str = _TYPE_MAP.get(self.items_type, "string")
            schema["items"] = {"type": items_type_str}

        return schema


@dataclass
class RetryPolicy:
    """Retry configuration for tool execution failures."""

    max_retries: int = 3
    backoff: str = "exponential"
    initial_delay_seconds: float = 1.0
    jitter: bool = True


@dataclass
class ToolDefinition:
    """Complete tool definition with handler, parameters, and metadata."""
    name: str
    description: str
    parameters: list[ToolParam] = field(default_factory=list)
    handler: Any = None
    async_handler: Any = None
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    visibility: ToolVisibility = ToolVisibility.PUBLIC
    timeout_seconds: float = 30.0
    retry_policy: RetryPolicy | None = None
    depends_on: list[str] = field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    provider: str = "sdk"
    metadata: dict[str, Any] = field(default_factory=dict)

    def _build_schema_parts(self) -> tuple[dict[str, Any], list[str]]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.parameters:
            properties[param.name] = param.to_json_schema_property()
            if param.required:
                required.append(param.name)
        return properties, required

    def to_json_schema(self) -> dict[str, Any]:
        properties, required = self._build_schema_parts()
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def to_openai_format(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.to_json_schema(),
            },
        }

    def to_anthropic_format(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.to_json_schema(),
        }


@dataclass
class ToolResult:
    """Result of a tool execution with content, error, and timing info."""

    tool_name: str
    tool_call_id: str = ""
    content: str = ""
    error: str | None = None
    duration_ms: float = 0
    retry_count: int = 0

    @property
    def status(self) -> str:
        return "error" if self.error else "success"

    @property
    def name(self) -> str:
        return self.tool_name


@dataclass
class ToolCall:
    """Represents a tool invocation with id, name, and arguments."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
