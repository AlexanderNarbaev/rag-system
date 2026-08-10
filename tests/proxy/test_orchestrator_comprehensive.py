"""Comprehensive tests for proxy/app/tools/orchestrator.py.

Covers CompositionPattern enum, ChainPattern/FanOutPattern/ConditionalPattern
dataclasses, ToolComposer factories, _resolve_dependency_levels,
_compute_backoff, ParallelExecutor (single + parallel),
and StreamingExecutor.
"""

from __future__ import annotations

import asyncio

import pytest

from proxy.app.tools.definition import RetryPolicy, ToolCall, ToolDefinition
from proxy.app.tools.orchestrator import (
    ChainPattern,
    CompositionPattern,
    ConditionalPattern,
    FanOutPattern,
    ParallelExecutor,
    StreamingExecutor,
    ToolComposer,
    _compute_backoff,
    _resolve_dependency_levels,
)
from proxy.app.tools.registry import EnhancedToolRegistry

# ---------------------------------------------------------------------------
# CompositionPattern enum
# ---------------------------------------------------------------------------


class TestCompositionPattern:
    def test_values(self):
        assert CompositionPattern.CHAIN.value == "chain"
        assert CompositionPattern.FAN_OUT.value == "fan_out"
        assert CompositionPattern.CONDITIONAL.value == "conditional"

    def test_member_count(self):
        assert len(list(CompositionPattern)) == 3


# ---------------------------------------------------------------------------
# Pattern dataclasses
# ---------------------------------------------------------------------------


class TestChainPattern:
    def test_init(self):
        p = ChainPattern(steps=["a", "b"])
        assert p.steps == ["a", "b"]
        assert p.input_mapper is None

    def test_with_mapper(self):
        def mapper(r):
            return {"x": 1}

        p = ChainPattern(steps=["a"], input_mapper=mapper)
        assert p.input_mapper is mapper


class TestFanOutPattern:
    def test_init(self):
        p = FanOutPattern(tool_name="t", inputs=[{"x": 1}])
        assert p.tool_name == "t"
        assert p.inputs == [{"x": 1}]


class TestConditionalPattern:
    def test_init(self):
        def cond(x):
            return x > 0

        p = ConditionalPattern(condition=cond, true_tool="a", false_tool="b")
        assert p.true_tool == "a"
        assert p.false_tool == "b"
        assert p.condition is cond


# ---------------------------------------------------------------------------
# ToolComposer factories
# ---------------------------------------------------------------------------


class TestToolComposer:
    def test_chain(self):
        p = ToolComposer.chain(["a", "b", "c"])
        assert isinstance(p, ChainPattern)
        assert p.steps == ["a", "b", "c"]

    def test_chain_with_mapper(self):
        def mapper(r):
            return {}

        p = ToolComposer.chain(["a"], input_mapper=mapper)
        assert p.input_mapper is mapper

    def test_chain_makes_copy(self):
        tools = ["a", "b"]
        p = ToolComposer.chain(tools)
        tools.append("c")
        # Should not be affected
        assert p.steps == ["a", "b"]

    def test_fan_out(self):
        p = ToolComposer.fan_out("t", [{"x": 1}, {"x": 2}])
        assert isinstance(p, FanOutPattern)
        assert p.tool_name == "t"
        assert len(p.inputs) == 2

    def test_fan_out_makes_copy(self):
        inputs = [{"x": 1}]
        p = ToolComposer.fan_out("t", inputs)
        inputs.append({"x": 2})
        assert len(p.inputs) == 1

    def test_conditional(self):
        def cond(x):
            return True

        p = ToolComposer.conditional(cond, "a", "b")
        assert isinstance(p, ConditionalPattern)


# ---------------------------------------------------------------------------
# _compute_backoff
# ---------------------------------------------------------------------------


class TestComputeBackoff:
    def test_none_returns_zero(self):
        assert _compute_backoff(None, 1) == 0.0

    def test_constant(self):
        policy = RetryPolicy(
            max_retries=3,
            backoff="constant",
            initial_delay_seconds=1.0,
            jitter=False,
        )
        assert _compute_backoff(policy, 1) == 1.0
        assert _compute_backoff(policy, 3) == 1.0

    def test_linear(self):
        policy = RetryPolicy(
            max_retries=3,
            backoff="linear",
            initial_delay_seconds=0.5,
            jitter=False,
        )
        assert _compute_backoff(policy, 1) == 0.5
        assert _compute_backoff(policy, 3) == 1.5

    def test_exponential(self):
        policy = RetryPolicy(
            max_retries=3,
            backoff="exponential",
            initial_delay_seconds=1.0,
            jitter=False,
        )
        assert _compute_backoff(policy, 1) == 1.0
        assert _compute_backoff(policy, 2) == 2.0
        assert _compute_backoff(policy, 3) == 4.0

    def test_jitter(self):
        # With jitter, delay is randomized between 0.5x and 1.5x
        policy = RetryPolicy(
            max_retries=3,
            backoff="exponential",
            initial_delay_seconds=1.0,
            jitter=True,
        )
        delays = [_compute_backoff(policy, 2) for _ in range(20)]
        # All should be around 2.0 ± 50%
        for d in delays:
            assert 1.0 <= d <= 3.0


# ---------------------------------------------------------------------------
# _resolve_dependency_levels
# ---------------------------------------------------------------------------


class TestResolveLevels:
    def test_no_tools(self):
        reg = EnhancedToolRegistry()
        EnhancedToolRegistry._instance = reg
        levels = _resolve_dependency_levels([], reg)
        assert levels == []

    def test_no_deps_one_level(self):
        reg = EnhancedToolRegistry()
        a = ToolDefinition(name="a", description="d", handler=lambda: None)
        b = ToolDefinition(name="b", description="d", handler=lambda: None)
        reg.register(a)
        reg.register(b)
        levels = _resolve_dependency_levels([a, b], reg)
        assert len(levels) == 1
        assert levels[0] == {"a", "b"}

    def test_chain_two_levels(self):
        reg = EnhancedToolRegistry()
        a = ToolDefinition(name="a", description="d", handler=lambda: None)
        b = ToolDefinition(
            name="b",
            description="d",
            depends_on=["a"],
            handler=lambda: None,
        )
        reg.register(a)
        reg.register(b)
        levels = _resolve_dependency_levels([a, b], reg)
        assert len(levels) == 2
        assert levels[0] == {"a"}
        assert levels[1] == {"b"}

    def test_unknown_dep_raises(self):
        reg = EnhancedToolRegistry()
        a = ToolDefinition(
            name="a",
            description="d",
            depends_on=["missing"],
            handler=lambda: None,
        )
        reg.register(a)
        with pytest.raises(ValueError, match="Unresolved dependencies"):
            _resolve_dependency_levels([a], reg)


# ---------------------------------------------------------------------------
# ParallelExecutor
# ---------------------------------------------------------------------------


@pytest.fixture
def registry():
    EnhancedToolRegistry._instance = None
    return EnhancedToolRegistry()


class TestParallelExecutor:
    def test_empty_tool_calls(self, registry):
        executor = ParallelExecutor()
        results = asyncio.run(executor.execute_all([], registry))
        assert results == []

    def test_unknown_tools_return_not_found(self, registry):
        executor = ParallelExecutor()
        tc1 = ToolCall(id="1", name="missing", arguments={})
        results = asyncio.run(executor.execute_all([tc1], registry))
        assert len(results) == 1
        assert "not found" in results[0].error

    def test_execute_single_returns_result(self, registry):
        async def handler(x: int) -> str:
            return f"got {x}"

        t = ToolDefinition(
            name="t",
            description="d",
            parameters=[],
            async_handler=handler,
        )
        registry.register(t)
        tc = ToolCall(id="call-1", name="t", arguments={"x": 5})
        executor = ParallelExecutor()
        result = asyncio.run(executor.execute_single(tc, registry))
        assert result.content == "got 5"
        assert result.tool_call_id == "call-1"

    def test_execute_single_unknown_tool(self, registry):
        tc = ToolCall(id="x", name="missing", arguments={})
        executor = ParallelExecutor()
        result = asyncio.run(executor.execute_single(tc, registry))
        assert "not found" in result.error

    def test_execute_all_preserves_order(self, registry):
        async def make_handler(prefix: str):
            async def handler(**kwargs):
                await asyncio.sleep(0)
                return f"{prefix}_result"

            return handler

        t1 = ToolDefinition(
            name="t1",
            description="d",
            parameters=[],
            async_handler=asyncio.run(make_handler("t1")),
        )
        t2 = ToolDefinition(
            name="t2",
            description="d",
            parameters=[],
            async_handler=asyncio.run(make_handler("t2")),
        )
        registry.register(t1)
        registry.register(t2)
        tc1 = ToolCall(id="1", name="t1", arguments={})
        tc2 = ToolCall(id="2", name="t2", arguments={})
        executor = ParallelExecutor()
        results = asyncio.run(executor.execute_all([tc1, tc2], registry))
        assert len(results) == 2
        assert results[0].content == "t1_result"
        assert results[1].content == "t2_result"

    def test_execute_all_respects_dependencies(self, registry):
        order = []

        async def a_handler(**kwargs):
            order.append("a")
            return "A"

        async def b_handler(**kwargs):
            order.append("b")
            return "B"

        a = ToolDefinition(
            name="a",
            description="d",
            parameters=[],
            async_handler=a_handler,
        )
        b = ToolDefinition(
            name="b",
            description="d",
            parameters=[],
            depends_on=["a"],
            async_handler=b_handler,
        )
        registry.register(a)
        registry.register(b)
        tc_a = ToolCall(id="1", name="a", arguments={})
        tc_b = ToolCall(id="2", name="b", arguments={})

        executor = ParallelExecutor()
        asyncio.run(executor.execute_all([tc_b, tc_a], registry))
        # a runs before b because of dependency
        assert order.index("a") < order.index("b")


# ---------------------------------------------------------------------------
# StreamingExecutor
# ---------------------------------------------------------------------------


class TestStreamingExecutor:
    def test_unknown_tool_yields_error(self, registry):
        tc = ToolCall(id="x", name="missing", arguments={})
        executor = StreamingExecutor()

        async def collect():
            return [chunk async for chunk in executor.execute_streaming(tc, registry)]

        results = asyncio.run(collect())
        assert any("not found" in r for r in results)

    def test_yields_content_in_chunks(self, registry):
        async def handler(**kwargs) -> str:
            return "x" * 2048  # 2 chunks worth

        t = ToolDefinition(
            name="t",
            description="d",
            parameters=[],
            async_handler=handler,
        )
        registry.register(t)
        tc = ToolCall(id="1", name="t", arguments={})
        executor = StreamingExecutor()

        async def collect():
            return [chunk async for chunk in executor.execute_streaming(tc, registry)]

        chunks = asyncio.run(collect())
        # 2 chunks of 1024 each
        assert len(chunks) == 2
        assert all(len(c) == 1024 for c in chunks)

    def test_error_result_yielded(self, registry):
        async def handler(**kwargs) -> str:
            raise RuntimeError("bad")

        t = ToolDefinition(
            name="t",
            description="d",
            parameters=[],
            async_handler=handler,
        )
        registry.register(t)
        tc = ToolCall(id="1", name="t", arguments={})
        executor = StreamingExecutor()

        async def collect():
            return [chunk async for chunk in executor.execute_streaming(tc, registry)]

        chunks = asyncio.run(collect())
        assert any("bad" in c for c in chunks)
