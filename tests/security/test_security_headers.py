"""Security-header middleware integration tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.app.shared.middleware import SecurityHeadersMiddleware


@pytest.fixture
def response():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app).get("/health")


def test_hsts_header(response) -> None:
    assert "max-age=31536000" in response.headers["Strict-Transport-Security"]


def test_content_type_options_header(response) -> None:
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_frame_options_header(response) -> None:
    assert response.headers["X-Frame-Options"] == "DENY"


def test_xss_protection_header(response) -> None:
    assert response.headers["X-XSS-Protection"] == "1; mode=block"


def test_content_security_policy_header(response) -> None:
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_referrer_policy_header(response) -> None:
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
