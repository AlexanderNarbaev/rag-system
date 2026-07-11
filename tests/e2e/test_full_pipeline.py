"""E2E tests for the full RAG pipeline: chat completion -> retrieval -> generation."""

import pytest
import requests


@pytest.mark.e2e
class TestChatCompletionRAG:
    """E2E tests for /v1/chat/completions with RAG."""

    def test_chat_completion_rag(self, service_url: str, auth_headers: dict):
        """POST /v1/chat/completions -> verify rag_feedback_id, rag_confidence, rag_sources."""
        payload = {
            "model": "rag-proxy",
            "messages": [{"role": "user", "content": "What is RAG?"}],
            "temperature": 0.2,
            "stream": False,
        }
        resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json=payload,
            headers=auth_headers,
            timeout=30,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:500]}"
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert len(data["choices"][0]["message"]["content"]) > 0
        assert "rag_feedback_id" in data
        assert data["rag_feedback_id"] is not None
        assert "rag_confidence" in data
        assert isinstance(data["rag_confidence"], (int, float))
        assert "rag_sources" in data

    def test_chat_completion_with_version(self, service_url: str, auth_headers: dict):
        """POST /v1/chat/completions with rag_version parameter."""
        payload = {
            "model": "rag-proxy",
            "messages": [{"role": "user", "content": "Explain RAG architecture"}],
            "temperature": 0.1,
            "stream": False,
            "rag_version": "1.0",
        }
        resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json=payload,
            headers=auth_headers,
            timeout=30,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert "rag_feedback_id" in data

    def test_chat_completion_empty_messages(self, service_url: str, auth_headers: dict):
        """POST /v1/chat/completions with no user message -> 400."""
        payload = {
            "model": "rag-proxy",
            "messages": [{"role": "system", "content": "You are a helpful assistant."}],
            "stream": False,
        }
        resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json=payload,
            headers=auth_headers,
            timeout=30,
        )
        assert resp.status_code in (400, 422)


@pytest.mark.e2e
class TestModelList:
    """E2E tests for /v1/models."""

    def test_model_list(self, service_url: str):
        """GET /v1/models -> verify model list returned."""
        resp = requests.get(f"{service_url}/v1/models", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1
        model_ids = [m["id"] for m in data["data"]]
        assert "rag-proxy" in model_ids


@pytest.mark.e2e
class TestHealthProbes:
    """E2E tests for health check endpoints."""

    def test_health_live(self, service_url: str):
        """GET /v1/health/live -> 200 with status alive."""
        resp = requests.get(f"{service_url}/v1/health/live", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alive"

    def test_health_ready(self, service_url: str):
        """GET /v1/health/ready -> returns Qdrant and LLM component status."""
        resp = requests.get(f"{service_url}/v1/health/ready", timeout=10)
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "components" in data
        assert "status" in data

    def test_health(self, service_url: str):
        """GET /v1/health -> full health with components."""
        resp = requests.get(f"{service_url}/v1/health", timeout=10)
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "components" in data


@pytest.mark.e2e
class TestFeedbackFlow:
    """E2E tests for the feedback loop."""

    def test_feedback_flow(self, service_url: str, auth_headers: dict):
        """Chat -> extract feedback_id -> POST /v1/feedback."""
        chat_payload = {
            "model": "rag-proxy",
            "messages": [{"role": "user", "content": "What is RAG?"}],
            "stream": False,
        }
        chat_resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json=chat_payload,
            headers=auth_headers,
            timeout=30,
        )
        if chat_resp.status_code != 200:
            pytest.skip(f"Chat endpoint returned {chat_resp.status_code}, skipping feedback test")
        chat_data = chat_resp.json()
        feedback_id = chat_data.get("rag_feedback_id")
        assert feedback_id is not None, "No feedback_id in chat response"

        feedback_payload = {
            "feedback_id": feedback_id,
            "rating": "positive",
            "comment": "E2E test feedback",
        }
        fb_resp = requests.post(
            f"{service_url}/v1/feedback",
            json=feedback_payload,
            headers=auth_headers,
            timeout=10,
        )
        assert fb_resp.status_code == 200
        fb_data = fb_resp.json()
        assert fb_data["status"] == "ok"

    def test_feedback_negative_with_correction(self, service_url: str, auth_headers: dict):
        """Submit negative feedback with correction."""
        feedback_payload = {
            "feedback_id": "test_feedback_id_nonexistent",
            "rating": "negative",
            "correction": "Corrected answer text",
            "comment": "Test correction",
        }
        fb_resp = requests.post(
            f"{service_url}/v1/feedback",
            json=feedback_payload,
            headers=auth_headers,
            timeout=10,
        )
        assert fb_resp.status_code == 200
        fb_data = fb_resp.json()
        assert fb_data["status"] == "ok"
