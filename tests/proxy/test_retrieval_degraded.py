# tests/proxy/test_retrieval_degraded.py
"""Tests for retrieval module graceful degradation when Qdrant is unavailable."""

from unittest.mock import MagicMock, patch


class TestRetrievalDegradation:
  """Test that retrieval degrades gracefully when Qdrant is down."""

  @patch ("proxy.app.llm.remote_services.create_embedder", return_value = MagicMock ())
  @patch ("proxy.app.core.retrieval.QdrantClient")
  def test_initialize_retrieval_handles_qdrant_down (self, mock_client_cls, mock_create_embedder):
    """When Qdrant is unreachable, initialize_retrieval sets client to None."""
    from proxy.app.core import retrieval

    mock_client_cls.side_effect = ConnectionError ("Connection refused")

    retrieval.initialize_retrieval ()
    assert retrieval.qdrant_client is None
    # Embedder should still be set (from mock)
    assert retrieval.embedder is not None

  @patch ("proxy.app.llm.remote_services.create_embedder", return_value = MagicMock ())
  @patch ("proxy.app.core.retrieval.QdrantClient")
  def test_initialize_retrieval_sets_client_on_success (self, mock_client_cls, mock_create_embedder):
    """When Qdrant is reachable, client is initialized."""
    from proxy.app.core import retrieval

    mock_client = MagicMock ()
    mock_client.get_collections.return_value = MagicMock (collections = [])
    mock_client_cls.return_value = mock_client

    retrieval.initialize_retrieval ()
    assert retrieval.qdrant_client is not None

  @patch ("proxy.app.core.retrieval.qdrant_client", None)
  @patch ("proxy.app.core.retrieval.embedder", None)
  def test_hybrid_search_returns_empty_when_no_client (self):
    """hybrid_search returns empty list when Qdrant is unavailable."""
    from proxy.app.core.retrieval import hybrid_search

    # Should not raise, should return empty
    with patch ("proxy.app.core.retrieval.initialize_retrieval"):
      with patch ("proxy.app.core.retrieval.qdrant_client", None):
        result = hybrid_search (query = "test query")
        assert result == []


class TestOrchestratorDegradation:
  """Test that orchestrator nodes degrade gracefully."""

  def test_retrieve_node_returns_empty_on_failure (self):
    """retrieve node returns empty chunks when hybrid_search fails."""
    from proxy.app.core.orchestrator.nodes import retrieve

    with patch ("proxy.app.core.orchestrator.nodes._get_hybrid_search") as mock_get:
      mock_get.return_value = MagicMock (side_effect = ConnectionError ("Qdrant down"))
      state = {"query": "test", "version": None}
      result = retrieve (state)
      assert result ["retrieved_chunks"] == []
