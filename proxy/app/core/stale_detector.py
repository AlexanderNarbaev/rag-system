# proxy/app/core/stale_detector.py
"""Stale document detection for knowledge bases.

Detects documents whose freshness has expired based on per-source
thresholds and computes a staleness score (0-100). Integrates with
kb_manager and Qdrant for metadata lookup.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from proxy.app.shared.config import (
    STALE_CONFLUENCE_DAYS,
    STALE_GITLAB_DAYS,
    STALE_JIRA_DAYS,
)

logger = logging.getLogger(__name__)

SOURCE_FRESHNESS_DAYS: dict[str, int] = {
    "confluence": STALE_CONFLUENCE_DAYS,
    "jira": STALE_JIRA_DAYS,
    "gitlab": STALE_GITLAB_DAYS,
    "file": 365,
    "book": 365,
    "chat": 90,
    "default": 180,
}


def _get_freshness_days(source_type: str) -> int:
    return SOURCE_FRESHNESS_DAYS.get(source_type, SOURCE_FRESHNESS_DAYS["default"])


def get_staleness_score(doc: dict[str, Any]) -> float:
    """Compute staleness score (0-100) for a document.

    0 = fresh, 100 = way overdue.

    Uses `last_updated` or `created_at` timestamp and the per-source
    `expected_refresh_days` field if available, otherwise uses the
    default freshness threshold for the source type.
    """
    now = datetime.now(UTC).timestamp()
    payload = doc.get("payload", doc)

    ts = payload.get("last_updated") or payload.get("updated_at") or payload.get("created_at")
    if ts is None:
        return 50.0

    source_type = payload.get("source_type", "default")
    expected_days = payload.get("expected_refresh_days") or _get_freshness_days(source_type)

    age_days = max(0, (now - float(ts)) / 86400)
    if age_days <= 0:
        return 0.0

    staleness = (age_days / expected_days) * 100.0
    return min(100.0, max(0.0, staleness))


def is_stale(doc: dict[str, Any], threshold: float = 100.0) -> bool:
    """Check if a document is stale (score >= threshold)."""
    return get_staleness_score(doc) >= threshold


def detect_stale_documents(
    kb_id: str,
    kb_manager: Any,
    qdrant_client: Any,
    collection_name: str,
    threshold: float | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Find documents in a KB that are past their freshness threshold.

    Args:
        kb_id: Knowledge base ID.
        kb_manager: KnowledgeBaseManager instance.
        qdrant_client: Qdrant client instance.
        collection_name: Qdrant collection name for the KB.
        threshold: Minimum staleness score to include (default: 100, all stale).
        limit: Maximum number of documents to scan.

    Returns:
        List of dicts with `id`, `source_type`, `source_id`, `title`,
        `last_updated`, `staleness_score`, `expected_refresh_days`.
    """
    if threshold is None:
        threshold = 100.0

    if qdrant_client is None:
        logger.warning("Qdrant client not available — cannot detect stale documents")
        return []

    from qdrant_client.http import models

    stale_docs: list[dict[str, Any]] = []

    try:
        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="kb_id",
                        match=models.MatchValue(value=kb_id),
                    ),
                ],
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        logger.warning("Failed to query Qdrant for stale detection: %s", e)
        return []

    if not results:
        return []

    for point in results:
        payload = point.payload or {}
        score = get_staleness_score({"payload": payload})

        if score >= threshold:
            source_type = payload.get("source_type", "unknown")
            stale_docs.append(
                {
                    "id": point.id,
                    "source_type": source_type,
                    "source_id": payload.get("source_id", ""),
                    "title": payload.get("title") or payload.get("doc_title", ""),
                    "last_updated": payload.get("last_updated")
                    or payload.get("updated_at")
                    or payload.get("created_at"),
                    "staleness_score": round(score, 1),
                    "expected_refresh_days": payload.get("expected_refresh_days") or _get_freshness_days(source_type),
                }
            )

    stale_docs.sort(key=lambda d: d["staleness_score"], reverse=True)
    return stale_docs


def update_prometheus_metrics(kb_id: str, stale_count: int) -> None:
    """Update Prometheus gauge for stale document count."""
    try:
        from proxy.app.shared.metrics import rag_stale_documents

        rag_stale_documents.labels(kb_id=kb_id).set(stale_count)
    except Exception:
        pass
