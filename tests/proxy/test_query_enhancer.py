"""Tests for proxy/app/query_enhancer.py - query enhancement module."""
import pytest

from proxy.app.query_enhancer import QueryEnhancer


class TestQueryEnhancer:
    """Tests for QueryEnhancer."""

    def setup_method(self):
        self.enhancer = QueryEnhancer()

    def test_hyde_enhance_adds_prefix(self):
        result = self.enhancer.hyde_enhance("What is RAG?")
        assert "What is RAG?" in result
        assert len(result) > len("What is RAG?")

    def test_hyde_enhance_simple_query(self):
        result = self.enhancer.hyde_enhance("explain transformers")
        assert "explain transformers" in result
        assert "document" in result.lower() or "answer" in result.lower()

    def test_multi_query_expand_how_question(self):
        variants = self.enhancer.multi_query_expand("How to configure CI/CD pipeline?")
        assert any("steps" in v.lower() or "guide" in v.lower() for v in variants)
        assert len(variants) <= 4

    def test_multi_query_expand_what_question(self):
        variants = self.enhancer.multi_query_expand("What is Kubernetes?")
        assert any("definition" in v.lower() or "explain" in v.lower() for v in variants)

    def test_multi_query_expand_why_question(self):
        variants = self.enhancer.multi_query_expand("Why use microservices?")
        assert any("reason" in v.lower() or "cause" in v.lower() for v in variants)

    def test_multi_query_expand_vs_query(self):
        variants = self.enhancer.multi_query_expand("Docker vs Podman")
        assert any("difference between" in v.lower() or "comparison" in v.lower() for v in variants)

    def test_multi_query_expand_keyword_query(self):
        variants = self.enhancer.multi_query_expand("deploy applications kubernetes")
        assert len(variants) >= 2

    def test_multi_query_expand_deduplicates_variants(self):
        variants = self.enhancer.multi_query_expand("RAG", num_variants=10)
        assert len(variants) == len(set(variants))

    def test_multi_query_expand_respects_num_variants(self):
        variants = self.enhancer.multi_query_expand("Hello world", num_variants=1)
        assert len(variants) <= 2

    def test_decompose_complex_query_with_and(self):
        parts = self.enhancer.decompose_complex_query(
            "How to set up CI/CD and configure monitoring"
        )
        assert len(parts) > 1

    def test_decompose_complex_query_semicolon(self):
        parts = self.enhancer.decompose_complex_query(
            "How to deploy service; configure database; set up alerts"
        )
        assert len(parts) > 1

    def test_decompose_simple_query_returns_original(self):
        parts = self.enhancer.decompose_complex_query("What is RAG?")
        assert len(parts) == 1
        assert parts[0] == "What is RAG?"

    def test_extract_metadata_filters_version(self):
        filters = self.enhancer.extract_metadata_filters("Find me version 2.4 docs")
        assert "version" in filters
        assert "2.4" in filters["version"]

    def test_extract_metadata_filters_date(self):
        filters = self.enhancer.extract_metadata_filters("Show documents from 2024-01-15")
        assert "date" in filters
        assert filters["date"] == "2024-01-15"

    def test_extract_metadata_filters_author(self):
        filters = self.enhancer.extract_metadata_filters("Documents by John Doe about deployment")
        assert "author" in filters
        assert "John Doe" in filters["author"]

    def test_extract_metadata_filters_multiple(self):
        filters = self.enhancer.extract_metadata_filters(
            "Show me the specification for version 3.0 from 2024-06-01"
        )
        assert "version" in filters
        assert "date" in filters
        assert "type" in filters

    def test_extract_metadata_filters_empty(self):
        filters = self.enhancer.extract_metadata_filters("Hello world")
        assert filters == {}

    def test_extract_metadata_filters_project(self):
        filters = self.enhancer.extract_metadata_filters("What is the setup in the myapp project?")
        assert "project" in filters

    def test_enhance_returns_all_keys(self):
        result = self.enhancer.enhance("How to deploy microservices?")
        assert "hyde_query" in result
        assert "variants" in result
        assert "sub_queries" in result
        assert "metadata_filters" in result
        assert isinstance(result["variants"], list)
        assert isinstance(result["sub_queries"], list)
        assert isinstance(result["metadata_filters"], dict)
