# tests/proxy/test_integrity.py
"""Tests for knowledge integrity validation (FR-18)."""

import time
from unittest.mock import MagicMock, patch


class TestCheckContradiction:
    """Tests for check_contradiction."""

    def test_empty_chunks(self):
        from proxy.app.core.integrity_checker import check_contradiction

        result = check_contradiction("", "")
        assert result["contradiction_score"] == 0.0
        assert result["entailment_score"] == 0.0
        assert result["neutral_score"] == 0.0

    def test_empty_chunk_a(self):
        from proxy.app.core.integrity_checker import check_contradiction

        result = check_contradiction("", "some text")
        assert result["contradiction_score"] == 0.0

    def test_lightweight_identical_chunks(self):
        from proxy.app.core.integrity_checker import _check_contradiction_lightweight

        result = _check_contradiction_lightweight(
            "The database is running on port 5432.",
            "The database is running on port 5432.",
        )
        assert result["contradiction_score"] < 0.2
        assert result["entailment_score"] >= 0.5
        assert result["neutral_score"] < 0.5

    def test_lightweight_different_chunks(self):
        from proxy.app.core.integrity_checker import _check_contradiction_lightweight

        result = _check_contradiction_lightweight(
            "The database is running on port 5432.",
            "The application uses Redis for caching.",
        )
        assert result["neutral_score"] >= 0.5

    def test_lightweight_negation_detection(self):
        from proxy.app.core.integrity_checker import _check_contradiction_lightweight

        result = _check_contradiction_lightweight(
            "The database is running on port 5432.",
            "The database is NOT running on port 5432.",
        )
        assert result["contradiction_score"] >= 0.4

    def test_lightweight_empty_inputs(self):
        from proxy.app.core.integrity_checker import _check_contradiction_lightweight

        result = _check_contradiction_lightweight("", "")
        assert result["contradiction_score"] == 0.0
        assert result["entailment_score"] == 0.0
        assert result["neutral_score"] == 1.0

    def test_contradiction_returns_dict_with_expected_keys(self):
        from proxy.app.core.integrity_checker import check_contradiction

        result = check_contradiction("test chunk a", "test chunk b")
        assert "contradiction_score" in result
        assert "entailment_score" in result
        assert "neutral_score" in result
        assert 0.0 <= result["contradiction_score"] <= 1.0
        assert 0.0 <= result["entailment_score"] <= 1.0
        assert 0.0 <= result["neutral_score"] <= 1.0


class TestFindContradictions:
    """Tests for find_contradictions."""

    def test_no_qdrant_client(self):
        from proxy.app.core.integrity_checker import find_contradictions

        result = find_contradictions("kb1", None, "test_collection")
        assert result == []

    def test_empty_results(self):
        from proxy.app.core.integrity_checker import find_contradictions

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([], None)

        result = find_contradictions("kb1", mock_qdrant, "test_collection")
        assert result == []

    def test_single_chunk_no_contradictions(self):
        from proxy.app.core.integrity_checker import find_contradictions

        mock_point = MagicMock()
        mock_point.id = "chunk-1"
        mock_point.payload = {
            "source_id": "doc-1",
            "text": "The service runs on port 8080.",
            "title": "Service Config",
            "source_type": "confluence",
        }

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([mock_point], None)

        result = find_contradictions("kb1", mock_qdrant, "test_collection")
        assert result == []

    @patch("proxy.app.core.integrity_checker.check_contradiction")
    def test_detects_contradiction_with_low_threshold(self, mock_check):
        from proxy.app.core.integrity_checker import find_contradictions

        mock_check.return_value = {
            "contradiction_score": 0.8,
            "entailment_score": 0.1,
            "neutral_score": 0.1,
        }

        p1 = MagicMock()
        p1.id = "c1"
        p1.payload = {
            "source_id": "doc-1",
            "text": "The port is 8080.",
            "title": "Config A",
            "source_type": "confluence",
        }
        p2 = MagicMock()
        p2.id = "c2"
        p2.payload = {
            "source_id": "doc-1",
            "text": "The port is 9090.",
            "title": "Config B",
            "source_type": "confluence",
        }

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)

        result = find_contradictions("kb1", mock_qdrant, "test_collection", threshold=0.5)
        assert len(result) == 1
        assert result[0]["chunk_a_id"] == "c1"
        assert result[0]["chunk_b_id"] == "c2"
        assert result[0]["contradiction_score"] == 0.8

    @patch("proxy.app.core.integrity_checker.check_contradiction")
    def test_excludes_below_threshold(self, mock_check):
        from proxy.app.core.integrity_checker import find_contradictions

        mock_check.return_value = {
            "contradiction_score": 0.3,
            "entailment_score": 0.4,
            "neutral_score": 0.3,
        }

        p1 = MagicMock()
        p1.id = "c1"
        p1.payload = {"source_id": "doc-1", "text": "text a", "title": "A", "source_type": "confluence"}
        p2 = MagicMock()
        p2.id = "c2"
        p2.payload = {"source_id": "doc-1", "text": "text b", "title": "B", "source_type": "confluence"}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)

        result = find_contradictions("kb1", mock_qdrant, "test_collection", threshold=0.8)
        assert len(result) == 0

    def test_different_source_ids_not_compared(self):
        from proxy.app.core.integrity_checker import find_contradictions

        p1 = MagicMock()
        p1.id = "c1"
        p1.payload = {"source_id": "doc-A", "text": "text a", "title": "A", "source_type": "confluence"}
        p2 = MagicMock()
        p2.id = "c2"
        p2.payload = {"source_id": "doc-B", "text": "text b", "title": "B", "source_type": "confluence"}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)

        result = find_contradictions("kb1", mock_qdrant, "test_collection")
        assert result == []


class TestComputeKnowledgeCoverage:
    """Tests for compute_knowledge_coverage."""

    def test_no_qdrant_client(self):
        from proxy.app.core.integrity_checker import compute_knowledge_coverage

        result = compute_knowledge_coverage("kb1", None, "test_collection")
        assert "error" in result

    def test_empty_results(self):
        from proxy.app.core.integrity_checker import compute_knowledge_coverage

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([], None)

        result = compute_knowledge_coverage("kb1", mock_qdrant, "test_collection")
        assert result["total_chunks"] == 0
        assert result["source_distribution"] == {}

    def test_source_distribution(self):
        from proxy.app.core.integrity_checker import compute_knowledge_coverage

        p1 = MagicMock()
        p1.payload = {
            "source_type": "confluence",
            "title": "Doc 1",
            "last_updated": time.time(),
        }
        p2 = MagicMock()
        p2.payload = {
            "source_type": "jira",
            "title": "Issue 1",
            "last_updated": time.time(),
        }

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)

        result = compute_knowledge_coverage("kb1", mock_qdrant, "test_collection")
        assert result["total_chunks"] == 2
        assert result["unique_sources"] == 2
        assert result["source_distribution"]["confluence"] == 1
        assert result["source_distribution"]["jira"] == 1

    def test_single_source_gap(self):
        from proxy.app.core.integrity_checker import compute_knowledge_coverage

        p1 = MagicMock()
        p1.payload = {"source_type": "confluence", "title": "Doc 1", "last_updated": time.time()}
        p2 = MagicMock()
        p2.payload = {"source_type": "confluence", "title": "Doc 2", "last_updated": time.time()}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)

        result = compute_knowledge_coverage("kb1", mock_qdrant, "test_collection")
        assert result["unique_sources"] == 1
        gaps = result["coverage_gaps"]
        assert any(g["type"] == "single_source" for g in gaps)

    def test_outdated_coverage_gap(self):
        from proxy.app.core.integrity_checker import compute_knowledge_coverage

        now = time.time()
        p1 = MagicMock()
        p1.payload = {"source_type": "confluence", "title": "Old Doc", "last_updated": now - 60 * 86400}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1], None)

        result = compute_knowledge_coverage("kb1", mock_qdrant, "test_collection")
        gaps = result["coverage_gaps"]
        assert any(g["type"] == "outdated" for g in gaps)

    def test_topic_distribution(self):
        from proxy.app.core.integrity_checker import compute_knowledge_coverage

        p1 = MagicMock()
        p1.payload = {"source_type": "confluence", "title": "API Reference", "last_updated": time.time()}
        p2 = MagicMock()
        p2.payload = {"source_type": "confluence", "title": "API Reference", "last_updated": time.time()}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)

        result = compute_knowledge_coverage("kb1", mock_qdrant, "test_collection")
        assert "API Reference" in result["topic_distribution"]


class TestComputeIntegrityScore:
    """Tests for compute_integrity_score."""

    @patch("proxy.app.core.integrity_checker.find_contradictions")
    @patch("proxy.app.core.integrity_checker.compute_knowledge_coverage")
    def test_perfect_score(self, mock_coverage, mock_contradictions):
        from proxy.app.core.integrity_checker import compute_integrity_score

        mock_contradictions.return_value = []
        mock_coverage.return_value = {
            "total_chunks": 100,
            "unique_sources": 5,
            "source_distribution": {"confluence": 50, "jira": 30, "gitlab": 20},
            "coverage_gaps": [],
        }

        result = compute_integrity_score("kb1", None, "test_collection")
        assert result["kb_id"] == "kb1"
        assert result["overall_score"] >= 50.0

    @patch("proxy.app.core.integrity_checker.find_contradictions")
    @patch("proxy.app.core.integrity_checker.compute_knowledge_coverage")
    def test_score_with_contradictions(self, mock_coverage, mock_contradictions):
        from proxy.app.core.integrity_checker import compute_integrity_score

        mock_contradictions.return_value = [{"source_id": "doc-1"} for _ in range(10)]
        mock_coverage.return_value = {
            "total_chunks": 100,
            "unique_sources": 3,
            "source_distribution": {"confluence": 100},
            "coverage_gaps": [],
        }

        result = compute_integrity_score("kb1", None, "test_collection")
        assert result["overall_score"] < 90.0

    @patch("proxy.app.core.integrity_checker.find_contradictions")
    @patch("proxy.app.core.integrity_checker.compute_knowledge_coverage")
    def test_score_in_range(self, mock_coverage, mock_contradictions):
        from proxy.app.core.integrity_checker import compute_integrity_score

        mock_contradictions.return_value = []
        mock_coverage.return_value = {
            "total_chunks": 50,
            "unique_sources": 2,
            "source_distribution": {"confluence": 30, "jira": 20},
            "coverage_gaps": [{"type": "outdated", "message": "Old"}],
        }

        result = compute_integrity_score("kb1", None, "test_collection")
        assert 0.0 <= result["overall_score"] <= 100.0
