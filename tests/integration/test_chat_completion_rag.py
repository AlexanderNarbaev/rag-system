# tests/integration/test_chat_completion_rag.py
"""Integration tests for the full RAG chat completion pipeline.

Tests the end-to-end flow from chat request to response:
- Retrieval (hybrid search) → Reranking → Context assembly → LLM generation
- Response includes RAG context (sources, feedback_id, confidence)
- Graceful degradation when components fail
"""

# Disable progressive retrieval — these tests mock hybrid_search directly
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ["PROGRESSIVE_RETRIEVAL_ENABLED"] = "false"

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


@pytest.fixture
def app_client():
    """Create a FastAPI TestClient with all external dependencies mocked."""
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.USE_LANGGRAPH", False),
        patch("proxy.app.main.LOG_REQUESTS", False),
        patch("proxy.app.main.LLM_MODEL_NAME", "test-model"),
        patch("proxy.app.main.PROGRESSIVE_RETRIEVAL_ENABLED", False),
        patch("proxy.app.auth.jwt.AUTH_ENABLED", False),
    ):
        from fastapi.testclient import TestClient

        from proxy.app.main import app

        client = TestClient(app)
        yield client


def _make_scored_points(texts_with_meta):
    """Helper to build fake Qdrant ScoredPoint objects."""
    points = []
    for i, item in enumerate(texts_with_meta):
        point = MagicMock()
        point.id = f"hash_{i}"
        point.score = 0.95 - i * 0.05
        point.payload = {
            "text": item["text"],
            "source_type": item.get("source_type", "confluence"),
            "source_id": item.get("source_id", f"src_{i}"),
            "version": item.get("version", "1.0"),
            "title": item.get("title", f"Title {i}"),
            "doc_title": item.get("doc_title", f"Doc {i}"),
        }
        points.append(point)
    return points


class TestChatCompletionRAGPipeline:
    """Integration tests for the full RAG chat completion pipeline."""

    def test_chat_triggers_retrieval_reranking_and_llm(self, app_client):
        """A chat request triggers hybrid_search → rerank_chunks → LLM generation in sequence."""
        search_results = _make_scored_points(
            [
                {"text": "RAG combines retrieval with generation.", "source_type": "confluence", "title": "RAG Guide"},
                {"text": "CI/CD pipelines automate deployment.", "source_type": "gitlab", "title": "CI/CD Setup"},
            ],
        )

        async def mock_llm(messages, **kwargs):
            return "Based on the context, RAG is a technique combining retrieval and generation."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results) as mock_search,
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1]) as mock_rerank,
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm) as mock_llm_fn,
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "What is RAG?"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            data = response.json()

            # Verify the pipeline was triggered
            mock_search.assert_called_once()
            mock_rerank.assert_called_once()
            mock_llm_fn.assert_called_once()

            # Verify response format
            assert data["object"] == "chat.completion"
            assert len(data["choices"]) == 1
            assert data["choices"][0]["message"]["role"] == "assistant"
            assert len(data["choices"][0]["message"]["content"]) > 0

    def test_response_includes_rag_sources(self, app_client):
        """Non-streaming response includes rag_sources with chunk metadata."""
        search_results = _make_scored_points(
            [
                {
                    "text": "RAG is retrieval-augmented generation.",
                    "source_type": "confluence",
                    "source_id": "conf_123",
                    "title": "RAG Overview",
                    "version": "2.0",
                },
                {
                    "text": "Hybrid search combines dense and sparse vectors.",
                    "source_type": "gitlab",
                    "source_id": "gl_456",
                    "title": "Search Module",
                    "version": "1.0",
                },
            ],
        )

        async def mock_llm(messages, **kwargs):
            return "RAG uses retrieval-augmented generation with hybrid search."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Explain RAG and hybrid search"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            data = response.json()

            # Verify rag_sources are present and well-formed
            assert "rag_sources" in data
            sources = data["rag_sources"]
            assert isinstance(sources, list)
            assert len(sources) > 0

            for source in sources:
                assert "chunk_id" in source
                assert "source" in source
                assert "title" in source
                assert "version" in source
                assert "relevance" in source
                assert "text_preview" in source

    def test_response_includes_feedback_id(self, app_client):
        """Non-streaming response includes a rag_feedback_id for feedback tracking."""
        search_results = _make_scored_points(
            [
                {"text": "RAG context chunk.", "source_type": "confluence"},
            ],
        )

        async def mock_llm(messages, **kwargs):
            return "Answer based on context."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Test query"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            data = response.json()

            assert "rag_feedback_id" in data
            assert data["rag_feedback_id"] is not None
            assert data["rag_feedback_id"].startswith("fb_")

    def test_response_includes_confidence_score(self, app_client):
        """Non-streaming response includes rag_confidence score."""
        search_results = _make_scored_points(
            [
                {"text": "Highly relevant RAG context.", "source_type": "confluence"},
            ],
        )

        async def mock_llm(messages, **kwargs):
            return "Detailed answer about RAG with good grounding."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "What is RAG?"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            data = response.json()

            assert "rag_confidence" in data
            assert data["rag_confidence"] is not None
            assert 0.0 <= data["rag_confidence"] <= 1.0

    def test_empty_search_results_still_returns_response(self, app_client):
        """When retrieval returns no results, LLM still generates a response (degraded mode)."""

        async def mock_llm(messages, **kwargs):
            return "I don't have specific context for this query."

        with (
            patch("proxy.app.main.hybrid_search", return_value=[]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Unknown topic query"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert data["object"] == "chat.completion"
            assert len(data["choices"]) == 1
            assert len(data["choices"][0]["message"]["content"]) > 0

    def test_search_failure_graceful_degradation(self, app_client):
        """When hybrid_search raises an exception, the pipeline degrades gracefully."""

        async def mock_llm(messages, **kwargs):
            return "Fallback response without context."

        with (
            patch("proxy.app.main.hybrid_search", side_effect=Exception("Qdrant unavailable")),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Test degraded mode"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert len(data["choices"][0]["message"]["content"]) > 0

    def test_multi_turn_conversation_preserves_history(self, app_client):
        """Multi-turn messages are forwarded to LLM correctly (excluding system messages from user)."""
        search_results = _make_scored_points(
            [
                {"text": "RAG context for multi-turn.", "source_type": "confluence"},
                {"text": "Hybrid search combines vectors.", "source_type": "confluence"},
            ],
        )

        captured_messages = []

        async def mock_llm(messages, **kwargs):
            captured_messages.extend(messages)
            return "Follow-up answer."

        with (
            patch("proxy.app.main.PROGRESSIVE_RETRIEVAL_ENABLED", False),
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [
                    {"role": "user", "content": "What is RAG?"},
                    {"role": "assistant", "content": "RAG is retrieval-augmented generation."},
                    {"role": "user", "content": "How does hybrid search work?"},
                ],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200

            # The LLM should receive system prompt + previous messages + user query
            assert len(captured_messages) >= 3  # system + assistant + user
            # System message should contain context
            assert captured_messages[0]["role"] == "system"
            assert "Context" in captured_messages[0]["content"] or "Контекст" in captured_messages[0]["content"]
            # Previous assistant message should be preserved
            assistant_msgs = [m for m in captured_messages if m["role"] == "assistant"]
            assert len(assistant_msgs) >= 1

    def test_version_filter_passed_to_search(self, app_client):
        """When rag_version is specified, it is passed to hybrid_search."""
        search_results = _make_scored_points(
            [
                {"text": "Versioned content.", "version": "2.0"},
            ],
        )

        async def mock_llm(messages, **kwargs):
            return "Version-specific answer."

        with (
            patch("proxy.app.main.PROGRESSIVE_RETRIEVAL_ENABLED", False),
            patch("proxy.app.main.hybrid_search") as mock_search,
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            mock_search.return_value = search_results

            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Show docs for v2.0"}],
                "rag_version": "2.0",
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200

            # Verify version was passed to search
            call_kwargs = mock_search.call_args.kwargs
            assert call_kwargs["version"] == "2.0"

    def test_response_id_format(self, app_client):
        """Response ID follows the 'rag_' prefix convention."""
        search_results = _make_scored_points(
            [
                {"text": "Some context.", "source_type": "confluence"},
            ],
        )

        async def mock_llm(messages, **kwargs):
            return "Response text."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Test"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            data = response.json()

            assert data["id"].startswith("rag_")
            assert data["model"] == "test-model+RAG"
            assert data["choices"][0]["finish_reason"] == "stop"
            assert "usage" in data

    def test_context_passed_to_llm_system_prompt(self, app_client):
        """Retrieved context is embedded in the system prompt sent to LLM."""
        search_results = _make_scored_points(
            [
                {"text": "RAG is a powerful technique for LLMs.", "source_type": "confluence", "title": "RAG Guide"},
                {"text": "RAG combines retrieval with generation.", "source_type": "confluence", "title": "Overview"},
            ],
        )

        captured_messages = []

        async def mock_llm(messages, **kwargs):
            captured_messages.extend(messages)
            return "Answer."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "What is RAG?"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 200

            # Verify system prompt contains retrieved context
            system_msg = captured_messages[0]
            assert system_msg["role"] == "system"
            assert "RAG is a powerful technique" in system_msg["content"]

    def test_rerank_exception_propagates(self, app_client):
        """Exception during reranking returns503 to the caller."""
        search_results = _make_scored_points(
            [
                {"text": "Some text.", "source_type": "confluence"},
            ],
        )

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", side_effect=RuntimeError("Reranker OOM")),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "Test"}],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            assert response.status_code == 503
            data = response.json()
            assert data["detail"]["error"] == "rag_unavailable"
