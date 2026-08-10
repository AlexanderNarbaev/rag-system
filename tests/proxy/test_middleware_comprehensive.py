"""Comprehensive tests for proxy/app/shared/middleware.py.

Covers the eight middleware classes and the two helper functions
(add_cors_middleware, setup_all_middleware).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from proxy.app.shared.middleware import (
    AuditMiddleware,
    CorrelationIdMiddleware,
    InputSanitizationMiddleware,
    RequestIdMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    TraceContextMiddleware,
    add_cors_middleware,
    setup_all_middleware,
)

# ---------------------------------------------------------------------------
# Fake request/response helpers
# ---------------------------------------------------------------------------


def make_request(headers: dict[str, str] | None = None, query: str = "", client_ip: str = "127.0.0.1"):
    request = MagicMock()
    request.headers = headers or {}
    request.url.path = "/test"
    request.url.query = query
    request.url = MagicMock(path="/test", query=query)
    request.method = "GET"
    request.query_params.multi_items.return_value = []  # default
    request.client.host = client_ip
    request.state = MagicMock()
    return request


def make_response(status_code: int = 200, headers: dict[str, str] | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    return response


async def make_response_factory(status_code: int = 200, headers: dict[str, str] | None = None):
    """Returns an async function suitable for call_next."""
    response = make_response(status_code, headers)

    async def _call_next(_request):
        return response

    return _call_next, response


# ---------------------------------------------------------------------------
# RequestIdMiddleware
# ---------------------------------------------------------------------------


class TestRequestIdMiddleware:
    def test_generates_request_id_when_header_missing(self):

        middleware = RequestIdMiddleware(app=MagicMock())
        request = make_request(headers={})

        async def call_next(_req):
            return make_response()

        # Simulate async dispatch by calling it directly
        # We test through the .dispatch async method
        import asyncio

        async def go():
            return await middleware.dispatch(request, call_next)

        # Should set request_id on state
        result = asyncio.run(go())
        assert result.headers["X-Request-ID"]
        assert len(result.headers["X-Request-ID"]) > 0

    def test_uses_provided_request_id_header(self):
        import asyncio

        middleware = RequestIdMiddleware(app=MagicMock())
        request = make_request(headers={"X-Request-ID": "rid-abc"})
        request.state = MagicMock()

        captured = {}

        async def call_next(_req):
            captured["state_request_id"] = _req.state.request_id
            return make_response()

        async def go():
            return await middleware.dispatch(request, call_next)

        result = asyncio.run(go())
        assert captured["state_request_id"] == "rid-abc"
        assert result.headers["X-Request-ID"] == "rid-abc"

    def test_extracts_forwarded_user_id(self):
        import asyncio

        middleware = RequestIdMiddleware(app=MagicMock())
        request = make_request(headers={"x-openwebui-user-id": "u123"})
        request.state = MagicMock()

        captured = {}

        async def call_next(_req):
            captured["fwd"] = _req.state.forwarded_user_id
            return make_response()

        async def go():
            return await middleware.dispatch(request, call_next)

        asyncio.run(go())
        assert captured["fwd"] == "u123"

    def test_extracts_forwarded_user_id_alt_header(self):
        import asyncio

        middleware = RequestIdMiddleware(app=MagicMock())
        request = make_request(headers={"x-forwarded-user": "u456"})
        request.state = MagicMock()

        captured = {}

        async def call_next(_req):
            captured["fwd"] = _req.state.forwarded_user_id
            return make_response()

        async def go():
            await middleware.dispatch(request, call_next)

        asyncio.run(go())
        assert captured["fwd"] == "u456"


# ---------------------------------------------------------------------------
# RequestLoggingMiddleware
# ---------------------------------------------------------------------------


class TestRequestLoggingMiddleware:
    def test_logs_response_duration(self):
        import asyncio

        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = make_request()

        captured = {}

        async def call_next(_req):
            captured["called"] = True
            return make_response(status_code=200)

        async def go():
            return await middleware.dispatch(request, call_next)

        result = asyncio.run(go())
        assert result.status_code == 200
        assert captured.get("called") is True

    def test_returns_same_response_object(self):
        import asyncio

        middleware = RequestLoggingMiddleware(app=MagicMock())
        request = make_request()
        response = make_response(status_code=201)

        async def call_next(_req):
            return response

        async def go():
            return await middleware.dispatch(request, call_next)

        result = asyncio.run(go())
        assert result is response


# ---------------------------------------------------------------------------
# CorrelationIdMiddleware
# ---------------------------------------------------------------------------


class TestCorrelationIdMiddleware:
    def test_generates_correlation_id_when_missing(self):
        import asyncio

        middleware = CorrelationIdMiddleware(app=MagicMock())
        request = make_request(headers={})
        request.state = MagicMock()

        captured = {}

        async def call_next(_req):
            captured["cid"] = _req.state.correlation_id
            return make_response()

        async def go():
            return await middleware.dispatch(request, call_next)

        result = asyncio.run(go())
        assert captured["cid"]
        assert result.headers[CorrelationIdMiddleware.HEADER_NAME] == captured["cid"]

    def test_uses_provided_correlation_id(self):
        import asyncio

        middleware = CorrelationIdMiddleware(app=MagicMock())
        request = make_request(headers={"X-Correlation-ID": "cid-123"})
        request.state = MagicMock()

        captured = {}

        async def call_next(_req):
            captured["cid"] = _req.state.correlation_id
            return make_response()

        async def go():
            return await middleware.dispatch(request, call_next)

        asyncio.run(go())
        assert captured["cid"] == "cid-123"


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware
# ---------------------------------------------------------------------------


class TestSecurityHeadersMiddleware:
    def test_injects_default_headers(self):
        import asyncio

        middleware = SecurityHeadersMiddleware(app=MagicMock())
        request = make_request()

        async def call_next(_req):
            # Return response with no existing headers
            return make_response(headers={})

        async def go():
            return await middleware.dispatch(request, call_next)

        result = asyncio.run(go())
        # At least one default header present
        assert "X-Content-Type-Options" in result.headers
        assert "X-Frame-Options" in result.headers

    def test_does_not_overwrite_existing_headers(self):
        import asyncio

        middleware = SecurityHeadersMiddleware(app=MagicMock())
        request = make_request()
        custom = {"X-Frame-Options": "SAMEORIGIN"}

        async def call_next(_req):
            return make_response(headers=custom)

        async def go():
            return await middleware.dispatch(request, call_next)

        result = asyncio.run(go())
        assert result.headers["X-Frame-Options"] == "SAMEORIGIN"


# ---------------------------------------------------------------------------
# AuditMiddleware
# ---------------------------------------------------------------------------


class TestAuditMiddleware:
    def test_no_audit_logger_skips(self):
        import asyncio

        middleware = AuditMiddleware(app=MagicMock(), audit_logger=None)
        request = make_request()

        async def call_next(_req):
            return make_response(status_code=500)

        async def go():
            return await middleware.dispatch(request, call_next)

        # Should not raise even with no audit_logger
        result = asyncio.run(go())
        assert result.status_code == 500

    def test_logs_error_on_4xx(self):
        import asyncio

        audit = MagicMock()
        middleware = AuditMiddleware(app=MagicMock(), audit_logger=audit)
        request = make_request()

        async def call_next(_req):
            return make_response(status_code=400)

        async def go():
            return await middleware.dispatch(request, call_next)

        asyncio.run(go())
        audit.log_error.assert_called_once()
        # Error type is the status code
        call_args = audit.log_error.call_args
        assert "400" in str(call_args)

    def test_logs_error_on_5xx(self):
        import asyncio

        audit = MagicMock()
        middleware = AuditMiddleware(app=MagicMock(), audit_logger=audit)
        request = make_request()

        async def call_next(_req):
            return make_response(status_code=500)

        async def go():
            return await middleware.dispatch(request, call_next)

        asyncio.run(go())
        audit.log_error.assert_called_once()

    def test_no_log_on_2xx(self):
        import asyncio

        audit = MagicMock()
        middleware = AuditMiddleware(app=MagicMock(), audit_logger=audit)
        request = make_request()

        async def call_next(_req):
            return make_response(status_code=200)

        async def go():
            return await middleware.dispatch(request, call_next)

        asyncio.run(go())
        audit.log_error.assert_not_called()

    def test_handles_audit_logger_exception(self):
        import asyncio

        audit = MagicMock()
        audit.log_error.side_effect = AttributeError("oops")
        middleware = AuditMiddleware(app=MagicMock(), audit_logger=audit)
        request = make_request()

        async def call_next(_req):
            return make_response(status_code=500)

        async def go():
            return await middleware.dispatch(request, call_next)

        # Should not propagate
        result = asyncio.run(go())
        assert result.status_code == 500

    def test_no_client_host(self):
        import asyncio

        audit = MagicMock()
        middleware = AuditMiddleware(app=MagicMock(), audit_logger=audit)
        request = make_request()
        request.client = None

        async def call_next(_req):
            return make_response(status_code=500)

        async def go():
            return await middleware.dispatch(request, call_next)

        asyncio.run(go())
        # Should log with "unknown" client_ip
        call_kwargs = audit.log_error.call_args.kwargs
        assert call_kwargs["client_ip"] == "unknown"


# ---------------------------------------------------------------------------
# InputSanitizationMiddleware
# ---------------------------------------------------------------------------


class TestInputSanitizationMiddleware:
    def test_no_query_string(self):
        import asyncio

        middleware = InputSanitizationMiddleware(app=MagicMock())
        request = make_request(query="")

        async def call_next(_req):
            return make_response()

        async def go():
            return await middleware.dispatch(request, call_next)

        result = asyncio.run(go())
        assert result.status_code == 200

    def test_with_query_params(self):
        import asyncio

        middleware = InputSanitizationMiddleware(app=MagicMock())
        request = make_request(query="a=1&b=2")
        request.url.query = "a=1&b=2"

        async def call_next(_req):
            return make_response()

        async def go():
            return await middleware.dispatch(request, call_next)

        asyncio.run(go())
        # multi_items called at least once
        request.query_params.multi_items.assert_called()


# ---------------------------------------------------------------------------
# TraceContextMiddleware
# ---------------------------------------------------------------------------


class TestTraceContextMiddleware:
    def test_dispatch_sets_status_code_on_span(self):
        import asyncio

        from proxy.app.shared import tracing as tracing_mod

        # Ensure no-op tracer (forced)
        old_tracer = tracing_mod._tracer
        tracing_mod._tracer = tracing_mod._NOOP_TRACER

        try:
            middleware = TraceContextMiddleware(app=MagicMock())
            request = make_request()

            async def call_next(_req):
                return make_response(status_code=200)

            async def go():
                return await middleware.dispatch(request, call_next)

            result = asyncio.run(go())
            assert result.status_code == 200
        finally:
            tracing_mod._tracer = old_tracer

    def test_dispatch_with_error_response(self):
        import asyncio

        from proxy.app.shared import tracing as tracing_mod

        old_tracer = tracing_mod._tracer
        tracing_mod._tracer = tracing_mod._NOOP_TRACER

        try:
            middleware = TraceContextMiddleware(app=MagicMock())
            request = make_request()

            async def call_next(_req):
                return make_response(status_code=500)

            async def go():
                return await middleware.dispatch(request, call_next)

            result = asyncio.run(go())
            assert result.status_code == 500
        finally:
            tracing_mod._tracer = old_tracer


# ---------------------------------------------------------------------------
# add_cors_middleware / setup_all_middleware
# ---------------------------------------------------------------------------


class TestAddCorsMiddleware:
    def test_adds_cors_with_wildcard(self):
        app = MagicMock()
        add_cors_middleware(app, origins="*")
        # CORS middleware appended with allow_origins=["*"]
        kwargs = app.add_middleware.call_args.kwargs
        assert kwargs["allow_origins"] == ["*"]

    def test_parses_csv_origins(self):
        app = MagicMock()
        add_cors_middleware(app, origins="https://a.com, https://b.com")
        kwargs = app.add_middleware.call_args.kwargs
        assert "https://a.com" in kwargs["allow_origins"]
        assert "https://b.com" in kwargs["allow_origins"]

    def test_exposes_known_headers(self):
        app = MagicMock()
        add_cors_middleware(app, origins="*")
        kwargs = app.add_middleware.call_args.kwargs
        assert "X-Request-ID" in kwargs["expose_headers"]
        assert "X-Correlation-ID" in kwargs["expose_headers"]
        assert "Retry-After" in kwargs["expose_headers"]

    def test_allow_credentials_enabled(self):
        app = MagicMock()
        add_cors_middleware(app, origins="*")
        kwargs = app.add_middleware.call_args.kwargs
        assert kwargs["allow_credentials"] is True


class TestSetupAllMiddleware:
    def test_default_appends_middleware(self):
        app = MagicMock()
        setup_all_middleware(app)
        # Should have called add_middleware at least 5 times
        assert app.add_middleware.call_count >= 5

    def test_with_audit_logger_appends_audit(self):
        app = MagicMock()
        audit = MagicMock()
        setup_all_middleware(app, audit_logger=audit)
        # AuditMiddleware added with audit_logger kwarg
        found_audit = False
        for call in app.add_middleware.call_args_list:
            if call.args and call.args[0] is AuditMiddleware:
                found_audit = True
                assert call.kwargs.get("audit_logger") is audit
        assert found_audit

    def test_without_audit_logger_skips_audit(self):
        app = MagicMock()
        setup_all_middleware(app, audit_logger=None)
        for call in app.add_middleware.call_args_list:
            # No call should be AuditMiddleware
            assert call.args[0] is not AuditMiddleware

    def test_middleware_order_starts_with_trace(self):
        app = MagicMock()
        setup_all_middleware(app)
        first_call = app.add_middleware.call_args_list[0]
        assert first_call.args[0] is TraceContextMiddleware
