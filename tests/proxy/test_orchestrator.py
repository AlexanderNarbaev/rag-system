"""Tests for orchestrator: graph construction, node functions, routing, and state management."""

from unittest.mock import MagicMock, patch

from proxy.app.core.orchestrator import (
    RAGState,
    _self_critique_route,
    _self_reflection_route,
    build_context_node,
    check_sufficiency,
    generate,
    graph_expand,
    rerank,
    retrieve,
    rewrite_query,
    self_critique,
)
from proxy.app.core.orchestrator.graph import _route_after_generate


def _make_chunk(text, score=0.8, hit_id="id1"):
    payload = {"text": text}
    mock_hit = MagicMock()
    mock_hit.id = hit_id
    mock_hit.score = score
    mock_hit.payload = payload
    return mock_hit


# ── Existing check_confidence tests ──────────────────────────────────────────


def test_check_confidence_high_score_no_escalation():
    with patch("proxy.app.shared.config.CONFIDENCE_THRESHOLD", 0.5):
        from proxy.app.core.orchestrator import check_confidence

        state = {
            "query": "What is Python?",
            "context": "Python is a programming language created in 1991 by Guido van Rossum. It is widely used.",
            "answer": (
                "Python is a programming language created in 1991 by Guido van Rossum. "
                "It is widely used for development."
            ),
            "rewrite_count": 0,
        }
        result = check_confidence(state)
        assert result["confidence"] is not None
        assert result["confidence"] > 0.5
        assert result["needs_escalation"] is False


def test_check_confidence_low_score_escalation():
    with (
        patch("proxy.app.shared.config.CONFIDENCE_THRESHOLD", 0.5),
        patch("proxy.app.shared.config.MAX_VERIFY_LOOPS", 2),
        patch("proxy.app.shared.config.ADMIN_ALERT_ENABLED", False),
        patch("proxy.app.shared.config.HALLUCINATION_CHECK_ENABLED", True),
    ):
        from proxy.app.core.orchestrator import check_confidence

        state = {
            "query": "What is XYZ?",
            "context": "",
            "answer": "I don't know about XYZ.",
            "rewrite_count": 0,
        }
        result = check_confidence(state)
        assert result["confidence"] < 0.5
        assert result["needs_escalation"] is True


def test_check_confidence_max_loops_no_escalation():
    with (
        patch("proxy.app.shared.config.CONFIDENCE_THRESHOLD", 0.5),
        patch("proxy.app.shared.config.MAX_VERIFY_LOOPS", 2),
        patch("proxy.app.shared.config.ADMIN_ALERT_ENABLED", False),
        patch("proxy.app.shared.config.HALLUCINATION_CHECK_ENABLED", True),
    ):
        from proxy.app.core.orchestrator import check_confidence

        state = {
            "query": "What is XYZ?",
            "context": "",
            "answer": "I don't know.",
            "rewrite_count": 2,
        }
        result = check_confidence(state)
        assert result["confidence"] < 0.5
        assert result["needs_escalation"] is False


def test_check_confidence_empty_answer():
    from proxy.app.core.orchestrator import check_confidence

    state = {
        "query": "test",
        "context": "context",
        "answer": "",
        "rewrite_count": 0,
    }
    result = check_confidence(state)
    assert result["confidence"] is None
    assert result["needs_escalation"] is False


# ── Graph construction tests ─────────────────────────────────────────────────


def test_build_rag_graph_returns_valid_graph():
    with (
        patch("proxy.app.core.orchestrator.graph.LANGGRAPH_AVAILABLE", True),
        patch("proxy.app.core.orchestrator.graph.StateGraph") as mock_sg,
    ):
        from proxy.app.core.orchestrator.graph import build_rag_graph

        graph = build_rag_graph()
        assert graph is not None
        assert mock_sg.called


def test_build_rag_graph_registers_all_nodes():
    with (
        patch("proxy.app.core.orchestrator.graph.LANGGRAPH_AVAILABLE", True),
        patch("proxy.app.core.orchestrator.graph.StateGraph") as mock_sg_class,
    ):
        from proxy.app.core.orchestrator.graph import build_rag_graph

        mock_builder = MagicMock()
        mock_sg_class.return_value = mock_builder
        build_rag_graph()

        expected_nodes = {
            "rewrite",
            "retrieve",
            "graph_expand",
            "rerank",
            "build_context",
            "generate",
            "check_sufficiency",
            "self_reflection",
            "check_confidence",
            "self_critique",
            "call_tools",
        }
        added_nodes = set()
        for call_args in mock_builder.add_node.call_args_list:
            added_nodes.add(call_args[0][0])
        assert expected_nodes == added_nodes


def test_build_rag_graph_entry_point():
    with (
        patch("proxy.app.core.orchestrator.graph.LANGGRAPH_AVAILABLE", True),
        patch("proxy.app.core.orchestrator.graph.StateGraph") as mock_sg_class,
    ):
        from proxy.app.core.orchestrator.graph import build_rag_graph

        mock_builder = MagicMock()
        mock_sg_class.return_value = mock_builder
        build_rag_graph()
        mock_builder.set_entry_point.assert_called_once_with("rewrite")


def test_get_orchestrator_none_when_langgraph_unavailable():
    from proxy.app.core.orchestrator import get_orchestrator
    from proxy.app.core.orchestrator import graph as graph_mod

    with patch.object(graph_mod, "LANGGRAPH_AVAILABLE", False):
        assert get_orchestrator() is None


# ── rewrite_query tests ──────────────────────────────────────────────────────


def test_rewrite_query_basic():
    with patch(
        "proxy.app.core.orchestrator.non_stream_completion_sync",
        return_value=" rewritten query ",
    ):
        state = {"query": "How to deploy Docker?", "rewrite_count": 0}
        result = rewrite_query(state)
        assert result["rewritten_query"] == "rewritten query"
        assert result["rewrite_count"] == 1


def test_rewrite_query_max_loops_exceeded():
    with patch("proxy.app.core.orchestrator.nodes.MAX_RETRIEVAL_LOOPS", 3):
        state = {"query": "How to deploy Docker?", "rewrite_count": 3}
        result = rewrite_query(state)
        assert result["rewritten_query"] == state["query"]
        assert result["rewrite_count"] == 3


def test_rewrite_query_llm_failure_fallback():
    with patch(
        "proxy.app.core.orchestrator.non_stream_completion_sync",
        side_effect=RuntimeError("LLM unavailable"),
    ):
        state = {"query": "Test query", "rewrite_count": 0}
        result = rewrite_query(state)
        assert result["rewritten_query"] == "Test query"
        assert result["rewrite_count"] == 1


# ── retrieve tests ───────────────────────────────────────────────────────────


def test_retrieve_returns_chunks():
    mock_hit = _make_chunk("Docker deployment guide")
    with (
        patch(
            "proxy.app.core.orchestrator.hybrid_search",
            return_value=[mock_hit],
        ),
        patch("proxy.app.core.retrieval.apply_time_decay", side_effect=lambda c: c),
    ):
        state = {"query": "Docker deployment", "rewritten_query": None}
        result = retrieve(state)
        assert len(result["retrieved_chunks"]) == 1
        assert result["retrieved_chunks"][0]["text"] == "Docker deployment guide"


def test_retrieve_uses_rewritten_query():
    mock_hit = _make_chunk("Rewritten result")
    with (
        patch(
            "proxy.app.core.orchestrator.hybrid_search",
            return_value=[mock_hit],
        ) as mock_search,
        patch("proxy.app.core.retrieval.apply_time_decay", side_effect=lambda c: c),
    ):
        state = {"query": "Original", "rewritten_query": "Rewritten", "version": None}
        retrieve(state)
        _, kwargs = mock_search.call_args
        assert kwargs["query"] == "Rewritten"


def test_retrieve_graceful_degradation():
    with patch(
        "proxy.app.core.orchestrator.hybrid_search",
        side_effect=ConnectionError("Qdrant down"),
    ):
        state = {"query": "Test", "rewritten_query": None}
        result = retrieve(state)
        assert result["retrieved_chunks"] == []


# ── graph_expand tests ───────────────────────────────────────────────────────


def test_graph_expand_disabled():
    with patch("proxy.app.core.orchestrator.nodes.USE_GRAPH_EXPANSION", False):
        state = {"query": "Test", "rewritten_query": None}
        result = graph_expand(state)
        assert result["graph_context"] == ""


def test_graph_expand_enabled_with_results():
    with (
        patch("proxy.app.core.orchestrator.nodes.USE_GRAPH_EXPANSION", True),
        patch(
            "proxy.app.core.retrieval.graph_expand_query",
            return_value="Entity: Docker, Type: Technology",
        ),
    ):
        state = {"query": "Docker overview", "rewritten_query": None}
        result = graph_expand(state)
        assert "Docker" in result["graph_context"]


def test_graph_expand_failure_returns_empty():
    with (
        patch("proxy.app.core.orchestrator.nodes.USE_GRAPH_EXPANSION", True),
        patch(
            "proxy.app.core.retrieval.graph_expand_query",
            side_effect=RuntimeError("Neo4j down"),
        ),
    ):
        state = {"query": "Docker", "rewritten_query": None}
        result = graph_expand(state)
        assert result["graph_context"] == ""


# ── check_sufficiency tests ──────────────────────────────────────────────────


def test_check_sufficiency_empty_chunks_rewrite():
    state = {"retrieved_chunks": [], "rewrite_count": 0}
    result = check_sufficiency(state)
    assert result == "rewrite"


def test_check_sufficiency_low_score_rewrite():
    with patch("proxy.app.core.orchestrator.nodes.MAX_RETRIEVAL_LOOPS", 3):
        chunks = [{"score": 0.2}, {"score": 0.3}]
        state = {"retrieved_chunks": chunks, "rewrite_count": 0}
        result = check_sufficiency(state)
        assert result == "rewrite"


def test_check_sufficiency_high_score_rerank():
    chunks = [{"score": 0.8}, {"score": 0.9}]
    state = {"retrieved_chunks": chunks, "rewrite_count": 0}
    result = check_sufficiency(state)
    assert result == "rerank"


def test_check_sufficiency_max_loops_rerank():
    with patch("proxy.app.core.orchestrator.nodes.MAX_RETRIEVAL_LOOPS", 1):
        chunks = [{"score": 0.3}]
        state = {"retrieved_chunks": chunks, "rewrite_count": 1}
        result = check_sufficiency(state)
        assert result == "rerank"


# ── rerank tests ─────────────────────────────────────────────────────────────


def test_rerank_basic():
    chunks = [
        {"id": 1, "text": "Chunk A", "score": 0.5, "payload": {}},
        {"id": 2, "text": "Chunk B", "score": 0.9, "payload": {}},
    ]
    with (
        patch(
            "proxy.app.core.orchestrator.rerank_chunks",
            return_value=[1, 0],
        ),
        patch(
            "proxy.app.core.context.deduplicate_chunks",
            side_effect=lambda x: x,
        ),
    ):
        state = {"query": "Test", "retrieved_chunks": chunks}
        result = rerank(state)
        assert len(result["reranked_chunks"]) == 2


def test_rerank_empty_chunks():
    state = {"retrieved_chunks": [], "query": "Test"}
    result = rerank(state)
    assert result["reranked_chunks"] == []


# ── build_context_node tests ─────────────────────────────────────────────────


def test_build_context_node_basic():
    chunks_with_scores = [
        ({"text": "Context A", "payload": {}}, 0.9),
        ({"text": "Context B", "payload": {}}, 0.7),
    ]
    with (
        patch(
            "proxy.app.core.context.build_context",
            return_value="Built context",
        ),
        patch("proxy.app.core.orchestrator.nodes.TokenOptimizer") as mock_optimizer_class,
    ):
        mock_optimizer = MagicMock()
        mock_optimizer.estimate_token_cost.return_value = 100
        mock_optimizer_class.return_value = mock_optimizer
        state = {
            "query": "Test",
            "reranked_chunks": chunks_with_scores,
            "graph_context": "",
            "max_tokens": 4096,
        }
        result = build_context_node(state)
        assert result["context"] == "Built context"
        assert result["sufficient"] is True


def test_build_context_node_with_graph_context():
    chunks_with_scores = [({"text": "A", "payload": {}}, 0.9)]
    with (
        patch(
            "proxy.app.core.context.build_context",
            return_value="Base context",
        ),
        patch("proxy.app.core.orchestrator.nodes.TokenOptimizer") as mock_optimizer_class,
    ):
        mock_optimizer = MagicMock()
        mock_optimizer.estimate_token_cost.return_value = 100
        mock_optimizer_class.return_value = mock_optimizer
        state = {
            "query": "Test",
            "reranked_chunks": chunks_with_scores,
            "graph_context": "\nGraph entities here",
            "max_tokens": 4096,
        }
        result = build_context_node(state)
        assert "Graph entities here" in result["context"]


# ── generate tests ───────────────────────────────────────────────────────────


def test_generate_basic():
    with patch(
        "proxy.app.core.orchestrator.non_stream_completion_sync",
        return_value="Generated answer text.",
    ):
        state = {
            "query": "What is Docker?",
            "context": "Docker is a container platform.",
            "temperature": 0.3,
            "max_tokens": 2048,
        }
        result = generate(state)
        assert result["answer"] == "Generated answer text."


# ── self_critique tests ──────────────────────────────────────────────────────


def test_self_critique_high_score():
    with patch("proxy.app.llm.slm._call_slm_sync", return_value="5"):
        state = {
            "query": "Test question",
            "answer": "Good answer.",
            "rewrite_count": 0,
            "self_critique_count": 0,
        }
        result = self_critique(state)
        assert result["self_critique_score"] == 5
        assert result["needs_rewrite"] is False


def test_self_critique_low_score_needs_rewrite():
    with patch("proxy.app.llm.slm._call_slm_sync", return_value="2"):
        state = {
            "query": "Test question",
            "answer": "Bad answer.",
            "rewrite_count": 0,
            "self_critique_count": 0,
            "max_rewrites": 3,
        }
        result = self_critique(state)
        assert result["self_critique_score"] == 2
        assert result["needs_rewrite"] is True


def test_self_critique_max_rewrites_exceeded():
    with patch("proxy.app.llm.slm._call_slm_sync", return_value="2"):
        state = {
            "query": "Test question",
            "answer": "Bad answer.",
            "rewrite_count": 2,
            "self_critique_count": 0,
            "max_rewrites": 2,
        }
        result = self_critique(state)
        assert result["needs_rewrite"] is False


def test_self_critique_empty_answer():
    state = {
        "query": "Test",
        "answer": "",
        "rewrite_count": 0,
        "self_critique_count": 0,
    }
    result = self_critique(state)
    assert result["needs_rewrite"] is False
    assert result["self_critique_score"] == 0


def test_self_critique_slm_failure():
    with patch("proxy.app.llm.slm._call_slm_sync", side_effect=Exception("SLM crash")):
        state = {
            "query": "Test question",
            "answer": "Some answer.",
            "rewrite_count": 0,
            "self_critique_count": 0,
        }
        result = self_critique(state)
        assert result["needs_rewrite"] is False
        assert result["self_critique_score"] == 3


# ── Routing function tests ───────────────────────────────────────────────────


def test_self_reflection_route_done():
    assert _self_reflection_route({"needs_reflection": False}) == "done"


def test_self_reflection_route_retrieve():
    assert _self_reflection_route({"needs_reflection": True}) == "retrieve"


def test_self_critique_route_rewrite():
    assert _self_critique_route({"needs_rewrite": True}) == "rewrite"


def test_self_critique_route_done():
    assert _self_critique_route({"needs_rewrite": False}) == "done"


def test_route_after_generate_with_tool_calls():
    state: dict = {
        "tool_calls": [{"id": "1", "function": {"name": "search"}}],
        "tool_loop_count": 0,
    }
    result = _route_after_generate(state)  # type: ignore[arg-type]
    assert result == "call_tools"


def test_route_after_generate_no_tool_calls():
    state: dict = {"tool_calls": [], "tool_loop_count": 0}
    result = _route_after_generate(state)  # type: ignore[arg-type]
    assert result == "reflect"


def test_route_after_generate_max_loops():
    state: dict = {
        "tool_calls": [{"id": "1", "function": {"name": "search"}}],
        "tool_loop_count": 5,
    }
    result = _route_after_generate(state)  # type: ignore[arg-type]
    assert result == "reflect"


# ── RAGState TypedDict tests ─────────────────────────────────────────────────


def test_rag_state_has_required_fields():
    assert "query" in RAGState.__annotations__
    assert "version" in RAGState.__annotations__
    assert "rewritten_query" in RAGState.__annotations__
    assert "rewrite_count" in RAGState.__annotations__
    assert "retrieved_chunks" in RAGState.__annotations__
    assert "reranked_chunks" in RAGState.__annotations__
    assert "graph_context" in RAGState.__annotations__
    assert "context" in RAGState.__annotations__
    assert "answer" in RAGState.__annotations__
    assert "tool_calls" in RAGState.__annotations__
    assert "tool_loop_count" in RAGState.__annotations__


def test_rag_state_tool_related_fields():
    """Verify tool-calling fields are present for agentic tools expansion."""
    assert "tool_calls" in RAGState.__annotations__
    assert "tool_results" in RAGState.__annotations__
    assert "tools_enabled" in RAGState.__annotations__


# ── check_confidence with hallucination disabled ─────────────────────────────


def test_check_confidence_hallucination_disabled():
    with patch("proxy.app.shared.config.HALLUCINATION_CHECK_ENABLED", False):
        from proxy.app.core.orchestrator import check_confidence

        state = {
            "query": "Test",
            "context": "Context",
            "answer": "Answer text.",
            "rewrite_count": 0,
        }
        result = check_confidence(state)
        assert result["confidence"] == 0.7
        assert result["needs_escalation"] is False
        assert result["needs_self_critique"] is False
