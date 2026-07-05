# proxy/app/tools.py
"""DEPRECATED: This module is a deprecation shim.

Import from proxy.app.tools package instead:
    from proxy.app.tools import ToolRegistry, execute_tool, ...

For new-style tool definitions:
    from proxy.app.tools.definition import ToolDefinition, ToolParam, ...

For tool errors:
    from proxy.app.tools.errors import ToolError, ToolNotFoundError, ...
"""

import warnings

warnings.warn(
    "proxy.app.tools module is deprecated. Import from proxy.app.tools package instead.",
    DeprecationWarning,
    stacklevel=2,
)

from proxy.app.tools.definition import (
    RetryPolicy,
    ToolCall,
    ToolDefinition as _NewToolDefinition,
    ToolErrorBase,
    ToolParam,
    ToolResult as _NewToolResult,
    ToolVisibility,
    _UNSET,
)
from proxy.app.tools.errors import (
    ToolDependencyError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRateLimitError,
    ToolTimeoutError,
    ToolValidationError,
    classify_error,
)
from proxy.app.tools._legacy import (
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    _get_document_metadata,
    _search_by_version,
    _search_documents,
    execute_tool,
    get_tool_registry,
    handle_function_call,
)


def format_tools_for_llm(tools: list) -> list[dict]:
    """Convert tool definitions to OpenAI function calling format.

    Handles both old-style (parameters_schema) and new-style
    (to_openai_format) ToolDefinition.
    """
    formatted = []
    for t in tools:
        if isinstance(t, _NewToolDefinition):
            formatted.append(t.to_openai_format())
        else:
            formatted.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            })
    return formatted
