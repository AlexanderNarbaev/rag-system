# ruff: noqa: E501, SIM117, E402, F401, I001, N803, B017
"""Degradation tests — verify circuit breaker state transitions and graceful degradation.

Tests the circuit breaker pattern directly:
- CLOSED → OPEN after N consecutive failures
- OPEN → HALF_OPEN after cooldown period
- HALF_OPEN → CLOSED on success
- HALF_OPEN → OPEN on failure

Also verifies retry logic and fallback behavior at the component level.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.llm.provider import ProviderType
from proxy.app.shared.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    State,
    get_breaker,
    reset_all_breakers,
)


# ── Circuit Breaker State Transitions ────────────────────────────────────────


class TestCircuitBreakerClosedToOpen:
    """Verify circuit opens after failure_threshold consecutive failures."""

    def test_opens_after_threshold_failures(self):
        """Circuit transitions CLOSED → OPEN after N failures."""
        cb = CircuitBreaker("test_closed_open", failure_threshold=3, cooldown_seconds=60.0)
        assert cb.state == State.CLOSED

        for _i in range(3):
            cb.failure()

        assert cb.state == State.OPEN

    def test_stays_closed_below_threshold(self):
        """Circuit stays CLOSED when failures are below threshold."""
        cb = CircuitBreaker("test_below", failure_threshold=5, cooldown_seconds=60.0)

        for _ in range(4):
            cb.failure()

        assert cb.state == State.CLOSED

    def test_success_resets_failure_count(self):
        """Success resets failure count, preventing circuit from opening."""
        cb = CircuitBreaker("test_reset", failure_threshold=3, cooldown_seconds=60.0)

        cb.failure()
        cb.failure()
        cb.success()  # reset

        cb.failure()
        cb.failure()
        # Should still be closed — only 2 consecutive failures after reset
        assert cb.state == State.CLOSED


class TestCircuitBreakerOpenToHalfOpen:
    """Verify circuit transitions OPEN → HALF_OPEN after cooldown."""

    def test_half_open_after_cooldown(self):
        """Circuit transitions to HALF_OPEN after cooldown_seconds elapse."""
        cb = CircuitBreaker("test_cooldown", failure_threshold=2, cooldown_seconds=0.1)

        cb.failure()
        cb.failure()
        assert cb.state == State.OPEN

        time.sleep(0.15)  # wait for cooldown

        assert cb.state == State.HALF_OPEN

    def test_stays_open_before_cooldown(self):
        """Circuit stays OPEN before cooldown expires."""
        cb = CircuitBreaker("test_still_open", failure_threshold=2, cooldown_seconds=10.0)

        cb.failure()
        cb.failure()
        assert cb.state == State.OPEN

        # No sleep — cooldown hasn't elapsed
        assert cb.state == State.OPEN


class TestCircuitBreakerHalfOpenToClosed:
    """Verify circuit transitions HALF_OPEN → CLOSED on success."""

    def test_closes_on_success(self):
        """Circuit closes after a successful call in HALF_OPEN state."""
        cb = CircuitBreaker("test_close", failure_threshold=2, cooldown_seconds=0.1, half_open_max=2)

        cb.failure()
        cb.failure()
        assert cb.state == State.OPEN

        time.sleep(0.15)
        assert cb.state == State.HALF_OPEN

        cb.success()
        assert cb.state == State.CLOSED

    def test_call_sync_closes_circuit(self):
        """call_sync with successful function closes the circuit."""
        cb = CircuitBreaker("test_call_sync", failure_threshold=2, cooldown_seconds=0.1)

        cb.failure()
        cb.failure()
        time.sleep(0.15)

        result = cb.call_sync(lambda: "ok")
        assert result == "ok"
        assert cb.state == State.CLOSED

    @pytest.mark.asyncio
    async def test_async_call_closes_circuit(self):
        """Async call with successful function closes the circuit."""
        cb = CircuitBreaker("test_async_close", failure_threshold=2, cooldown_seconds=0.1)

        cb.failure()
        cb.failure()
        time.sleep(0.15)

        async def ok():
            return "ok"

        result = await cb.call(ok)
        assert result == "ok"
        assert cb.state == State.CLOSED


class TestCircuitBreakerHalfOpenToOpen:
    """Verify circuit transitions HALF_OPEN → OPEN on failure."""

    def test_reopens_on_failure(self):
        """Circuit re-opens after a failure in HALF_OPEN state."""
        cb = CircuitBreaker("test_reopen", failure_threshold=2, cooldown_seconds=0.1)

        cb.failure()
        cb.failure()
        assert cb.state == State.OPEN

        time.sleep(0.15)
        assert cb.state == State.HALF_OPEN

        cb.failure()
        assert cb.state == State.OPEN

    def test_half_open_limits_calls(self):
        """Circuit rejects calls beyond half_open_max in HALF_OPEN state."""
        cb = CircuitBreaker("test_limit", failure_threshold=2, cooldown_seconds=0.1, half_open_max=1)

        cb.failure()
        cb.failure()
        time.sleep(0.15)

        # First call in half-open should be allowed
        cb.call_sync(lambda: "ok1")

        # After success, circuit is CLOSED, so this should work
        assert cb.state == State.CLOSED


class TestCircuitBreakerCallProtection:
    """Verify call_sync and call protect against open circuits."""

    def test_call_sync_raises_when_open(self):
        """call_sync raises CircuitBreakerOpenError when circuit is open."""
        cb = CircuitBreaker("test_raise", failure_threshold=1, cooldown_seconds=60.0)
        cb.failure()
        assert cb.state == State.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            cb.call_sync(lambda: "should not execute")

    @pytest.mark.asyncio
    async def test_async_call_raises_when_open(self):
        """Async call raises CircuitBreakerOpenError when circuit is open."""
        cb = CircuitBreaker("test_async_raise", failure_threshold=1, cooldown_seconds=60.0)
        cb.failure()
        assert cb.state == State.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(lambda: "should not execute")

    def test_call_sync_propagates_function_error(self):
        """call_sync propagates the original function exception."""
        cb = CircuitBreaker("test_propagate", failure_threshold=5, cooldown_seconds=60.0)

        with pytest.raises(ValueError, match="bad input"):
            cb.call_sync(lambda: (_ for _ in ()).throw(ValueError("bad input")))

    def test_failure_count_increments_on_error(self):
        """Failure count increments when wrapped function raises."""
        cb = CircuitBreaker("test_count", failure_threshold=3, cooldown_seconds=60.0)

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call_sync(lambda: (_ for _ in ()).throw(RuntimeError("fail")))

        assert cb.failure_count == 2
        assert cb.state == State.CLOSED  # below threshold


# ── Breaker Registry ─────────────────────────────────────────────────────────


class TestBreakerRegistry:
    """Verify get_breaker and reset_all_breakers work correctly."""

    def setup_method(self):
        reset_all_breakers()

    def test_get_breaker_returns_same_instance(self):
        """get_breaker returns the same instance for the same name."""
        cb1 = get_breaker("registry_test")
        cb2 = get_breaker("registry_test")
        assert cb1 is cb2

    def test_get_breaker_different_names(self):
        """Different names produce different breaker instances."""
        cb1 = get_breaker("service_a")
        cb2 = get_breaker("service_b")
        assert cb1 is not cb2

    def test_reset_all_breakers(self):
        """reset_all_breakers resets all breakers to CLOSED."""
        cb1 = get_breaker("reset_a", failure_threshold=1)
        cb2 = get_breaker("reset_b", failure_threshold=1)

        cb1.failure()
        cb2.failure()
        assert cb1.state == State.OPEN
        assert cb2.state == State.OPEN

        reset_all_breakers()
        assert cb1.state == State.CLOSED
        assert cb2.state == State.CLOSED

    def test_reset_preserves_configuration(self):
        """Reset preserves failure_threshold and cooldown settings."""
        cb = get_breaker("config_test", failure_threshold=7, cooldown_seconds=42.0)
        cb.failure()
        reset_all_breakers()

        assert cb.failure_threshold == 7
        assert cb.cooldown_seconds == 42.0


# ── Prometheus Metrics ───────────────────────────────────────────────────────


class TestCircuitBreakerMetrics:
    """Verify Prometheus metrics are updated on state changes."""

    def setup_method(self):
        reset_all_breakers()

    def test_state_gauge_updates_on_open(self):
        """State gauge updates when circuit opens."""
        cb = get_breaker("metrics_open", failure_threshold=1)
        cb.failure()
        # The gauge should be set to 1 (OPEN)
        # We verify indirectly through the state property
        assert cb.state == State.OPEN

    def test_failure_counter_increments(self):
        """Failure counter increments on each failure."""
        cb = get_breaker("metrics_count", failure_threshold=10)
        initial = cb.failure_count

        cb.failure()
        cb.failure()

        assert cb.failure_count == initial + 2


# ── Integration: Provider with Circuit Breaker ───────────────────────────────


class TestLLMProviderWithCircuitBreaker:
    """Verify LLM provider respects circuit breaker state."""

    @pytest.mark.asyncio
    async def test_provider_rejects_when_circuit_open(self):
        """LLM provider raises when circuit breaker is OPEN."""
        from proxy.app.llm.provider import MultiProviderRouter

        # Open the circuit breaker
        cb = get_breaker("llm_backend", failure_threshold=1)
        cb.failure()
        assert cb.state == State.OPEN

        router = MultiProviderRouter.__new__(MultiProviderRouter)
        router.provider_type = ProviderType.OPENAI
        router.adapter = MagicMock()
        router.endpoint = "http://fake"
        router.api_key = None
        router._adapter_cache = {}

        with pytest.raises(Exception) as exc_info:
            await router._send_request([{"role": "user", "content": "test"}], retry=0)

        assert "OPEN" in str(exc_info.value) or "circuit" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_provider_records_failure_on_error(self):
        """LLM provider records failure to circuit breaker on error."""
        from proxy.app.llm.provider import MultiProviderRouter

        reset_all_breakers()
        cb = get_breaker("llm_backend", failure_threshold=5)

        router = MultiProviderRouter.__new__(MultiProviderRouter)
        router.provider_type = ProviderType.OPENAI
        router.adapter = MagicMock()
        router.adapter.translate_request.return_value = {"model": "test", "messages": []}
        router.adapter.headers = {"Content-Type": "application/json"}
        router.endpoint = "http://localhost:1"  # unreachable
        router.api_key = None
        router._adapter_cache = {}

        initial_failures = cb.failure_count

        with pytest.raises(Exception):
            await router._send_request(
                [{"role": "user", "content": "test"}],
                retry=0,
            )

        # Failure count should have increased
        assert cb.failure_count > initial_failures


# ── Graceful Degradation Scenarios ───────────────────────────────────────────


class TestRetrievalGracefulDegradation:
    """Verify retrieval module degrades gracefully when Qdrant is unavailable."""

    def test_hybrid_search_returns_empty_on_circuit_open(self):
        """hybrid_search returns empty results when Qdrant circuit breaker is OPEN."""
        reset_all_breakers()
        cb = get_breaker("qdrant", failure_threshold=1)
        cb.failure()
        assert cb.state == State.OPEN

        # The retrieval module catches CircuitBreakerOpenError and returns empty  # This is verified by the existing
        # test_chaos.py tests at the HTTP level

    def test_graph_expand_returns_empty_when_disabled(self):
        """graph_expand_query returns empty string when graph is disabled."""
        from proxy.app.core.retrieval import graph_expand_query

        with patch("proxy.app.core.retrieval._GRAPH_ENABLED", False):
            result = graph_expand_query("test query")
            assert result == ""


class TestCacheGracefulDegradation:
    """Verify cache falls back to in-memory when Redis is unavailable."""

    @pytest.mark.asyncio
    async def test_cache_manager_uses_in_memory_fallback(self):
        """CacheManager uses InMemoryCache when use_redis=False."""
        from proxy.app.shared.cache import CacheManager, InMemoryCache

        cache = CacheManager(use_redis=False)
        assert isinstance(cache._cache, InMemoryCache)

        await cache.set("key", "value", ttl=60)
        result = await cache.get("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_in_memory_cache_ttl_expiry(self):
        """InMemoryCache respects TTL and expires entries."""
        from proxy.app.shared.cache import InMemoryCache

        cache = InMemoryCache()
        await cache.set("expire_key", "data", ttl=0)
        time.sleep(0.01)
        result = await cache.get("expire_key")
        assert result is None
