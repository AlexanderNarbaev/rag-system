"""Tests for proxy/app/main.py - FastAPI application with mocked dependencies."""
import json
import sys
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

# Before importing main, mock heavy dependencies that load at module level
# This prevents actual imports of qdrant, sentence-transformers, langgraph, etc.
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

# Now we can import the app
from proxy.app.main import (
    app,
    lifespan,
    generate_request_id,
    process_rag_query,
    ChatMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
)


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_rag_pipeline():
    """Mock all RAG pipeline dependencies used in endpoints."""
    with patch("proxy.app.main.hybrid_search") as mock_hybrid, \
         patch("proxy.app.main.rerank_chunks") as mock_rerank, \
         patch("proxy.app.main.deduplicate_chunks") as mock_dedup, \
         patch("proxy.app.main.build_context") as mock_build, \
         patch("proxy.app.main.non_stream_completion") as mock_nonstream, \
         patch("proxy.app.main.stream_completion") as mock_stream, \
         patch("proxy.app.main.extract_version_from_query", return_value=None), \
         patch("proxy.app.main.cache_manager", None), \
         patch("proxy.app.main.log_interaction") as mock_log:
        mock_hybrid.return_value = []
        mock_rerank.return_value = []
        mock_dedup.return_value = []
        mock_build.return_value = ""
        mock_nonstream.return_value = "Mocked LLM response"
        mock_stream.return_value = iter([])
        yield {
            "hybrid_search": mock_hybrid,
            "rerank_chunks": mock_rerank,
            "deduplicate_chunks": mock_dedup,
            "build_context": mock_build,
            "non_stream_completion": mock_nonstream,
            "stream_completion": mock_stream,
            "log_interaction": mock_log,
        }


class TestGenerateRequestId:
    """Tests for generate_request_id in main module."""

    def test_format(self):
        rid = generate_request_id()
        assert rid.startswith("rag_")

    def test_uniqueness(self):
        ids = {generate_request_id() for _ in range(50)}
        assert len(ids) == 50


class TestAppCreation:
    """Tests for FastAPI app creation."""

    def test_app_exists(self):
        assert app is not None
        assert "RAG Proxy" in app.title

    def test_app_has_routes(self):
        routes = [route.path for route in app.routes]
        assert "/v1/health" in routes
        assert "/v1/models" in routes
        assert "/v1/chat/completions" in routes


class TestHealthEndpoint:
    """Tests for /v1/health endpoint."""

    def test_health_mocked_components(self, client):
        with patch("app.retrieval.qdrant_client") as mock_qdrant, \
             patch("requests.get") as mock_get:
            mock_qdrant.get_collections.return_value = {}
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {}
            response = client.get("/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "components" in data

    def test_health_qdrant_error(self, client):
        with patch("app.retrieval.qdrant_client") as mock_qdrant, \
             patch("requests.get") as mock_get:
            mock_qdrant.get_collections.side_effect = Exception("down")
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {}
            response = client.get("/v1/health")
            data = response.json()
            assert data["status"] == "degraded"
            assert "error" in data["components"]["qdrant"]

    def test_health_llm_error(self, client):
        with patch("app.retrieval.qdrant_client") as mock_qdrant, \
             patch("requests.get", side_effect=Exception("refused")):
            mock_qdrant.get_collections.return_value = {}
            response = client.get("/v1/health")
            data = response.json()
            assert data["status"] == "degraded"


class TestModelsEndpoint:
    """Tests for /v1/models endpoint."""

    def test_returns_models_list(self, client):
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 2
        model_ids = [m["id"] for m in data["data"]]
        assert "rag-proxy" in model_ids


class TestChatCompletionsNonStreaming:
    """Tests for /v1/chat/completions in non-streaming mode."""

    def test_basic_chat_completion(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "This is a test answer."
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post("/v1/chat/completions", json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello, how are you?"}],
            "stream": False
        })
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["content"] == "This is a test answer."
        assert data["choices"][0]["message"]["role"] == "assistant"

    def test_chat_completion_with_version(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "Versioned answer."
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post("/v1/chat/completions", json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "What changed in v2.0?"}],
            "rag_version": "2.0",
            "stream": False
        })
        assert response.status_code == 200

    def test_missing_user_message(self, client, mock_rag_pipeline):
        response = client.post("/v1/chat/completions", json={
            "model": "test-model",
            "messages": [{"role": "system", "content": "You are helpful."}],
            "stream": False
        })
        assert response.status_code == 400
        assert "No user message found" in response.text

    def test_chat_completion_with_context(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "Context-based answer"
        mock_rag_pipeline["hybrid_search"].return_value = [
            MagicMock(payload={"text": "Relevant chunk"}, score=0.95)
        ]
        mock_rag_pipeline["rerank_chunks"].return_value = [0]
        mock_rag_pipeline["deduplicate_chunks"].return_value = [
            ({"text": "Relevant chunk", "source_type": "wiki", "title": "T", "doc_title": "D", "version": "1"}, 0.95)
        ]
        mock_rag_pipeline["build_context"].return_value = "[wiki] D / T (v1)\nRelevant chunk"

        response = client.post("/v1/chat/completions", json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "What is Kubernetes?"}],
            "stream": False
        })
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Context-based answer"

    def test_chat_completion_response_structure(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "Answer"
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post("/v1/chat/completions", json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "test"}],
            "temperature": 0.5,
            "max_tokens": 2000,
            "stream": False
        })
        data = response.json()
        assert data["object"] == "chat.completion"
        assert data["model"] == "test-model"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "id" in data
        assert "created" in data


class TestChatCompletionsStreaming:
    """Tests for /v1/chat/completions in streaming mode."""

    def test_streaming_response(self, client, mock_rag_pipeline):
        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "Hello"}}]}
            yield {"id": "2", "choices": [{"delta": {"content": " world"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post("/v1/chat/completions", json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True
        })
        assert response.status_code == 200
        body = response.text
        assert "data:" in body

    def test_streaming_done_sentinel(self, client, mock_rag_pipeline):
        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "test"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post("/v1/chat/completions", json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True
        })
        body = response.text
        assert "[DONE]" in body

    def test_streaming_error_handling(self, client, mock_rag_pipeline):
        mock_rag_pipeline["hybrid_search"].side_effect = Exception("Search failed")

        response = client.post("/v1/chat/completions", json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "query"}],
            "stream": True
        })
        # Streaming errors return the error in the stream body
        body = response.text
        assert "error" in body


class TestProcessRagQuery:
    """Tests for process_rag_query function directly."""

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value="Cached response")

        with patch("proxy.app.main.cache_manager", mock_cache), \
             patch("proxy.app.main.hybrid_search") as mock_search:
            result, context, from_cache = await process_rag_query(
                user_query="test query",
                version=None,
                force_refresh=False,
                stream=False,
            )
            assert result == "Cached response"
            assert from_cache is True
            mock_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_search_results(self):
        with patch("proxy.app.main.cache_manager", None), \
             patch("proxy.app.main.hybrid_search", return_value=[]), \
             patch("proxy.app.main.non_stream_completion", return_value="Answer from LLM"):
            result, context, from_cache = await process_rag_query(
                user_query="test",
                stream=False,
            )
            assert result == "Answer from LLM"
            assert from_cache is False

    @pytest.mark.asyncio
    async def test_streaming_returns_context_and_messages(self):
        mock_search = MagicMock()
        mock_hit = MagicMock()
        mock_hit.payload = {"text": "chunk text"}
        mock_hit.score = 0.9
        mock_search.return_value = [mock_hit]

        with patch("proxy.app.main.cache_manager", None), \
             patch("proxy.app.main.hybrid_search", mock_search), \
             patch("proxy.app.main.rerank_chunks", return_value=[0]), \
             patch("proxy.app.main.deduplicate_chunks") as mock_dedup, \
             patch("proxy.app.main.build_context", return_value="Built context"):
            mock_dedup.return_value = [({"text": "chunk text"}, 0.95)]
            context, messages, _ = await process_rag_query(
                user_query="test",
                stream=True,
            )
            assert context == "Built context"
            assert isinstance(messages, list)
            assert messages[0]["role"] == "system"


class TestLangGraphOrchestratorIntegration:
    """Tests for LangGraph orchestrator integration."""

    def test_langgraph_path_taken_when_enabled(self, client):
        mock_orchestrator = MagicMock()
        mock_orchestrator.ainvoke = AsyncMock(return_value={
            "answer": "Agentic response",
            "context": "some context"
        })

        with patch("proxy.app.main.USE_LANGGRAPH", True), \
             patch("proxy.app.main.orchestrator", mock_orchestrator):
            response = client.post("/v1/chat/completions", json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Complex question"}],
                "stream": False
            })
            assert response.status_code == 200
            data = response.json()
            assert data["choices"][0]["message"]["content"] == "Agentic response"

    def test_langgraph_streaming_path(self, client):
        mock_stream_response = MagicMock()
        mock_orchestrator = MagicMock()
        mock_orchestrator.ainvoke = AsyncMock(return_value=mock_stream_response)

        with patch("proxy.app.main.USE_LANGGRAPH", True), \
             patch("proxy.app.main.orchestrator", mock_orchestrator):
            response = client.post("/v1/chat/completions", json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "stream this"}],
                "stream": True
            })
            assert response.status_code == 200
