"""Tests for the BaseExtractor abstract class and data structures."""

import hashlib
from collections.abc import AsyncIterator

from etl.extractors.base_extractor import BaseExtractor, ExtractedDocument, ExtractorConfig


class TestExtractorConfig:
    def test_default_values(self):
        config = ExtractorConfig(
            source_name="test-source",
            source_type="book",
            base_url="/data/books",
        )
        assert config.source_name == "test-source"
        assert config.source_type == "book"
        assert config.base_url == "/data/books"
        assert config.api_token == ""
        assert config.max_pages == 1000
        assert config.batch_size == 50
        assert config.timeout == 30
        assert config.exclude_patterns == []

    def test_full_config(self):
        config = ExtractorConfig(
            source_name="wiki",
            source_type="confluence",
            base_url="https://wiki.example.com",
            api_token="secret-token",
            max_pages=500,
            batch_size=25,
            timeout=60,
            exclude_patterns=["/drafts", "/archived"],
        )
        assert config.api_token == "secret-token"
        assert config.max_pages == 500
        assert config.batch_size == 25
        assert config.timeout == 60
        assert config.exclude_patterns == ["/drafts", "/archived"]


class TestExtractedDocument:
    def test_minimal_creation(self):
        doc = ExtractedDocument(
            source_id="doc-1",
            source_type="confluence",
            title="Test Page",
            content="Some content",
            content_type="html",
        )
        assert doc.source_id == "doc-1"
        assert doc.source_type == "confluence"
        assert doc.title == "Test Page"
        assert doc.content == "Some content"
        assert doc.content_type == "html"
        assert doc.metadata == {}
        assert doc.access_level == "internal"
        assert doc.version == ""
        assert doc.links == []
        assert doc.extracted_at != ""

    def test_full_creation(self):
        doc = ExtractedDocument(
            source_id="doc-2",
            source_type="jira",
            title="PROJ-123",
            content="Issue description",
            content_type="html",
            metadata={"priority": "High", "status": "Open"},
            access_level="restricted",
            version="3",
            extracted_at="2025-06-01T00:00:00Z",
            links=[{"url": "https://example.com", "text": "ref"}],
        )
        assert doc.metadata["priority"] == "High"
        assert doc.access_level == "restricted"
        assert doc.version == "3"
        assert doc.extracted_at == "2025-06-01T00:00:00Z"
        assert len(doc.links) == 1

    def test_auto_extracted_at(self):
        doc = ExtractedDocument(source_id="d1", source_type="book", title="T", content="C", content_type="text")
        assert doc.extracted_at != ""
        assert "T" in doc.extracted_at or "+" in doc.extracted_at or "Z" in doc.extracted_at


class TestBaseExtractor:
    class _MockExtractor(BaseExtractor):
        def __init__(self, config):
            super().__init__(config)

        async def extract(self) -> AsyncIterator[ExtractedDocument]:
            yield ExtractedDocument(
                source_id="mock-1",
                source_type="mock",
                title="Mock",
                content="test",
                content_type="text",
            )
            return

        async def validate_connection(self) -> bool:
            return True

        def should_process(self, doc, last_hash):
            return True

    def test_compute_hash_deterministic(self):
        config = ExtractorConfig(source_name="test", source_type="test", base_url="url")
        ext = self._MockExtractor(config)
        h1 = ext.compute_hash("hello world")
        h2 = ext.compute_hash("hello world")
        assert h1 == h2
        assert len(h1) == 64

    def test_compute_hash_different(self):
        config = ExtractorConfig(source_name="test", source_type="test", base_url="url")
        ext = self._MockExtractor(config)
        h1 = ext.compute_hash("hello")
        h2 = ext.compute_hash("world")
        assert h1 != h2

    def test_compute_hash_empty(self):
        config = ExtractorConfig(source_name="test", source_type="test", base_url="url")
        ext = self._MockExtractor(config)
        h = ext.compute_hash("")
        expected = hashlib.sha256(b"").hexdigest()
        assert h == expected

    def test_extract_yields_documents(self):
        import asyncio

        config = ExtractorConfig(source_name="test", source_type="test", base_url="url")
        ext = self._MockExtractor(config)

        async def run():
            docs = []
            async for doc in ext.extract():
                docs.append(doc)
            return docs

        docs = asyncio.run(run())
        assert len(docs) == 1
        assert docs[0].source_id == "mock-1"

    def test_validate_connection(self):
        import asyncio

        config = ExtractorConfig(source_name="test", source_type="test", base_url="url")
        ext = self._MockExtractor(config)
        result = asyncio.run(ext.validate_connection())
        assert result is True

    def test_should_process(self):
        config = ExtractorConfig(source_name="test", source_type="test", base_url="url")
        ext = self._MockExtractor(config)
        doc = ExtractedDocument(source_id="d", source_type="t", title="t", content="c", content_type="text")
        assert ext.should_process(doc, "") is True

    def test_truncate_text(self):
        config = ExtractorConfig(source_name="test", source_type="test", base_url="url")
        ext = self._MockExtractor(config)
        long_text = "a" * 15000
        truncated = ext._truncate_text(long_text)
        assert len(truncated) == 10000 + 3  # 10000 + "..."
        assert truncated.endswith("...")

        short_text = "short"
        assert ext._truncate_text(short_text) == "short"
