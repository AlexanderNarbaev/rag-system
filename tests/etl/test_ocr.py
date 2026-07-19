"""Tests for etl/extractors/image_extractor.py — OCR pipeline (FR-09)."""

from unittest.mock import MagicMock, patch

from etl.extractors.image_extractor import (
    CLIP_MODEL_NAME,
    OCR_CONFIDENCE_THRESHOLD,
    OCR_ENABLED,
    OCR_LANGUAGES,
    ExtractedImage,
    OCRResult,
    caption_image,
    compute_cross_modal_similarity,
    embed_image,
    extract_images_from_html,
    extract_images_from_pdf,
    process_image_with_ocr,
    process_multi_page_ocr,
    process_pdf_with_ocr,
    search_images_by_text,
)

# ── OCRResult tests ───────────────────────────────────────────────────────────


class TestOCRResult:
    def test_creation(self):
        r = OCRResult(text="Hello", confidence=85.0, language="eng", page_number=1)
        assert r.text == "Hello"
        assert r.confidence == 85.0
        assert r.language == "eng"
        assert r.page_number == 1
        assert r.blocks == []
        assert r.metadata == {}

    def test_is_above_threshold_true(self):
        r = OCRResult(text="Good", confidence=80.0)
        assert r.is_above_threshold

    def test_is_above_threshold_false(self):
        r = OCRResult(text="Bad", confidence=40.0)
        assert not r.is_above_threshold

    def test_is_above_threshold_boundary(self):
        r = OCRResult(text="Edge", confidence=float(OCR_CONFIDENCE_THRESHOLD))
        assert r.is_above_threshold

    def test_default_values(self):
        r = OCRResult(text="", confidence=0.0)
        assert r.language == ""
        assert r.page_number == 0


class TestExtractedImage:
    def test_creation_defaults(self):
        img = ExtractedImage(path="/tmp/test.png")
        assert img.path == "/tmp/test.png"
        assert img.page_number == 0
        assert img.ocr_text == ""
        assert img.embedding == []

    def test_with_ocr(self):
        img = ExtractedImage(
            path="/tmp/test.png",
            page_number=3,
            ocr_text="Some text",
            ocr_confidence=92.0,
        )
        assert img.ocr_confidence == 92.0
        assert img.ocr_text == "Some text"


# ── extract_images_from_html tests ────────────────────────────────────────────


class TestExtractImagesFromHtml:
    def test_empty_html(self):
        assert extract_images_from_html("") == []

    def test_no_images(self):
        html = "<html><body><p>Hello world</p></body></html>"
        assert extract_images_from_html(html) == []

    def test_single_img(self):
        html = '<img src="photo.jpg" alt="A photo">'
        images = extract_images_from_html(html)
        assert len(images) == 1
        assert images[0].src == "photo.jpg"
        assert images[0].alt == "A photo"

    def test_multiple_images(self):
        html = '<img src="a.png" alt="A"><img src="b.jpg" alt="B">'
        images = extract_images_from_html(html)
        assert len(images) == 2
        assert images[0].src == "a.png"
        assert images[1].src == "b.jpg"

    def test_img_without_alt(self):
        html = '<img src="noalt.png">'
        images = extract_images_from_html(html)
        assert len(images) == 1
        assert images[0].src == "noalt.png"
        assert images[0].alt == ""

    def test_img_without_src_skipped(self):
        html = '<img alt="No source">'
        assert extract_images_from_html(html) == []

    def test_data_uri_skipped(self):
        html = '<img src="data:image/png;base64,abc123" alt="Inline">'
        assert extract_images_from_html(html) == []


# ── process_image_with_ocr tests (mocked) ─────────────────────────────────────


class TestProcessImageWithOcr:
    def test_disabled_returns_none(self):
        with patch("etl.extractors.image_extractor.OCR_ENABLED", False):
            assert process_image_with_ocr("/tmp/test.png") is None

    def test_missing_image_returns_none(self):
        assert process_image_with_ocr("/nonexistent/image.png") is None

    def test_non_image_returns_none(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("hello")
        assert process_image_with_ocr(str(txt_file)) is None

    def test_tesseract_primary(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_text("fake image")  # just so path exists

        mock_pt = MagicMock()
        mock_pt.Output.DICT = "dict"
        mock_pt.image_to_data.return_value = {
            "text": ["Hello", "World"],
            "conf": ["80", "90"],
        }
        mock_pt.image_to_string.return_value = "Hello World"

        with (
            patch("etl.extractors.image_extractor.OCR_ENABLED", True),
            patch("etl.extractors.image_extractor._ensure_pytesseract", return_value=mock_pt),
            patch("etl.extractors.image_extractor._ensure_pil", return_value=MagicMock()),
        ):
            result = process_image_with_ocr(str(img))
            assert result is not None
            assert "Hello" in result.text
            assert result.confidence > 0

    def test_easyocr_primary(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_text("fake")

        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [
            ([[0, 0], [100, 0], [100, 50], [0, 50]], "Hello", 0.95),
        ]

        with (
            patch("etl.extractors.image_extractor.OCR_ENABLED", True),
            patch("etl.extractors.image_extractor.OCR_PRIMARY_ENGINE", "easyocr"),
            patch("etl.extractors.image_extractor._ensure_easyocr", return_value=mock_reader),
        ):
            result = process_image_with_ocr(str(img))
            assert result is not None
            assert "Hello" in result.text


# ── process_multi_page_ocr tests ──────────────────────────────────────────────


class TestProcessMultiPageOcr:
    def test_empty_pages(self):
        results = process_multi_page_ocr([])
        assert results == []

    def test_disabled_returns_not_none(self):
        with patch("etl.extractors.image_extractor.OCR_ENABLED", False):
            results = process_multi_page_ocr(["page1.png"])
            assert len(results) == 1
            assert results[0].confidence == 0.0

    def test_page_numbers_assigned(self, tmp_path):
        img1 = tmp_path / "page1.png"
        img2 = tmp_path / "page2.png"
        img1.write_text("fake")
        img2.write_text("fake")

        mock_pt = MagicMock()
        mock_pt.Output.DICT = "dict"
        mock_pt.image_to_data.return_value = {"text": [], "conf": []}
        mock_pt.image_to_string.return_value = "Page text"

        with (
            patch("etl.extractors.image_extractor.OCR_ENABLED", True),
            patch("etl.extractors.image_extractor._ensure_pytesseract", return_value=mock_pt),
            patch("etl.extractors.image_extractor._ensure_pil", return_value=MagicMock()),
        ):
            results = process_multi_page_ocr([str(img1), str(img2)])
            assert len(results) == 2
            assert results[0].page_number == 1
            assert results[1].page_number == 2


# ── BLIP captioning tests (mocked) ────────────────────────────────────────────


class TestCaptionImage:
    def test_heuristic_fallback_without_model(self):
        caption = caption_image("/images/test_diagram.png")
        assert "test diagram" in caption.lower() or "test" in caption.lower()

    def test_returns_alt_based_caption(self):
        caption = caption_image("/images/test.png", alt_text="Architecture diagram")
        assert "Architecture" in caption

    def test_falls_back_to_generic(self):
        caption = caption_image("")
        assert len(caption) > 0


# ── CLIP embedding tests ──────────────────────────────────────────────────────


class TestEmbedImage:
    def test_disabled_returns_empty(self):
        with patch("etl.extractors.image_extractor.IMAGE_EXTRACTION_ENABLED", False):
            assert embed_image("/tmp/test.png") == []

    def test_missing_image_returns_empty(self):
        assert embed_image("/nonexistent/image.png") == []

    def test_no_clip_model_returns_empty(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_text("fake")
        with (
            patch("etl.extractors.image_extractor.IMAGE_EXTRACTION_ENABLED", True),
            patch("etl.extractors.image_extractor._ensure_clip", return_value=(None, None)),
        ):
            assert embed_image(str(img)) == []


# ── Cross-modal similarity tests ──────────────────────────────────────────────


class TestCrossModalSimilarity:
    def test_empty_embeddings(self):
        assert compute_cross_modal_similarity([], [1.0, 2.0]) == 0.0
        assert compute_cross_modal_similarity([1.0, 2.0], []) == 0.0

    def test_mismatched_dimensions(self):
        assert compute_cross_modal_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_identical_vectors(self):
        result = compute_cross_modal_similarity([0.6, 0.8], [0.6, 0.8])
        assert abs(result - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        result = compute_cross_modal_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(result - 0.0) < 1e-6

    def test_realistic_range(self):
        result = compute_cross_modal_similarity(
            [0.1, 0.2, 0.3, 0.4],
            [0.15, 0.25, 0.35, 0.45],
        )
        assert 0.9 < result <= 1.0


# ── search_images_by_text tests ───────────────────────────────────────────────


class TestSearchImagesByText:
    def test_no_client_returns_empty(self):
        assert search_images_by_text("query", "collection", qdrant_client=None) == []


# ── extract_images_from_pdf tests ─────────────────────────────────────────────


class TestExtractImagesFromPdf:
    def test_missing_pdf(self):
        assert extract_images_from_pdf("/nonexistent/test.pdf") == []

    def test_pdfplumber_fallback_to_pymupdf(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_text("%PDF-1.4 fake")

        mock_fitz_doc = MagicMock()
        mock_fitz_doc.__len__ = lambda s: 1
        mock_page = MagicMock()
        mock_page.get_images.return_value = []
        mock_fitz_doc.__getitem__ = lambda s, i: mock_page
        mock_fitz_doc.close = MagicMock()

        with (
            patch("etl.extractors.image_extractor._extract_images_with_pdfplumber", return_value=[]),
            patch("etl.extractors.image_extractor.fitz", create=True),
            patch("etl.extractors.image_extractor.fitz.open", return_value=mock_fitz_doc),
        ):
            results = extract_images_from_pdf(str(pdf))
            assert results == []


# ── process_pdf_with_ocr tests ────────────────────────────────────────────────


class TestProcessPdfWithOcr:
    def test_missing_pdf(self):
        assert process_pdf_with_ocr("/nonexistent/test.pdf") == []


# ── Configuration tests ───────────────────────────────────────────────────────


class TestConfiguration:
    def test_ocr_config_exists(self):
        assert isinstance(OCR_ENABLED, bool)
        assert isinstance(OCR_LANGUAGES, str)
        assert isinstance(OCR_CONFIDENCE_THRESHOLD, int)
        assert OCR_CONFIDENCE_THRESHOLD > 0

    def test_clip_model_name(self):
        assert "clip-vit" in CLIP_MODEL_NAME.lower()
