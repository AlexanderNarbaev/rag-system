# tests/etl/test_webhook_server.py
"""Tests for webhook server: Confluence/GitLab event ingestion."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_redis_client():
    client = MagicMock()
    client.xadd = MagicMock(return_value="1719000000000-0")
    client.ping = MagicMock(return_value=True)
    return client


@pytest.fixture
def webhook_app(mock_redis_client):
    from etl.scheduler.webhook_server import create_app

    app = create_app(
        redis_client=mock_redis_client,
        webhook_secret="test-secret-key",
    )
    return app


@pytest.fixture
def webhook_client(webhook_app):
    return TestClient(webhook_app)


def _make_signature(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class TestWebhookServerHealth:
    def test_health_check(self, webhook_client):
        response = webhook_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestConfluenceWebhook:
    CONFLUENCE_PAYLOAD = {
        "event": "page_created",
        "page": {
            "id": "123456",
            "title": "RAG Architecture Guide",
            "space": {"key": "DEV"},
            "version": {"number": 2},
            "body": {"storage": {"value": "<p>RAG combines retrieval and generation.</p>"}},
        },
        "timestamp": "2025-06-20T14:00:00Z",
        "user": {"username": "ivanov"},
    }

    def _post_confluence(self, client, payload=None, secret="test-secret-key"):
        if payload is None:
            payload = self.CONFLUENCE_PAYLOAD
        body = json.dumps(payload).encode()
        sig = _make_signature(secret, body)
        return client.post(
            "/webhook/confluence",
            content=body,
            headers={
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )

    def test_valid_confluence_event_returns_202(self, webhook_client, mock_redis_client):
        response = self._post_confluence(webhook_client)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"

    def test_confluence_event_produces_to_stream(self, webhook_client, mock_redis_client):
        self._post_confluence(webhook_client)
        mock_redis_client.xadd.assert_called_once()
        args, _ = mock_redis_client.xadd.call_args
        assert args[0] == "etl:events"
        fields = args[1]
        assert fields["event_type"] == "page_created"
        assert fields["source"] == "confluence"

    def test_invalid_signature_returns_401(self, webhook_client):
        body = json.dumps(self.CONFLUENCE_PAYLOAD).encode()
        response = webhook_client.post(
            "/webhook/confluence",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=invalidhash",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 401

    def test_missing_signature_header_returns_401(self, webhook_client):
        body = json.dumps(self.CONFLUENCE_PAYLOAD).encode()
        response = webhook_client.post(
            "/webhook/confluence",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 401

    def test_invalid_json_body_returns_422(self, webhook_client):
        sig = _make_signature("test-secret-key", b"not-json")
        response = webhook_client.post(
            "/webhook/confluence",
            content=b"not-json",
            headers={
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 422

    def test_redis_unavailable_returns_503(self, webhook_app, mock_redis_client):
        mock_redis_client.xadd.side_effect = Exception("connection refused")
        from etl.scheduler.webhook_server import create_app

        app = create_app(
            redis_client=mock_redis_client,
            webhook_secret="test-secret-key",
        )
        client = TestClient(app)
        body = json.dumps(self.CONFLUENCE_PAYLOAD).encode()
        sig = _make_signature("test-secret-key", body)
        response = client.post(
            "/webhook/confluence",
            content=body,
            headers={
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 503

    def test_confluence_page_updated_event(self, webhook_client, mock_redis_client):
        payload = {
            "event": "page_updated",
            "page": {
                "id": "789",
                "title": "Updated Title",
                "space": {"key": "OPS"},
                "version": {"number": 3},
            },
            "timestamp": "2025-06-20T15:00:00Z",
        }
        body = json.dumps(payload).encode()
        sig = _make_signature("test-secret-key", body)
        response = webhook_client.post(
            "/webhook/confluence",
            content=body,
            headers={
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202
        assert mock_redis_client.xadd.call_args[0][1]["event_type"] == "page_updated"

    def test_confluence_page_deleted_event(self, webhook_client, mock_redis_client):
        payload = {
            "event": "page_deleted",
            "page": {"id": "999", "title": "Deleted Page"},
            "timestamp": "2025-06-20T16:00:00Z",
        }
        body = json.dumps(payload).encode()
        sig = _make_signature("test-secret-key", body)
        response = webhook_client.post(
            "/webhook/confluence",
            content=body,
            headers={
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 202


class TestGitLabWebhook:
    GITLAB_PUSH_PAYLOAD = {
        "object_kind": "push",
        "event_name": "push",
        "project": {"id": 42, "name": "rag-system"},
        "commits": [
            {
                "id": "abc123def456",
                "message": "Add hybrid search module",
                "title": "Add hybrid search module",
                "author": {"name": "ivanov", "email": "ivanov@company.com"},
                "timestamp": "2025-06-18T12:00:00Z",
            }
        ],
        "repository": {"name": "rag-system", "url": "git@gitlab:team/rag-system.git"},
    }

    GITLAB_MERGE_PAYLOAD = {
        "object_kind": "merge_request",
        "event_name": "merge_request",
        "user": {"username": "ivanov"},
        "object_attributes": {
            "id": 8675309,
            "iid": 100,
            "title": "Add streaming ETL",
            "description": "Real-time webhook-based ETL pipeline",
            "state": "opened",
            "source_branch": "feature/streaming-etl",
            "target_branch": "main",
        },
    }

    GITLAB_WIKI_PAYLOAD = {
        "object_kind": "wiki_page",
        "event_name": "wiki_page",
        "user": {"username": "petrov"},
        "object_attributes": {
            "title": "Streaming ETL Architecture",
            "content": "# Streaming ETL\n\nWebhook-driven pipeline.",
            "action": "create",
            "slug": "streaming-etl-arch",
        },
    }

    def _post_gitlab(self, client, payload=None, secret="test-secret-key"):
        if payload is None:
            payload = self.GITLAB_PUSH_PAYLOAD
        body = json.dumps(payload).encode()
        sig = _make_signature(secret, body)
        return client.post(
            "/webhook/gitlab",
            content=body,
            headers={
                "X-Hub-Signature-256": f"sha256={sig}",
                "Content-Type": "application/json",
            },
        )

    def test_valid_gitlab_push_returns_202(self, webhook_client):
        response = self._post_gitlab(webhook_client)
        assert response.status_code == 202

    def test_gitlab_push_event_produces_to_stream(self, webhook_client, mock_redis_client):
        self._post_gitlab(webhook_client)
        mock_redis_client.xadd.assert_called_once()
        args, _ = mock_redis_client.xadd.call_args
        assert args[1]["source"] == "gitlab"
        assert args[1]["event_type"] == "push"

    def test_gitlab_merge_request_event(self, webhook_client, mock_redis_client):
        self._post_gitlab(webhook_client, self.GITLAB_MERGE_PAYLOAD)
        args, _ = mock_redis_client.xadd.call_args
        assert args[1]["event_type"] == "merge_request"

    def test_gitlab_wiki_page_event(self, webhook_client, mock_redis_client):
        self._post_gitlab(webhook_client, self.GITLAB_WIKI_PAYLOAD)
        args, _ = mock_redis_client.xadd.call_args
        assert args[1]["event_type"] == "wiki_page"

    def test_gitlab_invalid_signature_returns_401(self, webhook_client):
        body = json.dumps(self.GITLAB_PUSH_PAYLOAD).encode()
        response = webhook_client.post(
            "/webhook/gitlab",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=invalid",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 401

    def test_gitlab_missing_signature_returns_401(self, webhook_client):
        body = json.dumps(self.GITLAB_PUSH_PAYLOAD).encode()
        response = webhook_client.post(
            "/webhook/gitlab",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 401
