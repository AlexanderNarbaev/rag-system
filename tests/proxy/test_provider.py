# ruff: noqa: E501, SIM117
"""Tests for proxy/app/llm/provider.py — MultiProviderRouter and adapters."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxy.app.llm.provider import (
  AnthropicAdapter,
  GenericAdapter,
  LLMError,
  MultiProviderRouter,
  OllamaAdapter,
  OpenAIAdapter,
  ProviderType,
  get_router,
  non_stream_completion,
  non_stream_completion_sync,
  stream_completion,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture (autouse = True)
def _reset_singleton ():
  """Reset the global router singleton between tests."""
  import proxy.app.llm.provider as mod

  mod._router = None
  yield
  mod._router = None


@pytest.fixture (autouse = True)
def _set_config (monkeypatch):
  """Set default config for provider tests."""
  monkeypatch.setattr ("proxy.app.llm.provider.LLM_ENDPOINT", "http://localhost:8000/v1")
  monkeypatch.setattr ("proxy.app.llm.provider.LLM_MODEL_NAME", "test-model")
  monkeypatch.setattr ("proxy.app.llm.provider.LLM_API_KEY", "test-key")
  monkeypatch.setattr ("proxy.app.llm.provider.LLM_PROVIDER_TYPE", "openai")
  monkeypatch.setattr ("proxy.app.llm.provider.MAX_RETRIES", 0)
  monkeypatch.setattr ("proxy.app.llm.provider.REQUEST_TIMEOUT", 30)
  monkeypatch.setattr ("proxy.app.llm.provider.RETRY_DELAY", 0.01)


# ── ProviderType ─────────────────────────────────────────────────────────────


class TestProviderType:
  def test_enum_values (self):
    assert ProviderType.OPENAI == "openai"
    assert ProviderType.ANTHROPIC == "anthropic"
    assert ProviderType.OLLAMA == "ollama"
    assert ProviderType.GENERIC == "generic"

  def test_from_string (self):
    assert ProviderType ("openai") == ProviderType.OPENAI
    assert ProviderType ("anthropic") == ProviderType.ANTHROPIC


# ── OpenAIAdapter ────────────────────────────────────────────────────────────


class TestOpenAIAdapter:
  def test_headers_with_api_key (self):
    adapter = OpenAIAdapter ()
    headers = adapter.headers
    assert headers ["Content-Type"] == "application/json"
    assert headers ["Authorization"] == "Bearer test-key"

  def test_headers_without_api_key (self, monkeypatch):
    monkeypatch.setattr ("proxy.app.llm.provider.LLM_API_KEY", "")
    adapter = OpenAIAdapter ()
    headers = adapter.headers
    assert "Authorization" not in headers

  def test_translate_request_basic (self):
    adapter = OpenAIAdapter ()
    messages = [{"role": "user", "content": "hello"}]
    payload = adapter.translate_request (messages, temperature = 0.5, max_tokens = 100)
    assert payload ["model"] == "test-model"
    assert payload ["messages"] == messages
    assert payload ["temperature"] == 0.5
    assert payload ["max_tokens"] == 100
    assert payload ["stream"] is False

  def test_translate_request_with_tools (self):
    from proxy.app.tools.definition import ToolDefinition

    adapter = OpenAIAdapter ()
    tools = [ToolDefinition (name = "search", description = "Search docs", parameters = [])]
    payload = adapter.translate_request ([], tools = tools)
    assert "tools" in payload
    assert payload ["tool_choice"] == "auto"
    assert payload ["tools"] [0] ["type"] == "function"

  def test_translate_response_passthrough (self):
    adapter = OpenAIAdapter ()
    resp = {"choices": [{"message": {"content": "hi"}}]}
    assert adapter.translate_response (resp) == resp

  def test_translate_stream_chunk_valid (self):
    adapter = OpenAIAdapter ()
    chunk = b'data: {"id": "1", "choices": [{"delta": {"content": "hi"}}]}'
    result = adapter.translate_stream_chunk (chunk)
    assert result is not None
    assert result ["id"] == "1"

  def test_translate_stream_chunk_done (self):
    adapter = OpenAIAdapter ()
    result = adapter.translate_stream_chunk (b"data: [DONE]")
    assert result == {"_done": True}

  def test_translate_stream_chunk_empty_line (self):
    adapter = OpenAIAdapter ()
    assert adapter.translate_stream_chunk (b"") is None
    assert adapter.translate_stream_chunk (b"\n") is None

  def test_translate_stream_chunk_no_data_prefix (self):
    adapter = OpenAIAdapter ()
    assert adapter.translate_stream_chunk (b"event: ping") is None

  def test_translate_stream_chunk_invalid_json (self):
    adapter = OpenAIAdapter ()
    assert adapter.translate_stream_chunk (b"data: not-json!!!") is None


# ── AnthropicAdapter ─────────────────────────────────────────────────────────


class TestAnthropicAdapter:
  def test_headers (self):
    adapter = AnthropicAdapter ()
    headers = adapter.headers
    assert headers ["x-api-key"] == "test-key"
    assert headers ["anthropic-version"] == "2023-06-01"

  def test_translate_request_extracts_system (self):
    adapter = AnthropicAdapter ()
    messages = [
        {"role": "system", "content": "You are helpful"}, {"role": "user", "content": "hi"},
    ]
    payload = adapter.translate_request (messages)
    assert payload ["system"] == "You are helpful"
    assert len (payload ["messages"]) == 1
    assert payload ["messages"] [0] ["role"] == "user"

  def test_translate_request_assistant_message (self):
    adapter = AnthropicAdapter ()
    messages = [{"role": "assistant", "content": "hello"}]
    payload = adapter.translate_request (messages)
    assert payload ["messages"] [0] ["role"] == "assistant"
    assert payload ["messages"] [0] ["content"] == "hello"

  def test_translate_request_tool_result (self):
    adapter = AnthropicAdapter ()
    messages = [{"role": "tool", "tool_call_id": "tc1", "content": "result"}]
    payload = adapter.translate_request (messages)
    assert payload ["messages"] [0] ["role"] == "user"
    assert payload ["messages"] [0] ["content"] [0] ["type"] == "tool_result"

  def test_translate_response_text_only (self):
    adapter = AnthropicAdapter ()
    resp = {
        "id": "msg-1", "model": "claude-3", "content": [{"type": "text", "text": "Hello!"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    result = adapter.translate_response (resp)
    assert result ["choices"] [0] ["message"] ["content"] == "Hello!"
    assert result ["usage"] ["total_tokens"] == 15

  def test_translate_response_with_tool_use (self):
    adapter = AnthropicAdapter ()
    resp = {
        "id": "msg-1", "model": "claude-3", "content": [
            {"type": "text", "text": "Let me search"}, {
                "type": "tool_use", "id": "tu_1", "name": "search", "input": {"query": "test"},
            },
        ], "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 20},
    }
    result = adapter.translate_response (resp)
    msg = result ["choices"] [0] ["message"]
    assert msg ["content"] == "Let me search"
    assert len (msg ["tool_calls"]) == 1
    assert msg ["tool_calls"] [0] ["function"] ["name"] == "search"

  def test_translate_stream_chunk_text_delta (self):
    adapter = AnthropicAdapter ()
    chunk_data = {
        "type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hello"},
    }
    result = adapter.translate_stream_chunk (b"data: " + json.dumps (chunk_data).encode ())
    assert result is not None
    assert result ["choices"] [0] ["delta"] ["content"] == "hello"

  def test_translate_stream_chunk_message_stop (self):
    adapter = AnthropicAdapter ()
    result = adapter.translate_stream_chunk (b'data: {"type": "message_stop"}')
    assert result == {"_done": True}

  def test_translate_stream_chunk_message_delta (self):
    adapter = AnthropicAdapter ()
    chunk_data = {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
    result = adapter.translate_stream_chunk (b"data: " + json.dumps (chunk_data).encode ())
    assert result is not None
    assert result ["choices"] [0] ["finish_reason"] == "end_turn"

  def test_translate_stream_chunk_input_json_delta (self):
    adapter = AnthropicAdapter ()
    chunk_data = {
        "type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
    }
    result = adapter.translate_stream_chunk (b"data: " + json.dumps (chunk_data).encode ())
    assert result is not None
    assert result ["choices"] [0] ["delta"] ["tool_calls"] [0] ["function"] ["arguments"] == '{"q":'

  def test_translate_stream_chunk_unknown_type (self):
    adapter = AnthropicAdapter ()
    result = adapter.translate_stream_chunk (b'data: {"type": "unknown"}')
    assert result is None


# ── OllamaAdapter ────────────────────────────────────────────────────────────


class TestOllamaAdapter:
  def test_headers_no_auth (self):
    adapter = OllamaAdapter ()
    headers = adapter.headers
    assert "Authorization" not in headers
    assert headers ["Content-Type"] == "application/json"

  def test_translate_request_includes_options (self):
    adapter = OllamaAdapter ()
    payload = adapter.translate_request ([], temperature = 0.7, max_tokens = 512)
    assert payload ["options"] ["temperature"] == 0.7
    assert payload ["options"] ["num_predict"] == 512


# ── GenericAdapter ───────────────────────────────────────────────────────────


class TestGenericAdapter:
  def test_custom_request_transform (self):
    def add_field (payload):
      payload ["custom"] = True
      return payload

    adapter = GenericAdapter (request_transform = add_field)
    payload = adapter.translate_request ([])
    assert payload ["custom"] is True

  def test_custom_response_transform (self):
    def wrap_response (data):
      return {"wrapped": data}

    adapter = GenericAdapter (response_transform = wrap_response)
    resp = {"choices": [{"message": {"content": "hi"}}]}
    result = adapter.translate_response (resp)
    assert "wrapped" in result

  def test_no_transforms_uses_openai (self):
    adapter = GenericAdapter ()
    payload = adapter.translate_request ([{"role": "user", "content": "hi"}])
    assert payload ["model"] == "test-model"


# ── MultiProviderRouter ──────────────────────────────────────────────────────


class TestMultiProviderRouter:
  def test_default_provider_openai (self):
    router = MultiProviderRouter ()
    assert router.provider_type == ProviderType.OPENAI
    assert isinstance (router.adapter, OpenAIAdapter)

  def test_explicit_provider (self):
    router = MultiProviderRouter (provider_type = "anthropic")
    assert router.provider_type == ProviderType.ANTHROPIC
    assert isinstance (router.adapter, AnthropicAdapter)

  def test_unknown_provider_falls_back_to_openai (self):
    router = MultiProviderRouter (provider_type = "unknown_provider")
    assert router.provider_type == ProviderType.OPENAI

  def test_resolve_provider_default (self):
    router = MultiProviderRouter ()
    adapter, pt = router._resolve_provider ()
    assert pt == ProviderType.OPENAI

  def test_resolve_provider_override (self):
    router = MultiProviderRouter ()
    adapter, pt = router._resolve_provider ("anthropic")
    assert pt == ProviderType.ANTHROPIC
    assert isinstance (adapter, AnthropicAdapter)

  def test_resolve_provider_caches_adapter (self):
    router = MultiProviderRouter ()
    adapter1, _ = router._resolve_provider ("ollama")
    adapter2, _ = router._resolve_provider ("ollama")
    assert adapter1 is adapter2

  def test_resolve_provider_unknown_falls_back (self):
    router = MultiProviderRouter ()
    adapter, pt = router._resolve_provider ("nonexistent")
    assert pt == ProviderType.OPENAI

  @pytest.mark.asyncio
  async def test_non_stream_completion_success (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {"choices": [{"message": {"content": "answer"}}]})
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    router = MultiProviderRouter ()
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      result = await router.non_stream_completion ([{"role": "user", "content": "hi"}])
      assert result ["choices"] [0] ["message"] ["content"] == "answer"

  @pytest.mark.asyncio
  async def test_non_stream_completion_text (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {"choices": [{"message": {"content": "hello world"}}]})
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    router = MultiProviderRouter ()
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      text = await router.non_stream_completion_text ([{"role": "user", "content": "hi"}])
      assert text == "hello world"

  @pytest.mark.asyncio
  async def test_non_stream_completion_text_empty_choices (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {"choices": []})
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    router = MultiProviderRouter ()
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      with pytest.raises (LLMError):
        await router.non_stream_completion_text ([{"role": "user", "content": "hi"}])

  @pytest.mark.asyncio
  async def test_stream_completion (self):
    async def mock_lines ():
      yield b'data: {"id": "1", "choices": [{"delta": {"content": "Hi"}}]}'
      yield b'data: {"id": "2", "choices": [{"delta": {"content": " there"}}]}'
      yield b"data: [DONE]"

    mock_content = MagicMock ()
    mock_content.__aiter__ = MagicMock (return_value = mock_lines ())

    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.content = mock_content
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    router = MultiProviderRouter ()
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      chunks = []
      async for chunk in router.stream_completion ([{"role": "user", "content": "hi"}]):
        chunks.append (chunk)
      assert len (chunks) == 2

  @pytest.mark.asyncio
  async def test_non_stream_api_error (self):
    mock_response = MagicMock ()
    mock_response.status = 500
    mock_response.text = AsyncMock (return_value = "Internal Error")
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    router = MultiProviderRouter ()
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      with pytest.raises (LLMError, match = "LLM returned 500"):
        await router.non_stream_completion ([{"role": "user", "content": "hi"}])

  @pytest.mark.asyncio
  async def test_tool_use_completion (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {
        "choices": [
            {
                "message": {
                    "content": "", "tool_calls": [
                        {
                            "id": "call_1", "function": {
                            "name": "search", "arguments": json.dumps ({"query": "test"}),
                        },
                        }
                    ],
                }
            }
        ]
    })
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    from proxy.app.tools.definition import ToolDefinition

    router = MultiProviderRouter ()
    tools = [ToolDefinition (name = "search", description = "Search", parameters = [])]
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      calls = await router.tool_use_completion ([{"role": "user", "content": "search for test"}], tools = tools)
      assert len (calls) == 1
      assert calls [0].name == "search"

  @pytest.mark.asyncio
  async def test_tool_use_completion_no_calls (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {"choices": [{"message": {"content": "no tools needed"}}]})
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    from proxy.app.tools.definition import ToolDefinition

    router = MultiProviderRouter ()
    tools = [ToolDefinition (name = "search", description = "Search", parameters = [])]
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      calls = await router.tool_use_completion ([{"role": "user", "content": "hi"}], tools = tools)
      assert calls == []

  @pytest.mark.asyncio
  async def test_tool_results_injection (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {"choices": [{"message": {"content": "result processed"}}]})
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    from proxy.app.tools.definition import ToolResult

    router = MultiProviderRouter ()
    tool_results = [ToolResult (tool_name = "search", tool_call_id = "tc1", content = "found it")]
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      await router.non_stream_completion ([{"role": "user", "content": "hi"}], tool_results = tool_results)
      # Verify tool result was injected into messages
      call_args = mock_session.post.call_args
      payload = call_args.kwargs.get ("json") or call_args [1].get ("json")
      tool_msgs = [m for m in payload ["messages"] if m.get ("role") == "tool"]
      assert len (tool_msgs) == 1
      assert tool_msgs [0] ["tool_call_id"] == "tc1"

  def test_non_stream_completion_sync (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {"choices": [{"message": {"content": "sync result"}}]})
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    router = MultiProviderRouter ()
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      result = router.non_stream_completion_sync ([{"role": "user", "content": "hi"}])
      assert result == "sync result"


# ── Anthropic endpoint routing ───────────────────────────────────────────────


class TestAnthropicRouting:
  @pytest.mark.asyncio
  async def test_anthropic_uses_messages_endpoint (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {
        "choices": [{"message": {"content": "hi"}}],
    })
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    router = MultiProviderRouter ()
    with patch ("aiohttp.ClientSession", return_value = mock_session):
      await router.non_stream_completion ([{"role": "user", "content": "hi"}], provider_type = "anthropic", )
      call_args = mock_session.post.call_args
      call_args [0] [0] if call_args [0] else call_args.kwargs.get ("url", "")
      # The URL should use /messages for Anthropic
      # (aiohttp session.post is called with positional url)
      assert "/messages" in str (call_args)


# ── Singleton and backward-compat wrappers ───────────────────────────────────


class TestSingletonAndWrappers:
  def test_get_router_returns_singleton (self):
    r1 = get_router ()
    r2 = get_router ()
    assert r1 is r2

  @pytest.mark.asyncio
  async def test_module_level_non_stream (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {"choices": [{"message": {"content": "module answer"}}]})
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      result = await non_stream_completion ([{"role": "user", "content": "hi"}])
      assert result == "module answer"

  def test_module_level_sync (self):
    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.json = AsyncMock (return_value = {"choices": [{"message": {"content": "sync"}}]})
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      result = non_stream_completion_sync ([{"role": "user", "content": "hi"}])
      assert result == "sync"

  @pytest.mark.asyncio
  async def test_module_level_stream (self):
    async def mock_lines ():
      yield b'data: {"id": "1", "choices": [{"delta": {"content": "ok"}}]}'
      yield b"data: [DONE]"

    mock_content = MagicMock ()
    mock_content.__aiter__ = MagicMock (return_value = mock_lines ())

    mock_response = MagicMock ()
    mock_response.status = 200
    mock_response.content = mock_content
    mock_response.close = MagicMock ()

    mock_session = MagicMock ()
    mock_session.post = AsyncMock (return_value = mock_response)
    mock_session.close = AsyncMock ()

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      chunks = []
      async for chunk in stream_completion ([{"role": "user", "content": "hi"}]):
        chunks.append (chunk)
      assert len (chunks) == 1


# ── LLMError ─────────────────────────────────────────────────────────────────


class TestLLMError:
  def test_is_exception (self):
    with pytest.raises (LLMError):
      raise LLMError ("test")

  def test_message (self):
    err = LLMError ("something broke")
    assert str (err) == "something broke"
