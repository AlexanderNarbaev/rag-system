"""Extended tests for proxy/app/shared/retry.py — remaining code paths."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError
from proxy.app.shared.retry import (
    BackoffStrategy,
    RetryConfig,
    RetryExhaustedError,
    _compute_delay,
    _is_retryable,
    _record_circuit_breaker,
    async_retry,
    sync_retry,
)


class TestComputeDelay:
    def test_constant_strategy(self):
        config = RetryConfig(strategy=BackoffStrategy.CONSTANT, base_delay=2.0, jitter=False)
        assert _compute_delay(0, config) == 2.0
        assert _compute_delay(1, config) == 2.0
        assert _compute_delay(5, config) == 2.0

    def test_linear_strategy(self):
        config = RetryConfig(strategy=BackoffStrategy.LINEAR, base_delay=1.0, jitter=False)
        assert _compute_delay(0, config) == 1.0
        assert _compute_delay(1, config) == 2.0
        assert _compute_delay(2, config) == 3.0

    def test_exponential_strategy(self):
        config = RetryConfig(strategy=BackoffStrategy.EXPONENTIAL, base_delay=1.0, jitter=False)
        assert _compute_delay(0, config) == 1.0
        assert _compute_delay(1, config) == 2.0
        assert _compute_delay(3, config) == 8.0

    def test_max_delay_cap(self):
        config = RetryConfig(strategy=BackoffStrategy.EXPONENTIAL, base_delay=10.0, max_delay=5.0, jitter=False)
        assert _compute_delay(0, config) == 5.0
        assert _compute_delay(10, config) == 5.0

    def test_jitter_adds_variability(self):
        config = RetryConfig(strategy=BackoffStrategy.CONSTANT, base_delay=10.0, jitter=True)
        delays = {_compute_delay(0, config) for _ in range(100)}
        assert len(delays) > 1


class TestIsRetryable:
    def test_no_filter_always_retryable(self):
        config = RetryConfig(retryable_exceptions=())
        assert _is_retryable(ValueError("test"), config) is True
        assert _is_retryable(ConnectionError("test"), config) is True

    def test_filter_matches(self):
        config = RetryConfig(retryable_exceptions=(ConnectionError, TimeoutError))
        assert _is_retryable(ConnectionError("test"), config) is True
        assert _is_retryable(TimeoutError("test"), config) is True

    def test_filter_no_match(self):
        config = RetryConfig(retryable_exceptions=(ConnectionError,))
        assert _is_retryable(ValueError("test"), config) is False


class TestRecordCircuitBreaker:
    def test_record_success(self):
        mock_breaker = MagicMock()
        with patch(
            "proxy.app.shared.circuit_breaker.get_breaker",
            return_value=mock_breaker,
        ):
            _record_circuit_breaker("test-cb", success=True)
            mock_breaker.success.assert_called_once()

    def test_record_failure(self):
        mock_breaker = MagicMock()
        with patch(
            "proxy.app.shared.circuit_breaker.get_breaker",
            return_value=mock_breaker,
        ):
            _record_circuit_breaker("test-cb", success=False)
            mock_breaker.failure.assert_called_once()

    def test_record_import_error_swallowed(self):
        with patch(
            "proxy.app.shared.circuit_breaker.get_breaker",
            side_effect=ImportError,
        ):
            _record_circuit_breaker("test-cb", success=True)  # should not raise


class TestSyncRetryCircuitBreaker:
    def test_circuit_breaker_open_raises(self):
        mock_breaker = MagicMock()
        mock_breaker.state.name = "OPEN"

        config = RetryConfig(max_attempts=1, circuit_breaker_name="test-cb")
        with (
            patch(
                "proxy.app.shared.circuit_breaker.get_breaker",
                return_value=mock_breaker,
            ),
            pytest.raises(CircuitBreakerOpenError),
        ):
            sync_retry(lambda: 42, config=config)

    def test_circuit_breaker_import_error_skipped(self):
        config = RetryConfig(max_attempts=1, circuit_breaker_name="test-cb")
        with patch(
            "proxy.app.shared.circuit_breaker.get_breaker",
            side_effect=ImportError("no breaker module"),
        ):
            result = sync_retry(lambda: 42, config=config)
            assert result == 42

    def test_circuit_breaker_closed_success(self):
        mock_breaker = MagicMock()
        mock_breaker.state.name = "CLOSED"

        config = RetryConfig(max_attempts=1, circuit_breaker_name="test-cb")
        with patch(
            "proxy.app.shared.circuit_breaker.get_breaker",
            return_value=mock_breaker,
        ):
            result = sync_retry(lambda: 42, config=config)
            assert result == 42

    def test_sync_retry_failure_records_circuit_breaker(self):
        mock_breaker = MagicMock()
        mock_breaker.state.name = "CLOSED"

        config = RetryConfig(max_attempts=1, base_delay=0.001, circuit_breaker_name="test-cb")
        with (
            patch(
                "proxy.app.shared.circuit_breaker.get_breaker",
                return_value=mock_breaker,
            ),
            pytest.raises(RetryExhaustedError),
        ):
            sync_retry(lambda: (_ for _ in ()).throw(RuntimeError("fail")), config=config)


class TestAsyncRetryCircuitBreaker:
    @pytest.mark.asyncio
    async def test_async_circuit_breaker_open_raises(self):
        mock_breaker = MagicMock()
        mock_breaker.state.name = "OPEN"

        async def ok():
            return 42

        config = RetryConfig(max_attempts=1, circuit_breaker_name="async-cb")
        with (
            patch(
                "proxy.app.shared.circuit_breaker.get_breaker",
                return_value=mock_breaker,
            ),
            pytest.raises(CircuitBreakerOpenError),
        ):
            await async_retry(ok, config=config)

    @pytest.mark.asyncio
    async def test_async_circuit_breaker_import_error_skipped(self):
        async def ok():
            return 42

        config = RetryConfig(max_attempts=1, circuit_breaker_name="async-cb")
        with patch(
            "proxy.app.shared.circuit_breaker.get_breaker",
            side_effect=ImportError("no cb module"),
        ):
            result = await async_retry(ok, config=config)
            assert result == 42

    @pytest.mark.asyncio
    async def test_async_circuit_breaker_closed_success(self):
        mock_breaker = MagicMock()
        mock_breaker.state.name = "CLOSED"

        async def ok():
            return 42

        config = RetryConfig(max_attempts=1, circuit_breaker_name="async-cb")
        with patch(
            "proxy.app.shared.circuit_breaker.get_breaker",
            return_value=mock_breaker,
        ):
            result = await async_retry(ok, config=config)
            assert result == 42

    @pytest.mark.asyncio
    async def test_async_retry_failure_records_circuit_breaker(self):
        mock_breaker = MagicMock()
        mock_breaker.state.name = "CLOSED"

        async def always_fails():
            raise RuntimeError("permanent failure")

        config = RetryConfig(max_attempts=1, base_delay=0.001, circuit_breaker_name="async-cb")
        with (
            patch(
                "proxy.app.shared.circuit_breaker.get_breaker",
                return_value=mock_breaker,
            ),
            pytest.raises(RetryExhaustedError),
        ):
            await async_retry(always_fails, config=config)


class TestSyncRetryDefaultConfig:
    def test_default_config_used_when_none(self):
        result = sync_retry(lambda: "default", config=None)
        assert result == "default"


class TestAsyncRetryCancellationRecovery:
    @pytest.mark.asyncio
    async def test_cancellation_during_sleep(self):
        config = RetryConfig(max_attempts=5, base_delay=1.0)

        async def always_fail():
            raise ConnectionError("fail")

        task = asyncio.ensure_future(async_retry(always_fail, config=config))
        await asyncio.sleep(0.01)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
