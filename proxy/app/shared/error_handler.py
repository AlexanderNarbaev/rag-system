# proxy/app/error_handler.py
"""
Circuit breaker and resilience patterns for external service calls.
Provides:
- CircuitBreaker: open/half-open/closed state machine
- GracefulDegradation: fallback chains per service
- with_circuit_breaker: decorator for circuit breaker protection
- with_retry: decorator for exponential backoff retry
- with_fallback: decorator for graceful fallback
"""

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerError(Exception):
    pass


class CircuitBreaker:
    """Circuit breaker for external service calls."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_attempts = 0
        self._last_state_change: float = time.monotonic()

    @property
    def state(self) -> CircuitState:
        self._transition_if_needed()
        return self._state

    def _transition_if_needed(self):
        now = time.monotonic()
        if self._state == CircuitState.OPEN:  # noqa: SIM102
            if now - self._last_state_change >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_attempts = 0
                self._last_state_change = now
                logger.info(f"Circuit {self.name}: OPEN -> HALF_OPEN")

    def record_success(self):
        self._transition_if_needed()
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_attempts += 1
            if self._half_open_attempts >= self.half_open_max:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._last_state_change = time.monotonic()
                logger.info(f"Circuit {self.name}: HALF_OPEN -> CLOSED (recovered)")
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0

    def record_failure(self):
        self._transition_if_needed()
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._last_state_change = time.monotonic()
            logger.warning(f"Circuit {self.name}: HALF_OPEN -> OPEN (failed test)")
        elif self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._last_state_change = time.monotonic()
            logger.warning(f"Circuit {self.name}: CLOSED -> OPEN ({self._failure_count} failures)")

    def allow_request(self) -> bool:
        self._transition_if_needed()
        return self._state != CircuitState.OPEN


class GracefulDegradation:
    """Defines fallback chains for each service."""

    DEGRADATION_MATRIX = {
        "retrieval": ["hybrid_search", "dense_only", "keyword_only", "no_context"],
        "rerank": ["cross_encoder", "score_sort", "no_rerank"],
        "llm": ["primary_llm", "fallback_llm", "static_response"],
        "graph": ["neo4j", "cache", "no_graph"],
        "cache": ["redis", "memory", "no_cache"],
    }

    @classmethod
    def get_fallback_chain(cls, service_name: str) -> list:
        return cls.DEGRADATION_MATRIX.get(service_name, ["noop"])

    @classmethod
    def get_degradation_level(cls, service_name: str, strategy: str) -> int:
        chain = cls.get_fallback_chain(service_name)
        try:
            return chain.index(strategy)
        except ValueError:
            return len(chain)


_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    if service_name not in _circuit_breakers:
        _circuit_breakers[service_name] = CircuitBreaker(name=service_name)
    return _circuit_breakers[service_name]


def with_circuit_breaker(service_name: str):
    """Decorator for circuit breaker protection."""

    def decorator(func: Callable) -> Callable:
        breaker = get_circuit_breaker(service_name)

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not breaker.allow_request():
                raise CircuitBreakerError(f"Circuit {service_name} is OPEN")
            try:
                result = await func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception:
                breaker.record_failure()
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not breaker.allow_request():
                raise CircuitBreakerError(f"Circuit {service_name} is OPEN")
            try:
                result = func(*args, **kwargs)
                breaker.record_success()
                return result
            except Exception:
                breaker.record_failure()
                raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def with_retry(max_retries: int = 3, backoff_factor: float = 1.0, exceptions: tuple = (Exception,)):
    """Decorator for exponential backoff retry."""

    def decorator(func: Callable) -> Callable:

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = backoff_factor * (2**attempt)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}. Waiting {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
            if last_exception is not None:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without raising an exception")

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = backoff_factor * (2**attempt)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}. Waiting {delay:.1f}s"
                        )
                        time.sleep(delay)
            if last_exception is not None:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without raising an exception")

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def with_fallback(fallback_func: Callable):
    """Decorator for graceful fallback."""

    def decorator(func: Callable) -> Callable:

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Primary function {func.__name__} failed: {e}. Using fallback.")
                if inspect.iscoroutinefunction(fallback_func):
                    return await fallback_func(*args, **kwargs)
                return fallback_func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Primary function {func.__name__} failed: {e}. Using fallback.")
                if inspect.iscoroutinefunction(fallback_func):
                    return asyncio.run(fallback_func(*args, **kwargs))
                return fallback_func(*args, **kwargs)

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def reset_all_circuit_breakers():
    _circuit_breakers.clear()
