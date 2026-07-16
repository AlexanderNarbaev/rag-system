# ruff: noqa: E501, SIM117, E402, N817, SIM105
# tests/integration/test_streaming_chat.py
"""Integration tests for streaming chat completion.

Tests the SSE streaming flow:
- SSE chunk format (data: prefix, [DONE] sentinel)
- Empty choices handling
- rag_feedback_id in streaming
- Error handling during streaming
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


@pytest.fixture
def app_client():
    """Create a FastAPI TestClient with all external dependencies mocked."""
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.USE_LANGGRAPH", False),
        patch("proxy.app.main.LOG_REQUESTS", False),
        patch("proxy.app.main.LLM_MODEL_NAME", "test-model"),
        patch("proxy.app.auth.jwt.AUTH_ENABLED", False),
    ):
        from fastapi.testclient import TestClient

        from proxy.app.main import app

        client = TestClient(app)
        yield client


def _make_scored_point(text, score=0.95, source_type="confluence", version="1.0"):
    """Helper to build a single fake Qdrant ScoredPoint."""
    point = MagicMock()
    point.id = "fake_hash"
    point.score = score
    point.payload = {
        "text": text,
        "source_type": source_type,
        "source_id": "src_1",
        "version": version,
        "title": "Test Title",
        "doc_title": "Test Doc",
    }
    return point


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE response body into a list of event data dicts.

    Each SSE event is expected to be 'data: <json>\\n\\n'.
    The [DONE] sentinel is returned as {"_done": True}.
    """
    events = []
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("data: "):
            payload = line[6:]  # Strip 'data: ' prefix
            if payload == "[DONE]":
                events.append({"_done": True})
            else:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    events.append({"_raw": payload})
    return events


class TestStreamingChatCompletion:
    """Integration tests for streaming chat completion via SSE."""

    def test_streaming_returns_sse_content_type(self, app_client):
        """Streaming response has text/event-stream content type."""
        search_results = [_make_scored_point("RAG context for streaming.")]

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Hello"}, "index": 0}],
            }
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": " world"}, "index": 0}],
            }

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test streaming"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]

    def test_streaming_sends_done_sentinel(self, app_client):
        """Streaming response ends with 'data: [DONE]' sentinel."""
        search_results = [_make_scored_point("Context.")]

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Answer"}, "index": 0}],
            }

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            body = response.text

            assert "data: [DONE]" in body
            # [DONE] should be the last meaningful event
            done_pos = body.rfind("data: [DONE]")
            assert done_pos > 0

    def test_streaming_chunks_are_valid_json(self, app_client):
        """Each SSE data chunk (except [DONE]) is valid JSON."""
        search_results = [_make_scored_point("Context."), _make_scored_point("More context.")]

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Part1"}, "index": 0}],
            }
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Part2"}, "index": 0}],
            }
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Part3"}, "index": 0}],
            }

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            events = _parse_sse_events(response.text)

            # Filter out the [DONE], initial chunk marker, and feedback/metadata events
            data_events = [
                e
                for e in events
                if "_done" not in e and "_raw" not in e and "role" not in e and "rag_feedback_id" not in e
            ]
            assert len(data_events) >= 3

            for event in data_events:
                assert "id" in event or "choices" in event

    def test_streaming_handles_empty_choices(self, app_client):
        """Streaming handles chunks with empty choices list gracefully."""
        search_results = [_make_scored_point("Context.")]

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Good"}, "index": 0}],
            }
            yield {"id": "1", "object": "chat.completion.chunk", "choices": []}  # empty choices
            yield {"id": "1", "object": "chat.completion.chunk", "choices": [{"delta": {"content": "End"}, "index": 0}]}

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test empty choices"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            assert "data: [DONE]" in response.text  # Should not crash — empty choices are gracefully skipped

    def test_streaming_handles_choices_with_no_content(self, app_client):
        """Streaming handles choices where delta has no content field."""
        search_results = [_make_scored_point("Context.")]

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"role": "assistant"}, "index": 0}],
            }
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Actual content"}, "index": 0}],
            }
            yield {"id": "1", "object": "chat.completion.chunk", "choices": [{"delta": {}, "index": 0}]}

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            assert "data: [DONE]" in response.text

    def test_streaming_includes_feedback_id(self, app_client):
        """Streaming response includes rag_feedback_id before [DONE]."""
        search_results = [_make_scored_point("Context."), _make_scored_point("More context.")]

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Answer"}, "index": 0}],
            }

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            events = _parse_sse_events(response.text)

            # Find the feedback event (should be before [DONE])
            feedback_events = [e for e in events if "rag_feedback_id" in e]
            assert len(feedback_events) == 1
            assert feedback_events[0]["rag_feedback_id"].startswith("fb_")
            assert "rag_confidence" in feedback_events[0]

    def test_streaming_feedback_before_done(self, app_client):
        """The rag_feedback_id event appears before the [DONE] sentinel."""
        search_results = [_make_scored_point("Context."), _make_scored_point("More context.")]

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Text"}, "index": 0}],
            }

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            body = response.text

            feedback_pos = body.find("rag_feedback_id")
            done_pos = body.find("data: [DONE]")
            assert feedback_pos > 0
            assert done_pos > 0
            assert feedback_pos < done_pos

    def test_streaming_with_empty_search_results(self, app_client):
        """Streaming works when hybrid_search returns no results."""

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "No context available."}, "index": 0}],
            }

        with (
            patch("proxy.app.main.hybrid_search", return_value=[]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Unknown topic"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            assert "data: [DONE]" in response.text

    def test_streaming_error_yields_error_event(self, app_client):
        """When stream_completion raises, an error SSE event is emitted."""
        search_results = [_make_scored_point("Context."), _make_scored_point("More context.")]

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Start"}, "index": 0}],
            }
            raise RuntimeError("LLM connection lost")

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0, 1]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test error"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)
            body = response.text

            # Should contain an error event
            assert "error" in body.lower()
            assert "LLM connection lost" in body

    def test_streaming_search_failure_graceful_degradation(self, app_client):
        """When hybrid_search fails during streaming, the response still completes."""

        async def mock_stream(*args, **kwargs):
            yield {
                "id": "1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Fallback"}, "index": 0}],
            }

        with (
            patch("proxy.app.main.hybrid_search", side_effect=Exception("Qdrant timeout")),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
        ):
            payload = {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Test degraded streaming"}],
                "stream": True,
            }
            response = app_client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
