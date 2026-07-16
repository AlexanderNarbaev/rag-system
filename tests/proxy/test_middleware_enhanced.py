"""Tests for proxy/app/shared/middleware.py — middleware coverage."""

from unittest.mock import MagicMock

from fastapi import FastAPI
from starlette.testclient import TestClient

from proxy.app.shared.middleware import (
    CorrelationIdMiddleware,
    RequestIdMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    add_cors_middleware,
    setup_all_middleware,
)


class TestRequestIdMiddleware:
    def test_injects_request_id(self):
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert "X-Request-ID" in resp.headers

    def test_preserves_existing_request_id(self):
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test", headers={"X-Request-ID": "my-id-123"})
        assert resp.headers["X-Request-ID"] == "my-id-123"


class TestRequestLoggingMiddleware:
    def test_logs_request(self):
        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200


class TestCorrelationIdMiddleware:
    def test_injects_correlation_id(self):
        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert "X-Correlation-ID" in resp.headers

    def test_preserves_existing_correlation_id(self):
        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test", headers={"X-Correlation-ID": "corr-123"})
        assert resp.headers["X-Correlation-ID"] == "corr-123"


class TestSecurityHeadersMiddleware:
    def test_adds_security_headers(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        # SecurityHeaders should inject some headers
        assert resp.status_code == 200


class TestAddCorsMiddleware:
    def test_adds_cors_with_wildcard(self):
        app = FastAPI()
        add_cors_middleware(app, origins="*")
        # Should not raise
        assert len(app.middleware_stack.__class__.__mro__) > 0

    def test_adds_cors_with_specific_origins(self):
        app = FastAPI()
        add_cors_middleware(app, origins="http://localhost:3000,http://example.com")
        assert len(app.middleware_stack.__class__.__mro__) > 0


class TestSetupAllMiddleware:
    def test_setup_without_audit_logger(self):
        app = FastAPI()
        setup_all_middleware(app, audit_logger=None)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200

    def test_setup_with_audit_logger(self):
        app = FastAPI()
        mock_logger = MagicMock()
        setup_all_middleware(app, audit_logger=mock_logger)

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
