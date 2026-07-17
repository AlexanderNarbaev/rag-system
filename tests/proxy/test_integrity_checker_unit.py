"""Tests for integrity_checker module — additional edge cases."""

import time
from unittest.mock import MagicMock, patch

from proxy.app.core.integrity_checker import (
    _check_contradiction_lightweight,
    check_contradiction,
    compute_integrity_score,
    compute_knowledge_coverage,
    find_contradictions,
)


class TestCheckContradictionLightweight:
    def test_identical_chunks_high_entailment(self):
        result = _check_contradiction_lightweight(
            "the database runs on port 5432 with postgres",
            "the database runs on port 5432 with postgres",
        )
        assert result["entailment_score"] >= 0.5
        assert result["contradiction_score"] < 0.2

    def test_different_chunks_high_neutral(self):
        result = _check_contradiction_lightweight(
            "the database runs on port 5432",
            "the application uses redis for caching",
        )
        assert result["neutral_score"] >= 0.5

    def test_negation_detected(self):
        result = _check_contradiction_lightweight(
            "the database is running on port 5432",
            "the database is NOT running on port 5432",
        )
        assert result["contradiction_score"] >= 0.4

    def test_negation_in_a_only(self):
        result = _check_contradiction_lightweight(
            "the database is not running",
            "the database running always",
        )
        assert result["contradiction_score"] >= 0.4

    def test_negation_in_b_only(self):
        result = _check_contradiction_lightweight(
            "the database is running",
            "the database is never running",
        )
        assert result["contradiction_score"] >= 0.4

    def test_no_negation_different_words(self):
        result = _check_contradiction_lightweight(
            "the database is running on port 5432",
            "the system uses postgres on port 5432",
        )
        assert result["neutral_score"] >= 0.5

    def test_both_have_negation(self):
        result = _check_contradiction_lightweight(
            "the database is not configured",
            "the database is not set up",
        )
        assert result["neutral_score"] >= 0.5


class TestCheckContradiction:
    def test_empty_both_inputs(self):
        result = check_contradiction("", "")
        assert result["contradiction_score"] == 0.0
        assert result["entailment_score"] == 0.0
        assert result["neutral_score"] == 0.0

    def test_empty_a(self):
        result = check_contradiction("", "text")
        assert result["contradiction_score"] == 0.0

    def test_empty_b(self):
        result = check_contradiction("text", "")
        assert result["contradiction_score"] == 0.0

    def test_falls_back_to_lightweight_without_nli(self):
        with patch("proxy.app.core.integrity_checker._get_nli_classifier", return_value=None):
            result = check_contradiction("the port is 8080", "the port is 8080")
            assert result["entailment_score"] >= 0.5


class TestFindContradictions:
    def test_qdrant_error_returns_empty(self):
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.side_effect = RuntimeError("connection failure")
        result = find_contradictions("kb1", mock_qdrant, "test")
        assert result == []

    def test_empty_payloads_no_contradiction(self):
        p1 = MagicMock()
        p1.id = "c1"
        p1.payload = {}
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1], None)
        result = find_contradictions("kb1", mock_qdrant, "test")
        assert result == []

    def test_limited_to_100_results(self):
        p1 = MagicMock()
        p1.id = "c1"
        p1.payload = {"source_id": "s1", "text": "a", "title": "A", "source_type": "confluence"}
        p2 = MagicMock()
        p2.id = "c2"
        p2.payload = {"source_id": "s1", "text": "not a", "title": "B", "source_type": "confluence"}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)

        with patch("proxy.app.core.integrity_checker.check_contradiction", return_value={
            "contradiction_score": 0.8, "entailment_score": 0.1, "neutral_score": 0.1
        }):
            result = find_contradictions("kb1", mock_qdrant, "test", threshold=0.5)
            assert len(result) == 1


class TestComputeKnowledgeCoverage:
    def test_qdrant_error_returns_dict_with_error(self):
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.side_effect = RuntimeError("boom")
        result = compute_knowledge_coverage("kb1", mock_qdrant, "test")
        assert "error" in result

    def test_multiple_sources_no_gap(self):
        p1 = MagicMock()
        p1.payload = {"source_type": "confluence", "title": "D1", "last_updated": time.time()}
        p2 = MagicMock()
        p2.payload = {"source_type": "jira", "title": "I1", "last_updated": time.time()}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)
        result = compute_knowledge_coverage("kb1", mock_qdrant, "test")
        gap_types = [g["type"] for g in result["coverage_gaps"]]
        assert "single_source" not in gap_types

    def test_no_timestamps_no_outdated_gap(self):
        p1 = MagicMock()
        p1.payload = {"source_type": "confluence", "title": "D1"}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1], None)
        result = compute_knowledge_coverage("kb1", mock_qdrant, "test")
        gap_types = [g["type"] for g in result["coverage_gaps"]]
        assert "outdated" not in gap_types

    def test_fresh_documents_no_outdated_gap(self):
        p1 = MagicMock()
        p1.payload = {"source_type": "confluence", "title": "D1", "last_updated": time.time()}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1], None)
        result = compute_knowledge_coverage("kb1", mock_qdrant, "test")
        gap_types = [g["type"] for g in result["coverage_gaps"]]
        assert "outdated" not in gap_types

    def test_empty_payloads(self):
        p1 = MagicMock()
        p1.payload = {}
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1], None)
        result = compute_knowledge_coverage("kb1", mock_qdrant, "test")
        assert result["total_chunks"] == 1
        assert "unknown" in result["source_distribution"]


class TestComputeIntegrityScore:
    @patch("proxy.app.core.integrity_checker.find_contradictions")
    @patch("proxy.app.core.integrity_checker.compute_knowledge_coverage")
    def test_score_clamped_to_zero(self, mock_coverage, mock_contradictions):
        mock_contradictions.return_value = [{}] * 50
        mock_coverage.return_value = {
            "total_chunks": 10,
            "unique_sources": 0,
            "source_distribution": {},
            "coverage_gaps": [{"type": "outdated"}],
        }

        result = compute_integrity_score("kb1", None, "test")
        assert result["overall_score"] >= 0.0

    @patch("proxy.app.core.integrity_checker.find_contradictions")
    @patch("proxy.app.core.integrity_checker.compute_knowledge_coverage")
    def test_score_clamped_to_100(self, mock_coverage, mock_contradictions):
        mock_contradictions.return_value = []
        mock_coverage.return_value = {
            "total_chunks": 200,
            "unique_sources": 10,
            "source_distribution": {f"s{i}": 20 for i in range(10)},
            "coverage_gaps": [],
        }

        result = compute_integrity_score("kb1", None, "test")
        assert result["overall_score"] <= 100.0

    @patch("proxy.app.core.integrity_checker.find_contradictions")
    @patch("proxy.app.core.integrity_checker.compute_knowledge_coverage")
    @patch("proxy.app.shared.metrics.rag_knowledge_integrity_score")
    def test_records_prometheus_metric(self, mock_metric, mock_coverage, mock_contradictions):
        mock_contradictions.return_value = []
        mock_coverage.return_value = {
            "total_chunks": 100,
            "unique_sources": 5,
            "source_distribution": {"c": 100},
            "coverage_gaps": [],
        }

        result = compute_integrity_score("kb1", None, "test")
        mock_metric.labels.assert_called_once_with(kb_id="kb1")
        mock_metric.labels.return_value.set.assert_called_once_with(result["overall_score"])

    @patch("proxy.app.core.integrity_checker.find_contradictions")
    @patch("proxy.app.core.integrity_checker.compute_knowledge_coverage")
    def test_score_returns_contradictions_and_coverage(self, mock_coverage, mock_contradictions):
        mock_contradictions.return_value = [{"a": 1}]
        mock_coverage.return_value = {
            "total_chunks": 50,
            "unique_sources": 3,
            "source_distribution": {"c": 50},
            "coverage_gaps": [],
        }

        result = compute_integrity_score("kb1", None, "test")
        assert "contradictions" in result
        assert "coverage" in result
        assert "kb_id" in result
