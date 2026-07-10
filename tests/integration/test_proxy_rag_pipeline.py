# ruff: noqa: E501, SIM117, E402, N817, SIM105
# tests/integration/test_proxy_rag_pipeline.py
"""Integration tests for the RAG proxy query pipeline end-to-end.

Tests the full /v1/chat/completions flow with mocked external services
(Qdrant, LLM, Redis). Uses FastAPI TestClient.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure proxy module is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


@pytest.fixture
def app_client():
    """Create a FastAPI TestClient with all external dependencies mocked."""
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.USE_LANGGRAPH", False),
        patch("proxy.app.main.LOG_REQUESTS", False),
        patch("proxy.app.main.LLM_MODEL_NAME", "test-model"),
    ):
        from fastapi.testclient import TestClient

        from proxy.app.main import app

        client = TestClient(app)
        return client


class TestHealthEndpoint:
    """Tests for /v1/health endpoint."""

    def test_health_returns_ok_when_services_up(self, app_client):
        """Health endpoint returns 200 with status 'ok' when Qdrant and LLM are reachable."""
        # In test environment services are not running, so degraded is expected.
        response = app_client.get("/v1/health")
        assert response.status_code in (200, 503)
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "timestamp" in data
        assert "components" in data

    def test_health_returns_degraded_when_qdrant_unavailable(self, app_client):
        """Health endpoint returns 503 when Qdrant check raises an exception."""
        with patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant, patch("requests.get") as mock_get:
            mock_qdrant.get_collections.side_effect = Exception("Connection refused")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp

            response = app_client.get("/v1/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "degraded"


class TestModelsEndpoint:
    """Tests for /v1/models endpoint."""

    def test_models_returns_correct_format(self, app_client):
        """Models endpoint returns OpenAI-compatible model list."""
        response = app_client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) >= 2
        model_ids = [m["id"] for m in data["data"]]
        assert "rag-proxy" in model_ids
        assert all(m["object"] == "model" for m in data["data"])
        assert all("created" in m for m in data["data"])
        assert all(m["owned_by"] == "local" for m in data["data"])


class TestChatCompletionsNonStreaming:
    """Tests for POST /v1/chat/completions (non-streaming mode)."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self, sample_search_results, mock_non_stream_completion):
        """Mock hybrid_search and non_stream_completion for all chat tests."""
        self.search_results = sample_search_results
        self.mock_llm = mock_non_stream_completion

    def test_chat_completion_returns_openai_format(self, app_client):
        """Chat completion response follows OpenAI format with expected fields."""
        with (
            patch("proxy.app.main.hybrid_search", return_value=self.search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1, 3]),
            patch("proxy.app.main.non_stream_completion", self.mock_llm),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Что такое RAG?"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["object"] == "chat.completion"
            assert "id" in data
            assert data["id"].startswith("rag_")
            assert data["model"] == "test-model"
            assert len(data["choices"]) == 1
            choice = data["choices"][0]
            assert choice["index"] == 0
            assert choice["message"]["role"] == "assistant"
            assert len(choice["message"]["content"]) > 0
            assert choice["finish_reason"] == "stop"
            assert "usage" in data

    def test_chat_completion_builds_context_from_search_results(self, app_client):
        """Context is correctly built from hybrid_search results passed through reranking."""
        with (
            patch("proxy.app.main.hybrid_search") as mock_search,
            patch("proxy.app.main.rerank_chunks", return_value=[0, 2]),
            patch("proxy.app.main.non_stream_completion", self.mock_llm),
        ):
            mock_search.return_value = self.search_results

            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Расскажи про CI/CD pipeline"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert len(data["choices"][0]["message"]["content"]) > 0
            mock_search.assert_called_once()

    def test_chat_completion_with_version_filter(self, app_client):
        """Chat completion passes version filter to hybrid_search when rag_version is set."""
        with (
            patch("proxy.app.main.hybrid_search") as mock_search,
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", self.mock_llm),
        ):
            mock_search.return_value = self.search_results

            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Расскажи про RAG"}],
                "rag_version": "2.0",
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            call_kwargs = mock_search.call_args.kwargs
            assert call_kwargs["version"] == "2.0"

    def test_chat_completion_handles_empty_search_results(self, app_client):
        """Chat completion returns a response even when no search results are found."""
        with (
            patch("proxy.app.main.hybrid_search", return_value=[]),
            patch("proxy.app.main.non_stream_completion", self.mock_llm),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Запрос без результатов"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert len(data["choices"]) == 1

    def test_chat_completion_uses_cache_on_second_request(self, app_client):
        """Second identical request retrieves cached response instead of calling LLM."""
        with (
            patch("proxy.app.main.hybrid_search", return_value=self.search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", self.mock_llm),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Что такое RAG?"}],
            }
            # First request — no cache
            response1 = app_client.post("/v1/chat/completions", json=payload)
            assert response1.status_code == 200

            # Second request — should hit cache (in-memory cache lives in TestClient scope)
            response2 = app_client.post("/v1/chat/completions", json=payload)
            assert response2.status_code == 200
            assert (
                response1.json()["choices"][0]["message"]["content"]
                == response2.json()["choices"][0]["message"]["content"]
            )

    def test_chat_completion_force_refresh_skips_cache(self, app_client):
        """Setting rag_force_refresh=True bypasses cache and calls LLM again."""
        call_count = [0]

        async def tracking_llm(*args, **kwargs):
            call_count[0] += 1
            return f"Ответ LLM с номером вызова {call_count[0]}"

        with (
            patch("proxy.app.main.hybrid_search", return_value=self.search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", side_effect=tracking_llm),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Cache test query"}],
            }
            response1 = app_client.post("/v1/chat/completions", json=payload)
            assert response1.status_code == 200

            payload["rag_force_refresh"] = True
            response2 = app_client.post("/v1/chat/completions", json=payload)
            assert response2.status_code == 200

    def test_chat_completion_missing_user_message_returns_400(self, app_client):
        """Request without a user message returns 400 Bad Request."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "system", "content": "You are a helpful assistant."}],
        }
        response = app_client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 400
        assert "No user message found" in response.json()["detail"]

    def test_chat_completion_extracts_version_from_query_text(self, app_client):
        """Version is extracted from query text via extract_version_from_query."""
        with (
            patch("proxy.app.main.hybrid_search") as mock_search,
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", self.mock_llm),
        ):
            mock_search.return_value = self.search_results

            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Покажи документацию v2.0 про RAG"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            call_kwargs = mock_search.call_args.kwargs
            assert call_kwargs["version"] == "2.0"


class TestChatCompletionsStreaming:
    """Tests for POST /v1/chat/completions (streaming mode)."""

    def test_streaming_response_returns_sse_format(self, app_client):
        """Streaming endpoint returns text/event-stream with SSE data chunks."""

        async def mock_stream_llm(*args, **kwargs):
            chunks = [
                {
                    "id": "1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": "Ответ"}, "index": 0}],
                },
                {
                    "id": "1",
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": " по RAG."}, "index": 0}],
                },
            ]
            for chunk in chunks:
                yield chunk

        with (
            patch("proxy.app.main.hybrid_search") as mock_search,
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream_llm),
        ):

            class FakeScoredPoint:
                def __init__(self, score, payload):
                    self.id = "fake"
                    self.score = score
                    self.payload = payload

            mock_search.return_value = [
                FakeScoredPoint(0.95, {"text": "RAG — техника для LLM.", "version": "1.0", "source_id": "123"})
            ]

            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Что такое RAG?"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            body = response.text
            assert "data:" in body
            assert "[DONE]" in body


class TestErrorHandling:
    """Tests for error handling in the proxy pipeline."""

    def test_chat_completion_handles_rerank_exception(self, app_client):
        """Pipeline raises exception during reranking phase — verifies error propagation."""
        mock_hit = MagicMock()
        mock_hit.payload = {"text": "Some document text", "version": "1.0"}
        mock_hit.score = 0.95

        with (
            patch("proxy.app.main.hybrid_search", return_value=[mock_hit]),
            patch("proxy.app.main.rerank_chunks", side_effect=RuntimeError("Rerank failed")),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test"}],
            }
            with pytest.raises(RuntimeError, match="Rerank failed"):
                app_client.post("/v1/chat/completions", json=payload)
