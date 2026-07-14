# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/rerank.py - reranking module with mocked CrossEncoder."""

from unittest.mock import MagicMock, patch

import pytest

from proxy.app.core.rerank import (
  _get_cache_key, _truncate_text, initialize_reranker, rerank_chunks, rerank_chunks_with_scores,
)


class TestTruncateText:
  """Tests for _truncate_text helper."""
  
  def test_within_limit (self):
    assert _truncate_text ("short", max_tokens = 10) == "short"
  
  def test_exceeds_limit (self):
    long_text = "a" * 1000
    result = _truncate_text (long_text, max_tokens = 50)
    assert len (result) == 200  # 50 * 4
  
  def test_uses_default_max_length (self):
    with patch ("proxy.app.core.rerank.RERANKER_MAX_LENGTH", 10):
      long_text = "a" * 1000
      result = _truncate_text (long_text)
      assert len (result) == 40
  
  def test_none_max_tokens (self):
    with patch ("proxy.app.core.rerank.RERANKER_MAX_LENGTH", 5):
      long_text = "a" * 100
      result = _truncate_text (long_text, max_tokens = None)
      assert len (result) == 20


class TestGetCacheKey:
  """Tests for _get_cache_key function."""
  
  def test_produces_string_with_prefix (self):
    key = _get_cache_key ("my query", "chunk text")
    assert key.startswith ("rerank:")
    assert len (key) > len ("rerank:")
  
  def test_consistent_for_same_input (self):
    a = _get_cache_key ("q", "c")
    b = _get_cache_key ("q", "c")
    assert a == b
  
  def test_different_for_different_input (self):
    a = _get_cache_key ("q1", "c")
    b = _get_cache_key ("q2", "c")
    assert a != b


class TestRerankChunks:
  """Tests for rerank_chunks with mocked CrossEncoder."""
  
  def test_empty_chunks (self):
    with patch ("proxy.app.core.rerank.reranker", MagicMock ()):
      result = rerank_chunks ("query", [])
      assert result == []
  
  def test_basic_reranking (self):
    mock_reranker = MagicMock ()
    mock_reranker.predict.return_value = [0.8, 0.3, 0.9]
    
    with patch ("proxy.app.core.rerank.reranker", mock_reranker), patch ("proxy.app.core.rerank.cache_manager", None):
      result = rerank_chunks ("query", ["A", "B", "C"], top_k = 2)
      assert len (result) == 2
      assert result == [2, 0]  # sorted by score desc: idx2 (0.9), idx0 (0.8)
  
  def test_rerank_with_cache_hit (self):
    mock_reranker = MagicMock ()
    mock_cache = MagicMock ()
    mock_cache.get_sync.side_effect = ["0.8", "0.3", None]
    
    with (
      patch ("proxy.app.core.rerank.reranker", mock_reranker), patch ("proxy.app.core.rerank.cache_manager",
                                                                      mock_cache), ):
      mock_reranker.predict.return_value = [0.8, 0.3, 0.7]
      result = rerank_chunks ("q", ["A", "B", "C"], top_k = 3, use_cache = True)
      assert len (result) == 3
  
  def test_uses_top_k_limit (self):
    mock_reranker = MagicMock ()
    mock_reranker.predict.return_value = [0.9, 0.8, 0.7, 0.6, 0.5]
    
    with patch ("proxy.app.core.rerank.reranker", mock_reranker), patch ("proxy.app.core.rerank.cache_manager", None):
      result = rerank_chunks ("q", ["a", "b", "c", "d", "e"], top_k = 2)
      assert len (result) == 2
  
  def test_truncate_applied (self):
    mock_reranker = MagicMock ()
    mock_reranker.predict.return_value = [0.5]
    
    with (
      patch ("proxy.app.core.rerank.reranker", mock_reranker), patch ("proxy.app.core.rerank.cache_manager",
                                                                      None), patch (
        "proxy.app.core.rerank._truncate_text") as mock_trunc, ):
      mock_trunc.return_value = "short"
      rerank_chunks ("q", ["very long text " * 100])
      mock_trunc.assert_called ()
  
  def test_auto_initialize (self):
    with (
      patch ("proxy.app.core.rerank.reranker", None), patch (
        "proxy.app.core.rerank.initialize_reranker") as mock_init, patch ("proxy.app.core.rerank.cache_manager",
                                                                          None), ):
      mock_init.side_effect = lambda: setattr (__import__ ("proxy.app.core.rerank", fromlist = ["reranker"]),
          "reranker", MagicMock ())
      import proxy.app.core.rerank as rerank_mod
      
      rerank_mod.reranker = MagicMock ()
      rerank_mod.reranker.predict.return_value = [0.9]
      result = rerank_chunks ("q", ["text"])
      assert result == [0]


class TestRerankChunksWithScores:
  """Tests for rerank_chunks_with_scores."""
  
  def test_returns_index_score_pairs (self):
    with (
      patch ("proxy.app.core.rerank.rerank_chunks", return_value = [2, 0]), patch (
        "proxy.app.core.rerank.reranker") as mock_reranker, ):
      mock_reranker.predict.return_value = MagicMock ()
      mock_reranker.predict.return_value.tolist.return_value = [0.95, 0.85]
      result = rerank_chunks_with_scores ("q", ["A", "B", "C"], top_k = 2)
      assert len (result) == 2
      assert result [0] == (2, 0.95)
      assert result [1] == (0, 0.85)


class TestInitializeReranker:
  """Tests for initialize_reranker function."""
  
  def test_raises_when_not_available (self):
    with patch ("proxy.app.llm.remote_services.create_reranker", side_effect = ImportError ("no st")):
      with pytest.raises (ImportError):
        initialize_reranker ()
  
  def test_initializes_with_in_memory_cache (self):
    mock_reranker = object ()
    with (
      patch ("proxy.app.llm.remote_services.create_reranker", return_value = mock_reranker), patch (
        "proxy.app.core.rerank.USE_REDIS", False), ):
      initialize_reranker ()
      from proxy.app.core.rerank import cache_manager
      
      assert cache_manager is not None
      assert cache_manager.use_redis is False
  
  def test_initializes_with_redis (self):
    mock_reranker = object ()
    with (
      patch ("proxy.app.llm.remote_services.create_reranker", return_value = mock_reranker), patch (
        "proxy.app.core.rerank.USE_REDIS", True), patch ("proxy.app.core.rerank.REDIS_URL", "redis://test:6379"), ):
      initialize_reranker ()
      from proxy.app.core.rerank import cache_manager
      
      assert cache_manager.use_redis is True
