"""Tests for proxy/app/tools/orchestrator.py — ParallelExecutor, StreamingExecutor, ToolComposer.

TDD for orchestrator: dependency-aware parallel execution, streaming, composition patterns.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))

from tools.definition import (
    RetryPolicy,
    ToolCall,
    ToolDefinition,
    ToolParam,
    ToolResult,
    ToolVisibility,
)
from tools.registry import EnhancedToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(
    name,
    description="Test tool",
    category="general",
    tags=None,
    visibility=ToolVisibility.PUBLIC,
    handler=None,
    provider="sdk",
    depends_on=None,
    parameters=None,
    async_handler=None,
    timeout_seconds=30.0,
    retry_policy=None,
):
    if parameters is None:
        parameters = [ToolParam(name="query", type=str, description="Query")]
    if handler is None:

        def handler(**kw):
            return f"Result: {kw}"

    return ToolDefinition(
        name=name,
        description=description,
        parameters=parameters,
        handler=handler,
        async_handler=async_handler,
        category=category,
        tags=tags or [],
        visibility=visibility,
        provider=provider,
        depends_on=depends_on or [],
        timeout_seconds=timeout_seconds,
        retry_policy=retry_policy,
    )


def _make_registry(tools=None):
    registry = EnhancedToolRegistry()
    for t in tools or []:
        registry.register(t)
    return registry


# ---------------------------------------------------------------------------
# CompositionPattern enum
# ---------------------------------------------------------------------------


class TestCompositionPattern:
    def test_enum_values(self):
        from tools.orchestrator import CompositionPattern

        assert CompositionPattern.CHAIN.value == "chain"
        assert CompositionPattern.FAN_OUT.value == "fan_out"
        assert CompositionPattern.CONDITIONAL.value == "conditional"

    def test_enum_is_string_subclass(self):
        from tools.orchestrator import CompositionPattern

        assert isinstance(CompositionPattern.CHAIN, str)


# ---------------------------------------------------------------------------
# ToolComposer
# ---------------------------------------------------------------------------


class TestToolComposer:
    def test_chain_creates_chain_pattern(self):
        from tools.orchestrator import ChainPattern, ToolComposer

        def mapper(prev):
            return {"doc_id": prev.content}

        pattern = ToolComposer.chain(["search_documents", "get_document_metadata"], mapper)

        assert isinstance(pattern, ChainPattern)
        assert pattern.steps == ["search_documents", "get_document_metadata"]
        assert pattern.input_mapper is mapper

    def test_fan_out_creates_fan_out_pattern(self):
        from tools.orchestrator import FanOutPattern, ToolComposer

        inputs = [{"doc_id": "a"}, {"doc_id": "b"}, {"doc_id": "c"}]
        pattern = ToolComposer.fan_out("get_document_metadata", inputs)

        assert isinstance(pattern, FanOutPattern)
        assert pattern.tool_name == "get_document_metadata"
        assert pattern.inputs == inputs

    def test_conditional_creates_conditional_pattern(self):
        from tools.orchestrator import ConditionalPattern, ToolComposer

        def cond(ctx):
            return ctx.get_state("has_jira") is True

        pattern = ToolComposer.conditional(cond, "search_jira", "search_documents")

        assert isinstance(pattern, ConditionalPattern)
        assert pattern.condition is cond
        assert pattern.true_tool == "search_jira"
        assert pattern.false_tool == "search_documents"


# ---------------------------------------------------------------------------
# ParallelExecutor — execute_single
# ---------------------------------------------------------------------------


class TestParallelExecutorExecuteSingle:
    @pytest.mark.asyncio
    async def test_execute_single_success(self):
        from tools.orchestrator import ParallelExecutor

        tool = _make_tool(
            "echo",
            handler=lambda **kw: f"Echo: {kw.get('message')}",
            parameters=[],
        )
        registry = _make_registry([tool])
        executor = ParallelExecutor(max_concurrency=2)

        call = ToolCall(id="call-1", name="echo", arguments={"message": "hello"})
        result = await executor.execute_single(call, registry, None)

        assert isinstance(result, ToolResult)
        assert result.tool_name == "echo"
        assert result.tool_call_id == "call-1"
        assert result.content == "Echo: hello"
        assert result.error is None
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_execute_single_async_handler(self):
        from tools.orchestrator import ParallelExecutor

        async def async_echo(**kw) -> str:
            return f"Async: {kw.get('message')}"

        tool = _make_tool("async_echo", async_handler=async_echo, parameters=[])
        registry = _make_registry([tool])
        executor = ParallelExecutor(max_concurrency=2)

        call = ToolCall(id="call-2", name="async_echo", arguments={"message": "hi"})
        result = await executor.execute_single(call, registry, None)

        assert result.tool_name == "async_echo"
        assert result.content == "Async: hi"

    @pytest.mark.asyncio
    async def test_execute_single_missing_tool(self):
        from tools.orchestrator import ParallelExecutor

        registry = _make_registry([])
        executor = ParallelExecutor(max_concurrency=2)

        call = ToolCall(id="call-3", name="nonexistent", arguments={})
        result = await executor.execute_single(call, registry, None)

        assert result.error is not None
        assert "not found" in result.error
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_execute_single_handler_raises(self):
        from tools.orchestrator import ParallelExecutor

        def failing_handler(**kw):
            raise ValueError("boom")

        tool = _make_tool("failer", handler=failing_handler, parameters=[])
        registry = _make_registry([tool])
        executor = ParallelExecutor(max_concurrency=2)

        call = ToolCall(id="call-4", name="failer", arguments={})
        result = await executor.execute_single(call, registry, None)

        assert result.error == "boom"
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_execute_single_with_retry(self):
        from tools.orchestrator import ParallelExecutor

        call_count = 0

        def retry_handler(**kw):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary")
            return "recovered"

        tool = _make_tool(
            "retry_me",
            handler=retry_handler,
            parameters=[],
            retry_policy=RetryPolicy(max_retries=3, backoff="constant", initial_delay_seconds=0.0, jitter=False),
        )
        registry = _make_registry([tool])
        executor = ParallelExecutor(max_concurrency=2)

        call = ToolCall(id="call-5", name="retry_me", arguments={})
        result = await executor.execute_single(call, registry, None)

        assert result.status == "success"
        assert result.content == "recovered"
        assert result.retry_count == 2

    @pytest.mark.asyncio
    async def test_execute_single_with_retry_exhausted(self):
        from tools.orchestrator import ParallelExecutor

        def always_fails(**kw):
            raise RuntimeError("permanent")

        tool = _make_tool(
            "always_fail",
            handler=always_fails,
            parameters=[],
            retry_policy=RetryPolicy(max_retries=2, backoff="constant", initial_delay_seconds=0.0, jitter=False),
        )
        registry = _make_registry([tool])
        executor = ParallelExecutor(max_concurrency=2)

        call = ToolCall(id="call-6", name="always_fail", arguments={})
        result = await executor.execute_single(call, registry, None)

        assert result.error == "permanent"
        assert result.status == "error"
        assert result.retry_count == 2

    @pytest.mark.asyncio
    async def test_execute_single_timeout(self):
        from tools.orchestrator import ParallelExecutor

        async def slow_handler(**kw):
            await asyncio.sleep(10.0)
            return "too late"

        tool = _make_tool("slow", async_handler=slow_handler, timeout_seconds=0.01, parameters=[])
        registry = _make_registry([tool])
        executor = ParallelExecutor(max_concurrency=2, timeout=0.02)

        call = ToolCall(id="call-7", name="slow", arguments={})
        result = await executor.execute_single(call, registry, None)

        assert result.error is not None
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()
        assert result.status == "error"


# ---------------------------------------------------------------------------
# ParallelExecutor — execute_all (parallel + dependencies)
# ---------------------------------------------------------------------------


class TestParallelExecutorExecuteAll:
    @pytest.mark.asyncio
    async def test_execute_all_parallel(self):
        from tools.orchestrator import ParallelExecutor

        calls = []

        async def tracked(**kw) -> str:
            msg = kw.get("message", "")
            calls.append(msg)
            await asyncio.sleep(0.01)
            return msg

        tool_a = _make_tool("tool_a", async_handler=tracked, parameters=[])
        tool_b = _make_tool("tool_b", async_handler=tracked, parameters=[])
        registry = _make_registry([tool_a, tool_b])
        executor = ParallelExecutor(max_concurrency=5)

        tool_calls = [
            ToolCall(id="c1", name="tool_a", arguments={"message": "a"}),
            ToolCall(id="c2", name="tool_b", arguments={"message": "b"}),
        ]
        results = await executor.execute_all(tool_calls, registry, None)

        assert len(results) == 2
        assert {r.tool_name for r in results} == {"tool_a", "tool_b"}
        assert all(r.status == "success" for r in results)

    @pytest.mark.asyncio
    async def test_execute_all_preserves_order(self):
        from tools.orchestrator import ParallelExecutor

        tools = [
            _make_tool(f"tool_{i}", handler=(lambda idx: lambda **kw: f"result_{idx}")(i), parameters=[])
            for i in range(5)
        ]
        registry = _make_registry(tools)
        executor = ParallelExecutor(max_concurrency=3)

        tool_calls = [ToolCall(id=f"c{i}", name=f"tool_{i}", arguments={}) for i in range(5)]
        results = await executor.execute_all(tool_calls, registry, None)

        assert len(results) == 5
        for i, r in enumerate(results):
            assert r.tool_name == f"tool_{i}"

    @pytest.mark.asyncio
    async def test_execute_all_respects_dependencies(self):
        from tools.orchestrator import ParallelExecutor

        execution_order = []

        async def ordered(**kw) -> str:
            name = kw.get("name", "")
            execution_order.append(name)
            return name

        tool_a = _make_tool("tool_a", async_handler=ordered, depends_on=[], parameters=[])
        tool_b = _make_tool("tool_b", async_handler=ordered, depends_on=["tool_a"], parameters=[])
        tool_c = _make_tool("tool_c", async_handler=ordered, depends_on=["tool_a"], parameters=[])
        tool_d = _make_tool("tool_d", async_handler=ordered, depends_on=["tool_b", "tool_c"], parameters=[])
        registry = _make_registry([tool_a, tool_b, tool_c, tool_d])
        executor = ParallelExecutor(max_concurrency=5)

        tool_calls = [
            ToolCall(id="c1", name="tool_a", arguments={"name": "a"}),
            ToolCall(id="c2", name="tool_b", arguments={"name": "b"}),
            ToolCall(id="c3", name="tool_c", arguments={"name": "c"}),
            ToolCall(id="c4", name="tool_d", arguments={"name": "d"}),
        ]
        results = await executor.execute_all(tool_calls, registry, None)

        assert len(results) == 4
        assert all(r.status == "success" for r in results)
        # tool_a must execute before tool_b, tool_c; tool_b and tool_c before tool_d
        a_idx = execution_order.index("a")
        b_idx = execution_order.index("b")
        c_idx = execution_order.index("c")
        d_idx = execution_order.index("d")
        assert a_idx < b_idx
        assert a_idx < c_idx
        assert b_idx < d_idx
        assert c_idx < d_idx

    @pytest.mark.asyncio
    async def test_execute_all_partial_failure(self):
        from tools.orchestrator import ParallelExecutor

        async def succeeder(**kw) -> str:
            return kw.get("msg", "")

        def failer(**kw):
            raise RuntimeError("fail")

        tool_ok = _make_tool("ok", async_handler=succeeder, parameters=[])
        tool_fail = _make_tool("fail", handler=failer, parameters=[])
        registry = _make_registry([tool_ok, tool_fail])
        executor = ParallelExecutor(max_concurrency=5)

        tool_calls = [
            ToolCall(id="c1", name="ok", arguments={"msg": "good"}),
            ToolCall(id="c2", name="fail", arguments={}),
        ]
        results = await executor.execute_all(tool_calls, registry, None)

        assert len(results) == 2
        ok_result = next(r for r in results if r.tool_name == "ok")
        fail_result = next(r for r in results if r.tool_name == "fail")
        assert ok_result.status == "success"
        assert fail_result.status == "error"
        assert fail_result.error == "fail"

    @pytest.mark.asyncio
    async def test_execute_all_semaphore_concurrency(self):
        from tools.orchestrator import ParallelExecutor

        concurrent = 0
        max_concurrent = 0

        async def tracked_sem(**kw) -> str:
            nonlocal concurrent, max_concurrent
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.01)
            concurrent -= 1
            return kw.get("msg", "")

        tools = [_make_tool(f"sem_tool_{i}", async_handler=tracked_sem, parameters=[]) for i in range(10)]
        registry = _make_registry(tools)
        executor = ParallelExecutor(max_concurrency=3)

        tool_calls = [ToolCall(id=f"c{i}", name=f"sem_tool_{i}", arguments={"msg": f"m{i}"}) for i in range(10)]
        results = await executor.execute_all(tool_calls, registry, None)

        assert len(results) == 10
        assert all(r.status == "success" for r in results)
        assert max_concurrent <= 3

    @pytest.mark.asyncio
    async def test_execute_all_empty(self):
        from tools.orchestrator import ParallelExecutor

        registry = _make_registry([])
        executor = ParallelExecutor(max_concurrency=5)
        results = await executor.execute_all([], registry, None)

        assert results == []


# ---------------------------------------------------------------------------
# StreamingExecutor
# ---------------------------------------------------------------------------


class TestStreamingExecutor:
    @pytest.mark.asyncio
    async def test_execute_streaming_yields_chunks(self):
        from tools.orchestrator import StreamingExecutor

        async def streamer(**kw) -> str:
            return kw.get("msg", "")

        tool = _make_tool("stream_tool", async_handler=streamer, parameters=[])
        registry = _make_registry([tool])
        executor = StreamingExecutor()

        call = ToolCall(id="c-stream", name="stream_tool", arguments={"msg": "hello"})
        results = []
        async for chunk in executor.execute_streaming(call, registry, None):
            results.append(chunk)

        assert len(results) > 0
        assert isinstance(results[0], str)

    @pytest.mark.asyncio
    async def test_execute_streaming_missing_tool(self):
        from tools.orchestrator import StreamingExecutor

        registry = _make_registry([])
        executor = StreamingExecutor()

        call = ToolCall(id="c-stream", name="missing", arguments={})
        results = []
        async for chunk in executor.execute_streaming(call, registry, None):
            results.append(chunk)

        assert len(results) > 0
        assert any("not found" in r.lower() for r in results)

    @pytest.mark.asyncio
    async def test_execute_streaming_error(self):
        from tools.orchestrator import StreamingExecutor

        def failer(**kw):
            raise RuntimeError("stream broken")

        tool = _make_tool("fail_stream", handler=failer, parameters=[])
        registry = _make_registry([tool])
        executor = StreamingExecutor()

        call = ToolCall(id="c-stream", name="fail_stream", arguments={})
        results = []
        async for chunk in executor.execute_streaming(call, registry, None):
            results.append(chunk)

        assert any("stream broken" in r for r in results)


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------


class TestDependencyResolution:
    def test_single_level_no_deps(self):
        from tools.orchestrator import _resolve_dependency_levels

        tools = [
            _make_tool("a"),
            _make_tool("b"),
            _make_tool("c"),
        ]
        registry = _make_registry(tools)
        levels = _resolve_dependency_levels(tools, registry)

        assert len(levels) == 1
        assert len(levels[0]) == 3

    def test_three_levels_linear_chain(self):
        from tools.orchestrator import _resolve_dependency_levels

        tool_a = _make_tool("a", depends_on=[])
        tool_b = _make_tool("b", depends_on=["a"])
        tool_c = _make_tool("c", depends_on=["b"])
        registry = _make_registry([tool_a, tool_b, tool_c])
        levels = _resolve_dependency_levels([tool_a, tool_b, tool_c], registry)

        assert len(levels) == 3
        assert levels[0] == {"a"}
        assert levels[1] == {"b"}
        assert levels[2] == {"c"}

    def test_diamond_dependency_dag(self):
        from tools.orchestrator import _resolve_dependency_levels

        tool_a = _make_tool("a", depends_on=[])
        tool_b = _make_tool("b", depends_on=["a"])
        tool_c = _make_tool("c", depends_on=["a"])
        tool_d = _make_tool("d", depends_on=["b", "c"])
        registry = _make_registry([tool_a, tool_b, tool_c, tool_d])
        levels = _resolve_dependency_levels([tool_a, tool_b, tool_c, tool_d], registry)

        assert len(levels) == 3
        assert levels[0] == {"a"}
        assert levels[1] == {"b", "c"}
        assert levels[2] == {"d"}

    def test_unresolved_dependency_raises(self):
        from tools.orchestrator import _resolve_dependency_levels

        tool_x = _make_tool("x", depends_on=["z"])
        registry = _make_registry([tool_x])

        with pytest.raises(ValueError, match="Unresolved dependencies"):
            _resolve_dependency_levels([tool_x], registry)

    def test_circular_dependency_detected(self):
        from tools.orchestrator import _resolve_dependency_levels

        tool_a = _make_tool("a", depends_on=["b"])
        tool_b = _make_tool("b", depends_on=["a"])
        registry = _make_registry([tool_a, tool_b])

        with pytest.raises(ValueError, match="cycl"):
            _resolve_dependency_levels([tool_a, tool_b], registry)
