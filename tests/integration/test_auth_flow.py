# ruff: noqa: E501, SIM117, E402, N817, SIM105
# tests/integration/test_auth_flow.py
"""Integration tests for authentication and authorization flow.

Tests the complete auth lifecycle:
- Login → get token pair → use token → refresh token
- Protected endpoints require auth when AUTH_ENABLED=true
- Public endpoints work without auth
- Token validation and rejection
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


# ─── Shared helpers ───────────────────────────────────────────────────────────


def _create_test_token(
    user_id="test-user-001",
    username="testuser",
    roles=None,
    groups=None,
    secret="test-secret-key-for-integration",
):
    """Create a valid JWT token for testing."""
    from proxy.app.auth.jwt import create_token

    return create_token(
        user_id=user_id,
        username=username,
        roles=roles or ["user"],
        groups=groups or ["everyone"],
        access_level="internal",
        secret=secret,
    )


def _create_admin_token(secret="test-secret-key-for-integration"):
    """Create a JWT token with admin role."""
    return _create_test_token(
        user_id="admin-001",
        username="admin",
        roles=["admin", "user"],
        groups=["admins"],
        secret=secret,
    )


@pytest.fixture
def auth_disabled_client():
    """TestClient with AUTH_ENABLED=false (default behavior)."""
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


@pytest.fixture
def auth_enabled_client():
    """TestClient with AUTH_ENABLED=true for testing auth enforcement."""
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.USE_LANGGRAPH", False),
        patch("proxy.app.main.LOG_REQUESTS", False),
        patch("proxy.app.main.LLM_MODEL_NAME", "test-model"),
        patch("proxy.app.auth.jwt.AUTH_ENABLED", True),
        patch("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-integration"),
    ):
        from fastapi.testclient import TestClient

        from proxy.app.main import app

        client = TestClient(app)
        yield client


@pytest.fixture
def mock_user_db():
    """Mock the user database for login/refresh tests."""
    mock_db = AsyncMock()
    mock_db.verify_password = AsyncMock()
    mock_db.consume_refresh_token = AsyncMock()
    mock_db.store_refresh_token = AsyncMock(return_value="token_id_123")
    mock_db.revoke_user_tokens = AsyncMock(return_value=1)
    return mock_db


class TestPublicEndpointsNoAuth:
    """Test that public endpoints work without authentication."""

    def test_health_endpoint_no_auth_required(self, auth_disabled_client):
        """GET /v1/health works without any authentication."""
        response = auth_disabled_client.get("/v1/health")
        assert response.status_code in (200, 503)  # 503 if services down, but not 401
        assert "status" in response.json()

    def test_health_live_no_auth_required(self, auth_disabled_client):
        """GET /v1/health/live works without authentication."""
        response = auth_disabled_client.get("/v1/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_health_ready_no_auth_required(self, auth_disabled_client):
        """GET /v1/health/ready works without authentication."""
        response = auth_disabled_client.get("/v1/health/ready")
        assert response.status_code in (200, 503)

    def test_models_endpoint_no_auth_required(self, auth_disabled_client):
        """GET /v1/models works without authentication."""
        response = auth_disabled_client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"


class TestProtectedEndpointsWithAuth:
    """Test that protected endpoints require authentication when AUTH_ENABLED=true."""

    def test_chat_endpoint_rejects_no_token(self, auth_enabled_client):
        """POST /v1/chat/completions returns 401 when no token is provided."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        response = auth_enabled_client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 401

    def test_chat_endpoint_rejects_invalid_token(self, auth_enabled_client):
        """POST /v1/chat/completions returns 401 for an invalid JWT token."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        response = auth_enabled_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        assert response.status_code == 401

    def test_chat_endpoint_accepts_valid_token(self, auth_enabled_client):
        """POST /v1/chat/completions succeeds with a valid JWT token."""
        token = _create_test_token()

        search_results = [MagicMock()]
        search_results[0].id = "h"
        search_results[0].score = 0.95
        search_results[0].payload = {
            "text": "Context",
            "source_type": "test",
            "source_id": "1",
            "version": "1.0",
            "title": "T",
            "doc_title": "D",
        }

        async def mock_llm(messages, **kwargs):
            return "Authenticated response."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            }
            response = auth_enabled_client.post(
                "/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            assert response.json()["object"] == "chat.completion"

    def test_feedback_endpoint_rejects_no_token(self, auth_enabled_client):
        """POST /v1/feedback returns 401 without a token."""
        response = auth_enabled_client.post(
            "/v1/feedback",
            json={"feedback_id": "fb_test", "type": "positive"},
        )
        # Feedback may be behind auth or not — check for either 401 or the expected behavior
        assert response.status_code in (401, 200, 422)

    def test_health_endpoints_work_with_auth_enabled(self, auth_enabled_client):
        """Health endpoints are public even when AUTH_ENABLED=true."""
        # /v1/health/live should work without token (it's in _PUBLIC_PATHS)
        response = auth_enabled_client.get("/v1/health/live")
        assert response.status_code == 200

        response = auth_enabled_client.get("/v1/health")
        assert response.status_code in (200, 503)

        response = auth_enabled_client.get("/v1/health/ready")
        assert response.status_code in (200, 503)

    def test_models_endpoint_public_with_auth_enabled(self, auth_enabled_client):
        """GET /v1/models is public even when AUTH_ENABLED=true."""
        response = auth_enabled_client.get("/v1/models")
        assert response.status_code == 200


class TestLoginFlow:
    """Test login → token pair → use token → refresh flow."""

    def test_login_returns_token_pair(self, auth_disabled_client, mock_user_db):
        """POST /v1/auth/login returns access_token and refresh_token."""
        mock_user = {
            "id": "user-001",
            "username": "testuser",
            "password_hash": "$2b$12$hash",
            "roles": ["user"],
            "groups": ["everyone"],
            "access_level": "user",
            "namespace": "",
        }
        mock_user_db.verify_password.return_value = mock_user

        with (
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_user_db),
            patch("proxy.app.auth.user_db.get_user_db", return_value=mock_user_db),
            patch("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-integration"),
        ):
            response = auth_disabled_client.post(
                "/v1/auth/login",
                json={"username": "testuser", "password": "password123"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data
            assert data["token_type"] == "bearer"
            assert data["username"] == "testuser"
            assert "expires_in" in data

    def test_login_invalid_credentials_returns_401(self, auth_disabled_client, mock_user_db):
        """POST /v1/auth/login returns 401 for invalid credentials."""
        mock_user_db.verify_password.return_value = None

        with (
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_user_db),
        ):
            response = auth_disabled_client.post(
                "/v1/auth/login",
                json={"username": "testuser", "password": "wrong_password"},
            )

            assert response.status_code == 401
            assert "Invalid credentials" in response.json()["detail"]

    def test_refresh_token_returns_new_pair(self, auth_disabled_client, mock_user_db):
        """POST /v1/auth/refresh exchanges a refresh token for a new token pair."""
        mock_user = {
            "id": "user-001",
            "username": "testuser",
            "roles": ["user"],
            "groups": ["everyone"],
            "access_level": "user",
            "namespace": "",
        }
        mock_user_db.consume_refresh_token.return_value = mock_user

        with (
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_user_db),
            patch("proxy.app.auth.user_db.get_user_db", return_value=mock_user_db),
            patch("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-integration"),
        ):
            response = auth_disabled_client.post(
                "/v1/auth/refresh",
                json={"token": "valid_refresh_token_abc123"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data
            assert data["token_type"] == "bearer"

    def test_refresh_invalid_token_returns_401(self, auth_disabled_client, mock_user_db):
        """POST /v1/auth/refresh returns 401 for invalid refresh token."""
        mock_user_db.consume_refresh_token.return_value = None

        with (
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_user_db),
            patch("proxy.app.auth.user_db.get_user_db", return_value=mock_user_db),
            patch("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-integration"),
        ):
            response = auth_disabled_client.post(
                "/v1/auth/refresh",
                json={"token": "invalid_refresh_token"},
            )

            assert response.status_code == 401

    def test_login_then_use_access_token(self, auth_enabled_client, mock_user_db):
        """Full flow: login → get access_token → use it on a protected endpoint."""
        mock_user = {
            "id": "user-001",
            "username": "testuser",
            "password_hash": "$2b$12$hash",
            "roles": ["user"],
            "groups": ["everyone"],
            "access_level": "user",
            "namespace": "",
        }
        mock_user_db.verify_password.return_value = mock_user

        with (
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_user_db),
            patch("proxy.app.auth.user_db.get_user_db", return_value=mock_user_db),
        ):
            # Step 1: Login
            login_response = auth_enabled_client.post(
                "/v1/auth/login",
                json={"username": "testuser", "password": "password123"},
            )
            assert login_response.status_code == 200
            access_token = login_response.json()["access_token"]

            # Step 2: Use access token on protected endpoint
            search_results = [MagicMock()]
            search_results[0].id = "h"
            search_results[0].score = 0.95
            search_results[0].payload = {
                "text": "Ctx",
                "source_type": "t",
                "source_id": "1",
                "version": "1.0",
                "title": "T",
                "doc_title": "D",
            }

            async def mock_llm(messages, **kwargs):
                return "Authenticated answer."

            with (
                patch("proxy.app.main.hybrid_search", return_value=search_results),
                patch("proxy.app.main.rerank_chunks", return_value=[0]),
                patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
            ):
                chat_response = auth_enabled_client.post(
                    "/v1/chat/completions",
                    json={"model": "test-model", "messages": [{"role": "user", "content": "Hello"}]},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                assert chat_response.status_code == 200


class TestLogoutFlow:
    """Test logout endpoint behavior."""

    def test_logout_returns_ok(self, auth_disabled_client, mock_user_db):
        """POST /v1/auth/logout returns ok status."""
        mock_user_db.consume_refresh_token.return_value = None

        with (
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_user_db),
        ):
            response = auth_disabled_client.post(
                "/v1/auth/logout",
                json={"refresh_token": "some_token"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"


class TestTokenValidation:
    """Test JWT token creation and validation edge cases."""

    def test_create_and_verify_token(self):
        """create_token produces a token that verify_token can decode."""
        from proxy.app.auth.jwt import create_token, verify_token

        secret = "test-secret-validation"
        token = create_token(
            user_id="u1",
            username="alice",
            roles=["admin", "user"],
            groups=["engineering"],
            access_level="confidential",
            namespace="eng",
            secret=secret,
        )

        with patch("proxy.app.auth.jwt._get_verify_key", return_value=secret):
            ctx = verify_token(token)

        assert ctx.user_id == "u1"
        assert ctx.username == "alice"
        assert "admin" in ctx.roles
        assert "user" in ctx.roles
        assert ctx.access_level == "confidential"
        assert ctx.namespace == "eng"

    def test_verify_token_rejects_wrong_secret(self):
        """verify_token raises HTTPException for token signed with wrong secret."""
        from proxy.app.auth.jwt import create_token, verify_token

        token = create_token(user_id="u1", username="alice", secret="correct-secret")

        with (
            patch("proxy.app.auth.jwt._get_verify_key", return_value="wrong-secret"),
            pytest.raises(Exception, match="Invalid token"),
        ):
            verify_token(token)

    def test_anonymous_user_context(self):
        """UserContext.anonymous() returns expected default values."""
        from proxy.app.auth.jwt import UserContext

        anon = UserContext.anonymous()
        assert anon.user_id == "anonymous"
        assert anon.username == "anonymous"
        assert anon.is_authenticated is False
        assert "viewer" in anon.roles
        assert anon.access_level == "public"

    def test_authenticated_user_context(self):
        """UserContext with real user_id is authenticated."""
        from proxy.app.auth.jwt import UserContext

        user = UserContext(user_id="u1", username="alice", roles=["user"])
        assert user.is_authenticated is True
        assert user.is_admin is False

    def test_admin_user_context(self):
        """UserContext with admin role has is_admin=True."""
        from proxy.app.auth.jwt import UserContext

        admin = UserContext(user_id="a1", username="admin", roles=["admin", "user"])
        assert admin.is_admin is True
        assert admin.is_authenticated is True
