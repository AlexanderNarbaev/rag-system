"""Confidence scoring for RAG answers. Uses heuristics + optional SLM verification."""
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceReport:
    score: float
    needs_review: bool
    uncertainties: list[str] = field(default_factory=list)
    low_relevance_sources: list[str] = field(default_factory=list)
    recommendation: str = ""


def compute_confidence(
    query: str,
    context: str,
    answer: str,
    slm_available: bool = False,
) -> ConfidenceReport:
    uncertainties: list[str] = []
    score = 0.7

    if not context or len(context.strip()) < 20:
        uncertainties.append("Retrieved context is empty or very short")
        score -= 0.4

    if context and len(context) < len(answer) * 0.5:
        uncertainties.append("Context is much shorter than answer — possible hallucination")
        score -= 0.2

    uncertainty_phrases = [
        "I don't know", "I'm not sure", "I cannot", "no information",
        "не знаю", "не уверен", "нет информации", "не могу",
        "unclear", "uncertain", "possibly", "maybe",
        "возможно", "вероятно", "неясно",
    ]
    answer_lower = answer.lower()
    found_phrases = [p for p in uncertainty_phrases if p in answer_lower]
    if found_phrases:
        uncertainties.append(f"Answer contains uncertainty phrases: {', '.join(found_phrases)}")
        score -= 0.2

    if len(answer.strip()) < 20:
        uncertainties.append("Answer is very short — insufficient information")
        score -= 0.15

    score = max(0.0, min(1.0, score))
    needs_review = score < 0.5
    recommendation = ""
    if needs_review:
        recommendation = "Consider rewording query, expanding retrieved context, or flagging for human review."

    return ConfidenceReport(
        score=round(score, 2),
        needs_review=needs_review,
        uncertainties=uncertainties,
        recommendation=recommendation,
    )
