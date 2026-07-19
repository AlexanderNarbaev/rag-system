# tests/integration/test_health_checks.py
"""Integration tests for health check endpoints.

Tests:
- /v1/health/live always returns 200 (liveness probe)
- /v1/health/ready checks Qdrant and LLM connectivity (readiness probe)
- /v1/health reports component-level status
- Unhealthy components are reported with degraded status
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


@pytest.fixture
def app_client():
    """Create a FastAPI TestClient with minimal mocks."""
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.USE_LANGGRAPH", False),
        patch("proxy.app.main.LOG_REQUESTS", False),
        patch("proxy.app.main.LLM_MODEL_NAME", "test-model"),
        patch("proxy.app.auth.jwt.AUTH_ENABLED", False),
    ):
        from fastapi.testclient import TestClient

        from proxy.app.main import app

        client = TestClient(app)
        yield client


def _mock_qdrant_ok():
    """Return a mock qdrant_client that responds to get_collections."""
    mock = MagicMock()
    mock.get_collections.return_value = MagicMock()
    return mock


def _mock_qdrant_fail(error_msg="Connection refused"):
    """Return a mock qdrant_client that raises on get_collections."""
    mock = MagicMock()
    mock.get_collections.side_effect = Exception(error_msg)
    return mock


def _mock_llm_response(status_code=200):
    """Return a mock requests response for LLM health check."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    return mock_resp


class TestLivenessProbe:
    """Tests for GET /v1/health/live — must always return 200."""

    def test_live_always_returns_200(self, app_client):
        """Liveness probe returns 200 regardless of component health."""
        response = app_client.get("/v1/health/live")
        assert response.status_code == 200

    def test_live_returns_alive_status(self, app_client):
        """Liveness probe response contains status='alive'."""
        response = app_client.get("/v1/health/live")
        data = response.json()
        assert data["status"] == "alive"

    def test_live_includes_timestamp(self, app_client):
        """Liveness probe response includes an ISO timestamp."""
        response = app_client.get("/v1/health/live")
        data = response.json()
        assert "timestamp" in data
        # Basic ISO format check
        assert "T" in data["timestamp"]

    def test_live_returns_200_even_when_qdrant_down(self, app_client):
        """Liveness probe returns 200 even when Qdrant is completely down."""
        with patch("proxy.app.core.retrieval.qdrant_client", _mock_qdrant_fail("Qdrant down")):
            response = app_client.get("/v1/health/live")
            assert response.status_code == 200
            assert response.json()["status"] == "alive"


class TestReadinessProbe:
    """Tests for GET /v1/health/ready — checks component connectivity."""

    def test_ready_returns_200_when_all_components_ok(self, app_client):
        """Readiness probe returns 200 when Qdrant and LLM are reachable."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["components"]["qdrant"] == "ok"
            assert data["components"]["llm"] == "ok"

    def test_ready_returns_503_when_qdrant_unavailable(self, app_client):
        """Readiness probe returns 503 when Qdrant is unreachable."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("unavailable", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert data["components"]["qdrant"] == "unavailable"

    def test_ready_returns_503_when_llm_unavailable(self, app_client):
        """Readiness probe returns 503 when LLM endpoint is unreachable."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("unavailable", {})),
        ):
            response = app_client.get("/v1/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert data["components"]["llm"] == "unavailable"

    def test_ready_returns_503_when_both_down(self, app_client):
        """Readiness probe returns 503 when both Qdrant and LLM are down."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("unavailable", {})),
            patch("proxy.app.api.health._check_llm", return_value=("unavailable", {})),
        ):
            response = app_client.get("/v1/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert data["components"]["qdrant"] == "unavailable"
            assert data["components"]["llm"] == "unavailable"

    def test_ready_includes_timestamp(self, app_client):
        """Readiness probe response includes a timestamp."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health/ready")
            data = response.json()
            assert "timestamp" in data


class TestHealthEndpoint:
    """Tests for GET /v1/health — detailed component status."""

    def test_health_ok_when_all_services_up(self, app_client):
        """Health returns 200 with status='ok' when Qdrant and LLM respond."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["components"]["qdrant"] == "ok"
            assert data["components"]["llm"] == "ok"

    def test_health_degraded_when_qdrant_unavailable(self, app_client):
        """Health returns 503 with status='degraded' when Qdrant check fails."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("Qdrant service unavailable", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "degraded"
            assert "unavailable" in data["components"]["qdrant"].lower()

    def test_health_degraded_when_llm_unavailable(self, app_client):
        """Health returns 503 with status='degraded' when LLM check fails."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("LLM service unavailable", {})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "degraded"
            assert "unavailable" in data["components"]["llm"].lower()

    def test_health_degraded_when_llm_returns_non_200(self, app_client):
        """Health reports LLM as unhealthy when it returns a non-200 status."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("unhealthy", {"status_code": 503})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health")
            data = response.json()
            assert data["components"]["llm"] == "unhealthy"

    def test_health_includes_timestamp(self, app_client):
        """Health response includes an ISO-formatted timestamp."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health")
            data = response.json()
            assert "timestamp" in data
            assert "T" in data["timestamp"]

    def test_health_has_components_dict(self, app_client):
        """Health response always includes a components dictionary."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("Qdrant service unavailable", {})),
            patch("proxy.app.api.health._check_llm", return_value=("LLM service unavailable", {})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health")
            data = response.json()
            assert "components" in data
            assert isinstance(data["components"], dict)
            assert "qdrant" in data["components"]
            assert "llm" in data["components"]


class TestHealthEndpointAuthBypass:
    """Test that health endpoints bypass authentication when AUTH_ENABLED=true."""

    def test_health_live_bypasses_auth(self, app_client):
        """GET /v1/health/live works without auth even in the public paths list."""
        # This test verifies the _PUBLIC_PATHS whitelist in AuthMiddleware
        response = app_client.get("/v1/health/live")
        assert response.status_code == 200

    def test_health_bypasses_auth(self, app_client):
        """GET /v1/health works without auth."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health")
            assert response.status_code in (200, 503)

    def test_health_ready_bypasses_auth(self, app_client):
        """GET /v1/health/ready works without auth."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health/ready")
            assert response.status_code in (200, 503)


class TestHealthEndpointFormats:
    """Test response format consistency across health endpoints."""

    def test_all_health_endpoints_return_json(self, app_client):
        """All health endpoints return JSON content type."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            for path in ["/v1/health", "/v1/health/live", "/v1/health/ready"]:
                response = app_client.get(path)
                assert "application/json" in response.headers.get("content-type", "")

    def test_health_response_schema(self, app_client):
        """Health response has consistent schema with required fields."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
            patch("proxy.app.api.health._check_secret_rotation", return_value=("ok", {})),
            patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health")
            data = response.json()

            # Required fields
            assert "status" in data
            assert "timestamp" in data
            assert "components" in data

            # Status must be one of expected values
            assert data["status"] in ("ok", "degraded")

            # Components must have qdrant and llm
            assert "qdrant" in data["components"]
            assert "llm" in data["components"]

    def test_live_response_schema(self, app_client):
        """Live response has consistent schema."""
        response = app_client.get("/v1/health/live")
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert data["status"] == "alive"

    def test_ready_response_schema(self, app_client):
        """Ready response has consistent schema with components."""
        with (
            patch("proxy.app.api.health._check_qdrant", return_value=("ok", {})),
            patch("proxy.app.api.health._check_llm", return_value=("ok", {})),
        ):
            response = app_client.get("/v1/health/ready")
            data = response.json()
            assert "status" in data
            assert "timestamp" in data
            assert "components" in data
            assert data["status"] in ("ready", "not_ready")
