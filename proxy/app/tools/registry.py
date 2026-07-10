# proxy/app/tools/registry.py
"""Enhanced tool registry with multi-provider support.

Extends the legacy ToolRegistry pattern with:
- ToolProvider ABC for pluggable tool discovery (SDK, declarative, OpenAPI)
- EnhancedToolRegistry: register, unregister, get, list with filters
- Role-based visibility filtering (admin, expert, user, read_only)
- Sync/async execution with parameter validation
- Dependency graph tracking
- LLM format export (OpenAI, Anthropic)
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from .definition import (
    ToolDefinition,
    ToolResult,
    ToolVisibility,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role visibility hierarchy
# ---------------------------------------------------------------------------

ROLE_HIERARCHY: dict[str, list[str]] = {
    "admin": ["public", "admin", "expert", "user"],
    "expert": ["public", "expert", "user"],
    "user": ["public", "user"],
    "read_only": ["public"],
}

# Unauthenticated sees only public tools
DEFAULT_VISIBILITY: list[str] = ["public"]


def _visible_for_role(visibility: ToolVisibility, role: str | None) -> bool:
    """Check if a tool is visible to the given role."""
    if role is None:
        return visibility == ToolVisibility.PUBLIC
    allowed = ROLE_HIERARCHY.get(role, DEFAULT_VISIBILITY)
    return visibility.value in allowed


# ---------------------------------------------------------------------------
# ToolProvider ABC
# ---------------------------------------------------------------------------


class ToolProvider(ABC):
    """Abstract base for tool providers.

    Each provider discovers tools from a specific source:
    - SDKProvider: @tool-decorated functions
    - DeclarativeProvider: YAML/JSON files
    - OpenAPIProvider: OpenAPI specs
    """

    @abstractmethod
    async def discover(self) -> list[ToolDefinition]:
        """Discover and return tool definitions from this provider."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier (e.g. 'sdk', 'declarative', 'openapi')."""
        ...

    async def validate(self) -> list[str]:
        """Validate all tools from this provider. Returns list of issues."""
        return []

    async def reload(self) -> list[ToolDefinition]:
        """Reload (hot-reload) tools from this provider."""
        return await self.discover()


# ---------------------------------------------------------------------------
# Concrete Providers
# ---------------------------------------------------------------------------


class SDKProvider(ToolProvider):
    """Provider for SDK-registered (@tool-decorated) tools."""

    _sdk_registered_tools: list[ToolDefinition] = []

    @property
    def provider_name(self) -> str:
        return "sdk"

    async def discover(self) -> list[ToolDefinition]:
        return list(self._sdk_registered_tools)


class DeclarativeProvider(ToolProvider):
    """Provider for declarative tools (YAML/JSON files). Stub."""

    @property
    def provider_name(self) -> str:
        return "declarative"

    async def discover(self) -> list[ToolDefinition]:
        return []


class OpenAPIProvider(ToolProvider):
    """Provider for OpenAPI spec-derived tools. Stub."""

    @property
    def provider_name(self) -> str:
        return "openapi"

    async def discover(self) -> list[ToolDefinition]:
        return []


# ---------------------------------------------------------------------------
# EnhancedToolRegistry
# ---------------------------------------------------------------------------


class EnhancedToolRegistry:
    """Enhanced tool registry with multi-provider support.

    Backward-compatible with legacy ToolRegistry API:
    - register(tool), unregister(name) -> bool
    - get_tool(name) -> ToolDefinition | None
    - get_all() / list_all() -> list[ToolDefinition]

    Extended API:
    - list_tools() with category/tags/visibility/provider filters
    - Role-based visibility (admin sees all, read_only sees public only)
    - execute() / execute_async() with parameter validation
    - get_tools_for_llm() for OpenAI/Anthropic format export
    - get_dependency_graph() for DAG of tool dependencies
    - discover(provider) / reload_provider(name) for provider management
    - validate_tool(tool) for tool definition validation
    """

    ROLE_HIERARCHY: dict[str, list[str]] = ROLE_HIERARCHY

    _instance: EnhancedToolRegistry | None = None

    @classmethod
    def get_instance(cls) -> EnhancedToolRegistry:
        """Return the singleton EnhancedToolRegistry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._provider_tools: dict[str, set[str]] = {}

    # ── Basic CRUD ──────────────────────────────────────────────────────

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition, overwriting if already registered."""
        self._tools[tool.name] = tool
        provider = tool.provider or "unknown"
        if provider not in self._provider_tools:
            self._provider_tools[provider] = set()
        self._provider_tools[provider].add(tool.name)
        logger.info("Tool registered: %s (provider=%s, category=%s)", tool.name, provider, tool.category)

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if removed."""
        tool = self._tools.pop(name, None)
        if tool is not None:
            provider = tool.provider or "unknown"
            if provider in self._provider_tools:
                self._provider_tools[provider].discard(name)
            logger.info("Tool unregistered: %s", name)
            return True
        return False

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def get(self, name: str) -> ToolDefinition | None:
        """Alias for get_tool()."""
        return self.get_tool(name)

    def get_all(self) -> list[ToolDefinition]:
        """Return all registered tool definitions (backward compat)."""
        return list(self._tools.values())

    def list_all(self) -> list[ToolDefinition]:
        """Return all registered tools (alias for get_all)."""
        return self.get_all()

    # ── Filtered listing ────────────────────────────────────────────────

    def list_tools(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        visibility_filter: str | None = None,
        provider: str | None = None,
    ) -> list[ToolDefinition]:
        """Filter tools by category, tags, visibility role, and provider."""
        results = list(self._tools.values())

        if category is not None:
            results = [t for t in results if t.category == category]

        if tags is not None:
            tag_set = set(tags)
            results = [t for t in results if tag_set.issubset(set(t.tags))]

        if provider is not None:
            results = [t for t in results if t.provider == provider]

        if visibility_filter is not None:
            results = [t for t in results if _visible_for_role(t.visibility, visibility_filter)]

        return results

    def list_by_category(self, category: str) -> list[ToolDefinition]:
        """List tools filtered by category name."""
        return self.list_tools(category=category)

    # ── Execution ───────────────────────────────────────────────────────

    def execute(
        self,
        name: str,
        params: dict[str, Any],
        context: Any = None,
    ) -> ToolResult:
        """Execute a tool synchronously. Validates required parameters."""
        import time

        start = time.perf_counter()

        tool = self.get_tool(name)
        if tool is None:
            return ToolResult(
                tool_name=name,
                content="",
                error=f"Tool '{name}' not found",
            )

        # Validate required parameters
        missing = self._validate_params(tool, params)
        if missing:
            return ToolResult(
                tool_name=name,
                content="",
                error=f"Missing required parameters: {', '.join(missing)}",
            )

        handler = tool.handler
        if handler is None:
            return ToolResult(
                tool_name=name,
                content="",
                error=f"Tool '{name}' has no handler",
            )

        try:
            content = handler(**params)
            if not isinstance(content, str):
                content = str(content)
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=name,
                content=content,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=name,
                content="",
                error=str(exc),
                duration_ms=duration_ms,
            )

    async def execute_async(
        self,
        name: str,
        params: dict[str, Any],
        context: Any = None,
    ) -> ToolResult:
        """Execute a tool asynchronously.

        Tries async_handler first; falls back to sync handler if not available.
        """
        import time

        start = time.perf_counter()

        tool = self.get_tool(name)
        if tool is None:
            return ToolResult(
                tool_name=name,
                content="",
                error=f"Tool '{name}' not found",
            )

        # Validate required parameters
        missing = self._validate_params(tool, params)
        if missing:
            return ToolResult(
                tool_name=name,
                content="",
                error=f"Missing required parameters: {', '.join(missing)}",
            )

        # Prefer async handler, fall back to sync
        handler = tool.async_handler or tool.handler
        if handler is None:
            return ToolResult(
                tool_name=name,
                content="",
                error=f"Tool '{name}' has no handler",
            )

        try:
            if tool.async_handler is not None:
                content = await tool.async_handler(**params)
            else:
                content = tool.handler(**params)  # type: ignore[misc]

            if not isinstance(content, str):
                content = str(content)
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=name,
                content=content,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=name,
                content="",
                error=str(exc),
                duration_ms=duration_ms,
            )

    def _validate_params(
        self,
        tool: ToolDefinition,
        params: dict[str, Any],
    ) -> list[str]:
        """Check for missing required parameters. Returns list of missing names."""
        missing: list[str] = []
        for param in tool.parameters:
            if param.required and param.name not in params:
                missing.append(param.name)
        return missing

    # ── LLM format export ──────────────────────────────────────────────

    def get_tools_for_llm(
        self,
        provider_type: str = "openai",
        user_role: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get tools formatted for an LLM provider, respecting role visibility."""
        tools = self.list_tools(visibility_filter=user_role)

        if provider_type == "openai":
            return [t.to_openai_format() for t in tools]
        elif provider_type == "anthropic":
            return [t.to_anthropic_format() for t in tools]
        else:
            return [t.to_openai_format() for t in tools]

    # ── Validation ──────────────────────────────────────────────────────

    def validate_tool(self, tool: ToolDefinition) -> list[str]:
        """Validate a tool definition. Returns list of issues (empty if valid)."""
        issues: list[str] = []

        if not tool.name:
            issues.append("Tool name is required")

        if not tool.description:
            issues.append("Tool description is required")

        if tool.handler is None and tool.async_handler is None:
            issues.append("Tool must have a handler or async_handler")

        # Check for duplicate parameter names
        param_names = [p.name for p in tool.parameters]
        if len(param_names) != len(set(param_names)):
            issues.append("Duplicate parameter names detected")

        return issues

    # ── Dependency graph ────────────────────────────────────────────────

    def get_dependency_graph(self) -> dict[str, list[str]]:
        """Return the tool dependency DAG as {tool_name: [dep_names]}."""
        graph: dict[str, list[str]] = {}
        for tool in self._tools.values():
            graph[tool.name] = list(tool.depends_on)
        return graph

    # ── Provider discovery ──────────────────────────────────────────────

    def discover(self, provider: ToolProvider) -> list[ToolDefinition]:
        """Discover tools from a provider and register them synchronously."""
        try:
            discovered = asyncio.run(provider.discover())
        except Exception as exc:
            logger.error("Provider '%s' discovery failed: %s", provider.provider_name, exc)
            return []

        for tool in discovered:
            self.register(tool)

        return discovered

    def discover_from_provider(self, provider: ToolProvider) -> list[ToolDefinition]:
        """Alias for discover()."""
        return self.discover(provider)

    def reload_provider(self, provider_name: str) -> list[ToolDefinition]:
        """Reload tools from a specific provider (hot-reload).

        Removes all tools from this provider, then re-discovers.
        """
        if provider_name in self._provider_tools:
            for tool_name in list(self._provider_tools[provider_name]):
                self.unregister(tool_name)

        # Find the provider instance
        provider_registry: dict[str, type[ToolProvider]] = {
            "sdk": SDKProvider,
            "declarative": DeclarativeProvider,
            "openapi": OpenAPIProvider,
        }

        provider_cls = provider_registry.get(provider_name)
        if provider_cls is None:
            logger.warning("Unknown provider: %s", provider_name)
            return []

        return self.discover(provider_cls())

    async def discover_all(self) -> dict[str, list[ToolDefinition]]:
        """Discover tools from all providers and register them.

        Conditionally loads declarative and OpenAPI providers based on
        TOOLS_DECLARATIVE_DIR and TOOLS_OPENAPI_SPECS config settings.

        Returns a dict mapping provider_name -> list of discovered tools.
        """
        from proxy.app.shared.config import TOOLS_DECLARATIVE_DIR, TOOLS_OPENAPI_SPECS

        results: dict[str, list[ToolDefinition]] = {}

        # SDK provider (always available)
        sdk = SDKProvider()
        try:
            discovered = await sdk.discover()
            for tool in discovered:
                self.register(tool)
            results[sdk.provider_name] = discovered
            logger.info(
                "Discovered %d tools from provider '%s'",
                len(discovered),
                sdk.provider_name,
            )
        except Exception as exc:
            logger.error(
                "Provider '%s' discovery failed: %s",
                sdk.provider_name,
                exc,
            )
            results[sdk.provider_name] = []

        # Declarative provider (only if directory exists)
        if os.path.isdir(TOOLS_DECLARATIVE_DIR):
            try:
                from proxy.app.tools.declarative import DeclarativeProvider as RealDeclarativeProvider

                declarative = RealDeclarativeProvider()
                discovered = await declarative.discover()
                for tool in discovered:
                    self.register(tool)
                results[declarative.provider_name] = discovered
                logger.info(
                    "Discovered %d tools from provider '%s'",
                    len(discovered),
                    declarative.provider_name,
                )
            except Exception as exc:
                logger.error(
                    "Declarative provider discovery failed: %s",
                    exc,
                )
                results["declarative"] = []

        # OpenAPI provider (only if specs configured)
        if TOOLS_OPENAPI_SPECS:
            try:
                from proxy.app.tools.openapi_discovery import OpenAPIProvider as RealOpenAPIProvider

                openapi = RealOpenAPIProvider()
                discovered = await openapi.discover()
                for tool in discovered:
                    self.register(tool)
                results[openapi.provider_name] = discovered
                logger.info(
                    "Discovered %d tools from provider '%s'",
                    len(discovered),
                    openapi.provider_name,
                )
            except Exception as exc:
                logger.error(
                    "OpenAPI provider discovery failed: %s",
                    exc,
                )
                results["openapi"] = []

        return results


def get_enhanced_registry() -> EnhancedToolRegistry:
    """Return the singleton EnhancedToolRegistry instance."""
    return EnhancedToolRegistry.get_instance()
