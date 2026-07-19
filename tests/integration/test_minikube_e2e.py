"""End-to-end integration tests running against minikube deployment.

These tests require a running minikube cluster with the RAG system deployed.
Run: kubectl port-forward svc/rag-system-proxy 9080:8080 -n rag-system &
     python3 scripts/mock_llm_server.py &
     python -m pytest tests/integration/test_minikube_e2e.py -v

Tests verify:
- Health endpoints (liveness, readiness)
- Chat completions (streaming + non-streaming)
- Model listing
- RAG-specific response fields
- Ungrounded response behavior (no knowledge base)
- Error handling
"""

import os

import httpx
import pytest

PROXY_URL = os.getenv("RAG_PROXY_URL", "http://localhost:9080")
MOCK_LLM_URL = os.getenv("MOCK_LLM_URL", "http://localhost:8010")


@pytest.fixture(scope="module")
def client():
    """HTTP client for proxy requests."""
    with httpx.Client(base_url=PROXY_URL, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="module")
def mock_llm_client():
    """HTTP client for mock LLM requests."""
    with httpx.Client(base_url=MOCK_LLM_URL, timeout=5.0) as c:
        yield c


class TestHealthEndpoints:
    """Test health and readiness probes."""

    def test_liveness_returns_200(self, client):
        r = client.get("/v1/health/live")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "alive"

    def test_readiness_returns_200(self, client):
        r = client.get("/v1/health/ready")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ready"
        assert "components" in data
        assert "qdrant" in data["components"]
        assert "llm" in data["components"]

    def test_health_returns_component_status(self, client):
        r = client.get("/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert "components" in data


class TestModelListing:
    """Test /v1/models endpoint."""

    def test_models_returns_list(self, client):
        r = client.get("/v1/models")
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 1

    def test_models_include_rag_suffix(self, client):
        r = client.get("/v1/models")
        data = r.json()
        model_ids = [m["id"] for m in data["data"]]
        assert any("+RAG" in m for m in model_ids), f"No +RAG model found in {model_ids}"


class TestChatCompletions:
    """Test /v1/chat/completions endpoint."""

    def test_non_streaming_returns_openai_format(self, client):
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert len(data["choices"][0]["message"]["content"]) > 0

    def test_non_streaming_includes_rag_fields(self, client):
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "What is RAG?"}],
            },
        )
        data = r.json()
        assert "rag_feedback_id" in data
        assert "rag_confidence" in data
        assert "rag_sources" in data
        assert "rag_knowledge_status" in data

    def test_ungrounded_response_has_notice(self, client):
        """When no knowledge base, response should include ungrounded notice."""
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "What is quantum computing?"}],
            },
        )
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        # Should contain ungrounded notice or clarification
        has_notice = "knowledge base" in content.lower() or "not based" in content.lower()
        has_clarification = "rephrase" in content.lower() or "clarif" in content.lower()
        assert has_notice or has_clarification, f"Expected ungrounded notice, got: {content[:200]}"

    def test_knowledge_status_is_absent(self, client):
        """Without knowledge base, status should be 'absent'."""
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "test query"}],
            },
        )
        data = r.json()
        assert data.get("rag_knowledge_status") == "absent"

    def test_streaming_returns_sse(self, client):
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Hello stream"}],
                "stream": True,
            },
        ) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            body = ""
            for chunk in r.iter_text():
                body += chunk
            assert "[DONE]" in body

    def test_raw_model_passthrough(self, client):
        """Model without +RAG should pass through to LLM directly."""
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello direct"}],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "chat.completion"


class TestMockLLM:
    """Verify mock LLM is working."""

    def test_mock_llm_health(self, mock_llm_client):
        r = mock_llm_client.get("/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_mock_llm_chat(self, mock_llm_client):
        r = mock_llm_client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "test"}],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "choices" in data


class TestErrorHandling:
    """Test error scenarios."""

    def test_missing_messages_returns_422(self, client):
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model+RAG",
            },
        )
        assert r.status_code in (400, 422)  # FastAPI validation error

    def test_empty_messages_returns_400(self, client):
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model+RAG",
                "messages": [],
            },
        )
        assert r.status_code in (400, 422)
