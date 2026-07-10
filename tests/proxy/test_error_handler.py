"""Tests for proxy/app/error_handler.py - circuit breaker, retry, fallback."""

import asyncio
import time

import pytest

from proxy.app.shared.error_handler import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    GracefulDegradation,
    get_circuit_breaker,
    reset_all_circuit_breakers,
    with_circuit_breaker,
    with_fallback,
    with_retry,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker state machine."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_transitions_to_half_open_after_timeout(self, monkeypatch):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        cb._transition_if_needed()
        assert cb.state == CircuitState.HALF_OPEN

    def test_transitions_back_to_closed_after_half_open_success(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01, half_open_max=2)
        cb.record_failure()
        time.sleep(0.02)
        cb._transition_if_needed()
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_goes_back_to_open_on_half_open_failure(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01, half_open_max=3)
        cb.record_failure()
        time.sleep(0.02)
        cb._transition_if_needed()
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_resets_failure_count_on_closed_success(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb._failure_count == 2
        cb.record_success()
        assert cb._failure_count == 0

    def test_allow_request_returns_false_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.allow_request() is False


class TestGracefulDegradation:
    """Tests for GracefulDegradation fallback chains."""

    def test_matrix_has_all_services(self):
        expected_services = {"retrieval", "rerank", "llm", "graph", "cache"}
        assert set(GracefulDegradation.DEGRADATION_MATRIX.keys()) == expected_services

    def test_get_fallback_chain_returns_correct_order(self):
        chain = GracefulDegradation.get_fallback_chain("retrieval")
        assert chain == ["hybrid_search", "dense_only", "keyword_only", "no_context"]

    def test_get_fallback_chain_unknown_service(self):
        chain = GracefulDegradation.get_fallback_chain("nonexistent")
        assert chain == ["noop"]

    def test_get_degradation_level_first_strategy(self):
        level = GracefulDegradation.get_degradation_level("rerank", "cross_encoder")
        assert level == 0

    def test_get_degradation_level_last_strategy(self):
        level = GracefulDegradation.get_degradation_level("cache", "no_cache")
        assert level == 2

    def test_get_degradation_level_unknown_strategy(self):
        level = GracefulDegradation.get_degradation_level("llm", "unknown_strategy")
        assert level == 3


class TestWithRetry:
    """Tests for with_retry decorator."""

    def test_retries_async_and_succeeds(self):
        call_count = 0

        @with_retry(max_retries=3, backoff_factor=0.01)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return "success"

        result = asyncio.run(flaky_func())
        assert result == "success"
        assert call_count == 3

    def test_retries_exhausted_async(self):
        call_count = 0

        @with_retry(max_retries=2, backoff_factor=0.01)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("persistent error")

        with pytest.raises(RuntimeError, match="persistent error"):
            asyncio.run(always_fails())
        assert call_count == 3

    def test_retries_sync_and_succeeds(self):
        call_count = 0

        @with_retry(max_retries=2, backoff_factor=0.01)
        def flaky_sync():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("transient")
            return "ok"

        result = flaky_sync()
        assert result == "ok"
        assert call_count == 2

    def test_retries_exhausted_sync(self):
        call_count = 0

        @with_retry(max_retries=1, backoff_factor=0.01)
        def always_fails_sync():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("error")

        with pytest.raises(RuntimeError, match="error"):
            always_fails_sync()
        assert call_count == 2

    def test_only_retries_specified_exceptions(self):
        call_count = 0

        @with_retry(max_retries=3, backoff_factor=0.01, exceptions=(ValueError,))
        async def raises_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("not a ValueError")

        with pytest.raises(TypeError, match="not a ValueError"):
            asyncio.run(raises_type_error())
        assert call_count == 1


class TestWithFallback:
    """Tests for with_fallback decorator."""

    def test_calls_fallback_on_failure_async(self):
        async def primary():
            raise RuntimeError("primary failed")

        async def fallback():
            return "fallback result"

        wrapped = with_fallback(fallback)(primary)
        result = asyncio.run(wrapped())
        assert result == "fallback result"

    def test_calls_fallback_on_failure_sync(self):
        def primary():
            raise RuntimeError("primary failed")

        def fallback():
            return "sync fallback"

        wrapped = with_fallback(fallback)(primary)
        result = wrapped()
        assert result == "sync fallback"

    def test_does_not_call_fallback_on_success_async(self):
        async def primary():
            return "primary result"

        async def fallback():
            return "should not be called"

        wrapped = with_fallback(fallback)(primary)
        result = asyncio.run(wrapped())
        assert result == "primary result"

    def test_passes_arguments_to_fallback_async(self):
        async def primary(x):
            raise RuntimeError("fail")

        async def fallback(x):
            return f"fallback: {x}"

        wrapped = with_fallback(fallback)(primary)
        result = asyncio.run(wrapped("test_arg"))
        assert result == "fallback: test_arg"


class TestCircuitBreakerDecorator:
    """Tests for with_circuit_breaker decorator."""

    def setup_method(self):
        reset_all_circuit_breakers()

    def teardown_method(self):
        reset_all_circuit_breakers()

    def test_allows_when_closed(self):
        @with_circuit_breaker("test_service")
        async def service():
            return "ok"

        result = asyncio.run(service())
        assert result == "ok"

    def test_blocks_when_circuit_open(self):
        cb = get_circuit_breaker("test_service")
        for _ in range(cb.failure_threshold):
            cb.record_failure()

        @with_circuit_breaker("test_service")
        async def service():
            return "ok"

        with pytest.raises(CircuitBreakerError, match="OPEN"):
            asyncio.run(service())

    def test_records_failure_on_exception(self):
        reset_all_circuit_breakers()

        @with_circuit_breaker("test_service")
        async def failing_service():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(failing_service())

        cb = get_circuit_breaker("test_service")
        assert cb._failure_count == 1

    def test_sync_decorator_works(self):
        reset_all_circuit_breakers()

        @with_circuit_breaker("sync_service")
        def sync_func():
            return "sync ok"

        assert sync_func() == "sync ok"
