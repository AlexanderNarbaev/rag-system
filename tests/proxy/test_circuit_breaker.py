"""Tests for proxy/app/circuit_breaker.py — Circuit Breaker pattern."""

import asyncio
import time

import pytest

# NOTE: Do NOT mock heavy dependencies (qdrant_client, sentence_transformers,
# etc.) at module level here. The circuit_breaker module only depends on
# prometheus_client and stdlib. Mocking modules here would leak into other
# tests that run in the same session (e.g., test_hyde.py which relies on
# the real QdrantClient import behavior).


@pytest.fixture(autouse=True)
def _reset_breakers():
    """Reset circuit breaker registry before each test."""
    from proxy.app.shared.circuit_breaker import _breakers, _frozen, reset_all_breakers

    _frozen = False  # noqa: F811
    reset_all_breakers()
    _breakers.clear()
    yield
    _frozen = False
    reset_all_breakers()
    _breakers.clear()


# ── CircuitBreaker State Transitions ────────────────────────────────────────


class TestCircuitBreakerStates:
    """Test circuit breaker state transitions."""

    def test_initial_state_closed(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=10)
        assert cb.state == State.CLOSED
        assert cb.failure_count == 0

    def test_failures_increment(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=5, cooldown_seconds=10)
        cb.failure()
        cb.failure()
        assert cb.failure_count == 2
        assert cb.state == State.CLOSED

    def test_circuit_opens_after_threshold(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=10)
        cb.failure()
        cb.failure()
        cb.failure()
        assert cb.state == State.OPEN
        assert cb.failure_count == 3

    def test_circuit_opens_exactly_at_threshold(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=10)
        cb.failure()  # 1 — still CLOSED
        assert cb.state == State.CLOSED
        cb.failure()  # 2 — OPEN
        assert cb.state == State.OPEN

    def test_open_rejects_calls_immediately_sync(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=10)
        cb.failure()  # Opens circuit
        assert cb.state == State.OPEN

        with pytest.raises(CircuitBreakerOpenError, match="OPEN"):
            cb.call_sync(lambda: "should not run")

    @pytest.mark.asyncio
    async def test_open_rejects_calls_immediately_async(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=10)
        cb.failure()  # Opens circuit
        assert cb.state == State.OPEN

        with pytest.raises(CircuitBreakerOpenError, match="OPEN"):
            await cb.call(lambda: "should not run")

    def test_half_open_after_cooldown(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.failure()  # Opens circuit
        assert cb.state == State.OPEN

        # Wait for cooldown
        time.sleep(0.02)

        # State is lazy-evaluated on access
        assert cb.state == State.HALF_OPEN

    def test_success_in_half_open_closes_circuit_sync(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.failure()  # Opens circuit
        time.sleep(0.02)

        assert cb.state == State.HALF_OPEN
        result = cb.call_sync(lambda: "success")
        assert result == "success"
        assert cb.state == State.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_success_in_half_open_closes_circuit_async(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.failure()  # Opens circuit
        await asyncio.sleep(0.02)

        assert cb.state == State.HALF_OPEN

        async def async_fn():
            return "async_success"

        result = await cb.call(async_fn)
        assert result == "async_success"
        assert cb.state == State.CLOSED
        assert cb.failure_count == 0

    def test_failure_in_half_open_reopens_circuit_sync(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.failure()  # Opens circuit
        time.sleep(0.02)

        assert cb.state == State.HALF_OPEN

        def failing_fn():
            raise ValueError("service error")

        with pytest.raises(ValueError, match="service error"):
            cb.call_sync(failing_fn)

        assert cb.state == State.OPEN

    @pytest.mark.asyncio
    async def test_failure_in_half_open_reopens_circuit_async(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.failure()  # Opens circuit
        await asyncio.sleep(0.02)

        assert cb.state == State.HALF_OPEN

        async def failing_fn():
            raise RuntimeError("backend down")

        with pytest.raises(RuntimeError, match="backend down"):
            await cb.call(failing_fn)

        assert cb.state == State.OPEN


# ── CircuitBreaker call() and call_sync() ────────────────────────────────────


class TestCircuitBreakerCall:
    """Test call() and call_sync() execution and error handling."""

    def test_call_sync_success(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test")
        result = cb.call_sync(lambda x, y: x + y, 10, 20)
        assert result == 30
        assert cb.failure_count == 0

    def test_call_sync_failure_increments_count(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=5)
        for i in range(3):
            with pytest.raises(ValueError):
                cb.call_sync(lambda: (_ for _ in ()).throw(ValueError("fail")))
            assert cb.failure_count == i + 1

    def test_call_sync_resets_on_success(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=5)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call_sync(lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert cb.failure_count == 2

        cb.call_sync(lambda: "ok")
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_call_async_success(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test")

        async def compute(a, b):
            return a * b

        result = await cb.call(compute, 7, 6)
        assert result == 42

    @pytest.mark.asyncio
    async def test_call_async_failure(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test")

        async def broken():
            raise ConnectionError("no connection")

        with pytest.raises(ConnectionError, match="no connection"):
            await cb.call(broken)
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_call_with_sync_fn_in_async_context(self):
        """call() should handle sync functions when called from async context."""
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test")
        result = await cb.call(lambda: "sync_ok")
        assert result == "sync_ok"

    def test_call_sync_preserves_return_value_types(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test")
        assert cb.call_sync(lambda: 42) == 42
        assert cb.call_sync(lambda: 3.14) == 3.14
        assert cb.call_sync(lambda: None) is None
        assert cb.call_sync(lambda: [1, 2, 3]) == [1, 2, 3]
        assert cb.call_sync(lambda: {"key": "value"}) == {"key": "value"}


# ── Half-Open Max Calls ──────────────────────────────────────────────────────


class TestHalfOpenMaxCalls:
    """Test half_open_max limits."""

    def test_half_open_success_closes_circuit_immediately(self):
        """After a successful call in HALF_OPEN, circuit closes immediately.

        The half_open_max only matters when multiple concurrent callers enter
        HALF_OPEN before the state transition is visible. Once a call succeeds,
        the circuit is CLOSED and half_open_calls is reset.
        """
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01, half_open_max=2)
        cb.failure()  # OPEN
        time.sleep(0.02)  # HALF_OPEN

        # First call succeeds → circuit closes immediately
        cb.call_sync(lambda: "first")
        assert cb.state == State.CLOSED

        # Subsequent calls go through normally (circuit is CLOSED)
        result = cb.call_sync(lambda: "second")
        assert result == "second"
        cb.call_sync(lambda: "third")

    def test_half_open_max_rejects_when_limit_hit(self):
        """half_open_max rejects calls before success transitions state.

        When multiple entries happen rapidly (e.g., async), half_open_max
        ensures we don't flood the recovering service.

        We simulate this by entering HALF_OPEN, manually incrementing
        half_open_calls to the limit, then verifying rejection.
        """
        from proxy.app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01, half_open_max=2)
        cb.failure()  # OPEN
        time.sleep(0.02)  # HALF_OPEN
        assert cb.state == State.HALF_OPEN

        # Manually simulate rapid entries that exhaust the limit
        cb._half_open_calls = 2  # noqa: SLF001

        # Next call should be rejected
        with pytest.raises(CircuitBreakerOpenError):
            cb.call_sync(lambda: "should be rejected")

    def test_half_open_max_resets_after_reopen(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01, half_open_max=1)
        cb.failure()  # OPEN
        time.sleep(0.02)  # HALF_OPEN

        # Allow one call, let it fail
        with pytest.raises(ValueError):
            cb.call_sync(lambda: (_ for _ in ()).throw(ValueError("fail")))
        assert cb.state == State.OPEN

        time.sleep(0.02)  # Back to HALF_OPEN
        # Should allow one call again
        result = cb.call_sync(lambda: "recovery")
        assert result == "recovery"
        assert cb.state == State.CLOSED


# ── Prometheus Metrics ───────────────────────────────────────────────────────


class TestCircuitBreakerMetrics:
    """Test Prometheus metrics integration."""

    def test_metrics_defined(self):
        from proxy.app.shared.circuit_breaker import circuit_breaker_failures_total, circuit_breaker_state

        assert circuit_breaker_state is not None
        assert circuit_breaker_failures_total is not None

    def test_state_gauge_tracks_closed(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("gauge_test")
        # Gauge should show 0 (CLOSED)
        # We can't easily read back gauge values, but we verify no errors
        assert cb.state.metric_value == 0

    def test_state_gauge_tracks_open(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("gauge_test", failure_threshold=1)
        cb.failure()
        assert cb.state.metric_value == 1  # OPEN

    def test_state_gauge_tracks_half_open(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("gauge_test", failure_threshold=1, cooldown_seconds=0.01)
        cb.failure()
        time.sleep(0.02)
        assert cb.state.metric_value == 2  # HALF_OPEN

    def test_failures_counter_increments(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("counter_test")
        cb.failure()
        cb.failure()
        # Counter is incremented via circuit_breaker_failures_total.labels(name).inc()
        # We verify the counter object exists and the failure method runs without error
        assert cb.failure_count == 2


# ── Registry Functions ───────────────────────────────────────────────────────


class TestBreakerRegistry:
    """Test module-level registry functions."""

    def test_get_breaker_creates_and_returns(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, _breakers, get_breaker

        assert "registry_test" not in _breakers

        cb = get_breaker("registry_test", failure_threshold=4, cooldown_seconds=15)
        assert isinstance(cb, CircuitBreaker)
        assert cb.name == "registry_test"
        assert cb.failure_threshold == 4
        assert cb.cooldown_seconds == 15

        assert "registry_test" in _breakers

    def test_get_breaker_returns_same_instance(self):
        from proxy.app.shared.circuit_breaker import get_breaker

        cb1 = get_breaker("shared")
        cb2 = get_breaker("shared")
        assert cb1 is cb2

    def test_get_breaker_uses_defaults(self):
        from proxy.app.shared.circuit_breaker import get_breaker

        cb = get_breaker("defaults")
        assert cb.failure_threshold == 5
        assert cb.cooldown_seconds == 30.0
        assert cb.half_open_max == 2

    def test_get_all_breakers(self):
        from proxy.app.shared.circuit_breaker import get_all_breakers, get_breaker

        get_breaker("a")
        get_breaker("b")
        all_b = get_all_breakers()
        assert "a" in all_b
        assert "b" in all_b
        assert len(all_b) == 2

    def test_reset_all_breakers(self):
        from proxy.app.shared.circuit_breaker import State, get_breaker, reset_all_breakers

        cb = get_breaker("to_reset")
        cb.failure()
        cb.failure()
        cb.failure()
        cb.failure()
        cb.failure()
        assert cb.state == State.OPEN

        reset_all_breakers()
        assert cb.state == State.CLOSED
        assert cb.failure_count == 0


# ── Edge Cases ────────────────────────────────────────────────────────────────


class TestCircuitBreakerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_failure_threshold_opens_immediately(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("zero", failure_threshold=0)
        assert cb.state == State.CLOSED
        cb.failure()
        assert cb.state == State.OPEN

    def test_very_long_cooldown(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("long", failure_threshold=1, cooldown_seconds=999999)
        cb.failure()
        assert cb.state == State.OPEN
        # Should still be OPEN since cooldown is far in the future
        assert cb.state == State.OPEN

    def test_multiple_services_independent(self):
        from proxy.app.shared.circuit_breaker import State, get_breaker

        qdrant = get_breaker("qdrant", failure_threshold=2)
        llm = get_breaker("llm", failure_threshold=3)

        # Fail qdrant twice — opens its breaker
        qdrant.failure()
        qdrant.failure()
        assert qdrant.state == State.OPEN

        # LLM should still be closed with only 1 failure
        llm.failure()
        assert llm.state == State.CLOSED
        assert llm.failure_count == 1

    def test_success_does_not_close_if_closed(self):
        """Calling success() on a closed breaker is a no-op."""
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("test")
        assert cb.state == State.CLOSED
        cb.success()
        assert cb.state == State.CLOSED
        assert cb.failure_count == 0

    def test_exception_propagation_sync(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=5)

        class CustomError(Exception):
            pass

        with pytest.raises(CustomError):
            cb.call_sync(lambda: (_ for _ in ()).throw(CustomError("custom")))
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_exception_propagation_async(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test", failure_threshold=5)

        class BackendError(Exception):
            pass

        async def raise_backend():
            raise BackendError("backend timeout")

        with pytest.raises(BackendError):
            await cb.call(raise_backend)
        assert cb.failure_count == 1


# ── CircuitBreakerOpenError ──────────────────────────────────────────────────


class TestCircuitBreakerOpenError:
    """Test the CircuitBreakerOpenError exception."""

    def test_error_message_contains_name(self):
        from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError

        err = CircuitBreakerOpenError("qdrant")
        assert "qdrant" in str(err)
        assert err.name == "qdrant"

    def test_error_is_exception(self):
        from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError

        err = CircuitBreakerOpenError("test")
        assert isinstance(err, Exception)

    def test_error_can_be_caught(self):
        from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError

        try:
            raise CircuitBreakerOpenError("test")
        except CircuitBreakerOpenError as e:
            assert e.name == "test"


# ── Rapid State Toggles ──────────────────────────────────────────────────────


class TestCircuitBreakerRapidToggles:
    """Test rapid open/close cycles and resilience to repeated state changes."""

    def test_multiple_open_close_cycles(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("cycles", failure_threshold=2, cooldown_seconds=0.01)
        for _ in range(5):
            cb.failure()
            cb.failure()
            assert cb.state == State.OPEN
            time.sleep(0.02)
            assert cb.state == State.HALF_OPEN
            cb.call_sync(lambda: "recover")
            assert cb.state == State.CLOSED
            assert cb.failure_count == 0

    def test_rapid_failure_recovery_toggle(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("rapid", failure_threshold=1, cooldown_seconds=0.0)
        for _ in range(3):
            cb.failure()
            # With cooldown=0, accessing .state immediately transitions OPEN→HALF_OPEN
            assert cb.state == State.HALF_OPEN
            cb.call_sync(lambda: "ok")
            assert cb.state == State.CLOSED

    def test_success_after_open_without_half_open_call(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("direct_success", failure_threshold=1, cooldown_seconds=0.01)
        cb.failure()
        assert cb.state == State.OPEN
        # success() directly when OPEN should close the circuit
        cb.success()
        assert cb.state == State.CLOSED
        assert cb.failure_count == 0


# ── call/call_sync with args/kwargs ──────────────────────────────────────────


class TestCircuitBreakerArgsKwargs:
    """Test call() and call_sync() with complex arguments."""

    def test_call_sync_with_kwargs(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("kwargs")
        result = cb.call_sync(lambda prefix="", suffix="": f"{prefix}hello{suffix}", prefix="<<", suffix=">>")
        assert result == "<<hello>>"

    def test_call_sync_with_mixed_args_kwargs(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("mixed")
        result = cb.call_sync(lambda a, b, mul=1: (a + b) * mul, 3, 4, mul=2)
        assert result == 14

    @pytest.mark.asyncio
    async def test_call_async_with_kwargs(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("async_kwargs")

        async def build_msg(name: str, count: int) -> str:
            return f"{name}: {count}"

        result = await cb.call(build_msg, name="items", count=42)
        assert result == "items: 42"

    def test_call_sync_preserves_none_return(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("none_test")

        result = cb.call_sync(lambda: None)
        assert result is None


# ── Half-Open Concurrency Simulation ─────────────────────────────────────────


class TestHalfOpenConcurrency:
    """Simulate concurrent entries into HALF_OPEN state."""

    def test_half_open_limit_with_multiple_fast_successes(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("fast", failure_threshold=1, cooldown_seconds=0.01, half_open_max=2)
        cb.failure()
        time.sleep(0.02)
        assert cb.state == State.HALF_OPEN

        # First success closes circuit — subsequent calls go through
        cb.call_sync(lambda: "s1")
        assert cb.state == State.CLOSED
        cb.call_sync(lambda: "s2")
        assert cb.state == State.CLOSED

    @pytest.mark.asyncio
    async def test_async_concurrent_half_open_entries(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, State

        cb = CircuitBreaker("async_half", failure_threshold=1, cooldown_seconds=0.01, half_open_max=2)
        cb.failure()
        await asyncio.sleep(0.02)
        assert cb.state == State.HALF_OPEN

        executed = []

        async def worker(name: str):
            try:
                result = await cb.call(lambda: executed.append(name))
                return result
            except CircuitBreakerOpenError:
                return None

        # Launch tasks concurrently
        _results = await asyncio.gather(*(worker(f"w{i}") for i in range(4)))
        assert cb.state == State.CLOSED

    def test_half_open_max_zero_allows_no_calls(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, State

        cb = CircuitBreaker("zero_max", failure_threshold=1, cooldown_seconds=0.01, half_open_max=0)
        cb.failure()
        time.sleep(0.02)
        assert cb.state == State.HALF_OPEN

        with pytest.raises(CircuitBreakerOpenError):
            cb.call_sync(lambda: "rejected")


# ── State Enum Behavior ──────────────────────────────────────────────────────


class TestStateEnum:
    """Test State enum properties and behavior."""

    def test_state_string_values(self):
        from proxy.app.shared.circuit_breaker import State

        assert str(State.CLOSED) == "closed"
        assert State.CLOSED.value == "closed"
        assert State.OPEN.value == "open"
        assert State.HALF_OPEN.value == "half_open"

    def test_state_metric_values(self):
        from proxy.app.shared.circuit_breaker import State

        assert State.CLOSED.metric_value == 0
        assert State.OPEN.metric_value == 1
        assert State.HALF_OPEN.metric_value == 2

    def test_state_comparison(self):
        from proxy.app.shared.circuit_breaker import State

        assert State("closed") == State.CLOSED
        assert State("open") == State.OPEN
        assert State("half_open") == State.HALF_OPEN


# ── Failure Counting Boundaries ──────────────────────────────────────────────


class TestFailureCounting:
    """Test edge cases in failure counting and threshold behavior."""

    def test_failure_count_does_not_reset_on_state_change(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("count", failure_threshold=2)
        cb.failure()
        cb.failure()
        assert cb.failure_count == 2

    def test_failure_threshold_one_opens_on_single_failure(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("single", failure_threshold=1)
        cb.failure()
        assert cb.state == State.OPEN

    def test_call_sync_does_not_increment_on_open_rejection(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

        cb = CircuitBreaker("reject", failure_threshold=1)
        cb.failure()
        count_before = cb.failure_count

        with pytest.raises(CircuitBreakerOpenError):
            cb.call_sync(lambda: "nope")
        assert cb.failure_count == count_before

    @pytest.mark.asyncio
    async def test_call_does_not_increment_on_open_rejection(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

        cb = CircuitBreaker("reject_async", failure_threshold=1)
        cb.failure()
        count_before = cb.failure_count

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(lambda: "nope")
        assert cb.failure_count == count_before


# ── Registry Advanced ────────────────────────────────────────────────────────


class TestRegistryAdvanced:
    """Advanced registry tests."""

    def test_reset_all_preserves_breaker_identity(self):
        from proxy.app.shared.circuit_breaker import State, get_breaker, reset_all_breakers

        cb = get_breaker("identity_test")
        cb.failure()
        cb.failure()
        cb.failure()
        cb.failure()
        cb.failure()

        reset_all_breakers()
        assert cb.state == State.CLOSED
        assert cb.failure_count == 0

        # Same instance should still be in the registry
        cb2 = get_breaker("identity_test")
        assert cb is cb2

    def test_get_all_breakers_returns_copy(self):
        from proxy.app.shared.circuit_breaker import get_all_breakers, get_breaker

        get_breaker("copy_test")
        all_breakers = get_all_breakers()
        all_breakers["new_fake"] = None  # type: ignore[assignment]
        # Original registry should be unaffected
        second_copy = get_all_breakers()
        assert "new_fake" not in second_copy

    def test_multiple_registry_names_with_same_params(self):
        from proxy.app.shared.circuit_breaker import get_breaker

        cb_a = get_breaker("svc_a", failure_threshold=10, cooldown_seconds=10)
        cb_b = get_breaker("svc_b", failure_threshold=10, cooldown_seconds=10)
        assert cb_a is not cb_b
        assert cb_a.name != cb_b.name


# ── DLQ Integration Pattern ──────────────────────────────────────────────────


class TestCircuitBreakerDLQIntegration:
    """Test circuit breaker + DLQ integration patterns."""

    def test_circuit_breaker_failure_triggers_dlq_add(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("dlq_pattern", failure_threshold=5)

        failed_payloads = []

        def failing_call(payload):
            raise ConnectionError("service down")

        for i in range(3):
            with pytest.raises(ConnectionError):
                cb.call_sync(failing_call, {"query": f"q{i}"})
            failed_payloads.append({"query": f"q{i}", "error": "service down"})

        assert cb.failure_count == 3
        assert len(failed_payloads) == 3

    def test_circuit_breaker_open_can_trigger_dlq_direct_add(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

        cb = CircuitBreaker("dlq_open", failure_threshold=1)
        cb.failure()

        dlq_entries = []
        try:
            cb.call_sync(lambda: "should not run")
        except CircuitBreakerOpenError:
            dlq_entries.append({"action": "deferred", "reason": "circuit_open"})

        assert len(dlq_entries) == 1

    def test_circuit_breaker_recovery_enables_dlq_retry(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State

        cb = CircuitBreaker("dlq_recovery", failure_threshold=1, cooldown_seconds=0.01)
        cb.failure()
        time.sleep(0.02)

        recovered = []

        def retry_handler():
            recovered.append("processed")
            return "ok"

        cb.call_sync(retry_handler)
        assert len(recovered) == 1
        assert cb.state == State.CLOSED


# ── Metrics Registration Robustness ──────────────────────────────────────────


class TestMetricsRegistration:
    """Test that Prometheus metrics handle duplicate registration gracefully."""

    def test_metrics_reimport_does_not_raise(self):
        """Re-importing the module should not raise DuplicateMetricError."""
        import importlib

        import proxy.app.shared.circuit_breaker as cb_module

        importlib.reload(cb_module)

    def test_breaker_creation_does_not_raise_metric_error(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        for i in range(5):
            cb = CircuitBreaker(f"metric_test_{i}")
            assert cb.state.metric_value == 0

    def test_custom_failure_threshold_and_cooldown(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("custom_params", failure_threshold=7, cooldown_seconds=60.0, half_open_max=3)
        assert cb.failure_threshold == 7
        assert cb.cooldown_seconds == 60.0
        assert cb.half_open_max == 3
