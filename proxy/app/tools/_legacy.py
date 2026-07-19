# proxy/app/tools.py
"""Pluggable tool registry and function calling handler.  **DEPRECATED** —
use :class:`proxy.app.tools.registry.EnhancedToolRegistry` instead.

Supports OpenAI-compatible function calling with pluggable tools
that can wrap retrieval, live sources, or custom handlers.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Definition of a callable tool with its schema and handler."""

    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[..., Any]
    category: str = "general"
    is_async: bool = False


@dataclass
class ToolResult:
    """Result of a tool execution."""

    name: str
    content: str
    tool_call_id: str = ""
    error: str | None = None


class ToolRegistry:
    """Registry for tool definitions with register/unregister/lookup."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool, overwriting if already registered."""
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name} (category={tool.category})")

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if removed."""
        if name in self._tools:
            del self._tools[name]
            logger.info(f"Tool unregistered: {name}")
            return True
        return False

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return list of registered tool names."""
        return list(self._tools.keys())

    def get_all(self) -> list[ToolDefinition]:
        """Return all registered tool definitions."""
        return list(self._tools.values())


def format_tools_for_llm(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    """Convert tool definitions to OpenAI function calling format."""
    formatted = []
    for t in tools:
        formatted.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            },
        )
    return formatted


def execute_tool(name: str, params: dict[str, Any], registry: ToolRegistry) -> ToolResult:
    """Execute a registered tool by name with given parameters."""
    tool = registry.get_tool(name)
    if tool is None:
        error_msg = f"Tool '{name}' not found in registry"
        logger.warning(error_msg)
        return ToolResult(name=name, content="", error=error_msg)

    try:
        result = tool.handler(**params)
        content = str(result) if not isinstance(result, str) else result
        return ToolResult(name=name, content=content)
    except Exception as e:
        error_msg = f"Tool '{name}' execution failed: {e}"
        logger.error(error_msg)
        return ToolResult(name=name, content="", error=error_msg)


def handle_function_call(call: dict[str, Any], registry: ToolRegistry) -> ToolResult:
    """Parse a function call from LLM response and execute it."""
    call_id = call.get("id", "")
    function_info = call.get("function", {})

    tool_name = function_info.get("name", "")
    if not tool_name:
        return ToolResult(name="", content="", tool_call_id=call_id, error="Missing function name in tool call")

    arguments_raw = function_info.get("arguments", "{}")
    try:
        arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else arguments_raw
    except json.JSONDecodeError as e:
        return ToolResult(name=tool_name, content="", tool_call_id=call_id, error=f"Invalid JSON arguments: {e}")

    result = execute_tool(tool_name, arguments, registry)
    result.tool_call_id = call_id
    return result


# ── Built-in Tools ──


def _search_documents(query: str, top_k: int = 5, version: str | None = None) -> str:
    """Search indexed documents using hybrid search."""
    from proxy.app.core.retrieval import hybrid_search

    try:
        results = hybrid_search(query=query, version=version, top_k=top_k)
        if not results:
            return "No documents found."
        formatted = []
        for i, hit in enumerate(results):
            title = hit.payload.get("title", "") or hit.payload.get("doc_title", "")
            text = hit.payload.get("text", "")
            source = hit.payload.get("source_type", "unknown")
            formatted.append(f"[{i + 1}] {title} (source: {source}, score: {hit.score:.3f})\n{text[:300]}")
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Search failed: {e}"


def _search_by_version(version: str, query: str | None = None, top_k: int = 10) -> str:
    """Search documents by a specific version string."""
    from proxy.app.core.retrieval import hybrid_search

    try:
        results = hybrid_search(query=query or version, version=version, top_k=top_k)
        if not results:
            return f"No documents found for version '{version}'."
        formatted = []
        for i, hit in enumerate(results):
            title = hit.payload.get("title", "") or hit.payload.get("doc_title", "")
            text = hit.payload.get("text", "")
            formatted.append(f"[{i + 1}] {title} (v{hit.payload.get('version', '?')})\n{text[:300]}")
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Version search failed: {e}"


def _get_document_metadata(doc_id: str) -> str:
    """Get metadata for a specific document by its ID."""
    try:
        from qdrant_client import QdrantClient

        from proxy.app.shared.config import COLLECTION_NAME, QDRANT_HOST, QDRANT_PORT

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, check_compatibility=False)
        points = client.retrieve(collection_name=COLLECTION_NAME, ids=[doc_id])
        if not points:
            return f"Document '{doc_id}' not found."
        payload = points[0].payload or {}
        meta = {
            "id": doc_id,
            "title": payload.get("title", "") or payload.get("doc_title", ""),
            "source": payload.get("source_type", "unknown"),
            "version": payload.get("version", "unknown"),
            "size": len(payload.get("text", "")),
        }
        return json.dumps(meta, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Metadata lookup failed: {e}"


# ── Global singleton registry ──


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry with built-in tools."""
    import sys

    from . import TOOLS_ENABLED  # type: ignore[attr-defined]

    _tools_pkg = sys.modules[__package__]
    if _tools_pkg._global_registry is None:
        _tools_pkg._global_registry = ToolRegistry()  # type: ignore[attr-defined]
        if TOOLS_ENABLED:
            _tools_pkg._global_registry.register(
                ToolDefinition(
                    name="search_documents",
                    description="Search indexed documents using hybrid (dense+sparse) search",
                    parameters_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query text"},
                            "top_k": {"type": "integer", "description": "Number of results (default 5)"},
                            "version": {"type": "string", "description": "Optional document version filter"},
                        },
                        "required": ["query"],
                    },
                    handler=_search_documents,
                    category="search",
                ),
            )
            _tools_pkg._global_registry.register(
                ToolDefinition(
                    name="search_by_version",
                    description="Search documents by a specific version string",
                    parameters_schema={
                        "type": "object",
                        "properties": {
                            "version": {"type": "string", "description": "Version string to search for"},
                            "query": {"type": "string", "description": "Optional search query"},
                            "top_k": {"type": "integer", "description": "Number of results (default 10)"},
                        },
                        "required": ["version"],
                    },
                    handler=_search_by_version,
                    category="search",
                ),
            )
            _tools_pkg._global_registry.register(
                ToolDefinition(
                    name="get_document_metadata",
                    description="Get metadata for a specific document by its ID",
                    parameters_schema={
                        "type": "object",
                        "properties": {
                            "doc_id": {"type": "string", "description": "Document ID (chunk hash)"},
                        },
                        "required": ["doc_id"],
                    },
                    handler=_get_document_metadata,
                    category="metadata",
                ),
            )
    return _tools_pkg._global_registry  # type: ignore[no-any-return]
