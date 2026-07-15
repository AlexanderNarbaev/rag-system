"""Tests for the BookExtractor with mocked file parsing."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from etl.extractors.base_extractor import ExtractedDocument, ExtractorConfig
from etl.extractors.book_extractor import BookExtractor


@pytest.fixture
def book_config (tmp_path):
  return ExtractorConfig (source_name = "test-books", source_type = "book", base_url = str (tmp_path), )


@pytest.fixture
def mock_ebooklib ():
  """Fixture that fakes ebooklib being installed with proper epub attribute."""
  mock_epub = MagicMock ()
  mock_epub.ITEM_DOCUMENT = 9
  mock_module = MagicMock ()
  mock_module.epub = mock_epub
  mock_module.ITEM_DOCUMENT = 9
  with patch.dict (sys.modules, {"ebooklib": mock_module}):
    yield mock_epub


@pytest.fixture
def mock_pypdf ():
  """Fixture that fakes pypdf being installed."""
  mock_mod = MagicMock ()
  with patch.dict (sys.modules, {"pypdf": mock_mod}):
    yield mock_mod


@pytest.fixture
def mock_docx ():
  """Fixture that fakes python-docx being installed."""
  mock_mod = MagicMock ()
  with patch.dict (sys.modules, {"docx": mock_mod}):
    yield mock_mod


class TestBookExtractorInit:
  def test_init_with_config (self, book_config):
    ext = BookExtractor (book_config)
    assert ext.config.source_name == "test-books"
    assert ext.config.source_type == "book"
    assert ext._validated is False
    assert ext._source_files == []


class TestBookExtractorValidateConnection:
  def test_empty_directory (self, book_config, tmp_path):
    ext = BookExtractor (book_config)
    import asyncio

    result = asyncio.run (ext.validate_connection ())
    assert result is False

  def test_with_epub_file (self, book_config, tmp_path):
    epub_file = tmp_path / "test.epub"
    epub_file.write_text ("mock epub content")
    ext = BookExtractor (book_config)
    import asyncio

    result = asyncio.run (ext.validate_connection ())
    assert result is True
    assert len (ext._source_files) == 1

  def test_with_multiple_formats (self, book_config, tmp_path):
    (tmp_path / "book1.epub").write_text ("epub")
    (tmp_path / "book2.pdf").write_text ("pdf")
    (tmp_path / "book3.docx").write_text ("docx")
    (tmp_path / "ignore.txt").write_text ("not a book")
    ext = BookExtractor (book_config)
    import asyncio

    result = asyncio.run (ext.validate_connection ())
    assert result is True
    assert len (ext._source_files) == 3

  def test_exclude_patterns (self, tmp_path):
    config = ExtractorConfig (source_name = "test-books", source_type = "book", base_url = str (tmp_path),
        exclude_patterns = ["drafts"], )
    (tmp_path / "book.epub").write_text ("good")
    (tmp_path / "drafts").mkdir (parents = True, exist_ok = True)
    (tmp_path / "drafts" / "old.epub").write_text ("bad")
    ext = BookExtractor (config)
    import asyncio

    result = asyncio.run (ext.validate_connection ())
    assert result is True
    assert len (ext._source_files) == 1


class TestBookExtractorShouldProcess:
  def test_no_last_hash_returns_true (self, book_config):
    ext = BookExtractor (book_config)
    doc = ExtractedDocument (source_id = "d1", source_type = "book", title = "T", content = "C", content_type = "text")
    assert ext.should_process (doc, "") is True

  def test_same_hash_returns_false (self, book_config):
    ext = BookExtractor (book_config)
    doc = ExtractedDocument (source_id = "d1", source_type = "book", title = "T", content = "C", content_type = "text")
    h = ext.compute_hash ("C")
    assert ext.should_process (doc, h) is False

  def test_different_hash_returns_true (self, book_config):
    ext = BookExtractor (book_config)
    doc = ExtractedDocument (source_id = "d1", source_type = "book", title = "T", content = "C", content_type = "text")
    assert ext.should_process (doc, "otherhash") is True


class TestBookExtractorEPub:
  def test_extract_epub_minimal (self, book_config, tmp_path, mock_ebooklib):
    mock_book = MagicMock ()
    mock_book.get_metadata.return_value = [(("title",),)]
    mock_ebooklib.read_epub.return_value = mock_book

    mock_item = MagicMock ()
    mock_item.get_content.return_value = b"<h1>Chapter 1</h1><p>Hello world.</p>"
    mock_book.get_items_of_type.return_value = [mock_item]

    epub_file = tmp_path / "test.epub"
    ext = BookExtractor (book_config)
    import asyncio

    docs = asyncio.run (ext._extract_epub (epub_file))
    assert len (docs) >= 1
    assert docs [0].source_type == "book"
    assert docs [0].content_type == "text"
    assert "Chapter" in docs [0].title

  def test_extract_epub_no_headings (self, book_config, tmp_path, mock_ebooklib):
    mock_book = MagicMock ()
    mock_book.get_metadata.return_value = [(("title",),)]
    mock_ebooklib.read_epub.return_value = mock_book

    mock_item = MagicMock ()
    mock_item.get_content.return_value = b"<p>Just a paragraph, no headings.</p>"
    mock_book.get_items_of_type.return_value = [mock_item]

    epub_file = tmp_path / "nohead.epub"
    ext = BookExtractor (book_config)
    import asyncio

    docs = asyncio.run (ext._extract_epub (epub_file))
    assert len (docs) >= 1
    assert docs [0].content_type == "text"

  def test_extract_epub_no_library (self, book_config, tmp_path):
    epub_file = tmp_path / "test.epub"
    ext = BookExtractor (book_config)
    import asyncio

    docs = asyncio.run (ext._extract_epub (epub_file))
    assert docs == []


class TestBookExtractorPDF:
  def test_extract_pdf_with_content (self, book_config, tmp_path, mock_pypdf):
    mock_reader = MagicMock ()
    mock_page = MagicMock ()
    mock_page.extract_text.return_value = "PDF page content.\nMore text."
    mock_reader.pages = [mock_page, mock_page]
    mock_reader.metadata = {"/Title": "Test PDF", "/Author": "Author Name"}
    mock_pypdf.PdfReader.return_value = mock_reader

    pdf_file = tmp_path / "test.pdf"
    ext = BookExtractor (book_config)
    import asyncio

    docs = asyncio.run (ext._extract_pdf (pdf_file))
    assert len (docs) >= 1
    assert docs [0].source_type == "book"
    assert docs [0].metadata ["format"] == "pdf"
    assert docs [0].metadata ["book_title"] == "Test PDF"
    assert docs [0].metadata ["author"] == "Author Name"

  def test_extract_pdf_no_library (self, book_config, tmp_path):
    pdf_file = tmp_path / "test.pdf"
    ext = BookExtractor (book_config)
    import asyncio

    docs = asyncio.run (ext._extract_pdf (pdf_file))
    assert docs == []


class TestBookExtractorDocx:
  def test_extract_docx_with_headings (self, book_config, tmp_path, mock_docx):
    mock_core = MagicMock ()
    mock_core.title = "My Document"
    mock_core.author = "Author"
    mock_doc = MagicMock ()
    mock_doc.core_properties = mock_core

    para_heading = MagicMock ()
    para_heading.text = "Introduction"
    para_heading.style.name = "Heading 1"

    para_body = MagicMock ()
    para_body.text = "This is the body text."
    para_body.style.name = "Normal"

    mock_doc.paragraphs = [para_heading, para_body]
    mock_docx.Document.return_value = mock_doc

    docx_file = tmp_path / "test.docx"
    ext = BookExtractor (book_config)
    import asyncio

    docs = asyncio.run (ext._extract_docx (docx_file))
    assert len (docs) >= 1
    assert docs [0].source_type == "book"
    assert docs [0].metadata ["format"] == "docx"
    assert docs [0].metadata ["book_title"] == "My Document"

  def test_extract_docx_no_library (self, book_config, tmp_path):
    docx_file = tmp_path / "test.docx"
    ext = BookExtractor (book_config)
    import asyncio

    docs = asyncio.run (ext._extract_docx (docx_file))
    assert docs == []


class TestBookExtractorExtract:
  def test_extract_full_flow (self, book_config, tmp_path, mock_ebooklib):
    mock_book = MagicMock ()
    mock_book.get_metadata.return_value = [(("title",),)]
    mock_ebooklib.read_epub.return_value = mock_book
    mock_item = MagicMock ()
    mock_item.get_content.return_value = b"<h1>Chapter</h1><p>Text</p>"
    mock_book.get_items_of_type.return_value = [mock_item]

    (tmp_path / "book.epub").write_text ("epub")
    ext = BookExtractor (book_config)
    import asyncio

    async def collect ():
      await ext.validate_connection ()
      docs = []
      async for doc in ext.extract ():
        docs.append (doc)
      return docs

    docs = asyncio.run (collect ())
    assert len (docs) >= 1


class TestBookExtractorHelpers:
  def test_clean_html_with_bs4 (self, book_config):
    ext = BookExtractor (book_config)
    html = "<html><head><script>alert('x')</script></head><body><p>Hello</p><p>World</p></body></html>"
    result = ext._clean_html (html)
    assert "Hello" in result
    assert "World" in result
    assert "alert" not in result.lower () or "script" not in result.lower ()

  def test_clean_html_simple (self, book_config):
    ext = BookExtractor (book_config)
    html = "<p>Simple <b>bold</b> text</p>"
    result = ext._clean_html (html)
    assert "Simple" in result
    assert "bold" in result
    assert "text" in result

  def test_extract_headings (self, book_config):
    ext = BookExtractor (book_config)
    text = "# Title\nContent\n## Section 1\nSection text\n### Sub\nMore text"
    headings = ext._extract_headings (text)
    assert len (headings) == 3
    assert headings [0] == ("Title", 1, "Content")
    assert headings [1] == ("Section 1", 2, "Section text")
    assert headings [2] == ("Sub", 3, "More text")

  def test_extract_headings_empty (self, book_config):
    ext = BookExtractor (book_config)
    headings = ext._extract_headings ("Just plain text without headings.")
    assert headings == []

  def test_split_into_sections_chapter (self, book_config):
    ext = BookExtractor (book_config)
    text = "Chapter 1: Intro\nContent of chapter 1.\nChapter 2: Next\nContent of chapter 2."
    sections = ext._split_into_sections (text)
    assert len (sections) == 2
    assert sections [0] [0].startswith ("Chapter 1")
    assert "Content of chapter 1" in sections [0] [1]

  def test_split_into_sections_no_pattern (self, book_config):
    ext = BookExtractor (book_config)
    text = "Some text without any chapter patterns."
    sections = ext._split_into_sections (text)
    assert len (sections) == 1
    assert sections [0] [0] == ""

  def test_get_epub_metadata (self):
    mock_book = MagicMock ()
    mock_book.get_metadata.return_value = [("John Doe",)]
    result = BookExtractor._get_epub_metadata (mock_book, "creator")
    assert result == "John Doe"

  def test_get_epub_metadata_none (self):
    mock_book = MagicMock ()
    mock_book.get_metadata.return_value = []
    result = BookExtractor._get_epub_metadata (mock_book, "creator")
    assert result == ""

  def test_get_epub_identifier_isbn (self):
    mock_book = MagicMock ()
    mock_book.get_metadata.return_value = [("978-3-16-148410-0",)]
    result = BookExtractor._get_epub_identifier (mock_book)
    assert "978" in result

  def test_get_epub_identifier_none (self):
    mock_book = MagicMock ()
    mock_book.get_metadata.return_value = []
    result = BookExtractor._get_epub_identifier (mock_book)
    assert result == ""
