"""Tests for proxy/app/tracing.py — OpenTelemetry distributed tracing setup."""

from unittest.mock import MagicMock, patch


class TestTracingNoOpWhenDisabled:
    """Verify tracing is no-op (zero overhead) when OTEL_ENABLED=false."""

    def test_setup_tracing_noop_when_disabled(self):
        """setup_tracing() should return immediately when disabled."""
        from proxy.app.shared.tracing import setup_tracing

        with patch("proxy.app.shared.tracing.OTEL_ENABLED", False):
            result = setup_tracing()
            assert result is None

    def test_tracer_is_proxy_when_disabled(self):
        """Module-level tracer should be a no-op proxy when tracing is disabled."""
        from proxy.app.shared.tracing import tracer

        # The tracer from get_tracer() with unset provider is a ProxyTracer (no-op).
        # Verify that start_as_current_span returns a valid span context manager.
        with tracer.start_as_current_span("test.noop") as span:
            # No-op span should not be recording
            assert not span.is_recording()
            # set_attribute should not raise
            span.set_attribute("test.key", "value")

    def test_get_current_span_noop(self):
        """get_current_span() should return a non-recording span."""
        from opentelemetry.trace import INVALID_SPAN

        from proxy.app.shared.tracing import get_current_span

        span = get_current_span()
        assert not span.is_recording() or span is INVALID_SPAN

    def test_add_event_noop(self):
        """add_event() should not raise when no span is active."""
        from proxy.app.shared.tracing import add_event

        with patch("proxy.app.shared.tracing.trace.get_current_span") as mock_span_fn:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = False
            mock_span_fn.return_value = mock_span

            add_event("test.event", {"key": "value"})
            # Event should not be added to a non-recording span
            mock_span.add_event.assert_not_called()

    def test_set_span_error_noop(self):
        """set_span_error() should not raise when no span is active."""
        from proxy.app.shared.tracing import set_span_error

        with patch("proxy.app.shared.tracing.trace.get_current_span") as mock_span_fn:
            mock_span = MagicMock()
            mock_span.is_recording.return_value = False
            mock_span_fn.return_value = mock_span

            exc = ValueError("test error")
            set_span_error(exc)
            mock_span.record_exception.assert_not_called()


class TestTracingSetup:
    """Test tracing initialization when OTEL_ENABLED=true."""

    def test_setup_tracing_initializes_provider(self):
        """setup_tracing() should create a TracerProvider and exporter."""
        from proxy.app.shared.tracing import _tracer_provider, _tracing_initialized, setup_tracing

        # Save state
        was_initialized = _tracing_initialized
        old_provider = _tracer_provider

        try:
            with (
                patch("proxy.app.shared.tracing.OTEL_ENABLED", True),
                patch("proxy.app.shared.tracing.OTEL_EXPORTER_ENDPOINT", "http://localhost:4318/v1/traces"),
                patch("proxy.app.shared.tracing.OTEL_BATCH_TIMEOUT", 5),
                patch("proxy.app.shared.tracing.OTLPSpanExporter") as mock_exporter_cls,
                patch("proxy.app.shared.tracing.BatchSpanProcessor") as mock_bsp_cls,
                patch("proxy.app.shared.tracing.TracerProvider") as mock_provider_cls,
                patch("proxy.app.shared.tracing.trace"),
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
            # Restore module state
            import proxy.app.shared.tracing as tracing_mod

            tracing_mod._tracing_initialized = was_initialized
            tracing_mod._tracer_provider = old_provider

    def test_setup_tracing_sets_global_provider(self):
        """setup_tracing() should register the provider globally via trace.set_tracer_provider."""
        with (
            patch("proxy.app.shared.tracing.OTEL_ENABLED", True),
            patch("proxy.app.shared.tracing.trace") as mock_trace,
            patch("proxy.app.shared.tracing.OTLPSpanExporter"),
            patch("proxy.app.shared.tracing.BatchSpanProcessor"),
            patch("proxy.app.shared.tracing.TracerProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider_cls.return_value = mock_provider

            import proxy.app.shared.tracing as tracing_mod

            tracing_mod._tracing_initialized = False
            try:
                from proxy.app.shared.tracing import setup_tracing

                setup_tracing(service_name="test-svc")
                mock_trace.set_tracer_provider.assert_called_once_with(mock_provider)
            finally:
                tracing_mod._tracing_initialized = False
                tracing_mod._tracer_provider = None

    def test_setup_tracing_handles_exporter_error(self):
        """setup_tracing() should gracefully degrade when exporter init fails."""
        with (
            patch("proxy.app.shared.tracing.OTEL_ENABLED", True),
            patch("proxy.app.shared.tracing.OTLPSpanExporter", side_effect=ConnectionError("Cannot connect")),
            patch("proxy.app.shared.tracing.TracerProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider_cls.return_value = mock_provider

            # Should not raise — graceful degradation
            from proxy.app.shared.tracing import setup_tracing

            result = setup_tracing()
            assert result is None

    def test_setup_tracing_idempotent(self):
        """setup_tracing() should be idempotent — second call is a no-op."""
        with (
            patch("proxy.app.shared.tracing.OTEL_ENABLED", True),
            patch("proxy.app.shared.tracing.trace") as mock_trace,
            patch("proxy.app.shared.tracing.OTLPSpanExporter"),
            patch("proxy.app.shared.tracing.BatchSpanProcessor"),
            patch("proxy.app.shared.tracing.TracerProvider") as mock_provider_cls,
        ):
            mock_provider = MagicMock()
            mock_provider_cls.return_value = mock_provider

            import proxy.app.shared.tracing as tracing_mod

            # Reset state
            tracing_mod._tracing_initialized = False
            tracing_mod._tracer_provider = None
            try:
                from proxy.app.shared.tracing import setup_tracing

                # First call
                setup_tracing(service_name="test-svc")
                first_call_count = mock_trace.set_tracer_provider.call_count

                # Second call
                setup_tracing(service_name="test-svc")
                # Should not have called set_tracer_provider again
                assert mock_trace.set_tracer_provider.call_count == first_call_count
            finally:
                tracing_mod._tracing_initialized = False
                tracing_mod._tracer_provider = None


class TestSpanContextManager:
    """Test that tracer.start_as_current_span works correctly."""

    def test_span_context_manager_works(self):
        """start_as_current_span should work as a context manager."""
        from proxy.app.shared.tracing import tracer

        with tracer.start_as_current_span("test.context_manager") as span:
            span.set_attribute("test.attr", "hello")
            # When tracing disabled, span is non-recording but doesn't raise
            pass

        # Context manager should exit cleanly
        assert True

    def test_span_captures_attributes(self):
        """Span attributes should be settable."""
        from proxy.app.shared.tracing import tracer

        with tracer.start_as_current_span("test.attributes") as span:
            span.set_attribute("string_attr", "value")
            span.set_attribute("int_attr", 42)
            span.set_attribute("bool_attr", True)
            span.set_attribute("float_attr", 3.14)
            # No exceptions raised
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

        # Reload config with fresh env to ensure defaults
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
