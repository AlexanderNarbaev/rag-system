# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""E2E tests for the full RAG pipeline with mocked external services.

Tests the complete flow: HTTP request -> FastAPI -> RAG pipeline -> response.
All external services (Qdrant, LLM, embedder, reranker) are mocked so tests
run without any infrastructure dependencies.

Run with: pytest tests/e2e/test_full_pipeline.py -v
"""

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock heavy external dependencies before importing the app
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
    "bcrypt",
]

for mod in _modules_to_mock:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from proxy.app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _disable_auth(monkeypatch):
    """Disable authentication for all tests in this module."""
    import proxy.app.auth.jwt as _jwt
    import proxy.app.shared.config as _cfg

    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(_cfg, "AUTH_ENABLED", False)
    monkeypatch.setattr(_jwt, "AUTH_ENABLED", False)


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_rag_pipeline():
    """Mock all RAG pipeline dependencies used in endpoints."""
    with (
        patch("proxy.app.main.hybrid_search") as mock_hybrid,
        patch("proxy.app.main.rerank_chunks") as mock_rerank,
        patch("proxy.app.main.deduplicate_chunks") as mock_dedup,
        patch("proxy.app.main.build_context") as mock_build,
        patch("proxy.app.main.non_stream_completion") as mock_nonstream,
        patch("proxy.app.main.stream_completion") as mock_stream,
        patch("proxy.app.main.extract_version_from_query", return_value=None),
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.log_interaction") as mock_log,
    ):
        mock_hybrid.return_value = []
        mock_rerank.return_value = []
        mock_dedup.return_value = []
        mock_build.return_value = ""
        mock_nonstream.return_value = "Mocked LLM response about RAG technology."
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


@pytest.fixture
def mock_rag_pipeline_with_context():
    """Mock RAG pipeline returning actual context chunks from retrieval."""
    chunk_a = {
        "text": "RAG (Retrieval-Augmented Generation) combines retrieval with generation.",
        "source_type": "confluence",
        "title": "RAG Overview",
        "doc_title": "Architecture Guide",
        "version": "2.0",
    }
    chunk_b = {
        "text": "Hybrid search uses both dense and sparse vectors in Qdrant.",
        "source_type": "gitlab_commit",
        "title": "hybrid search commit",
        "doc_title": "Commit a1b2c3d",
        "version": "latest",
    }

    with (
        patch("proxy.app.main.hybrid_search") as mock_hybrid,
        patch("proxy.app.main.rerank_chunks") as mock_rerank,
        patch("proxy.app.main.deduplicate_chunks") as mock_dedup,
        patch("proxy.app.main.build_context") as mock_build,
        patch("proxy.app.main.non_stream_completion") as mock_nonstream,
        patch("proxy.app.main.stream_completion") as mock_stream,
        patch("proxy.app.main.extract_version_from_query", return_value=None),
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.log_interaction") as mock_log,
    ):
        mock_hybrid.return_value = [
            MagicMock(payload=chunk_a, score=0.95),
            MagicMock(payload=chunk_b, score=0.85),
        ]
        mock_rerank.return_value = [0, 1]
        mock_dedup.return_value = [(chunk_a, 0.95), (chunk_b, 0.85)]
        mock_build.return_value = "[confluence] Architecture Guide / RAG Overview (v2.0)\nRAG combines retrieval with generation."
        mock_nonstream.return_value = "Based on the context, RAG combines retrieval with generation for accurate responses."
        mock_stream.return_value = iter([])
        yield {
            "hybrid_search": mock_hybrid,
            "rerank_chunks": mock_rerank,
            "deduplicate_chunks": mock_dedup,
            "build_context": mock_build,
            "non_stream_completion": mock_nonstream,
            "stream_completion": mock_stream,
            "log_interaction": mock_log,
            "chunks": [chunk_a, chunk_b],
        }


@pytest.fixture
def mock_feedback_logger():
    """Mock the HITL feedback logger to avoid file I/O."""
    with patch("proxy.app.core.hitl.get_logger") as mock_get_logger:
        mock_logger = MagicMock()
        mock_logger.log_feedback = MagicMock()
        mock_get_logger.return_value = mock_logger
        yield mock_logger


# ---------------------------------------------------------------------------
# Test: Chat Completion with RAG Context (Non-Streaming)
# ---------------------------------------------------------------------------


class TestChatCompletionWithRAGContext:
    """E2E tests for /v1/chat/completions — full pipeline with mocked services."""

    def test_basic_chat_returns_openai_compatible_response(self, client, mock_rag_pipeline):
        """POST /v1/chat/completions returns a valid OpenAI-compatible response."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        # OpenAI compatibility checks
        assert data["object"] == "chat.completion"
        assert "id" in data
        assert "created" in data
        assert data["model"] == "rag-proxy"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert len(data["choices"][0]["message"]["content"]) > 0

    def test_chat_response_includes_rag_extensions(self, client, mock_rag_pipeline):
        """Response includes RAG-specific extensions: feedback_id, confidence, sources."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "Explain RAG architecture"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        # RAG extension fields
        assert "rag_feedback_id" in data
        assert data["rag_feedback_id"] is not None
        assert data["rag_feedback_id"].startswith("fb_")
        assert "rag_confidence" in data
        assert isinstance(data["rag_confidence"], (int, float))
        assert 0.0 <= data["rag_confidence"] <= 1.0
        assert "rag_sources" in data
        assert isinstance(data["rag_sources"], list)

    def test_chat_with_retrieved_context_returns_sources(self, client, mock_rag_pipeline_with_context):
        """When retrieval finds chunks, response includes source citations."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Sources from retrieval
        assert len(data["rag_sources"]) > 0
        source = data["rag_sources"][0]
        assert "chunk_id" in source
        assert "source" in source
        assert "title" in source
        assert "version" in source
        assert "relevance" in source
        assert "text_preview" in source

    def test_chat_with_version_parameter(self, client, mock_rag_pipeline):
        """Request with rag_version parameter passes version to pipeline."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What changed?"}],
                "rag_version": "2.0",
                "stream": False,
            },
        )
        assert response.status_code == 200
        # Verify hybrid_search was called with version
        mock_rag_pipeline["hybrid_search"].assert_called_once()
        call_kwargs = mock_rag_pipeline["hybrid_search"].call_args
        assert call_kwargs.kwargs.get("version") == "2.0" or call_kwargs[1].get("version") == "2.0"

    def test_chat_with_force_refresh_bypasses_cache(self, client, mock_rag_pipeline):
        """Request with rag_force_refresh=True should not read from cache."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "Latest info"}],
                "rag_force_refresh": True,
                "stream": False,
            },
        )
        assert response.status_code == 200

    def test_chat_with_custom_temperature_and_max_tokens(self, client, mock_rag_pipeline):
        """Custom temperature and max_tokens are passed through."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "test"}],
                "temperature": 0.7,
                "max_tokens": 2048,
                "stream": False,
            },
        )
        assert response.status_code == 200

    def test_chat_with_multi_turn_conversation(self, client, mock_rag_pipeline):
        """Multi-turn conversation with system + assistant + user messages."""
        mock_rag_pipeline["non_stream_completion"].return_value = "Follow-up answer"
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "What is RAG?"},
                    {"role": "assistant", "content": "RAG is Retrieval-Augmented Generation."},
                    {"role": "user", "content": "How does it work?"},
                ],
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Follow-up answer"

    def test_chat_missing_user_message_returns_400(self, client, mock_rag_pipeline):
        """Request with no user message returns 400."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "system", "content": "You are helpful."}],
                "stream": False,
            },
        )
        assert response.status_code == 400
        assert "No user message found" in response.text

    def test_chat_empty_messages_returns_error(self, client, mock_rag_pipeline):
        """Request with empty messages list returns client error."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [],
                "stream": False,
            },
        )
        assert response.status_code in (400, 422)

    def test_chat_skip_generation_returns_chunks_only(self, client, mock_rag_pipeline_with_context):
        """rag_skip_generation=True returns empty content with sources."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "rag_skip_generation": True,
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == ""
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert len(data["rag_sources"]) == 2
        # LLM should NOT be called
        mock_rag_pipeline_with_context["non_stream_completion"].assert_not_called()


# ---------------------------------------------------------------------------
# Test: Streaming Chat Completion
# ---------------------------------------------------------------------------


class TestStreamingChatCompletion:
    """E2E tests for streaming /v1/chat/completions."""

    def test_streaming_returns_sse_events(self, client, mock_rag_pipeline):
        """Streaming response returns Server-Sent Events format."""
        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "RAG "}}]}
            yield {"id": "2", "choices": [{"delta": {"content": "is "}}]}
            yield {"id": "3", "choices": [{"delta": {"content": "great."}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        body = response.text
        # Must contain SSE data lines
        assert "data:" in body
        # Must contain the streamed content
        assert "RAG" in body
        assert "great." in body

    def test_streaming_ends_with_done_sentinel(self, client, mock_rag_pipeline):
        """Streaming response ends with [DONE] sentinel."""
        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "test"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        body = response.text
        assert "[DONE]" in body

    def test_streaming_includes_rag_metadata(self, client, mock_rag_pipeline):
        """Streaming response includes rag_feedback_id and rag_confidence before [DONE]."""
        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "Answer"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "test"}],
                "stream": True,
            },
        )
        body = response.text
        # Find the metadata line (JSON with rag_feedback_id)
        metadata_found = False
        for line in body.split("\n"):
            if line.startswith("data: ") and "rag_feedback_id" in line:
                data = json.loads(line[len("data: "):])
                assert "rag_feedback_id" in data
                assert "rag_confidence" in data
                metadata_found = True
                break
        assert metadata_found, "RAG metadata not found in streaming response"

    def test_streaming_handles_search_failure_gracefully(self, client, mock_rag_pipeline):
        """When search fails, streaming returns error in the stream, not HTTP 500."""
        mock_rag_pipeline["hybrid_search"].side_effect = Exception("Qdrant unavailable")

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "test"}],
                "stream": True,
            },
        )
        # Should still be 200 — errors go into the stream
        assert response.status_code == 200
        body = response.text
        assert "error" in body

    def test_streaming_content_type_is_event_stream(self, client, mock_rag_pipeline):
        """Streaming response has text/event-stream content type."""
        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "ok"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "test"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Test: Feedback Submission
# ---------------------------------------------------------------------------


class TestFeedbackSubmission:
    """E2E tests for the feedback loop."""

    def test_positive_feedback_accepted(self, client, mock_rag_pipeline, mock_feedback_logger):
        """POST /v1/feedback with positive rating returns 200."""
        with patch("proxy.app.shared.config.ENRICHMENT_ENABLED", False):
            response = client.post(
                "/v1/feedback",
                json={
                    "feedback_id": "fb_test123",
                    "rating": "positive",
                    "comment": "Great answer!",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"

    def test_negative_feedback_with_correction_accepted(self, client, mock_rag_pipeline, mock_feedback_logger):
        """POST /v1/feedback with negative rating + correction returns 200."""
        with patch("proxy.app.shared.config.ENRICHMENT_ENABLED", False):
            response = client.post(
                "/v1/feedback",
                json={
                    "feedback_id": "fb_test456",
                    "rating": "negative",
                    "correction": "The correct answer is...",
                    "comment": "Wrong information",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"

    def test_feedback_missing_required_field_returns_422(self, client, mock_rag_pipeline):
        """POST /v1/feedback without feedback_id returns validation error."""
        response = client.post(
            "/v1/feedback",
            json={
                "rating": "positive",
            },
        )
        assert response.status_code == 422

    def test_feedback_invalid_rating_returns_422(self, client, mock_rag_pipeline):
        """POST /v1/feedback with invalid rating returns validation error."""
        response = client.post(
            "/v1/feedback",
            json={
                "feedback_id": "fb_test",
                "rating": "neutral",  # invalid — must be positive/negative
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test: Health Checks
# ---------------------------------------------------------------------------


class TestHealthChecks:
    """E2E tests for health check endpoints."""

    def test_health_live_returns_alive(self, client):
        """GET /v1/health/live -> 200 with status alive."""
        response = client.get("/v1/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert "timestamp" in data

    def test_health_ready_with_all_services_up(self, client):
        """GET /v1/health/ready -> 200 when Qdrant and LLM are available."""
        with (
            patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
            patch("requests.get") as mock_get,
        ):
            mock_qdrant.get_collections.return_value = {}
            mock_get.return_value.status_code = 200

            response = client.get("/v1/health/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["components"]["qdrant"] == "ok"
            assert data["components"]["llm"] == "ok"

    def test_health_ready_with_qdrant_down(self, client):
        """GET /v1/health/ready -> 503 when Qdrant is down."""
        with (
            patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
            patch("requests.get") as mock_get,
        ):
            mock_qdrant.get_collections.side_effect = Exception("Connection refused")
            mock_get.return_value.status_code = 200

            response = client.get("/v1/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert data["components"]["qdrant"] == "unavailable"

    def test_health_ready_with_llm_down(self, client):
        """GET /v1/health/ready -> 503 when LLM is down."""
        with (
            patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
            patch("requests.get", side_effect=Exception("LLM unreachable")),
        ):
            mock_qdrant.get_collections.return_value = {}

            response = client.get("/v1/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert data["components"]["llm"] == "unavailable"

    def test_health_full_with_all_services_up(self, client):
        """GET /v1/health -> 200 with all components ok."""
        with (
            patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
            patch("requests.get") as mock_get,
        ):
            mock_qdrant.get_collections.return_value = {}
            mock_get.return_value.status_code = 200

            response = client.get("/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "components" in data
            assert data["components"]["qdrant"] == "ok"
            assert data["components"]["llm"] == "ok"

    def test_health_full_degraded_when_qdrant_fails(self, client):
        """GET /v1/health -> 503 with status degraded when Qdrant fails."""
        with (
            patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
            patch("requests.get") as mock_get,
        ):
            mock_qdrant.get_collections.side_effect = Exception("down")
            mock_get.return_value.status_code = 200

            response = client.get("/v1/health")
            data = response.json()
            assert data["status"] == "degraded"
            assert "error" in data["components"]["qdrant"]


# ---------------------------------------------------------------------------
# Test: Model Listing
# ---------------------------------------------------------------------------


class TestModelListing:
    """E2E tests for /v1/models endpoint."""

    def test_models_returns_openai_compatible_list(self, client):
        """GET /v1/models returns OpenAI-compatible model list."""
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

    def test_models_include_rag_proxy(self, client):
        """Model list includes 'rag-proxy' model."""
        response = client.get("/v1/models")
        data = response.json()
        model_ids = [m["id"] for m in data["data"]]
        assert "rag-proxy" in model_ids

    def test_model_info_has_required_fields(self, client):
        """Each model entry has required OpenAI fields."""
        response = client.get("/v1/models")
        data = response.json()
        for model in data["data"]:
            assert "id" in model
            assert "object" in model
            assert model["object"] == "model"
            assert "created" in model
            assert "owned_by" in model


# ---------------------------------------------------------------------------
# Test: Full Pipeline E2E Integration
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """End-to-end integration tests that exercise the complete RAG pipeline flow."""

    def test_chat_then_feedback_flow(self, client, mock_rag_pipeline, mock_feedback_logger):
        """Complete flow: chat -> get feedback_id -> submit feedback."""
        # Step 1: Chat request
        chat_response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "stream": False,
            },
        )
        assert chat_response.status_code == 200
        chat_data = chat_response.json()
        feedback_id = chat_data["rag_feedback_id"]
        assert feedback_id is not None

        # Step 2: Submit feedback using the feedback_id
        with patch("proxy.app.shared.config.ENRICHMENT_ENABLED", False):
            feedback_response = client.post(
                "/v1/feedback",
                json={
                    "feedback_id": feedback_id,
                    "rating": "positive",
                    "comment": "Accurate answer",
                },
            )
            assert feedback_response.status_code == 200
            assert feedback_response.json()["status"] == "ok"

    def test_chat_with_retrieval_context_then_feedback_with_correction(self, client, mock_rag_pipeline_with_context, mock_feedback_logger):
        """Full pipeline: retrieval -> generation -> negative feedback with correction."""
        # Step 1: Chat with retrieval
        chat_response = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "Explain hybrid search"}],
                "stream": False,
            },
        )
        assert chat_response.status_code == 200
        chat_data = chat_response.json()
        assert len(chat_data["rag_sources"]) > 0

        # Step 2: Submit correction
        with patch("proxy.app.shared.config.ENRICHMENT_ENABLED", False):
            fb_response = client.post(
                "/v1/feedback",
                json={
                    "feedback_id": chat_data["rag_feedback_id"],
                    "rating": "negative",
                    "correction": "Hybrid search uses RRF fusion of dense and sparse vectors.",
                    "comment": "Missing detail about RRF",
                },
            )
            assert fb_response.status_code == 200

    def test_health_then_chat_then_health(self, client, mock_rag_pipeline):
        """Verify health before and after chat requests."""
        # Health before
        with (
            patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
            patch("requests.get") as mock_get,
        ):
            mock_qdrant.get_collections.return_value = {}
            mock_get.return_value.status_code = 200
            health1 = client.get("/v1/health")
            assert health1.status_code == 200

        # Chat
        chat = client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "test"}],
                "stream": False,
            },
        )
        assert chat.status_code == 200

        # Health after
        with (
            patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
            patch("requests.get") as mock_get,
        ):
            mock_qdrant.get_collections.return_value = {}
            mock_get.return_value.status_code = 200
            health2 = client.get("/v1/health")
            assert health2.status_code == 200

    def test_models_endpoint_always_available(self, client):
        """GET /v1/models works independently of RAG pipeline state."""
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) >= 1
