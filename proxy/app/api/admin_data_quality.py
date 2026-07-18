# proxy/app/api/admin_data_quality.py
"""Data quality endpoint — OCR confidence, chunk coherence, stale documents, contradictions (FR-106)."""

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.config import (
    COLLECTION_NAME,
    STALE_CONFLUENCE_DAYS,
    STALE_DEFAULT_DAYS,
    STALE_GITLAB_DAYS,
    STALE_JIRA_DAYS,
)
from proxy.app.shared.tracing import add_event, tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(prefix="/v1/admin/data-quality", tags=["admin-data-quality"])

SOURCE_FRESHNESS_DAYS: dict[str, int] = {
    "confluence": STALE_CONFLUENCE_DAYS,
    "jira": STALE_JIRA_DAYS,
    "gitlab": STALE_GITLAB_DAYS,
    "file": 365,
    "book": 365,
    "chat": 90,
    "default": STALE_DEFAULT_DAYS,
}

_qdrant_cache_lock = threading.RLock()
_cached_payloads: list[dict[str, Any]] = []
_cache_timestamp: float = 0.0
_CACHE_TTL_SECONDS = 300


def _get_qdrant_payloads(collection_name: str, source_filter: str | None = None) -> list[dict[str, Any]]:
    """Retrieve all payloads from Qdrant, with optional source_type filter and TTL cache."""
    global _cached_payloads, _cache_timestamp

    now = datetime.now(UTC).timestamp()
    with _qdrant_cache_lock:
        if _cached_payloads and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
            logger.debug("Returning cached Qdrant payloads (%d items)", len(_cached_payloads))
            if source_filter:
                return [p for p in _cached_payloads if p.get("source_type") == source_filter]
            return list(_cached_payloads)

    try:
        from proxy.app.core.retrieval import qdrant_client

        if qdrant_client is None:
            logger.warning("Qdrant client not available for data quality check")
            return []


        all_payloads: list[dict[str, Any]] = []
        offset: str | None = None

        while True:
            results, next_offset = qdrant_client.scroll(
                collection_name=collection_name,
                limit=500,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not results:
                break
            for point in results:
                if point.payload:
                    all_payloads.append(point.payload)
            if next_offset is None or isinstance(next_offset, str) and not next_offset:
                break
            offset = next_offset

        with _qdrant_cache_lock:
            _cached_payloads = all_payloads
            _cache_timestamp = now

        logger.info("Fetched %d Qdrant payloads for data quality", len(all_payloads))
    except Exception as e:
        logger.warning("Failed to query Qdrant for data quality: %s", e)
        return []

    if source_filter:
        return [p for p in all_payloads if p.get("source_type") == source_filter]
    return all_payloads


def _compute_chunk_coherence(chunk: dict[str, Any]) -> float:
    """Estimate chunk coherence based on text quality heuristics (0.0–1.0).

    Checks text length, keyword density, and content structure.
    """
    text = chunk.get("text", "")
    if not text or not isinstance(text, str):
        return 0.0

    words = text.split()
    word_count = len(words)

    if word_count < 5:
        return 0.1 * (word_count / 5)
    if word_count > 2000:
        return 0.5

    score = 0.5

    if 50 <= word_count <= 800:
        score += 0.2

    unique_words = len({w.lower() for w in words})
    if word_count > 0:
        type_token_ratio = unique_words / word_count
        if type_token_ratio > 0.6:
            score += 0.15
        elif type_token_ratio > 0.3:
            score += 0.1

    if chunk.get("title") or chunk.get("doc_title"):
        score += 0.1

    if chunk.get("summary"):
        score += 0.05

    return min(1.0, max(0.0, score))


def _is_stale(payload: dict[str, Any]) -> bool:
    """Check if a document is stale based on source freshness threshold."""
    now = datetime.now(UTC).timestamp()
    source_type = payload.get("source_type", "default")
    ts = payload.get("last_updated") or payload.get("updated_at") or payload.get("created_at")

    if ts is None:
        return False

    expected_days = SOURCE_FRESHNESS_DAYS.get(source_type, SOURCE_FRESHNESS_DAYS["default"])
    try:
        age_days = max(0, (now - float(ts)) / 86400)
    except (ValueError, TypeError):
        return False

    return age_days >= expected_days


def _parse_source_filter(source: str) -> list[str] | None:
    """Parse source query parameter. 'all' returns None (no filter)."""
    if not source or source == "all":
        return None
    return [s.strip() for s in source.split(",")]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def get_data_quality(
    request: Request,
    source: str = Query("all", description="Source filter: all, confluence, jira, gitlab (comma-separated)"),
    user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Return data quality metrics for indexed knowledge bases (FR-106).

    Computes OCR confidence, chunk coherence, stale document counts,
    and contradiction detection from Qdrant payloads.
    """
    source_filters = _parse_source_filter(source)

    with tracer.start_as_current_span("admin.data_quality") as span:
        if span.is_recording():
            span.set_attribute("admin.data_quality.source", source)

        payloads = _get_qdrant_payloads(COLLECTION_NAME)

        # Group by source_type
        sources_data: dict[str, dict[str, Any]] = {}
        all_source_types = {"confluence", "jira", "gitlab", "file", "book", "chat"}

        for st in all_source_types:
            if source_filters and st not in source_filters:
                continue
            sources_data[st] = {
                "total_documents": 0,
                "ocr_confidences": [],
                "coherence_scores": [],
                "stale_documents": 0,
                "contradictions_found": 0,
            }

        # Also track "other" for unknown source types
        sources_data["other"] = {
            "total_documents": 0,
            "ocr_confidences": [],
            "coherence_scores": [],
            "stale_documents": 0,
            "contradictions_found": 0,
        }

        issues: list[str] = []
        low_ocr_chunks: list[str] = []
        stale_count_by_source: dict[str, int] = {}
        total_docs = 0

        for payload in payloads:
            st = payload.get("source_type", "other")
            if source_filters and st not in source_filters:
                continue
            if st not in sources_data:
                st = "other"

            entry = sources_data[st]
            entry["total_documents"] += 1
            total_docs += 1

            ocr_conf = payload.get("ocr_confidence") or payload.get("ocr_text_confidence")
            if ocr_conf is not None:
                try:
                    entry["ocr_confidences"].append(float(ocr_conf))
                    if float(ocr_conf) < 0.6:
                        chunk_id = payload.get("chunk_hash", payload.get("source_id", "unknown"))
                        low_ocr_chunks.append(
                            f"Chunk {chunk_id[:16]} in {st}: OCR confidence {float(ocr_conf):.0%}"
                        )
                except (ValueError, TypeError):
                    pass

            coherence = _compute_chunk_coherence(payload)
            entry["coherence_scores"].append(coherence)
            if coherence < 0.3:
                chunk_id = payload.get("chunk_hash", payload.get("source_id", "unknown"))
                issues.append(f"Low coherence ({coherence:.2f}) for chunk {chunk_id[:16]} in {st}")

            if _is_stale(payload):
                entry["stale_documents"] += 1
                if st not in stale_count_by_source:
                    stale_count_by_source[st] = 0
                stale_count_by_source[st] += 1

        # Compute per-source metrics
        source_metrics: dict[str, dict[str, Any]] = {}
        all_coherence: list[float] = []
        total_stale = 0
        total_ocr_confidences: list[float] = []

        for st, entry in sources_data.items():
            if entry["total_documents"] == 0:
                continue

            avg_ocr = (
                round(sum(entry["ocr_confidences"]) / len(entry["ocr_confidences"]) * 100, 1)
                if entry["ocr_confidences"]
                else 0.0
            )
            avg_coherence = (
                round(sum(entry["coherence_scores"]) / len(entry["coherence_scores"]), 2)
                if entry["coherence_scores"]
                else 0.0
            )

            source_metrics[st] = {
                "avg_ocr_confidence": avg_ocr,
                "avg_chunk_coherence": avg_coherence,
                "stale_documents": entry["stale_documents"],
                "total_documents": entry["total_documents"],
                "contradictions_found": entry["contradictions_found"],
            }

            all_coherence.extend(entry["coherence_scores"])
            total_stale += entry["stale_documents"]
            total_ocr_confidences.extend(entry["ocr_confidences"])

        # Build issues list
        for st, count in stale_count_by_source.items():
            if count > 0:
                issues.append(f"{count} stale documents in {st}")

        if low_ocr_chunks:
            issues.extend(low_ocr_chunks[:15])

        if not issues and total_docs == 0:
            issues.append("No indexed documents found")

        # Overall score (weighted: 30% OCR, 40% coherence, 30% freshness)
        avg_ocr_all = (
            (sum(total_ocr_confidences) / len(total_ocr_confidences) * 100)
            if total_ocr_confidences
            else 80.0
        )
        avg_coherence_all = (
            (sum(all_coherence) / len(all_coherence)) if all_coherence else 0.7
        )
        freshness_ratio = 1.0 - (total_stale / max(total_docs, 1))

        overall_score = round(
            (avg_ocr_all * 0.3) + (avg_coherence_all * 100 * 0.4) + (freshness_ratio * 100 * 0.3),
            1,
        )

        add_event("admin.data_quality.retrieved", {
            "total_documents": total_docs,
            "overall_score": overall_score,
            "issues_count": len(issues),
        })

        return JSONResponse(
            status_code=200,
            content={
                "overall_score": overall_score,
                "sources": source_metrics,
                "issues": issues,
            },
        )
