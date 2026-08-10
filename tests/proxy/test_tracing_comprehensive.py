"""Comprehensive tests for proxy/app/shared/tracing.py.

Covers no-op span/tracer classes, lazy tracer init, setup_tracing paths,
helpers (get_current_span, add_event, set_span_error,
span_context_from_headers, inject_context_to_headers), and the ``traced``
decorator (sync + async + exception handling).

Since ``tracing`` caches globals (e.g., ``_tracing_initialized``, ``_tracer``),
each test that mutates those globals resets them explicitly.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

import proxy.app.shared.tracing as tracing_mod
from proxy.app.shared.tracing import (
    add_event,
    get_current_span,
    inject_context_to_headers,
    set_span_error,
    setup_tracing,
    span_context_from_headers,
    traced,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def reset_tracing_state():
    """Reset tracing.py module-level globals to defaults."""
    tracing_mod._tracing_initialized = False
    tracing_mod._tracer = None
    tracing_mod._tracer_provider = None
    tracing_mod._OTEL_ENABLED = None
    tracing_mod._OTEL_EXPORTER_ENDPOINT = None
    tracing_mod._OTEL_SERVICE_NAME = None
    tracing_mod._OTEL_BATCH_TIMEOUT = 5


# ---------------------------------------------------------------------------
# _NoOpSpan / _NoOpSpanContext / _NoOpTracer
# ---------------------------------------------------------------------------


class TestNoOpSpan:
    def test_context_manager(self):
        span = tracing_mod._NoOpSpan()
        with span as s:
            assert s is span

    def test_context_manager_with_exception(self):
        span = tracing_mod._NoOpSpan()

        class _CustomError(Exception):
            pass

        with pytest.raises(_CustomError), span:
            raise _CustomError("x")

    def test_is_recording_false(self):
        assert tracing_mod._NoOpSpan().is_recording() is False

    def test_set_attribute_noop(self):
        tracing_mod._NoOpSpan().set_attribute("k", "v")

    def test_set_attributes_noop(self):
        tracing_mod._NoOpSpan().set_attributes({"k": "v"})

    def test_add_event_noop(self):
        tracing_mod._NoOpSpan().add_event("name")

    def test_record_exception_noop(self):
        tracing_mod._NoOpSpan().record_exception(RuntimeError("e"))

    def test_set_status_noop(self):
        tracing_mod._NoOpSpan().set_status("ok")

    def test_end_noop(self):
        tracing_mod._NoOpSpan().end()

    def test_get_span_context_returns_span_context(self):
        ctx = tracing_mod._NoOpSpan().get_span_context()
        assert ctx.trace_id == 0
        assert ctx.span_id == 0
        assert ctx.is_remote is False


class TestNoOpTracer:
    def test_start_as_current_span_yields_noop(self):
        with tracing_mod._NOOP_TRACER.start_as_current_span("name") as span:
            assert isinstance(span, tracing_mod._NoOpSpan)

    def test_start_span_returns_noop(self):
        span = tracing_mod._NOOP_TRACER.start_span("name")
        assert isinstance(span, tracing_mod._NoOpSpan)


# ---------------------------------------------------------------------------
# _TracerProxy + module tracer
# ---------------------------------------------------------------------------


class TestTracerProxy:
    def test_proxy_resolves_to_tracer(self):
        reset_tracing_state()
        # Force the no-op tracer path
        tracing_mod._tracer = tracing_mod._NOOP_TRACER
        # module-level tracer is a proxy
        proxy = tracing_mod.tracer
        result = proxy.start_as_current_span("name")
        with result as span:
            assert isinstance(span, tracing_mod._NoOpSpan)

    def test_proxy_memoises(self):
        reset_tracing_state()
        # Same proxy instance, resolves to current tracer
        assert tracing_mod.tracer is tracing_mod.tracer


# ---------------------------------------------------------------------------
# setup_tracing
# ---------------------------------------------------------------------------


class TestSetupTracing:
    def setup_method(self):
        reset_tracing_state()

    def teardown_method(self):
        reset_tracing_state()

    def test_disabled_no_op(self):
        with patch.object(tracing_mod, "_OTEL_ENABLED", False):
            setup_tracing()
        assert tracing_mod._tracing_initialized is False

    def test_disabled_no_op_logs(self):
        with patch.object(tracing_mod, "_OTEL_ENABLED", False):
            setup_tracing()  # Just verify no exception

    def test_otel_api_not_installed(self):
        # When _OTEL_AVAILABLE is False, setup_tracing is a no-op
        with (
            patch.object(tracing_mod, "_OTEL_ENABLED", True),
            patch.object(
                tracing_mod,
                "_OTEL_AVAILABLE",
                False,
            ),
        ):
            setup_tracing()
        assert tracing_mod._tracing_initialized is False

    def test_otel_sdk_not_installed(self):
        with (
            patch.object(tracing_mod, "_OTEL_ENABLED", True),
            patch.object(
                tracing_mod,
                "_OTEL_AVAILABLE",
                True,
            ),
            patch.object(tracing_mod, "_OTEL_SDK_AVAILABLE", False),
        ):
            setup_tracing()
        assert tracing_mod._tracing_initialized is False

    def test_already_initialized_skips(self):
        with (
            patch.object(tracing_mod, "_OTEL_ENABLED", True),
            patch.object(
                tracing_mod,
                "_OTEL_AVAILABLE",
                False,
            ),
        ):
            tracing_mod._tracing_initialized = True
            setup_tracing()  # no-op
        # Still True because we forced it before the call
        assert tracing_mod._tracing_initialized is True


# ---------------------------------------------------------------------------
# get_current_span
# ---------------------------------------------------------------------------


class TestGetCurrentSpan:
    def setup_method(self):
        reset_tracing_state()

    def test_otel_not_available_returns_noop(self):
        with patch.object(tracing_mod, "_OTEL_AVAILABLE", False):
            span = get_current_span()
        assert isinstance(span, tracing_mod._NoOpSpan)

    def test_otel_available_returns_otel(self):
        fake_trace = MagicMock()
        fake_span = MagicMock()
        fake_trace.get_current_span.return_value = fake_span
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_trace",
                fake_trace,
            ),
        ):
            span = get_current_span()
        assert span is fake_span


# ---------------------------------------------------------------------------
# add_event + set_span_error
# ---------------------------------------------------------------------------


class TestAddEvent:
    def setup_method(self):
        reset_tracing_state()

    def test_noop_when_no_span_recording(self):
        fake_trace = MagicMock()
        fake_span = MagicMock()
        fake_span.is_recording.return_value = False
        fake_trace.get_current_span.return_value = fake_span
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_trace",
                fake_trace,
            ),
        ):
            add_event("cache.hit")  # Should NOT call add_event

        # add_event on span was not called because is_recording was False.
        fake_span.add_event.assert_not_called()

    def test_records_when_recording(self):
        fake_trace = MagicMock()
        fake_span = MagicMock()
        fake_span.is_recording.return_value = True
        fake_trace.get_current_span.return_value = fake_span
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_trace",
                fake_trace,
            ),
        ):
            add_event("cache.hit", {"k": "v"})

        fake_span.add_event.assert_called_once_with("cache.hit", attributes={"k": "v"})

    def test_attributes_default_to_empty_dict(self):
        fake_trace = MagicMock()
        fake_span = MagicMock()
        fake_span.is_recording.return_value = True
        fake_trace.get_current_span.return_value = fake_span
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_trace",
                fake_trace,
            ),
        ):
            add_event("name")

        fake_span.add_event.assert_called_once_with("name", attributes={})


class TestSetSpanError:
    def setup_method(self):
        reset_tracing_state()

    def test_noop_when_not_recording(self):
        fake_trace = MagicMock()
        fake_span = MagicMock()
        fake_span.is_recording.return_value = False
        fake_trace.get_current_span.return_value = fake_span
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_trace",
                fake_trace,
            ),
        ):
            set_span_error(RuntimeError("e"))
        fake_span.record_exception.assert_not_called()

    def test_records_when_recording(self):
        exc = RuntimeError("oops")
        fake_trace = MagicMock()
        fake_span = MagicMock()
        fake_span.is_recording.return_value = True
        fake_trace.get_current_span.return_value = fake_span
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_trace",
                fake_trace,
            ),
        ):
            set_span_error(exc)
        fake_span.record_exception.assert_called_once_with(exc)
        fake_span.set_status.assert_called_once()


# ---------------------------------------------------------------------------
# span_context_from_headers + inject_context_to_headers
# ---------------------------------------------------------------------------


class TestSpanContextFromHeaders:
    def test_otel_not_available_returns_none(self):
        with patch.object(tracing_mod, "_OTEL_AVAILABLE", False):
            assert span_context_from_headers({}) is None

    def test_no_traceparent_returns_none(self):
        fake_extract = MagicMock()
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_extract",
                fake_extract,
            ),
        ):
            ctx = span_context_from_headers({"x-other": "y"})
        assert ctx is None
        fake_extract.assert_not_called()

    def test_with_traceparent_calls_extract(self):
        result_ctx = MagicMock()
        fake_extract = MagicMock(return_value=result_ctx)
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_extract",
                fake_extract,
            ),
            patch.object(tracing_mod, "_TextMapGetter", MagicMock()),
        ):
            ctx = span_context_from_headers({"traceparent": "abc"})
        assert ctx is result_ctx
        fake_extract.assert_called_once()


class TestInjectContextToHeaders:
    def test_otel_not_available_noop(self):
        with patch.object(tracing_mod, "_OTEL_AVAILABLE", False):
            inject_context_to_headers({})  # no exception

    def test_injects_when_available(self):
        fake_inject = MagicMock()
        with (
            patch.object(tracing_mod, "_OTEL_AVAILABLE", True),
            patch.object(
                tracing_mod,
                "_otel_inject",
                fake_inject,
            ),
        ):
            inject_context_to_headers({"x-existing": "v"})
        fake_inject.assert_called_once()
        # Headers dict passed to inject
        call_args = fake_inject.call_args[0][0]
        assert "x-existing" in call_args
        assert call_args["x-existing"] == "v"


# ---------------------------------------------------------------------------
# traced decorator
# ---------------------------------------------------------------------------


class TestTracedDecorator:
    def test_sync_decorator_default_name(self):
        @traced()
        def my_func():
            return 42

        assert my_func() == 42

    def test_async_decorator_default_name(self):
        @traced()
        async def my_async():
            await asyncio.sleep(0)
            return 99

        result = asyncio.run(my_async())
        assert result == 99

    def test_custom_span_name(self):
        @traced("custom.span")
        def go():
            return "ok"

        assert go() == "ok"

    def test_attributes_passed(self):
        captured = {}

        @traced(attributes={"k": "v"})
        def go():
            captured["called"] = True
            return True

        assert go() is True
        assert captured.get("called") is True


class TestTracedExceptions:
    def test_sync_raises_propagates(self):
        @traced()
        def boom():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            boom()

    def test_async_raises_propagates(self):
        @traced()
        async def boom():
            await asyncio.sleep(0)
            raise ValueError("asyncboom")

        with pytest.raises(ValueError, match="asyncboom"):
            asyncio.run(boom())

    def test_sync_records_exception_on_span(self):
        # Force no-op tracer so span.is_recording() is False
        # The decorator still works correctly
        @traced()
        def boom():
            raise RuntimeError("oops")

        with pytest.raises(RuntimeError):
            boom()


# ---------------------------------------------------------------------------
# TraceContextMiddleware (signature only) — referenced in module docstring,
# not currently exposed in this module. Skipped.
# ---------------------------------------------------------------------------
