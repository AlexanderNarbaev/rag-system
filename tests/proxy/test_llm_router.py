"""Tests for proxy/app/llm_router.py - LLM routing with mocked aiohttp."""
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
import aiohttp

from proxy.app.llm_router import (
    LLMError,
    non_stream_completion,
    stream_completion,
    non_stream_completion_sync,
    _send_completion_request,
)


class TestLLMError:
    """Tests for LLMError exception."""

    def test_is_exception(self):
        with pytest.raises(LLMError):
            raise LLMError("test error")

    def test_can_be_caught_as_exception(self):
        try:
            raise LLMError("msg")
        except Exception as e:
            assert isinstance(e, LLMError)
            assert str(e) == "msg"


class TestSendCompletionRequest:
    """Tests for _send_completion_request with mocked aiohttp."""

    @pytest.mark.asyncio
    async def test_non_stream_success(self):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "choices": [{"message": {"content": "answer"}}]
        })
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await _send_completion_request(
                [{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=100,
                stream=False,
                retry=0
            )
            assert result["choices"][0]["message"]["content"] == "answer"

    @pytest.mark.asyncio
    async def test_non_stream_bad_status(self):
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Error")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMError, match="LLM returned 500"):
                await _send_completion_request(
                    [{"role": "user", "content": "hi"}],
                    0.2, 100, stream=False, retry=0
                )

    @pytest.mark.asyncio
    async def test_stream_success(self):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await _send_completion_request(
                [{"role": "user", "content": "hi"}],
                0.2, 100, stream=True, retry=0
            )
            assert result is mock_response

    @pytest.mark.asyncio
    async def test_invalid_response_format(self):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"unexpected": "format"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(LLMError, match="Invalid response format"):
                await _send_completion_request(
                    [{"role": "user", "content": "hi"}],
                    0.2, 100, stream=False, retry=0
                )

    @pytest.mark.asyncio
    async def test_retry_logic(self):
        mock_response_fail = MagicMock()
        mock_response_fail.status = 503
        mock_response_fail.text = AsyncMock(return_value="Service Unavailable")
        mock_response_fail.__aenter__ = AsyncMock(return_value=mock_response_fail)
        mock_response_fail.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response_fail)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("asyncio.sleep", AsyncMock()):
            with pytest.raises(LLMError, match="failed after"):
                await _send_completion_request(
                    [{"role": "user", "content": "hi"}],
                    0.2, 100, stream=False, retry=2
                )
            assert mock_session.post.call_count == 3  # 1 + 2 retries

    @pytest.mark.asyncio
    async def test_retry_eventually_succeeds(self):
        mock_response_fail = MagicMock()
        mock_response_fail.status = 429
        mock_response_fail.text = AsyncMock(return_value="Rate limited")
        mock_response_fail.__aenter__ = AsyncMock(return_value=mock_response_fail)
        mock_response_fail.__aexit__ = AsyncMock(return_value=None)

        mock_response_ok = MagicMock()
        mock_response_ok.status = 200
        mock_response_ok.json = AsyncMock(return_value={
            "choices": [{"message": {"content": "ok"}}]
        })
        mock_response_ok.__aenter__ = AsyncMock(return_value=mock_response_ok)
        mock_response_ok.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=[mock_response_fail, mock_response_ok])
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("asyncio.sleep", AsyncMock()):
            result = await _send_completion_request(
                [{"role": "user", "content": "hi"}],
                0.2, 100, stream=False, retry=1
            )
            assert result["choices"][0]["message"]["content"] == "ok"


class TestNonStreamCompletion:
    """Tests for non_stream_completion."""

    @pytest.mark.asyncio
    async def test_returns_content(self):
        with patch("proxy.app.llm_router._send_completion_request") as mock_send:
            mock_send.return_value = {
                "choices": [{"message": {"content": "Hello, world!"}}]
            }
            result = await non_stream_completion(
                [{"role": "user", "content": "hi"}]
            )
            assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_raises_on_missing_choices(self):
        with patch("proxy.app.llm_router._send_completion_request") as mock_send:
            mock_send.return_value = {}
            with pytest.raises(LLMError):
                await non_stream_completion([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_raises_on_empty_choices(self):
        with patch("proxy.app.llm_router._send_completion_request") as mock_send:
            mock_send.return_value = {"choices": []}
            with pytest.raises(LLMError):
                await non_stream_completion([{"role": "user", "content": "hi"}])


class TestStreamCompletion:
    """Tests for stream_completion."""

    @pytest.mark.asyncio
    async def test_streams_chunks(self):
        async def mock_lines():
            yield b'data: {"id": "1", "choices": [{"delta": {"content": "Hello"}}]}\n'
            yield b'\n'
            yield b'data: {"id": "2", "choices": [{"delta": {"content": " world"}}]}\n'
            yield b'data: [DONE]\n'

        mock_content = MagicMock()
        mock_content.__aiter__ = MagicMock(return_value=mock_lines())

        mock_response = MagicMock()
        mock_response.content = mock_content

        with patch("proxy.app.llm_router._send_completion_request", return_value=mock_response):
            chunks = []
            async for chunk in stream_completion([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
            assert len(chunks) == 2
            assert chunks[0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self):
        async def mock_lines():
            yield b'data: {"valid": "json"}\n'
            yield b'data: not-json!!!\n'
            yield b'data: [DONE]\n'

        mock_content = MagicMock()
        mock_content.__aiter__ = MagicMock(return_value=mock_lines())

        mock_response = MagicMock()
        mock_response.content = mock_content

        with patch("proxy.app.llm_router._send_completion_request", return_value=mock_response):
            chunks = []
            async for chunk in stream_completion([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
            assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_stops_on_done(self):
        async def mock_lines():
            yield b'data: [DONE]\n'
            yield b'data: {"id": "3", "choices": []}\n'  # should be ignored

        mock_content = MagicMock()
        mock_content.__aiter__ = MagicMock(return_value=mock_lines())

        mock_response = MagicMock()
        mock_response.content = mock_content

        with patch("proxy.app.llm_router._send_completion_request", return_value=mock_response):
            chunks = []
            async for chunk in stream_completion([{"role": "user", "content": "hi"}]):
                chunks.append(chunk)
            assert len(chunks) == 0


class TestNonStreamCompletionSync:
    """Tests for non_stream_completion_sync."""

    def test_calls_async_version(self):
        with patch("proxy.app.llm_router.non_stream_completion") as mock_async:
            async def _fake(*args, **kwargs):
                return "sync result"
            mock_async.side_effect = _fake
            result = non_stream_completion_sync([{"role": "user", "content": "hi"}])
            assert result == "sync result"
            mock_async.assert_called_once()
