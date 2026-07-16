"""Tests for chat.py uncovered error handling paths — using proper module mocking.

Uses the same pattern as test_main.py: mock heavy deps first, then patch proxy.app.main.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

# Mock heavy dependencies BEFORE any imports from proxy.app
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

# Now import proxy.app.main to ensure module is available

from proxy.app.api.chat import (  # noqa: E402
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    chat_completions,
)


@pytest.fixture
def raw_request():
    req = MagicMock()
    req.client.host = "127.0.0.1"
    req.state = MagicMock()
    req.headers = {}
    return req


@pytest.fixture
def user():
    u = MagicMock()
    u.is_authenticated = True
    u.roles = ["expert"]
    return u


@pytest.fixture
def basic_request():
    return ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="What is RAG?")],
    )


class TestChatCompletionsBasic:
    """Test chat_completions edge cases using monkey-patched proxy.app.main."""

    def test_invalid_empty_model_400(self, raw_request, user):
        """Line 160: HTTP 400 on empty model name."""
        request = ChatCompletionRequest(
            model="",
            messages=[ChatMessage(role="user", content="test")],
        )
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                chat_completions(
                    request=request,
                    raw_request=raw_request,
                    user=user,
                ),
            )
        assert exc_info.value.status_code == 400

    def test_no_user_message_400(self, raw_request, user):
        """Lines 174-175: HTTP 400 when no user message."""
        request = ChatCompletionRequest(
            model="test-model",
            messages=[ChatMessage(role="system", content="system msg")],
        )
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                chat_completions(
                    request=request,
                    raw_request=raw_request,
                    user=user,
                ),
            )
        assert exc_info.value.status_code == 400


class TestChatCompletionsSpanRecording:
    """Cover span recording branch (lines 180-183, 357-359)."""

    @pytest.fixture(autouse=True)
    def setup_main(self):
        mock_m = MagicMock()
        mock_m.LOG_REQUESTS = False
        mock_m.USE_LANGGRAPH = False
        mock_m.orchestrator = None
        mock_m.request_tracker = MagicMock()
        mock_m.extract_version_from_query = MagicMock(return_value=None)
        mock_m.process_rag_query = AsyncMock(
            return_value=(
                "ctx",
                [{"role": "user", "content": "q"}],
                False,
                [{"chunk_id": "h", "title": "T", "relevance": 0.9}],
                None,
            ),
        )
        mock_m.audit_logger = MagicMock()
        mock_m.non_stream_completion = AsyncMock(return_value="Test answer")
        return mock_m

    def test_non_streaming_span_recording(self, raw_request, user, setup_main):
        """Cover lines 180-183: span attribute recording."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with (
            patch("proxy.app.main", setup_main),
            patch("proxy.app.api.chat.get_current_span", return_value=mock_span),
        ):
            request = ChatCompletionRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="test query")],
            )
            response = asyncio.run(
                chat_completions(
                    request=request,
                    raw_request=raw_request,
                    user=user,
                ),
            )
            assert response is not None
            # Span attribute setting should have been called
            set_attr_calls = [c for c in mock_span.method_calls if "set_attribute" in str(c)]
            assert len(set_attr_calls) >= 3

    def test_streaming_span_attributes(self, raw_request, user, setup_main):
        """Cover lines 357-359: pipeline span attributes."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        setup_main.process_rag_query = AsyncMock(
            return_value=("ctx", [{"role": "user", "content": "q"}], False, [], None),
        )

        async def mock_stream(*args, **kwargs):
            yield {"choices": [{"delta": {"content": "test"}, "index": 0}]}

        setup_main.stream_completion = mock_stream

        with (
            patch("proxy.app.main", setup_main),
            patch("proxy.app.api.chat.tracer") as mock_tracer,
        ):
            mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span
            request = ChatCompletionRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="stream test")],
                stream=True,
            )
            response = asyncio.run(
                chat_completions(
                    request=request,
                    raw_request=raw_request,
                    user=user,
                ),
            )
            assert isinstance(response, StreamingResponse)


class TestChatCompletionsErrorPaths:
    """Cover error handling in chat_completions."""

    @pytest.fixture
    def raw_request(self):
        req = MagicMock()
        req.client.host = "10.0.0.1"
        req.state = MagicMock()
        req.headers = {}
        return req

    @pytest.fixture
    def user(self):
        u = MagicMock()
        u.is_authenticated = True
        u.roles = ["admin"]
        return u

    def test_orchestrator_error_503(self, raw_request, user):
        """Lines 252-262: LangGraph orchestrator error."""
        mock_main = MagicMock()
        mock_main.LOG_REQUESTS = True
        mock_main.USE_LANGGRAPH = True
        mock_main.orchestrator = MagicMock()
        mock_main.orchestrator.ainvoke = AsyncMock(side_effect=RuntimeError("graph crashed"))
        mock_main.request_tracker = MagicMock()
        mock_main.audit_logger = MagicMock()

        with patch("proxy.app.main", mock_main):
            request = ChatCompletionRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="test")],
            )
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    chat_completions(
                        request=request,
                        raw_request=raw_request,
                        user=user,
                    ),
                )
            assert exc_info.value.status_code == 503

    def test_rag_query_error_503(self, raw_request, user):
        """Lines 444-454: non-streaming RAG query failure."""
        mock_main = MagicMock()
        mock_main.LOG_REQUESTS = True
        mock_main.USE_LANGGRAPH = False
        mock_main.orchestrator = None
        mock_main.request_tracker = MagicMock()
        mock_main.extract_version_from_query = MagicMock(return_value=None)
        mock_main.process_rag_query = AsyncMock(side_effect=RuntimeError("Qdrant down"))
        mock_main.audit_logger = MagicMock()

        with patch("proxy.app.main", mock_main):
            request = ChatCompletionRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="query")],
                stream=False,
            )
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    chat_completions(
                        request=request,
                        raw_request=raw_request,
                        user=user,
                    ),
                )
            assert exc_info.value.status_code == 503

    def test_streaming_error_yields_error_event(self, raw_request, user):
        """Lines 417-427: streaming error handler."""
        mock_main = MagicMock()
        mock_main.LOG_REQUESTS = True
        mock_main.USE_LANGGRAPH = False
        mock_main.orchestrator = None
        mock_main.request_tracker = MagicMock()
        mock_main.extract_version_from_query = MagicMock(return_value=None)
        mock_main.audit_logger = MagicMock()

        async def ok_rag(*args, **kwargs):
            return "ctx", [{"role": "user", "content": "q"}], False, [], None

        mock_main.process_rag_query = AsyncMock(side_effect=ok_rag)

        async def fail_stream(*args, **kwargs):
            raise RuntimeError("LLM timeout")
            yield

        mock_main.stream_completion = fail_stream

        with patch("proxy.app.main", mock_main):
            request = ChatCompletionRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="stream test")],
                stream=True,
            )
            response = asyncio.run(
                chat_completions(
                    request=request,
                    raw_request=raw_request,
                    user=user,
                ),
            )
            assert isinstance(response, StreamingResponse)

    def test_skip_generation(self, raw_request, user):
        """Cover rag_skip_generation path."""
        mock_main = MagicMock()
        mock_main.LOG_REQUESTS = True
        mock_main.USE_LANGGRAPH = False
        mock_main.orchestrator = None
        mock_main.request_tracker = MagicMock()
        mock_main.extract_version_from_query = MagicMock(return_value=None)
        mock_main.process_rag_query = AsyncMock(
            return_value=("ctx", "answer", False, [{"chunk_id": "h1", "title": "T"}], None),
        )
        mock_main.audit_logger = MagicMock()

        with patch("proxy.app.main", mock_main):
            request = ChatCompletionRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="query")],
                stream=False,
                rag_skip_generation=True,
            )
            response = asyncio.run(
                chat_completions(
                    request=request,
                    raw_request=raw_request,
                    user=user,
                ),
            )
            assert isinstance(response, ChatCompletionResponse)
            assert response.rag_sources is not None


class TestStreamingRefusalPath:
    """Cover streaming refusal when messages_for_llm is empty (lines 372-385)."""

    @pytest.fixture
    def raw_request(self):
        req = MagicMock()
        req.client.host = "10.0.0.1"
        req.state = MagicMock()
        req.headers = {}
        return req

    @pytest.fixture
    def user(self):
        u = MagicMock()
        u.is_authenticated = True
        u.roles = ["user"]
        return u

    def test_streaming_refusal_when_no_context(self, raw_request, user):
        """Cover streaming generator refusal (line 372-385)."""
        mock_main = MagicMock()
        mock_main.LOG_REQUESTS = False
        mock_main.USE_LANGGRAPH = False
        mock_main.orchestrator = None
        mock_main.request_tracker = MagicMock()
        mock_main.extract_version_from_query = MagicMock(return_value=None)
        mock_main.audit_logger = MagicMock()

        async def empty_rag(*args, **kwargs):
            return "context", [], False, [], None

        mock_main.process_rag_query = AsyncMock(side_effect=empty_rag)

        with patch("proxy.app.main", mock_main):
            request = ChatCompletionRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="obscure query")],
                stream=True,
            )
            response = asyncio.run(
                chat_completions(
                    request=request,
                    raw_request=raw_request,
                    user=user,
                ),
            )
            assert isinstance(response, StreamingResponse)


class TestRouterExists:
    def test_router_has_routes(self):
        from proxy.app.api.chat import router

        assert hasattr(router, "routes")
