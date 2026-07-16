# proxy/app/shared/connection_pool.py
"""Connection pool management for HTTP and database clients.

Provides:
    - PooledHTTPClient: HTTP client with connection pooling, keep-alive,
      retry integration, and graceful shutdown.
    - PoolConfig: Connection pool size, timeout, keep-alive settings.
    - PoolStats: Runtime statistics (active, idle, total connections).
"""

from __future__ import annotations

import logging
import time
import weakref
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class PoolConfig:
    """Configuration for a connection pool.

    Attributes:
        max_connections: Maximum total connections in the pool.
        max_keepalive: Maximum idle connections to keep alive.
        keepalive_timeout: Seconds to keep idle connections alive.
        connect_timeout: Timeout for establishing new connections (seconds).
        acquire_timeout: Maximum time to wait for a connection from the pool (seconds).
        max_retries: Retries for transient connection failures.
        retry_delay: Base delay between retries (seconds).

    """

    max_connections: int = 20
    max_keepalive: int = 5
    keepalive_timeout: float = 60.0
    connect_timeout: float = 10.0
    acquire_timeout: float = 30.0
    max_retries: int = 2
    retry_delay: float = 0.5


@dataclass
class PoolStats:
    """Runtime statistics for a connection pool."""

    name: str = ""
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    total_requests: int = 0
    total_errors: int = 0
    total_timeouts: int = 0
    created_at: float = 0.0
    last_activity: float = 0.0

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_errors / self.total_requests

    @property
    def utilization(self) -> float:
        if self.total_connections == 0:
            return 0.0
        return self.active_connections / self.total_connections


class PoolExhaustedError(Exception):
    """Raised when the connection pool is exhausted and cannot serve a request."""

    def __init__(self, pool_name: str, max_connections: int):
        self.pool_name = pool_name
        self.max_connections = max_connections
        super().__init__(
            f"Connection pool '{pool_name}' exhausted (max={max_connections}). "
            "All connections are in use."
        )


class PoolTimeoutError(Exception):
    """Raised when acquiring a connection from the pool times out."""

    def __init__(self, pool_name: str, timeout: float):
        self.pool_name = pool_name
        self.timeout = timeout
        super().__init__(
            f"Timed out waiting for connection from pool '{pool_name}' ({timeout:.1f}s)"
        )


class ConnectionPool:
    """Generic connection pool with tracking and graceful shutdown.

    Manages a fixed-size pool of connections. Supports async context
    manager protocol for acquiring/releasing connections. Tracks stats
    and integrates with circuit breaker for gating.

    Usage:
        >>> pool = ConnectionPool("qdrant_http", PoolConfig(max_connections=10))
        >>> async with pool.acquire() as conn:
        ...     result = await conn.search(...)
    """

    def __init__(self, name: str, config: PoolConfig | None = None):
        self.name = name
        self.config = config or PoolConfig()
        self._connections: list[Any] = []
        self._available: list[Any] = []
        self._in_use: set[int] = set()
        self._factory: Callable[[], Any] | None = None
        self._total_requests = 0
        self._total_errors = 0
        self._total_timeouts = 0
        self._created_at = time.time()
        self._last_activity = time.time()
        self._closed = False
        self._lock: Any = None

        logger.info(
            "Connection pool '%s' initialized: max=%d, keepalive=%d, connect_timeout=%.1fs",
            self.name,
            self.config.max_connections,
            self.config.max_keepalive,
            self.config.connect_timeout,
        )

    def set_factory(self, factory: Callable[[], Any]) -> None:
        self._factory = factory

    async def _ensure_lock(self) -> Any:
        if self._lock is None:
            import asyncio
            self._lock = asyncio.Lock()
        return self._lock

    async def _create_connection(self) -> Any:
        if self._factory is None:
            raise RuntimeError(f"Connection pool '{self.name}' has no factory set")

        for attempt in range(self.config.max_retries + 1):
            try:
                conn = self._factory()
                if hasattr(conn, "connect"):
                    await conn.connect()
                return conn
            except Exception as e:
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay * (2**attempt)
                    logger.warning(
                        "Pool '%s': connection attempt %d failed: %s. Retrying in %.2fs...",
                        self.name, attempt + 1, e, delay,
                    )
                    import asyncio
                    await asyncio.sleep(delay)
                else:
                    logger.error("Pool '%s': all connection attempts exhausted: %s", self.name, e)
                    raise

        raise RuntimeError(f"Pool '{self.name}': unreachable")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        lock = await self._ensure_lock()
        async with lock:
            if self._closed:
                raise RuntimeError(f"Connection pool '{self.name}' is closed")

            conn = None
            while self._available:
                candidate = self._available.pop()
                if self._is_valid(candidate):
                    conn = candidate
                    break
                else:
                    await self._close_connection(candidate)
                    self._connections.remove(candidate)

            if conn is None and len(self._connections) < self.config.max_connections:
                conn = await self._create_connection()
                self._connections.append(conn)

            if conn is None:
                raise PoolExhaustedError(self.name, self.config.max_connections)

            conn_id = id(conn)
            self._in_use.add(conn_id)
            self._total_requests += 1
            self._last_activity = time.time()

        try:
            yield conn
        except Exception:
            self._total_errors += 1
            raise
        finally:
            async with lock:
                self._in_use.discard(conn_id)
                if self._is_valid(conn) and len(self._available) < self.config.max_keepalive:
                    self._available.append(conn)
                else:
                    await self._close_connection(conn)
                    if conn in self._connections:
                        self._connections.remove(conn)

    def acquire_sync(self) -> Any:
        """Synchronous connection acquisition for sync endpoints."""
        if self._closed:
            raise RuntimeError(f"Connection pool '{self.name}' is closed")

        conn = None
        while self._available:
            candidate = self._available.pop()
            if self._is_valid(candidate):
                conn = candidate
                break
            else:
                self._close_connection_sync(candidate)
                self._connections.remove(candidate)

        if conn is None and len(self._connections) < self.config.max_connections:
            if self._factory is not None:
                conn = self._factory()
            self._connections.append(conn)

        if conn is None:
            raise PoolExhaustedError(self.name, self.config.max_connections)

        self._in_use.add(id(conn))
        self._total_requests += 1
        self._last_activity = time.time()
        return conn

    def release_sync(self, conn: Any) -> None:
        conn_id = id(conn)
        self._in_use.discard(conn_id)
        if self._is_valid(conn) and len(self._available) < self.config.max_keepalive:
            self._available.append(conn)
        else:
            self._close_connection_sync(conn)
            if conn in self._connections:
                self._connections.remove(conn)

    @property
    def stats(self) -> PoolStats:
        return PoolStats(
            name=self.name,
            total_connections=len(self._connections),
            active_connections=len(self._in_use),
            idle_connections=len(self._available),
            total_requests=self._total_requests,
            total_errors=self._total_errors,
            total_timeouts=self._total_timeouts,
            created_at=self._created_at,
            last_activity=self._last_activity,
        )

    async def close(self) -> None:
        lock = await self._ensure_lock()
        async with lock:
            self._closed = True
            for conn in self._connections:
                await self._close_connection(conn)
            self._connections.clear()
            self._available.clear()
            self._in_use.clear()
            logger.info("Connection pool '%s' closed (%d connections released)", self.name, len(self._connections))

    def close_sync(self) -> None:
        self._closed = True
        for conn in self._connections:
            self._close_connection_sync(conn)
        self._connections.clear()
        self._available.clear()
        self._in_use.clear()
        logger.info("Connection pool '%s' closed", self.name)

    async def drain(self) -> None:
        lock = await self._ensure_lock()
        async with lock:
            old_connections = list(self._connections)
            for conn in old_connections:
                await self._close_connection(conn)
            self._connections.clear()
            self._available.clear()
            logger.info("Connection pool '%s' drained", self.name)

    async def health_check(self) -> bool:
        if self._closed:
            return False
        try:
            for conn in list(self._available):
                if not self._is_valid(conn):
                    self._available.remove(conn)
                    await self._close_connection(conn)
                    if conn in self._connections:
                        self._connections.remove(conn)
            return True
        except Exception:
            return False

    def _is_valid(self, conn: Any) -> bool:
        if hasattr(conn, "closed") and conn.closed:
            return False
        if hasattr(conn, "is_connected") and not conn.is_connected():
            return False
        return True

    async def _close_connection(self, conn: Any) -> None:
        try:
            if hasattr(conn, "close"):
                close_fn = conn.close
                import inspect as _insp
                if _insp.iscoroutinefunction(close_fn):
                    await close_fn()
                else:
                    close_fn()
            elif hasattr(conn, "aclose"):
                await conn.aclose()
        except Exception as e:
            logger.debug("Error closing connection in pool '%s': %s", self.name, e)

    def _close_connection_sync(self, conn: Any) -> None:
        try:
            if hasattr(conn, "close"):
                conn.close()
        except Exception as e:
            logger.debug("Error closing connection in pool '%s': %s", self.name, e)


class PoolRegistry:
    """Global registry of connection pools keyed by service name.

    Provides:
        - Named pool lookup and creation
        - Bulk stats collection
        - Bulk health check
        - Bulk close

    """

    def __init__(self) -> None:
        self._pools: dict[str, ConnectionPool] = {}

    def get_or_create(self, name: str, config: PoolConfig | None = None) -> ConnectionPool:
        if name not in self._pools:
            self._pools[name] = ConnectionPool(name, config)
        return self._pools[name]

    def get(self, name: str) -> ConnectionPool | None:
        return self._pools.get(name)

    def remove(self, name: str) -> None:
        pool = self._pools.pop(name, None)
        if pool is not None:
            pool.close_sync()

    def all_stats(self) -> dict[str, PoolStats]:
        return {name: pool.stats for name, pool in self._pools.items()}

    async def health_check_all(self) -> dict[str, bool]:
        results = {}
        for name, pool in self._pools.items():
            results[name] = await pool.health_check()
        return results

    async def close_all(self) -> None:
        for pool in self._pools.values():
            await pool.close()
        self._pools.clear()

    def close_all_sync(self) -> None:
        for pool in self._pools.values():
            pool.close_sync()
        self._pools.clear()

    @property
    def pool_count(self) -> int:
        return len(self._pools)

    @property
    def total_active(self) -> int:
        return sum(s.active_connections for s in self.all_stats().values())

    @property
    def total_connections(self) -> int:
        return sum(s.total_connections for s in self.all_stats().values())


_pool_registry: PoolRegistry | None = None


def get_pool_registry() -> PoolRegistry:
    global _pool_registry
    if _pool_registry is None:
        _pool_registry = PoolRegistry()
    return _pool_registry


def reset_pool_registry() -> None:
    global _pool_registry
    if _pool_registry is not None:
        _pool_registry.close_all_sync()
    _pool_registry = None
