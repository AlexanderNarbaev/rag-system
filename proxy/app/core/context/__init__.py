# proxy/app/core/context/__init__.py
"""Context building, deduplication, versioning, and compression for RAG proxy.

Re-exports all public symbols for backward compatibility with
``from proxy.app.core.context import ...`` imports.
"""

from proxy.app.core.context.builder import (
  KnowledgeStrip,
  build_context,
  compute_chunk_hash,
  deduplicate_chunks,
  estimate_tokens,
  extract_relevant_segments,
  group_by_semantic_key,
  prepare_context,
  reorder_chunks,
)
from proxy.app.core.context.compression import (
  assemble_multimodal_context,
  decompose_to_strips,
)
from proxy.app.core.context.versioning import (
  extract_version_from_query,
  resolve_versions,
)

__all__ = [
    # builder
    "KnowledgeStrip", "assemble_multimodal_context", "build_context", "compute_chunk_hash", # compression
    "decompose_to_strips", "deduplicate_chunks", "estimate_tokens", "extract_relevant_segments", # versioning
    "extract_version_from_query", "group_by_semantic_key", "prepare_context", "reorder_chunks", "resolve_versions",
]
