import time
from federation.app.circuit_breaker import CircuitBreaker, get_breaker


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout_s=30)
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout_s=30)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

    def test_half_open_after_recovery_timeout(self, monkeypatch):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"

        monkeypatch.setattr(time, "monotonic", lambda: cb._last_failure_time + 2.0)
        assert cb.state == "HALF_OPEN"
        assert cb.allow_request() is True

    def test_half_open_success_closes_circuit(self, monkeypatch):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"

        monkeypatch.setattr(time, "monotonic", lambda: cb._last_failure_time + 2.0)
        assert cb.allow_request() is True
        cb.record_success()
        assert cb.state == "CLOSED"

    def test_half_open_failure_opens_again(self, monkeypatch):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=1)
        cb.record_failure()
        cb.record_failure()

        monkeypatch.setattr(time, "monotonic", lambda: cb._last_failure_time + 2.0)
        cb.record_failure()
        assert cb.state == "OPEN"

    def test_successes_reset_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=5, recovery_timeout_s=30)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        assert cb.state == "CLOSED"


class TestGetBreaker:
    def test_returns_same_breaker_for_same_name(self):
        b1 = get_breaker("silo_hr")
        b2 = get_breaker("silo_hr")
        assert b1 is b2

    def test_returns_different_breaker_for_different_name(self):
        b1 = get_breaker("silo_hr")
        b2 = get_breaker("silo_eng")
        assert b1 is not b2
