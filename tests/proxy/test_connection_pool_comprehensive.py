"""Comprehensive tests for proxy/app/shared/connection_pool.py.

Targets the 71% coverage gap in the connection pool module.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from proxy.app.shared.connection_pool import (
    ConnectionPool,
    PoolConfig,
    PoolExhaustedError,
    PoolRegistry,
    PoolStats,
    PoolTimeoutError,
)

# ---------------------------------------------------------------------------
# PoolConfig
# ---------------------------------------------------------------------------


class TestPoolConfig:
    """Tests for the pool configuration dataclass."""

    def test_default_values(self) -> None:
        cfg = PoolConfig()
        assert cfg.max_connections == 20
        assert cfg.max_keepalive == 5
        assert cfg.keepalive_timeout == 60.0
        assert cfg.connect_timeout == 10.0
        assert cfg.acquire_timeout == 30.0
        assert cfg.max_retries == 2
        assert cfg.retry_delay == 0.5

    def test_custom_values(self) -> None:
        cfg = PoolConfig(max_connections=50, max_keepalive=10, keepalive_timeout=120.0)
        assert cfg.max_connections == 50
        assert cfg.max_keepalive == 10
        assert cfg.keepalive_timeout == 120.0


# ---------------------------------------------------------------------------
# PoolStats
# ---------------------------------------------------------------------------


class TestPoolStats:
    """Tests for the pool stats dataclass."""

    def test_error_rate_no_requests(self) -> None:
        stats = PoolStats(total_requests=0, total_errors=5)
        assert stats.error_rate == 0.0

    def test_error_rate_with_requests(self) -> None:
        stats = PoolStats(total_requests=10, total_errors=3)
        assert stats.error_rate == pytest.approx(0.3)

    def test_utilization_no_connections(self) -> None:
        stats = PoolStats(total_connections=0, active_connections=5)
        assert stats.utilization == 0.0

    def test_utilization_with_connections(self) -> None:
        stats = PoolStats(total_connections=10, active_connections=4)
        assert stats.utilization == 0.4

    def test_utilization_full(self) -> None:
        stats = PoolStats(total_connections=10, active_connections=10)
        assert stats.utilization == 1.0


# ---------------------------------------------------------------------------
# PoolExhaustedError / PoolTimeoutError
# ---------------------------------------------------------------------------


class TestPoolErrors:
    """Tests for the pool exception classes."""

    def test_exhausted_error_attributes(self) -> None:
        err = PoolExhaustedError("my_pool", 20)
        assert err.pool_name == "my_pool"
        assert err.max_connections == 20
        assert "my_pool" in str(err)

    def test_timeout_error_attributes(self) -> None:
        err = PoolTimeoutError("my_pool", 30.0)
        assert err.pool_name == "my_pool"
        assert err.timeout == 30.0
        assert "my_pool" in str(err)


# ---------------------------------------------------------------------------
# ConnectionPool — async interface
# ---------------------------------------------------------------------------


class TestConnectionPoolAsync:
    """Tests for the async connection pool interface."""

    def _make_factory(self) -> Any:
        """Factory producing connections WITHOUT a .connect() attribute,
        so the pool's _create_connection doesn't try to await a MagicMock.
        Sets closed=False so the pool treats the connection as valid.
        """
        counter = {"n": 0}

        def factory() -> Any:
            counter["n"] += 1
            # spec excludes 'connect' so the pool doesn't try to await it
            conn = MagicMock(spec=["close", "is_connected", "closed"])
            conn.closed = False
            return conn

        return factory

    @pytest.mark.asyncio
    async def test_set_factory(self) -> None:
        pool = ConnectionPool("test")
        factory = self._make_factory()
        pool.set_factory(factory)
        assert pool._factory is factory

    @pytest.mark.asyncio
    async def test_acquire_creates_connection(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        async with pool.acquire() as conn:
            assert conn is not None
            assert len(pool._connections) == 1

    @pytest.mark.asyncio
    async def test_acquire_re_uses_available_connection(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        async with pool.acquire() as conn1:
            first_id = id(conn1)
        # Pool should have stored the connection for reuse
        assert len(pool._available) == 1

        async with pool.acquire() as conn2:
            # Same connection should be reused
            assert id(conn2) == first_id

    @pytest.mark.asyncio
    async def test_acquire_lazily_creates(self) -> None:
        """Pool should not create connections until acquire is called."""
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())
        assert len(pool._connections) == 0

    @pytest.mark.asyncio
    async def test_acquire_drops_invalid_connections(self) -> None:
        """Invalid connections in the pool should be discarded."""
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        # Manually inject an invalid connection (closed=True)
        invalid_conn = MagicMock(spec=["close", "is_connected", "closed"])
        invalid_conn.closed = True
        pool._available.append(invalid_conn)
        pool._connections.append(invalid_conn)

        async with pool.acquire() as conn:
            # Should have created a new connection, not used the invalid one
            assert conn.closed is False

    @pytest.mark.asyncio
    async def test_acquire_exhausted_raises(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=1))
        pool.set_factory(self._make_factory())

        async with pool.acquire():
            pass  # hold the only connection

        # Manually fill the pool
        import asyncio as _asyncio

        async def try_acquire() -> None:
            async with pool.acquire():
                _asyncio.sleep(0.001)

        # Without a real second connection, the pool should reject
        # Use _available directly to simulate exhaustion
        pool._available = []  # drain available
        # Manually set the connection count to max
        pool._connections = [MagicMock() for _ in range(1)]
        pool._in_use.add(id(pool._connections[0]))

        with pytest.raises(PoolExhaustedError):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_acquire_after_close_raises(self) -> None:
        pool = ConnectionPool("test")
        pool.set_factory(self._make_factory())

        async with pool.acquire():
            pass

        await pool.close()

        with pytest.raises(RuntimeError, match="closed"):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_acquire_records_errors(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        with pytest.raises(ValueError, match="test error"):
            async with pool.acquire():
                raise ValueError("test error")

        assert pool._total_errors == 1

    @pytest.mark.asyncio
    async def test_release_too_many_keeps_max_keepalive(self) -> None:
        """When releasing, only up to max_keepalive connections are kept."""
        pool = ConnectionPool("test", PoolConfig(max_connections=10, max_keepalive=2))
        pool.set_factory(self._make_factory())

        # Acquire and release 4 connections
        for _ in range(4):
            async with pool.acquire():
                pass

        # Only max_keepalive should be kept in available
        assert len(pool._available) <= 2

    @pytest.mark.asyncio
    async def test_stats_after_acquire(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        async with pool.acquire():
            stats = pool.stats
            assert stats.name == "test"
            assert stats.active_connections == 1
            assert stats.total_requests == 1

    @pytest.mark.asyncio
    async def test_stats_after_release(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        async with pool.acquire():
            pass

        stats = pool.stats
        assert stats.active_connections == 0
        assert stats.idle_connections >= 1

    @pytest.mark.asyncio
    async def test_close_clears_all(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        async with pool.acquire():
            pass

        await pool.close()

        assert pool._closed is True
        assert len(pool._connections) == 0
        assert len(pool._available) == 0

    @pytest.mark.asyncio
    async def test_drain_closes_all(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        async with pool.acquire():
            pass

        await pool.drain()

        assert len(pool._connections) == 0
        assert len(pool._available) == 0

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_open(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        result = await pool.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_closed(self) -> None:
        pool = ConnectionPool("test")
        pool.set_factory(self._make_factory())
        await pool.close()

        result = await pool.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_removes_invalid_connections(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        pool.set_factory(self._make_factory())

        # Add invalid connection to available
        invalid = MagicMock()
        invalid.closed = True
        pool._available.append(invalid)
        pool._connections.append(invalid)

        result = await pool.health_check()
        assert result is True
        assert invalid not in pool._available


# ---------------------------------------------------------------------------
# ConnectionPool — sync interface
# ---------------------------------------------------------------------------


class TestConnectionPoolSync:
    """Tests for the synchronous connection pool interface."""

    def test_acquire_sync_without_factory_raises(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))
        # No factory set, no available connections → exhausted
        with pytest.raises(PoolExhaustedError):
            pool.acquire_sync()

    def test_acquire_sync_with_factory(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))

        def factory() -> Any:
            return MagicMock()

        pool.set_factory(factory)

        conn = pool.acquire_sync()
        assert conn is not None
        assert len(pool._connections) == 1

    def test_acquire_sync_re_uses_available(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))

        # Use a single shared connection so re-use is testable
        shared_conn = MagicMock(spec=["close", "is_connected"])

        def factory() -> Any:
            return shared_conn

        pool.set_factory(factory)

        conn1 = pool.acquire_sync()
        assert conn1 is shared_conn
        pool.release_sync(conn1)

        conn2 = pool.acquire_sync()
        assert conn2 is shared_conn

    def test_acquire_sync_after_close_raises(self) -> None:
        pool = ConnectionPool("test")

        def factory() -> Any:
            return MagicMock()

        pool.set_factory(factory)
        pool.close_sync()

        with pytest.raises(RuntimeError, match="closed"):
            pool.acquire_sync()

    def test_acquire_sync_exhausted(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=1))

        def factory() -> Any:
            return MagicMock()

        pool.set_factory(factory)

        pool.acquire_sync()
        # Now pool is exhausted
        with pytest.raises(PoolExhaustedError):
            pool.acquire_sync()

    def test_release_sync_to_keepalive(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=10, max_keepalive=5))

        def factory() -> Any:
            return MagicMock(spec=["close", "is_connected"])

        pool.set_factory(factory)

        conn = pool.acquire_sync()
        pool.release_sync(conn)

        assert len(pool._available) == 1

    def test_release_sync_drops_invalid(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=10, max_keepalive=5))

        def factory() -> Any:
            return MagicMock()

        pool.set_factory(factory)

        conn = pool.acquire_sync()
        # Make it invalid
        conn.closed = True
        pool.release_sync(conn)

        assert len(pool._available) == 0
        assert conn not in pool._connections

    def test_close_sync_clears_all(self) -> None:
        pool = ConnectionPool("test", PoolConfig(max_connections=2))

        def factory() -> Any:
            return MagicMock()

        pool.set_factory(factory)

        pool.acquire_sync()
        pool.close_sync()

        assert pool._closed is True
        assert len(pool._connections) == 0


# ---------------------------------------------------------------------------
# ConnectionPool — close behaviors
# ---------------------------------------------------------------------------


class TestConnectionPoolClose:
    """Tests for connection close behaviors."""

    @pytest.mark.asyncio
    async def test_close_connection_async_with_sync_close(self) -> None:
        pool = ConnectionPool("test")
        conn = MagicMock()
        conn.close = MagicMock()
        await pool._close_connection(conn)
        conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_connection_async_with_async_close(self) -> None:
        pool = ConnectionPool("test")
        conn = MagicMock()
        conn.close = AsyncMock()
        await pool._close_connection(conn)
        conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_connection_uses_aclose(self) -> None:
        """When close is not available, aclose is used."""
        pool = ConnectionPool("test")
        conn = MagicMock(spec=["aclose"])
        conn.aclose = AsyncMock()
        await pool._close_connection(conn)
        conn.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_connection_swallows_errors(self) -> None:
        """Errors during close should be logged but not raised."""
        pool = ConnectionPool("test")
        conn = MagicMock()
        conn.close = MagicMock(side_effect=Exception("close failed"))
        # Should not raise
        await pool._close_connection(conn)

    def test_close_connection_sync_async_close_warns(self) -> None:
        """Async close called via sync path should not crash."""
        pool = ConnectionPool("test")
        conn = MagicMock()
        conn.close = AsyncMock()  # async function
        # Should not raise
        pool._close_connection_sync(conn)

    def test_close_connection_sync_swallows_errors(self) -> None:
        pool = ConnectionPool("test")
        conn = MagicMock()
        conn.close = MagicMock(side_effect=Exception("close failed"))
        # Should not raise
        pool._close_connection_sync(conn)


# ---------------------------------------------------------------------------
# ConnectionPool — _is_valid
# ---------------------------------------------------------------------------


class TestConnectionPoolValidity:
    """Tests for the _is_valid connection check."""

    def test_is_valid_no_close_attr(self) -> None:
        pool = ConnectionPool("test")
        conn = MagicMock(spec=["is_connected"])
        assert pool._is_valid(conn) is True

    def test_is_valid_closed_true(self) -> None:
        pool = ConnectionPool("test")
        conn = MagicMock(spec=["close"])
        conn.closed = True
        assert pool._is_valid(conn) is False

    def test_is_valid_closed_false(self) -> None:
        pool = ConnectionPool("test")
        conn = MagicMock(spec=["close"])
        conn.closed = False
        assert pool._is_valid(conn) is True

    def test_is_valid_is_connected_false(self) -> None:
        pool = ConnectionPool("test")
        conn = MagicMock(spec=["close"])
        conn.is_connected = MagicMock(return_value=False)
        assert pool._is_valid(conn) is False

    def test_is_valid_is_connected_true(self) -> None:
        pool = ConnectionPool("test")
        conn = MagicMock(spec=["close"])
        conn.is_connected = MagicMock(return_value=True)
        assert pool._is_valid(conn) is True


# ---------------------------------------------------------------------------
# PoolRegistry
# ---------------------------------------------------------------------------


class TestPoolRegistry:
    """Tests for the global pool registry."""

    def test_init_empty(self) -> None:
        reg = PoolRegistry()
        assert reg.all_stats() == {}

    def test_get_or_create(self) -> None:
        reg = PoolRegistry()
        pool = reg.get_or_create("api1", PoolConfig(max_connections=5))
        assert pool.name == "api1"
        assert pool.config.max_connections == 5

    def test_get_or_create_returns_same(self) -> None:
        """Existing pool should be returned, not recreated."""
        reg = PoolRegistry()
        pool1 = reg.get_or_create("api1")
        pool2 = reg.get_or_create("api1")
        assert pool1 is pool2

    def test_get_existing(self) -> None:
        reg = PoolRegistry()
        pool = reg.get_or_create("api1")
        assert reg.get("api1") is pool

    def test_get_nonexistent(self) -> None:
        reg = PoolRegistry()
        assert reg.get("missing") is None

    def test_remove_existing(self) -> None:
        reg = PoolRegistry()
        reg.get_or_create("api1")
        reg.remove("api1")
        assert reg.get("api1") is None

    def test_remove_nonexistent(self) -> None:
        reg = PoolRegistry()
        # Should not raise
        reg.remove("missing")

    def test_all_stats(self) -> None:
        reg = PoolRegistry()
        reg.get_or_create("api1")
        reg.get_or_create("api2")
        stats = reg.all_stats()
        assert "api1" in stats
        assert "api2" in stats

    @pytest.mark.asyncio
    async def test_health_check_all(self) -> None:
        reg = PoolRegistry()
        reg.get_or_create("api1")
        reg.get_or_create("api2")

        results = await reg.health_check_all()
        assert "api1" in results
        assert "api2" in results
        assert results["api1"] is True
        assert results["api2"] is True
