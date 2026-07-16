# proxy/app/llm/__init__.py
"""LLM integration — provider adapter, router, SLM, remote services."""

from proxy.app.llm.provider import non_stream_completion, stream_completion
from proxy.app.llm.slm import IntentType, classify_intent, decompose_query

__all__ = [
    "IntentType",
    "classify_intent",
    "decompose_query",
    "non_stream_completion",
    "stream_completion",
]
