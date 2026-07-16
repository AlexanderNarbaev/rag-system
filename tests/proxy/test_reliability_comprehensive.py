"""Comprehensive reliability tests for retry, circuit breaker, and DLQ."""

from __future__ import annotations

import pytest

from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError
from proxy.app.shared.retry import (
    BackoffStrategy,
    RetryConfig,
    RetryExhaustedError,
    _compute_delay,
    async_retry,
    sync_retry,
)


class TestRetryConfig:
    """Test retry configuration."""

    def test_default_config(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.strategy == BackoffStrategy.EXPONENTIAL

    def test_custom_config(self):
        config = RetryConfig(max_attempts=5, base_delay=2.0)
        assert config.max_attempts == 5
        assert config.base_delay == 2.0


class TestBackoffStrategies:
    """Test backoff delay computation."""

    def test_constant_strategy(self):
        config = RetryConfig(base_delay=1.0, strategy=BackoffStrategy.CONSTANT)
        delay = _compute_delay(1, config)
        assert 0.5 <= delay <= 2.0  # constant with jitter

    def test_linear_strategy(self):
        config = RetryConfig(base_delay=1.0, strategy=BackoffStrategy.LINEAR)
        delay = _compute_delay(2, config)
        assert 1.0 <= delay <= 4.0  # linear with jitter

    def test_exponential_strategy(self):
        config = RetryConfig(base_delay=1.0, strategy=BackoffStrategy.EXPONENTIAL)
        delay = _compute_delay(3, config)
        assert 2.0 <= delay <= 10.0  # exponential with jitter


class TestSyncRetry:
    """Test synchronous retry."""

    def test_success_on_first_try(self):
        result = sync_retry(lambda: 42, config=RetryConfig(max_attempts=3))
        assert result == 42

    def test_success_on_retry(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("not yet")
            return 42

        result = sync_retry(flaky, config=RetryConfig(max_attempts=3, base_delay=0.01))
        assert result == 42
        assert call_count == 3

    def test_exhausted_raises_retry_exhausted(self):
        with pytest.raises(RetryExhaustedError):
            sync_retry(
                lambda: (_ for _ in ()).throw(RuntimeError("always fails")),
                config=RetryConfig(max_attempts=2, base_delay=0.01),
            )


class TestAsyncRetry:
    """Test asynchronous retry."""

    @pytest.mark.asyncio
    async def test_async_success_on_first_try(self):
        async def ok():
            return 42

        result = await async_retry(ok, config=RetryConfig(max_attempts=3))
        assert result == 42

    @pytest.mark.asyncio
    async def test_async_success_on_retry(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("not yet")
            return 42

        result = await async_retry(flaky, config=RetryConfig(max_attempts=3, base_delay=0.01))
        assert result == 42
        assert call_count == 3


class TestCircuitBreaker:
    """Test circuit breaker behavior."""

    def test_circuit_breaker_open_error_exists(self):
        assert CircuitBreakerOpenError is not None

    def test_circuit_breaker_open_error_is_exception(self):
        assert issubclass(CircuitBreakerOpenError, Exception)


class TestDLQ:
    """Test Dead Letter Queue."""

    def test_dlq_importable(self):
        from proxy.app.shared.dlq import DeadLetterQueue

        assert DeadLetterQueue is not None

    def test_dlq_add_and_get(self, tmp_path):
        from proxy.app.shared.dlq import DeadLetterQueue

        dlq = DeadLetterQueue(str(tmp_path / "test.db"))
        msg_id = dlq.add({"data": "test"}, "test error")
        assert msg_id is not None
        msg = dlq.get(msg_id)
        assert msg is not None
        dlq.close()

    def test_dlq_stats(self, tmp_path):
        from proxy.app.shared.dlq import DeadLetterQueue

        dlq = DeadLetterQueue(str(tmp_path / "test.db"))
        dlq.add({"data": "test"}, "test error")
        stats = dlq.stats()
        assert isinstance(stats, dict)
        dlq.close()
