# proxy/app/tools/__init__.py
"""Tools package — SDK, declarative, OpenAPI, orchestration.

Re-exports all legacy symbols from _legacy for backward compatibility.
"""
from app.config import TOOLS_ENABLED

from ._legacy import (
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

_global_registry = None
