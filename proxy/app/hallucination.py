"""Hallucination detection and benchmark metrics for self-correcting RAG Level 5.

Detects unsupported claims in generated answers by checking each factual claim
against the retrieved context using NLI-style entailment with keyword overlap
and cosine similarity proxies (air-gapped compatible).
"""
import logging
import math
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class HallucinationReport:
    hallucination_rate: float
    hallucinated_claims: list[str] = field(default_factory=list)
    supported_claims: int = 0
    total_claims: int = 0
    evidence_links: dict[str, str] = field(default_factory=dict)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _compute_cosine_proxy(text_a: str, text_b: str) -> float:
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / math.sqrt(len(tokens_a) * len(tokens_b))


def extract_factual_claims(answer: str) -> list[str]:
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


def check_claim_against_context(claim: str, context: str) -> bool:
    if not context or not context.strip():
        return False
    if not claim or not claim.strip():
        return False

    claim_tokens = _tokenize(claim)
    if not claim_tokens:
        return False

    context_tokens = _tokenize(context)
    cosine_score = _compute_cosine_proxy(claim, context)
    keyword_overlap = len(claim_tokens & context_tokens) / len(claim_tokens)

    combined = 0.5 * cosine_score + 0.5 * keyword_overlap
    return combined >= 0.30


def _find_evidence(claim: str, context: str) -> str:
    if not context or not context.strip():
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", context)
    for sentence in sentences:
        if check_claim_against_context(claim, sentence):
            return sentence.strip()
    return ""


def detect_hallucinations(answer: str, context: str) -> HallucinationReport:
    if not answer or not answer.strip():
        return HallucinationReport(hallucination_rate=0.0)

    claims = extract_factual_claims(answer)
    if not claims:
        return HallucinationReport(hallucination_rate=0.0)

    if not context or not context.strip():
        return HallucinationReport(
            hallucination_rate=1.0,
            hallucinated_claims=list(claims),
            total_claims=len(claims),
        )

    hallucinated = []
    evidence_links = {}
    supported = 0
    for claim in claims:
        if check_claim_against_context(claim, context):
            supported += 1
            evidence_links[claim] = _find_evidence(claim, context) or "context"
        else:
            hallucinated.append(claim)

    rate = len(hallucinated) / len(claims) if claims else 0.0
    return HallucinationReport(
        hallucination_rate=round(rate, 3),
        hallucinated_claims=hallucinated,
        supported_claims=supported,
        total_claims=len(claims),
        evidence_links=evidence_links,
    )


def compute_hallucination_rate(answers: list[str], contexts: list[str]) -> float:
    if not answers and not contexts:
        return 0.0
    if not answers:
        return 0.0

    total_hallucinated = 0
    total_claims = 0
    limit = min(len(answers), len(contexts))

    for i in range(limit):
        report = detect_hallucinations(answers[i], contexts[i])
        total_hallucinated += len(report.hallucinated_claims)
        total_claims += report.total_claims

    if total_claims == 0:
        return 0.0
    return round(total_hallucinated / total_claims, 3)


def run_hallucination_benchmark(eval_dataset: list[dict]) -> dict:
    if not eval_dataset:
        return {
            "hallucination_rate": 0.0,
            "total_claims": 0,
            "hallucinated_claims": 0,
            "samples_count": 0,
        }

    answers = [item.get("answer", "") for item in eval_dataset]
    contexts = [item.get("context", "") for item in eval_dataset]
    rate = compute_hallucination_rate(answers, contexts)

    total_hallucinated = 0
    total_claims_count = 0
    for i in range(len(eval_dataset)):
        report = detect_hallucinations(answers[i], contexts[i])
        total_hallucinated += len(report.hallucinated_claims)
        total_claims_count += report.total_claims

    return {
        "hallucination_rate": rate,
        "total_claims": total_claims_count,
        "hallucinated_claims": total_hallucinated,
        "samples_count": len(eval_dataset),
    }
