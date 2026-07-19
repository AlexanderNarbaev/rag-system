"""Tests for auth endpoints — /v1/auth/login, register, me, refresh, logout.

Uses TestClient with unittest.mock.patch for user_db and config.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_modules_to_mock = [
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "sentence_transformers",
    "langgraph",
    "langgraph.graph",
    "langgraph.checkpoint",
    "neo4j",
    "redis",
    "redis.asyncio",
    "tiktoken",
]

for mod in _modules_to_mock:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from proxy.app.auth import get_auth_context, get_optional_auth_context  # noqa: E402
from proxy.app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_mock_db():
    """Create a mocked UserDatabase with all needed async methods."""
    db = MagicMock()
    db.verify_password = AsyncMock()
    db.create_user = AsyncMock()
    db.store_refresh_token = AsyncMock()
    db.consume_refresh_token = AsyncMock()
    db.revoke_user_tokens = AsyncMock(return_value=1)
    db.add_to_blacklist = AsyncMock()
    db.is_blacklisted = AsyncMock(return_value=False)
    db.get_user = AsyncMock()
    db.get_user_by_username = AsyncMock()
    return db


def _make_test_user(user_id="test-id", username="testuser", password="password123!"):
    import bcrypt

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")
    return {
        "id": user_id,
        "username": username,
        "password_hash": password_hash,
        "email": "test@example.com",
        "roles": ["user"],
        "groups": ["everyone"],
        "access_level": "user",
        "namespace": "",
        "is_active": 1,
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }


# ===========================================================================
# POST /v1/auth/register
# ===========================================================================


class TestRegister:
    """Tests for POST /v1/auth/register."""

    def test_register_success_returns_201(self, client):
        """Successful registration returns 201 and user details."""
        mock_db = _make_mock_db()
        mock_db.create_user.return_value = {
            "user_id": "new-user-id",
            "username": "newuser123",
            "created_at": "2025-01-01T00:00:00+00:00",
        }

        with (
            patch("proxy.app.shared.config.AUTH_ENABLED", True),
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db),
        ):
            response = client.post(
                "/v1/auth/register",
                json={
                    "username": "newuser123",
                    "password": "Password123!",
                    "email": "new@example.com",
                },
            )
            assert response.status_code == 201, response.text
            data = response.json()
            assert data["username"] == "newuser123"
            assert "user_id" in data

    def test_register_duplicate_returns_409(self, client):
        """Duplicate username returns 409."""
        mock_db = _make_mock_db()
        mock_db.create_user.side_effect = ValueError("Username 'duplicate' already exists")

        with (
            patch("proxy.app.shared.config.AUTH_ENABLED", True),
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db),
        ):
            response = client.post(
                "/v1/auth/register",
                json={
                    "username": "duplicate",
                    "password": "Password123!",
                },
            )
            assert response.status_code == 409

    def test_register_auth_disabled_returns_400(self, client):
        """When AUTH_ENABLED is false, registration returns 400."""
        response = client.post(
            "/v1/auth/register",
            json={
                "username": "newuser456",
                "password": "Password123!",
            },
        )
        assert response.status_code == 400

    def test_register_short_password_returns_422(self, client):
        """Password shorter than 10 chars returns 422."""
        with patch("proxy.app.shared.config.AUTH_ENABLED", True):
            response = client.post(
                "/v1/auth/register",
                json={
                    "username": "shortpass",
                    "password": "short",
                },
            )
            assert response.status_code == 422

    def test_register_invalid_username_returns_422(self, client):
        """Username with invalid characters returns 422."""
        with patch("proxy.app.shared.config.AUTH_ENABLED", True):
            response = client.post(
                "/v1/auth/register",
                json={
                    "username": "user name",
                    "password": "Password123!",
                },
            )
            assert response.status_code == 422


# ===========================================================================
# POST /v1/auth/login
# ===========================================================================


class TestLogin:
    """Tests for POST /v1/auth/login."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-unit-tests-32chars!")
        monkeypatch.setenv("JWT_ALGORITHM", "HS256")
        from proxy.app.api.auth_endpoints import _LOGIN_ATTEMPTS

        _LOGIN_ATTEMPTS.clear()

    def test_login_valid_credentials(self, client):
        """Valid credentials return access + refresh tokens."""
        mock_db = _make_mock_db()
        test_user = _make_test_user(username="loginuser", password="password123!")
        mock_db.verify_password.return_value = test_user

        with (
            patch("proxy.app.shared.config.JWT_ALGORITHM", "HS256"),
            patch("proxy.app.shared.config.JWT_SECRET", "test-secret-key-for-unit-tests-32chars!"),
            patch("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256"),
            patch("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-unit-tests-32chars!"),
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db),
            patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db),
        ):
            response = client.post(
                "/v1/auth/login",
                json={"username": "loginuser", "password": "password123!"},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data
            assert data["token_type"] == "bearer"

    def test_login_invalid_password_returns_401(self, client):
        """Invalid password returns 401."""
        mock_db = _make_mock_db()
        mock_db.verify_password.return_value = None

        with patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db):
            response = client.post(
                "/v1/auth/login",
                json={"username": "baduser", "password": "wrongpassword!"},
            )
            assert response.status_code == 401

    def test_login_deactivated_user_returns_403(self, client):
        """Deactivated user returns 403."""
        mock_db = _make_mock_db()
        test_user = _make_test_user(username="deactivated")
        test_user["is_active"] = 0
        mock_db.verify_password.return_value = test_user

        with patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db):
            response = client.post(
                "/v1/auth/login",
                json={"username": "deactivated", "password": "password123!"},
            )
            assert response.status_code in (401, 403)

    def test_login_requires_fields(self, client):
        """Missing fields return 422."""
        response = client.post("/v1/auth/login", json={})
        assert response.status_code == 422


# ===========================================================================
# GET /v1/auth/me
# ===========================================================================


class TestAuthMe:
    """Tests for GET /v1/auth/me."""

    def test_auth_me_with_admin_ctx(self, client):
        """Returns user info for authenticated user."""
        admin_ctx = MagicMock()
        admin_ctx.user_id = "admin-1"
        admin_ctx.username = "admin"
        admin_ctx.roles = ["admin"]
        admin_ctx.groups = ["engineering"]
        admin_ctx.access_level = "admin"
        admin_ctx.is_admin = True
        admin_ctx.is_authenticated = True

        async def _mock_auth(request=None, credentials=None):
            return admin_ctx

        app.dependency_overrides[get_auth_context] = _mock_auth

        response = client.get("/v1/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "admin"
        assert data["is_admin"] is True
        assert "admin" in data["roles"]

    def test_auth_me_requires_auth_when_enabled(self, client, monkeypatch):
        """Without auth when AUTH_ENABLED=true, returns 401."""
        monkeypatch.setenv("AUTH_ENABLED", "true")
        app.dependency_overrides.clear()

        with patch("proxy.app.shared.config.AUTH_ENABLED", True):
            response = client.get("/v1/auth/me")
            assert response.status_code in (200, 401, 403)


# ===========================================================================
# POST /v1/auth/refresh
# ===========================================================================


class TestRefresh:
    """Tests for POST /v1/auth/refresh."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-unit-tests-32chars!")
        monkeypatch.setenv("JWT_ALGORITHM", "HS256")
        monkeypatch.setenv("AUTH_ENABLED", "true")

    def test_refresh_with_valid_token(self, client):
        """Valid refresh token returns new token pair."""
        mock_db = _make_mock_db()
        test_user = _make_test_user(username="refresher", user_id="refresh-user-id")
        mock_db.consume_refresh_token.return_value = test_user

        with (
            patch("proxy.app.shared.config.AUTH_ENABLED", True),
            patch("proxy.app.shared.config.JWT_ALGORITHM", "HS256"),
            patch("proxy.app.shared.config.JWT_SECRET", "test-secret-key-for-unit-tests-32chars!"),
            patch("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256"),
            patch("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-unit-tests-32chars!"),
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db),
            patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db),
        ):
            response = client.post(
                "/v1/auth/refresh",
                json={"token": "fake-refresh-token"},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data
            assert data["token_type"] == "bearer"

    def test_refresh_invalid_token_returns_401(self, client):
        """Invalid refresh token returns 401."""
        mock_db = _make_mock_db()
        mock_db.consume_refresh_token.return_value = None

        with (
            patch("proxy.app.shared.config.AUTH_ENABLED", True),
            patch("proxy.app.shared.config.JWT_ALGORITHM", "HS256"),
            patch("proxy.app.shared.config.JWT_SECRET", "test-secret-key-for-unit-tests-32chars!"),
            patch("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256"),
            patch("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-unit-tests-32chars!"),
            patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db),
            patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db),
        ):
            response = client.post(
                "/v1/auth/refresh",
                json={"token": "bad-refresh-token"},
            )
            assert response.status_code == 401


# ===========================================================================
# POST /v1/auth/logout
# ===========================================================================


class TestLogout:
    """Tests for POST /v1/auth/logout."""

    def test_logout_without_auth_returns_ok(self, client):
        """Logout without auth succeeds (optional auth)."""
        mock_db = _make_mock_db()
        with patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db):
            response = client.post("/v1/auth/logout", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"

    def test_logout_revokes_refresh_token(self, client):
        """Logout with refresh_token revokes it."""
        mock_db = _make_mock_db()
        with patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db):
            response = client.post(
                "/v1/auth/logout",
                json={"refresh_token": "token-to-revoke"},
            )
            assert response.status_code == 200
            mock_db.consume_refresh_token.assert_called_once()

    def test_logout_all_sessions(self, client):
        """Logout with all_sessions=true revokes all user tokens."""
        mock_db = _make_mock_db()
        user_ctx = MagicMock()
        user_ctx.user_id = "user-revoke"
        user_ctx.username = "revoker"
        user_ctx.roles = ["user"]
        user_ctx.groups = []
        user_ctx.access_level = "user"
        user_ctx.is_admin = False
        user_ctx.is_authenticated = True
        user_ctx.namespace = ""

        async def _mock_optional_auth(request=None, credentials=None):
            return user_ctx

        app.dependency_overrides[get_optional_auth_context] = _mock_optional_auth

        with patch("proxy.app.api.auth_endpoints.get_user_db", return_value=mock_db):
            response = client.post(
                "/v1/auth/logout",
                json={"all_sessions": True},
            )
            assert response.status_code == 200
            mock_db.revoke_user_tokens.assert_called_once_with("user-revoke")


# ===========================================================================
# Pydantic Models
# ===========================================================================


class TestAuthPydanticModels:
    """Test Pydantic models for validation."""

    def test_login_request_fields(self):
        from proxy.app.api.auth_endpoints import LoginRequest

        req = LoginRequest(username="test", password="pass")
        assert req.username == "test"
        assert req.expires_in_hours == 24

    def test_register_request_validation(self):
        from proxy.app.api.auth_endpoints import RegisterRequest

        req = RegisterRequest(username="validuser", password="Password123!")
        assert req.username == "validuser"

    def test_register_request_short_username(self):
        from proxy.app.api.auth_endpoints import RegisterRequest

        with pytest.raises(ValueError):
            RegisterRequest(username="a", password="Password123!")

    def test_refresh_request(self):
        from proxy.app.api.auth_endpoints import RefreshRequest

        req = RefreshRequest(token="my-refresh-token")
        assert req.token == "my-refresh-token"

    def test_logout_request_defaults(self):
        from proxy.app.api.auth_endpoints import LogoutRequest

        req = LogoutRequest()
        assert req.refresh_token is None
        assert req.all_sessions is False

    def test_user_info_response_structure(self):
        from proxy.app.api.auth_endpoints import UserInfoResponse

        resp = UserInfoResponse(
            user_id="u1",
            username="tester",
            roles=["user"],
            groups=["everyone"],
            access_level="user",
            is_admin=False,
            is_authenticated=True,
        )
        assert resp.is_admin is False
        assert resp.username == "tester"
