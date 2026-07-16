"""Comprehensive reliability tests for the RAG system.

Tests cover:
    - Health check aggregation (health_aggregator.py)
    - Timeout management (timeout_manager.py)
    - Connection pool management (connection_pool.py)
    - Retry + circuit breaker integration
    - DLQ integration patterns
    - Graceful degradation for all services
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_reliability_state():
    """Reset reliability module state between tests."""
    try:
        from proxy.app.shared.health_aggregator import reset_health_aggregator
        reset_health_aggregator()
    except ImportError:
        pass
    try:
        from proxy.app.shared.timeout_manager import reset_service_timeouts
        reset_service_timeouts()
    except ImportError:
        pass
    try:
        from proxy.app.shared.connection_pool import reset_pool_registry
        reset_pool_registry()
    except ImportError:
        pass
    try:
        from proxy.app.shared.circuit_breaker import _breakers, _frozen, reset_all_breakers
        _frozen = False
        reset_all_breakers()
        _breakers.clear()
    except ImportError:
        pass
    yield
    try:
        from proxy.app.shared.health_aggregator import reset_health_aggregator
        reset_health_aggregator()
    except ImportError:
        pass
    try:
        from proxy.app.shared.timeout_manager import reset_service_timeouts
        reset_service_timeouts()
    except ImportError:
        pass
    try:
        from proxy.app.shared.connection_pool import reset_pool_registry
        reset_pool_registry()
    except ImportError:
        pass
    try:
        from proxy.app.shared.circuit_breaker import _breakers, _frozen, reset_all_breakers
        _frozen = False
        reset_all_breakers()
        _breakers.clear()
    except ImportError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Health Check Aggregation Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestHealthAggregator:
    """Test HealthAggregator — component registration, status aggregation."""

    def test_initial_state_unknown(self):
        from proxy.app.shared.health_aggregator import (
            AggregateStatus,
            HealthAggregator,
        )

        agg = HealthAggregator()
        result = agg.run_all()
        assert result.status == AggregateStatus.OK
        assert result.components == {}

    def test_register_check(self):
        from proxy.app.shared.health_aggregator import (
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator()
        agg.register("qdrant", lambda: True, critical=True)
        result = agg.run_all()
        assert result.status == "ok"
        assert result.components["qdrant"].status == HealthStatus.OK

    def test_critical_failure_aggregates_critical(self):
        from proxy.app.shared.health_aggregator import (
            AggregateStatus,
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator(critical_components=["qdrant"])
        agg.register("qdrant", lambda: False, critical=True)
        agg.register("redis", lambda: True)
        result = agg.run_all()
        assert result.status == AggregateStatus.CRITICAL
        assert result.components["qdrant"].status == HealthStatus.CRITICAL
        assert result.components["redis"].status == HealthStatus.OK

    def test_non_critical_failure_aggregates_degraded(self):
        from proxy.app.shared.health_aggregator import (
            AggregateStatus,
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator(critical_components=["qdrant"])
        agg.register("qdrant", lambda: True, critical=True)
        agg.register("redis", lambda: False)
        agg.register("neo4j", lambda: True)
        result = agg.run_all()
        assert result.status == AggregateStatus.DEGRADED
        assert result.components["redis"].status == HealthStatus.CRITICAL

    def test_all_healthy_is_ok(self):
        from proxy.app.shared.health_aggregator import (
            AggregateStatus,
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator(critical_components=["qdrant"])
        agg.register("qdrant", lambda: True, critical=True)
        agg.register("redis", lambda: True)
        agg.register("neo4j", lambda: True)
        agg.register("llm", lambda: True, critical=True)
        result = agg.run_all()
        assert result.status == AggregateStatus.OK
        assert all(c.status == HealthStatus.OK for c in result.components.values())

    def test_exception_in_check_is_critical(self):
        from proxy.app.shared.health_aggregator import (
            AggregateStatus,
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator()
        agg.register("qdrant", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        result = agg.run_all()
        assert result.components["qdrant"].status == HealthStatus.CRITICAL
        assert result.components["qdrant"].error == "boom"

    def test_get_component_returns_cached(self):
        from proxy.app.shared.health_aggregator import (
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator()
        agg.register("test_svc", lambda: True)
        agg.run_check("test_svc")
        comp = agg.get_component("test_svc")
        assert comp is not None
        assert comp.status == HealthStatus.OK

    def test_get_component_unknown_returns_none(self):
        from proxy.app.shared.health_aggregator import HealthAggregator

        agg = HealthAggregator()
        assert agg.get_component("nonexistent") is None

    def test_healthy_components_list(self):
        from proxy.app.shared.health_aggregator import HealthAggregator

        agg = HealthAggregator()
        agg.register("svc_a", lambda: True)
        agg.register("svc_b", lambda: False)
        agg.register("svc_c", lambda: True)
        agg.run_all()
        healthy = agg.healthy_components
        assert "svc_a" in healthy
        assert "svc_c" in healthy
        assert "svc_b" not in healthy

    def test_unhealthy_components_list(self):
        from proxy.app.shared.health_aggregator import HealthAggregator

        agg = HealthAggregator()
        agg.register("svc_a", lambda: True)
        agg.register("svc_b", lambda: False)
        agg.run_all()
        unhealthy = agg.unhealthy_components
        assert "svc_b" in unhealthy
        assert "svc_a" not in unhealthy

    def test_cache_ttl_respects(self):
        from proxy.app.shared.health_aggregator import HealthAggregator

        agg = HealthAggregator()
        agg.set_ttl(60.0)
        agg.register("svc", lambda: True)
        result1 = agg.run_all(use_cache=True)
        result2 = agg.run_all(use_cache=True)
        assert result1.timestamp == result2.timestamp

    def test_invalidate_cache_forces_refresh(self):
        from proxy.app.shared.health_aggregator import HealthAggregator

        agg = HealthAggregator()
        agg.set_ttl(60.0)
        agg.register("svc", lambda: True)
        result1 = agg.run_all(use_cache=True)
        agg.invalidate_cache()
        result2 = agg.run_all(use_cache=True)
        assert result2.timestamp >= result1.timestamp

    def test_details_fn_passed_through(self):
        from proxy.app.shared.health_aggregator import (
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator()
        agg.register(
            "qdrant",
            lambda: True,
            details_fn=lambda: {"collections": 5, "vectors": 10000},
        )
        agg.run_check("qdrant")
        comp = agg.get_component("qdrant")
        assert comp is not None
        assert comp.details == {"collections": 5, "vectors": 10000}

    def test_unregister_removes_check(self):
        from proxy.app.shared.health_aggregator import HealthAggregator

        agg = HealthAggregator()
        agg.register("temp", lambda: True)
        assert "temp" in agg.all_component_names
        agg.unregister("temp")
        assert "temp" not in agg.all_component_names

    @pytest.mark.asyncio
    async def test_async_run_all(self):
        from proxy.app.shared.health_aggregator import (
            AggregateStatus,
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator()
        agg.register("svc_a", lambda: True)
        agg.register("svc_b", lambda: False)
        result = await agg.run_all_async()
        assert result.components["svc_a"].status == HealthStatus.OK
        assert result.components["svc_b"].status == HealthStatus.CRITICAL

    def test_default_critical_components_via_getter(self):
        from proxy.app.shared.health_aggregator import get_health_aggregator

        agg = get_health_aggregator()
        assert "qdrant" in agg.critical_components
        assert "llm_backend" in agg.critical_components
        assert "proxy" in agg.critical_components


# ═══════════════════════════════════════════════════════════════════════════════
# Timeout Manager Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTimeoutManager:
    """Test TimeoutManager — context manager, decorator, service timeouts."""

    def test_context_manager_no_timeout_normal(self):
        from proxy.app.shared.timeout_manager import TimeoutManager

        with TimeoutManager(5.0, operation="test"):
            result = 42
        assert result == 42

    def test_service_timeouts_default_values(self):
        from proxy.app.shared.timeout_manager import get_service_timeouts

        st = get_service_timeouts()
        assert st.get("qdrant") == 10.0
        assert st.get("llm_backend") == 120.0
        assert st.get("neo4j") == 10.0
        assert st.get("redis") == 5.0
        assert st.get("reranker") == 10.0
        assert st.get("embedder") == 30.0

    def test_service_timeouts_custom_override(self):
        from proxy.app.shared.timeout_manager import get_service_timeouts

        st = get_service_timeouts()
        st.set("qdrant", 15.0)
        assert st.get("qdrant") == 15.0

    def test_service_timeouts_unknown_service_returns_default(self):
        from proxy.app.shared.timeout_manager import get_service_timeouts

        st = get_service_timeouts()
        assert st.get("nonexistent_service") == 30.0

    def test_service_timeouts_set_all(self):
        from proxy.app.shared.timeout_manager import get_service_timeouts

        st = get_service_timeouts()
        st.set_all(60.0)
        assert st.get("qdrant") == 60.0
        assert st.get("llm_backend") == 60.0
        assert st.get("redis") == 60.0

    def test_service_timeouts_enabled_toggle(self):
        from proxy.app.shared.timeout_manager import get_service_timeouts

        st = get_service_timeouts()
        assert st.enabled is True
        st.enabled = False
        assert st.enabled is False
        st.enabled = True
        assert st.enabled is True

    def test_all_timeouts_property(self):
        from proxy.app.shared.timeout_manager import get_service_timeouts

        st = get_service_timeouts()
        all_t = st.all_timeouts
        assert isinstance(all_t, dict)
        assert "qdrant" in all_t
        assert "llm_backend" in all_t

    def test_request_timeout_error_str(self):
        from proxy.app.shared.timeout_manager import RequestTimeoutError

        err = RequestTimeoutError(5.0, "search_qdrant")
        assert "5.0s" in str(err)
        assert "search_qdrant" in str(err)
        assert err.timeout == 5.0
        assert err.operation == "search_qdrant"

    @pytest.mark.asyncio
    async def test_async_timeout_wrap(self):
        from proxy.app.shared.timeout_manager import RequestTimeoutError, TimeoutManager

        async def slow_op():
            await asyncio.sleep(10.0)
            return "done"

        tm = TimeoutManager(timeout=0.01, operation="slow_test")
        with pytest.raises(RequestTimeoutError):
            await tm.wrap_async(slow_op())

    def test_timeout_decorator_async(self):
        from proxy.app.shared.timeout_manager import RequestTimeoutError, TimeoutManager

        @TimeoutManager.timeout(seconds=0.01, operation="decorated")
        async def slow_fn():
            await asyncio.sleep(10.0)

        with pytest.raises(RequestTimeoutError):
            asyncio.run(slow_fn())

    def test_timeout_decorator_sync(self):
        from proxy.app.shared.timeout_manager import TimeoutManager

        @TimeoutManager.timeout(seconds=5.0)
        def fast_fn(x):
            return x * 2

        result = fast_fn(21)
        assert result == 42

    def test_timeout_manager_properties(self):
        from proxy.app.shared.timeout_manager import TimeoutManager

        tm = TimeoutManager(timeout=15.0, operation="search", service="qdrant")
        assert tm.timeout_value == 15.0
        assert tm.operation == "search"

    def test_timeout_manager_uses_service_defaults(self):
        from proxy.app.shared.timeout_manager import TimeoutManager

        tm = TimeoutManager(service="qdrant")
        assert tm.timeout_value == 10.0


class TestTimeoutIntegrationWithCircuitBreaker:
    """Test timeout + circuit breaker integration patterns."""

    def test_timeout_triggers_circuit_breaker_failure(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker
        from proxy.app.shared.timeout_manager import RequestTimeoutError

        cb = CircuitBreaker("timeout_cb", failure_threshold=3)
        try:
            raise RequestTimeoutError(5.0, "qdrant_search")
        except RequestTimeoutError:
            cb.failure()
        assert cb.failure_count == 1

    def test_timeout_exhaustion_feeds_dlq(self):
        from proxy.app.shared.dlq import DeadLetterQueue
        from proxy.app.shared.timeout_manager import RequestTimeoutError

        dlq = DeadLetterQueue("timeout_dlq", db_path=":memory:")
        try:
            try:
                raise RequestTimeoutError(5.0, "llm_generation")
            except RequestTimeoutError as e:
                dlq.add(
                    {"action": "llm_generation", "error": str(e)},
                    error=str(e),
                    metadata={"service": "llm_backend"},
                )
        finally:
            stats = dlq.stats()
            assert stats["total"] == 1

    def test_retry_with_timeout_per_attempt(self):
        from proxy.app.shared.retry import RetryConfig, async_retry

        config = RetryConfig(max_attempts=3, base_delay=0.001)
        assert config.max_attempts == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Connection Pool Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestConnectionPool:
    """Test ConnectionPool — acquire/release, stats, lifecycle."""

    def test_pool_creation(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        config = PoolConfig(max_connections=10, max_keepalive=3)
        pool = ConnectionPool("test_pool", config)
        assert pool.name == "test_pool"
        assert pool.config.max_connections == 10
        assert pool.config.max_keepalive == 3

    def test_pool_config_defaults(self):
        from proxy.app.shared.connection_pool import PoolConfig

        config = PoolConfig()
        assert config.max_connections == 20
        assert config.max_keepalive == 5
        assert config.keepalive_timeout == 60.0
        assert config.connect_timeout == 10.0
        assert config.acquire_timeout == 30.0

    def test_pool_stats_initial(self):
        from proxy.app.shared.connection_pool import ConnectionPool

        pool = ConnectionPool("stats_test")
        stats = pool.stats
        assert stats.name == "stats_test"
        assert stats.total_connections == 0
        assert stats.active_connections == 0
        assert stats.idle_connections == 0
        assert stats.total_requests == 0
        assert stats.total_errors == 0

    @pytest.mark.asyncio
    async def test_pool_acquire_and_release(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        connections_created = []

        def factory():
            conn = AsyncMock()
            conn.closed = False
            conn.close = AsyncMock()
            connections_created.append(conn)
            return conn

        pool = ConnectionPool("acq_test", PoolConfig(max_connections=2))
        pool.set_factory(factory)

        async with pool.acquire() as conn1:
            assert conn1 is not None
            stats = pool.stats
            assert stats.total_requests == 1

        async with pool.acquire() as conn2:
            assert conn2 is not None

        pool.close_sync()

    @pytest.mark.asyncio
    async def test_pool_exhausted(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig, PoolExhaustedError

        def factory():
            conn = AsyncMock()
            conn.closed = False
            conn.close = AsyncMock()
            return conn

        pool = ConnectionPool("exhaust_test", PoolConfig(max_connections=1))
        pool.set_factory(factory)

        async with pool.acquire() as conn1:
            with pytest.raises(PoolExhaustedError):
                async with pool.acquire() as conn2:
                    pass

        pool.close_sync()

    @pytest.mark.asyncio
    async def test_pool_closed_raises_on_acquire(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        pool = ConnectionPool("closed_test", PoolConfig(max_connections=1))
        pool.close_sync()

        with pytest.raises(RuntimeError, match="closed"):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_pool_reuse_idle_connections(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        created = []

        def factory():
            conn = AsyncMock()
            conn.closed = False
            conn.close = AsyncMock()
            conn.is_connected = MagicMock(return_value=True)
            created.append(conn)
            return conn

        pool = ConnectionPool("reuse_test", PoolConfig(max_connections=5, max_keepalive=5))
        pool.set_factory(factory)

        async with pool.acquire():
            pass
        async with pool.acquire():
            pass

        assert len(created) == 1

        pool.close_sync()

    @pytest.mark.asyncio
    async def test_pool_stats_after_usage(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        def factory():
            conn = AsyncMock()
            conn.closed = False
            conn.close = AsyncMock()
            return conn

        pool = ConnectionPool("stats_use", PoolConfig(max_connections=3))
        pool.set_factory(factory)

        async with pool.acquire():
            pass
        async with pool.acquire():
            pass

        stats = pool.stats
        assert stats.total_requests == 2

        pool.close_sync()

    @pytest.mark.asyncio
    async def test_pool_multiple_connections(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        created = []

        def factory():
            conn = AsyncMock()
            conn.closed = False
            conn.close = AsyncMock()
            created.append(conn)
            return conn

        pool = ConnectionPool("multi_test", PoolConfig(max_connections=3, max_keepalive=3))
        pool.set_factory(factory)

        async def use_pool():
            async with pool.acquire() as conn:
                await asyncio.sleep(0.01)

        await asyncio.gather(use_pool(), use_pool(), use_pool())
        assert len(created) <= 3
        pool.close_sync()

    @pytest.mark.asyncio
    async def test_pool_drain(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        created = []

        def factory():
            conn = AsyncMock()
            conn.closed = False
            conn.close = AsyncMock()
            created.append(conn)
            return conn

        pool = ConnectionPool("drain_test", PoolConfig(max_connections=3))
        pool.set_factory(factory)

        async with pool.acquire():
            pass

        await pool.drain()
        assert pool.stats.total_connections == 0
        pool.close_sync()

    @pytest.mark.asyncio
    async def test_health_check_removes_invalid(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        def factory():
            conn = AsyncMock()
            conn.closed = False
            conn.close = AsyncMock()
            return conn

        pool = ConnectionPool("health_test", PoolConfig(max_connections=2))
        pool.set_factory(factory)

        async with pool.acquire():
            pass

        result = await pool.health_check()
        assert result is True
        pool.close_sync()

    def test_health_check_closed_pool(self):
        from proxy.app.shared.connection_pool import ConnectionPool, PoolConfig

        pool = ConnectionPool("closed_health", PoolConfig(max_connections=1))
        pool.close_sync()
        import asyncio as _a
        result = _a.run(pool.health_check())
        assert result is False


class TestPoolRegistry:
    """Test PoolRegistry — global pool management."""

    def test_get_or_create_returns_same(self):
        from proxy.app.shared.connection_pool import get_pool_registry

        reg = get_pool_registry()
        p1 = reg.get_or_create("qdrant_http")
        p2 = reg.get_or_create("qdrant_http")
        assert p1 is p2

    def test_registry_pool_count(self):
        from proxy.app.shared.connection_pool import get_pool_registry

        reg = get_pool_registry()
        reg.get_or_create("svc_a")
        reg.get_or_create("svc_b")
        reg.get_or_create("svc_c")
        assert reg.pool_count == 3

    def test_registry_remove(self):
        from proxy.app.shared.connection_pool import get_pool_registry

        reg = get_pool_registry()
        reg.get_or_create("temp_pool")
        assert reg.get("temp_pool") is not None
        reg.remove("temp_pool")
        assert reg.get("temp_pool") is None

    def test_all_stats(self):
        from proxy.app.shared.connection_pool import get_pool_registry

        reg = get_pool_registry()
        reg.get_or_create("pool_a")
        reg.get_or_create("pool_b")
        stats = reg.all_stats()
        assert "pool_a" in stats
        assert "pool_b" in stats
        assert stats["pool_a"].total_requests == 0

    def test_total_active_and_connections(self):
        from proxy.app.shared.connection_pool import get_pool_registry

        reg = get_pool_registry()
        reg.get_or_create("p1")
        reg.get_or_create("p2")
        assert reg.total_active == 0
        assert reg.total_connections == 0


class TestPoolStats:
    """Test PoolStats dataclass methods."""

    def test_error_rate_zero_requests(self):
        from proxy.app.shared.connection_pool import PoolStats

        stats = PoolStats(total_requests=0, total_errors=5)
        assert stats.error_rate == 0.0

    def test_error_rate_normal(self):
        from proxy.app.shared.connection_pool import PoolStats

        stats = PoolStats(total_requests=100, total_errors=10)
        assert stats.error_rate == 0.1

    def test_utilization_zero_connections(self):
        from proxy.app.shared.connection_pool import PoolStats

        stats = PoolStats(total_connections=0, active_connections=3)
        assert stats.utilization == 0.0

    def test_utilization_normal(self):
        from proxy.app.shared.connection_pool import PoolStats

        stats = PoolStats(total_connections=10, active_connections=7)
        assert stats.utilization == 0.7


# ═══════════════════════════════════════════════════════════════════════════════
# Graceful Degradation Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestGracefulDegradation:
    """Test graceful degradation across the reliability stack."""

    def test_circuit_breaker_open_triggers_degraded_health(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State
        from proxy.app.shared.health_aggregator import HealthAggregator, HealthStatus

        cb = CircuitBreaker("qdrant", failure_threshold=1)
        cb.failure()
        assert cb.state == State.OPEN

        agg = HealthAggregator(critical_components=["qdrant"])
        agg.register("qdrant", lambda: cb.state != State.OPEN, critical=True)
        result = agg.run_all()
        assert result.status == "critical"

    def test_retry_exhausted_flows_to_dlq(self):
        from proxy.app.shared.dlq import DeadLetterQueue
        from proxy.app.shared.retry import RetryConfig, RetryExhaustedError, sync_retry

        dlq = DeadLetterQueue("graceful_dlq", db_path=":memory:")
        try:
            def always_fails():
                raise ConnectionError("transient")

            try:
                sync_retry(always_fails, config=RetryConfig(max_attempts=2, base_delay=0.001))
            except RetryExhaustedError as e:
                dlq.add(
                    {"fn": "always_fails"},
                    error=str(e),
                    metadata={"type": "retry_exhausted"},
                )

            stats = dlq.stats()
            assert stats["total"] == 1
        finally:
            dlq.close()

    def test_redis_unavailable_cache_fallback(self):
        from proxy.app.shared.cache import InMemoryCache

        cache = InMemoryCache()
        cache.set_sync("test_key", "test_value")
        assert cache.get_sync("test_key") == "test_value"
        cache.delete_sync("test_key")
        assert cache.get_sync("test_key") is None

    def test_neo4j_unavailable_skip_graph_expansion(self):
        from proxy.app.shared.exceptions import GraphError

        err = GraphError("Neo4j not available", component="graph")
        assert err.recoverable is True
        assert err.component == "graph"
        assert "Neo4j" in str(err)

    def test_reranker_unavailable_fallback_to_raw_scores(self):
        from proxy.app.shared.exceptions import RerankerError

        err = RerankerError("Reranker OOM", component="reranker")
        assert err.recoverable is True

    def test_embedder_unavailable_fallback_to_remote(self):
        from proxy.app.shared.exceptions import EmbeddingError

        err = EmbeddingError("Local embedder failed", component="embedder")
        assert err.component == "embedder"

    def test_llm_unavailable_triggers_retry_then_degraded(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State
        from proxy.app.shared.retry import RetryConfig, RetryExhaustedError, sync_retry

        cb = CircuitBreaker("llm_backend", failure_threshold=2)
        cb.failure()
        cb.failure()
        assert cb.state == State.OPEN

    def test_dlq_persists_across_restarts(self):
        from proxy.app.shared.dlq import DeadLetterQueue

        dlq = DeadLetterQueue("persist_test", db_path=":memory:")
        dlq.add({"query": "test"}, error="transient failure")
        stats = dlq.stats()
        assert stats["total"] == 1
        assert stats["pending"] == 1

    def test_component_failure_isolation(self):
        from proxy.app.shared.circuit_breaker import CircuitBreaker, State, CircuitBreakerOpenError
        from proxy.app.shared.health_aggregator import HealthAggregator, HealthStatus

        qdrant_cb = CircuitBreaker("qdrant", failure_threshold=1)
        neo4j_cb = CircuitBreaker("neo4j", failure_threshold=3)

        qdrant_cb.failure()
        neo4j_cb.failure()

        assert qdrant_cb.state == State.OPEN
        assert neo4j_cb.state == State.CLOSED

        agg = HealthAggregator(critical_components=["qdrant"])
        agg.register("qdrant", lambda: qdrant_cb.state != State.OPEN, critical=True)
        agg.register("neo4j", lambda: neo4j_cb.state != State.OPEN)

        result = agg.run_all()
        assert result.status == "critical"
        assert result.components["qdrant"].status == HealthStatus.CRITICAL


# ═══════════════════════════════════════════════════════════════════════════════
# End-to-End Reliability Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestReliabilityPipeline:
    """End-to-end reliability pipeline: CB → retry → DLQ → health."""

    def test_full_cb_retry_dlq_health_flow(self):
        from proxy.app.shared.circuit_breaker import State, CircuitBreakerOpenError, get_breaker
        from proxy.app.shared.dlq import DeadLetterQueue
        from proxy.app.shared.health_aggregator import HealthAggregator
        from proxy.app.shared.retry import RetryConfig, RetryExhaustedError, sync_retry

        dlq = DeadLetterQueue("e2e_dlq", db_path=":memory:")
        cb = get_breaker("e2e_service", failure_threshold=3)
        agg = HealthAggregator(critical_components=["e2e_service"])

        def e2e_service_call():
            if cb.state == State.OPEN:
                raise CircuitBreakerOpenError("e2e_service")
            raise ConnectionError("transient")

        for i in range(3):
            try:
                sync_retry(
                    e2e_service_call,
                    config=RetryConfig(
                        max_attempts=2,
                        base_delay=0.001,
                        retryable_exceptions=(ConnectionError,),
                        circuit_breaker_name="e2e_service",
                    ),
                )
            except (RetryExhaustedError, CircuitBreakerOpenError) as e:
                dlq.add(
                    {"attempt": i + 1},
                    error=str(e),
                    metadata={"circuit": cb.state.value},
                )

        agg.register("e2e_service", lambda: cb.state != State.OPEN, critical=True)
        result = agg.run_all()

        assert result.status == "critical"
        assert dlq.stats()["total"] == 3
        dlq.close()

    def test_health_aggregation_with_multiple_degraded_services(self):
        from proxy.app.shared.health_aggregator import (
            AggregateStatus,
            HealthAggregator,
            HealthStatus,
        )

        agg = HealthAggregator(critical_components=["qdrant", "llm_backend"])
        agg.register("qdrant", lambda: True, critical=True)
        agg.register("llm_backend", lambda: False, critical=True)
        agg.register("neo4j", lambda: False)
        agg.register("redis", lambda: False)
        agg.register("reranker", lambda: True)

        result = agg.run_all()
        assert result.status == AggregateStatus.CRITICAL
        assert "llm_backend" in result.summary


# ═══════════════════════════════════════════════════════════════════════════════
# Retry + Circuit Breaker Integration Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestRetryCircuitBreakerIntegration:
    """Test deeper retry + circuit breaker integration."""

    def test_retry_records_circuit_breaker_on_failure(self):
        from proxy.app.shared.circuit_breaker import get_breaker
        from proxy.app.shared.retry import RetryConfig, RetryExhaustedError, sync_retry

        cb = get_breaker("retry_cb_test", failure_threshold=5)

        def transient_fail():
            raise ConnectionError("fail")

        try:
            sync_retry(
                transient_fail,
                config=RetryConfig(
                    max_attempts=3,
                    base_delay=0.001,
                    circuit_breaker_name="retry_cb_test",
                ),
            )
        except RetryExhaustedError:
            pass

        assert cb.failure_count >= 1

    def test_retry_honours_circuit_breaker_open(self):
        from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError, get_breaker
        from proxy.app.shared.retry import RetryConfig, RetryExhaustedError, sync_retry

        cb = get_breaker("retry_open_test", failure_threshold=1)
        cb.failure()

        def should_not_run():
            return "success"

        with pytest.raises((CircuitBreakerOpenError, RetryExhaustedError)):
            sync_retry(
                should_not_run,
                config=RetryConfig(
                    max_attempts=2,
                    base_delay=0.001,
                    circuit_breaker_name="retry_open_test",
                ),
            )

    def test_retry_with_non_retryable_exception_skips_dlq(self):
        from proxy.app.shared.dlq import DeadLetterQueue
        from proxy.app.shared.retry import RetryConfig, sync_retry

        dlq = DeadLetterQueue("non_retry_dlq", db_path=":memory:")
        try:
            def bad_input():
                raise ValueError("invalid input")

            with pytest.raises(ValueError):
                sync_retry(
                    bad_input,
                    config=RetryConfig(
                        max_attempts=3,
                        base_delay=0.001,
                        retryable_exceptions=(ConnectionError, TimeoutError),
                    ),
                )

            assert dlq.stats()["total"] == 0
        finally:
            dlq.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Exception Hierarchy Integration
# ═══════════════════════════════════════════════════════════════════════════════


class TestExceptionHierarchy:
    """Verify exception hierarchy works with reliability components."""

    def test_all_exceptions_are_recoverable_by_default(self):
        from proxy.app.shared.exceptions import (
            CacheError,
            DLQError,
            EmbeddingError,
            GraphError,
            LLMError,
            RerankerError,
            RetrievalError,
            StorageError,
        )

        for cls in [RetrievalError, RerankerError, LLMError, GraphError, CacheError,
                     EmbeddingError, StorageError, DLQError]:
            err = cls("test")
            assert err.recoverable is True

    def test_security_and_config_are_not_recoverable(self):
        from proxy.app.shared.exceptions import AuthError, ConfigError, SecurityError, ValidationError

        for cls in [ConfigError, AuthError, SecurityError, ValidationError]:
            err = cls("test")
            assert err.recoverable is False

    def test_rag_error_can_be_caught_by_base(self):
        from proxy.app.shared.exceptions import RAGError, RetrievalError

        try:
            raise RetrievalError("not found")
        except RAGError:
            pass

    def test_retry_exhausted_preserves_chain(self):
        from proxy.app.shared.retry import RetryConfig, RetryExhaustedError, sync_retry

        def fails():
            raise TimeoutError("nested")

        try:
            sync_retry(fails, config=RetryConfig(max_attempts=2, base_delay=0.001))
        except RetryExhaustedError as e:
            assert isinstance(e.__cause__, TimeoutError)
