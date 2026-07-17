"""Tests for expert KB management API — FR-21."""

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
def expert_ctx():
    ctx = MagicMock()
    ctx.is_admin = False
    ctx.is_expert = True
    ctx.is_authenticated = True
    ctx.user_id = "expert-1"
    ctx.username = "expert"
    ctx.roles = ["expert"]
    ctx.groups = []
    ctx.access_level = "confidential"
    ctx.namespace = ""
    return ctx


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
    ctx.is_expert = False
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


class TestExpertKBDocumentReview:
    def test_review_document_as_expert(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.post(
            "/v1/expert/kb/test-kb/documents/review",
            json={"chunk_id": "chunk-001", "rating": "approved", "comment": "Looks good"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["review_id"].startswith("rev-")
        assert data["kb_id"] == "test-kb"
        assert data["chunk_id"] == "chunk-001"
        assert data["rating"] == "approved"
        assert "created_at" in data

    def test_review_with_corrections(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.post(
            "/v1/expert/kb/test-kb/documents/review",
            json={
                "chunk_id": "chunk-002",
                "rating": "needs_revision",
                "comment": "Update text",
                "corrections": {"title": "New Title", "text": "Updated text"},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["rating"] == "needs_revision"

    def test_review_rejects_invalid_rating(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.post(
            "/v1/expert/kb/test-kb/documents/review",
            json={"chunk_id": "chunk-003", "rating": "invalid_rating", "comment": ""},
        )
        assert response.status_code == 422


class TestExpertKBDocumentFlagging:
    def test_flag_document_as_expert(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.post(
            "/v1/expert/kb/test-kb/documents/flag",
            json={"chunk_id": "chunk-outdated", "reason": "outdated", "comment": "This info is from 2023"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["flag_id"].startswith("flag-")
        assert data["kb_id"] == "test-kb"
        assert data["chunk_id"] == "chunk-outdated"
        assert data["reason"] == "outdated"
        assert data["status"] == "open"
        assert "flagged_at" in data

    def test_flag_rejects_invalid_reason(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.post(
            "/v1/expert/kb/test-kb/documents/flag", json={"chunk_id": "chunk-x", "reason": "bad_reason", "comment": ""}
        )
        assert response.status_code == 422

    def test_flag_all_valid_reasons(self, client, expert_ctx):
        _override_auth(expert_ctx)
        for reason in ("duplicate", "outdated", "inaccurate", "spam"):
            response = client.post(
                "/v1/expert/kb/test-kb/documents/flag",
                json={"chunk_id": f"chunk-{reason}", "reason": reason, "comment": f"Flagged as {reason}"},
            )
            assert response.status_code == 201
            assert response.json()["reason"] == reason


class TestExpertKBListFlags:
    def test_list_flags_as_expert(self, client, expert_ctx):
        _override_auth(expert_ctx)
        # First, flag a document
        client.post(
            "/v1/expert/kb/test-kb-flags/documents/flag",
            json={"chunk_id": "chunk-a", "reason": "duplicate", "comment": ""},
        )

        response = client.get("/v1/expert/kb/test-kb-flags/flags")
        assert response.status_code == 200
        data = response.json()
        assert data["kb_id"] == "test-kb-flags"
        assert data["total"] >= 1

    def test_list_flags_filter_by_status(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.get("/v1/expert/kb/test-kb-flags/flags?status=open")
        assert response.status_code == 200
        data = response.json()
        for flag in data["flags"]:
            assert flag["status"] == "open"


class TestExpertKBReindex:
    def test_trigger_reindex_as_expert(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.post(
            "/v1/expert/kb/test-kb/reindex", json={"source_type": "confluence", "source_id": "page-123"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["kb_id"] == "test-kb"
        assert data["reindex_id"].startswith("reidx-")
        assert data["source_type"] == "confluence"
        assert data["source_id"] == "page-123"
        assert data["status"] == "queued"

    def test_trigger_reindex_full_kb(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.post("/v1/expert/kb/test-kb/reindex", json={})
        assert response.status_code == 201
        data = response.json()
        assert data["source_type"] is None
        assert data["source_id"] is None

    def test_trigger_reindex_source_type_only(self, client, expert_ctx):
        _override_auth(expert_ctx)
        response = client.post("/v1/expert/kb/test-kb/reindex", json={"source_type": "jira"})
        assert response.status_code == 201
        data = response.json()
        assert data["source_type"] == "jira"
        assert data["source_id"] is None


@pytest.fixture(autouse=True)
def _enable_auth(monkeypatch):
    """Re-enable auth for auth-specific tests."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    import proxy.app.shared.config as _cfg
    import proxy.app.auth.rbac as _rbac

    monkeypatch.setattr(_cfg, "AUTH_ENABLED", True)
    monkeypatch.setattr(_cfg, "RBAC_ENABLED", True)
    monkeypatch.setattr(_rbac, "RBAC_ENABLED", True)

class TestExpertKBAuth:
    def test_review_requires_expert(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.post(
            "/v1/expert/kb/test-kb/documents/review", json={"chunk_id": "chunk-1", "rating": "approved", "comment": ""}
        )
        assert response.status_code == 403

    def test_flag_requires_expert(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.post(
            "/v1/expert/kb/test-kb/documents/flag", json={"chunk_id": "chunk-1", "reason": "outdated", "comment": ""}
        )
        assert response.status_code == 403

    def test_list_flags_requires_expert(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.get("/v1/expert/kb/test-kb/flags")
        assert response.status_code == 403

    def test_reindex_requires_expert(self, client, user_ctx):
        _override_auth(user_ctx)
        response = client.post("/v1/expert/kb/test-kb/reindex", json={})
        assert response.status_code == 403

    def test_admin_can_access_expert_endpoints(self, client, admin_ctx):
        _override_auth(admin_ctx)
        response = client.get("/v1/expert/kb/test-kb/flags")
        assert response.status_code == 200
