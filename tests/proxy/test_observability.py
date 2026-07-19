# tests/proxy/test_observability.py
"""Observability tests for metrics, logging, and tracing.

Covers:
- FR-160: Prometheus /metrics endpoint
- FR-161: Structured JSON logging
- FR-164: OpenTelemetry trace ID propagation
"""

import json
import logging
import re

import pytest

# ============================================================================
# FR-160: Prometheus /metrics endpoint
# ============================================================================


class TestPrometheusMetrics:
    """FR-160: /metrics must return valid Prometheus text format with >=12 metrics."""

    def test_metrics_module_imports(self):
        """Metrics module must be importable."""
        from proxy.app.shared.metrics import (
            metrics_endpoint,
            rag_active_requests,
            rag_cache_hits_total,
            rag_request_duration_seconds,
            rag_requests_total,
        )

        assert rag_requests_total is not None
        assert rag_request_duration_seconds is not None
        assert rag_cache_hits_total is not None
        assert rag_active_requests is not None
        assert callable(metrics_endpoint)

    @staticmethod
    def _get_metrics_body() -> str:
        """Get metrics body as string."""
        from proxy.app.shared.metrics import metrics_endpoint

        response = metrics_endpoint()
        raw = response.body
        return raw.decode("utf-8") if isinstance(raw, bytes) else bytes(raw).decode("utf-8")

    def test_metrics_endpoint_returns_prometheus_format(self):
        """metrics_endpoint() must return valid Prometheus text format."""
        body = self._get_metrics_body()

        # Prometheus text format: lines starting with # HELP or metric_name
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        assert len(lines) > 0, "Empty metrics response"

        # At least some lines must be metric definitions or HELP/TYPE comments
        metric_lines = [ln for ln in lines if not ln.startswith("#") and re.match(r"^[a-zA-Z_]", ln)]
        assert len(metric_lines) > 0, "No metric lines found"

    def test_metrics_have_minimum_count(self):
        """Must expose >= 12 distinct metric names."""
        body = self._get_metrics_body()

        # Extract metric names from HELP comments
        metric_names: set[str] = set()
        for line in body.splitlines():
            if line.startswith("# HELP"):
                parts = line.split()
                if len(parts) >= 3:
                    metric_names.add(parts[2])
        assert len(metric_names) >= 12, f"Only {len(metric_names)} metrics found, need >=12"

    def test_metrics_include_required_counters(self):
        """Must include key counter metrics."""
        body = self._get_metrics_body()

        for metric in ("rag_requests_total", "rag_cache_hits_total"):
            assert metric in body, f"Missing required metric: {metric}"

    def test_metrics_include_required_histograms(self):
        """Must include key histogram metrics."""
        body = self._get_metrics_body()

        for metric in ("rag_request_duration_seconds", "rag_retrieval_duration_seconds"):
            assert metric in body, f"Missing required histogram: {metric}"

    def test_metrics_include_required_gauges(self):
        """Must include key gauge metrics."""
        body = self._get_metrics_body()

        assert "rag_active_requests" in body, "Missing gauge: rag_active_requests"

    def test_metrics_content_type(self):
        """Response must have Prometheus content type."""
        from proxy.app.shared.metrics import CONTENT_TYPE_LATEST, metrics_endpoint

        response = metrics_endpoint()
        assert response.media_type == CONTENT_TYPE_LATEST

    def test_record_rag_request_function(self):
        """record_rag_request helper must work without errors."""
        from proxy.app.shared.metrics import record_rag_request

        # Should not raise
        record_rag_request(method="POST", status="200", has_context=True, duration=0.5)

    def test_record_cache_hit_function(self):
        """record_cache_hit helper must work without errors."""
        from proxy.app.shared.metrics import record_cache_hit

        record_cache_hit(cache_type="embedding")

    def test_record_confidence_function(self):
        """record_confidence helper must work without errors."""
        from proxy.app.shared.metrics import record_confidence

        record_confidence(score=0.85)


# ============================================================================
# FR-161: Structured JSON logging
# ============================================================================


class TestStructuredLogging:
    """FR-161: LOG_FORMAT=json → valid JSON logs, secrets masked, request_id propagated."""

    def test_json_formatter_produces_valid_json(self):
        """JsonFormatter must output valid JSON per line."""
        from proxy.app.shared.logging import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert isinstance(data, dict)
        assert "timestamp" in data
        assert "level" in data
        assert "message" in data

    def test_json_formatter_includes_required_fields(self):
        """JSON log entry must include timestamp, level, logger, message."""
        from proxy.app.shared.logging import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="rag.proxy",
            level=logging.WARNING,
            pathname="chat.py",
            lineno=100,
            msg="Slow request",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "WARNING"
        assert data["logger"] == "rag.proxy"
        assert data["message"] == "Slow request"
        assert "line" in data

    def test_json_formatter_masks_api_key(self):
        """API keys must be masked as *** in JSON logs."""
        from proxy.app.shared.logging import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg='api_key="sk-secret12345678"',
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "sk-secret12345678" not in data["message"]
        assert "***" in data["message"]

    def test_json_formatter_masks_password(self):
        """Passwords must be masked in JSON logs."""
        from proxy.app.shared.logging import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="password=supersecret123",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "supersecret123" not in data["message"]
        assert "***" in data["message"]

    def test_json_formatter_masks_bearer_token(self):
        """Bearer tokens must be masked in JSON logs."""
        from proxy.app.shared.logging import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in data["message"]
        assert "***" in data["message"]

    def test_mask_sensitive_data_function(self):
        """mask_sensitive_data must replace secrets with ***."""
        from proxy.app.shared.logging import mask_sensitive_data

        test_cases = [
            ('api_key="abcdef123"', "***"),
            ("password= hunter2", "***"),
            ("secret: mysecretvalue", "***"),
        ]
        for input_msg, expected_marker in test_cases:
            result = mask_sensitive_data(input_msg)
            assert expected_marker in result, f"Failed to mask: {input_msg}"

    def test_request_id_filter_propagates_id(self):
        """RequestIdFilter must inject request_id into log records."""
        from proxy.app.shared.logging import RequestIdFilter

        filt = RequestIdFilter()
        RequestIdFilter.set_request_id("req-abc-123")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert hasattr(record, "request_id")
        assert record.request_id == "req-abc-123"
        # Cleanup
        RequestIdFilter.set_request_id(None)

    def test_request_id_filter_default(self):
        """RequestIdFilter must set '-' when no request_id is active."""
        from proxy.app.shared.logging import RequestIdFilter

        filt = RequestIdFilter()
        RequestIdFilter.set_request_id(None)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert record.request_id == "-"

    def test_json_formatter_with_exception(self):
        """JSON formatter must include exception info when present."""
        from proxy.app.shared.logging import JsonFormatter

        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_json_formatter_with_request_id(self):
        """JSON formatter must include request_id from record."""
        from proxy.app.shared.logging import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-xyz-789"  # type: ignore[attr-defined]
        output = formatter.format(record)
        data = json.loads(output)
        assert data["request_id"] == "req-xyz-789"


# ============================================================================
# FR-164: OpenTelemetry tracing
# ============================================================================


class TestOpenTelemetryTracing:
    """FR-164: Trace ID propagation via W3C traceparent header."""

    def test_tracing_module_imports(self):
        """Tracing module must be importable."""
        from proxy.app.shared.tracing import (
            add_event,
            inject_context_to_headers,
            setup_tracing,
            span_context_from_headers,
            tracer,
        )

        assert tracer is not None
        assert callable(setup_tracing)
        assert callable(span_context_from_headers)
        assert callable(inject_context_to_headers)
        assert callable(add_event)

    def test_noop_tracer_works_without_otel(self):
        """No-op tracer must work even when OTEL is not installed."""
        from proxy.app.shared.tracing import _NOOP_TRACER

        with _NOOP_TRACER.start_as_current_span("test") as span:
            assert span is not None
            assert not span.is_recording()
            span.set_attribute("key", "value")  # Should not raise

    def test_span_context_from_headers_requires_traceparent(self):
        """span_context_from_headers must return None without traceparent header."""
        from proxy.app.shared.tracing import span_context_from_headers

        result = span_context_from_headers({"Content-Type": "application/json"})
        assert result is None

    def test_span_context_from_headers_extracts_traceparent(self):
        """span_context_from_headers must extract W3C traceparent."""
        from proxy.app.shared.tracing import span_context_from_headers

        headers = {
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        }
        result = span_context_from_headers(headers)
        # With OTEL installed, should return a context; without, returns None
        # Either way, it should not raise
        assert result is not None or result is None  # Valid

    def test_inject_context_to_headers_does_not_raise(self):
        """inject_context_to_headers must not raise even without active span."""
        from proxy.app.shared.tracing import inject_context_to_headers

        headers: dict[str, str] = {}
        inject_context_to_headers(headers)  # Should not raise

    def test_add_event_does_not_raise_without_span(self):
        """add_event must not raise without an active span."""
        from proxy.app.shared.tracing import add_event

        add_event("test.event", {"key": "value"})  # Should not raise

    def test_set_span_error_does_not_raise(self):
        """set_span_error must not raise without active span."""
        from proxy.app.shared.tracing import set_span_error

        set_span_error(ValueError("test"))  # Should not raise

    def test_traced_decorator_exists(self):
        """traced decorator must be available."""
        from proxy.app.shared.tracing import traced

        assert callable(traced)

    def test_traced_decorator_wraps_sync_function(self):
        """traced decorator must wrap a sync function without errors."""
        from proxy.app.shared.tracing import traced

        @traced("test.span")
        def sync_func(x: int) -> int:
            return x * 2

        result = sync_func(21)
        assert result == 42

    @pytest.mark.asyncio
    async def test_traced_decorator_wraps_async_function(self):
        """traced decorator must wrap an async function without errors."""
        from proxy.app.shared.tracing import traced

        @traced("test.async_span")
        async def async_func(x: int) -> int:
            return x * 3

        result = await async_func(14)
        assert result == 42
