# ruff: noqa: E501, E402
"""Tests for proxy/app/core/retrieval.py — additional coverage."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch


class TestParseTimestamp:
  def test_none_returns_none (self):
    from proxy.app.core.retrieval import _parse_timestamp

    assert _parse_timestamp (None) is None

  def test_int_value (self):
    from proxy.app.core.retrieval import _parse_timestamp

    assert _parse_timestamp (1000) == 1000.0

  def test_float_value (self):
    from proxy.app.core.retrieval import _parse_timestamp

    assert _parse_timestamp (1234.5) == 1234.5

  def test_iso_string (self):
    from proxy.app.core.retrieval import _parse_timestamp

    result = _parse_timestamp ("2025-01-01T00:00:00Z")
    assert result is not None

  def test_iso_without_z (self):
    from proxy.app.core.retrieval import _parse_timestamp

    result = _parse_timestamp ("2025-06-15T12:30:00")
    assert result is not None

  def test_invalid_string (self):
    from proxy.app.core.retrieval import _parse_timestamp

    assert _parse_timestamp ("not-a-date") is None

  def test_empty_string (self):
    from proxy.app.core.retrieval import _parse_timestamp

    assert _parse_timestamp ("") is None


class TestApplyTimeDecay:
  def test_empty_chunks (self):
    from proxy.app.core.retrieval import apply_time_decay

    assert apply_time_decay ([]) == []

  def test_no_timestamp_no_change (self):
    from proxy.app.core.retrieval import apply_time_decay

    chunks = [{"score": 0.5, "text": "test"}]
    result = apply_time_decay (chunks)
    assert len (result) == 1
    assert result [0] ["score"] == 0.5

  def test_with_updated_at (self):
    from proxy.app.core.retrieval import apply_time_decay

    recent = datetime.now (UTC).isoformat ()
    chunks = [{"score": 0.5, "payload": {"updated_at": recent}}]
    result = apply_time_decay (chunks)
    assert len (result) == 1
    assert result [0] ["score"] > 0.5

  def test_with_old_date (self):
    from proxy.app.core.retrieval import apply_time_decay

    chunks = [{"score": 0.5, "payload": {"created_at": "2020-01-01T00:00:00Z"}}]
    result = apply_time_decay (chunks)
    assert len (result) == 1
    # Old documents get lower boost
    assert result [0] ["time_boost"] < 0.5

  def test_with_created_at (self):
    from proxy.app.core.retrieval import apply_time_decay

    chunks = [{"score": 0.5, "created_at": "2025-01-01T00:00:00Z"}]
    result = apply_time_decay (chunks)
    assert len (result) == 1


class TestReciprocalRankFusion:
  def test_basic_fusion (self):
    from proxy.app.core.retrieval import reciprocal_rank_fusion

    hit1 = MagicMock (id = "d1", score = 0.9)
    hit2 = MagicMock (id = "d2", score = 0.8)
    hit3 = MagicMock (id = "d1", score = 0.7)
    result = reciprocal_rank_fusion ([hit1, hit2], [hit3])
    assert len (result) == 2

  def test_empty_dense (self):
    from proxy.app.core.retrieval import reciprocal_rank_fusion

    hit = MagicMock (id = "d1", score = 0.9)
    result = reciprocal_rank_fusion ([], [hit])
    assert len (result) == 1

  def test_empty_sparse (self):
    from proxy.app.core.retrieval import reciprocal_rank_fusion

    hit = MagicMock (id = "d1", score = 0.9)
    result = reciprocal_rank_fusion ([hit], [])
    assert len (result) == 1


class TestComputeDynamicTopK:
  @patch ("proxy.app.llm.slm.score_query_complexity")
  @patch ("proxy.app.llm.slm.dynamic_top_k_from_complexity")
  def test_success (self, mock_dtk, mock_sc):
    mock_sc.return_value = 0.5
    mock_dtk.return_value = 25
    from proxy.app.core.retrieval import compute_dynamic_top_k

    result = compute_dynamic_top_k ("test query")
    assert result == 25

  @patch ("proxy.app.llm.slm.score_query_complexity", side_effect = Exception ("slm error"))
  def test_fallback (self, mock_sc):
    from proxy.app.core.retrieval import compute_dynamic_top_k

    result = compute_dynamic_top_k ("test query", default = 50)
    assert result == 50


class TestCheckQdrantHealth:
  @patch ("proxy.app.core.retrieval.qdrant_client")
  def test_healthy (self, mock_client):
    mock_client.get_collections.return_value = True
    from proxy.app.core.retrieval import check_qdrant_health

    assert check_qdrant_health () is True

  @patch ("proxy.app.core.retrieval.qdrant_client")
  def test_unhealthy (self, mock_client):
    mock_client.get_collections.side_effect = Exception ("down")
    from proxy.app.core.retrieval import check_qdrant_health

    assert check_qdrant_health () is False
