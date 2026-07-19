"""Tests for admin config API — FR-19."""

import sys
from unittest.mock import MagicMock

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

from proxy.app.auth import get_auth_context  # noqa: E402
from proxy.app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_ctx():
    ctx = MagicMock()
    ctx.is_admin = True
    ctx.is_authenticated = True
    ctx.user_id = "admin-1"
    ctx.username = "admin"
    ctx.roles = ["admin"]
    ctx.groups = []
    ctx.access_level = "admin"
    ctx.namespace = ""
    return ctx


@pytest.fixture
def user_ctx():
    ctx = MagicMock()
    ctx.is_admin = False
    ctx.is_authenticated = True
    ctx.user_id = "user-1"
    ctx.username = "user"
    ctx.roles = ["user"]
    ctx.groups = []
    ctx.access_level = "user"
    ctx.namespace = ""
    return ctx


def _override_auth(user_context):
    async def _mock_get_auth(request=None, credentials=None):
        return user_context

    app.dependency_overrides[get_auth_context] = _mock_get_auth


class TestAdminConfigGet:
    def test_get_config_as_admin(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/config")
        assert response.status_code == 200
        data = response.json()
        assert "config" in data
        assert "total" in data
        assert data["total"] > 0

    def test_get_config_sets_include_secrets(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/config")
        data = response.json()
        assert "JWT_SECRET" in data["config"]
        assert data["config"]["JWT_SECRET"]["secret"] is True

    def test_get_config_masks_secrets(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/config")
        data = response.json()
        jwt_entry = data["config"]["JWT_SECRET"]
        if jwt_entry["value"] and jwt_entry["value"] != "":
            assert "***" in str(jwt_entry["value"])

    def test_get_config_marks_safe_keys(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/config")
        data = response.json()
        assert data["config"]["LOG_LEVEL"]["safe"] is True
        assert data["config"]["JWT_SECRET"]["safe"] is False


class TestAdminConfigDefaults:
    def test_get_defaults_as_admin(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/config/defaults")
        assert response.status_code == 200
        data = response.json()
        assert "defaults" in data
        assert "total" in data
        assert "LOG_LEVEL" in data["defaults"]
        log_level = data["defaults"]["LOG_LEVEL"]
        assert "default" in log_level
        assert "current" in log_level

    def test_get_defaults_shows_overridden_flag(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/config/defaults")
        data = response.json()
        log_level = data["defaults"]["LOG_LEVEL"]
        assert "overridden" in log_level
        assert log_level["overridden"] is False


class TestAdminConfigPatch:
    def test_patch_safe_config(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.patch("/v1/admin/config", json={"updates": {"LOG_LEVEL": "DEBUG"}})
        assert response.status_code == 200
        data = response.json()
        assert "LOG_LEVEL" in data["accepted"]
        assert data["accepted"]["LOG_LEVEL"] == "DEBUG"

    def test_patch_rejects_secret_key(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.patch("/v1/admin/config", json={"updates": {"JWT_SECRET": "new-secret"}})
        assert response.status_code == 200
        data = response.json()
        assert "JWT_SECRET" in data["rejected"]
        assert "not safe" in data["rejected"]["JWT_SECRET"]

    def test_patch_rejects_unknown_key(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.patch("/v1/admin/config", json={"updates": {"NONEXISTENT_KEY": "value"}})
        assert response.status_code == 200
        data = response.json()
        assert "NONEXISTENT_KEY" in data["rejected"]

    def test_patch_multiple_keys(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.patch(
            "/v1/admin/config",
            json={
                "updates": {
                    "LOG_LEVEL": "WARNING",
                    "LOG_FORMAT": "text",
                    "JWT_SECRET": "bad",
                }
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "LOG_LEVEL" in data["accepted"]
        assert "LOG_FORMAT" in data["accepted"]
        assert "JWT_SECRET" in data["rejected"]


@pytest.fixture(autouse=True)
def _enable_auth(monkeypatch):
    """Re-enable auth for auth-specific tests."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    import proxy.app.auth.rbac as _rbac
    import proxy.app.shared.config as _cfg

    monkeypatch.setattr(_cfg, "AUTH_ENABLED", True)
    monkeypatch.setattr(_cfg, "RBAC_ENABLED", True)
    monkeypatch.setattr(_rbac, "RBAC_ENABLED", True)


class TestAdminConfigAuth:
    def test_get_config_requires_admin(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.get("/v1/admin/config")
        assert response.status_code == 403

    def test_patch_config_requires_admin(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.patch("/v1/admin/config", json={"updates": {"LOG_LEVEL": "DEBUG"}})
        assert response.status_code == 403

    def test_get_defaults_requires_admin(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.get("/v1/admin/config/defaults")
        assert response.status_code == 403
