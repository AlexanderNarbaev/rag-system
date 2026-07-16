# ruff: noqa: E501, SIM117, E402
"""End-to-end tests for the full RAG pipeline.

Tests the complete flow from request to response with real-like data:
- Chat completion with RAG context
- Multi-turn conversation
- Streaming response
- Feedback submission
- Health checks
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


@pytest.fixture(autouse=True)
def _disable_auth(monkeypatch):
    """Disable authentication for all tests in this module."""
    import proxy.app.auth.jwt as _jwt
    import proxy.app.shared.config as _cfg

    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(_cfg, "AUTH_ENABLED", False)
    monkeypatch.setattr(_jwt, "AUTH_ENABLED", False)


@pytest.fixture
def app_client():
    """Create a FastAPI TestClient with mocked external dependencies."""
    from fastapi.testclient import TestClient

    from proxy.app.main import app

    with TestClient(app) as client:
        yield client


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
        mock_nonstream.return_value = "RAG is retrieval-augmented generation."
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
        mock_build.return_value = (
            "[confluence] Architecture Guide / RAG Overview (v2.0)\nRAG combines retrieval with generation."
        )
        mock_nonstream.return_value = (
            "Based on the context, RAG combines retrieval with generation for accurate responses."
        )
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


def _make_mock_chunks(count: int = 3):
    """Create mock search results with realistic scores."""
    chunks = []
    for i in range(count):
        chunk = MagicMock()
        chunk.id = f"chunk_{i}"
        chunk.score = 0.95 - i * 0.1  # 0.95, 0.85, 0.75
        chunk.payload = {
            "text": f"This is relevant context chunk {i} about RAG systems.",
            "source_type": "confluence",
            "source_id": f"page_{i}",
            "title": f"RAG Documentation Part {i}",
            "doc_title": f"RAG Guide {i}",
            "version": "1.0",
        }
        chunks.append(chunk)
    return chunks


class TestFullRAGPipeline:
    """E2E tests for the complete RAG pipeline."""

    def test_health_check(self, app_client):
        """Health endpoint returns healthy status."""
        response = app_client.get("/v1/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    def test_models_endpoint(self, app_client):
        """Models endpoint returns available models."""
        response = app_client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) > 0

    def test_chat_completion_with_rag(self, app_client, mock_rag_pipeline):
        """Full chat completion with RAG context retrieval."""
        response = app_client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "stream": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
        assert "rag_feedback_id" in data
        assert "rag_sources" in data

    def test_multi_turn_conversation(self, app_client, mock_rag_pipeline_with_context):
        """Multi-turn conversation preserves message history."""
        mock_rag_pipeline_with_context["non_stream_completion"].return_value = "Follow-up answer."

        response = app_client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [
                    {"role": "user", "content": "What is RAG?"},
                    {"role": "assistant", "content": "RAG is retrieval-augmented generation."},
                    {"role": "user", "content": "How does it work?"},
                ],
                "stream": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Follow-up answer."

    def test_feedback_submission(self, app_client, mock_rag_pipeline, mock_feedback_logger):
        """Feedback endpoint accepts and stores feedback."""
        with patch("proxy.app.shared.config.ENRICHMENT_ENABLED", False):
            response = app_client.post(
                "/v1/feedback",
                json={
                    "feedback_id": "fb_test_123",
                    "rating": "positive",
                    "comment": "Good answer",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_error_handling(self, app_client, mock_rag_pipeline):
        """Invalid request returns proper error."""
        response = app_client.post(
            "/v1/chat/completions",
            json={},  # Missing required fields
        )
        assert response.status_code == 422  # Validation error

    def test_empty_messages(self, app_client, mock_rag_pipeline):
        """Empty messages list returns error."""
        response = app_client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [],
                "stream": False,
            },
        )
        assert response.status_code in (400, 422)

    def test_chat_with_retrieved_context_returns_sources(self, app_client, mock_rag_pipeline_with_context):
        """When retrieval finds chunks, response includes source citations."""
        response = app_client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["rag_sources"]) > 0
        source = data["rag_sources"][0]
        assert "title" in source
        assert "version" in source

    def test_streaming_returns_sse_events(self, app_client, mock_rag_pipeline):
        """Streaming response returns Server-Sent Events format."""

        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "RAG "}}]}
            yield {"id": "2", "choices": [{"delta": {"content": "is "}}]}
            yield {"id": "3", "choices": [{"delta": {"content": "great."}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        response = app_client.post(
            "/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "What is RAG?"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        body = response.text
        assert "data:" in body
        assert "RAG" in body
        assert "[DONE]" in body

    def test_chat_then_feedback_flow(self, app_client, mock_rag_pipeline, mock_feedback_logger):
        """Complete flow: chat -> get feedback_id -> submit feedback."""
        # Step 1: Chat request
        chat_response = app_client.post(
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
            feedback_response = app_client.post(
                "/v1/feedback",
                json={
                    "feedback_id": feedback_id,
                    "rating": "positive",
                    "comment": "Accurate answer",
                },
            )
            assert feedback_response.status_code == 200
            assert feedback_response.json()["status"] == "ok"
