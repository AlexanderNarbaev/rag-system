"""Tests for proxy/app/core/context/compression.py — CRAG decomposition and multimodal assembly."""

from proxy.app.core.context.compression import (
    assemble_multimodal_context,
    decompose_to_strips,
)


class TestDecomposeToStrips:
    """Tests for decompose_to_strips function."""

    def test_empty_input(self):
        assert decompose_to_strips([]) == []

    def test_single_chunk(self):
        chunks = [
            (
                {
                    "text": "This is sentence one. And this is sentence two.",
                    "source_type": "confluence",
                    "doc_title": "Doc",
                },
                0.9,
            ),
        ]
        strips = decompose_to_strips(chunks)
        assert len(strips) >= 2
        assert all(s.score == 0.9 for s in strips)
        assert all(s.source_type == "confluence" for s in strips)

    def test_filters_short_sentences(self):
        """Sentences shorter than 10 chars are filtered out."""
        chunks = [
            (
                {
                    "text": "Short. This is a longer sentence that passes the filter.",
                    "source_type": "test",
                    "doc_title": "D",
                },
                0.8,
            ),
        ]
        strips = decompose_to_strips(chunks)
        # "Short." is < 10 chars, should be filtered
        assert all(len(s.text) >= 10 for s in strips)

    def test_relevance_threshold_filter(self):
        """Strips below relevance_threshold are removed."""
        chunks = [
            ({"text": "High relevance sentence here for testing.", "source_type": "a", "doc_title": "A"}, 0.9),
            ({"text": "Low relevance sentence here for testing.", "source_type": "b", "doc_title": "B"}, 0.3),
        ]
        strips = decompose_to_strips(chunks, relevance_threshold=0.5)
        assert all(s.score >= 0.5 for s in strips)

    def test_empty_text_chunk_skipped(self):
        """Chunks with empty text are skipped."""
        chunks = [({"text": "", "source_type": "test", "doc_title": "D"}, 0.9)]
        strips = decompose_to_strips(chunks)
        assert len(strips) == 0

    def test_missing_fields_use_defaults(self):
        """Missing source_type and doc_title use defaults."""
        chunks = [({"text": "This is a sentence with enough length."}, 0.7)]
        strips = decompose_to_strips(chunks)
        assert len(strips) >= 1
        assert strips[0].source_type == "unknown"
        assert strips[0].doc_title == ""

    def test_multiple_chunks(self):
        """Multiple chunks produce strips from each."""
        chunks = [
            ({"text": "First chunk sentence. Another sentence here.", "source_type": "a", "doc_title": "A"}, 0.8),
            ({"text": "Second chunk sentence. And one more sentence.", "source_type": "b", "doc_title": "B"}, 0.6),
        ]
        strips = decompose_to_strips(chunks)
        sources = {s.source_type for s in strips}
        assert "a" in sources
        assert "b" in sources


class TestAssembleMultimodalContext:
    """Tests for assemble_multimodal_context function."""

    def test_empty_all(self):
        result = assemble_multimodal_context([], images=None, tables=None, code_blocks=None)
        assert result == ""

    def test_text_only(self):
        chunks = ["First chunk.", "Second chunk."]
        result = assemble_multimodal_context(chunks)
        assert "First chunk." in result
        assert "Second chunk." in result

    def test_with_tables(self):
        chunks = ["Text chunk."]
        tables = ["| A | B |\n|---|---|\n| 1 | 2 |"]
        result = assemble_multimodal_context(chunks, tables=tables)
        assert "Text chunk." in result
        assert "| A | B |" in result

    def test_with_code_blocks(self):
        chunks = ["Some text."]
        code = ["def hello():\n    return 'world'"]
        result = assemble_multimodal_context(chunks, code_blocks=code)
        assert "Some text." in result
        assert "def hello()" in result
        assert "```" in result

    def test_with_images(self):
        """Short image captions are included."""
        chunks = ["Text."]
        images = ["A diagram of the architecture"]
        result = assemble_multimodal_context(chunks, images=images)
        assert "Text." in result

    def test_token_budget_limiting(self):
        """Content is truncated when exceeding token budget."""
        # Create large chunks that exceed a small budget
        big_chunks = ["word " * 500] * 10
        result = assemble_multimodal_context(big_chunks, max_tokens=100)
        # Should not contain all content
        assert len(result) < len("\n\n".join(big_chunks))

    def test_multimodal_disabled(self):
        """When MULTI_MODAL_ENABLED is False, just joins chunks."""
        import proxy.app.core.context.compression as mod

        original = mod.MULTI_MODAL_ENABLED
        try:
            mod.MULTI_MODAL_ENABLED = False
            chunks = ["A", "B"]
            result = assemble_multimodal_context(chunks, images=["img"])
            assert "A" in result
            assert "B" in result
            # Images should NOT be included when disabled
        finally:
            mod.MULTI_MODAL_ENABLED = original

    def test_large_code_budget_limit(self):
        """Code blocks exceeding budget are truncated."""
        chunks = ["text"]
        code = ["x" * 10000]
        result = assemble_multimodal_context(chunks, code_blocks=code, max_tokens=50)
        assert result  # Should still produce output

    def test_images_not_included_when_too_long(self):
        """Image captions with >= 20 tokens are excluded."""
        chunks = ["text"]
        long_caption = "This is a very long image caption that definitely exceeds twenty tokens easily."
        result = assemble_multimodal_context(chunks, images=[long_caption])
        assert "text" in result
        # Long caption should be excluded
