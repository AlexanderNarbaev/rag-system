# tests/integration/test_context_assembly.py
"""Integration tests for context assembly pipeline.

Tests deduplication, version resolution, and build_context working together.
"""

import sys
from pathlib import Path

sys.path.insert (0, str (Path (__file__).parent.parent.parent / "proxy"))


class TestDeduplicationAndVersionResolution:
  """Tests for deduplication and version resolution working in sequence."""

  def test_dedup_then_resolve_versions (self):
    """Deduplication removes exact duplicates; resolve_versions picks latest per document."""
    from proxy.app.core.context import deduplicate_chunks, resolve_versions

    chunks = [
        ({"text": "Chunk A", "source_id": "doc1", "version": "1.0", "title": "Section 1"}, 0.95),
        ({"text": "Chunk A", "source_id": "doc1", "version": "1.0", "title": "Section 1"}, 0.93),  # duplicate
        ({"text": "Chunk B", "source_id": "doc1", "version": "2.0", "title": "Section 2"}, 0.90),
        ({"text": "Other doc chunk", "source_id": "doc2", "version": "1.5", "title": "Guide"}, 0.88),
    ]
    deduped = deduplicate_chunks (chunks)
    assert len (deduped) == 3

    resolved = resolve_versions (deduped, requested_version = None)
    # doc1: v2.0 wins, doc2: v1.5 remains
    assert len (resolved) == 2
    versions = {ch ["source_id"]: ch ["version"] for ch, _ in resolved}
    assert versions ["doc1"] == "2.0"
    assert versions ["doc2"] == "1.5"

  def test_resolve_with_specific_version_requested (self):
    """When a specific version is requested, only matching chunks survive."""
    from proxy.app.core.context import resolve_versions

    chunks = [
        ({"text": "V1 content", "source_id": "doc1", "version": "1.0", "title": "A"}, 0.90),
        ({"text": "V2 content", "source_id": "doc1", "version": "2.0", "title": "A"}, 0.95),
        ({"text": "V3 content", "source_id": "doc1", "version": "3.0", "title": "A"}, 0.85),
    ]
    resolved = resolve_versions (chunks, requested_version = "2.0")
    assert len (resolved) == 1
    assert resolved [0] [0] ["version"] == "2.0"

  def test_resolve_versions_semantic_comparison (self):
    """When no version is requested, version tuples are compared semantically."""
    from proxy.app.core.context import resolve_versions

    chunks = [
        ({"text": "Older API docs", "source_id": "api_spec", "version": "2.3", "title": "API"}, 0.80),
        ({"text": "Newer API docs", "source_id": "api_spec", "version": "10.1", "title": "API"}, 0.92),
        ({"text": "Even newer", "source_id": "api_spec", "version": "10.0.5", "title": "API"}, 0.85),
    ]
    resolved = resolve_versions (chunks)
    assert len (resolved) == 1
    assert resolved [0] [0] ["version"] == "10.1"

  def test_dedup_preserves_first_occurrence (self):
    """Deduplication keeps the first occurrence of a duplicate (usually higher score)."""
    from proxy.app.core.context import deduplicate_chunks

    chunks = [
        ({"text": "Important info", "source_id": "doc", "version": "1.0", "title": "T"}, 0.99),
        ({"text": "Important info", "source_id": "doc", "version": "1.0", "title": "T"}, 0.50),
    ]
    deduped = deduplicate_chunks (chunks)
    assert len (deduped) == 1
    assert deduped [0] [1] == 0.99


class TestBuildContext:
  """Tests for context assembly with token limits and metadata."""

  def test_context_built_with_metadata (self):
    """Context includes metadata headers from chunks."""
    from proxy.app.core.context import build_context

    chunks = [
        (
            {
                "text": "RAG is a technique for LLMs.", "source_type": "confluence", "doc_title": "RAG Guide",
                "title": "Overview", "version": "2.0",
            }, 0.95,
        ),
    ]
    context = build_context (chunks, max_tokens = 100000, include_metadata = True)
    assert "[confluence]" in context
    assert "RAG Guide" in context
    assert "v2.0" in context
    assert "RAG is a technique" in context

  def test_context_excludes_metadata_when_disabled (self):
    """Context omits metadata headers when include_metadata=False."""
    from proxy.app.core.context import build_context

    chunks = [
        (
            {
                "text": "Plain content without metadata prefix.", "source_type": "confluence", "doc_title": "Doc",
                "title": "Sec", "version": "1.0",
            }, 0.90,
        ),
    ]
    context = build_context (chunks, max_tokens = 100000, include_metadata = False)
    assert "[confluence]" not in context
    assert "Plain content" in context

  def test_context_respects_token_limit (self):
    """Context stops adding chunks when estimated token limit is reached."""
    from proxy.app.core.context import build_context

    long_text = "x" * 4000  # ~1000 tokens
    chunks = [(
        {
            "text": long_text, "source_type": "test", "doc_title": "Long Doc", "title": "Section", "version": "1.0",
        }, 0.95,
    ) for _ in range (5)]
    context = build_context (chunks, max_tokens = 2500, include_metadata = False)
    assert len (context) < len (long_text) * 5

  def test_context_sorted_by_score_desc (self):
    """Chunks are ordered by score descending in the context."""
    from proxy.app.core.context import build_context

    chunks = [
        (
            {"text": "Medium relevance", "source_type": "test", "doc_title": "D", "title": "S", "version": "1.0"}, 0.50,
        ), ({"text": "High relevance", "source_type": "test", "doc_title": "D", "title": "S", "version": "1.0"}, 0.99),
        ({"text": "Low relevance", "source_type": "test", "doc_title": "D", "title": "S", "version": "1.0"}, 0.30),
    ]
    context = build_context (chunks, max_tokens = 100000, include_metadata = True)
    high_pos = context.find ("High relevance")
    medium_pos = context.find ("Medium relevance")
    low_pos = context.find ("Low relevance")
    assert high_pos < medium_pos < low_pos

  def test_empty_chunks_produce_empty_context (self):
    """Empty chunks list produces an empty context string."""
    from proxy.app.core.context import build_context

    context = build_context ([], max_tokens = 1000)
    assert context == ""


class TestFullContextAssemblyPipeline:
  """Tests for the prepare_context high-level function combining all steps."""

  def test_prepare_context_full_pipeline (self):
    """prepare_context runs deduplication -> version resolution -> context building."""
    from proxy.app.core.context import prepare_context

    chunks = [
        (
            {
                "text": "RAG v1 overview", "source_id": "rag_doc", "version": "1.0", "source_type": "confluence",
                "doc_title": "RAG", "title": "Overview",
            }, 0.80,
        ), (
            {
                "text": "RAG v1 overview", "source_id": "rag_doc", "version": "1.0", "source_type": "confluence",
                "doc_title": "RAG", "title": "Overview",
            }, 0.75,
        ),  # duplicate
        (
            {
                "text": "RAG v2 overview with updates", "source_id": "rag_doc", "version": "2.0",
                "source_type": "confluence", "doc_title": "RAG", "title": "Overview",
            }, 0.95,
        ), (
            {
                "text": "CI/CD setup guide", "source_id": "cicd_doc", "version": "3.1", "source_type": "gitlab",
                "doc_title": "CI/CD Guide", "title": "Setup",
            }, 0.88,
        ),
    ]
    context = prepare_context (chunks, requested_version = None, max_tokens = 100000)
    assert "RAG" in context
    assert "v2" in context
    assert "CI/CD" in context
    # The duplicate should have been removed
    assert context.count ("RAG v1 overview") <= 1

  def test_prepare_context_with_version_filter (self):
    """prepare_context respects requested_version for filtering."""
    from proxy.app.core.context import prepare_context

    chunks = [
        (
            {
                "text": "Old API v1", "source_id": "api_doc", "version": "1.0", "source_type": "confluence",
                "doc_title": "API", "title": "Endpoints",
            }, 0.90,
        ), (
            {
                "text": "New API v2", "source_id": "api_doc", "version": "2.0", "source_type": "confluence",
                "doc_title": "API", "title": "Endpoints",
            }, 0.85,
        ),
    ]
    context = prepare_context (chunks, requested_version = "1.0", max_tokens = 100000)
    assert "Old API v1" in context
    assert "New API v2" not in context


class TestExtractVersionFromQuery:
  """Tests for version extraction from user queries."""

  def test_extracts_semantic_version_v_prefix (self):
    """Extracts version like v2.0 from queries."""
    from proxy.app.core.context import extract_version_from_query

    assert extract_version_from_query ("Покажи документацию v2.0 про RAG") == "2.0"
    assert extract_version_from_query ("Используй v1.2.3 для поиска") == "1.2.3"

  def test_extracts_version_keyword (self):
    """Extracts version when specified with 'version' keyword."""
    from proxy.app.core.context import extract_version_from_query

    assert extract_version_from_query ("Документация version 3.1") == "3.1"
    assert extract_version_from_query ("Поиск version=4.0 по CI/CD") == "4.0"

  def test_extracts_date_as_version (self):
    """Extracts YYYY-MM-DD date as version string."""
    from proxy.app.core.context import extract_version_from_query

    assert extract_version_from_query ("Документация от 2025-06-01") == "2025-06-01"

  def test_no_version_returns_none (self):
    """Returns None when no version pattern is found."""
    from proxy.app.core.context import extract_version_from_query

    assert extract_version_from_query ("Расскажи про RAG") is None
    assert extract_version_from_query ("") is None

  def test_extracts_russian_version_keyword (self):
    """Extracts version with Russian 'версия' keyword."""
    from proxy.app.core.context import extract_version_from_query

    assert extract_version_from_query ("Покажи версия 5.2 документа") == "5.2"
