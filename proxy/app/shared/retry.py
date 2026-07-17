# proxy/app/shared/retry.py
"""Centralized retry utility with configurable backoff and circuit breaker integration.

Provides:
    - async_retry() — retry an async callable with configurable backoff
    - sync_retry() — retry a sync callable with configurable backoff
    - RetryConfig — typed configuration for retry behavior
    - RetryExhaustedError — raised when all retries are exhausted
    - Integration with CircuitBreaker (records failures, checks state)

Backoff strategies: constant, linear, exponential (with optional jitter).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class BackoffStrategy(StrEnum):
    """Available backoff strategies."""

    CONSTANT = "constant"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_attempts: Total number of attempts (1 = no retry).
        base_delay: Base delay in seconds between retries.
        max_delay: Maximum delay cap in seconds.
        strategy: Backoff strategy (constant, linear, exponential).
        jitter: Whether to add random jitter (±25%) to delay.
        retryable_exceptions: Tuple of exception types that trigger retry.
            If None, all exceptions trigger retry.
        circuit_breaker_name: If set, integrates with the named circuit breaker.
        on_retry: Optional callback invoked before each retry attempt.
            Receives (attempt, exception, delay) as arguments.

    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = field(default_factory=tuple)
    circuit_breaker_name: str | None = None
    on_retry: Callable[[int, Exception, float], None] | None = None


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, attempts: int, last_error: Exception, operation: str = ""):
        self.attempts = attempts
        self.last_error = last_error
        self.operation = operation
        msg = f"All {attempts} retry attempts exhausted"
        if operation:
            msg += f" for '{operation}'"
        msg += f". Last error: {last_error!r}"
        super().__init__(msg)


def _compute_delay(attempt: int, config: RetryConfig) -> float:
    """Compute delay for the given attempt number (0-indexed)."""
    if config.strategy == BackoffStrategy.CONSTANT:
        delay = config.base_delay
    elif config.strategy == BackoffStrategy.LINEAR:
        delay = config.base_delay * (attempt + 1)
    else:  # EXPONENTIAL
        delay = config.base_delay * (2**attempt)

    delay = min(delay, config.max_delay)

    if config.jitter:
        delay *= random.uniform(0.75, 1.25)

    return delay


def _record_circuit_breaker(name: str, success: bool) -> None:
    """Record success/failure to the named circuit breaker."""
    try:
        from proxy.app.shared.circuit_breaker import get_breaker

        breaker = get_breaker(name)
        if success:
            breaker.success()
        else:
            breaker.failure()
    except (ImportError, Exception):
        pass


def _is_retryable(exc: Exception, config: RetryConfig) -> bool:
    """Check if an exception should trigger a retry."""
    if not config.retryable_exceptions:
        return True
    return isinstance(exc, config.retryable_exceptions)


async def async_retry[T](
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> T:
    """Execute an async function with retry on failure.

    Args:
        fn: The async callable to execute.
        *args: Positional arguments for fn.
        config: Retry configuration. Uses defaults if None.
        **kwargs: Keyword arguments for fn.

    Returns:
        The return value of fn(*args, **kwargs).

    Raises:
        RetryExhaustedError: If all attempts are exhausted.
        CircuitBreakerOpenError: If the circuit breaker is open (pre-flight check).

    Example:
        >>> result = await async_retry(
        ...     fetch_data, "param1",
        ...     config=RetryConfig(max_attempts=3, base_delay=1.0),
        ... )

    """
    if config is None:
        config = RetryConfig()

    # Pre-flight circuit breaker check
    _cboe_cls: Any = None
    if config.circuit_breaker_name:
        try:
            from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError as CBOE  # noqa: N817
            from proxy.app.shared.circuit_breaker import get_breaker

            _cboe_cls = CBOE
            breaker = get_breaker(config.circuit_breaker_name)
            if breaker.state.name == "OPEN":
                raise CBOE(f"Circuit breaker '{config.circuit_breaker_name}' is OPEN")
        except ImportError:
            pass
        except Exception as e:
            if _cboe_cls is not None and isinstance(e, _cboe_cls):
                raise

    last_error: Exception | None = None

    for attempt in range(config.max_attempts):
        try:
            result = await fn(*args, **kwargs)
            if config.circuit_breaker_name:
                _record_circuit_breaker(config.circuit_breaker_name, success=True)
            return result
        except Exception as e:
            last_error = e
            if config.circuit_breaker_name:
                _record_circuit_breaker(config.circuit_breaker_name, success=False)

            if not _is_retryable(e, config):
                logger.debug("Non-retryable exception: %r", e)
                raise

            if attempt < config.max_attempts - 1:
                delay = _compute_delay(attempt, config)
                if config.on_retry:
                    config.on_retry(attempt, e, delay)
                logger.warning(
                    "Retry attempt %d/%d failed: %r. Retrying in %.2fs...",
                    attempt + 1,
                    config.max_attempts,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All %d retry attempts exhausted. Last error: %r",
                    config.max_attempts,
                    e,
                )
                raise RetryExhaustedError(
                    config.max_attempts,
                    last_error,
                    operation=getattr(fn, "__name__", str(fn)),
                ) from e

    # This line should be unreachable but keeps type checker happy
    raise RetryExhaustedError(config.max_attempts, last_error or RuntimeError("unknown"))


def sync_retry[T](
    fn: Callable[..., T],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> T:
    """Execute a sync function with retry on failure.

    Args:
        fn: The sync callable to execute.
        *args: Positional arguments for fn.
        config: Retry configuration. Uses defaults if None.
        **kwargs: Keyword arguments for fn.

    Returns:
        The return value of fn(*args, **kwargs).

    Raises:
        RetryExhaustedError: If all attempts are exhausted.

    Example:
        >>> result = sync_retry(
        ...     connect_db, host="localhost",
        ...     config=RetryConfig(max_attempts=5, base_delay=2.0),
        ... )

    """
    if config is None:
        config = RetryConfig()

    # Pre-flight circuit breaker check
    _cboe_cls: Any = None
    if config.circuit_breaker_name:
        try:
            from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError as CBOE  # noqa: N817
            from proxy.app.shared.circuit_breaker import get_breaker

            _cboe_cls = CBOE
            breaker = get_breaker(config.circuit_breaker_name)
            if breaker.state.name == "OPEN":
                raise CBOE(f"Circuit breaker '{config.circuit_breaker_name}' is OPEN")
        except ImportError:
            pass
        except Exception as e:
            if _cboe_cls is not None and isinstance(e, _cboe_cls):
                raise

    last_error: Exception | None = None

    for attempt in range(config.max_attempts):
        try:
            result = fn(*args, **kwargs)
            if config.circuit_breaker_name:
                _record_circuit_breaker(config.circuit_breaker_name, success=True)
            return result
        except Exception as e:
            last_error = e
            if config.circuit_breaker_name:
                _record_circuit_breaker(config.circuit_breaker_name, success=False)

            if not _is_retryable(e, config):
                logger.debug("Non-retryable exception: %r", e)
                raise

            if attempt < config.max_attempts - 1:
                delay = _compute_delay(attempt, config)
                if config.on_retry:
                    config.on_retry(attempt, e, delay)
                logger.warning(
                    "Retry attempt %d/%d failed: %r. Retrying in %.2fs...",
                    attempt + 1,
                    config.max_attempts,
                    e,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "All %d retry attempts exhausted. Last error: %r",
                    config.max_attempts,
                    e,
                )
                raise RetryExhaustedError(
                    config.max_attempts,
                    last_error,
                    operation=getattr(fn, "__name__", str(fn)),
                ) from e

    raise RetryExhaustedError(config.max_attempts, last_error or RuntimeError("unknown"))
