# proxy/app/llm/provider/openai.py
"""OpenAI-compatible provider adapters (OpenAI, Anthropic, Ollama, Generic)."""

import json
from collections.abc import Callable
from typing import Any

from proxy.app.llm.provider.base import ProviderAdapter
from proxy.app.shared.config import LLM_API_KEY as _LLM_API_KEY
from proxy.app.shared.config import LLM_MODEL_NAME as _LLM_MODEL_NAME
from proxy.app.tools.definition import ToolDefinition


def _get_api_key () -> str:
  """Get LLM_API_KEY, checking provider module first for test patching."""
  import proxy.app.llm.provider as _pkg
  
  return getattr (_pkg, "LLM_API_KEY", _LLM_API_KEY) or ""


def _get_model_name () -> str:
  """Get LLM_MODEL_NAME, checking provider module first for test patching."""
  import proxy.app.llm.provider as _pkg
  
  return getattr (_pkg, "LLM_MODEL_NAME", _LLM_MODEL_NAME) or ""


class OpenAIAdapter (ProviderAdapter):
  """Adapter for OpenAI-compatible APIs (vLLM, llama.cpp, LiteLLM, etc.)."""
  
  @property
  def headers (self) -> dict [str, str]:
    h = {"Content-Type": "application/json"}
    api_key = _get_api_key ()
    if api_key:
      h ["Authorization"] = f"Bearer {api_key}"
    return h
  
  def translate_request (
      self, messages: list [dict [str, Any]], temperature: float = 0.2, max_tokens: int = 4096,
      tools: list [ToolDefinition] | None = None, stream: bool = False, ) -> dict [str, Any]:
    payload = {
        "model": _get_model_name (), "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
        "stream": stream,
    }
    if tools:
      payload ["tools"] = [t.to_openai_format () for t in tools]
      payload ["tool_choice"] = "auto"
    return payload
  
  def translate_response (self, response_data: dict [str, Any]) -> dict [str, Any]:
    return response_data
  
  def translate_stream_chunk (self, chunk: bytes) -> dict [str, Any] | None:
    line = chunk.decode ("utf-8").strip ()
    if not line or not line.startswith ("data: "):
      return None
    data_str = line [6:]
    if data_str == "[DONE]":
      return {"_done": True}
    try:
      result: dict [str, Any] = json.loads (data_str)
      return result
    except json.JSONDecodeError:
      return None


class AnthropicAdapter (ProviderAdapter):
  """
  Adapter for Anthropic Claude API.
  Translates between OpenAI message format and Anthropic Messages API format.
  """
  
  @property
  def headers (self) -> dict [str, str]:
    return {
        "Content-Type": "application/json", "x-api-key": _get_api_key (), "anthropic-version": "2023-06-01",
    }
  
  def translate_request (
      self, messages: list [dict [str, Any]], temperature: float = 0.2, max_tokens: int = 4096,
      tools: list [ToolDefinition] | None = None, stream: bool = False, ) -> dict [str, Any]:
    # Extract system message if present
    system = None
    anthropic_messages = []
    for msg in messages:
      role = msg.get ("role", "user")
      if role == "system":
        system = msg.get ("content", "")
      elif role == "assistant":
        content = msg.get ("content", "")
        tool_calls = msg.get ("tool_calls", [])
        anthropic_msg = {"role": "assistant", "content": content}
        if tool_calls:
          anthropic_msg ["content"] = [
              {"type": "text", "text": content} if content else None, *[{
                  "type": "tool_use", "id": tc.get ("id", ""), "name": tc.get ("function", {}).get ("name", ""),
                  "input": json.loads (tc.get ("function", {}).get ("arguments", "{}")),
              } for tc in tool_calls],
          ]
          anthropic_msg ["content"] = [c for c in anthropic_msg.get ("content", []) if c is not None]
        anthropic_messages.append (anthropic_msg)
      elif role == "tool":
        anthropic_messages.append ({
            "role": "user", "content": [
                {
                    "type": "tool_result", "tool_use_id": msg.get ("tool_call_id", ""),
                    "content": msg.get ("content", ""),
                }
            ],
        })
      else:
        anthropic_messages.append ({"role": "user", "content": msg.get ("content", "")})
    
    payload = {
        "model": _get_model_name (), "messages": anthropic_messages, "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
      payload ["system"] = system
    if tools:
      payload ["tools"] = [t.to_anthropic_format () for t in tools]
    if stream:
      payload ["stream"] = True
    return payload
  
  def translate_response (self, response_data: dict [str, Any]) -> dict [str, Any]:
    """Convert Anthropic response to OpenAI format."""
    content = response_data.get ("content", [])
    text_content = ""
    tool_calls = []
    
    for block in content:
      if block.get ("type") == "text":
        text_content += block.get ("text", "")
      elif block.get ("type") == "tool_use":
        tool_calls.append ({
            "id": block.get ("id", ""), "type": "function", "function": {
                "name": block.get ("name", ""), "arguments": json.dumps (block.get ("input", {})),
            },
        })
    
    return {
        "id": response_data.get ("id", ""), "object": "chat.completion", "created": 0,
        "model": response_data.get ("model", _get_model_name ()), "choices": [
            {
                "index": 0, "message": {
                "role": "assistant", "content": text_content or None, "tool_calls": tool_calls or None,
            }, "finish_reason": response_data.get ("stop_reason", "stop"),
            }
        ], "usage": {
            "prompt_tokens": response_data.get ("usage", {}).get ("input_tokens", 0),
            "completion_tokens": response_data.get ("usage", {}).get ("output_tokens", 0), "total_tokens": (
                response_data.get ("usage", {}).get ("input_tokens", 0) + response_data.get ("usage", {}).get (
              "output_tokens", 0)),
        },
    }
  
  def translate_stream_chunk (self, chunk: bytes) -> dict [str, Any] | None:
    """Convert Anthropic SSE chunk to OpenAI format."""
    line = chunk.decode ("utf-8").strip ()
    if not line or not line.startswith ("data: "):
      return None
    data_str = line [6:]
    if data_str == "[DONE]":
      return {"_done": True}
    
    try:
      data = json.loads (data_str)
    except json.JSONDecodeError:
      return None
    
    if data.get ("type") == "message_stop":
      return {"_done": True}
    
    event_type = data.get ("type", "")
    if event_type == "content_block_delta":
      delta = data.get ("delta", {})
      if delta.get ("type") == "text_delta":
        return {
            "id": data.get ("index", ""), "object": "chat.completion.chunk", "choices": [
                {
                    "index": 0, "delta": {"content": delta.get ("text", "")}, "finish_reason": None,
                }
            ],
        }
      elif delta.get ("type") == "input_json_delta":
        return {
            "id": data.get ("index", ""), "object": "chat.completion.chunk", "choices": [
                {
                    "index": 0, "delta": {
                    "tool_calls": [
                        {
                            "index": 0, "function": {"arguments": delta.get ("partial_json", "")},
                        }
                    ]
                }, "finish_reason": None,
                }
            ],
        }
    elif event_type == "message_delta":
      return {
          "id": "", "object": "chat.completion.chunk", "choices": [
              {
                  "index": 0, "delta": {}, "finish_reason": data.get ("delta", {}).get ("stop_reason", "stop"),
              }
          ],
      }
    
    return None


class OllamaAdapter (OpenAIAdapter):
  """
  Adapter for Ollama API (OpenAI-compatible by default via ollama serve).
  Has minor differences: no Authorization header, model endpoint variant.
  """
  
  @property
  def headers (self) -> dict [str, str]:
    return {"Content-Type": "application/json"}
  
  def translate_request (
      self, messages: list [dict [str, Any]], temperature: float = 0.2, max_tokens: int = 4096,
      tools: list [ToolDefinition] | None = None, stream: bool = False, ) -> dict [str, Any]:
    payload = super ().translate_request (messages, temperature, max_tokens, tools, stream)
    # Ollama uses "options" for extra params
    payload ["options"] = {
        "temperature": temperature, "num_predict": max_tokens,
    }
    return payload


class GenericAdapter (OpenAIAdapter):
  """
  Adapter for any generic REST API endpoint.
  Uses a configurable request/response transformation.
  """
  
  def __init__ (
      self, request_transform: Callable [[dict [str, Any]], dict [str, Any]] | None = None,
      response_transform: Callable [[dict [str, Any]], dict [str, Any]] | None = None, ):
    self._request_transform = request_transform
    self._response_transform = response_transform
  
  def translate_request (
      self, messages: list [dict [str, Any]], temperature: float = 0.2, max_tokens: int = 4096,
      tools: list [ToolDefinition] | None = None, stream: bool = False, ) -> dict [str, Any]:
    payload = super ().translate_request (messages, temperature, max_tokens, tools, stream)
    if self._request_transform:
      payload = self._request_transform (payload)
    return payload
  
  def translate_response (self, response_data: dict [str, Any]) -> dict [str, Any]:
    if self._response_transform:
      response_data = self._response_transform (response_data)
    return super ().translate_response (response_data)
