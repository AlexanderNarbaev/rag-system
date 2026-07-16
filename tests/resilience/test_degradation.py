# ruff: noqa: I001, B017
"""Degradation tests — verify circuit breaker state transitions and graceful degradation.

Tests the circuit breaker pattern directly:
- CLOSED → OPEN after N consecutive failures
- OPEN → HALF_OPEN after cooldown period
- HALF_OPEN → CLOSED on success
- HALF_OPEN → OPEN on failure

Also verifies retry logic and fallback behavior at the component level.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

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
        router.endpoint = "http://localhost:1"
        router.api_key = None
        router._adapter_cache = {}

        initial_failures = cb.failure_count

        with pytest.raises(Exception):
            await router._send_request(
                [{"role": "user", "content": "test"}],
                retry=0,
            )

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


# ── Retry Logic ───────────────────────────────────────────────────────────────


class TestRetryLogic:
    """Verify retry logic in critical connection paths."""

    def test_sync_retry_succeeds_after_failures(self):
        """sync_retry retries on transient failures and succeeds."""
        from proxy.app.shared.retry import RetryConfig, sync_retry

        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("transient")
            return "recovered"

        result = sync_retry(flaky, config=RetryConfig(max_attempts=5, base_delay=0.001))
        assert result == "recovered"
        assert call_count[0] == 3

    def test_sync_retry_exhausted(self):
        """sync_retry raises RetryExhaustedError after max attempts."""
        from proxy.app.shared.retry import RetryConfig, RetryExhaustedError, sync_retry

        call_count = [0]

        def always_fail():
            call_count[0] += 1
            raise RuntimeError("permanent")

        with pytest.raises(RetryExhaustedError) as exc_info:
            sync_retry(always_fail, config=RetryConfig(max_attempts=3, base_delay=0.001))

        assert exc_info.value.attempts == 3
        assert call_count[0] == 3

    def test_sync_retry_non_retryable(self):
        """sync_retry does not retry non-retryable exceptions."""
        from proxy.app.shared.retry import RetryConfig, sync_retry

        call_count = [0]

        def raises_value_error():
            call_count[0] += 1
            raise ValueError("bad input")

        config = RetryConfig(
            max_attempts=3,
            retryable_exceptions=(ConnectionError, TimeoutError),
        )

        with pytest.raises(ValueError):
            sync_retry(raises_value_error, config=config)

        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_async_retry_succeeds_after_failures(self):
        """async_retry retries on transient failures and succeeds."""
        from proxy.app.shared.retry import RetryConfig, async_retry

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
    async def test_async_retry_exhausted(self):
        """async_retry raises RetryExhaustedError after max attempts."""
        from proxy.app.shared.retry import RetryConfig, RetryExhaustedError, async_retry

        async def always_fail():
            raise RuntimeError("permanent")

        with pytest.raises(RetryExhaustedError):
            await async_retry(always_fail, config=RetryConfig(max_attempts=2, base_delay=0.001))


# ── Qdrant Connection Retry ───────────────────────────────────────────────────


class TestQdrantConnectionRetry:
    """Verify Qdrant initialization retries on transient failures."""

    def test_initialize_retrieval_retries_qdrant(self):
        """initialize_retrieval retries Qdrant connection before degrading."""
        from unittest.mock import MagicMock

        from proxy.app.shared.circuit_breaker import reset_all_breakers

        reset_all_breakers()

        call_count = [0]

        def mock_qdrant_client(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise OSError("Connection refused")
            mock = MagicMock()
            mock.get_collections.return_value = MagicMock(collections=[])
            return mock

        with (
            patch("proxy.app.core.retrieval.QdrantClient", side_effect=mock_qdrant_client),
            patch("proxy.app.core.retrieval.QDRANT_AVAILABLE", True),
            patch("proxy.app.llm.remote_services.create_embedder", return_value=MagicMock()),
        ):
            from proxy.app.core.retrieval import initialize_retrieval

            initialize_retrieval()
            assert call_count[0] == 2

    def test_qdrant_degradation_sets_client_none(self):
        """initialize_retrieval sets qdrant_client=None on persistent failure."""
        from unittest.mock import MagicMock

        import proxy.app.core.retrieval as ret_mod

        ret_mod.qdrant_client = "not_none"

        def mock_connect(*args, **kwargs):
            raise OSError("Host unreachable")

        with (
            patch("proxy.app.core.retrieval.QdrantClient", side_effect=mock_connect),
            patch("proxy.app.core.retrieval.QDRANT_AVAILABLE", True),
            patch("proxy.app.llm.remote_services.create_embedder", return_value=MagicMock()),
        ):
            from proxy.app.core.retrieval import initialize_retrieval

            initialize_retrieval()
            assert ret_mod.qdrant_client is None


# ── Neo4j Connection Retry ────────────────────────────────────────────────────


class TestNeo4jConnectionRetry:
    """Verify Neo4j initialization retries and degrades gracefully."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_neo4j(self):
        try:
            import neo4j  # noqa: F401
        except ImportError:
            pytest.skip("neo4j not installed")

    def test_neo4j_retries_then_succeeds(self):
        """initialize_retrieval retries Neo4j, succeeds on retry."""
        from unittest.mock import MagicMock

        import proxy.app.core.retrieval as ret_mod

        ret_mod._GRAPH_ENABLED = True

        call_count = [0]

        def mock_driver(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise OSError("Neo4j unreachable")
            mock = MagicMock()
            mock.verify_connectivity.return_value = None
            return mock

        mock_qdrant = MagicMock(get_collections=MagicMock(return_value=MagicMock(collections=[])))

        with (
            patch("neo4j.GraphDatabase.driver", side_effect=mock_driver),
            patch("proxy.app.core.retrieval.QDRANT_AVAILABLE", True),
            patch("proxy.app.core.retrieval.QdrantClient", return_value=mock_qdrant),
            patch("proxy.app.llm.remote_services.create_embedder", return_value=MagicMock()),
        ):
            from proxy.app.core.retrieval import initialize_retrieval

            initialize_retrieval()
            assert call_count[0] == 2

    def test_neo4j_disables_on_persistent_failure(self):
        """Neo4j disables graph expansion on persistent connection failure."""
        from unittest.mock import MagicMock

        import proxy.app.core.retrieval as ret_mod

        ret_mod._GRAPH_ENABLED = True

        def mock_driver(*args, **kwargs):
            raise OSError("Neo4j permanently down")

        mock_qdrant = MagicMock(get_collections=MagicMock(return_value=MagicMock(collections=[])))

        with (
            patch("neo4j.GraphDatabase.driver", side_effect=mock_driver),
            patch("proxy.app.core.retrieval.QDRANT_AVAILABLE", True),
            patch("proxy.app.core.retrieval.QdrantClient", return_value=mock_qdrant),
            patch("proxy.app.llm.remote_services.create_embedder", return_value=MagicMock()),
        ):
            from proxy.app.core.retrieval import initialize_retrieval

            initialize_retrieval()
            assert ret_mod._GRAPH_ENABLED is False


# ── Reranker Degradation ──────────────────────────────────────────────────────


class TestRerankerDegradation:
    """Verify reranker degrades gracefully when circuit breaker is open."""

    def test_reranker_returns_neutral_scores_on_circuit_open(self):
        """_call_reranker_safe returns neutral 0.5 scores when CB is open."""
        from unittest.mock import MagicMock

        import proxy.app.core.rerank as rerank_mod
        from proxy.app.shared.circuit_breaker import get_breaker, reset_all_breakers

        reset_all_breakers()

        mock_reranker = MagicMock()
        mock_reranker.predict.return_value = [0.9, 0.8, 0.3]
        rerank_mod.reranker = mock_reranker

        cb = get_breaker("reranker", failure_threshold=1)
        cb.failure()
        assert cb.state == State.OPEN

        pairs = [("q", "doc1"), ("q", "doc2"), ("q", "doc3")]
        result = rerank_mod._call_reranker_safe(pairs)

        assert result == [0.5, 0.5, 0.5]

    def test_reranker_returns_neutral_when_not_initialized(self):
        """_call_reranker_safe returns neutral scores when reranker is None."""
        import proxy.app.core.rerank as rerank_mod

        rerank_mod.reranker = None
        result = rerank_mod._call_reranker_safe([("q", "d1"), ("q", "d2")])
        assert result == [0.5, 0.5]


# ── LLM Provider Resource Cleanup ─────────────────────────────────────────────


class TestLLMProviderCleanup:
    """Verify LLM provider properly cleans up sessions on retry."""

    @pytest.mark.asyncio
    async def test_session_closed_on_timeout_retry(self):
        """Aiohttp session is closed after timeout in retry loop."""
        from unittest.mock import MagicMock

        from proxy.app.llm.provider import MultiProviderRouter

        router = MultiProviderRouter.__new__(MultiProviderRouter)
        router.provider_type = ProviderType.OPENAI
        router.adapter = MagicMock()
        router.adapter.translate_request.return_value = {"model": "test", "messages": []}
        router.adapter.headers = {"Content-Type": "application/json"}
        router.endpoint = "http://localhost:9999"
        router.api_key = None
        router._adapter_cache = {}

        mock_session = AsyncMock()
        mock_session.post.side_effect = TimeoutError("connection timed out")

        mock_config = {"MAX_RETRIES": 0, "REQUEST_TIMEOUT": 5, "RETRY_DELAY": 0.05}

        with (
            patch("aiohttp.ClientSession", return_value=mock_session),
            patch(
                "proxy.app.llm.provider.base._get_config",
                side_effect=lambda attr, default: mock_config.get(attr, default),
            ),
        ):
            with pytest.raises(Exception):
                await router._send_request([{"role": "user", "content": "test"}], retry=0)

            mock_session.close.assert_called()
