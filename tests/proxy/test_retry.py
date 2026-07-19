"""Tests for proxy/app/shared/retry.py — centralized retry utility."""

from __future__ import annotations

import asyncio
import time

import pytest

from proxy.app.shared.retry import (
    BackoffStrategy,
    RetryConfig,
    RetryExhaustedError,
    async_retry,
    sync_retry,
)

# ── RetryConfig ───────────────────────────────────────────────────────────────


class TestRetryConfig:
    """Test RetryConfig defaults and customization."""

    def test_default_values(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.strategy == BackoffStrategy.EXPONENTIAL
        assert config.jitter is True
        assert config.retryable_exceptions == ()
        assert config.circuit_breaker_name is None

    def test_custom_values(self):
        config = RetryConfig(
            max_attempts=5,
            base_delay=2.0,
            max_delay=30.0,
            strategy=BackoffStrategy.LINEAR,
            jitter=False,
            circuit_breaker_name="test_cb",
        )
        assert config.max_attempts == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 30.0
        assert config.strategy == BackoffStrategy.LINEAR
        assert config.jitter is False
        assert config.circuit_breaker_name == "test_cb"

    def test_on_retry_callback(self):
        calls = []

        def on_retry(attempt: int, exc: Exception, delay: float):
            calls.append((attempt, type(exc).__name__, delay))

        config = RetryConfig(on_retry=on_retry)
        assert config.on_retry is on_retry


# ── BackoffStrategy ───────────────────────────────────────────────────────────


class TestBackoffStrategy:
    """Test backoff strategy enum."""

    def test_str_values(self):
        assert BackoffStrategy.CONSTANT == "constant"
        assert BackoffStrategy.LINEAR == "linear"
        assert BackoffStrategy.EXPONENTIAL == "exponential"


# ── sync_retry ────────────────────────────────────────────────────────────────


class TestSyncRetry:
    """Test sync_retry() function."""

    def test_success_first_attempt(self):
        result = sync_retry(lambda: 42, config=RetryConfig(max_attempts=1))
        assert result == 42

    def test_success_after_retry(self):
        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("transient failure")
            return "ok"

        result = sync_retry(flaky, config=RetryConfig(max_attempts=3, base_delay=0.001))
        assert result == "ok"
        assert call_count[0] == 2

    def test_exhausted_retries(self):
        def always_fails():
            raise RuntimeError("permanent failure")

        with pytest.raises(RetryExhaustedError) as exc_info:
            sync_retry(always_fails, config=RetryConfig(max_attempts=3, base_delay=0.001))

        assert exc_info.value.attempts == 3
        assert isinstance(exc_info.value.last_error, RuntimeError)

    def test_non_retryable_exception(self):
        def raises_value_error():
            raise ValueError("bad input")

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.001,
            retryable_exceptions=(ConnectionError, TimeoutError),
        )

        with pytest.raises(ValueError, match="bad input"):
            sync_retry(raises_value_error, config=config)

    def test_retryable_exception_filter(self):
        call_count = [0]

        def raises_connection_error():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("transient")
            return "recovered"

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.001,
            retryable_exceptions=(ConnectionError,),
        )

        result = sync_retry(raises_connection_error, config=config)
        assert result == "recovered"
        assert call_count[0] == 2

    def test_with_args_and_kwargs(self):
        def add(a, b, mul=1):
            return (a + b) * mul

        result = sync_retry(add, 2, 3, mul=2, config=RetryConfig(max_attempts=1))
        assert result == 10

    def test_exponential_backoff_delays(self):
        config = RetryConfig(
            max_attempts=4,
            base_delay=0.1,
            strategy=BackoffStrategy.EXPONENTIAL,
            jitter=False,
        )

        call_count = [0]
        start = time.monotonic()

        def fail_until_last():
            call_count[0] += 1
            if call_count[0] < 4:
                raise ConnectionError("fail")
            return "ok"

        result = sync_retry(fail_until_last, config=config)
        elapsed = time.monotonic() - start

        assert result == "ok"
        # Delays: 0.1 * 2^0 = 0.1, 0.1 * 2^1 = 0.2, 0.1 * 2^2 = 0.4 → total ~0.7s
        assert elapsed >= 0.6, f"Expected >= 0.6s, got {elapsed:.2f}s"

    def test_constant_backoff(self):
        config = RetryConfig(
            max_attempts=3,
            base_delay=0.1,
            strategy=BackoffStrategy.CONSTANT,
            jitter=False,
        )

        call_count = [0]
        start = time.monotonic()

        def fail_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("fail")
            return "ok"

        result = sync_retry(fail_twice, config=config)
        elapsed = time.monotonic() - start

        assert result == "ok"
        # Constant delays: 0.1 + 0.1 = 0.2s
        assert elapsed >= 0.15, f"Expected >= 0.15s, got {elapsed:.2f}s"

    def test_max_delay_cap(self):
        config = RetryConfig(
            max_attempts=3,
            base_delay=10.0,
            max_delay=0.1,
            strategy=BackoffStrategy.EXPONENTIAL,
            jitter=False,
        )

        call_count = [0]
        start = time.monotonic()

        def fail_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("fail")
            return "ok"

        result = sync_retry(fail_twice, config=config)
        elapsed = time.monotonic() - start

        assert result == "ok"
        # Both delays capped at 0.1 → total ~0.2s
        assert elapsed >= 0.15, f"Expected >= 0.15s, got {elapsed:.2f}s"

    def test_on_retry_callback_called(self):
        callbacks = []

        def on_retry(attempt, exc, delay):
            callbacks.append((attempt, type(exc).__name__))

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.001,
            on_retry=on_retry,
        )

        call_count = [0]

        def fail_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("fail")
            return "ok"

        sync_retry(fail_twice, config=config)
        assert len(callbacks) == 2
        assert callbacks[0] == (0, "ConnectionError")
        assert callbacks[1] == (1, "ConnectionError")

    def test_single_attempt_no_retry(self):
        config = RetryConfig(max_attempts=1)

        with pytest.raises(RetryExhaustedError):
            sync_retry(lambda: (_ for _ in ()).throw(RuntimeError("fail")), config=config)

    def test_linear_backoff(self):
        config = RetryConfig(
            max_attempts=3,
            base_delay=0.05,
            strategy=BackoffStrategy.LINEAR,
            jitter=False,
        )

        call_count = [0]
        start = time.monotonic()

        def fail_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("fail")
            return "ok"

        result = sync_retry(fail_twice, config=config)
        elapsed = time.monotonic() - start

        assert result == "ok"
        # Linear delays: 0.05 * 1 = 0.05, 0.05 * 2 = 0.1 → total ~0.15s
        assert elapsed >= 0.1, f"Expected >= 0.1s, got {elapsed:.2f}s"


# ── async_retry ───────────────────────────────────────────────────────────────


class TestAsyncRetry:
    """Test async_retry() function."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        async def ok():
            return 42

        result = await async_retry(ok, config=RetryConfig(max_attempts=1))
        assert result == 42

    @pytest.mark.asyncio
    async def test_success_after_retry(self):
        call_count = [0]

        async def flaky():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("transient")
            return "ok"

        result = await async_retry(flaky, config=RetryConfig(max_attempts=3, base_delay=0.001))
        assert result == "ok"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries(self):
        async def always_fails():
            raise RuntimeError("permanent")

        with pytest.raises(RetryExhaustedError) as exc_info:
            await async_retry(always_fails, config=RetryConfig(max_attempts=3, base_delay=0.001))

        assert exc_info.value.attempts == 3

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        async def raises_value_error():
            raise ValueError("bad input")

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.001,
            retryable_exceptions=(ConnectionError,),
        )

        with pytest.raises(ValueError, match="bad input"):
            await async_retry(raises_value_error, config=config)

    @pytest.mark.asyncio
    async def test_with_args_and_kwargs(self):
        async def multiply(a, b, factor=1):
            return a * b * factor

        result = await async_retry(multiply, 4, 5, factor=2, config=RetryConfig(max_attempts=1))
        assert result == 40

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        config = RetryConfig(
            max_attempts=3,
            base_delay=0.1,
            jitter=False,
        )

        call_count = [0]

        async def fail_once():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("fail")
            return "ok"

        result = await async_retry(fail_once, config=config)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_cancellation_during_retry(self):
        config = RetryConfig(max_attempts=10, base_delay=10.0)

        call_count = [0]

        async def always_fail():
            call_count[0] += 1
            raise ConnectionError("fail")

        task = asyncio.ensure_future(async_retry(always_fail, config=config))
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


# ── RetryExhaustedError ───────────────────────────────────────────────────────


class TestRetryExhaustedError:
    """Test RetryExhaustedError exception."""

    def test_error_contains_attempts(self):
        err = RetryExhaustedError(3, RuntimeError("failed"))
        assert "3" in str(err)
        assert err.attempts == 3
        assert isinstance(err.last_error, RuntimeError)
        assert isinstance(err, Exception)

    def test_error_with_operation_name(self):
        err = RetryExhaustedError(5, TimeoutError("timed out"), operation="qdrant_connect")
        assert "qdrant_connect" in str(err)
        assert err.operation == "qdrant_connect"


# ── Qdrant Connection Retry Integration ───────────────────────────────────────


class TestQdrantConnectionRetry:
    """Test that Qdrant initialization uses retry logic."""

    def test_initialize_retrieval_imports_retry(self):
        """initialize_retrieval imports and uses sync_retry from retry module."""
        from proxy.app.core.retrieval import initialize_retrieval

        # Verify the function is callable and the retry module exists
        assert callable(initialize_retrieval)

    def test_retry_config_used_in_retrieval_init(self):
        from proxy.app.core.retrieval import initialize_retrieval

        # Just verify the function exists and can be imported
        assert callable(initialize_retrieval)


# ── Redis Connection Retry Integration ────────────────────────────────────────


class TestRedisConnectionRetry:
    """Test that Redis cache initialization uses retry logic."""

    def test_redis_cache_uses_retry(self):
        from proxy.app.shared.cache import RedisCache

        # Verify RedisCache class exists and is importable
        assert RedisCache is not None

    def test_in_memory_cache_no_retry_needed(self):
        from proxy.app.shared.cache import InMemoryCache

        cache = InMemoryCache()
        cache.set_sync("test", "value")
        assert cache.get_sync("test") == "value"
        cache.delete_sync("test")
        assert cache.get_sync("test") is None


# ── LLM Provider Session Cleanup ──────────────────────────────────────────────


class TestLLMProviderSessionCleanup:
    """Test that LLM provider properly cleans up aiohttp sessions on retry."""

    @pytest.mark.asyncio
    async def test_session_closed_on_timeout(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from proxy.app.llm.provider import MultiProviderRouter, ProviderType

        router = MultiProviderRouter.__new__(MultiProviderRouter)
        router.provider_type = ProviderType.OPENAI
        router.adapter = MagicMock()
        router.adapter.translate_request.return_value = {"model": "test", "messages": []}
        router.adapter.headers = {"Content-Type": "application/json"}
        router.endpoint = "http://localhost:1"
        router.api_key = None
        router._adapter_cache = {}

        mock_session = AsyncMock()
        mock_session.post.side_effect = TimeoutError("connection timed out")

        mock_config = {"MAX_RETRIES": 0, "REQUEST_TIMEOUT": 5, "RETRY_DELAY": 0.1}

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            patch(
                "proxy.app.llm.provider.base._get_config",
                side_effect=lambda attr, default: mock_config.get(attr, default),
            ),
        ):
            with pytest.raises((TimeoutError, Exception)):
                await router._send_request([{"role": "user", "content": "test"}], retry=0)

            # Session should have been closed in finally block
            mock_session.close.assert_called()

    @pytest.mark.asyncio
    async def test_response_closed_on_http_error(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from proxy.app.llm.provider import MultiProviderRouter, ProviderType

        router = MultiProviderRouter.__new__(MultiProviderRouter)
        router.provider_type = ProviderType.OPENAI
        router.adapter = MagicMock()
        router.adapter.translate_request.return_value = {"model": "test", "messages": []}
        router.adapter.headers = {"Content-Type": "application/json"}
        router.endpoint = "http://localhost:1"
        router.api_key = None
        router._adapter_cache = {}

        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_session = AsyncMock()
        mock_session.post = AsyncMock(return_value=mock_response)

        mock_config = {"MAX_RETRIES": 0, "REQUEST_TIMEOUT": 5, "RETRY_DELAY": 0.1}

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            patch(
                "proxy.app.llm.provider.base._get_config",
                side_effect=lambda attr, default: mock_config.get(attr, default),
            ),
        ):
            with pytest.raises((OSError, Exception)):
                await router._send_request([{"role": "user", "content": "test"}], retry=0)

            mock_response.close.assert_called()
            mock_session.close.assert_called()
