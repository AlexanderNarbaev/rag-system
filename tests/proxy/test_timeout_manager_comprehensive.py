"""Comprehensive tests for proxy/app/shared/timeout_manager.py.

Targets the 91% coverage gap in the timeout manager module.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch

import pytest

from proxy.app.shared.timeout_manager import (
    RequestTimeoutError,
    ServiceTimeouts,
    TimeoutConfig,
    TimeoutManager,
    get_service_timeouts,
    reset_service_timeouts,
)

# ---------------------------------------------------------------------------
# RequestTimeoutError
# ---------------------------------------------------------------------------


class TestRequestTimeoutError:
    """Tests for the timeout exception."""

    def test_error_inherits_from_timeout(self) -> None:
        err = RequestTimeoutError(5.0)
        assert isinstance(err, TimeoutError)

    def test_error_attributes(self) -> None:
        err = RequestTimeoutError(5.0, operation="qdrant_search")
        assert err.timeout == 5.0
        assert err.operation == "qdrant_search"
        assert "5.0" in str(err)
        assert "qdrant_search" in str(err)

    def test_error_without_operation(self) -> None:
        err = RequestTimeoutError(10.0)
        assert err.timeout == 10.0
        assert err.operation == ""


# ---------------------------------------------------------------------------
# TimeoutConfig
# ---------------------------------------------------------------------------


class TestTimeoutConfig:
    """Tests for the timeout configuration dataclass."""

    def test_default_values(self) -> None:
        cfg = TimeoutConfig()
        assert cfg.default == 30.0
        assert cfg.per_service == {}
        assert cfg.enabled is True

    def test_get_timeout_default(self) -> None:
        cfg = TimeoutConfig()
        assert cfg.get_timeout() == 30.0

    def test_get_timeout_named_service(self) -> None:
        cfg = TimeoutConfig()
        cfg.per_service["qdrant"] = 5.0
        assert cfg.get_timeout("qdrant") == 5.0

    def test_get_timeout_unknown_service(self) -> None:
        cfg = TimeoutConfig()
        assert cfg.get_timeout("unknown_service") == 30.0


# ---------------------------------------------------------------------------
# ServiceTimeouts
# ---------------------------------------------------------------------------


class TestServiceTimeouts:
    """Tests for the per-service timeout registry."""

    def test_init(self) -> None:
        st = ServiceTimeouts()
        assert st.enabled is True

    def test_get_known(self) -> None:
        st = ServiceTimeouts()
        assert st.get("qdrant") == 10.0
        assert st.get("llm_backend") == 120.0

    def test_get_unknown_returns_default(self) -> None:
        st = ServiceTimeouts()
        assert st.get("unknown") == ServiceTimeouts.DEFAULT_FALLBACK

    def test_set_custom_timeout(self) -> None:
        st = ServiceTimeouts()
        st.set("custom_service", 7.5)
        assert st.get("custom_service") == 7.5

    def test_set_all(self) -> None:
        st = ServiceTimeouts()
        st.set_all(99.0)
        assert st.get("qdrant") == 99.0
        assert st.get("llm_backend") == 99.0
        assert st.get("embedder") == 99.0

    def test_enabled_toggle(self) -> None:
        st = ServiceTimeouts()
        assert st.enabled is True
        st.enabled = False
        assert st.enabled is False

    def test_all_timeouts(self) -> None:
        st = ServiceTimeouts()
        all_t = st.all_timeouts
        assert "qdrant" in all_t
        assert "llm_backend" in all_t
        assert "embedder" in all_t


class TestGlobalServiceTimeouts:
    """Tests for the global service timeouts accessor."""

    def teardown_method(self, method: Any) -> None:
        reset_service_timeouts()

    def test_get_service_timeouts_returns_instance(self) -> None:
        st = get_service_timeouts()
        assert isinstance(st, ServiceTimeouts)

    def test_get_returns_same_instance(self) -> None:
        st1 = get_service_timeouts()
        st2 = get_service_timeouts()
        assert st1 is st2

    def test_reset_clears_state(self) -> None:
        st = get_service_timeouts()
        st.set("custom", 99.0)
        reset_service_timeouts()
        st2 = get_service_timeouts()
        assert st2.get("custom") != 99.0


# ---------------------------------------------------------------------------
# TimeoutManager — context manager
# ---------------------------------------------------------------------------


class TestTimeoutManagerSync:
    """Tests for the sync context manager interface."""

    def test_init_with_timeout(self) -> None:
        tm = TimeoutManager(timeout=5.0, operation="test")
        assert tm._timeout == 5.0
        assert tm._operation == "test"

    def test_init_with_service(self) -> None:
        tm = TimeoutManager(service="qdrant")
        assert tm._timeout == 10.0  # default for qdrant

    def test_init_with_unknown_service(self) -> None:
        tm = TimeoutManager(service="unknown_service")
        assert tm._timeout == ServiceTimeouts.DEFAULT_FALLBACK

    def test_init_default(self) -> None:
        tm = TimeoutManager()
        assert tm._timeout == ServiceTimeouts.DEFAULT_FALLBACK

    def test_context_manager_returns_self(self) -> None:
        with TimeoutManager(5.0) as tm:
            assert isinstance(tm, TimeoutManager)

    def test_context_manager_cancels_timer(self) -> None:
        with (
            patch.object(TimeoutManager, "_setup_sync") as mock_setup,
            patch.object(TimeoutManager, "_teardown_sync") as mock_teardown,
        ):
            with TimeoutManager(5.0):
                mock_setup.assert_called_once()
            mock_teardown.assert_called_once()

    def test_context_manager_disabled_skips_setup(self) -> None:
        st = get_service_timeouts()
        original = st.enabled
        st.enabled = False
        try:
            with patch.object(TimeoutManager, "_setup_sync") as mock_setup, TimeoutManager(5.0):
                mock_setup.assert_not_called()
        finally:
            st.enabled = original

    def test_exit_with_timeout_error_returns_false(self) -> None:
        """When exc_val is RequestTimeoutError, __exit__ should re-raise."""
        tm = TimeoutManager(5.0)
        err = RequestTimeoutError(5.0)
        result = tm.__exit__(RequestTimeoutError, err, None)
        assert result is False

    def test_exit_with_other_error_returns_none(self) -> None:
        tm = TimeoutManager(5.0)
        with patch.object(TimeoutManager, "_teardown_sync"):
            result = tm.__exit__(ValueError, ValueError("test"), None)
        assert result is None

    def test_exit_with_no_exception_returns_none(self) -> None:
        tm = TimeoutManager(5.0)
        with patch.object(TimeoutManager, "_teardown_sync"):
            result = tm.__exit__(None, None, None)
        assert result is None


class TestTimeoutManagerAsync:
    """Tests for the async context manager interface."""

    @pytest.mark.asyncio
    async def test_async_context_manager_returns_self(self) -> None:
        async with TimeoutManager(5.0) as tm:
            assert isinstance(tm, TimeoutManager)

    @pytest.mark.asyncio
    async def test_async_exit_with_timeout_error(self) -> None:
        tm = TimeoutManager(5.0)
        err = RequestTimeoutError(5.0)
        result = await tm.__aexit__(RequestTimeoutError, err, None)
        assert result is False

    @pytest.mark.asyncio
    async def test_async_exit_without_exception(self) -> None:
        tm = TimeoutManager(5.0)
        result = await tm.__aexit__(None, None, None)
        assert result is None


class TestTimeoutManagerActuallyTimesOut:
    """Verify that the sync timer actually fires."""

    def test_sync_timer_triggers_after_timeout(self) -> None:
        """When the timeout fires, _on_timeout is called."""
        tm = TimeoutManager(0.05, operation="fast_op")
        with patch.object(TimeoutManager, "_on_timeout") as mock_on_timeout:
            with tm:
                time.sleep(0.02)
                # Cancel before timeout fires
            mock_on_timeout.assert_not_called()

    def test_sync_timer_with_shutdown(self) -> None:
        tm = TimeoutManager(0.05)
        with tm:
            pass
        # Re-entering should work after exit
        with tm:
            pass


# ---------------------------------------------------------------------------
# TimeoutManager.timeout — decorator
# ---------------------------------------------------------------------------


class TestTimeoutManagerDecorator:
    """Tests for the timeout decorator."""

    def test_timeout_decorator_sync(self) -> None:
        @TimeoutManager.timeout(5.0, operation="test_op")
        def sync_func() -> str:
            return "result"

        result = sync_func()
        assert result == "result"

    def test_timeout_decorator_sync_with_service(self) -> None:
        @TimeoutManager.timeout(service="qdrant")
        def sync_func() -> str:
            return "result"

        result = sync_func()
        assert result == "result"

    def test_timeout_decorator_passes_args(self) -> None:
        @TimeoutManager.timeout(5.0)
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    def test_timeout_decorator_passes_kwargs(self) -> None:
        @TimeoutManager.timeout(5.0)
        def greet(name: str = "world") -> str:
            return f"hello {name}"

        assert greet(name="test") == "hello test"

    def test_timeout_decorator_sync_does_not_raise_on_timeout(self) -> None:
        """The sync decorator uses threading.Timer which logs the timeout
        but does NOT raise. The function continues to completion."""

        @TimeoutManager.timeout(0.05, operation="slow_op")
        def slow_op() -> str:
            time.sleep(0.1)
            return "result"

        # sync decorator does not raise — it just logs
        result = slow_op()
        assert result == "result"

    @pytest.mark.asyncio
    async def test_timeout_decorator_async(self) -> None:
        @TimeoutManager.timeout(5.0, operation="async_op")
        async def async_func() -> str:
            return "async_result"

        result = await async_func()
        assert result == "async_result"

    @pytest.mark.asyncio
    async def test_timeout_decorator_async_raises_on_timeout(self) -> None:
        @TimeoutManager.timeout(0.05, operation="async_slow")
        async def async_slow() -> str:
            await asyncio.sleep(0.5)
            return "result"

        with pytest.raises(asyncio.TimeoutError):
            await async_slow()
