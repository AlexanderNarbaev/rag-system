# proxy/app/llm/provider/__init__.py
"""Multi-provider LLM adapter — OpenAI, Anthropic, Ollama, Generic.

Re-exports all public symbols for backward compatibility with
``from proxy.app.llm.provider import ...`` imports.
"""

from proxy.app.llm.provider.base import (
  MultiProviderRouter,
  ProviderAdapter,
  ProviderType,
  _record_llm_failure,
  _record_llm_success,
)
from proxy.app.llm.provider.openai import (
  AnthropicAdapter,
  GenericAdapter,
  OllamaAdapter,
  OpenAIAdapter,
)
from proxy.app.llm.provider.utils import (
  _router,  # noqa: F401 — re-export for test patching
  get_router,
  non_stream_completion,
  non_stream_completion_sync,
  stream_completion,
)
from proxy.app.shared.config import (  # noqa: F401 — re-export for test patching
  LLM_API_KEY,
  LLM_ENDPOINT,
  LLM_MODEL_NAME,
  LLM_PROVIDER_TYPE,
  MAX_RETRIES,
  REQUEST_TIMEOUT,
  RETRY_DELAY,
)
from proxy.app.shared.exceptions import LLMError
from proxy.app.tools.definition import ToolCall, ToolDefinition, ToolResult

__all__ = [
    "AnthropicAdapter", "GenericAdapter", "LLMError", "MultiProviderRouter", "OllamaAdapter", "OpenAIAdapter",
    "ProviderAdapter", "ProviderType", "ToolCall", "ToolDefinition", "ToolResult", "_record_llm_failure",
    "_record_llm_success", "get_router", "non_stream_completion", "non_stream_completion_sync", "stream_completion",
]
