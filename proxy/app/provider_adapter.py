# proxy/app/provider_adapter.py
"""
Multi-provider adapter for RAG proxy.
Transparently translates between internal OpenAI-compatible format and
external provider-specific formats (Anthropic, Ollama, OpenRouter, etc.).

Поддерживает / Supports:
- OpenAI-compatible (vLLM, llama.cpp, LiteLLM, Ollama, etc.)
- Anthropic (Claude API)
- Generic REST (custom endpoints)
- Tool/function calling across providers
- Streaming translation across providers
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientTimeout
from app.config import (
    LLM_API_KEY,
    LLM_ENDPOINT,
    LLM_MODEL_NAME,
    LLM_PROVIDER_TYPE,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
)

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    """Supported AI provider types."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    GENERIC = "generic"


@dataclass
class ToolDefinition:
    """Tool/function definition compatible with OpenAI function calling format."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Result of a tool execution."""

    tool_call_id: str
    name: str
    content: str
    error: str | None = None


class ProviderAdapter:
    """
    Base adapter for translating between internal format and provider-specific format.

    Internal canonical format is OpenAI-compatible:
    - Messages: [{"role": "...", "content": "...", "tool_calls": [...], "tool_call_id": "..."}]
    - Streaming: SSE chunks with "data: " prefix
    """

    def translate_request(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Convert internal request to provider-specific payload."""
        raise NotImplementedError

    def translate_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Convert provider response to OpenAI-compatible format."""
        raise NotImplementedError

    def translate_stream_chunk(self, chunk: bytes) -> dict[str, Any] | None:
        """Convert a raw stream chunk to OpenAI-compatible SSE chunk."""
        raise NotImplementedError

    @property
    def headers(self) -> dict[str, str]:
        """HTTP headers for the provider."""
        raise NotImplementedError


class OpenAIAdapter(ProviderAdapter):
    """Adapter for OpenAI-compatible APIs (vLLM, llama.cpp, LiteLLM, etc.)."""

    @property
    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if LLM_API_KEY:
            h["Authorization"] = f"Bearer {LLM_API_KEY}"
        return h

    def translate_request(self, messages, temperature=0.2, max_tokens=4096, tools=None, stream=False) -> dict[str, Any]:
        payload = {
            "model": LLM_MODEL_NAME,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            payload["tool_choice"] = "auto"
        return payload

    def translate_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        return response_data

    def translate_stream_chunk(self, chunk: bytes) -> dict[str, Any] | None:
        line = chunk.decode("utf-8").strip()
        if not line or not line.startswith("data: "):
            return None
        data_str = line[6:]
        if data_str == "[DONE]":
            return {"_done": True}
        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            return None


class AnthropicAdapter(ProviderAdapter):
    """
    Adapter for Anthropic Claude API.
    Translates between OpenAI message format and Anthropic Messages API format.
    """

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": LLM_API_KEY or "",
            "anthropic-version": "2023-06-01",
        }

    def translate_request(self, messages, temperature=0.2, max_tokens=4096, tools=None, stream=False) -> dict[str, Any]:
        # Extract system message if present
        system = None
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                system = msg.get("content", "")
            elif role == "assistant":
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls", [])
                anthropic_msg = {"role": "assistant", "content": content}
                if tool_calls:
                    anthropic_msg["content"] = [
                        {"type": "text", "text": content} if content else None,
                        *[
                            {
                                "type": "tool_use",
                                "id": tc.get("id", ""),
                                "name": tc.get("function", {}).get("name", ""),
                                "input": json.loads(tc.get("function", {}).get("arguments", "{}")),
                            }
                            for tc in tool_calls
                        ],
                    ]
                    anthropic_msg["content"] = [c for c in anthropic_msg.get("content", []) if c is not None]
                anthropic_messages.append(anthropic_msg)
            elif role == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id", ""),
                                "content": msg.get("content", ""),
                            }
                        ],
                    }
                )
            else:
                anthropic_messages.append({"role": "user", "content": msg.get("content", "")})

        payload = {
            "model": LLM_MODEL_NAME,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]
        if stream:
            payload["stream"] = True
        return payload

    def translate_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """Convert Anthropic response to OpenAI format."""
        content = response_data.get("content", [])
        text_content = ""
        tool_calls = []

        for block in content:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }
                )

        return {
            "id": response_data.get("id", ""),
            "object": "chat.completion",
            "created": 0,
            "model": response_data.get("model", LLM_MODEL_NAME),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text_content or None,
                        "tool_calls": tool_calls or None,
                    },
                    "finish_reason": response_data.get("stop_reason", "stop"),
                }
            ],
            "usage": {
                "prompt_tokens": response_data.get("usage", {}).get("input_tokens", 0),
                "completion_tokens": response_data.get("usage", {}).get("output_tokens", 0),
                "total_tokens": (
                    response_data.get("usage", {}).get("input_tokens", 0)
                    + response_data.get("usage", {}).get("output_tokens", 0)
                ),
            },
        }

    def translate_stream_chunk(self, chunk: bytes) -> dict[str, Any] | None:
        """Convert Anthropic SSE chunk to OpenAI format."""
        line = chunk.decode("utf-8").strip()
        if not line or not line.startswith("data: "):
            return None
        data_str = line[6:]
        if data_str == "[DONE]":
            return {"_done": True}

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return None

        if data.get("type") == "message_stop":
            return {"_done": True}

        event_type = data.get("type", "")
        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                return {
                    "id": data.get("index", ""),
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": delta.get("text", "")},
                            "finish_reason": None,
                        }
                    ],
                }
            elif delta.get("type") == "input_json_delta":
                return {
                    "id": data.get("index", ""),
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"arguments": delta.get("partial_json", "")},
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
        elif event_type == "message_delta":
            return {
                "id": "",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": data.get("delta", {}).get("stop_reason", "stop"),
                    }
                ],
            }

        return None


class OllamaAdapter(OpenAIAdapter):
    """
    Adapter for Ollama API (OpenAI-compatible by default via ollama serve).
    Has minor differences: no Authorization header, model endpoint variant.
    """

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def translate_request(self, messages, temperature=0.2, max_tokens=4096, tools=None, stream=False) -> dict[str, Any]:
        payload = super().translate_request(messages, temperature, max_tokens, tools, stream)
        # Ollama uses "options" for extra params
        payload["options"] = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        return payload


class GenericAdapter(OpenAIAdapter):
    """
    Adapter for any generic REST API endpoint.
    Uses a configurable request/response transformation.
    """

    def __init__(self, request_transform: Callable | None = None, response_transform: Callable | None = None):
        self._request_transform = request_transform
        self._response_transform = response_transform

    def translate_request(self, messages, temperature=0.2, max_tokens=4096, tools=None, stream=False) -> dict[str, Any]:
        payload = super().translate_request(messages, temperature, max_tokens, tools, stream)
        if self._request_transform:
            payload = self._request_transform(payload)
        return payload

    def translate_response(self, response_data: dict[str, Any]) -> dict[str, Any]:
        if self._response_transform:
            response_data = self._response_transform(response_data)
        return super().translate_response(response_data)


class MultiProviderRouter:
    """
    Routes LLM requests through the appropriate provider adapter.
    Handles streaming and non-streaming with transparent translation.
    """

    ADAPTERS = {
        ProviderType.OPENAI: OpenAIAdapter,
        ProviderType.ANTHROPIC: AnthropicAdapter,
        ProviderType.OLLAMA: OllamaAdapter,
        ProviderType.GENERIC: GenericAdapter,
    }

    def __init__(self, provider_type: str | None = None):
        provider_str = (provider_type or LLM_PROVIDER_TYPE or "openai").lower()
        try:
            self.provider_type = ProviderType(provider_str)
        except ValueError:
            logger.warning(f"Unknown provider type '{provider_str}', falling back to openai")
            self.provider_type = ProviderType.OPENAI
        self.adapter = self.ADAPTERS[self.provider_type]()
        self.endpoint = LLM_ENDPOINT
        self.api_key = LLM_API_KEY

    async def _send_request(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        stream: bool = False,
        tools: list[ToolDefinition] | None = None,
        tool_results: list[ToolResult] | None = None,
        retry: int = MAX_RETRIES,
    ) -> Any:
        """Send request through the appropriate adapter."""
        # Inject tool results into messages if provided
        if tool_results:
            messages = list(messages)
            for tr in tool_results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id,
                        "name": tr.name,
                        "content": tr.content,
                    }
                )

        payload = self.adapter.translate_request(messages, temperature, max_tokens, tools, stream)
        headers = self.adapter.headers
        url = f"{self.endpoint}/chat/completions"

        # Anthropic uses a different endpoint path
        if self.provider_type == ProviderType.ANTHROPIC:
            url = f"{self.endpoint}/messages"

        timeout = ClientTimeout(total=REQUEST_TIMEOUT)

        for attempt in range(retry + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"LLM API error {response.status}: {error_text}")
                            raise LLMError(f"LLM returned {response.status}: {error_text}")

                        if stream:
                            return response
                        else:
                            data = await response.json()
                            translated = self.adapter.translate_response(data)
                            if "choices" not in translated or not translated["choices"]:
                                raise LLMError("Invalid response format from LLM")
                            return translated
            except (TimeoutError, ClientError, LLMError) as e:
                logger.warning(f"LLM request attempt {attempt + 1}/{retry + 1} failed: {e}")
                if attempt < retry:
                    delay = RETRY_DELAY * (attempt + 1)
                    await asyncio.sleep(delay)
                else:
                    raise LLMError(f"LLM request failed after {retry + 1} attempts: {e}") from e

    async def stream_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[ToolDefinition] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming completion with provider translation."""
        response = await self._send_request(messages, temperature, max_tokens, stream=True, tools=tools)

        async for raw_line in response.content:
            chunk = self.adapter.translate_stream_chunk(raw_line)
            if chunk is None:
                continue
            if chunk.get("_done"):
                break
            yield chunk

    async def non_stream_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[ToolDefinition] | None = None,
        tool_results: list[ToolResult] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming completion with provider translation.
        Returns full response dict including content and optional tool_calls."""
        return await self._send_request(
            messages, temperature, max_tokens, stream=False, tools=tools, tool_results=tool_results
        )

    async def non_stream_completion_text(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Convenience method that returns just the text content."""
        data = await self.non_stream_completion(messages, temperature, max_tokens)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected LLM response structure: {data}")
            raise LLMError(f"Failed to extract content: {e}") from e

    async def tool_use_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> list[ToolCall]:
        """Request tool calls from the LLM. Returns list of tool calls."""
        data = await self.non_stream_completion(messages, temperature, max_tokens, tools=tools)
        try:
            message = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls", [])
            return [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    name=tc.get("function", {}).get("name", ""),
                    arguments=json.loads(tc.get("function", {}).get("arguments", "{}")),
                )
                for i, tc in enumerate(tool_calls)
            ]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse tool calls: {e}")
            return []

    def non_stream_completion_sync(self, messages, temperature=0.2, max_tokens=4096) -> str:
        """Synchronous wrapper for non-async contexts (e.g., LangGraph nodes)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.non_stream_completion_text(messages, temperature, max_tokens))
        finally:
            loop.close()


class LLMError(Exception):
    """Exception raised on LLM call failure."""

    pass


# Singleton router instance
_router: MultiProviderRouter | None = None


def get_router() -> MultiProviderRouter:
    """Get or create the singleton MultiProviderRouter."""
    global _router
    if _router is None:
        _router = MultiProviderRouter()
    return _router


# Backward-compatible wrappers that use the singleton router
async def stream_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> AsyncIterator[dict[str, Any]]:
    router = get_router()
    async for chunk in router.stream_completion(messages, temperature, max_tokens):
        yield chunk


async def non_stream_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    router = get_router()
    return await router.non_stream_completion_text(messages, temperature, max_tokens)


def non_stream_completion_sync(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    router = get_router()
    return router.non_stream_completion_sync(messages, temperature, max_tokens)
