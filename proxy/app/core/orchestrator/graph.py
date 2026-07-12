# proxy/app/core/orchestrator/graph.py
"""LangGraph state graph construction for RAG orchestration."""

import logging
from typing import Any, TypedDict

try:
    from langgraph.checkpoint import MemorySaver
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    END = None  # type: ignore[assignment]
    MemorySaver = None  # type: ignore[assignment,misc]
    StateGraph = None  # type: ignore[assignment,misc]

from proxy.app.core.orchestrator.nodes import (
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

logger = logging.getLogger(__name__)


class RAGState(TypedDict):
    """Состояние графа RAG."""

    query: str
    version: str | None
    rewritten_query: str | None
    rewrite_count: int
    retrieved_chunks: list[dict[str, Any]]
    reranked_chunks: list[dict[str, Any]]
    graph_context: str | None
    context: str
    answer: str
    sufficient: bool
    temperature: float
    max_tokens: int
    stream: bool
    # Tool/function calling
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    tool_loop_count: int
    tools_enabled: bool


def _self_critique_route(state: dict) -> str:
    """Route after self-critique: rewrite if needed, otherwise done."""
    if state.get("needs_rewrite"):
        return "rewrite"
    return "done"


def _self_reflection_route(state: dict) -> str:
    """Route after self-reflection: re-retrieve if gaps found, otherwise done."""
    if state.get("needs_reflection"):
        return "retrieve"
    return "done"


def _route_after_generate(state: RAGState) -> str:
    """Route after generate: if tool calls were requested, go to call_tools."""
    tool_calls = state.get("tool_calls", [])
    tool_loop_count = state.get("tool_loop_count", 0)
    max_tool_loops = 5

    if tool_calls and tool_loop_count < max_tool_loops:
        return "call_tools"
    return "reflect"


def build_rag_graph() -> StateGraph:
    """Создаёт и компилирует граф RAG с tool-calling поддержкой."""
    builder = StateGraph(RAGState)

    # Добавляем узлы
    builder.add_node("rewrite", rewrite_query)
    builder.add_node("retrieve", retrieve)
    builder.add_node("graph_expand", graph_expand)
    builder.add_node("rerank", rerank)
    builder.add_node("build_context", build_context_node)
    builder.add_node("generate", generate)
    builder.add_node("check_sufficiency", check_sufficiency)

    # Начало
    builder.set_entry_point("rewrite")

    # Переходы
    builder.add_edge("rewrite", "retrieve")
    builder.add_edge("retrieve", "check_sufficiency")

    # Условное ребро после проверки
    builder.add_conditional_edges("check_sufficiency", check_sufficiency, {"rewrite": "rewrite", "rerank": "rerank"})

    builder.add_edge("build_context", "generate")
    builder.add_node("self_reflection", self_reflection)
    builder.add_node("check_confidence", check_confidence)
    builder.add_node("self_critique", self_critique)
    builder.add_node("call_tools", call_tools)

    # Route from generate:
    # - If tool_calls were requested → call_tools
    # - Otherwise → self_reflection
    builder.add_conditional_edges(
        "generate",
        _route_after_generate,
        {
            "call_tools": "call_tools",
            "reflect": "self_reflection",
        },
    )

    # After tool calls, loop back to generate with tool results
    builder.add_edge("call_tools", "generate")

    builder.add_conditional_edges(
        "self_reflection",
        _self_reflection_route,
        {
            "retrieve": "retrieve",
            "done": "check_confidence",
        },
    )

    # Route from check_confidence:
    builder.add_conditional_edges(
        "check_confidence",
        lambda s: (
            "escalate" if s.get("needs_escalation") else ("self_critique" if s.get("needs_self_critique") else "done")
        ),
        {
            "escalate": "rewrite",
            "self_critique": "self_critique",
            "done": END,
        },
    )

    # Route from self_critique:
    builder.add_conditional_edges(
        "self_critique",
        _self_critique_route,
        {
            "rewrite": "rewrite",
            "done": END,
        },
    )

    # Добавляем графовое расширение как опциональный узел между rerank и build_context
    builder.add_edge("rerank", "graph_expand")
    builder.add_edge("graph_expand", "build_context")

    return builder


class RAGOrchestrator:
    """Обёртка над скомпилированным графом."""

    def __init__(self, checkpointer=None):
        self.builder = build_rag_graph()
        self.graph = self.builder.compile(checkpointer=checkpointer or MemorySaver())

    async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Асинхронный вызов графа."""
        return await self.graph.ainvoke(inputs)

    def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Синхронный вызов графа."""
        return self.graph.invoke(inputs)


# Функция для получения экземпляра оркестратора (синглтон)
_orchestrator = None


def get_orchestrator() -> RAGOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RAGOrchestrator()
    return _orchestrator
