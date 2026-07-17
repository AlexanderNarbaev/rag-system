# ruff: noqa: SIM117, E402
"""Tests for proxy/app/core/progressive_retrieval.py — FR-25 Progressive Retrieval."""

import sys
from unittest.mock import MagicMock, patch

import pytest

for _mod in ("qdrant_client", "qdrant_client.http", "sentence_transformers", "neo4j"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from proxy.app.core.progressive_retrieval import (
    _dedup_new_only,
    _get_id,
    progressive_retrieve,
    quality_sufficient,
)


def _make_scored_point(id_, score):
    """Helper to create a mock ScoredPoint-like object."""
    mock = MagicMock()
    mock.id = id_
    mock.score = score
    return mock


class TestQualitySufficient:
    """Tests for quality_sufficient() function."""

    def test_empty_results(self):
        assert not quality_sufficient([])

    def test_insufficient_single_weak(self):
        results = [_make_scored_point("a", 0.1)]
        assert not quality_sufficient(results)

    def test_insufficient_two_weak(self):
        results = [_make_scored_point("a", 0.1), _make_scored_point("b", 0.2)]
        assert not quality_sufficient(results)

    def test_sufficient_two_strong(self):
        results = [_make_scored_point("a", 0.32), _make_scored_point("b", 0.35)]
        assert quality_sufficient(results)

    def test_sufficient_two_strong_plus_weak(self):
        results = [
            _make_scored_point("a", 0.5),
            _make_scored_point("b", 0.4),
            _make_scored_point("c", 0.1),
        ]
        assert quality_sufficient(results)

    def test_insufficient_single_strong(self):
        results = [_make_scored_point("a", 0.5), _make_scored_point("b", 0.1)]
        assert not quality_sufficient(results)

    def test_dict_results(self):
        results = [{"id": "a", "score": 0.5}, {"id": "b", "score": 0.4}]
        assert quality_sufficient(results)

    def test_dict_results_insufficient(self):
        results = [{"id": "a", "score": 0.1}]
        assert not quality_sufficient(results)

    def test_mixed_results_dict_and_object(self):
        obj = _make_scored_point("a", 0.5)
        d = {"id": "b", "score": 0.4}
        assert quality_sufficient([obj, d])

    def test_result_without_score(self):
        mock = MagicMock()
        mock.id = "a"
        del mock.score
        assert not quality_sufficient([mock])


class TestGetId:
    """Tests for _get_id() helper."""

    def test_from_scored_point(self):
        sp = _make_scored_point("abc123", 0.5)
        assert _get_id(sp) == "abc123"

    def test_from_dict(self):
        d = {"id": "xyz", "score": 0.5}
        assert _get_id(d) == "xyz"

    def test_from_dict_chunk_id(self):
        d = {"chunk_id": "chk1", "score": 0.5}
        assert _get_id(d) == "chk1"

    def test_fallback(self):
        d = {"score": 0.5}
        result = _get_id(d)
        assert isinstance(result, str)


class TestDedupNewOnly:
    """Tests for _dedup_new_only() helper."""

    def test_no_existing_ids(self):
        existing: set[str] = set()
        results = [
            _make_scored_point("a", 0.5),
            _make_scored_point("b", 0.4),
        ]
        new = _dedup_new_only(existing, results)
        assert len(new) == 2
        assert existing == {"a", "b"}

    def test_partial_overlap(self):
        existing: set[str] = {"a", "c"}
        results = [
            _make_scored_point("a", 0.5),
            _make_scored_point("b", 0.4),
            _make_scored_point("c", 0.3),
            _make_scored_point("d", 0.2),
        ]
        new = _dedup_new_only(existing, results)
        assert len(new) == 2
        assert {r.id for r in new} == {"b", "d"}
        assert existing == {"a", "b", "c", "d"}

    def test_all_existing(self):
        existing: set[str] = {"a", "b"}
        results = [
            _make_scored_point("a", 0.5),
            _make_scored_point("b", 0.4),
        ]
        new = _dedup_new_only(existing, results)
        assert len(new) == 0

    def test_empty_results(self):
        existing: set[str] = set()
        new = _dedup_new_only(existing, [])
        assert len(new) == 0


class TestProgressiveRetrieve:
    """Tests for progressive_retrieve() — the main function."""

    @pytest.fixture(autouse=True)
    def _mock_deps(self):
        with patch(
            "proxy.app.core.progressive_retrieval.hybrid_search",
            new_callable=MagicMock,
        ) as self.mock_search, patch(
            "proxy.app.core.progressive_retrieval.graph_expand_query",
            new_callable=MagicMock,
        ) as self.mock_graph:
            yield

    @pytest.mark.asyncio
    async def test_direct_stage_sufficient(self):
        results_5 = [
            _make_scored_point("a", 0.5),
            _make_scored_point("b", 0.4),
        ]
        self.mock_search.return_value = results_5

        final, stage = await progressive_retrieve("test query")

        assert stage == "direct"
        assert len(final) == 2
        self.mock_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_expanded_stage_sufficient(self):
        results_5 = [
            _make_scored_point("a", 0.5),
        ]
        results_10 = [
            _make_scored_point("a", 0.5),
            _make_scored_point("b", 0.4),
            _make_scored_point("c", 0.3),
        ]
        self.mock_search.side_effect = [results_5, results_10]

        final, stage = await progressive_retrieve("test query")

        assert stage == "expanded"
        assert len(final) == 3
        assert self.mock_search.call_count == 2

    @pytest.mark.asyncio
    async def test_graph_expanded_stage_sufficient(self):
        results_5 = [_make_scored_point("a", 0.5)]
        results_10 = [_make_scored_point("a", 0.5)]
        results_20 = [
            _make_scored_point("a", 0.5),
            _make_scored_point("d", 0.4),
            _make_scored_point("e", 0.3),
        ]
        self.mock_search.side_effect = [results_5, results_10, results_20]
        self.mock_graph.return_value = "Related entities from graph"

        final, stage = await progressive_retrieve("test query")

        assert stage == "graph_expanded"
        assert len(final) == 3
        assert self.mock_search.call_count == 3
        self.mock_graph.assert_called_once_with("test query")

    @pytest.mark.asyncio
    async def test_insufficient_all_stages(self):
        results_5 = [_make_scored_point("a", 0.1)]
        results_10 = [_make_scored_point("a", 0.1), _make_scored_point("b", 0.2)]
        results_20 = [_make_scored_point("a", 0.1), _make_scored_point("c", 0.15)]
        self.mock_search.side_effect = [results_5, results_10, results_20]
        self.mock_graph.return_value = ""

        final, stage = await progressive_retrieve("test query")

        assert stage == "insufficient"
        assert self.mock_search.call_count == 3

    @pytest.mark.asyncio
    async def test_insufficient_with_graph_context(self):
        results_5 = [_make_scored_point("a", 0.1)]
        results_10 = [_make_scored_point("b", 0.2)]
        results_20 = [_make_scored_point("c", 0.15)]
        self.mock_search.side_effect = [results_5, results_10, results_20]
        self.mock_graph.return_value = "Some graph context"

        final, stage = await progressive_retrieve("test query")

        assert stage == "insufficient"
        assert self.mock_search.call_count == 3
        self.mock_graph.assert_called_once_with("test query")

    @pytest.mark.asyncio
    async def test_no_duplicates_across_stages(self):
        results_5 = [_make_scored_point("a", 0.1), _make_scored_point("b", 0.2)]
        self.mock_search.side_effect = [
            results_5,
            [_make_scored_point("a", 0.1), _make_scored_point("b", 0.2),
             _make_scored_point("c", 0.35), _make_scored_point("d", 0.4)],
        ]

        final, stage = await progressive_retrieve("test query")

        assert stage == "expanded"
        ids = {r.id for r in final}
        assert ids == {"a", "b", "c", "d"}
        assert len(final) == 4

    @pytest.mark.asyncio
    async def test_custom_stages(self):
        results_3 = [
            _make_scored_point("a", 0.5),
            _make_scored_point("b", 0.4),
        ]
        self.mock_search.return_value = results_3

        final, stage = await progressive_retrieve("test query", stages=[3, 7, 15])

        assert stage == "direct"
        assert self.mock_search.call_count == 1
        call_kwargs = self.mock_search.call_args[1]
        assert call_kwargs["top_k"] == 3

    @pytest.mark.asyncio
    async def test_passes_version_and_filter(self):
        results = [
            _make_scored_point("a", 0.5),
            _make_scored_point("b", 0.4),
        ]
        self.mock_search.return_value = results

        await progressive_retrieve(
            "test query",
            version="v2.0",
            access_filter=[{"key": "namespace", "match": {"value": "tenant1"}}],
            namespace="tenant1",
            lang="en",
        )

        call_kwargs = self.mock_search.call_args[1]
        assert call_kwargs["version"] == "v2.0"
        assert call_kwargs["access_filter"] == [{"key": "namespace", "match": {"value": "tenant1"}}]
        assert call_kwargs["namespace"] == "tenant1"
        assert call_kwargs["lang"] == "en"

    @pytest.mark.asyncio
    async def test_two_stage_config(self):
        results_5 = [_make_scored_point("a", 0.1)]
        results_10 = [_make_scored_point("a", 0.1), _make_scored_point("b", 0.2)]
        self.mock_search.side_effect = [results_5, results_10]

        final, stage = await progressive_retrieve("test", stages=[5, 10])

        assert stage == "insufficient"
        assert self.mock_search.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_results_all_stages(self):
        self.mock_search.return_value = []

        final, stage = await progressive_retrieve("test query")

        assert stage == "insufficient"
        assert len(final) == 0
        assert self.mock_search.call_count == 3
