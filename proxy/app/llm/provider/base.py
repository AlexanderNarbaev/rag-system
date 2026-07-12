# proxy/app/llm/provider/base.py
"""Base provider adapter classes and router for multi-provider LLM support."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientTimeout

from proxy.app.shared.config import (
    LLM_API_KEY as _DEFAULT_LLM_API_KEY,
)
from proxy.app.shared.config import (
    LLM_ENDPOINT as _DEFAULT_LLM_ENDPOINT,
)
from proxy.app.shared.config import (
    LLM_PROVIDER_TYPE as _DEFAULT_LLM_PROVIDER_TYPE,
)
from proxy.app.shared.config import (
    MAX_RETRIES as _DEFAULT_MAX_RETRIES,
)
from proxy.app.shared.config import (
    REQUEST_TIMEOUT as _DEFAULT_REQUEST_TIMEOUT,
)
from proxy.app.shared.config import (
    RETRY_DELAY as _DEFAULT_RETRY_DELAY,
)
from proxy.app.tools.definition import ToolCall, ToolDefinition, ToolResult


def _get_config(attr: str, default):
    """Get config value, checking provider package level first for test monkeypatching."""
    import proxy.app.llm.provider as _pkg

    return getattr(_pkg, attr, default)


logger = logging.getLogger(__name__)


# ── Circuit breaker helpers ──────────────────────────────────────────────────


def _record_llm_success() -> None:
    """Record a successful LLM call to the circuit breaker."""
    try:
        from proxy.app.shared.circuit_breaker import get_breaker as _llm_cb

        _llm_cb("llm_backend").success()
    except (ImportError, Exception):
        pass


def _record_llm_failure() -> None:
    """Record a failed LLM call to the circuit breaker."""
    try:
        from proxy.app.shared.circuit_breaker import get_breaker as _llm_cb

        _llm_cb("llm_backend").failure()
    except (ImportError, Exception):
        pass


class ProviderType(StrEnum):
    """Supported AI provider types."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    GENERIC = "generic"


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


class LLMError(Exception):
    """Exception raised on LLM call failure."""

    pass


class MultiProviderRouter:
    """
    Routes LLM requests through the appropriate provider adapter.
    Handles streaming and non-streaming with transparent translation.
    Supports per-request provider_type override for multi-provider routing.
    """

    def __init__(self, provider_type: str | None = None):
        from proxy.app.llm.provider.openai import (
            AnthropicAdapter,
            GenericAdapter,
            OllamaAdapter,
            OpenAIAdapter,
        )

        self.ADAPTERS = {
            ProviderType.OPENAI: OpenAIAdapter,
            ProviderType.ANTHROPIC: AnthropicAdapter,
            ProviderType.OLLAMA: OllamaAdapter,
            ProviderType.GENERIC: GenericAdapter,
        }

        provider_cfg = _get_config("LLM_PROVIDER_TYPE", _DEFAULT_LLM_PROVIDER_TYPE)
        provider_str = (provider_type or provider_cfg or "openai").lower()
        try:
            self.provider_type = ProviderType(provider_str)
        except ValueError:
            logger.warning(f"Unknown provider type '{provider_str}', falling back to openai")
            self.provider_type = ProviderType.OPENAI
        self.adapter = self.ADAPTERS[self.provider_type]()
        self.endpoint = _get_config("LLM_ENDPOINT", _DEFAULT_LLM_ENDPOINT)
        self.api_key = _get_config("LLM_API_KEY", _DEFAULT_LLM_API_KEY)
        # Cache of per-provider-type adapters for per-request overrides
        self._adapter_cache: dict[ProviderType, ProviderAdapter] = {}

    def _resolve_provider(self, provider_type: str | None = None) -> tuple[ProviderAdapter, ProviderType]:
        """Resolve the adapter and provider type for a request."""
        if not provider_type:
            return self.adapter, self.provider_type

        pt_str = provider_type.lower()
        try:
            pt = ProviderType(pt_str)
        except ValueError:
            logger.warning(f"Unknown per-request provider type '{pt_str}', using default")
            return self.adapter, self.provider_type

        if pt == self.provider_type:
            return self.adapter, self.provider_type

        if pt not in self._adapter_cache:
            adapter_cls = self.ADAPTERS.get(pt)
            if adapter_cls is None:
                logger.warning(f"No adapter for '{pt}', using default")
                return self.adapter, self.provider_type
            self._adapter_cache[pt] = adapter_cls()

        return self._adapter_cache[pt], pt

    async def _send_request(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        stream: bool = False,
        tools: list[ToolDefinition] | None = None,
        tool_results: list[ToolResult] | None = None,
        retry: int | None = None,
        provider_type: str | None = None,
    ) -> Any:
        """Send request through the appropriate adapter."""
        if retry is None:
            retry = _get_config("MAX_RETRIES", _DEFAULT_MAX_RETRIES)
        # Circuit breaker check — reject immediately if LLM backend is in OPEN state
        try:
            from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError as _CBOE  # noqa: N814
            from proxy.app.shared.circuit_breaker import get_breaker as _llm_cb

            if _llm_cb("llm_backend").state.name == "OPEN":
                raise _CBOE("LLM backend circuit breaker is OPEN")
        except ImportError:
            pass
        except _CBOE:  # type: ignore[name-defined]
            raise

        # Resolve adapter for this request
        adapter, pt = self._resolve_provider(provider_type)
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

        payload = adapter.translate_request(messages, temperature, max_tokens, tools, stream)
        headers = adapter.headers
        url = f"{self.endpoint}/chat/completions"

        # Anthropic uses a different endpoint path
        if pt == ProviderType.ANTHROPIC:
            url = f"{self.endpoint}/messages"

        timeout = ClientTimeout(total=_get_config("REQUEST_TIMEOUT", _DEFAULT_REQUEST_TIMEOUT))

        for attempt in range(retry + 1):
            try:
                async with aiohttp.ClientSession() as session:  # noqa: SIM117
                    async with session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"LLM API error {response.status}: {error_text}")
                            raise LLMError(f"LLM returned {response.status}: {error_text}")

                        if stream:
                            _record_llm_success()
                            return response, adapter
                        else:
                            data = await response.json()
                            translated = adapter.translate_response(data)
                            if "choices" not in translated or not translated["choices"]:
                                raise LLMError("Invalid response format from LLM")
                            _record_llm_success()
                            return translated
            except (TimeoutError, ClientError, LLMError) as e:
                logger.warning(f"LLM request attempt {attempt + 1}/{retry + 1} failed: {e}")
                if attempt < retry:
                    delay = _get_config("RETRY_DELAY", _DEFAULT_RETRY_DELAY) * (attempt + 1)
                    await asyncio.sleep(delay)
                else:
                    _record_llm_failure()
                    raise LLMError(f"LLM request failed after {retry + 1} attempts: {e}") from e

    async def stream_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[ToolDefinition] | None = None,
        provider_type: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming completion with provider translation."""
        response, adapter = await self._send_request(
            messages,
            temperature,
            max_tokens,
            stream=True,
            tools=tools,
            provider_type=provider_type,
        )

        async for raw_line in response.content:
            chunk = adapter.translate_stream_chunk(raw_line)
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
        provider_type: str | None = None,
    ) -> dict[str, Any]:
        """Non-streaming completion with provider translation."""
        return await self._send_request(
            messages,
            temperature,
            max_tokens,
            stream=False,
            tools=tools,
            tool_results=tool_results,
            provider_type=provider_type,
        )

    async def non_stream_completion_text(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        provider_type: str | None = None,
    ) -> str:
        """Convenience method that returns just the text content."""
        data = await self.non_stream_completion(
            messages,
            temperature,
            max_tokens,
            provider_type=provider_type,
        )
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
        provider_type: str | None = None,
    ) -> list[ToolCall]:
        """Request tool calls from the LLM. Returns list of tool calls."""
        data = await self.non_stream_completion(
            messages,
            temperature,
            max_tokens,
            tools=tools,
            provider_type=provider_type,
        )
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

    def non_stream_completion_sync(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        provider_type: str | None = None,
    ) -> str:
        """Synchronous wrapper for non-async contexts (e.g., LangGraph nodes)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.non_stream_completion_text(
                    messages,
                    temperature,
                    max_tokens,
                    provider_type=provider_type,
                )
            )
        finally:
            loop.close()
