# tests/proxy/test_stale_detection.py
"""Tests for stale document detection (FR-16)."""

import time
from unittest.mock import MagicMock


class TestStalenessScore:
    """Tests for get_staleness_score."""

    def test_fresh_document(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"last_updated": now, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert score < 0.01

    def test_overdue_document(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"last_updated": now - 120 * 86400, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert score >= 100.0

    def test_exactly_stale(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"last_updated": now - 90 * 86400, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert 99.0 <= score <= 101.0

    def test_half_stale_confluence(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"last_updated": now - 45 * 86400, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0

    def test_staleness_with_expected_refresh_days(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {
            "payload": {
                "last_updated": now - 10 * 86400,
                "source_type": "confluence",
                "expected_refresh_days": 20,
            }
        }
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0

    def test_jira_default_threshold(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"last_updated": now - 15 * 86400, "source_type": "jira"}}
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0

    def test_gitlab_default_threshold(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"last_updated": now - 7 * 86400, "source_type": "gitlab"}}
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0

    def test_unknown_source_type(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"last_updated": now - 90 * 86400, "source_type": "unknown"}}
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0

    def test_no_timestamp_returns_50(self):
        from proxy.app.core.stale_detector import get_staleness_score

        doc = {"payload": {"source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert score == 50.0

    def test_score_capped_at_100(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"last_updated": now - 365 * 86400, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert score == 100.0

    def test_uses_created_at_fallback(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"created_at": now - 45 * 86400, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0

    def test_uses_updated_at_fallback(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"payload": {"updated_at": now - 45 * 86400, "source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0

    def test_top_level_fields(self):
        from proxy.app.core.stale_detector import get_staleness_score

        now = time.time()
        doc = {"last_updated": now - 45 * 86400, "payload": {"source_type": "confluence"}}
        score = get_staleness_score(doc)
        assert 49.0 <= score <= 51.0


class TestIsStale:
    """Tests for is_stale function."""

    def test_is_stale_above_threshold(self):
        from proxy.app.core.stale_detector import is_stale

        now = time.time()
        doc = {"payload": {"last_updated": now - 95 * 86400, "source_type": "confluence"}}
        assert is_stale(doc, threshold=100.0) is True

    def test_not_stale_below_threshold(self):
        from proxy.app.core.stale_detector import is_stale

        now = time.time()
        doc = {"payload": {"last_updated": now - 10 * 86400, "source_type": "confluence"}}
        assert is_stale(doc, threshold=90.0) is False


class TestDetectStaleDocuments:
    """Tests for detect_stale_documents."""

    def test_no_qdrant_client(self):
        from proxy.app.core.stale_detector import detect_stale_documents

        result = detect_stale_documents("kb1", MagicMock(), None, "test_collection")
        assert result == []

    def test_empty_results(self):
        from proxy.app.core.stale_detector import detect_stale_documents

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([], None)
        mock_kb = MagicMock()

        result = detect_stale_documents("kb1", mock_kb, mock_qdrant, "test_collection")
        assert result == []

    def test_filters_by_threshold(self):
        from proxy.app.core.stale_detector import detect_stale_documents

        now = time.time()
        mock_point = MagicMock()
        mock_point.id = "doc-1"
        mock_point.payload = {
            "last_updated": now - 100 * 86400,
            "source_type": "confluence",
            "source_id": "conf-123",
            "title": "Test Doc",
        }

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([mock_point], None)
        mock_kb = MagicMock()

        result = detect_stale_documents("kb1", mock_kb, mock_qdrant, "test_collection", threshold=100.0)
        assert len(result) == 1
        assert result[0]["id"] == "doc-1"
        assert result[0]["source_type"] == "confluence"
        assert result[0]["source_id"] == "conf-123"
        assert result[0]["title"] == "Test Doc"
        assert result[0]["staleness_score"] >= 100.0

    def test_excludes_fresh_documents(self):
        from proxy.app.core.stale_detector import detect_stale_documents

        now = time.time()
        mock_point = MagicMock()
        mock_point.id = "doc-1"
        mock_point.payload = {
            "last_updated": now - 10 * 86400,
            "source_type": "confluence",
            "source_id": "conf-123",
            "title": "Fresh Doc",
        }

        mock_qdrant = MagicMock()
        mock_qdrant.scroll.return_value = ([mock_point], None)
        mock_kb = MagicMock()

        result = detect_stale_documents("kb1", mock_kb, mock_qdrant, "test_collection", threshold=70.0)
        assert len(result) == 0


class TestUpdatePrometheusMetrics:
    """Tests for Prometheus metrics update."""

    def test_updates_gauge(self):
        from proxy.app.core.stale_detector import update_prometheus_metrics

        update_prometheus_metrics("kb-1", 5)
