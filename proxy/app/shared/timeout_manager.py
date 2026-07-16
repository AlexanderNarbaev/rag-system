# proxy/app/shared/timeout_manager.py
"""Request timeout handling with context managers and decorators.

Provides:
    - Timeout context manager for sync/async operations
    - Decorator for applying timeouts to functions
    - Per-service default timeout configuration
    - TimeoutError with timeout value embedded
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_EMPTY = object()


class RequestTimeoutError(TimeoutError):
    """Raised when an operation exceeds its configured timeout."""

    def __init__(self, timeout: float, operation: str = ""):
        self.timeout = timeout
        self.operation = operation
        msg = f"Operation timed out after {timeout:.1f}s"
        if operation:
            msg += f": {operation}"
        super().__init__(msg)


@dataclass
class TimeoutConfig:
    """Per-service timeout configuration.

    Attributes:
        default: Default timeout in seconds for operations.
        per_service: Service-specific overrides.
        enabled: Master switch to disable all timeout enforcement.

    """

    default: float = 30.0
    per_service: dict[str, float] = field(default_factory=dict)
    enabled: bool = True

    def get_timeout(self, service: str | None = None) -> float:
        if service and service in self.per_service:
            return self.per_service[service]
        return self.default


class ServiceTimeouts:
    """Registry of per-service timeout configurations.

    Built-in defaults for all RAG system components:
        - qdrant: 10s (vector search)
        - llm_backend: 120s (generation can be slow)
        - slm_backend: 30s (routing, fast inference)
        - neo4j: 10s (graph traversal)
        - redis: 5s (cache operations)
        - embedder: 30s (embedding generation)
        - reranker: 10s (cross-encoder scoring)
        - minio: 30s (object storage)
        - default: 30s

    """

    DEFAULT_TIMEOUTS: dict[str, float] = {
        "qdrant": 10.0,
        "llm_backend": 120.0,
        "slm_backend": 30.0,
        "neo4j": 10.0,
        "redis": 5.0,
        "embedder": 30.0,
        "reranker": 10.0,
        "minio": 30.0,
        "confluence": 15.0,
        "jira": 15.0,
        "gitlab": 15.0,
    }

    DEFAULT_FALLBACK: float = 30.0

    def __init__(self) -> None:
        self._timeouts: dict[str, float] = dict(self.DEFAULT_TIMEOUTS)
        self._enabled: bool = True

    def get(self, service: str) -> float:
        return self._timeouts.get(service, self.DEFAULT_FALLBACK)

    def set(self, service: str, timeout: float) -> None:
        self._timeouts[service] = timeout

    def set_all(self, timeout: float) -> None:
        for key in self._timeouts:
            self._timeouts[key] = timeout

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def all_timeouts(self) -> dict[str, float]:
        return dict(self._timeouts)


_default_timeouts: ServiceTimeouts | None = None


def get_service_timeouts() -> ServiceTimeouts:
    global _default_timeouts
    if _default_timeouts is None:
        _default_timeouts = ServiceTimeouts()
    return _default_timeouts


def reset_service_timeouts() -> None:
    global _default_timeouts
    _default_timeouts = None


class TimeoutManager:
    """Manages timeouts for sync and async operations.

    Usage as context manager:
        >>> with TimeoutManager(5.0, operation="qdrant_search"):
        ...     results = qdrant.search(query)

        >>> async with TimeoutManager(5.0, operation="qdrant_search_async"):
        ...     results = await qdrant.search_async(query)

    Usage as decorator:
        >>> @TimeoutManager.timeout(5.0)
        ... def fetch_data():
        ...     return api.get()

    """

    def __init__(
        self,
        timeout: float | None = None,
        operation: str = "",
        service: str | None = None,
    ):
        if timeout is None and service is not None:
            timeout = get_service_timeouts().get(service)
        elif timeout is None:
            timeout = ServiceTimeouts.DEFAULT_FALLBACK

        self._timeout = timeout
        self._operation = operation
        self._service = service
        self._thread_timer: threading.Timer | None = None

    def __enter__(self) -> TimeoutManager:
        if not get_service_timeouts().enabled:
            return self
        self._setup_sync()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool | None:
        self._teardown_sync()
        if exc_type is not None and exc_val is not None and isinstance(exc_val, RequestTimeoutError):
            return False
        return None

    async def __aenter__(self) -> TimeoutManager:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> Any:
        if exc_type is not None and exc_val is not None and isinstance(exc_val, RequestTimeoutError):
            return False
        return None

    def _setup_sync(self) -> None:
        self._thread_timer = threading.Timer(
            self._timeout,
            self._on_timeout,
        )
        self._thread_timer.start()

    def _teardown_sync(self) -> None:
        if self._thread_timer is not None:
            self._thread_timer.cancel()
            self._thread_timer = None

    def _on_timeout(self) -> None:
        logger.warning(
            "Timeout %.1fs reached for operation '%s' (service: %s)",
            self._timeout,
            self._operation,
            self._service or "unknown",
        )

    @staticmethod
    def timeout(
        seconds: float | None = None,
        service: str | None = None,
        operation: str = "",
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            import functools

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> T:
                tm = TimeoutManager(timeout=seconds, operation=operation, service=service)
                with tm:
                    return func(*args, **kwargs)

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> T:
                tm = TimeoutManager(timeout=seconds, operation=operation, service=service)
                timeout_val = tm._timeout
                service_name = tm._service or "unknown"
                try:
                    result: T = await asyncio.wait_for(
                        func(*args, **kwargs),  # type: ignore[arg-type]
                        timeout=timeout_val,
                    )
                    return result
                except TimeoutError:
                    raise RequestTimeoutError(timeout_val, f"{operation or func.__name__} ({service_name})") from None

            import inspect as _inspect

            if _inspect.iscoroutinefunction(func):
                return async_wrapper  # type: ignore[return-value]
            return sync_wrapper

        return decorator

    def wrap_async(self, coro: Awaitable[T]) -> Awaitable[T]:
        async def _wrapped() -> T:
            try:
                return await asyncio.wait_for(coro, timeout=self._timeout)
            except TimeoutError:
                raise RequestTimeoutError(
                    self._timeout,
                    f"{self._operation} ({self._service or 'unknown'})",
                ) from None

        return _wrapped()

    @property
    def timeout_value(self) -> float:
        return self._timeout

    @property
    def operation(self) -> str:
        return self._operation
