# proxy/app/core/__init__.py
"""Core domain logic — retrieval, reranking, context building, orchestration."""

from proxy.app.core.confidence import ConfidenceReport, GroundingReport, compute_confidence
from proxy.app.core.context import (
  KnowledgeStrip, build_context, deduplicate_chunks, extract_version_from_query,
)
from proxy.app.core.rerank import initialize_reranker, rerank_chunks
from proxy.app.core.retrieval import hybrid_search, initialize_retrieval

__all__ = [
    # confidence
    "ConfidenceReport", "GroundingReport", "compute_confidence", # context
    "KnowledgeStrip", "build_context", "deduplicate_chunks", "extract_version_from_query", # retrieval
    "hybrid_search", "initialize_retrieval", # rerank
    "initialize_reranker", "rerank_chunks",
]
