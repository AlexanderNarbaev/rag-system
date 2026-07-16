# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for advanced retrieval classes: MultiHopGraphExplorer, CypherQueryGenerator, GlobalSearch, etc."""

from datetime import UTC
from unittest.mock import MagicMock

from proxy.app.core.retrieval import (
    CypherQueryGenerator,
    EmbeddingCache,
    GlobalSearch,
    MultiHopGraphExplorer,
    _parse_timestamp,
    apply_time_decay,
    filter_results_by_score,
    knee_point_pruning,
)


class TestEmbeddingCache:
    """Tests for EmbeddingCache."""

    def test_exact_match(self):
        cache = EmbeddingCache()
        cache.set("test query", [0.1, 0.2, 0.3])
        result = cache.get("test query")
        assert result == [0.1, 0.2, 0.3]

    def test_case_insensitive_exact_match(self):
        cache = EmbeddingCache()
        cache.set("Test Query", [0.1, 0.2])
        assert cache.get("test query") == [0.1, 0.2]

    def test_miss(self):
        cache = EmbeddingCache()
        assert cache.get("no such query") is None

    def test_eviction(self):
        cache = EmbeddingCache(max_size=2)
        cache.set("q1", [1.0])
        cache.set("q2", [2.0])
        cache.set("q3", [3.0])
        # q1 should be evicted
        assert cache.get("q1") is None
        assert cache.get("q3") == [3.0]


class TestParseTimestamp:
    """Tests for _parse_timestamp."""

    def test_none(self):
        assert _parse_timestamp(None) is None

    def test_int(self):
        assert _parse_timestamp(1000) == 1000.0

    def test_float(self):
        assert _parse_timestamp(1000.5) == 1000.5

    def test_iso_format(self):
        ts = _parse_timestamp("2025-01-15T10:00:00Z")
        assert ts is not None
        assert ts > 0

    def test_iso_format_with_offset(self):
        ts = _parse_timestamp("2025-01-15T10:00:00+00:00")
        assert ts is not None

    def test_invalid_string(self):
        assert _parse_timestamp("not-a-date") is None


class TestApplyTimeDecay:
    """Tests for apply_time_decay."""

    def test_empty_chunks(self):
        assert apply_time_decay([]) == []

    def test_no_timestamp(self):
        chunks = [{"id": "1", "score": 0.8, "text": "hello"}]
        result = apply_time_decay(chunks)
        assert len(result) == 1
        assert result[0]["score"] == 0.8

    def test_recent_timestamp_boost(self):
        from datetime import datetime

        recent = datetime.now(UTC).isoformat()
        chunks = [{"id": "1", "score": 0.5, "payload": {"updated_at": recent}}]
        result = apply_time_decay(chunks)
        # Recent documents get higher boost
        assert result[0]["score"] > 0.5
        assert "time_boost" in result[0]

    def test_old_timestamp_decay(self):
        chunks = [{"id": "1", "score": 0.5, "payload": {"created_at": "2020-01-01T00:00:00Z"}}]
        result = apply_time_decay(chunks)
        # Old documents get lower boost
        assert result[0]["time_boost"] < 0.5


class TestFilterResultsByScore:
    """Tests for filter_results_by_score."""

    def test_empty(self):
        results, quality = filter_results_by_score([])
        assert results == []
        assert quality == "insufficient"

    def test_strong_results(self):
        r1 = MagicMock(score=0.5)
        r2 = MagicMock(score=0.4)
        r3 = MagicMock(score=0.35)
        results, quality = filter_results_by_score([r1, r2, r3])
        assert quality == "strong"
        assert len(results) >= 2

    def test_borderline_only(self):
        r1 = MagicMock(score=0.28)
        r2 = MagicMock(score=0.26)
        results, quality = filter_results_by_score([r1, r2])
        assert quality == "borderline"

    def test_insufficient(self):
        r1 = MagicMock(score=0.1)
        results, quality = filter_results_by_score([r1])
        assert quality == "insufficient"


class TestKneePointPruning:
    """Tests for knee_point_pruning."""

    def test_few_results_returned_as_is(self):
        r1 = MagicMock(score=0.9)
        r2 = MagicMock(score=0.5)
        result = knee_point_pruning([r1, r2])
        assert len(result) == 2

    def test_prunes_at_knee(self):
        results = [MagicMock(score=s) for s in [0.9, 0.85, 0.8, 0.3, 0.2, 0.1]]
        pruned = knee_point_pruning(results, sensitivity=0.5)
        assert len(pruned) <= len(results)
        assert len(pruned) >= 2

    def test_flat_scores(self):
        """When all scores are the same, returns a subset."""
        results = [MagicMock(score=0.5) for _ in range(10)]
        pruned = knee_point_pruning(results, sensitivity=0.5)
        assert len(pruned) >= 2


class TestMultiHopGraphExplorer:
    """Tests for MultiHopGraphExplorer."""

    def test_empty_inputs(self):
        explorer = MultiHopGraphExplorer()
        assert explorer.explore([], {}) == []

    def test_single_hop(self):
        explorer = MultiHopGraphExplorer(max_hops=1)
        entity_map = {"A": ["B", "C"], "B": ["D"]}
        paths = explorer.explore(["A"], entity_map)
        assert len(paths) > 0
        assert all("path" in p for p in paths)

    def test_cycle_detection(self):
        """Cycle detection prevents infinite loops in cyclic graphs."""
        explorer = MultiHopGraphExplorer(max_hops=3, cycle_detection=True)
        entity_map = {"A": ["B"], "B": ["C"], "C": ["A"]}
        paths = explorer.explore(["A"], entity_map)
        # Should produce finite paths without infinite looping
        assert isinstance(paths, list)
        # Each path should have at most max_hops + 1 entities
        for p in paths:
            assert len(p["path"]) <= explorer.max_hops + 1

    def test_no_cycle_detection(self):
        explorer = MultiHopGraphExplorer(max_hops=2, cycle_detection=False)
        entity_map = {"A": ["B"], "B": ["C"]}
        paths = explorer.explore(["A"], entity_map)
        assert len(paths) > 0

    def test_format_context(self):
        explorer = MultiHopGraphExplorer()
        paths = [
            {"path": ["A", "B", "C"], "score": 0.8, "hops": 2},
            {"path": ["X", "Y"], "score": 0.6, "hops": 1},
        ]
        context = explorer.format_context(paths)
        assert "A → B → C" in context
        assert "X → Y" in context

    def test_format_context_empty(self):
        explorer = MultiHopGraphExplorer()
        assert explorer.format_context([]) == ""

    def test_score_path(self):
        explorer = MultiHopGraphExplorer()
        entity_map = {"A": ["B", "C", "D"], "B": ["E"]}
        score = explorer._score_path(["A", "B"], entity_map)
        assert 0 < score <= 1

    def test_score_path_empty(self):
        explorer = MultiHopGraphExplorer()
        assert explorer._score_path([], {}) == 0.0

    def test_leaf_node_path(self):
        """Leaf nodes (no neighbors) still produce a path."""
        explorer = MultiHopGraphExplorer(max_hops=2)
        entity_map = {"A": ["B"], "B": []}
        paths = explorer.explore(["A"], entity_map)
        assert len(paths) >= 1


class TestCypherQueryGenerator:
    """Tests for CypherQueryGenerator."""

    def test_project_pattern(self):
        gen = CypherQueryGenerator()
        cypher = gen.generate("what projects does John work on")
        assert cypher is not None
        assert "John" in cypher

    def test_who_works_on_pattern(self):
        gen = CypherQueryGenerator()
        cypher = gen.generate("who worked on ProjectX")
        assert cypher is not None
        assert "Project" in cypher  # capitalize() normalizes

    def test_issues_pattern(self):
        gen = CypherQueryGenerator()
        cypher = gen.generate("what issues are linked to RAG")
        assert cypher is not None
        assert "Issue" in cypher

    def test_dependencies_pattern(self):
        gen = CypherQueryGenerator()
        cypher = gen.generate("what dependencies does SystemA have")
        assert cypher is not None
        assert "DEPENDS_ON" in cypher

    def test_fallback_entity_search(self):
        gen = CypherQueryGenerator()
        cypher = gen.generate("tell me about Kubernetes")
        assert cypher is not None
        assert "Kubernetes" in cypher

    def test_no_match(self):
        gen = CypherQueryGenerator()
        cypher = gen.generate("hi")
        # May return None or fallback depending on entity extraction
        # "hi" is a stop word, so should return None
        assert cypher is None

    def test_extract_entities(self):
        gen = CypherQueryGenerator()
        entities = gen._extract_entities("Kubernetes and Docker are tools")
        assert "Kubernetes" in entities
        assert "Docker" in entities


class TestGlobalSearch:
    """Tests for GlobalSearch."""

    def test_empty_summaries(self):
        gs = GlobalSearch()
        assert gs.search("test query") == []

    def test_keyword_overlap(self):
        summaries = [
            {"id": "c1", "summary": "Python programming language tutorial", "key_entities": ["Python"], "members": []},
            {"id": "c2", "summary": "JavaScript web development guide", "key_entities": ["JS"], "members": []},
        ]
        gs = GlobalSearch(summaries)
        results = gs.search("Python tutorial")
        assert len(results) >= 1
        assert results[0]["community_id"] == "c1"

    def test_format_context(self):
        gs = GlobalSearch()
        results = [
            {"summary": "About AI", "key_entities": ["ML", "DL"], "score": 0.9},
        ]
        ctx = gs.format_context(results)
        assert "About AI" in ctx
        assert "ML" in ctx

    def test_format_context_empty(self):
        gs = GlobalSearch()
        assert gs.format_context([]) == ""

    def test_top_k_limiting(self):
        summaries = [
            {"id": f"c{i}", "summary": f"Summary {i} about python", "key_entities": [], "members": []}
            for i in range(20)
        ]
        gs = GlobalSearch(summaries)
        results = gs.search("python", top_k=3)
        assert len(results) <= 3
