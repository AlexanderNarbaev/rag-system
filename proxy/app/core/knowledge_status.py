"""Knowledge status determination for RAG responses.

Provides structured knowledge grounding status based on retrieval quality,
source count, and score thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STRONG_SCORE_THRESHOLD = 0.32
MIN_STRONG_SOURCES = 2


@dataclass
class KnowledgeStatus:
    status: str  # "grounded", "partial", "no_knowledge"
    source_count: int
    strong_source_count: int
    max_score: float
    reason: str


def determine_knowledge_status(
    sources: list[dict[str, Any]],
    should_generate: bool = True,
) -> KnowledgeStatus:
    """Determine the knowledge grounding status for a RAG response.

    Args:
        sources: List of source dicts with 'relevance' or 'score' key.
        should_generate: Whether should_generate_answer() returned True.

    Returns:
        KnowledgeStatus with status, counts, and human-readable reason.
    """
    if not sources or not should_generate:
        return KnowledgeStatus(
            status="no_knowledge",
            source_count=len(sources),
            strong_source_count=0,
            max_score=0.0,
            reason="No relevant sources found in the knowledge base."
            if not sources
            else "Insufficient source quality to generate a reliable answer.",
        )

    scores = [s.get("relevance", s.get("score", 0.0)) for s in sources]
    strong_count = sum(1 for s in scores if s >= STRONG_SCORE_THRESHOLD)
    max_score = max(scores) if scores else 0.0

    if strong_count >= MIN_STRONG_SOURCES:
        return KnowledgeStatus(
            status="grounded",
            source_count=len(sources),
            strong_source_count=strong_count,
            max_score=max_score,
            reason=f"Answer is grounded in {len(sources)} source(s) ({strong_count} strong).",
        )

    if len(sources) > 0:
        return KnowledgeStatus(
            status="partial",
            source_count=len(sources),
            strong_source_count=strong_count,
            max_score=max_score,
            reason=(
                f"Only {strong_count} strong source(s) from {len(sources)} — answer may be incomplete or uncertain."
            ),
        )

    return KnowledgeStatus(
        status="no_knowledge",
        source_count=0,
        strong_source_count=0,
        max_score=0.0,
        reason="No usable sources found.",
    )
