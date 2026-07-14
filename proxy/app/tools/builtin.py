# proxy/app/tools/builtin.py
"""Built-in RAG tools: search_documents, search_by_version, get_document_metadata.

Defines handler functions that wrap hybrid_search() from proxy.app.core.retrieval
and new-style ToolDefinition wrappers using ToolParam schemas.

Compatible with both the old execute_tool() path (via handler callable)
and new decorator-based registration (via ToolDefinition with ToolParam lists).
"""

from __future__ import annotations

import json
import logging

from proxy.app.core.retrieval import hybrid_search

from .definition import ToolDefinition, ToolParam

logger = logging.getLogger (__name__)


def search_documents (query: str, top_k: int = 5, namespace: str | None = None, version: str | None = None) -> str:
  """Search indexed documents using hybrid (dense+sparse) search."""
  try:
    results = hybrid_search (query = query, version = version, top_k = top_k, namespace = namespace)
    if not results:
      return "No documents found."
    formatted = []
    for i, hit in enumerate (results):
      title = hit.payload.get ("title", "") or hit.payload.get ("doc_title", "")
      text = hit.payload.get ("text", "")
      source = hit.payload.get ("source_type", "unknown")
      formatted.append (f"[{i + 1}] {title} (source: {source}, score: {hit.score:.3f})\n{text [:300]}")
    return "\n\n".join (formatted)
  except Exception as e:
    return f"Search failed: {e}"


def search_by_version (version: str, query: str | None = None, top_k: int = 10) -> str:
  """Search documents by a specific version string."""
  try:
    results = hybrid_search (query = query or version, version = version, top_k = top_k)
    if not results:
      return f"No documents found for version '{version}'."
    formatted = []
    for i, hit in enumerate (results):
      title = hit.payload.get ("title", "") or hit.payload.get ("doc_title", "")
      text = hit.payload.get ("text", "")
      formatted.append (f"[{i + 1}] {title} (v{hit.payload.get ('version', '?')})\n{text [:300]}")
    return "\n\n".join (formatted)
  except Exception as e:
    return f"Version search failed: {e}"


def get_document_metadata (doc_id: str) -> str:
  """Get metadata for a specific document by its ID."""
  try:
    from qdrant_client import QdrantClient
    
    from proxy.app.shared.config import COLLECTION_NAME, QDRANT_HOST, QDRANT_PORT
    
    client = QdrantClient (host = QDRANT_HOST, port = QDRANT_PORT, check_compatibility = False)
    points = client.retrieve (collection_name = COLLECTION_NAME, ids = [doc_id])
    if not points:
      return f"Document '{doc_id}' not found."
    payload = points [0].payload or {}
    meta = {
        "id": doc_id, "title": payload.get ("title", "") or payload.get ("doc_title", ""),
        "source": payload.get ("source_type", "unknown"), "version": payload.get ("version", "unknown"),
        "size": len (payload.get ("text", "")),
    }
    return json.dumps (meta, indent = 2, ensure_ascii = False)
  except Exception as e:
    return f"Metadata lookup failed: {e}"


SEARCH_DOCUMENTS_TOOL = ToolDefinition (name = "search_documents",
    description = "Search indexed documents using hybrid (dense+sparse) search", parameters = [
        ToolParam (name = "query", type = str, description = "Search query text"),
        ToolParam (name = "top_k", type = int, description = "Number of results (default 5)", required = False,
                   default = 5),
        ToolParam (name = "namespace", type = str, description = "Optional tenant namespace filter", required = False),
        ToolParam (name = "version", type = str, description = "Optional document version filter", required = False),
    ], handler = search_documents, category = "search", tags = ["retrieval", "hybrid", "qdrant"], )

SEARCH_BY_VERSION_TOOL = ToolDefinition (name = "search_by_version",
    description = "Search documents by a specific version string", parameters = [
        ToolParam (name = "version", type = str, description = "Version string to search for"),
        ToolParam (name = "query", type = str, description = "Optional search query", required = False),
        ToolParam (name = "top_k", type = int, description = "Number of results (default 10)", required = False,
                   default = 10),
    ], handler = search_by_version, category = "search", tags = ["retrieval", "version", "qdrant"], )

GET_DOCUMENT_METADATA_TOOL = ToolDefinition (name = "get_document_metadata",
    description = "Get metadata for a specific document by its ID", parameters = [
        ToolParam (name = "doc_id", type = str, description = "Document ID (chunk hash)"),
    ], handler = get_document_metadata, category = "metadata", tags = ["retrieval", "metadata", "qdrant"], )


def get_all_builtin_tools () -> list [ToolDefinition]:
  """Return all built-in tools as new-style ToolDefinition instances."""
  return [SEARCH_DOCUMENTS_TOOL, SEARCH_BY_VERSION_TOOL, GET_DOCUMENT_METADATA_TOOL]
