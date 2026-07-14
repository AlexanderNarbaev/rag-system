# proxy/app/circuit_breaker.py
"""
Circuit breaker pattern for external service calls with Prometheus metrics.

Protects against cascading failures by opening the circuit after N consecutive
failures, then testing recovery via half-open state after a cooldown period.

States:
    CLOSED    — Normal operation, calls pass through.
    OPEN      — Circuit is open, calls are rejected immediately.
    HALF_OPEN  — Testing recovery, limited calls allowed.

Uses only standard library (asyncio, time, enum) — no external dependencies.
Exports Prometheus metrics: circuit_breaker_state{name}, circuit_breaker_failures_total{name}.
"""

import inspect
import logging
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import prometheus_client
from prometheus_client import Counter, Gauge

logger = logging.getLogger (__name__)


# ── Prometheus metrics ──────────────────────────────────────────────────────

# Prometheus metrics must be resilient to duplicate registration when the
# module is imported via different package paths in tests
# (e.g., `app.circuit_breaker` vs `proxy.app.circuit_breaker`).
# We check whether the metric name is already registered before creating it.


def _register_metric (metric_cls: Any, name: str, documentation: str, labelnames: list [str] | None = None) -> Any:
  """Register a Prometheus metric, reusing an existing one if already present."""
  registry = prometheus_client.REGISTRY
  # Check if metric name is already registered via any collector
  for collector in list (registry._collector_to_names):  # noqa: SLF001
    try:
      existing_names = registry._get_names (collector)  # type: ignore[no-untyped-call]  # noqa: SLF001
    except Exception:
      continue
    if name in existing_names and isinstance (collector, metric_cls):
      logger.debug ("Reusing existing metric: %s", name)
      return collector
  return metric_cls (name, documentation, labelnames or [])


circuit_breaker_state = _register_metric (Gauge, "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)", ["name"], )

circuit_breaker_failures_total = _register_metric (Counter, "circuit_breaker_failures_total",
    "Total number of failures per circuit breaker", ["name"], )


class State (StrEnum):
  """Circuit breaker states."""
  
  CLOSED = "closed"
  OPEN = "open"
  HALF_OPEN = "half_open"
  
  @property
  def metric_value (self) -> int:
    """Map state to numeric value for Prometheus gauge."""
    return {State.CLOSED: 0, State.OPEN: 1, State.HALF_OPEN: 2} [self]


class CircuitBreakerOpenError (Exception):
  """Raised when a call is rejected because the circuit is open."""
  
  def __init__ (self, name: str):
    self.name = name
    super ().__init__ (f"Circuit breaker '{name}' is OPEN — calls are rejected")


class CircuitBreaker:
  """Circuit breaker for external service calls with Prometheus metrics.

  Attributes:
      CLOSED (0): Normal operation — calls pass through.
      OPEN (1): Failing — calls are rejected immediately.
      HALF_OPEN (2): Testing recovery — limited calls allowed.
  """
  
  CLOSED = State.CLOSED
  OPEN = State.OPEN
  HALF_OPEN = State.HALF_OPEN
  
  def __init__ (
      self, name: str, failure_threshold: int = 5, cooldown_seconds: float = 30.0, half_open_max: int = 2, ):
    """Initialize a circuit breaker.

    Args:
        name: Unique service name (used for metrics labels).
        failure_threshold: Number of consecutive failures before opening.
        cooldown_seconds: Time to wait before transitioning from OPEN to HALF_OPEN.
        half_open_max: Maximum number of test calls allowed in HALF_OPEN state.
    """
    self.name = name
    self.failure_threshold = failure_threshold
    self.cooldown_seconds = cooldown_seconds
    self.half_open_max = half_open_max
    
    self._state = State.CLOSED
    self._failure_count = 0
    self._last_failure_time: float = 0.0
    self._half_open_calls = 0
    self._opened_at: float = 0.0
    
    # Publish initial gauge value
    circuit_breaker_state.labels (name = self.name).set (self._state.metric_value)
    logger.info ("Circuit breaker '%s' initialized: threshold=%d, cooldown=%.1fs, half_open_max=%d", self.name,
        self.failure_threshold, self.cooldown_seconds, self.half_open_max, )
  
  @property
  def state (self) -> State:
    """Current circuit breaker state (evaluated at access time).

    Automatically transitions from OPEN to HALF_OPEN if cooldown has elapsed.
    """
    self._maybe_transition ()
    return self._state
  
  @property
  def failure_count (self) -> int:
    """Current consecutive failure count."""
    return self._failure_count
  
  def _maybe_transition (self) -> None:
    """Check and perform state transitions based on time and failure counts.

    OPEN → HALF_OPEN: when cooldown period has elapsed.
    """
    if self._state == State.OPEN:
      elapsed = time.monotonic () - self._opened_at
      if elapsed >= self.cooldown_seconds:
        old_state = self._state
        self._state = State.HALF_OPEN
        self._half_open_calls = 0
        circuit_breaker_state.labels (name = self.name).set (self._state.metric_value)
        logger.info ("Circuit breaker '%s': %s → %s (cooldown %.1fs elapsed)", self.name, old_state, self._state,
            elapsed, )
  
  def _transition (self, new_state: State) -> None:
    """Manually transition to a new state with logging and metrics update."""
    old_state = self._state
    self._state = new_state
    circuit_breaker_state.labels (name = self.name).set (self._state.metric_value)
    logger.info ("Circuit breaker '%s': %s → %s (failures=%d)", self.name, old_state, self._state,
        self._failure_count, )
  
  def success (self) -> None:
    """Record a successful call — resets the failure count and closes the circuit."""
    self._failure_count = 0
    if self._state != State.CLOSED:
      self._transition (State.CLOSED)
  
  def failure (self) -> None:
    """Record a failed call — increments failure count, may open the circuit."""
    self._failure_count += 1
    self._last_failure_time = time.monotonic ()
    circuit_breaker_failures_total.labels (name = self.name).inc ()
    
    if self._state == State.HALF_OPEN:
      # Any failure in half-open immediately re-opens the circuit
      self._opened_at = time.monotonic ()
      self._transition (State.OPEN)
    elif self._state == State.CLOSED and self._failure_count >= self.failure_threshold:
      self._opened_at = time.monotonic ()
      self._transition (State.OPEN)
  
  def _check_and_enter (self) -> None:
    """Validate state and allow entry if circuit permits. Raises on rejection."""
    current_state = self.state  # triggers _maybe_transition
    
    if current_state == State.OPEN:
      raise CircuitBreakerOpenError (self.name)
    
    if current_state == State.HALF_OPEN:
      if self._half_open_calls >= self.half_open_max:
        raise CircuitBreakerOpenError (self.name)
      self._half_open_calls += 1
  
  def call_sync (self, fn: Callable [..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute fn(*args, **kwargs) with circuit breaker protection (synchronous).

    For use in synchronous code paths. The passed ``fn`` must be synchronous.

    Args:
        fn: The synchronous callable to execute under protection.
        *args: Positional arguments for fn.
        **kwargs: Keyword arguments for fn.

    Returns:
        The return value of fn(*args, **kwargs).

    Raises:
        CircuitBreakerOpenError: If the circuit is open and rejects the call.
        The original exception from fn if it fails.
    """
    self._check_and_enter ()
    try:
      result = fn (*args, **kwargs)
      self.success ()
      return result
    except Exception as e:
      if isinstance (e, CircuitBreakerOpenError):
        raise
      self.failure ()
      raise
  
  async def call (self, fn: Callable [..., Any], *args: Any, **kwargs: Any) -> Any:
    """Execute fn(*args, **kwargs) with circuit breaker protection (async).

    Supports both sync and async functions. Detects async functions
    via asyncio.iscoroutinefunction().

    Use ``call_sync()`` for synchronous call sites to avoid the need
    for ``asyncio.run()`` wrappers.

    Args:
        fn: The callable (sync or async) to execute under protection.
        *args: Positional arguments for fn.
        **kwargs: Keyword arguments for fn.

    Returns:
        The return value of fn(*args, **kwargs).

    Raises:
        CircuitBreakerOpenError: If the circuit is open and rejects the call.
        The original exception from fn if it fails.
    """
    self._check_and_enter ()
    try:
      if inspect.iscoroutinefunction (fn):
        result = await fn (*args, **kwargs)
      else:
        result = fn (*args, **kwargs)
      self.success ()
      return result
    except Exception as e:
      # Don't count CircuitBreakerOpenError as a failure
      if isinstance (e, CircuitBreakerOpenError):
        raise
      self.failure ()
      raise


# ── Module-level breaker registry ────────────────────────────────────────────

_breakers: dict [str, CircuitBreaker] = {}

# Frozen set to prevent registration after wiring is complete
_frozen: bool = False


def get_breaker (
    name: str, failure_threshold: int = 5, cooldown_seconds: float = 30.0, half_open_max: int = 2, ) -> CircuitBreaker:
  """Get or create a named circuit breaker.

  Args:
      name: Unique service name (e.g., "qdrant", "llm_backend", "reranker").
      failure_threshold: Consecutive failures before opening.
      cooldown_seconds: Seconds to wait before testing recovery.
      half_open_max: Max test calls in half-open state.

  Returns:
      The existing or newly created CircuitBreaker instance.
  """
  if name not in _breakers:
    _breakers [name] = CircuitBreaker (name = name, failure_threshold = failure_threshold,
        cooldown_seconds = cooldown_seconds, half_open_max = half_open_max, )
  return _breakers [name]


def get_all_breakers () -> dict [str, CircuitBreaker]:
  """Return a copy of all registered circuit breakers."""
  return dict (_breakers)


def reset_all_breakers () -> None:
  """Reset all circuit breakers to CLOSED state (for testing)."""
  for breaker in _breakers.values ():
    breaker._failure_count = 0  # noqa: SLF001
    breaker._half_open_calls = 0  # noqa: SLF001
    breaker._transition (State.CLOSED)
