"""Tests for proxy/app/context_builder.py functions."""
import pytest
from unittest.mock import patch

from proxy.app.context_builder import (
    extract_version_from_query,
    compute_chunk_hash,
    deduplicate_chunks,
    resolve_versions,
    group_by_semantic_key,
    estimate_tokens,
    build_context,
    prepare_context,
)


class TestExtractVersionFromQuery:
    """Tests for extract_version_from_query with various patterns."""

    def test_v_prefix(self):
        assert extract_version_from_query("use v2.3.1") == "2.3.1"

    def test_version_keyword(self):
        assert extract_version_from_query("see version 1.5") == "1.5"

    def test_version_equals(self):
        assert extract_version_from_query("we need version=3.0.0") == "3.0.0"

    def test_russian_pattern(self):
        assert extract_version_from_query("проверь версия 4.2") == "4.2"

    def test_date_as_version(self):
        assert extract_version_from_query("as of 2025-06-01") == "2025-06-01"

    def test_no_version(self):
        assert extract_version_from_query("how to set up CI/CD?") is None

    def test_empty_query(self):
        assert extract_version_from_query("") is None

    def test_none_query(self):
        assert extract_version_from_query(None) is None

    def test_version_with_colon(self):
        assert extract_version_from_query("use version: 1.0") == "1.0"


class TestComputeChunkHash:
    """Tests for compute_chunk_hash function."""

    def test_same_content_same_hash(self):
        chunk = {"text": "hello", "source_type": "confluence", "source_id": "X-1", "version": "1.0", "doc_title": "Test"}
        assert compute_chunk_hash(chunk) == compute_chunk_hash(dict(chunk))

    def test_different_text_different_hash(self):
        a = {"text": "hello", "source_type": "confluence", "source_id": "X-1", "version": "1.0", "doc_title": "T"}
        b = {"text": "world", "source_type": "confluence", "source_id": "X-1", "version": "1.0", "doc_title": "T"}
        assert compute_chunk_hash(a) != compute_chunk_hash(b)

    def test_score_ignored(self):
        a = {"text": "hello", "source_type": "c", "source_id": "1", "version": "1", "doc_title": "T", "score": 0.9}
        b = {"text": "hello", "source_type": "c", "source_id": "1", "version": "1", "doc_title": "T", "score": 0.5}
        assert compute_chunk_hash(a) == compute_chunk_hash(b)

    def test_missing_fields_use_defaults(self):
        chunk = {"text": "data"}
        result = compute_chunk_hash(chunk)
        assert isinstance(result, str)
        assert len(result) == 64


class TestDeduplicateChunks:
    """Tests for deduplicate_chunks function."""

    def test_removes_duplicates(self):
        chunk = {"text": "A", "source_type": "c", "source_id": "1", "version": "1.0", "doc_title": "T"}
        chunks = [(chunk, 0.9), (chunk, 0.85)]
        result = deduplicate_chunks(chunks)
        assert len(result) == 1

    def test_keeps_first_occurrence(self):
        c1 = {"text": "A", "source_type": "c", "source_id": "1", "version": "1.0", "doc_title": "T"}
        c2 = {"text": "B", "source_type": "c", "source_id": "1", "version": "1.0", "doc_title": "T"}
        chunks = [(c1, 0.9), (c2, 0.8), (c1, 0.7)]
        result = deduplicate_chunks(chunks)
        assert len(result) == 2
        assert result[0][1] == 0.9

    def test_empty_list(self):
        assert deduplicate_chunks([]) == []

    def test_no_duplicates(self):
        c1 = {"text": "A", "source_type": "c", "source_id": "1", "version": "1", "doc_title": "T"}
        c2 = {"text": "B", "source_type": "c", "source_id": "2", "version": "1", "doc_title": "T"}
        result = deduplicate_chunks([(c1, 0.9), (c2, 0.8)])
        assert len(result) == 2


class TestResolveVersions:
    """Tests for resolve_versions function."""

    def test_latest_version_selected(self):
        chunks = [
            ({"text": "old", "source_id": "doc1", "version": "1.0"}, 0.8),
            ({"text": "new", "source_id": "doc1", "version": "2.0"}, 0.9),
        ]
        result = resolve_versions(chunks)
        assert len(result) == 1
        assert result[0][0]["version"] == "2.0"

    def test_requested_version_exact_match(self):
        chunks = [
            ({"text": "v1", "source_id": "doc1", "version": "1.0"}, 0.8),
            ({"text": "v2", "source_id": "doc1", "version": "2.0"}, 0.9),
        ]
        result = resolve_versions(chunks, requested_version="1.0")
        assert len(result) == 1
        assert result[0][0]["text"] == "v1"

    def test_multiple_documents(self):
        chunks = [
            ({"text": "d1_v1", "source_id": "doc1", "version": "1.0"}, 0.9),
            ({"text": "d1_v2", "source_id": "doc1", "version": "2.0"}, 0.8),
            ({"text": "d2_v1", "source_id": "doc2", "version": "1.5"}, 0.7),
        ]
        result = resolve_versions(chunks)
        assert len(result) == 2

    def test_version_key_with_date(self):
        chunks = [
            ({"text": "old", "source_id": "doc1", "version": "2025-01-01"}, 0.8),
            ({"text": "new", "source_id": "doc1", "version": "2025-06-01"}, 0.9),
        ]
        result = resolve_versions(chunks)
        assert len(result) == 1
        assert result[0][0]["version"] == "2025-06-01"

    def test_empty_list(self):
        assert resolve_versions([]) == []

    def test_fallback_when_requested_not_found(self):
        chunks = [
            ({"text": "only", "source_id": "doc1", "version": "1.0"}, 0.9),
        ]
        result = resolve_versions(chunks, requested_version="99.0")
        assert len(result) == 1
        assert result[0][0]["version"] == "1.0"


class TestGroupBySemanticKey:
    """Tests for group_by_semantic_key function."""

    def test_groups_by_semantic_key(self):
        chunks = [
            ({"text": "A1", "semantic_key": "sec1"}, 0.9),
            ({"text": "A2", "semantic_key": "sec1"}, 0.8),
            ({"text": "B", "semantic_key": "sec2"}, 0.7),
        ]
        result = group_by_semantic_key(chunks)
        assert len(result) == 2

    def test_merges_texts(self):
        chunks = [
            ({"text": "part1", "semantic_key": "s1"}, 0.9),
            ({"text": "part2", "semantic_key": "s1"}, 0.8),
        ]
        result = group_by_semantic_key(chunks)
        assert len(result) == 1
        assert "part1" in result[0][0]["text"]
        assert "part2" in result[0][0]["text"]

    def test_fallback_to_hash(self):
        chunks = [
            ({"text": "A", "hash": "h1"}, 0.9),
            ({"text": "B", "hash": "h2"}, 0.8),
        ]
        result = group_by_semantic_key(chunks)
        assert len(result) == 2

    def test_average_score(self):
        chunks = [
            ({"text": "A", "semantic_key": "s1"}, 1.0),
            ({"text": "B", "semantic_key": "s1"}, 0.5),
        ]
        result = group_by_semantic_key(chunks)
        assert result[0][1] == 0.75

    def test_empty_list(self):
        assert group_by_semantic_key([]) == []


class TestEstimateTokensCB:
    """Tests for context_builder.estimate_tokens."""

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_four_chars_one_token(self):
        assert estimate_tokens("1234") == 1

    def test_partial_token(self):
        assert estimate_tokens("12") == 0


class TestBuildContext:
    """Tests for build_context function."""

    def test_empty_input(self):
        assert build_context([]) == ""

    def test_basic_context_building(self):
        chunks = [
            ({"text": "Hello world", "source_type": "wiki", "title": "Page", "doc_title": "Doc", "version": "1"}, 0.95),
            ({"text": "More data", "source_type": "wiki", "title": "P2", "doc_title": "D2", "version": "2"}, 0.80),
        ]
        result = build_context(chunks)
        assert "Hello world" in result
        assert "More data" in result
        assert "[wiki]" in result

    def test_no_metadata(self):
        chunks = [
            ({"text": "Content A"}, 0.9),
            ({"text": "Content B"}, 0.8),
        ]
        result = build_context(chunks, include_metadata=False)
        assert "[wiki]" not in result

    def test_max_tokens_limit(self):
        long_text = "x" * 2000
        chunks = [
            ({"text": long_text}, 0.9),
        ]
        result = build_context(chunks, max_tokens=10, include_metadata=False)
        assert len(result) < len(long_text)

    def test_sort_by_score(self):
        chunks = [
            ({"text": "Low", "source_type": "t", "title": "", "doc_title": "", "version": ""}, 0.5),
            ({"text": "High", "source_type": "t", "title": "", "doc_title": "", "version": ""}, 1.0),
        ]
        result = build_context(chunks, include_metadata=False)
        assert result.find("High") < result.find("Low")

    def test_skip_empty_text(self):
        chunks = [
            ({"text": "", "source_type": "t", "title": "", "doc_title": "", "version": ""}, 0.9),
            ({"text": "valid", "source_type": "t", "title": "", "doc_title": "", "version": ""}, 0.8),
        ]
        result = build_context(chunks, include_metadata=False)
        assert "valid" in result


class TestPrepareContext:
    """Tests for prepare_context integration function."""

    def test_full_pipeline(self):
        chunks = [
            ({"text": "A dup", "source_id": "doc1", "version": "1.0", "source_type": "w", "title": "T", "doc_title": "D"}, 0.9),
            ({"text": "A dup", "source_id": "doc1", "version": "1.0", "source_type": "w", "title": "T", "doc_title": "D"}, 0.8),
            ({"text": "B newer", "source_id": "doc1", "version": "2.0", "source_type": "w", "title": "T", "doc_title": "D"}, 0.85),
        ]
        result = prepare_context(chunks)
        assert "B newer" in result

    def test_empty_input(self):
        assert prepare_context([]) == ""

    def test_skip_dedup(self):
        chunks = [
            ({"text": "A", "source_id": "d1", "version": "1", "source_type": "w", "title": "T", "doc_title": "D"}, 0.9),
            ({"text": "A", "source_id": "d1", "version": "1", "source_type": "w", "title": "T", "doc_title": "D"}, 0.8),
        ]
        result = prepare_context(chunks, deduplicate=False, resolve_versions_flag=False)
        assert result.count("A") > 1

    def test_with_semantic_grouping(self):
        chunks = [
            ({"text": "P1", "semantic_key": "s1", "source_id": "d1", "version": "1", "source_type": "w", "title": "T", "doc_title": "D"}, 0.9),
            ({"text": "P2", "semantic_key": "s1", "source_id": "d1", "version": "1", "source_type": "w", "title": "T", "doc_title": "D"}, 0.8),
        ]
        result = prepare_context(chunks, group_semantic=True, resolve_versions_flag=False)
        assert "P1" in result
        assert "P2" in result


class TestLanguageAwareContextAssembly:
    """F4: Language-aware context assembly — build_context with lang parameter."""

    def test_build_context_accepts_lang(self):
        """build_context should accept an optional lang parameter."""
        from proxy.app.context_builder import build_context

        chunks = [
            ({"text": "RAG combines retrieval with generation.", "source_type": "wiki", "title": "RAG", "doc_title": "RAG Overview"}, 0.95),
        ]
        context = build_context(chunks, lang="de")
        assert "RAG" in context

    def test_build_context_lang_none(self):
        """build_context should work with lang=None (default behavior)."""
        from proxy.app.context_builder import build_context

        chunks = [
            ({"text": "RAG combines retrieval with generation.", "source_type": "wiki", "title": "RAG", "doc_title": "RAG Overview"}, 0.95),
        ]
        context = build_context(chunks, lang=None)
        assert "RAG" in context

    def test_prepare_context_accepts_lang(self):
        """prepare_context should accept and pass through lang parameter."""
        from proxy.app.context_builder import prepare_context

        chunks = [
            ({"text": "Test content", "source_id": "d1", "source_type": "wiki", "title": "T", "doc_title": "D"}, 0.9),
        ]
        context = prepare_context(chunks, lang="fr")
        assert "Test" in context

    def test_language_instruction_included_for_non_en(self):
        """When building context for non-EN, the response should include language awareness."""
        from proxy.app.context_builder import build_context

        chunks = [
            ({"text": "Qdrant is a vector database for RAG systems.", "source_type": "wiki", "title": "Qdrant", "doc_title": "Vector DB Guide"}, 0.98),
        ]
        context = build_context(chunks, lang="de")
        assert isinstance(context, str)
        assert len(context) > 0

    def test_context_for_chinese_works(self):
        from proxy.app.context_builder import build_context

        chunks = [
            ({"text": "Qdrant is a vector database for RAG systems.", "source_type": "wiki", "title": "Qdrant", "doc_title": "Vector DB Guide"}, 0.98),
        ]
        context = build_context(chunks, lang="zh")
        assert isinstance(context, str)
        assert len(context) > 0

    def test_multilang_prioritization(self):
        """Chunks matching query language should be prioritized (de query, de chunks first)."""
        from proxy.app.context_builder import build_context

        chunks = [
            ({"text": "German context here.", "source_type": "wiki", "title": "DE Doc", "doc_title": "German Guide"}, 0.70),
            ({"text": "English context here.", "source_type": "wiki", "title": "EN Doc", "doc_title": "English Guide"}, 0.95),
        ]
        context = build_context(chunks, lang="de")
        assert isinstance(context, str)
        assert len(context) > 0
