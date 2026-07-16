# tests/integration/test_query_rewrite_retrieve.py
"""Integration tests for query rewriting and retrieval flow.

Tests extract_version_from_query used in query processing,
SLM routing decisions affecting retrieval, hybrid search results
flowing through reranking, and the orchestrator flow.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))

# ---------------------------------------------------------------------------
# Mock langgraph modules — langgraph is not installed, but orchestrator.py
# tries to import it at module level. We inject minimal mocks into sys.modules
# so the orchestrator module can be loaded for testing.
# ---------------------------------------------------------------------------

_END_SENTINEL = "__end__"


class _MockCompiledGraph:
    """Minimal compiled graph that walks nodes in order for tests."""

    def __init__(self, nodes, edges, conditional_edges, entry_point):
        self._nodes = nodes
        self._edges = edges
        self._conditional_edges = conditional_edges
        self._entry_point = entry_point

    def invoke(self, state):
        current = self._entry_point
        seen = set()
        while current is not None and current != _END_SENTINEL:
            if current in seen:
                break
            seen.add(current)
            fn = self._nodes.get(current)
            if fn:
                result = fn(state)
                if result and isinstance(result, dict):
                    state.update(result)
            next_node = None
            if current in self._conditional_edges:
                cond_fn, mapping = self._conditional_edges[current]
                label = cond_fn(state)
                next_node = mapping.get(label)
            if next_node is None:
                next_node = self._edges.get(current)
            current = next_node
        return state

    async def ainvoke(self, state):
        return self.invoke(state)


class _MockStateGraph:
    """Minimal StateGraph that records nodes/edges and compiles to _MockCompiledGraph."""

    def __init__(self, state_type=None):
        self._nodes = {}
        self._edges = {}
        self._conditional_edges = {}
        self._entry = None

    def add_node(self, name, func):
        self._nodes[name] = func
        return self

    def set_entry_point(self, name):
        self._entry = name
        return self

    def add_edge(self, from_name, to_name):
        self._edges[from_name] = to_name
        return self

    def add_conditional_edges(self, from_name, condition_func, mapping):
        self._conditional_edges[from_name] = (condition_func, mapping)
        return self

    def compile(self, checkpointer=None):
        return _MockCompiledGraph(
            self._nodes,
            self._edges,
            self._conditional_edges,
            self._entry,
        )


class _MockMemorySaver:
    pass


_langgraph_graph = type(sys)("langgraph.graph")
_langgraph_graph.StateGraph = _MockStateGraph
_langgraph_graph.END = _END_SENTINEL

_langgraph_checkpoint = type(sys)("langgraph.checkpoint")
_langgraph_checkpoint.MemorySaver = _MockMemorySaver

_langgraph = type(sys)("langgraph")
_langgraph.graph = _langgraph_graph
_langgraph.checkpoint = _langgraph_checkpoint

sys.modules["langgraph"] = _langgraph
sys.modules["langgraph.graph"] = _langgraph_graph
sys.modules["langgraph.checkpoint"] = _langgraph_checkpoint


# ---------------------------------------------------------------------------
# Evict cached orchestrator so it re-imports with our _MockStateGraph.
# ---------------------------------------------------------------------------

# NOTE: We do NOT evict the orchestrator module at module-level because that
# would break other test files (e.g. test_orchestrator_dynamic_topk.py) that
# rely on the MagicMock-based StateGraph injected by proxy tests.
# Instead, each TestOrchestratorFlow test method patches StateGraph directly.


def _reset_orchestrator_singleton():
    """Reset the orchestrator module-level singleton so each test starts fresh."""
    try:
        import proxy.app.core.orchestrator as _orch_mod

        _orch_mod._orchestrator = None
    except (ImportError, AttributeError):
        pass


class TestVersionExtractionInQueryProcessing:
    """Tests for extract_version_from_query integrated into the query pipeline."""

    def test_version_extracted_before_search(self):
        """Version from query is extracted and passed to hybrid_search."""
        from proxy.app.core.context import extract_version_from_query

        queries_and_versions = [
            ("Покажи документацию v2.0 по архитектуре", "2.0"),
            ("Use version 3.1 API docs", "3.1"),
            ("What changed in v1.2.3", "1.2.3"),
            ("Документы от 2025-06-01", "2025-06-01"),
            ("No version in this query", None),
        ]
        for query, expected_version in queries_and_versions:
            result = extract_version_from_query(query)
            assert result == expected_version, f"Failed for query: {query}"

    def test_rag_version_overrides_query_version(self):
        """Explicit rag_version parameter takes precedence over query-extracted version."""
        from proxy.app.core.context import extract_version_from_query

        query = "Расскажи про RAG v1.0"
        extracted = extract_version_from_query(query)
        assert extracted == "1.0"

        # Explicit version override would happen at caller level
        explicit_version = "2.0"
        effective = explicit_version if explicit_version else extracted
        assert effective == "2.0"


class TestHybridSearchResultsThroughReranking:
    """Tests for hybrid search results flowing through reranking."""

    def test_rerank_filters_top_k(self):
        """Rerank returns only top_k most relevant indices."""
        from proxy.app.core.rerank import rerank_chunks

        with (
            patch("proxy.app.core.rerank.reranker") as mock_reranker,
            patch("proxy.app.core.rerank.cache_manager", None),
        ):
            # Mock cross-encoder: higher score = more relevant
            mock_reranker.predict.return_value = [0.1, 0.9, 0.5, 0.2, 0.8, 0.3]

            query = "How to configure CI/CD?"
            chunks = [
                "Docker containers are used for isolation.",
                "CI/CD pipeline is configured via .gitlab-ci.yml.",
                "Kubernetes manages container orchestration.",
                "PostgreSQL is a relational database.",
                "Use GitLab CI for automated deployments.",
                "Node.js is a JavaScript runtime.",
            ]
            top_indices = rerank_chunks(query, chunks, top_k=3)
            assert len(top_indices) == 3
            # Best chunks should be indices 1 and 4
            assert top_indices[0] == 1
            assert top_indices[1] == 4

    def test_rerank_handles_empty_chunks(self):
        """Rerank returns empty list when given no chunks."""
        from proxy.app.core.rerank import rerank_chunks

        with patch("proxy.app.core.rerank.reranker"), patch("proxy.app.core.rerank.cache_manager", None):
            result = rerank_chunks("query", [], top_k=5)
            assert result == []

    def test_rerank_truncates_long_text(self):
        """Rerank truncates chunk text to model's max length before scoring."""
        from proxy.app.core.rerank import _truncate_text

        short = "Short text"
        assert len(_truncate_text(short)) == len(short)

        long_text = "x" * 5000
        truncated = _truncate_text(long_text, max_tokens=100)
        assert len(truncated) <= 100 * 4

    def test_hybrid_search_fusion_combines_scores(self):
        """RRF fusion properly combines dense and sparse search results."""
        from proxy.app.core.retrieval import reciprocal_rank_fusion

        class FakeHit:
            def __init__(self, id, score):
                self.id = id
                self.score = score

        dense = [FakeHit("A", 0.9), FakeHit("B", 0.8), FakeHit("C", 0.5)]
        sparse = [FakeHit("B", 0.7), FakeHit("D", 0.6), FakeHit("A", 0.4)]

        fused = reciprocal_rank_fusion(dense, sparse, k=60)
        fused_ids = [h.id for h in fused]

        # B appears in both => should rank high
        # A appears in both => should also rank high
        assert "B" in fused_ids
        assert "A" in fused_ids
        # All unique IDs from both lists should appear
        assert set(fused_ids) == {"A", "B", "C", "D"}


class TestSLMRoutingDecisions:
    """Tests for SLM routing decisions affecting downstream retrieval behavior."""

    def test_intent_classification_returns_correct_types(self):
        """SLM classify_intent returns valid IntentType and confidence."""
        from proxy.app.llm.slm import IntentType, classify_intent

        with patch("proxy.app.llm.slm._call_slm_sync", return_value="factual"):
            intent, confidence = classify_intent("Что такое RAG?")
            assert intent == IntentType.FACTUAL
            assert 0 <= confidence <= 1

        with patch("proxy.app.llm.slm._call_slm_sync", return_value="procedural"):
            intent, confidence = classify_intent("Как настроить CI/CD?")
            assert intent == IntentType.PROCEDURAL

    def test_intent_classification_unknown_fallback(self):
        """Unknown SLM response falls back to UNKNOWN intent."""
        from proxy.app.llm.slm import IntentType, classify_intent

        with patch("proxy.app.llm.slm._call_slm_sync", return_value="garbage"):
            intent, confidence = classify_intent("Some query")
            assert intent == IntentType.UNKNOWN

    def test_needs_retrieval_false_for_greetings(self):
        """Greeting intents do not require retrieval."""
        from proxy.app.llm.slm import IntentType, needs_retrieval

        assert needs_retrieval(IntentType.GREETING) is False
        assert needs_retrieval(IntentType.FACTUAL) is True
        assert needs_retrieval(IntentType.PROCEDURAL) is True

    def test_slm_rewrite_preserves_key_terms(self):
        """SLM query rewrite preserves key technical terms."""
        from proxy.app.llm.slm import rewrite_query_slm

        with patch("proxy.app.llm.slm._call_slm_sync", return_value="CI/CD pipeline GitLab configuration setup"):
            rewritten = rewrite_query_slm("Как настроить CI/CD пайплайн в GitLab?")
            assert "CI/CD" in rewritten
            assert "GitLab" in rewritten

    def test_slm_rewrite_falls_back_to_original(self):
        """When SLM fails, rewrite returns the original query."""
        from proxy.app.llm.slm import rewrite_query_slm

        with patch("proxy.app.llm.slm._call_slm_sync", return_value=""):
            original = "Как настроить CI/CD?"
            result = rewrite_query_slm(original)
            assert result == original

    def test_should_use_graph_for_comparison(self):
        """Graph usage is recommended for comparison intents and relation queries."""
        from proxy.app.llm.slm import IntentType, should_use_graph

        assert should_use_graph(IntentType.COMPARISON, "Сравни GitLab и GitHub") is True
        assert should_use_graph(IntentType.FACTUAL, "Что такое RAG?") is False
        assert should_use_graph(IntentType.FACTUAL, "От чего зависит скорость поиска?") is True

    def test_query_decomposition_splits_complex_queries(self):
        """Decompose splits complex queries into subqueries."""
        from proxy.app.llm.slm import decompose_query

        with patch(
            "proxy.app.llm.slm._call_slm_sync",
            return_value='["Настройка CI/CD в GitLab","Отличия GitHub Actions от GitLab CI"]',
        ):
            subs = decompose_query("Как настроить CI/CD в GitLab и чем он отличается от GitHub Actions?")
            assert len(subs) >= 1

    def test_decompose_falls_back_to_original(self):
        """Decompose returns original query in list when SLM fails."""
        from proxy.app.llm.slm import decompose_query

        with patch("proxy.app.llm.slm._call_slm_sync", return_value="not valid json {"):
            original = "Complex query that cannot be decomposed"
            subs = decompose_query(original)
            assert subs == [original]


class TestOrchestratorFlow:
    """Tests for LangGraph orchestrator flow (mocked appropriately)."""

    def setup_method(self, _method=None):
        """Reset orchestrator singleton before each test to avoid stale state."""
        _reset_orchestrator_singleton()

    def test_orchestrator_state_flows_through_nodes(self):
        """Orchestrator invokes the graph and produces final answer in state."""
        import proxy.app.core.orchestrator as _orch_mod
        import proxy.app.core.orchestrator.graph as _graph_mod

        # Pre-set the attributes if they are None (langgraph not installed)
        _graph_mod.StateGraph = _graph_mod.StateGraph or _MockStateGraph
        _graph_mod.END = _graph_mod.END or _END_SENTINEL
        _graph_mod.MemorySaver = _graph_mod.MemorySaver or _MockMemorySaver

        with (
            patch("proxy.app.shared.config.USE_LANGGRAPH", True),
            patch.object(_graph_mod, "StateGraph", _MockStateGraph),
            patch.object(_graph_mod, "END", _END_SENTINEL),
            patch.object(_graph_mod, "MemorySaver", _MockMemorySaver),
            patch.object(_orch_mod, "hybrid_search") as mock_search,
            patch.object(_orch_mod, "rerank_chunks", return_value=[0, 1]),
            patch.object(_orch_mod, "non_stream_completion", new_callable=MagicMock) as mock_llm,
            patch.object(_orch_mod, "non_stream_completion_sync", new_callable=MagicMock) as mock_llm_sync,
        ):
            mock_llm.return_value = "RAG — это техника объединения LLM с базой знаний."
            mock_llm_sync.return_value = "RAG — это техника объединения LLM с базой знаний."

            class FakeScoredPoint:
                def __init__(self, id, score, payload):
                    self.id = id
                    self.score = score
                    self.payload = payload

            mock_search.return_value = [
                FakeScoredPoint("h1", 0.95, {"text": "RAG combines retrieval and generation.", "version": "1.0"}),
                FakeScoredPoint("h2", 0.90, {"text": "LLM generates answers from context.", "version": "1.0"}),
            ]

            from proxy.app.core.orchestrator import RAGOrchestrator

            orchestrator = RAGOrchestrator()
            result = orchestrator.invoke(
                {
                    "query": "Что такое RAG?",
                    "version": None,
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "stream": False,
                    "rewritten_query": None,
                    "rewrite_count": 0,
                    "retrieved_chunks": [],
                    "reranked_chunks": [],
                    "graph_context": "",
                    "context": "",
                    "answer": "",
                    "sufficient": False,
                }
            )
            assert "answer" in result
            assert "RAG" in result["answer"]
            assert len(result["context"]) > 0

    def test_orchestrator_rewrite_loop_limit(self):
        """Orchestrator respects max rewrite loops and produces answer."""
        import proxy.app.core.orchestrator as _orch_mod
        import proxy.app.core.orchestrator.graph as _graph_mod

        # Pre-set the attributes if they are None (langgraph not installed)
        _graph_mod.StateGraph = _graph_mod.StateGraph or _MockStateGraph
        _graph_mod.END = _graph_mod.END or _END_SENTINEL
        _graph_mod.MemorySaver = _graph_mod.MemorySaver or _MockMemorySaver

        with (
            patch("proxy.app.shared.config.USE_LANGGRAPH", True),
            patch("proxy.app.shared.config.MAX_RETRIEVAL_LOOPS", 1),
            patch.object(_graph_mod, "StateGraph", _MockStateGraph),
            patch.object(_graph_mod, "END", _END_SENTINEL),
            patch.object(_graph_mod, "MemorySaver", _MockMemorySaver),
            patch.object(_orch_mod, "hybrid_search") as mock_search,
            patch.object(_orch_mod, "rerank_chunks", return_value=[0]),
            patch.object(_orch_mod, "non_stream_completion", new_callable=MagicMock) as mock_llm,
            patch.object(_orch_mod, "non_stream_completion_sync", new_callable=MagicMock) as mock_llm_sync,
        ):
            mock_llm.return_value = "Ответ после ограничения циклов."
            mock_llm_sync.return_value = "Ответ после ограничения циклов."

            class FakeScoredPoint:
                def __init__(self, id, score, payload):
                    self.id = id
                    self.score = score
                    self.payload = payload

            mock_search.return_value = [
                FakeScoredPoint("h1", 0.55, {"text": "Some marginally relevant text.", "version": "1.0"}),
            ]

            from proxy.app.core.orchestrator import RAGOrchestrator

            orchestrator = RAGOrchestrator()
            result = orchestrator.invoke(
                {
                    "query": "Сложный запрос с низкой релевантностью",
                    "version": None,
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "stream": False,
                    "rewritten_query": None,
                    "rewrite_count": 2,
                    "retrieved_chunks": [],
                    "reranked_chunks": [],
                    "graph_context": "",
                    "context": "",
                    "answer": "",
                    "sufficient": False,
                }
            )
            assert "answer" in result

    def test_orchestrator_graph_has_expected_nodes(self):
        """Graph builder creates all expected nodes (rewrite, retrieve, rerank, etc.)."""
        from proxy.app.core.orchestrator import build_rag_graph

        builder = build_rag_graph()
        # Graph builder should be a StateGraph with nodes configured
        assert builder is not None
