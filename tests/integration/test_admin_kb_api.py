# tests/integration/test_admin_kb_api.py
"""Integration tests for the Knowledge Base Admin API endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_kb_manager():
    """Mock KnowledgeBaseManager for API tests."""
    from proxy.app.core.kb_manager import ETLTask, KnowledgeBase

    manager = MagicMock()
    # create_kb returns a KB
    manager.create_kb.return_value = KnowledgeBase(
        id="kb-123",
        name="Test KB",
        description="Test",
        collection_name="kb_test_kb",
        embedding_model="BAAI/bge-m3",
        dense_vector_size=1024,
    )
    # list_kbs returns a list
    manager.list_kbs.return_value = [
        KnowledgeBase(id="kb-1", name="KB One", collection_name="kb_one"),
        KnowledgeBase(id="kb-2", name="KB Two", collection_name="kb_two"),
    ]
    # get_kb returns a KB
    manager.get_kb.return_value = KnowledgeBase(
        id="kb-123",
        name="Test KB",
        collection_name="kb_test_kb",
    )
    # update_kb returns updated KB
    manager.update_kb.return_value = KnowledgeBase(
        id="kb-123",
        name="Updated KB",
        collection_name="kb_test_kb",
    )
    # delete_kb returns True
    manager.delete_kb.return_value = True
    # create_task returns a task
    manager.create_task.return_value = ETLTask(
        id="task-1",
        kb_id="kb-123",
        source_type="confluence",
        source_id="page-1",
    )
    # list_tasks returns a list
    manager.list_tasks.return_value = [
        ETLTask(id="task-1", kb_id="kb-123", source_type="confluence", source_id="page-1", status="completed"),
    ]
    # get_task returns a task
    manager.get_task.return_value = ETLTask(
        id="task-1",
        kb_id="kb-123",
        source_type="confluence",
        source_id="page-1",
        status="completed",
    )
    return manager


@pytest.fixture
def client(mock_kb_manager):
    """Create a TestClient with mocked KB manager."""
    from fastapi import FastAPI

    from proxy.app.api.admin_kb import router
    from proxy.app.auth.jwt import UserContext, get_auth_context

    app = FastAPI()
    app.include_router(router)

    admin_user = UserContext(
        user_id="test-admin",
        username="test-admin",
        roles=["admin"],
        groups=["admins"],
    )
    app.dependency_overrides[get_auth_context] = lambda: admin_user

    # Patch kb_manager in main module
    with (
        patch("proxy.app.main.kb_manager", mock_kb_manager),
        patch("proxy.app.api.admin_kb._get_kb_manager", return_value=mock_kb_manager),
    ):
        yield TestClient(app)


class TestCreateKnowledgeBase:
    """Test POST /v1/admin/kb/"""

    def test_create_kb_success(self, client):
        response = client.post(
            "/v1/admin/kb/",
            json={
                "name": "Production Docs",
                "description": "Production documentation",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test KB"
        assert data["id"] == "kb-123"

    def test_create_kb_missing_name(self, client):
        response = client.post("/v1/admin/kb/", json={"description": "No name"})
        assert response.status_code == 422  # Validation error


class TestListKnowledgeBases:
    """Test GET /v1/admin/kb/"""

    def test_list_kbs(self, client):
        response = client.get("/v1/admin/kb/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["knowledge_bases"]) == 2

    def test_list_kbs_include_deleted(self, client):
        response = client.get("/v1/admin/kb/?include_deleted=true")
        assert response.status_code == 200


class TestGetKnowledgeBase:
    """Test GET /v1/admin/kb/{kb_id}"""

    def test_get_kb_success(self, client):
        response = client.get("/v1/admin/kb/kb-123")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "kb-123"

    def test_get_kb_not_found(self, client, mock_kb_manager):
        mock_kb_manager.get_kb.return_value = None
        response = client.get("/v1/admin/kb/nonexistent")
        assert response.status_code == 404


class TestUpdateKnowledgeBase:
    """Test PUT /v1/admin/kb/{kb_id}"""

    def test_update_kb_success(self, client):
        response = client.put("/v1/admin/kb/kb-123", json={"name": "Updated KB"})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated KB"


class TestDeleteKnowledgeBase:
    """Test DELETE /v1/admin/kb/{kb_id}"""

    def test_soft_delete(self, client):
        response = client.delete("/v1/admin/kb/kb-123")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["hard"] is False

    def test_hard_delete(self, client):
        response = client.delete("/v1/admin/kb/kb-123?hard=true")
        assert response.status_code == 200
        data = response.json()
        assert data["hard"] is True


class TestETLTasks:
    """Test ETL task endpoints."""

    def test_create_task(self, client):
        response = client.post(
            "/v1/admin/kb/kb-123/tasks",
            json={
                "source_type": "confluence",
                "source_id": "page-123",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["source_type"] == "confluence"
        assert data["id"] == "task-1"

    def test_list_tasks(self, client):
        response = client.get("/v1/admin/kb/kb-123/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    def test_get_task(self, client):
        response = client.get("/v1/admin/kb/kb-123/tasks/task-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "task-1"
        assert data["status"] == "completed"
