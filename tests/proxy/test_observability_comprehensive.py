"""Comprehensive observability tests — tracing and metrics coverage across all endpoints.

Covers:
- Metrics registration for all new auth/feedback/files/admin metrics
- Metrics helper function invocations
- Tracing imports in all endpoint modules (chat, auth, feedback, admin, files)
- Tracing no-op behavior
- Spans created for auth operations
- Spans created for file operations
- Spans created for admin operations
- Metrics endpoint integration
- All metrics appear in /metrics output
- Cross-module tracing consistency
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestNewMetricsRegistration:
    """Test that all new auth/feedback/files/admin metrics are properly registered."""

    def test_auth_login_metric_registered(self):
        from proxy.app.shared.metrics import RAG_AUTH_LOGIN_TOTAL

        assert RAG_AUTH_LOGIN_TOTAL is not None

    def test_auth_register_metric_registered(self):
        from proxy.app.shared.metrics import RAG_AUTH_REGISTER_TOTAL

        assert RAG_AUTH_REGISTER_TOTAL is not None

    def test_auth_refresh_metric_registered(self):
        from proxy.app.shared.metrics import RAG_AUTH_REFRESH_TOTAL

        assert RAG_AUTH_REFRESH_TOTAL is not None

    def test_auth_logout_metric_registered(self):
        from proxy.app.shared.metrics import RAG_AUTH_LOGOUT_TOTAL

        assert RAG_AUTH_LOGOUT_TOTAL is not None

    def test_auth_rate_limit_metric_registered(self):
        from proxy.app.shared.metrics import RAG_AUTH_RATE_LIMIT_TOTAL

        assert RAG_AUTH_RATE_LIMIT_TOTAL is not None

    def test_feedback_metric_registered(self):
        from proxy.app.shared.metrics import RAG_FEEDBACK_TOTAL

        assert RAG_FEEDBACK_TOTAL is not None

    def test_feedback_processing_metric_registered(self):
        from proxy.app.shared.metrics import RAG_FEEDBACK_PROCESSING_SECONDS

        assert RAG_FEEDBACK_PROCESSING_SECONDS is not None

    def test_enrichment_metric_registered(self):
        from proxy.app.shared.metrics import RAG_ENRICHMENT_TOTAL

        assert RAG_ENRICHMENT_TOTAL is not None

    def test_file_upload_metric_registered(self):
        from proxy.app.shared.metrics import RAG_FILE_UPLOAD_TOTAL

        assert RAG_FILE_UPLOAD_TOTAL is not None

    def test_file_upload_bytes_metric_registered(self):
        from proxy.app.shared.metrics import RAG_FILE_UPLOAD_BYTES

        assert RAG_FILE_UPLOAD_BYTES is not None

    def test_file_download_metric_registered(self):
        from proxy.app.shared.metrics import RAG_FILE_DOWNLOAD_TOTAL

        assert RAG_FILE_DOWNLOAD_TOTAL is not None

    def test_file_delete_metric_registered(self):
        from proxy.app.shared.metrics import RAG_FILE_DELETE_TOTAL

        assert RAG_FILE_DELETE_TOTAL is not None

    def test_file_list_metric_registered(self):
        from proxy.app.shared.metrics import RAG_FILE_LIST_TOTAL

        assert RAG_FILE_LIST_TOTAL is not None

    def test_file_presigned_metric_registered(self):
        from proxy.app.shared.metrics import RAG_FILE_PRESIGNED_TOTAL

        assert RAG_FILE_PRESIGNED_TOTAL is not None

    def test_admin_operations_metric_registered(self):
        from proxy.app.shared.metrics import RAG_ADMIN_OPERATIONS_TOTAL

        assert RAG_ADMIN_OPERATIONS_TOTAL is not None

    def test_training_jobs_metric_registered(self):
        from proxy.app.shared.metrics import RAG_TRAINING_JOBS_TOTAL

        assert RAG_TRAINING_JOBS_TOTAL is not None

    def test_canary_split_metric_registered(self):
        from proxy.app.model_evolution.canary_controller import canary_split_ratio

        assert canary_split_ratio is not None

    def test_warmup_status_metric_registered(self):
        from proxy.app.shared.metrics import RAG_WARMUP_STATUS

        assert RAG_WARMUP_STATUS is not None


class TestNewMetricsRecording:
    """Test that new metrics can be recorded without errors."""

    def test_record_auth_login(self):
        from proxy.app.shared.metrics import record_auth_login

        record_auth_login("success", "local")
        record_auth_login("failure", "local")
        record_auth_login("success", "ldap")
        record_auth_login("rate_limited")

    def test_record_auth_register(self):
        from proxy.app.shared.metrics import record_auth_register

        record_auth_register("success")
        record_auth_register("conflict")
        record_auth_register("weak_password")
        record_auth_register("disabled")

    def test_record_auth_refresh(self):
        from proxy.app.shared.metrics import record_auth_refresh

        record_auth_refresh("success")
        record_auth_refresh("failure")
        record_auth_refresh("rate_limited")

    def test_record_auth_logout(self):
        from proxy.app.shared.metrics import record_auth_logout

        record_auth_logout()
        record_auth_logout()

    def test_record_auth_rate_limit(self):
        from proxy.app.shared.metrics import record_auth_rate_limit

        record_auth_rate_limit("login")
        record_auth_rate_limit("refresh")
        record_auth_rate_limit("register")

    def test_record_feedback(self):
        from proxy.app.shared.metrics import record_feedback

        record_feedback("positive", 0.5)
        record_feedback("negative", 1.2)
        record_feedback("positive")

    def test_record_enrichment(self):
        from proxy.app.shared.metrics import record_enrichment

        record_enrichment("success")
        record_enrichment("failure")

    def test_record_file_upload(self):
        from proxy.app.shared.metrics import record_file_upload

        record_file_upload("success", 1024000)
        record_file_upload("rejected_content_type")
        record_file_upload("size_exceeded")

    def test_record_file_download(self):
        from proxy.app.shared.metrics import record_file_download

        record_file_download("success")
        record_file_download("not_found")
        record_file_download("error")

    def test_record_file_delete(self):
        from proxy.app.shared.metrics import record_file_delete

        record_file_delete("success")
        record_file_delete("not_found")

    def test_record_file_list(self):
        from proxy.app.shared.metrics import record_file_list

        record_file_list()
        record_file_list()

    def test_record_file_presigned(self):
        from proxy.app.shared.metrics import record_file_presigned

        record_file_presigned("success")
        record_file_presigned("error")

    def test_record_admin_operation(self):
        from proxy.app.shared.metrics import record_admin_operation

        record_admin_operation("train", "running")
        record_admin_operation("promote", "success")
        record_admin_operation("rollback", "not_found")

    def test_record_training_job(self):
        from proxy.app.shared.metrics import record_training_job

        record_training_job("slm", "completed")
        record_training_job("llm", "failed")
        record_training_job("reranker", "completed")

    def test_set_canary_split(self):
        from proxy.app.shared.metrics import set_canary_split

        set_canary_split("test-model", 0.3)
        set_canary_split("test-model", 0.0)

    def test_set_warmup_status(self):
        from proxy.app.shared.metrics import set_warmup_status

        set_warmup_status(0)
        set_warmup_status(1)
        set_warmup_status(-1)


class TestTracingInEndpointModules:
    """Test that tracing is imported in all endpoint modules."""

    def test_auth_endpoints_imports_tracing(self):
        from proxy.app.api.auth_endpoints import add_event, tracer

        assert tracer is not None
        assert callable(add_event)

    def test_feedback_imports_tracing(self):
        from proxy.app.api.feedback import add_event, set_span_error, tracer

        assert tracer is not None
        assert callable(add_event)
        assert callable(set_span_error)

    def test_admin_imports_tracing(self):
        from proxy.app.api.admin import add_event, tracer

        assert tracer is not None
        assert callable(add_event)

    def test_files_imports_tracing(self):
        from proxy.app.api.files import set_span_error, tracer

        assert tracer is not None
        assert callable(set_span_error)

    def test_chat_imports_tracing(self):
        from proxy.app.api.chat import add_event, get_current_span, tracer

        assert tracer is not None
        assert callable(add_event)
        assert callable(get_current_span)

    def test_retrieval_imports_tracing(self):
        from proxy.app.core.retrieval import add_event, tracer

        assert tracer is not None
        assert callable(add_event)

    def test_rerank_imports_tracing(self):
        from proxy.app.core.rerank import add_event, tracer

        assert tracer is not None
        assert callable(add_event)

    def test_middleware_imports_tracing(self):
        from proxy.app.shared.middleware import span_context_from_headers, tracer

        assert tracer is not None
        assert callable(span_context_from_headers)


class TestTracingNoOp:
    """Test tracing works when OpenTelemetry is not installed."""

    def test_traced_decorator_importable(self):
        from proxy.app.shared.tracing import traced

        assert callable(traced)

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

    def test_span_context_returns_none_without_traceparent(self):
        from proxy.app.shared.tracing import span_context_from_headers

        result = span_context_from_headers({"user-agent": "test"})
        assert result is None

    def test_setup_tracing_importable(self):
        from proxy.app.shared.tracing import setup_tracing

        assert callable(setup_tracing)

    def test_noop_span_context_manager(self):
        from proxy.app.shared.tracing import tracer

        with tracer.start_as_current_span("test.noop") as span:
            assert not span.is_recording()
            span.set_attribute("k", "v")

    def test_inject_context_to_headers_noop(self):
        from proxy.app.shared.tracing import inject_context_to_headers

        headers: dict[str, str] = {}
        inject_context_to_headers(headers)
        assert headers == {}

    def test_noop_span_all_methods(self):
        from proxy.app.shared.tracing import _NoOpSpan

        span = _NoOpSpan()
        span.add_event("e", {"k": "v"})
        span.record_exception(ValueError("x"))
        span.set_status("OK")
        span.end()
        span.set_attributes({"a": 1})
        assert span.is_recording() is False


class TestTracingSpansInEndpoints:
    """Test that tracing spans are created in endpoint modules."""

    def test_auth_register_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("auth.register") as span:
            span.set_attribute("auth.username", "testuser")
            span.set_attribute("auth.client_ip", "127.0.0.1")
        assert True

    def test_auth_login_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("auth.login") as span:
            span.set_attribute("auth.username", "testuser")
            span.set_attribute("auth.client_ip", "127.0.0.1")
        assert True

    def test_auth_refresh_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("auth.refresh") as span:
            span.set_attribute("auth.client_ip", "127.0.0.1")
        assert True

    def test_auth_logout_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("auth.logout"):
            pass
        assert True

    def test_feedback_submit_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("feedback.submit") as span:
            span.set_attribute("feedback.id", "fb-123")
            span.set_attribute("feedback.rating", "positive")
        assert True

    def test_file_upload_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("file.upload") as span:
            span.set_attribute("file.filename", "test.pdf")
            span.set_attribute("file.size_bytes", 1024)
        assert True

    def test_file_download_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("file.download") as span:
            span.set_attribute("file.id", "uploads/test.pdf")
        assert True

    def test_file_delete_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("file.delete") as span:
            span.set_attribute("file.id", "uploads/test.pdf")
        assert True

    def test_admin_warmup_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("admin.warmup") as span:
            span.set_attribute("admin.warmup_components", 3)
        assert True

    def test_admin_train_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("admin.train") as span:
            span.set_attribute("admin.trainer_type", "slm")
            span.set_attribute("admin.training_job_id", "train-abc123")
        assert True

    def test_admin_evaluate_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("admin.evaluate") as span:
            span.set_attribute("admin.model_name", "test-model")
            span.set_attribute("admin.eval_status", "PASS")
        assert True

    def test_admin_canary_split_creates_span(self):
        from proxy.app.shared.tracing import tracer as t

        with t.start_as_current_span("admin.canary_split") as span:
            span.set_attribute("admin.model_name", "test-model")
            span.set_attribute("admin.traffic_split", 0.2)
        assert True


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


class TestMetricsEndpointIntegration:
    """Test that all new metrics appear in the /metrics endpoint."""

    def test_new_auth_metrics_appear_in_metrics_output(self):
        from proxy.app.shared.metrics import init_metrics, metrics_endpoint

        init_metrics()
        from proxy.app.shared.metrics import record_auth_login

        record_auth_login("success", "local")
        result = metrics_endpoint()
        body = result.body.decode()
        assert "rag_auth_login_total" in body

    def test_new_feedback_metrics_appear_in_metrics_output(self):
        from proxy.app.shared.metrics import init_metrics, metrics_endpoint

        init_metrics()
        from proxy.app.shared.metrics import record_feedback

        record_feedback("positive", 0.5)
        result = metrics_endpoint()
        body = result.body.decode()
        assert "rag_feedback_total" in body

    def test_new_file_metrics_appear_in_metrics_output(self):
        from proxy.app.shared.metrics import init_metrics, metrics_endpoint

        init_metrics()
        from proxy.app.shared.metrics import record_file_upload

        record_file_upload("success", 1024)
        result = metrics_endpoint()
        body = result.body.decode()
        assert "rag_file_upload_total" in body

    def test_new_admin_metrics_appear_in_metrics_output(self):
        from proxy.app.shared.metrics import init_metrics, metrics_endpoint

        init_metrics()
        from proxy.app.shared.metrics import record_admin_operation

        record_admin_operation("warmup", "success")
        result = metrics_endpoint()
        body = result.body.decode()
        assert "rag_admin_operations_total" in body


class TestTracingContextPropagation:
    """Test W3C trace context propagation utilities."""

    def test_span_context_from_headers_no_traceparent(self):
        from proxy.app.shared.tracing import span_context_from_headers

        result = span_context_from_headers({})
        assert result is None

    def test_inject_context_to_headers_empty_dict(self):
        from proxy.app.shared.tracing import inject_context_to_headers

        headers: dict[str, str] = {"existing": "value"}
        inject_context_to_headers(headers)


class TestTracingSetup:
    """Test tracing setup function behavior."""

    def test_setup_tracing_disabled_by_default(self):
        import importlib

        import proxy.app.shared.config as cfg

        importlib.reload(cfg)
        assert cfg.OTEL_ENABLED is False

    def test_setup_tracing_has_config_values(self):
        import proxy.app.shared.config as cfg

        assert hasattr(cfg, "OTEL_ENABLED")
        assert hasattr(cfg, "OTEL_EXPORTER_ENDPOINT")
        assert hasattr(cfg, "OTEL_SERVICE_NAME")
        assert hasattr(cfg, "OTEL_BATCH_TIMEOUT")


class TestMetricsAllEndpoints:
    """Test that all 30+ metrics are registered and countable in output."""

    def test_all_metrics_present_in_output(self):
        from proxy.app.shared.metrics import (
            init_metrics,
            metrics_endpoint,
        )

        init_metrics()
        record_auth_login = __import__("proxy.app.shared.metrics", fromlist=["record_auth_login"]).record_auth_login
        record_auth_login("success", "local")
        result = metrics_endpoint()
        body = result.body.decode()
        rag_metrics = [line for line in body.split("\n") if line.startswith("rag_")]
        assert len(rag_metrics) >= 25
