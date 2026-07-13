# proxy/app/tools/orchestrator.py
"""Tool orchestration: parallel execution, streaming, and composition patterns.

Provides:
- ParallelExecutor: execute multiple tools via asyncio.gather() with
  semaphore-based concurrency and dependency-aware scheduling.
- StreamingExecutor: async generator for incremental tool results.
- ToolComposer: tool composition patterns (chain, fan-out, conditional).
- CompositionPattern enum: CHAIN, FAN_OUT, CONDITIONAL.
- _resolve_dependency_levels: resolve depends_on graph, execute per level.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .definition import ToolCall, ToolDefinition, ToolResult
from .registry import EnhancedToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CompositionPattern
# ---------------------------------------------------------------------------


class CompositionPattern(StrEnum):
    CHAIN = "chain"
    FAN_OUT = "fan_out"
    CONDITIONAL = "conditional"


# ---------------------------------------------------------------------------
# Pattern dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ChainPattern:
    """Sequential chain: A -> B -> C. Each step receives previous output."""

    steps: list[str]
    input_mapper: Callable[[ToolResult], dict[str, Any]] | None = None


@dataclass
class FanOutPattern:
    """Fan-out: run same tool with N different inputs in parallel."""

    tool_name: str
    inputs: list[dict[str, Any]]


@dataclass
class ConditionalPattern:
    """Conditional branching: if condition then tool_a else tool_b."""

    condition: Callable[[Any], bool]
    true_tool: str
    false_tool: str


# ---------------------------------------------------------------------------
# ToolComposer
# ---------------------------------------------------------------------------


class ToolComposer:
    """Compose tools into workflows using declarative patterns."""

    @staticmethod
    def chain(
        tools: list[str],
        input_mapper: Callable[[ToolResult], dict[str, Any]] | None = None,
    ) -> ChainPattern:
        return ChainPattern(steps=list(tools), input_mapper=input_mapper)

    @staticmethod
    def fan_out(tool: str, inputs: list[dict[str, Any]]) -> FanOutPattern:
        return FanOutPattern(tool_name=tool, inputs=list(inputs))

    @staticmethod
    def conditional(
        condition: Callable[[Any], bool],
        true_tool: str,
        false_tool: str,
    ) -> ConditionalPattern:
        return ConditionalPattern(
            condition=condition,
            true_tool=true_tool,
            false_tool=false_tool,
        )


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------


def _resolve_dependency_levels(
    tools: list[ToolDefinition],
    registry: EnhancedToolRegistry,
) -> list[set[str]]:
    """Topologically sort tool names into levels for parallel execution.

    Each level is a set of tool names that have no remaining
    dependencies and can be executed concurrently.  Raises ValueError
    for circular dependencies or unresolved references.
    """
    tool_names = {t.name for t in tools}
    deps: dict[str, set[str]] = {}

    for tool in tools:
        dep_names = set(tool.depends_on)
        for d in dep_names:
            if d not in tool_names:
                raise ValueError(f"Unresolved dependencies for '{tool.name}': '{d}' is not in the tool call set")
        deps[tool.name] = dep_names

    levels: list[set[str]] = []
    remaining: set[str] = set(tool_names)

    while remaining:
        level = {name for name in remaining if not (deps[name] & remaining)}
        if not level:
            raise ValueError(f"Circular dependency cycle detected among tools: {remaining}")
        levels.append(level)
        remaining -= level

    return levels


# ---------------------------------------------------------------------------
# ParallelExecutor
# ---------------------------------------------------------------------------


class ParallelExecutor:
    """Execute multiple tool calls in parallel with concurrency control."""

    def __init__(self, max_concurrency: int = 10, timeout: float = 120.0):
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout

    async def execute_all(
        self,
        tool_calls: list[ToolCall],
        registry: EnhancedToolRegistry,
        context: Any = None,
    ) -> list[ToolResult]:
        """Execute all tool calls respecting dependency order.

        Algorithm:
        1. Build ToolDefinition list from tool calls
        2. Resolve dependency levels
        3. Execute each level in parallel via asyncio.gather
        4. Collect results, preserving original call order
        """
        if not tool_calls:
            return []

        name_to_call: dict[str, ToolCall] = {tc.name: tc for tc in tool_calls}

        tools: list[ToolDefinition] = []
        for tc in tool_calls:
            td = registry.get_tool(tc.name)
            if td is None:
                continue
            tools.append(td)

        if not tools:
            return [
                ToolResult(
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    error=f"Tool '{tc.name}' not found",
                )
                for tc in tool_calls
            ]

        levels = _resolve_dependency_levels(tools, registry)

        results_map: dict[str, ToolResult] = {}

        for level in levels:
            coros = []
            level_order: list[str] = []
            for name in level:
                tool_call: ToolCall | None = name_to_call.get(name)
                if tool_call is None:
                    continue
                level_order.append(name)
                coros.append(self._execute_with_semaphore(tool_call, registry, context))

            if not coros:
                continue

            level_results = await asyncio.gather(*coros)
            for name, result in zip(level_order, level_results, strict=False):
                results_map[name] = result

        return [
            results_map.get(
                tc.name,
                ToolResult(
                    tool_name=tc.name,
                    tool_call_id=tc.id,
                    error=f"No result for '{tc.name}'",
                ),
            )
            for tc in tool_calls
        ]

    async def _execute_with_semaphore(
        self,
        tool_call: ToolCall,
        registry: EnhancedToolRegistry,
        context: Any,
    ) -> ToolResult:
        async with self._semaphore:
            return await self.execute_single(tool_call, registry, context)

    async def execute_single(
        self,
        tool_call: ToolCall,
        registry: EnhancedToolRegistry,
        context: Any = None,
    ) -> ToolResult:
        """Execute one tool call with retry and error handling."""
        tool_def = registry.get_tool(tool_call.name)
        retry_policy = tool_def.retry_policy if tool_def else None
        max_retries = retry_policy.max_retries if retry_policy else 0
        total_attempts = 1 + max_retries

        last_error: str | None = None
        retry_count = 0

        for attempt in range(total_attempts):
            try:
                result = await asyncio.wait_for(
                    registry.execute_async(
                        tool_call.name,
                        tool_call.arguments,
                        context,
                    ),
                    timeout=(tool_def.timeout_seconds if tool_def else 30.0),
                )
                result.tool_call_id = tool_call.id
                result.retry_count = retry_count

                if result.error and attempt < total_attempts - 1:
                    last_error = result.error
                    retry_count += 1
                    delay = _compute_backoff(retry_policy, retry_count)
                    await asyncio.sleep(delay)
                    continue

                return result
            except TimeoutError:
                last_error = (
                    f"Tool '{tool_call.name}' timed out after {tool_def.timeout_seconds if tool_def else 30.0}s"
                )
                if attempt < total_attempts - 1:
                    retry_count += 1
                    delay = _compute_backoff(retry_policy, retry_count)
                    await asyncio.sleep(delay)

        return ToolResult(
            tool_name=tool_call.name,
            tool_call_id=tool_call.id,
            error=last_error or "Unknown error",
            retry_count=retry_count,
        )


def _compute_backoff(retry_policy: Any, attempt: int) -> float:
    """Compute backoff delay for a given attempt.

    Supports: constant, linear, exponential.
    """
    if retry_policy is None:
        return 0.0

    base: float = retry_policy.initial_delay_seconds
    strategy = getattr(retry_policy, "backoff", "exponential")

    if strategy == "constant":
        delay = base
    elif strategy == "linear":
        delay = base * attempt
    else:
        delay = base * (2 ** (attempt - 1))

    if getattr(retry_policy, "jitter", False):
        import random

        delay = delay * (0.5 + random.random())

    return delay


# ---------------------------------------------------------------------------
# StreamingExecutor
# ---------------------------------------------------------------------------


class StreamingExecutor:
    """Execute tools that produce streaming results.

    Yields partial results as they become available. Useful for
    long-running tools or progressive search.
    """

    async def execute_streaming(
        self,
        tool_call: ToolCall,
        registry: EnhancedToolRegistry,
        context: Any = None,
    ) -> AsyncIterator[str]:
        """Execute a tool and yield partial result strings.

        For non-streaming tools, yields a single chunk with the full result.
        For errors, yields an error string.
        """
        tool_def = registry.get_tool(tool_call.name)

        if tool_def is None:
            yield f"Error: Tool '{tool_call.name}' not found"
            return

        try:
            result = await registry.execute_async(
                tool_call.name,
                tool_call.arguments,
                context,
            )

            if result.error:
                yield result.error
                return

            content = result.content or ""
            chunk_size = 1024
            for i in range(0, len(content), chunk_size):
                yield content[i : i + chunk_size]

        except TimeoutError:
            yield f"Error: Tool '{tool_call.name}' timed out"
        except Exception as exc:
            yield str(exc)
