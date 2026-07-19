"""Knowledge status determination for RAG responses.

Provides structured knowledge grounding status based on retrieval quality,
source count, and score thresholds.

FR-144: Updated taxonomy — "sufficient", "partial", "insufficient", "absent".
Old statuses ("grounded", "no_knowledge") are still accepted but log a
deprecation warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

STRONG_SCORE_THRESHOLD = 0.32
MIN_STRONG_SOURCES = 2

# Backward-compat mapping: old → new status names
_DEPRECATED_STATUS_MAP: dict[str, str] = {
    "grounded": "sufficient",
    "no_knowledge": "absent",
}


def normalize_knowledge_status(status: str) -> str:
    """Normalize a knowledge status string, mapping old names to new ones.

    Logs a deprecation warning when an old status name is encountered.
    """
    if status in _DEPRECATED_STATUS_MAP:
        new_status = _DEPRECATED_STATUS_MAP[status]
        logger.warning(
            "Deprecated knowledge status %r used — map to %r. "
            "Update callers to use the new taxonomy: "
            "sufficient, partial, insufficient, absent.",
            status,
            new_status,
        )
        return new_status
    return status


# Ensure old names are mapped for direct module-level usage.
deprecated_statuses = frozenset(_DEPRECATED_STATUS_MAP.keys())


@dataclass
class KnowledgeStatus:
    status: str  # "sufficient", "partial", "insufficient", "absent"
    source_count: int
    strong_source_count: int
    max_score: float
    reason: str


def determine_knowledge_status(
    sources: list[dict[str, Any]],
    should_generate: bool = True,
) -> KnowledgeStatus:
    """Determine the knowledge grounding status for a RAG response.

    FR-144 taxonomy:
    - "sufficient"  — >= 2 strong sources (was "grounded")
    - "insufficient" — 1 strong source, or sources present but generation refused
    - "partial"      — 0 strong sources, some borderline sources
    - "absent"       — 0 sources at all

    Args:
        sources: List of source dicts with 'relevance' or 'score' key.
        should_generate: Whether should_generate_answer() returned True.

    Returns:
        KnowledgeStatus with status, counts, and human-readable reason.
    """
    if not sources:
        return KnowledgeStatus(
            status="absent",
            source_count=0,
            strong_source_count=0,
            max_score=0.0,
            reason="No relevant sources found in the knowledge base.",
        )

    if not should_generate:
        return KnowledgeStatus(
            status="insufficient",
            source_count=len(sources),
            strong_source_count=0,
            max_score=0.0,
            reason="Insufficient source quality to generate a reliable answer.",
        )

    scores = [s.get("relevance", s.get("score", 0.0)) for s in sources]
    strong_count = sum(1 for s in scores if s >= STRONG_SCORE_THRESHOLD)
    max_score = max(scores) if scores else 0.0

    if strong_count >= MIN_STRONG_SOURCES:
        return KnowledgeStatus(
            status="sufficient",
            source_count=len(sources),
            strong_source_count=strong_count,
            max_score=max_score,
            reason=f"Answer is grounded in {len(sources)} source(s) ({strong_count} strong).",
        )

    if strong_count >= 1:
        return KnowledgeStatus(
            status="insufficient",
            source_count=len(sources),
            strong_source_count=strong_count,
            max_score=max_score,
            reason=(f"Only {strong_count} strong source(s) from {len(sources)} — answer may be unreliable."),
        )

    # 0 strong sources, but sources exist
    return KnowledgeStatus(
        status="partial",
        source_count=len(sources),
        strong_source_count=0,
        max_score=max_score,
        reason=(f"No strong sources from {len(sources)} — answer may be incomplete or uncertain."),
    )
