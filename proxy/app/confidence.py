"""Confidence scoring for RAG answers. Uses heuristics + NLI grounding + calibration."""
import logging
import math
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceReport:
    score: float
    needs_review: bool
    uncertainties: list[str] = field(default_factory=list)
    low_relevance_sources: list[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class GroundingReport:
    score: float
    supported_claims: int
    total_claims: int
    unsupported: list[str] = field(default_factory=list)


# ── F1: NLI-based Grounding Checker ──


def decompose_into_claims(answer: str) -> list[str]:
    """Decompose answer text into atomic claims using sentence splitting."""
    if not answer or not answer.strip():
        return []

    parts = re.split(r"(?<=[.!?])\s+|\n|(?<=;)\s+", answer.strip())
    claims = []
    for part in parts:
        stripped = part.strip().rstrip(";.")
        stripped = re.sub(r"^[-*•]\s*", "", stripped).strip()
        if len(stripped) >= 10:
            claims.append(stripped)
    return claims


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase word set for overlap computation."""
    return set(re.findall(r"\w+", text.lower()))


def _compute_cosine_proxy(text_a: str, text_b: str) -> float:
    """Lightweight cosine similarity proxy using word overlap."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / math.sqrt(len(tokens_a) * len(tokens_b))


def _check_claim_supported(claim: str, context: str) -> bool:
    """Check if a claim is supported by context using cosine + keyword overlap."""
    if not context or not context.strip():
        return False

    claim_tokens = _tokenize(claim)
    if not claim_tokens:
        return False

    cosine_score = _compute_cosine_proxy(claim, context)

    context_tokens = _tokenize(context)
    keyword_overlap = len(claim_tokens & context_tokens) / len(claim_tokens)

    combined = 0.5 * cosine_score + 0.5 * keyword_overlap
    return combined >= 0.25


def compute_nli_grounding(answer: str, context: str) -> GroundingReport:
    """Compute NLI-grounded confidence by checking each claim against context.

    Uses lightweight cosine similarity + keyword overlap as NLI proxy
    (no external NLI model needed — air-gapped compatible).

    Returns a GroundingReport with score 0.0–1.0 and unsupported claims list.
    """
    if not answer or not answer.strip():
        return GroundingReport(score=0.0, supported_claims=0, total_claims=0, unsupported=[])

    claims = decompose_into_claims(answer)
    if not claims:
        return GroundingReport(score=0.0, supported_claims=0, total_claims=0, unsupported=[])

    if not context or not context.strip():
        return GroundingReport(
            score=0.0, supported_claims=0, total_claims=len(claims), unsupported=list(claims)
        )

    supported = 0
    unsupported = []
    for claim in claims:
        if _check_claim_supported(claim, context):
            supported += 1
        else:
            unsupported.append(claim)

    score = supported / len(claims) if claims else 0.0
    return GroundingReport(
        score=round(score, 3),
        supported_claims=supported,
        total_claims=len(claims),
        unsupported=unsupported,
    )


# ── F6: Confidence Threshold Calibration ──


def calibrate_threshold(test_cases: list[tuple[float, bool]]) -> float:
    """Given labeled test cases (score, is_correct), find optimal threshold maximizing F1.

    If no cases, returns the current CONFIDENCE_THRESHOLD as fallback.
    """
    if not test_cases:
        from proxy.app.config import CONFIDENCE_THRESHOLD
        return CONFIDENCE_THRESHOLD

    candidates = [c[0] for c in test_cases]
    best_f1 = 0.0
    best_threshold = 0.5

    for candidate in candidates:
        tp = fn = fp = tn = 0
        for score, is_correct in test_cases:
            predicted_ok = score >= candidate
            if predicted_ok and is_correct:
                tp += 1
            elif predicted_ok and not is_correct:
                fp += 1
            elif not predicted_ok and is_correct:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        if f1 > best_f1:
            best_f1 = f1
            best_threshold = candidate
        elif f1 == best_f1 and candidate < best_threshold:
            best_threshold = candidate

    # Also try midpoints between sorted candidates
    sorted_candidates = sorted(set(candidates))
    for i in range(len(sorted_candidates) - 1):
        mid = (sorted_candidates[i] + sorted_candidates[i + 1]) / 2
        tp = fn = fp = tn = 0
        for score, is_correct in test_cases:
            predicted_ok = score >= mid
            if predicted_ok and is_correct:
                tp += 1
            elif predicted_ok and not is_correct:
                fp += 1
            elif not predicted_ok and is_correct:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        if f1 > best_f1:
            best_f1 = f1
            best_threshold = mid

    return round(best_threshold, 3)


# ── Main confidence function ──


def compute_confidence(
    query: str,
    context: str,
    answer: str,
    slm_available: bool = False,
) -> ConfidenceReport:
    uncertainties: list[str] = []
    score = 0.7
    nli_score = None

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

    # F1: NLI grounding integration
    try:
        from proxy.app.config import NLI_GROUNDING_ENABLED
    except ImportError:
        NLI_GROUNDING_ENABLED = True

    if NLI_GROUNDING_ENABLED and answer.strip() and context.strip():
        nli_report = compute_nli_grounding(answer, context)
        nli_score = nli_report.score
        if nli_report.unsupported:
            unsupported_preview = nli_report.unsupported[:3]
            uncertainties.append(
                f"NLI: {nli_report.supported_claims}/{nli_report.total_claims} claims grounded. "
                f"Unsupported: {unsupported_preview}"
            )
        score = 0.6 * score + 0.4 * nli_score

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


# ── F2: CRAG Retrieval Quality Evaluator ──


@dataclass
class RetrievalQualityReport:
    classification: str  # "Correct", "Incorrect", "Ambiguous"
    correct_count: int
    incorrect_count: int
    ambiguous_count: int
    total_count: int
    correct_rate: float
    recommendations: list[str] = field(default_factory=list)


def _score_chunk_relevance(query: str, chunk_text: str) -> float:
    """Score a single chunk's relevance to the query using keyword overlap."""
    if not query or not chunk_text:
        return 0.0

    query_tokens = _tokenize(query)
    chunk_tokens = _tokenize(chunk_text)
    if not query_tokens:
        return 0.0

    intersection = query_tokens & chunk_tokens
    overlap_ratio = len(intersection) / len(query_tokens)

    cosine = _compute_cosine_proxy(query, chunk_text)
    combined = 0.4 * overlap_ratio + 0.6 * cosine
    return min(1.0, combined)


def evaluate_retrieval_quality(query: str, chunks: list[dict]) -> RetrievalQualityReport:
    """Evaluate retrieval quality: score each chunk, classify, return report.

    CRAG-style classification:
    - Correct: score > 0.7 → highly relevant
    - Ambiguous: 0.3 <= score <= 0.7 → somewhat relevant
    - Incorrect: score < 0.3 → not relevant

    Args:
        query: The user query.
        chunks: List of chunk dicts with 'text' and optionally 'score' keys.

    Returns:
        RetrievalQualityReport with classification and statistics.
    """
    if not chunks:
        return RetrievalQualityReport(
            classification="Incorrect",
            correct_count=0,
            incorrect_count=0,
            ambiguous_count=0,
            total_count=0,
            correct_rate=0.0,
            recommendations=["No chunks retrieved. Consider expanding retrieval scope or checking index."],
        )

    correct = 0
    incorrect = 0
    ambiguous = 0
    recommendations: list[str] = []

    for chunk in chunks:
        text = chunk.get("text", "")
        score = _score_chunk_relevance(query, text)

        if score > 0.7:
            correct += 1
        elif score < 0.3:
            incorrect += 1
        else:
            ambiguous += 1

    total = len(chunks)
    correct_rate = correct / total if total > 0 else 0.0

    if correct_rate >= 0.5:
        classification = "Correct"
    elif correct_rate == 0.0 and incorrect == total:
        classification = "Incorrect"
    else:
        classification = "Ambiguous"

    if incorrect > 0:
        recommendations.append(f"{incorrect}/{total} chunks are irrelevant to the query.")
    if ambiguous > 0:
        recommendations.append(f"{ambiguous}/{total} chunks are partially relevant — consider query refinement.")
    if correct == 0 and total > 0:
        recommendations.append("No highly relevant chunks found. Consider re-running retrieval with HyDE enabled.")
    if correct_rate >= 0.5:
        recommendations.append("Retrieval quality is acceptable.")

    return RetrievalQualityReport(
        classification=classification,
        correct_count=correct,
        incorrect_count=incorrect,
        ambiguous_count=ambiguous,
        total_count=total,
        correct_rate=round(correct_rate, 3),
        recommendations=recommendations,
    )


# ── F4: Answer Claim Verification ──


@dataclass
class VerificationReport:
    verification_rate: float
    supported_claims: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    total_claims: int = 0


def verify_answer_claims(answer: str, context: str) -> VerificationReport:
    """Decompose answer into atomic claims and verify each against context.

    Uses the same entailment-style check as NLI grounding: cosine similarity
    + keyword overlap for air-gapped compatibility.

    Args:
        answer: The generated answer text.
        context: The retrieved context to verify against.

    Returns:
        VerificationReport with supported/unsupported claims and verification rate.
    """
    if not answer or not answer.strip():
        return VerificationReport(verification_rate=0.0)

    claims = decompose_into_claims(answer)
    if not claims:
        return VerificationReport(verification_rate=0.0)

    if not context or not context.strip():
        return VerificationReport(
            verification_rate=0.0,
            unsupported_claims=list(claims),
            total_claims=len(claims),
        )

    supported = []
    unsupported = []
    for claim in claims:
        if _check_claim_supported(claim, context):
            supported.append(claim)
        else:
            unsupported.append(claim)

    rate = len(supported) / len(claims) if claims else 0.0
    return VerificationReport(
        verification_rate=round(rate, 3),
        supported_claims=supported,
        unsupported_claims=unsupported,
        total_claims=len(claims),
    )
