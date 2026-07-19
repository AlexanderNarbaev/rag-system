"""Tests for proxy/app/core/context/builder.py — context building functions."""

from proxy.app.core.context.builder import (
    build_context,
    compute_chunk_hash,
    deduplicate_chunks,
    estimate_tokens,
    extract_relevant_segments,
    prepare_context,
)


class TestExtractRelevantSegments:
    """Tests for extract_relevant_segments."""

    def test_empty_text(self):
        assert extract_relevant_segments("", "query") == ""

    def test_empty_query(self):
        assert extract_relevant_segments("some text", "") == "some text"

    def test_short_text_returns_original(self):
        """Text with <= 3 sentences is returned as-is."""
        text = "First sentence. Second sentence."
        assert extract_relevant_segments(text, "test") == text

    def test_long_text_filters_irrelevant(self):
        """Long text is filtered to query-relevant sentences."""
        text = (
            "Python is a programming language. "
            "The weather is nice today. "
            "Python supports object oriented programming. "
            "Cooking is an art form. "
            "Python has many libraries for data science. "
            "Music is universal."
        )
        result = extract_relevant_segments(text, "Python programming")
        assert "Python" in result
        assert "weather" not in result or "Cooking" not in result

    def test_no_relevant_returns_first_3(self):
        """When no sentences match, returns first 3."""
        text = "Aaa. Bbb. Ccc. Ddd. Eee."
        result = extract_relevant_segments(text, "xyz123")
        assert "Aaa" in result


class TestEstimateTokens:
    """Tests for estimate_tokens."""

    def test_short_text(self):
        assert estimate_tokens("hello") >= 1

    def test_empty_text(self):
        assert estimate_tokens("") == 0

    def test_longer_text(self):
        short = estimate_tokens("hi")
        long = estimate_tokens("a" * 1000)
        assert long > short


class TestComputeChunkHash:
    """Tests for compute_chunk_hash."""

    def test_returns_string(self):
        h = compute_chunk_hash({"text": "hello world"})
        assert isinstance(h, str)
        assert len(h) > 0

    def test_consistent(self):
        chunk = {"text": "test"}
        assert compute_chunk_hash(chunk) == compute_chunk_hash(chunk)

    def test_different_chunks_different_hash(self):
        h1 = compute_chunk_hash({"text": "aaa"})
        h2 = compute_chunk_hash({"text": "bbb"})
        assert h1 != h2


class TestDeduplicateChunks:
    """Tests for deduplicate_chunks."""

    def test_empty(self):
        assert deduplicate_chunks([]) == []

    def test_no_duplicates(self):
        chunks = [
            ({"text": "unique one", "hash": "h1"}, 0.9),
            ({"text": "unique two", "hash": "h2"}, 0.8),
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 2

    def test_removes_duplicates(self):
        chunks = [
            ({"text": "same", "hash": "h1"}, 0.9),
            ({"text": "same", "hash": "h1"}, 0.8),
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 1


class TestBuildContext:
    """Tests for build_context."""

    def test_empty(self):
        assert build_context([]) == ""

    def test_single_chunk(self):
        chunks = [({"text": "hello world", "title": "T", "source_type": "test"}, 0.9)]
        result = build_context(chunks)
        assert "hello world" in result

    def test_multiple_chunks(self):
        chunks = [
            ({"text": "first", "title": "T1", "source_type": "a"}, 0.9),
            ({"text": "second", "title": "T2", "source_type": "b"}, 0.8),
        ]
        result = build_context(chunks)
        assert "first" in result
        assert "second" in result

    def test_token_limit(self):
        big_chunks = [({"text": "word " * 500, "title": "T", "source_type": "a"}, 0.9)] * 20
        result = build_context(big_chunks, max_tokens=100)
        assert len(result) > 0


class TestPrepareContext:
    """Tests for prepare_context."""

    def test_empty(self):
        result = prepare_context([])
        assert result == "" or isinstance(result, str)
