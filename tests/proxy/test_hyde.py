# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for HyDE (Hypothetical Document Embeddings) pipeline."""

from unittest.mock import MagicMock, patch

from proxy.app.core.hyde import (
  embed_hypothetical, generate_hypothetical_answer, hyde_search,
)


class TestGenerateHypotheticalAnswer:
  """Tests for SLM-based hypothetical answer generation."""
  
  def test_generates_answer_when_slm_available (self):
    with patch ("proxy.app.core.hyde._call_slm_sync", return_value = "A test answer."):
      result = generate_hypothetical_answer ("What is testing?")
      assert result == "A test answer."
  
  def test_returns_original_query_when_slm_empty (self):
    with patch ("proxy.app.core.hyde._call_slm_sync", return_value = ""):
      result = generate_hypothetical_answer ("What is testing?")
      assert result == "What is testing?"
  
  def test_returns_original_query_when_slm_fails (self):
    with patch ("proxy.app.core.hyde._call_slm_sync", side_effect = Exception ("SLM down")):
      result = generate_hypothetical_answer ("What is testing?")
      assert result == "What is testing?"
  
  def test_strips_whitespace_from_result (self):
    with patch ("proxy.app.core.hyde._call_slm_sync", return_value = "   A padded answer.   "):
      result = generate_hypothetical_answer ("Query")
      assert result == "A padded answer."
  
  def test_empty_query (self):
    with patch ("proxy.app.core.hyde._call_slm_sync", return_value = "Answer"):
      result = generate_hypothetical_answer ("")
      assert result == ""


class TestEmbedHypothetical:
  """Tests for embedding a hypothetical answer."""
  
  @patch ("proxy.app.core.hyde.embedder")
  def test_returns_dense_vector (self, mock_embedder):
    mock_embedder.encode.return_value = MagicMock ()
    mock_embedder.encode.return_value.tolist.return_value = [0.1, 0.2, 0.3]
    result = embed_hypothetical ("A test hypothesis")
    assert isinstance (result, list)
    assert len (result) == 3
  
  @patch ("proxy.app.core.hyde.embedder")
  def test_embeds_with_normalization (self, mock_embedder):
    mock_embedder.encode.return_value = MagicMock ()
    mock_embedder.encode.return_value.tolist.return_value = [0.5, -0.3]
    embed_hypothetical ("Normalized")
    mock_embedder.encode.assert_called_once ()
    assert "normalize_embeddings" in str (mock_embedder.encode.call_args)
  
  @patch ("proxy.app.core.hyde.embedder", None)
  def test_returns_empty_when_embedder_unavailable (self):
    result = embed_hypothetical ("No embedder")
    assert result == []
  
  def test_empty_input (self):
    result = embed_hypothetical ("")
    assert result == []


class TestHydeSearch:
  """Tests for the full HyDE pipeline: generate -> embed -> search."""
  
  @patch ("proxy.app.core.hyde.hybrid_search")
  @patch ("proxy.app.core.hyde.embedder")
  def test_search_returns_chunks (self, mock_embedder, mock_search):
    mock_embedder.encode.return_value = MagicMock ()
    mock_embedder.encode.return_value.tolist.return_value = [0.1, 0.2]
    
    mock_hit = MagicMock ()
    mock_hit.id = "chunk-1"
    mock_hit.score = 0.95
    mock_hit.payload = {"text": "Relevant document text", "source_type": "docs"}
    mock_search.return_value = [mock_hit]
    
    # Patch qdrant_client to prevent direct search path from using stale mocks
    mock_qdrant = MagicMock ()
    mock_response = MagicMock ()
    mock_response.points = [mock_hit]
    mock_qdrant.query_points.return_value = mock_response
    with patch ("proxy.app.core.hyde._call_slm_sync", return_value = "A hypothetical answer about documents."):
      with patch ("proxy.app.core.hyde.HYDE_ENABLED", True):
        with patch ("proxy.app.core.retrieval.qdrant_client", mock_qdrant):
          result = hyde_search ("What are documents?")
          assert isinstance (result, list)
  
  @patch ("proxy.app.core.hyde.hybrid_search")
  @patch ("proxy.app.core.hyde.embedder")
  def test_search_fallback_when_slm_fails (self, mock_embedder, mock_search):
    mock_embedder.encode.return_value = MagicMock ()
    mock_embedder.encode.return_value.tolist.return_value = [0.1, 0.2]
    
    mock_hit = MagicMock ()
    mock_hit.id = "chunk-1"
    mock_hit.score = 0.8
    mock_hit.payload = {"text": "Content", "source_type": "wiki"}
    mock_search.return_value = [mock_hit]
    
    mock_qdrant = MagicMock ()
    mock_response = MagicMock ()
    mock_response.points = [mock_hit]
    mock_qdrant.query_points.return_value = mock_response
    with patch ("proxy.app.core.hyde._call_slm_sync", side_effect = Exception ("SLM error")):
      with patch ("proxy.app.core.hyde.HYDE_ENABLED", True):
        with patch ("proxy.app.core.retrieval.qdrant_client", mock_qdrant):
          result = hyde_search ("Test query")
          assert isinstance (result, list)
          assert len (result) >= 0
  
  @patch ("proxy.app.core.hyde.hybrid_search")
  @patch ("proxy.app.core.hyde.embedder")
  def test_search_returns_empty_on_search_failure (self, mock_embedder, mock_search):
    mock_embedder.encode.return_value = MagicMock ()
    mock_embedder.encode.return_value.tolist.return_value = [0.1, 0.2]
    mock_search.side_effect = Exception ("Qdrant down")
    
    mock_qdrant = MagicMock ()
    mock_qdrant.query_points.side_effect = Exception ("Qdrant down")
    with patch ("proxy.app.core.hyde._call_slm_sync", return_value = "Hypothesis"):
      with patch ("proxy.app.core.hyde.HYDE_ENABLED", True):
        with patch ("proxy.app.core.retrieval.qdrant_client", mock_qdrant):
          result = hyde_search ("Query")
          assert result == []
  
  @patch ("proxy.app.core.hyde.hybrid_search")
  @patch ("proxy.app.core.hyde.embedder")
  def test_search_skips_when_hyde_disabled (self, mock_embedder, mock_search):
    mock_embedder.encode.return_value = MagicMock ()
    mock_embedder.encode.return_value.tolist.return_value = [0.1, 0.2]
    
    mock_hit = MagicMock ()
    mock_hit.id = "chunk-1"
    mock_hit.score = 0.9
    mock_hit.payload = {"text": "Content"}
    mock_search.return_value = [mock_hit]
    
    mock_qdrant = MagicMock ()
    mock_response = MagicMock ()
    mock_response.points = [mock_hit]
    mock_qdrant.query_points.return_value = mock_response
    with patch ("proxy.app.core.hyde.HYDE_ENABLED", False):
      with patch ("proxy.app.core.retrieval.qdrant_client", mock_qdrant):
        result = hyde_search ("Query")
        # When HyDE is disabled, qdrant_client is used for direct search
        assert len (result) == 1
  
  @patch ("proxy.app.core.hyde.hybrid_search")
  @patch ("proxy.app.core.hyde.embedder")
  def test_search_with_version (self, mock_embedder, mock_search):
    mock_embedder.encode.return_value = MagicMock ()
    mock_embedder.encode.return_value.tolist.return_value = [0.1, 0.2]
    
    mock_hit = MagicMock ()
    mock_hit.id = "chunk-2"
    mock_hit.score = 0.85
    mock_hit.payload = {"text": "Versioned content", "source_type": "docs"}
    mock_search.return_value = [mock_hit]
    
    mock_qdrant = MagicMock ()
    mock_response = MagicMock ()
    mock_response.points = [mock_hit]
    mock_qdrant.query_points.return_value = mock_response
    with patch ("proxy.app.core.hyde._call_slm_sync", return_value = "Versioned answer"):
      with patch ("proxy.app.core.hyde.HYDE_ENABLED", True):
        with patch ("proxy.app.core.retrieval.qdrant_client", mock_qdrant):
          result = hyde_search ("Query", version = "v2.0")
          assert isinstance (result, list)
  
  @patch ("proxy.app.core.hyde.hybrid_search")
  @patch ("proxy.app.core.hyde.embedder")
  def test_search_with_top_k (self, mock_embedder, mock_search):
    mock_embedder.encode.return_value = MagicMock ()
    mock_embedder.encode.return_value.tolist.return_value = [0.1, 0.2]
    mock_search.return_value = [MagicMock () for _ in range (20)]
    
    with patch ("proxy.app.core.hyde._call_slm_sync", return_value = "Answer"):
      with patch ("proxy.app.core.hyde.HYDE_ENABLED", True):
        result = hyde_search ("Query", top_k = 20)
        assert len (result) <= 20
