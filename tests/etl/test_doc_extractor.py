# ruff: noqa: E501, E402
"""Tests for etl/extractors/doc_extractor.py — doc extractor coverage."""

from unittest.mock import MagicMock

from etl.extractors.doc_extractor import DocExtractor


class TestDocExtractorInit:
    def test_supported_extensions(self):
        assert ".md" in DocExtractor.SUPPORTED_EXTENSIONS
        assert ".rst" in DocExtractor.SUPPORTED_EXTENSIONS
        assert ".adoc" in DocExtractor.SUPPORTED_EXTENSIONS


class TestParseMarkdownHeadings:
    def test_basic_headings(self):
        text = "# Title\n## Section 1\n### Subsection\n## Section 2"
        results = DocExtractor._parse_markdown_headings(text)
        assert len(results) >= 3
        assert results[0][0] == "Title"
        assert results[0][1] == 1

    def test_no_headings(self):
        text = "Just plain text\nNo headings here"
        results = DocExtractor._parse_markdown_headings(text)
        assert len(results) == 0

    def test_multiple_levels(self):
        text = "# H1\n## H2\n### H3\n#### H4"
        results = DocExtractor._parse_markdown_headings(text)
        assert len(results) == 4
        levels = [r[1] for r in results]
        assert levels == [1, 2, 3, 4]


class TestParseRstHeadings:
    def test_rst_headings(self):
        text = "Title\n=====\n\nSubtitle\n--------\n\nContent"
        results = DocExtractor._parse_rst_headings(text)
        assert len(results) >= 1

    def test_no_headings(self):
        text = "Just plain text"
        results = DocExtractor._parse_rst_headings(text)
        assert len(results) == 0


class TestExtractMarkdown:
    def test_with_headings(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)

        md_file = tmp_path / "test.md"
        md_file.write_text(
            "# Main Title\n\nSome content.\n\n## Section 1\n\nMore content.\n\n## Section 2\n\nEven more."
        )

        results = extractor._extract_markdown(md_file)
        assert len(results) >= 1

    def test_without_headings(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)

        md_file = tmp_path / "simple.md"
        md_file.write_text("Just some plain text content without any headings.")

        results = extractor._extract_markdown(md_file)
        assert len(results) == 1


class TestExtractRst:
    def test_basic_rst(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)

        rst_file = tmp_path / "test.rst"
        rst_file.write_text("Title\n=====\n\nContent here.\n\nSubtitle\n--------\n\nMore content.")

        results = extractor._extract_rst(rst_file)
        assert len(results) >= 1


class TestExtractAsciidoc:
    def test_basic_asciidoc(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)

        adoc_file = tmp_path / "test.adoc"
        adoc_file.write_text("= Main Title\n\nContent.\n\n== Section 1\n\nMore content.")

        results = extractor._extract_asciidoc(adoc_file)
        assert len(results) >= 1


class TestExtractGenericText:
    def test_plain_text(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)

        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("This is a plain text file.")

        results = extractor._extract_generic_text(txt_file)
        assert len(results) == 1
        assert results[0].title == "readme"
        assert results[0].content_type == "text"


class TestValidateConnection:
    def test_no_base_url(self):
        config = MagicMock()
        config.base_url = ""
        extractor = DocExtractor(config)
        import asyncio

        result = asyncio.run(extractor.validate_connection())
        assert result is False

    def test_nonexistent_dir(self):
        config = MagicMock()
        config.base_url = "/nonexistent/path/xyz"
        config.exclude_patterns = []
        extractor = DocExtractor(config)
        import asyncio

        result = asyncio.run(extractor.validate_connection())
        assert result is False

    def test_valid_dir_with_files(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)
        (tmp_path / "test.md").write_text("# Hello")
        import asyncio

        result = asyncio.run(extractor.validate_connection())
        assert result is True

    def test_empty_dir(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)
        import asyncio

        result = asyncio.run(extractor.validate_connection())
        assert result is False

    def test_exclude_patterns(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = ["node_modules"]
        extractor = DocExtractor(config)
        (tmp_path / "test.md").write_text("# Hello")
        sub = tmp_path / "node_modules"
        sub.mkdir()
        (sub / "ignored.md").write_text("# Ignored")
        import asyncio

        result = asyncio.run(extractor.validate_connection())
        assert result is True
        assert len(extractor._source_files) == 1


class TestExtract:
    def test_extract_markdown_files(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)
        (tmp_path / "doc.md").write_text("# Title\n\nContent here.")
        (tmp_path / "guide.md").write_text("# Guide\n\nGuide content.")
        import asyncio

        async def run():
            await extractor.validate_connection()
            docs = []
            async for doc in extractor.extract():
                docs.append(doc)
            return docs

        docs = asyncio.run(run())
        assert len(docs) >= 1

    def test_extract_mixed_formats(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)
        (tmp_path / "readme.md").write_text("# README")
        (tmp_path / "manual.rst").write_text("Title\n=====\nContent")
        (tmp_path / "notes.txt").write_text("Plain text notes")
        import asyncio

        async def run():
            await extractor.validate_connection()
            docs = []
            async for doc in extractor.extract():
                docs.append(doc)
            return docs

        docs = asyncio.run(run())
        assert len(docs) >= 2


class TestMakeDocument:
    def test_make_document(self, tmp_path):
        config = MagicMock()
        config.base_url = str(tmp_path)
        extractor = DocExtractor(config)
        file_path = tmp_path / "test.md"
        file_path.write_text("content")
        doc = extractor._make_document(
            file_path, "Test Title", "content", "markdown", 0, 1, ["code1"], ["table1"], ["link1"]
        )
        assert doc.title == "Test Title"
        assert doc.content == "content"
        assert doc.content_type == "markdown"
        assert doc.metadata["code_block_count"] == 1
        assert doc.metadata["table_count"] == 1
