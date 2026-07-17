"""Tests for etl/extractors/image_extractor.py — image extraction (FR-11)
and quality metrics (FR-12)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from etl.extractors.image_extractor import (
    BLIP_MODEL_NAME,
    CLIP_MODEL_NAME,
    ExtractedImage,
    ImageInfo,
    compute_image_caption_quality,
    embed_text,
    extract_images_from_pdf,
)
from etl.extractors.quality_metrics import (
    ExtractionQualityReport,
    ImageCaptionQualityMetrics,
    OCRQualityMetrics,
    TableQualityMetrics,
    build_quality_payload,
    compute_ocr_quality,
    compute_table_quality,
    save_quality_report,
)

# ── ImageInfo tests ───────────────────────────────────────────────────────────


class TestImageInfo:
    def test_creation_with_defaults(self):
        img = ImageInfo(src="/img/test.png", alt="Test image")
        assert img.src == "/img/test.png"
        assert img.alt == "Test image"
        assert img.caption == ""
        assert img.embedding == []

    def test_creation_with_caption(self):
        img = ImageInfo(src="photo.jpg", alt="Photo", caption="A beautiful photo")
        assert img.caption == "A beautiful photo"
        assert img.src == "photo.jpg"

    def test_creation_with_embedding(self):
        img = ImageInfo(src="x.png", alt="X", embedding=[0.1, 0.2, 0.3])
        assert img.embedding == [0.1, 0.2, 0.3]

    def test_equality(self):
        a = ImageInfo(src="a.png", alt="A")
        b = ImageInfo(src="a.png", alt="A")
        assert a == b

    def test_repr(self):
        img = ImageInfo(src="test.png", alt="Test")
        assert "ImageInfo" in repr(img)
        assert "test.png" in repr(img)


# ── CLIP/BLIP model configuration tests ───────────────────────────────────────


class TestModelConfig:
    def test_clip_model_name(self):
        assert "clip-vit" in CLIP_MODEL_NAME.lower() or "CLIP" in CLIP_MODEL_NAME.upper()

    def test_blip_model_name(self):
        assert "blip" in BLIP_MODEL_NAME.lower()


# ── embed_text tests ──────────────────────────────────────────────────────────


class TestEmbedText:
    def test_no_clip_model(self):
        with patch("etl.extractors.image_extractor._ensure_clip", return_value=(None, None)):
            assert embed_text("hello world") == []

    def test_with_model_no_crash(self):
        mock_model = MagicMock()
        mock_processor = MagicMock()

        tensor_mock = MagicMock()
        tensor_mock.__getitem__.return_value.cpu.return_value.tolist.return_value = [0.1, 0.2, 0.3]
        mock_model.get_text_features.return_value = tensor_mock

        with patch("etl.extractors.image_extractor._ensure_clip", return_value=(mock_model, mock_processor)):
            result = embed_text("test")
            assert result == [0.1, 0.2, 0.3]


# ── compute_image_caption_quality tests ───────────────────────────────────────


class TestImageCaptionQuality:
    def test_missing_image(self):
        assert compute_image_caption_quality("/nonexistent/img.png", "caption") == 0.0

    def test_no_clip_model(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_text("fake")
        with patch("etl.extractors.image_extractor.IMAGE_EXTRACTION_ENABLED", True), \
             patch("etl.extractors.image_extractor._ensure_clip", return_value=(None, None)):
            assert compute_image_caption_quality(str(img), "a cat") == 0.0


# ── extract_images_from_pdf (mocked) ──────────────────────────────────────────


class TestExtractImagesFromPdfMocked:
    def test_empty(self, tmp_path):
        pdf = tmp_path / "empty.pdf"
        pdf.write_text("%PDF")

        with patch("etl.extractors.image_extractor._extract_images_with_pdfplumber", return_value=[]), \
             patch("etl.extractors.image_extractor._extract_images_with_pymupdf", return_value=[]):
            assert extract_images_from_pdf(str(pdf)) == []

    def test_pdfplumber_extracts_images(self, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_text("%PDF-1.4")

        mock_result = [
            ExtractedImage(
                path="/tmp/img1.png",
                page_number=1,
                width=800,
                height=600,
                format="png",
            ),
        ]

        with patch(
            "etl.extractors.image_extractor._extract_images_with_pdfplumber",
            return_value=mock_result,
        ):
            results = extract_images_from_pdf(str(pdf))
            assert len(results) == 1
            assert results[0].page_number == 1
            assert results[0].format == "png"


# ── Quality metrics: OCRQualityMetrics ────────────────────────────────────────


class TestOCRQualityMetrics:
    def test_defaults(self):
        m = OCRQualityMetrics()
        assert m.page_count == 0
        assert m.avg_confidence == 0.0

    def test_to_dict(self):
        m = OCRQualityMetrics(
            page_count=5,
            pages_with_text=4,
            avg_confidence=85.5,
            min_confidence=60.0,
            max_confidence=99.0,
            total_chars=1000,
            ocr_enabled=True,
        )
        d = m.to_dict()
        assert d["page_count"] == 5
        assert d["avg_confidence"] == 85.5
        assert d["ocr_enabled"] is True


# ── Quality metrics: TableQualityMetrics ──────────────────────────────────────


class TestTableQualityMetrics:
    def test_defaults(self):
        m = TableQualityMetrics()
        assert m.total_tables == 0
        assert m.estimated_accuracy == 0.0

    def test_to_dict(self):
        m = TableQualityMetrics(
            total_tables=10,
            tables_with_rows=9,
            avg_rows_per_table=5.5,
            avg_columns_per_table=3.0,
            empty_tables=1,
            consistency_score=0.9,
            estimated_accuracy=0.85,
        )
        d = m.to_dict()
        assert d["total_tables"] == 10
        assert d["estimated_accuracy"] == 0.85


# ── Quality metrics: ImageCaptionQualityMetrics ───────────────────────────────


class TestImageCaptionQualityMetrics:
    def test_defaults(self):
        m = ImageCaptionQualityMetrics()
        assert m.total_images == 0

    def test_to_dict(self):
        m = ImageCaptionQualityMetrics(
            total_images=5,
            captioned_images=4,
            avg_clip_similarity=0.75,
            min_clip_similarity=0.5,
            max_clip_similarity=0.95,
            images_with_ocr=3,
            avg_ocr_confidence=82.0,
        )
        d = m.to_dict()
        assert d["avg_clip_similarity"] == 0.75
        assert d["images_with_ocr"] == 3


# ── compute_table_quality tests ───────────────────────────────────────────────


class TestComputeTableQuality:
    def test_empty_tables(self):
        result = compute_table_quality([])
        assert result.total_tables == 0
        assert result.estimated_accuracy == 0.0

    def test_single_well_formed_table(self):
        table = "| Name | Age |\n|------|-----|\n| John | 30  |\n| Jane | 25  |"
        result = compute_table_quality([table])
        assert result.total_tables == 1
        assert result.tables_with_rows == 1
        assert result.avg_rows_per_table > 0
        assert result.avg_columns_per_table > 0
        assert result.consistency_score == 1.0  # well-formed

    def test_empty_table(self):
        table = "| Header |\n|--------|"
        result = compute_table_quality([table])
        assert result.empty_tables >= 1

    def test_multiple_tables(self):
        tables = [
            "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |",
            "| X | Y | Z |\n|---|---|---|\n| a | b | c |",
        ]
        result = compute_table_quality(tables)
        assert result.total_tables == 2
        assert result.tables_with_rows == 2

    def test_malformed_table(self):
        table = "| A | B |\n| 1 | 2 | 3 |\n| 4 |"
        result = compute_table_quality([table])
        assert result.consistency_score < 1.0


# ── compute_ocr_quality tests ─────────────────────────────────────────────────


class TestComputeOCRQuality:
    def test_empty_results(self):
        result = compute_ocr_quality([])
        assert result.ocr_enabled
        assert result.page_count == 0

    def test_single_result(self):
        results = [{"text": "Hello World", "confidence": 85.0}]
        result = compute_ocr_quality(results)
        assert result.page_count == 1
        assert result.pages_with_text == 1
        assert result.avg_confidence == 85.0

    def test_multiple_results(self):
        results = [
            {"text": "Page 1", "confidence": 90.0},
            {"text": "", "confidence": 0.0},
            {"text": "Page 3", "confidence": 70.0},
        ]
        result = compute_ocr_quality(results)
        assert result.page_count == 3
        assert result.pages_with_text == 2
        assert result.avg_confidence == pytest.approx(53.33, rel=0.1)
        assert result.min_confidence == 0.0
        assert result.max_confidence == 90.0


# ── ExtractionQualityReport tests ─────────────────────────────────────────────


class TestExtractionQualityReport:
    def test_defaults(self):
        report = ExtractionQualityReport()
        assert report.document_id == ""
        assert report.overall_score() == 100.0  # nothing to score

    def test_overall_score_with_ocr(self):
        report = ExtractionQualityReport(
            document_id="doc1",
            source_type="pdf",
            ocr=OCRQualityMetrics(
                page_count=3,
                pages_with_text=3,
                avg_confidence=90.0,
                ocr_enabled=True,
            ),
        )
        assert 85 <= report.overall_score() <= 95

    def test_overall_score_with_tables(self):
        report = ExtractionQualityReport(
            document_id="doc2",
            source_type="md",
            tables=TableQualityMetrics(
                total_tables=5,
                tables_with_rows=4,
                estimated_accuracy=0.8,
            ),
        )
        assert 75 <= report.overall_score() <= 85

    def test_to_dict(self):
        report = ExtractionQualityReport(document_id="test", source_type="confluence")
        d = report.to_dict()
        assert d["document_id"] == "test"
        assert "ocr" in d
        assert "tables" in d
        assert "images" in d


# ── build_quality_payload tests ───────────────────────────────────────────────


class TestBuildQualityPayload:
    def test_payload_structure(self):
        report = ExtractionQualityReport(
            document_id="doc1",
            ocr=OCRQualityMetrics(
                page_count=2,
                pages_with_text=2,
                avg_confidence=88.0,
                ocr_enabled=True,
            ),
        )
        payload = build_quality_payload(report)
        assert "quality" in payload
        assert "overall_score" in payload["quality"]
        assert "ocr_avg_confidence" in payload["quality"]
        assert payload["quality"]["ocr_avg_confidence"] == 88.0


# ── save_quality_report tests ─────────────────────────────────────────────────


class TestSaveQualityReport:
    def test_empty_reports(self, tmp_path):
        output = tmp_path / "report.json"
        path = save_quality_report([], str(output))
        assert Path(path).exists()

    def test_with_reports(self, tmp_path):
        output = tmp_path / "quality.json"
        reports = [
            ExtractionQualityReport(
                document_id="doc1",
                source_type="pdf",
                ocr=OCRQualityMetrics(
                    page_count=2,
                    pages_with_text=2,
                    avg_confidence=90.0,
                    ocr_enabled=True,
                ),
            ),
        ]
        path = save_quality_report(reports, str(output))
        assert Path(path).exists()
        import json

        with open(path) as f:
            data = json.load(f)
        assert data["total_documents"] == 1
        assert "documents" in data
