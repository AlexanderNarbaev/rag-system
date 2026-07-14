"""Tests for proxy/app/tools/builtin.py — Built-in RAG tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestSearchDocuments:
  """Tests for search_documents handler."""
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_returns_formatted_results (self, mock_search):
    from proxy.app.tools.builtin import search_documents
    
    hit = MagicMock ()
    hit.payload = {
        "title": "Docker Guide", "text": "Docker is a containerization platform.", "source_type": "confluence",
    }
    hit.score = 0.95
    mock_search.return_value = [hit]
    
    result = search_documents (query = "What is Docker?", top_k = 5)
    assert "Docker Guide" in result
    assert "0.950" in result
    assert "confluence" in result
    mock_search.assert_called_once_with (query = "What is Docker?", version = None, top_k = 5, namespace = None)
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_returns_no_results_message (self, mock_search):
    from proxy.app.tools.builtin import search_documents
    
    mock_search.return_value = []
    result = search_documents (query = "nonexistent")
    assert result == "No documents found."
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_handles_exception (self, mock_search):
    from proxy.app.tools.builtin import search_documents
    
    mock_search.side_effect = RuntimeError ("Qdrant down")
    result = search_documents (query = "test")
    assert "Search failed" in result
    assert "Qdrant down" in result
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_with_doc_title_fallback (self, mock_search):
    from proxy.app.tools.builtin import search_documents
    
    hit = MagicMock ()
    hit.payload = {"doc_title": "Alt Title", "text": "Content", "source_type": "jira"}
    hit.score = 0.8
    mock_search.return_value = [hit]
    
    result = search_documents (query = "test")
    assert "Alt Title" in result
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_with_namespace_and_version (self, mock_search):
    from proxy.app.tools.builtin import search_documents
    
    mock_search.return_value = []
    search_documents (query = "test", namespace = "team-a", version = "v2")
    mock_search.assert_called_once_with (query = "test", version = "v2", top_k = 5, namespace = "team-a")
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_multiple_results (self, mock_search):
    from proxy.app.tools.builtin import search_documents
    
    hits = []
    for i in range (3):
      hit = MagicMock ()
      hit.payload = {"title": f"Doc {i}", "text": f"Content {i}", "source_type": "confluence"}
      hit.score = 0.9 - i * 0.1
      hits.append (hit)
    mock_search.return_value = hits
    
    result = search_documents (query = "test")
    assert "[1]" in result
    assert "[2]" in result
    assert "[3]" in result


class TestSearchByVersion:
  """Tests for search_by_version handler."""
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_by_version_returns_results (self, mock_search):
    from proxy.app.tools.builtin import search_by_version
    
    hit = MagicMock ()
    hit.payload = {"title": "API v2", "text": "API docs", "version": "v2.0"}
    hit.score = 0.9
    mock_search.return_value = [hit]
    
    result = search_by_version (version = "v2.0")
    assert "API v2" in result
    assert "v2.0" in result
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_by_version_no_results (self, mock_search):
    from proxy.app.tools.builtin import search_by_version
    
    mock_search.return_value = []
    result = search_by_version (version = "v99")
    assert "No documents found" in result
    assert "v99" in result
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_by_version_with_custom_query (self, mock_search):
    from proxy.app.tools.builtin import search_by_version
    
    mock_search.return_value = []
    search_by_version (version = "v2", query = "deploy", top_k = 5)
    mock_search.assert_called_once_with (query = "deploy", version = "v2", top_k = 5)
  
  @patch ("proxy.app.tools.builtin.hybrid_search")
  def test_search_by_version_exception (self, mock_search):
    from proxy.app.tools.builtin import search_by_version
    
    mock_search.side_effect = RuntimeError ("Connection refused")
    result = search_by_version (version = "v1")
    assert "Version search failed" in result


class TestGetDocumentMetadata:
  """Tests for get_document_metadata handler."""
  
  @patch ("qdrant_client.QdrantClient")
  def test_get_metadata_returns_json (self, mock_client_cls):
    from proxy.app.tools.builtin import get_document_metadata
    
    mock_client = MagicMock ()
    mock_client_cls.return_value = mock_client
    
    point = MagicMock ()
    point.payload = {
        "title": "Docker Guide", "source_type": "confluence", "version": "v1", "text": "Docker content here",
    }
    mock_client.retrieve.return_value = [point]
    
    result = get_document_metadata (doc_id = "abc123")
    import json
    
    meta = json.loads (result)
    assert meta ["id"] == "abc123"
    assert meta ["title"] == "Docker Guide"
    assert meta ["source"] == "confluence"
  
  @patch ("qdrant_client.QdrantClient")
  def test_get_metadata_not_found (self, mock_client_cls):
    from proxy.app.tools.builtin import get_document_metadata
    
    mock_client = MagicMock ()
    mock_client_cls.return_value = mock_client
    mock_client.retrieve.return_value = []
    
    result = get_document_metadata (doc_id = "nonexistent")
    assert "not found" in result
  
  @patch ("qdrant_client.QdrantClient")
  def test_get_metadata_exception (self, mock_client_cls):
    from proxy.app.tools.builtin import get_document_metadata
    
    mock_client_cls.side_effect = RuntimeError ("Qdrant down")
    result = get_document_metadata (doc_id = "abc")
    assert "Metadata lookup failed" in result
  
  @patch ("qdrant_client.QdrantClient")
  def test_get_metadata_with_doc_title_fallback (self, mock_client_cls):
    from proxy.app.tools.builtin import get_document_metadata
    
    mock_client = MagicMock ()
    mock_client_cls.return_value = mock_client
    
    point = MagicMock ()
    point.payload = {
        "doc_title": "Alt Title", "source_type": "jira", "version": "v3", "text": "content",
    }
    mock_client.retrieve.return_value = [point]
    
    result = get_document_metadata (doc_id = "def456")
    import json
    
    meta = json.loads (result)
    assert meta ["title"] == "Alt Title"


class TestGetAllBuiltinTools:
  """Tests for get_all_builtin_tools."""
  
  def test_returns_three_tools (self):
    from proxy.app.tools.builtin import get_all_builtin_tools
    
    tools = get_all_builtin_tools ()
    assert len (tools) == 3
  
  def test_tool_names (self):
    from proxy.app.tools.builtin import get_all_builtin_tools
    
    tools = get_all_builtin_tools ()
    names = [t.name for t in tools]
    assert "search_documents" in names
    assert "search_by_version" in names
    assert "get_document_metadata" in names
  
  def test_tools_have_handlers (self):
    from proxy.app.tools.builtin import get_all_builtin_tools
    
    for tool in get_all_builtin_tools ():
      assert tool.handler is not None
      assert callable (tool.handler)
