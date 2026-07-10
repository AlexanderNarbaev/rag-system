# proxy/app/tools/__init__.py
"""Tools package — SDK, declarative, OpenAPI, orchestration.

Canonical import point. Re-exports all public symbols from definition.py,
errors.py, _legacy.py, and builtin.py for backward compatibility.

Backward compat: ``from proxy.app.tools import ToolDefinition`` returns the
legacy ToolDefinition (with parameters_schema). For the new unified model,
use ``from proxy.app.tools.definition import ToolDefinition``.
"""

from __future__ import annotations

from proxy.app.shared.config import TOOLS_ENABLED

from ._legacy import (
    ToolDefinition,
    ToolRegistry,
)
from ._legacy import (
    ToolResult as ToolResult,  # noqa: F401  # re-export
)
from ._legacy import (
    _get_document_metadata as _get_document_metadata,  # noqa: F401  # re-export
)
from ._legacy import (
    _search_by_version as _search_by_version,  # noqa: F401  # re-export
)
from ._legacy import (
    _search_documents as _search_documents,  # noqa: F401  # re-export
)
from ._legacy import (
    execute_tool as execute_tool,  # noqa: F401  # re-export
)
from ._legacy import (
    get_tool_registry as _legacy_get_tool_registry,  # noqa: F401  # re-export (aliased to avoid conflict)
)
from ._legacy import (
    handle_function_call as handle_function_call,  # noqa: F401  # re-export
)
from .definition import (
    _UNSET as _UNSET,  # noqa: F401  # re-export
)
from .definition import (
    RetryPolicy as RetryPolicy,  # noqa: F401  # re-export
)
from .definition import (
    ToolCall as ToolCall,  # noqa: F401  # re-export
)
from .definition import (
    ToolDefinition as NewToolDefinition,
)
from .definition import (
    ToolErrorBase as ToolErrorBase,  # noqa: F401  # re-export
)
from .definition import (
    ToolParam as ToolParam,  # noqa: F401  # re-export
)
from .definition import (
    ToolResult as NewToolResult,  # noqa: F401  # aliased re-export
)
from .definition import (
    ToolVisibility as ToolVisibility,  # noqa: F401  # re-export
)
from .errors import (
    ToolDependencyError as ToolDependencyError,  # noqa: F401  # re-export
)
from .errors import (
    ToolError as ToolError,  # noqa: F401  # re-export
)
from .errors import (
    ToolExecutionError as ToolExecutionError,  # noqa: F401  # re-export
)
from .errors import (
    ToolNotFoundError as ToolNotFoundError,  # noqa: F401  # re-export
)
from .errors import (
    ToolPermissionError as ToolPermissionError,  # noqa: F401  # re-export
)
from .errors import (
    ToolRateLimitError as ToolRateLimitError,  # noqa: F401  # re-export
)
from .errors import (
    ToolTimeoutError as ToolTimeoutError,  # noqa: F401  # re-export
)
from .errors import (
    ToolValidationError as ToolValidationError,  # noqa: F401  # re-export
)
from .errors import (
    classify_error as classify_error,  # noqa: F401  # re-export
)

_global_registry = None
_enhanced_registry = None


class EnhancedToolRegistry:
    """Registry for new-style ToolDefinition objects with ToolParam schemas.

    Provides the same interface as the legacy ToolRegistry (get_tool, list_tools,
    get_all, register, unregister) for backward compatibility with execute_tool(),
    while storing new-style ToolDefinition instances.

    Also supports lookup by new-style ToolDefinition and format conversion
    (to_openai, to_anthropic).
    """

    def __init__(self):
        self._tools: dict[str, NewToolDefinition] = {}

    def register(self, tool: NewToolDefinition) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get_tool(self, name: str) -> NewToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_all(self) -> list[NewToolDefinition]:
        return list(self._tools.values())

    def get_all_openai(self) -> list[dict]:
        return [t.to_openai_format() for t in self._tools.values()]

    def get_all_anthropic(self) -> list[dict]:
        return [t.to_anthropic_format() for t in self._tools.values()]


def _register_builtin_tools(
    legacy_registry: ToolRegistry | None = None,
    enhanced_registry: EnhancedToolRegistry | None = None,
) -> None:
    """Register the 3 built-in tools into both legacy and enhanced registries.

    Uses handler functions from builtin.py and registers them as:
    - old-style ToolDefinition (with parameters_schema) into the legacy registry
    - new-style ToolDefinition (with ToolParam lists) into the enhanced registry
    """
    from .builtin import (
        GET_DOCUMENT_METADATA_TOOL,
        SEARCH_BY_VERSION_TOOL,
        SEARCH_DOCUMENTS_TOOL,
        get_document_metadata,
        search_by_version,
        search_documents,
    )

    if enhanced_registry is not None:
        enhanced_registry.register(SEARCH_DOCUMENTS_TOOL)
        enhanced_registry.register(SEARCH_BY_VERSION_TOOL)
        enhanced_registry.register(GET_DOCUMENT_METADATA_TOOL)

    if legacy_registry is not None:
        legacy_registry.register(
            ToolDefinition(
                name="search_documents",
                description="Search indexed documents using hybrid (dense+sparse) search",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query text"},
                        "top_k": {"type": "integer", "description": "Number of results (default 5)"},
                        "namespace": {"type": "string", "description": "Optional tenant namespace filter"},
                        "version": {"type": "string", "description": "Optional document version filter"},
                    },
                    "required": ["query"],
                },
                handler=search_documents,
                category="search",
            )
        )
        legacy_registry.register(
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
                handler=search_by_version,
                category="search",
            )
        )
        legacy_registry.register(
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
                handler=get_document_metadata,
                category="metadata",
            )
        )


def _ensure_registries() -> tuple[ToolRegistry, EnhancedToolRegistry]:
    """Create or return the singleton registries, initializing built-in tools if needed.

    Stored on the tools package module for process-wide sharing.
    """
    import sys

    pkg = sys.modules[__package__]  # type: ignore[index]

    legacy = getattr(pkg, "_global_registry", None)
    enhanced = getattr(pkg, "_enhanced_registry", None)

    if legacy is None or enhanced is None:
        legacy = ToolRegistry()
        enhanced = EnhancedToolRegistry()

        if TOOLS_ENABLED:
            _register_builtin_tools(legacy_registry=legacy, enhanced_registry=enhanced)

        pkg._global_registry = legacy  # type: ignore[union-attr]
        pkg._enhanced_registry = enhanced  # type: ignore[union-attr]

    return legacy, enhanced


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry with built-in tools.

    Returns the legacy ToolRegistry for backward compatibility with
    execute_tool() and handle_function_call(). Also initializes the
    enhanced registry (new-style ToolDefinition) in parallel.

    For new-style tool definitions, use get_enhanced_registry().
    """
    legacy, _ = _ensure_registries()
    return legacy


def get_enhanced_registry() -> EnhancedToolRegistry:
    """Get the enhanced tool registry with new-style ToolDefinition objects.

    Initializes both registries as a side effect.
    """
    _, enhanced = _ensure_registries()
    return enhanced


def format_tools_for_llm(tools: list) -> list[dict]:
    """Convert tool definitions to OpenAI function calling format.

    Handles both old-style ToolDefinition (from _legacy, with
    parameters_schema) and new-style ToolDefinition (from definition,
    with to_openai_format()).
    """
    formatted = []
    for t in tools:
        if isinstance(t, NewToolDefinition):
            formatted.append(t.to_openai_format())
        else:
            formatted.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters_schema,
                    },
                }
            )
    return formatted
