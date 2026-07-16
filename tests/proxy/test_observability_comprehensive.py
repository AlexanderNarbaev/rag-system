"""Comprehensive observability tests for tracing and metrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from proxy.app.shared.metrics import (
    RAG_CACHE_HITS,
    RAG_CACHE_MISSES,
    RAG_LATENCY,
    RAG_QUEUE_DEPTH,
    RAG_REQUEST_COUNT,
    RAG_RETRIEVAL_SCORES,
    record_cache_hit,
    record_cache_miss,
    record_rag_request,
    record_retrieval,
    set_queue_depth,
)


class TestMetricsRegistration:
    """Test that all metrics are properly registered."""

    def test_rag_request_count_registered(self):
        assert RAG_REQUEST_COUNT is not None

    def test_rag_latency_registered(self):
        assert RAG_LATENCY is not None

    def test_rag_cache_hits_registered(self):
        assert RAG_CACHE_HITS is not None

    def test_rag_cache_misses_registered(self):
        assert RAG_CACHE_MISSES is not None

    def test_rag_retrieval_scores_registered(self):
        assert RAG_RETRIEVAL_SCORES is not None

    def test_rag_queue_depth_registered(self):
        assert RAG_QUEUE_DEPTH is not None


class TestMetricsRecording:
    """Test that metrics record correctly."""

    def test_record_rag_request(self):
        record_rag_request("/v1/chat/completions", "200", True, 0.5)

    def test_record_retrieval(self):
        record_retrieval(0.85, 0.1)

    def test_record_cache_hit(self):
        record_cache_hit("memory")

    def test_record_cache_miss(self):
        record_cache_miss("memory")

    def test_set_queue_depth(self):
        set_queue_depth(5)
        set_queue_depth(0)


class TestTracingImports:
    """Test tracing module imports."""

    def test_traced_decorator_importable(self):
        from proxy.app.shared.tracing import traced
        assert callable(traced)

    def test_span_context_from_headers_importable(self):
        from proxy.app.shared.tracing import span_context_from_headers
        assert callable(span_context_from_headers)

    def test_setup_tracing_importable(self):
        from proxy.app.shared.tracing import setup_tracing
        assert callable(setup_tracing)


class TestTracingNoOp:
    """Test tracing works when OpenTelemetry is not installed."""

    def test_traced_works_without_otel(self):
        from proxy.app.shared.tracing import traced

        @traced("test.span")
        def test_func():
            return 42

        assert test_func() == 42

    def test_traced_handles_exceptions(self):
        from proxy.app.shared.tracing import traced

        @traced("test.span")
        def test_func():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            test_func()

    def test_span_context_returns_none_without_otel(self):
        from proxy.app.shared.tracing import span_context_from_headers
        result = span_context_from_headers({})
        assert result is None


class TestMiddlewareIntegration:
    """Test middleware integration with tracing."""

    def test_trace_context_middleware_exists(self):
        from proxy.app.shared.middleware import TraceContextMiddleware
        assert TraceContextMiddleware is not None

    def test_middleware_is_asgi_app(self):
        from proxy.app.shared.middleware import TraceContextMiddleware
        app = MagicMock()
        middleware = TraceContextMiddleware(app)
        assert callable(middleware)
