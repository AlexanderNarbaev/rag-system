import time
import threading
import logging
from .config import (
    FEDERATION_CIRCUIT_BREAKER_THRESHOLD,
    FEDERATION_CIRCUIT_BREAKER_RECOVERY_S,
)

logger = logging.getLogger("federation")

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_s: int = 30,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self._state = CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._recovery_deadline: float = 0.0
        self._lock = threading.Lock()

    def _transition_to_open(self) -> None:
        self._state = OPEN
        self._recovery_deadline = time.monotonic() + self.recovery_timeout_s

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == OPEN and time.monotonic() >= self._recovery_deadline:
                self._state = HALF_OPEN
                logger.info(f"Breaker '{self.name}' → HALF_OPEN")
            return self._state

    def allow_request(self) -> bool:
        return self.state != OPEN

    def record_success(self) -> None:
        with self._lock:
            if self._state == HALF_OPEN:
                self._state = CLOSED
                self._failure_count = 0
                logger.info(f"Breaker '{self.name}' → CLOSED (half-open success)")
            self._success_count += 1
            if self._success_count >= self.failure_threshold:
                self._failure_count = 0
                self._success_count = 0

    def record_failure(self) -> None:
        with self._lock:
            if self._state == OPEN:
                if time.monotonic() >= self._recovery_deadline:
                    self._state = HALF_OPEN

            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.monotonic()

            if self._state == HALF_OPEN:
                self._transition_to_open()
                logger.warning(f"Breaker '{self.name}' → OPEN (half-open failure)")
            elif self._failure_count >= self.failure_threshold and self._state == CLOSED:
                self._transition_to_open()
                logger.warning(f"Breaker '{self.name}' → OPEN ({self._failure_count} failures)")


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(name: str) -> CircuitBreaker:
    with _breakers_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=FEDERATION_CIRCUIT_BREAKER_THRESHOLD,
                recovery_timeout_s=FEDERATION_CIRCUIT_BREAKER_RECOVERY_S,
            )
        return _breakers[name]
