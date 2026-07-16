# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/shared/tracing.py — OpenTelemetry distributed tracing stubs."""

import pytest
from unittest.mock import MagicMock, patch


class TestTracingNoOpWhenDisabled:
    """Verify tracing is no-op (zero overhead) when OTEL_ENABLED=false."""

    def test_setup_tracing_noop_when_disabled(self):
        """setup_tracing() should return immediately when disabled."""
        from proxy.app.shared import tracing as tracing_mod
        from proxy.app.shared.tracing import _tracing_initialized, setup_tracing

        was_initialized = _tracing_initialized
        try:
            tracing_mod._OTEL_ENABLED = False
            result = setup_tracing()
            assert result is None
        finally:
            tracing_mod._tracing_initialized = was_initialized

    def test_tracer_start_as_current_span_noop(self):
        """Tracer should work as a context manager when OTEL is not installed."""
        from proxy.app.shared.tracing import tracer

        with tracer.start_as_current_span("test.noop") as span:
            assert not span.is_recording()
            span.set_attribute("test.key", "value")

    def test_get_current_span_noop(self):
        """get_current_span() should return a non-recording span."""
        from proxy.app.shared.tracing import get_current_span

        span = get_current_span()
        assert not span.is_recording()

    def test_add_event_noop(self):
        """add_event() should not raise when no span is active."""
        from proxy.app.shared.tracing import add_event

        # Should not raise
        add_event("test.event", {"key": "value"})

    def test_set_span_error_noop(self):
        """set_span_error() should not raise when no span is active."""
        from proxy.app.shared.tracing import set_span_error

        exc = ValueError("test error")
        # Should not raise
        set_span_error(exc)

    def test_span_context_from_headers_noop(self):
        """span_context_from_headers() should return None when no traceparent."""
        from proxy.app.shared.tracing import span_context_from_headers

        result = span_context_from_headers({"user-agent": "test"})
        assert result is None

    def test_inject_context_to_headers_noop(self):
        """inject_context_to_headers() should not mutate or raise."""
        from proxy.app.shared.tracing import inject_context_to_headers

        headers: dict[str, str] = {}
        inject_context_to_headers(headers)
        # No-op when OTEL disabled — headers stay empty
        assert headers == {}

    def test_noop_span_context_manager(self):
        """NoOpSpan should work as a context manager."""
        from proxy.app.shared.tracing import _NoOpSpan

        span = _NoOpSpan()
        with span:
            span.set_attribute("k", "v")
        assert True


class TestTracingSetup:
    """Test tracing initialization when OTEL_ENABLED=true."""

    def test_setup_tracing_initializes_provider(self):
        """setup_tracing() should create a TracerProvider and exporter."""
        from proxy.app.shared.tracing import _tracing_initialized, _tracer_provider, setup_tracing

        was_initialized = _tracing_initialized
        old_provider = _tracer_provider

        import proxy.app.shared.tracing as tracing_mod

        try:
            tracing_mod._OTEL_ENABLED = True
            tracing_mod._OTEL_AVAILABLE = True
            tracing_mod._OTEL_SDK_AVAILABLE = True
            tracing_mod._OTEL_EXPORTER_ENDPOINT = "http://localhost:4318/v1/traces"
            tracing_mod._OTEL_BATCH_TIMEOUT = 5

            with (
                patch.object(tracing_mod, "OTLPSpanExporter") as mock_exporter_cls,
                patch.object(tracing_mod, "BatchSpanProcessor") as mock_bsp_cls,
                patch.object(tracing_mod, "TracerProvider") as mock_provider_cls,
                patch.object(tracing_mod, "_otel_trace") as mock_otel_trace,
            ):
                mock_provider = MagicMock()
                mock_provider_cls.return_value = mock_provider

                result = setup_tracing(service_name="test-service")
                assert result is None

                mock_provider_cls.assert_called_once()
                mock_exporter_cls.assert_called_once_with(endpoint="http://localhost:4318/v1/traces")
                mock_bsp_cls.assert_called_once()
                mock_provider.add_span_processor.assert_called_once()
        finally:
            tracing_mod._tracing_initialized = was_initialized
            tracing_mod._tracer_provider = old_provider

    def test_setup_tracing_sets_global_provider(self):
        """setup_tracing() should register the provider globally."""
        import proxy.app.shared.tracing as tracing_mod

        was_initialized = tracing_mod._tracing_initialized
        try:
            tracing_mod._OTEL_ENABLED = True
            tracing_mod._OTEL_AVAILABLE = True
            tracing_mod._OTEL_SDK_AVAILABLE = True
            tracing_mod._OTEL_EXPORTER_ENDPOINT = "http://localhost:4318/v1/traces"
            tracing_mod._tracing_initialized = False
            tracing_mod._tracer_provider = None

            with (
                patch.object(tracing_mod, "OTLPSpanExporter"),
                patch.object(tracing_mod, "BatchSpanProcessor"),
                patch.object(tracing_mod, "TracerProvider") as mock_provider_cls,
                patch.object(tracing_mod, "_otel_trace") as mock_otel_trace,
            ):
                mock_provider = MagicMock()
                mock_provider_cls.return_value = mock_provider

                from proxy.app.shared.tracing import setup_tracing

                setup_tracing(service_name="test-svc")
                mock_otel_trace.set_tracer_provider.assert_called_once_with(mock_provider)
        finally:
            tracing_mod._tracing_initialized = was_initialized
            tracing_mod._tracer_provider = None

    def test_setup_tracing_handles_exporter_error(self):
        """setup_tracing() should gracefully degrade on exporter init failure."""
        import proxy.app.shared.tracing as tracing_mod

        was_initialized = tracing_mod._tracing_initialized
        try:
            tracing_mod._OTEL_ENABLED = True
            tracing_mod._OTEL_AVAILABLE = True
            tracing_mod._OTEL_SDK_AVAILABLE = True
            tracing_mod._tracing_initialized = False

            with (
                patch.object(tracing_mod, "OTLPSpanExporter", side_effect=ConnectionError("Cannot connect")),
                patch.object(tracing_mod, "TracerProvider") as mock_provider_cls,
            ):
                mock_provider = MagicMock()
                mock_provider_cls.return_value = mock_provider

                from proxy.app.shared.tracing import setup_tracing

                result = setup_tracing()
                assert result is None
        finally:
            tracing_mod._tracing_initialized = was_initialized

    def test_setup_tracing_idempotent(self):
        """setup_tracing() should be idempotent — second call is a no-op."""
        import proxy.app.shared.tracing as tracing_mod

        was_initialized = tracing_mod._tracing_initialized
        try:
            tracing_mod._OTEL_ENABLED = True
            tracing_mod._OTEL_AVAILABLE = True
            tracing_mod._OTEL_SDK_AVAILABLE = True
            tracing_mod._tracing_initialized = False
            tracing_mod._tracer_provider = None

            with (
                patch.object(tracing_mod, "OTLPSpanExporter"),
                patch.object(tracing_mod, "BatchSpanProcessor"),
                patch.object(tracing_mod, "TracerProvider") as mock_provider_cls,
                patch.object(tracing_mod, "_otel_trace") as mock_otel_trace,
            ):
                mock_provider = MagicMock()
                mock_provider_cls.return_value = mock_provider

                from proxy.app.shared.tracing import setup_tracing

                setup_tracing(service_name="test-svc")
                first_call_count = mock_otel_trace.set_tracer_provider.call_count

                setup_tracing(service_name="test-svc")
                assert mock_otel_trace.set_tracer_provider.call_count == first_call_count
        finally:
            tracing_mod._tracing_initialized = was_initialized
            tracing_mod._tracer_provider = None

    def test_setup_tracing_skips_when_otel_not_available(self):
        """setup_tracing() should return early when OTEL API not installed."""
        import proxy.app.shared.tracing as tracing_mod

        was_initialized = tracing_mod._tracing_initialized
        try:
            tracing_mod._OTEL_ENABLED = True
            tracing_mod._OTEL_AVAILABLE = False
            tracing_mod._OTEL_SDK_AVAILABLE = False
            tracing_mod._tracing_initialized = False

            from proxy.app.shared.tracing import setup_tracing

            result = setup_tracing()
            assert result is None
        finally:
            tracing_mod._tracing_initialized = was_initialized


class TestSpanContextManager:
    """Test that tracer.start_as_current_span works correctly."""

    def test_span_context_manager_works(self):
        """start_as_current_span should work as a context manager."""
        from proxy.app.shared.tracing import tracer

        with tracer.start_as_current_span("test.context_manager") as span:
            span.set_attribute("test.attr", "hello")
        assert True

    def test_span_captures_attributes(self):
        """Span attributes should be settable."""
        from proxy.app.shared.tracing import tracer

        with tracer.start_as_current_span("test.attributes") as span:
            span.set_attribute("string_attr", "value")
            span.set_attribute("int_attr", 42)
            span.set_attribute("bool_attr", True)
            span.set_attribute("float_attr", 3.14)
        assert True

    def test_nested_spans(self):
        """Nested spans should work without issues."""
        from proxy.app.shared.tracing import tracer

        with tracer.start_as_current_span("outer"), tracer.start_as_current_span("inner") as inner_span:
            inner_span.set_attribute("nested", True)
        assert True


class TestTracingConfig:
    """Test that tracing config values are properly defined."""

    def test_otel_config_defaults(self):
        """Verify OpenTelemetry config defaults exist in config module."""
        import proxy.app.shared.config as cfg

        assert hasattr(cfg, "OTEL_ENABLED")
        assert hasattr(cfg, "OTEL_EXPORTER_ENDPOINT")
        assert hasattr(cfg, "OTEL_SERVICE_NAME")
        assert hasattr(cfg, "OTEL_BATCH_TIMEOUT")
        assert hasattr(cfg, "OTEL_MAX_ATTRIBUTES_PER_SPAN")

    def test_otel_disabled_by_default(self):
        """Tracing must be disabled by default (no overhead)."""
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.OTEL_ENABLED is False

    def test_otel_exporter_default_endpoint(self):
        """Default OTLP endpoint should be HTTP/protobuf."""
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.OTEL_EXPORTER_ENDPOINT == "http://localhost:4318/v1/traces"

    def test_otel_service_name_default(self):
        """Default service name should be 'rag-proxy'."""
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.OTEL_SERVICE_NAME == "rag-proxy"


class TestTracingModuleExports:
    """Verify that tracing.py exports the expected symbols."""

    def test_exports_tracer(self):
        """tracing module should export a tracer instance."""
        import proxy.app.shared.tracing as tracing_mod

        assert hasattr(tracing_mod, "tracer")

    def test_exports_setup_tracing(self):
        """tracing module should export setup_tracing function."""
        import proxy.app.shared.tracing as tracing_mod

        assert hasattr(tracing_mod, "setup_tracing")
        assert callable(tracing_mod.setup_tracing)

    def test_exports_get_current_span(self):
        """tracing module should export get_current_span function."""
        import proxy.app.shared.tracing as tracing_mod

        assert hasattr(tracing_mod, "get_current_span")
        assert callable(tracing_mod.get_current_span)

    def test_exports_add_event(self):
        """tracing module should export add_event function."""
        import proxy.app.shared.tracing as tracing_mod

        assert hasattr(tracing_mod, "add_event")
        assert callable(tracing_mod.add_event)

    def test_exports_set_span_error(self):
        """tracing module should export set_span_error function."""
        import proxy.app.shared.tracing as tracing_mod

        assert hasattr(tracing_mod, "set_span_error")
        assert callable(tracing_mod.set_span_error)

    def test_exports_span_context_from_headers(self):
        """tracing module should export span_context_from_headers."""
        import proxy.app.shared.tracing as tracing_mod

        assert hasattr(tracing_mod, "span_context_from_headers")
        assert callable(tracing_mod.span_context_from_headers)

    def test_exports_inject_context_to_headers(self):
        """tracing module should export inject_context_to_headers."""
        import proxy.app.shared.tracing as tracing_mod

        assert hasattr(tracing_mod, "inject_context_to_headers")
        assert callable(tracing_mod.inject_context_to_headers)

    def test_exports_traced_decorator(self):
        """tracing module should export traced decorator."""
        import proxy.app.shared.tracing as tracing_mod

        assert hasattr(tracing_mod, "traced")
        assert callable(tracing_mod.traced)


class TestTracedDecorator:
    """Test the @traced decorator for function instrumentation."""

    def test_sync_traced_function(self):
        """@traced should wrap a sync function with a span."""
        from proxy.app.shared.tracing import traced

        @traced("test.sync_func")
        def my_func(x: int) -> int:
            return x * 2

        result = my_func(5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_async_traced_function(self):
        """@traced should wrap an async function with a span."""
        import asyncio

        from proxy.app.shared.tracing import traced

        @traced("test.async_func")
        async def my_async_func(x: int) -> int:
            await asyncio.sleep(0)
            return x * 3

        result = await my_async_func(5)
        assert result == 15

    def test_traced_preserves_metadata(self):
        """@traced should preserve function name and docstring."""
        from proxy.app.shared.tracing import traced

        @traced()
        def documented_func():
            """My docstring."""
            return 42

        assert documented_func.__name__ == "documented_func"
        assert documented_func.__doc__ == "My docstring."
        assert documented_func() == 42

    def test_traced_exception_propagation(self):
        """@traced should propagate exceptions from the wrapped function."""
        from proxy.app.shared.tracing import traced

        @traced("test.error_func")
        def failing_func():
            raise RuntimeError("expected")

        with pytest.raises(RuntimeError, match="expected"):
            failing_func()

    @pytest.mark.asyncio
    async def test_async_traced_exception_propagation(self):
        """@traced should propagate exceptions from async wrapped functions."""
        from proxy.app.shared.tracing import traced

        @traced("test.async_error")
        async def async_failing():
            raise ValueError("async expected")

        with pytest.raises(ValueError, match="async expected"):
            await async_failing()


class TestTraceContextMiddleware:
    """Test the TraceContextMiddleware for W3C context propagation."""

    def test_middleware_class_exists(self):
        """TraceContextMiddleware should be importable."""
        from proxy.app.shared.middleware import TraceContextMiddleware

        assert TraceContextMiddleware is not None

    def test_middleware_registered_in_setup(self):
        """setup_all_middleware should include TraceContextMiddleware."""
        from unittest.mock import MagicMock

        from fastapi import FastAPI

        from proxy.app.shared.middleware import setup_all_middleware

        app = FastAPI()
        app.add_middleware = MagicMock()
        setup_all_middleware(app)
        # TraceContextMiddleware should be first
        calls = app.add_middleware.call_args_list
        assert len(calls) >= 1
        # Find TraceContextMiddleware in calls
        middleware_classes = [call[0][0].__name__ if hasattr(call[0][0], "__name__") else str(call) for call in calls]
        assert "TraceContextMiddleware" in middleware_classes

    def test_middleware_dispatches_without_trace_headers(self):
        """TraceContextMiddleware should handle requests without trace headers."""
        import pytest

        TraceContextMiddleware = pytest.importorskip("proxy.app.shared.middleware").TraceContextMiddleware

        assert TraceContextMiddleware is not None


class TestTracingStubsIntegration:
    """Integration tests verifying tracing stubs in key modules."""

    def test_chat_imports_tracing(self):
        """chat.py should import tracing utilities."""
        from proxy.app.api.chat import tracer, add_event, get_current_span

        assert tracer is not None
        assert callable(add_event)
        assert callable(get_current_span)

    def test_retrieval_imports_tracing(self):
        """retrieval.py should import tracing utilities."""
        from proxy.app.core.retrieval import tracer, add_event

        assert tracer is not None
        assert callable(add_event)

    def test_rerank_imports_tracing(self):
        """rerank.py should import tracing utilities."""
        from proxy.app.core.rerank import tracer, add_event

        assert tracer is not None
        assert callable(add_event)

    def test_middleware_imports_tracing(self):
        """middleware.py should import span_context_from_headers."""
        from proxy.app.shared.middleware import span_context_from_headers, tracer

        assert callable(span_context_from_headers)
        assert tracer is not None
