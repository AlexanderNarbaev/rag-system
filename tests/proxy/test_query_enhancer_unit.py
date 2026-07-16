# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/core/query_enhancer.py — query enhancement functions."""

from unittest.mock import MagicMock

from proxy.app.core.query_enhancer import (
    QueryEnhancer,
    generate_query_variants,
    multi_query_search,
)


class TestQueryEnhancer:
    """Tests for QueryEnhancer class."""

    def test_init(self):
        enhancer = QueryEnhancer()
        assert enhancer is not None

    def test_enhance(self):
        enhancer = QueryEnhancer()
        result = enhancer.enhance("RAG system")
        assert isinstance(result, dict)
        assert "variants" in result

    def test_decompose_complex_query_simple(self):
        enhancer = QueryEnhancer()
        result = enhancer.decompose_complex_query("What is RAG?")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_decompose_complex_query_compound(self):
        enhancer = QueryEnhancer()
        result = enhancer.decompose_complex_query("What is RAG and how does it work?")
        assert len(result) >= 1

    def test_decompose_complex_query_empty(self):
        enhancer = QueryEnhancer()
        result = enhancer.decompose_complex_query("")
        assert isinstance(result, list)

    def test_extract_metadata_filters(self):
        enhancer = QueryEnhancer()
        result = enhancer.extract_metadata_filters("search in confluence about CI/CD")
        assert isinstance(result, dict)

    def test_multi_query_expand(self):
        enhancer = QueryEnhancer()
        result = enhancer.multi_query_expand("RAG architecture")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_hyde_enhance(self):
        enhancer = QueryEnhancer()
        result = enhancer.hyde_enhance("What is RAG?")
        assert isinstance(result, (str, list))


class TestGenerateQueryVariants:
    """Tests for generate_query_variants."""

    def test_basic(self):
        variants = generate_query_variants("RAG architecture")
        assert len(variants) >= 1
        assert "RAG architecture" in variants  # original included

    def test_question_form(self):
        variants = generate_query_variants("set up CI/CD")
        assert any("?" in v for v in variants)

    def test_already_question(self):
        variants = generate_query_variants("what is RAG?")
        assert len(variants) >= 1

    def test_num_variants_limit(self):
        variants = generate_query_variants("test query", num_variants=2)
        assert len(variants) <= 3  # +1 for original

    def test_keywords_extracted(self):
        variants = generate_query_variants("the best RAG system for production")
        assert len(variants) >= 2


class TestMultiQuerySearch:
    """Tests for multi_query_search."""

    def _make_hit(self, id_, score):
        mock = MagicMock()
        mock.id = id_
        mock.score = score
        return mock

    def test_empty_results(self):
        mock_fn = MagicMock(return_value=[])
        result = multi_query_search("test", mock_fn)
        assert result == []

    def test_single_variant(self):
        hits = [self._make_hit("1", 0.9)]
        mock_fn = MagicMock(return_value=hits)
        result = multi_query_search("test", mock_fn, num_variants=1)
        assert len(result) >= 1

    def test_search_failure_graceful(self):
        """Search failures for variants are handled gracefully."""
        call_count = 0

        def failing_search(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("search failed")
            return [self._make_hit("1", 0.9)]

        result = multi_query_search("test", failing_search, num_variants=2)
        assert isinstance(result, list)

    def test_all_searches_fail(self):
        """Returns empty when all searches fail."""

        def failing_search(**kwargs):
            raise Exception("always fails")

        result = multi_query_search("test", failing_search, num_variants=1)
        assert result == []
