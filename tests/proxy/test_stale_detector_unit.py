"""Tests for stale_detector module — edge cases and uncovered paths."""

import time
from unittest.mock import MagicMock, patch

from proxy.app.core.stale_detector import (
    _get_freshness_days,
    detect_stale_documents,
    get_staleness_score,
    is_stale,
    update_prometheus_metrics,
)

NOW = time.time()


class TestFreshnessDays:
    def test_known_source_types(self):
        assert _get_freshness_days("confluence") == 90
        assert _get_freshness_days("jira") == 30
        assert _get_freshness_days("gitlab") == 14
        assert _get_freshness_days("file") == 365
        assert _get_freshness_days("book") == 365
        assert _get_freshness_days("chat") == 90

    def test_unknown_source_defaults(self):
        assert _get_freshness_days("unknown") == 180
        assert _get_freshness_days("") == 180


class TestGetStalenessScore:
    def test_score_is_zero_when_age_is_zero(self):
        doc = {"payload": {"last_updated": NOW, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert score < 0.01

    def test_score_is_zero_for_future_document(self):
        doc = {"payload": {"last_updated": NOW + 86400, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert score == 0.0

    def test_expected_refresh_days_overrides_default(self):
        doc = {
            "payload": {
                "last_updated": NOW - 10 * 86400,
                "source_type": "confluence",
                "expected_refresh_days": 20,
            }
        }
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0


class TestIsStale:
    def test_is_stale_with_custom_threshold_true(self):
        doc = {"payload": {"last_updated": NOW - 95 * 86400, "source_type": "confluence"}}
        assert is_stale(doc, threshold=90.0) is True

    def test_is_stale_with_custom_threshold_false(self):
        doc = {"payload": {"last_updated": NOW - 10 * 86400, "source_type": "confluence"}}
        assert is_stale(doc, threshold=90.0) is False

    def test_is_stale_default_threshold(self):
        doc = {"payload": {"last_updated": NOW - 200 * 86400, "source_type": "confluence"}}
        assert is_stale(doc) is True


class TestDetectStaleDocuments:
    def test_no_qdrant_client(self):
        result = detect_stale_documents("kb1", MagicMock(), None, "test")
        assert result == []

    def test_empty_results(self):
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([], None)
        result = detect_stale_documents("kb1", MagicMock(), mock_qdrant, "test")
        assert result == []

    def test_sorted_by_staleness_desc(self):
        now = time.time()
        p1 = MagicMock()
        p1.id = "doc-1"
        p1.payload = {"last_updated": now - 200 * 86400, "source_type": "confluence", "source_id": "s1", "title": "T1"}
        p2 = MagicMock()
        p2.id = "doc-2"
        p2.payload = {"last_updated": now - 100 * 86400, "source_type": "confluence", "source_id": "s2", "title": "T2"}

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p1, p2], None)

        result = detect_stale_documents("kb1", MagicMock(), mock_qdrant, "test", threshold=50.0)
        assert len(result) == 2
        assert result[0]["staleness_score"] >= result[1]["staleness_score"]

    def test_qdrant_query_error_returns_empty(self):
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.side_effect = RuntimeError("connection failed")
        result = detect_stale_documents("kb1", MagicMock(), mock_qdrant, "test")
        assert result == []

    def test_doc_title_fallback(self):
        now = time.time()
        p = MagicMock()
        p.id = "doc-1"
        p.payload = {
            "last_updated": now - 100 * 86400,
            "source_type": "confluence",
            "source_id": "s1",
            "doc_title": "Document Title",
        }
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p], None)
        result = detect_stale_documents("kb1", MagicMock(), mock_qdrant, "test", threshold=1.0)
        assert result[0]["title"] == "Document Title"

    def test_null_payload_graceful(self):
        p = MagicMock()
        p.id = "doc-1"
        p.payload = None
        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([p], None)
        result = detect_stale_documents("kb1", MagicMock(), mock_qdrant, "test")
        assert result == []


class TestUpdatePrometheusMetrics:
    def test_call_does_not_raise(self):
        update_prometheus_metrics("kb-1", 10)

    @patch("proxy.app.shared.metrics.rag_stale_documents")
    def test_sets_gauge(self, mock_gauge):
        update_prometheus_metrics("kb-1", 42)
        mock_gauge.labels.assert_called_once_with(kb_id="kb-1")
        mock_gauge.labels.return_value.set.assert_called_once_with(42)
