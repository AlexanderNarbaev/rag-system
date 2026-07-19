"""Tests for admin analytics API — FR-105."""

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


class TestAdminAnalyticsOverview:
    def test_get_analytics_as_admin(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics?period=7d")
        assert response.status_code == 200
        data = response.json()
        assert "period" in data
        assert data["period"] == "7d"
        assert "queries" in data
        assert "total" in data["queries"]
        assert "avg_per_hour" in data["queries"]
        assert "trend" in data["queries"]
        assert "users" in data
        assert "unique" in data["users"]
        assert "avg_queries_per_user" in data["users"]
        assert "latency" in data
        assert "p50_ms" in data["latency"]
        assert "p95_ms" in data["latency"]
        assert "p99_ms" in data["latency"]
        assert "tokens" in data
        assert "total_input" in data["tokens"]
        assert "total_output" in data["tokens"]
        assert "top_kbs" in data
        assert isinstance(data["top_kbs"], list)

    def test_get_analytics_default_period(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "30d"

    def test_get_analytics_24h(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics?period=24h")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "24h"

    def test_get_analytics_days_backward_compat(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics?days=90")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "90d"

    def test_get_analytics_rejects_invalid_days(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics?days=0")
        assert response.status_code == 422

    def test_get_analytics_with_metric_filter(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics?metric=queries,latency")
        assert response.status_code == 200
        data = response.json()
        assert "period" in data
        assert "queries" in data
        assert "latency" in data
        assert "users" not in data
        assert "tokens" not in data

    def test_get_analytics_top_kbs_structure(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics")
        data = response.json()
        assert "top_kbs" in data
        for kb in data["top_kbs"]:
            assert "name" in kb
            assert "queries" in kb


class TestAdminAnalyticsKB:
    def test_get_kb_analytics(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics/kb/test-kb?period=7d")
        assert response.status_code == 200
        data = response.json()
        assert data["kb_id"] == "test-kb"
        assert data["period"] == "7d"
        assert "total_queries" in data
        assert "percentage_of_total" in data
        assert "daily_breakdown" in data

    def test_get_kb_analytics_default(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics/kb/test-kb")
        assert response.status_code == 200
        data = response.json()
        assert data["period"] == "30d"

    def test_get_kb_analytics_daily_structure(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/admin/analytics/kb/test-kb?period=24h")
        data = response.json()
        for day in data["daily_breakdown"]:
            assert "date" in day
            assert "queries" in day


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


class TestAdminAnalyticsAuth:
    def test_get_analytics_requires_admin(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.get("/v1/admin/analytics")
        assert response.status_code == 403

    def test_get_kb_analytics_requires_admin(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.get("/v1/admin/analytics/kb/test-kb")
        assert response.status_code == 403
