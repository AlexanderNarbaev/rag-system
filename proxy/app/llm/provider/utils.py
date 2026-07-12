# proxy/app/llm/provider/utils.py
"""Helper functions and backward-compatible wrappers for LLM provider."""

from collections.abc import AsyncIterator
from typing import Any

from proxy.app.llm.provider.base import MultiProviderRouter

# Singleton router instance — exposed at module level for test patching
_router: MultiProviderRouter | None = None


def get_router() -> MultiProviderRouter:
    """Get or create the singleton MultiProviderRouter."""
    global _router
    # Check if test fixture reset the package-level _router
    import proxy.app.llm.provider as _pkg

    pkg_router = getattr(_pkg, "_router", None)
    if pkg_router is None and _router is not None:
        _router = None  # Sync with package level
    if _router is None:
        _router = MultiProviderRouter()
        _pkg._router = _router  # Sync back to package level
    return _router


# Backward-compatible wrappers that use the singleton router
async def stream_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 4096,
    provider_type: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    router = get_router()
    async for chunk in router.stream_completion(
        messages,
        temperature,
        max_tokens,
        provider_type=provider_type,
    ):
        yield chunk


async def non_stream_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 4096,
    provider_type: str | None = None,
) -> str:
    router = get_router()
    return await router.non_stream_completion_text(
        messages,
        temperature,
        max_tokens,
        provider_type=provider_type,
    )


def non_stream_completion_sync(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 4096,
    provider_type: str | None = None,
) -> str:
    router = get_router()
    return router.non_stream_completion_sync(
        messages,
        temperature,
        max_tokens,
        provider_type=provider_type,
    )
