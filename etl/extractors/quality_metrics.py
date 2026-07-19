# etl/extractors/quality_metrics.py
"""FR-12: Extraction quality metrics for OCR, tables, and image captions.

Provides quality scoring that can be stored in chunk payloads and
exported as a JSON quality report.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OCRQualityMetrics:
    page_count: int = 0
    pages_with_text: int = 0
    avg_confidence: float = 0.0
    min_confidence: float = 0.0
    max_confidence: float = 0.0
    total_chars: int = 0
    ocr_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_count": self.page_count,
            "pages_with_text": self.page_count,
            "pages_with_ocr_text": self.pages_with_text,
            "avg_confidence": round(self.avg_confidence, 2),
            "min_confidence": round(self.min_confidence, 2),
            "max_confidence": round(self.max_confidence, 2),
            "total_chars": self.total_chars,
            "ocr_enabled": self.ocr_enabled,
        }


@dataclass
class TableQualityMetrics:
    total_tables: int = 0
    tables_with_rows: int = 0
    avg_rows_per_table: float = 0.0
    avg_columns_per_table: float = 0.0
    empty_tables: int = 0
    consistency_score: float = 0.0  # 0-1: how well-formed tables are
    estimated_accuracy: float = 0.0  # 0-1: estimated extraction accuracy

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tables": self.total_tables,
            "tables_with_rows": self.tables_with_rows,
            "empty_tables": self.empty_tables,
            "avg_rows_per_table": round(self.avg_rows_per_table, 2),
            "avg_columns_per_table": round(self.avg_columns_per_table, 2),
            "consistency_score": round(self.consistency_score, 2),
            "estimated_accuracy": round(self.estimated_accuracy, 2),
        }


@dataclass
class ImageCaptionQualityMetrics:
    total_images: int = 0
    captioned_images: int = 0
    avg_clip_similarity: float = 0.0
    min_clip_similarity: float = 0.0
    max_clip_similarity: float = 0.0
    images_with_ocr: int = 0
    avg_ocr_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_images": self.total_images,
            "captioned_images": self.captioned_images,
            "avg_clip_similarity": round(self.avg_clip_similarity, 4),
            "min_clip_similarity": round(self.min_clip_similarity, 4),
            "max_clip_similarity": round(self.max_clip_similarity, 4),
            "images_with_ocr": self.images_with_ocr,
            "avg_ocr_confidence": round(self.avg_ocr_confidence, 2),
        }


@dataclass
class ExtractionQualityReport:
    document_id: str = ""
    source_type: str = ""
    ocr: OCRQualityMetrics = field(default_factory=OCRQualityMetrics)
    tables: TableQualityMetrics = field(default_factory=TableQualityMetrics)
    images: ImageCaptionQualityMetrics = field(default_factory=ImageCaptionQualityMetrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_type": self.source_type,
            "ocr": self.ocr.to_dict(),
            "tables": self.tables.to_dict(),
            "images": self.images.to_dict(),
        }

    def overall_score(self) -> float:
        """Compute aggregate quality score (0-100)."""
        scores = []

        if self.ocr.ocr_enabled and self.ocr.page_count > 0:
            ocr_score = min(self.ocr.avg_confidence, 100.0)
            scores.append(ocr_score)

        if self.tables.total_tables > 0:
            table_score = self.tables.estimated_accuracy * 100
            scores.append(table_score)

        if self.images.total_images > 0:
            caption_score = self.images.avg_clip_similarity * 100
            scores.append(caption_score)

        if not scores:
            return 100.0  # No quality-sensitive content

        return sum(scores) / len(scores)


def compute_table_quality(table_texts: list[str]) -> TableQualityMetrics:
    """Analyze extracted tables for quality estimation.

    Checks row/column completeness and structural consistency.
    """
    if not table_texts:
        return TableQualityMetrics(total_tables=0)

    metrics = TableQualityMetrics(total_tables=len(table_texts))
    row_counts = []
    col_counts = []
    empty_count = 0

    for table in table_texts:
        lines = [ln.strip() for ln in table.splitlines() if ln.strip()]
        # Count data rows (skip separator rows like |---|)
        data_rows = [ln for ln in lines if not all(c in "|-: " for c in ln) and "|" in ln]

        if len(data_rows) <= 1:  # Only header or no rows
            empty_count += 1
            continue

        metrics.tables_with_rows += 1
        # Count columns from the row with most pipe characters
        for row in data_rows:
            cols = [c.strip() for c in row.split("|") if c.strip()]
            if len(cols) > 0:
                col_counts.append(len(cols))
        row_counts.append(len(data_rows))

    if row_counts:
        metrics.avg_rows_per_table = sum(row_counts) / len(row_counts)
    if col_counts:
        metrics.avg_columns_per_table = sum(col_counts) / len(col_counts)

    metrics.empty_tables = empty_count

    # Consistency: check that each table has consistent column count across rows
    consistency_scores = []
    for table in table_texts:
        lines = [ln.strip() for ln in table.splitlines() if ln.strip()]
        data_rows = [ln for ln in lines if not all(c in "|-: " for c in ln) and "|" in ln]
        if len(data_rows) < 2:
            consistency_scores.append(0.0)
            continue
        cols_per_row = []
        for row in data_rows:
            cols = [c.strip() for c in row.split("|") if c.strip()]
            if cols:
                cols_per_row.append(len(cols))
        if len(set(cols_per_row)) == 1 and len(cols_per_row) > 0:
            consistency_scores.append(1.0)
        elif len(cols_per_row) > 1:
            variation = max(cols_per_row) - min(cols_per_row) if cols_per_row else 1
            consistency_scores.append(max(0, 1.0 - variation / max(max(cols_per_row), 1)))
        else:
            consistency_scores.append(0.0)

    if consistency_scores:
        metrics.consistency_score = sum(consistency_scores) / len(consistency_scores)

    # Estimated accuracy: combination of structure + data presence
    structure_score = metrics.consistency_score
    data_score = metrics.tables_with_rows / max(metrics.total_tables, 1)
    metrics.estimated_accuracy = (structure_score + data_score) / 2

    return metrics


def compute_ocr_quality(ocr_results: list[dict[str, Any]]) -> OCRQualityMetrics:
    """Compute OCR quality from a list of per-page results."""
    if not ocr_results:
        return OCRQualityMetrics(ocr_enabled=True, page_count=0)

    confidences = [r.get("confidence", 0.0) for r in ocr_results]
    pages_with_text = sum(1 for r in ocr_results if r.get("text", "").strip())

    return OCRQualityMetrics(
        page_count=len(ocr_results),
        pages_with_text=pages_with_text,
        avg_confidence=sum(confidences) / len(confidences) if confidences else 0.0,
        min_confidence=min(confidences) if confidences else 0.0,
        max_confidence=max(confidences) if confidences else 0.0,
        total_chars=sum(len(r.get("text", "")) for r in ocr_results),
        ocr_enabled=True,
    )


def compute_image_caption_quality(
    similarity_scores: list[float],
    ocr_confidences: list[float],
    total_images: int,
    captioned_images: int,
) -> ImageCaptionQualityMetrics:
    """Compute image caption quality metrics from aggregated scores."""
    return ImageCaptionQualityMetrics(
        total_images=total_images,
        captioned_images=captioned_images,
        avg_clip_similarity=sum(similarity_scores) / len(similarity_scores) if similarity_scores else 0.0,
        min_clip_similarity=min(similarity_scores) if similarity_scores else 0.0,
        max_clip_similarity=max(similarity_scores) if similarity_scores else 0.0,
        images_with_ocr=len(ocr_confidences),
        avg_ocr_confidence=sum(ocr_confidences) / len(ocr_confidences) if ocr_confidences else 0.0,
    )


def build_quality_payload(report: ExtractionQualityReport) -> dict[str, Any]:
    """Create a compact quality payload for chunk metadata."""
    return {
        "quality": {
            "overall_score": round(report.overall_score(), 2),
            "ocr_avg_confidence": report.ocr.avg_confidence,
            "table_accuracy": report.tables.estimated_accuracy,
            "caption_clip_similarity": report.images.avg_clip_similarity,
        },
    }


def save_quality_report(reports: list[ExtractionQualityReport], output_path: str) -> str:
    """Save aggregated quality reports as JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    summaries = [r.to_dict() for r in reports]

    aggregate = {
        "generated_at": "",
        "total_documents": len(reports),
        "average_overall_score": (round(sum(r.overall_score() for r in reports) / len(reports), 2) if reports else 0.0),
        "average_ocr_confidence": (
            round(
                sum(r.ocr.avg_confidence for r in reports if r.ocr.page_count > 0)
                / max(sum(1 for r in reports if r.ocr.page_count > 0), 1),
                2,
            )
        ),
        "average_table_accuracy": (
            round(
                sum(r.tables.estimated_accuracy for r in reports if r.tables.total_tables > 0)
                / max(sum(1 for r in reports if r.tables.total_tables > 0), 1),
                2,
            )
        ),
        "average_caption_quality": (
            round(
                sum(r.images.avg_clip_similarity for r in reports if r.images.total_images > 0)
                / max(sum(1 for r in reports if r.images.total_images > 0), 1),
                4,
            )
        ),
        "documents": summaries,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(aggregate, f, ensure_ascii=False, indent=2)

    logger.info("Quality report saved: %s (%d documents)", path, len(reports))
    return str(path)
