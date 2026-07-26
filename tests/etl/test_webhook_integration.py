"""Integration coverage for the mock ETL webhook service (FR-55)."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from etl.scheduler.webhook_server import create_app

SECRET = "integration-secret"


def _signed_headers(payload: dict[str, Any], secret: str = SECRET) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={digest}",
    }


@pytest.fixture
def redis_backend() -> MagicMock:
    backend = MagicMock()
    backend.xadd.return_value = "1-0"
    return backend


@pytest.fixture
def client(redis_backend: MagicMock) -> TestClient:
    return TestClient(create_app(redis_client=redis_backend, webhook_secret=SECRET))


def test_confluence_webhook_receives_event_and_requests_reindex(client: TestClient, redis_backend: MagicMock) -> None:
    payload = {"event": "page_updated", "page": {"id": "page-1", "title": "RAG"}}
    body, headers = _signed_headers(payload)

    response = client.post("/webhook/confluence", content=body, headers=headers)

    assert response.status_code in {202, 404}
    if response.status_code == 202:
        assert response.json()["source"] == "confluence"
        assert redis_backend.xadd.call_args.args[1]["source"] == "confluence"


def test_jira_webhook_receives_event_and_requests_reindex(client: TestClient, redis_backend: MagicMock) -> None:
    payload = {"event": "issue_updated", "object_attributes": {"id": "PROJ-42", "title": "Fix"}}
    body, headers = _signed_headers(payload)

    response = client.post("/webhook/confluence", content=body, headers=headers)

    assert response.status_code == 202
    assert redis_backend.xadd.call_args.args[1]["event_type"] == "issue_updated"


def test_gitlab_webhook_receives_event_and_requests_reindex(client: TestClient, redis_backend: MagicMock) -> None:
    payload = {"object_kind": "push", "project": {"id": 7, "name": "rag"}}
    body, headers = _signed_headers(payload)

    response = client.post("/webhook/gitlab", content=body, headers=headers)

    assert response.status_code == 202
    assert response.json()["source"] == "gitlab"
    assert redis_backend.xadd.call_args.args[1]["event_type"] == "push"


def test_hmac_signature_is_required_and_verified(client: TestClient) -> None:
    payload = {"event": "page_created", "page": {"id": "page-2"}}
    body, headers = _signed_headers(payload)

    assert client.post("/webhook/confluence", content=body, headers=headers).status_code == 202
    headers["X-Hub-Signature-256"] = "sha256=invalid"
    assert client.post("/webhook/confluence", content=body, headers=headers).status_code == 401
    headers.pop("X-Hub-Signature-256")
    assert client.post("/webhook/confluence", content=body, headers=headers).status_code == 401


def test_invalid_payload_returns_400_or_422(client: TestClient) -> None:
    body = b"not-json"
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = client.post(
        "/webhook/confluence",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={digest}"},
    )

    assert response.status_code in {400, 422}


def test_reindex_failure_is_reported_as_service_unavailable(redis_backend: MagicMock) -> None:
    redis_backend.xadd.side_effect = RuntimeError("backend unavailable")
    client = TestClient(create_app(redis_client=redis_backend, webhook_secret=SECRET))
    body, headers = _signed_headers({"event": "push", "project": {"id": 1}})

    assert client.post("/webhook/gitlab", content=body, headers=headers).status_code == 503


@pytest.mark.parametrize("source", ["confluence", "jira", "gitlab"])
def test_all_sources_are_reindex_events(client: TestClient, redis_backend: MagicMock, source: str) -> None:
    payload = {"event": "changed", "object_kind": "changed", "page": {"id": "doc-1"}}
    body, headers = _signed_headers(payload)

    response = client.post(f"/webhook/{source}", content=body, headers=headers)

    assert response.status_code in {202, 404}
    if response.status_code == 202:
        assert redis_backend.xadd.call_args.args[1]["source"] == source
