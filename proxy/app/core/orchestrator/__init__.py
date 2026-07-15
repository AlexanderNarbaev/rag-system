# proxy/app/core/orchestrator/__init__.py
"""RAG orchestration using LangGraph agentic pipeline.

Re-exports all public symbols for backward compatibility with
``from proxy.app.core.orchestrator import ...`` imports.
"""

from proxy.app.core.orchestrator.graph import (  # type: ignore[attr-defined]
  END,
  LANGGRAPH_AVAILABLE,
  MemorySaver,
  RAGOrchestrator,
  RAGState,
  StateGraph,
  _self_critique_route,
  _self_reflection_route,
  build_rag_graph,
  get_orchestrator,
)
from proxy.app.core.orchestrator.nodes import (
  _dynamic_top_k,
  build_context_node,
  call_tools,
  check_confidence,
  check_sufficiency,
  generate,
  graph_expand,
  rerank,
  retrieve,
  rewrite_query,
  self_critique,
  self_reflection,
)
from proxy.app.core.rerank import rerank_chunks  # noqa: F401 — re-export for test patching
from proxy.app.core.retrieval import hybrid_search  # noqa: F401 — re-export for test patching
from proxy.app.llm.provider import non_stream_completion  # noqa: F401 — re-export for test patching
from proxy.app.llm.provider.utils import non_stream_completion_sync  # noqa: F401 — re-export for test patching
from proxy.app.llm.slm import IntentType, classify_intent  # noqa: F401 — re-export for test patching

__all__ = [
    "END", "IntentType", "LANGGRAPH_AVAILABLE", "MemorySaver", "RAGOrchestrator", "RAGState", "StateGraph",
    "_dynamic_top_k", "_self_critique_route", "_self_reflection_route", "build_context_node", "build_rag_graph",
    "call_tools", "check_confidence", "check_sufficiency", "classify_intent", "generate", "get_orchestrator",
    "graph_expand", "rerank", "retrieve", "rewrite_query", "self_critique", "self_reflection",
]
