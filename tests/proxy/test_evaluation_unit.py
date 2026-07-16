# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/core/evaluation.py — retrieval evaluation metrics."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.core.evaluation import (
    compute_all_metrics,
    compute_mrr,
    compute_ndcg_at_k,
    compute_precision_at_k,
    compute_recall_at_k,
    evaluate_cross_lingual_retrieval,
    load_eval_dataset,
)


class TestComputeMRR:
    """Tests for compute_mrr."""

    def test_empty(self):
        assert compute_mrr([], []) == 0.0

    def test_perfect_ranking(self):
        result = compute_mrr([["a", "b", "c"]], [{"a"}])
        assert result == pytest.approx(1.0)

    def test_second_rank(self):
        result = compute_mrr([["x", "a", "b"]], [{"a"}])
        assert result == pytest.approx(0.5)

    def test_not_found(self):
        result = compute_mrr([["x", "y", "z"]], [{"a"}])
        assert result == pytest.approx(0.0)

    def test_multiple_queries(self):
        lists = [["a", "b"], ["x", "y"]]
        sets = [{"a"}, {"y"}]
        result = compute_mrr(lists, sets)
        assert result == pytest.approx((1.0 + 0.5) / 2)

    def test_empty_relevant_skipped(self):
        result = compute_mrr([["a"]], [set()])
        assert result == 0.0


class TestComputeRecallAtK:
    """Tests for compute_recall_at_k."""

    def test_empty_relevant(self):
        assert compute_recall_at_k(["a"], set(), 5) == 1.0

    def test_perfect(self):
        assert compute_recall_at_k(["a", "b"], {"a", "b"}, 5) == 1.0

    def test_partial(self):
        assert compute_recall_at_k(["a", "x"], {"a", "b"}, 5) == 0.5

    def test_k_limit(self):
        assert compute_recall_at_k(["a", "b", "c"], {"a", "b", "c"}, 2) == pytest.approx(2 / 3)

    def test_no_hits(self):
        assert compute_recall_at_k(["x", "y"], {"a", "b"}, 5) == 0.0


class TestComputeNDCGAtK:
    """Tests for compute_ndcg_at_k."""

    def test_empty_relevant(self):
        assert compute_ndcg_at_k(["a"], set(), 5) == 1.0

    def test_perfect_ranking(self):
        assert compute_ndcg_at_k(["a", "b"], {"a", "b"}, 5) == pytest.approx(1.0)

    def test_worst_ranking(self):
        result = compute_ndcg_at_k(["x", "y", "a"], {"a"}, 3)
        assert result < 1.0
        assert result > 0.0

    def test_zero_idcg(self):
        # No relevant docs -> idcg=0 -> 0.0
        assert compute_ndcg_at_k([], set(), 5) == 1.0  # empty relevant = 1.0


class TestComputePrecisionAtK:
    """Tests for compute_precision_at_k."""

    def test_empty_retrieved(self):
        assert compute_precision_at_k([], {"a"}, 5) == 0.0

    def test_perfect(self):
        assert compute_precision_at_k(["a", "b"], {"a", "b"}, 2) == 1.0

    def test_partial(self):
        assert compute_precision_at_k(["a", "x"], {"a", "b"}, 2) == 0.5

    def test_zero_k(self):
        assert compute_precision_at_k(["a"], {"a"}, 0) == 0.0


class TestComputeAllMetrics:
    """Tests for compute_all_metrics."""

    def test_basic(self):
        lists = [["a", "b", "c"]]
        sets = [{"a", "b"}]
        metrics = compute_all_metrics(lists, sets)
        assert "mrr" in metrics
        assert "recall@5" in metrics
        assert "recall@10" in metrics
        assert "recall@20" in metrics
        assert "ndcg@5" in metrics
        assert "ndcg@10" in metrics
        assert "precision@5" in metrics
        assert "num_queries" in metrics
        assert metrics["num_queries"] == 1.0

    def test_empty(self):
        metrics = compute_all_metrics([], [])
        assert metrics["mrr"] == 0.0
        assert metrics["num_queries"] == 0.0


class TestLoadEvalDataset:
    """Tests for load_eval_dataset."""

    def test_json_array(self, tmp_path):
        data = [
            {"query": "test", "relevant_docs": ["doc1"]},
            {"query": "test2", "relevant_docs": ["doc2"]},
        ]
        path = tmp_path / "eval.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_eval_dataset(str(path))
        assert len(result) == 2

    def test_json_single(self, tmp_path):
        data = {"query": "test", "relevant_docs": ["doc1"]}
        path = tmp_path / "eval.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_eval_dataset(str(path))
        assert len(result) == 1

    def test_jsonl(self, tmp_path):
        lines = [
            json.dumps({"query": "q1", "relevant_docs": ["d1"]}),
            json.dumps({"query": "q2", "relevant_docs": ["d2"]}),
        ]
        path = tmp_path / "eval.jsonl"
        path.write_text("\n".join(lines), encoding="utf-8")
        result = load_eval_dataset(str(path))
        assert len(result) == 2

    def test_jsonl_with_comments(self, tmp_path):
        lines = [
            "# comment",
            "",
            json.dumps({"query": "q1", "relevant_docs": ["d1"]}),
        ]
        path = tmp_path / "eval.jsonl"
        path.write_text("\n".join(lines), encoding="utf-8")
        result = load_eval_dataset(str(path))
        assert len(result) == 1

    def test_missing_file(self):
        result = load_eval_dataset("/nonexistent/path.json")
        assert result == []

    def test_json_with_invalid_records(self, tmp_path):
        data = [
            {"query": "valid", "relevant_docs": ["d1"]},
            {"no_query": "invalid"},  # Missing required keys
        ]
        path = tmp_path / "eval.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = load_eval_dataset(str(path))
        assert len(result) == 1

    def test_jsonl_with_invalid_json(self, tmp_path):
        lines = [
            json.dumps({"query": "q1", "relevant_docs": ["d1"]}),
            "not json at all",
        ]
        path = tmp_path / "eval.jsonl"
        path.write_text("\n".join(lines), encoding="utf-8")
        result = load_eval_dataset(str(path))
        assert len(result) == 1

    def test_empty_json_array(self, tmp_path):
        path = tmp_path / "eval.json"
        path.write_text("[]", encoding="utf-8")
        result = load_eval_dataset(str(path))
        assert result == []


class TestEvaluateCrossLingualRetrieval:
    """Tests for evaluate_cross_lingual_retrieval."""

    def test_retrieval_unavailable(self):
        """Returns fallback metrics when retrieval fails."""
        with patch("proxy.app.core.retrieval.hybrid_search", side_effect=Exception("Qdrant down")):
            result = evaluate_cross_lingual_retrieval(("en", "de"))
            assert result["source_lang"] == "en"
            assert result["target_lang"] == "de"
            assert "monolingual" in result
            assert "cross_lingual" in result

    def test_empty_source_queries(self):
        """Returns empty result when no source queries."""
        result = evaluate_cross_lingual_retrieval(("xx", "yy"), queries={"xx": [], "yy": []})
        assert result["num_queries"] == 0

    def test_with_custom_queries(self):
        """Works with custom query dict."""
        with patch("proxy.app.core.retrieval.hybrid_search", return_value=[]):
            result = evaluate_cross_lingual_retrieval(
                ("en", "de"),
                queries={"en": ["test query"], "de": ["test anfrage"]},
            )
            assert "monolingual" in result
            assert result["num_queries"] >= 0

    def test_default_queries(self):
        """Uses built-in sample queries when queries=None."""
        with patch("proxy.app.core.retrieval.hybrid_search", return_value=[]):
            result = evaluate_cross_lingual_retrieval(("en", "de"))
            assert result["num_queries"] > 0
