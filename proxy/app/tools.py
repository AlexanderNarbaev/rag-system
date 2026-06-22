# proxy/app/tools.py
"""DEPRECATED: This module is a deprecation shim.

Import from proxy.app.tools package instead:
    from proxy.app.tools import ToolRegistry, execute_tool, ...

For new-style tool definitions:
    from proxy.app.tools.definition import ToolDefinition, ToolParam, ...

For tool errors:
    from proxy.app.tools.errors import ToolError, ToolNotFoundError, ...

For enhanced registry:
    from proxy.app.tools import get_enhanced_registry
"""

import warnings

warnings.warn(
    "proxy.app.tools module is deprecated. Import from proxy.app.tools package instead.",
    DeprecationWarning,
    stacklevel=2,
)

from proxy.app.tools import (  # noqa: E402
    EnhancedToolRegistry,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    _get_document_metadata,
    _search_by_version,
    _search_documents,
    _UNSET,
    classify_error,
    execute_tool,
    format_tools_for_llm,
    get_enhanced_registry,
    get_tool_registry,
    handle_function_call,
)
from proxy.app.tools.definition import (  # noqa: E402
    RetryPolicy,
    ToolCall,
    ToolDefinition as _NewToolDefinition,
    ToolErrorBase,
    ToolParam,
    ToolResult as _NewToolResult,
    ToolVisibility,
)
from proxy.app.tools.errors import (  # noqa: E402,F811
    ToolDependencyError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRateLimitError,
    ToolTimeoutError,
    ToolValidationError,
)
