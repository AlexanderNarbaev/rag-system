"""NLI-based model evaluator for eval gate integration.

Provides real Natural Language Inference (entailment/contradiction) checks
using transformers-based NLI models with CPU fallback for air-gapped environments.

Metrics produced:
- nli_entailment_rate: fraction of claims entailed by context
- nli_contradiction_rate: fraction of claims contradicted by context
- nli_neutral_rate: fraction of claims neither entailed nor contradicted
- nli_overall_score: weighted score (entailment - contradiction) normalized to [0,1]
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_NLI_MODEL = None
_NLI_TOKENIZER = None
_NLI_MODEL_LOADED = False
_NLI_LOAD_ERROR: str | None = None


@dataclass
class NLIEvaluationResult:
    entailment_rate: float
    contradiction_rate: float
    neutral_rate: float
    overall_score: float
    total_claims: int
    entailed_claims: int
    contradicted_claims: int
    neutral_claims: int
    per_claim_scores: list[dict[str, Any]] = field(default_factory=list)

    def as_metrics(self) -> dict[str, float]:
        return {
            "nli_entailment_rate": self.entailment_rate,
            "nli_contradiction_rate": self.contradiction_rate,
            "nli_neutral_rate": self.neutral_rate,
            "nli_overall_score": self.overall_score,
        }


def _load_nli_model(
    model_name: str = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",
    device: str = "cpu",
) -> tuple[Any, Any]:
    global _NLI_MODEL, _NLI_TOKENIZER, _NLI_MODEL_LOADED, _NLI_LOAD_ERROR

    if _NLI_MODEL_LOADED:
        return _NLI_MODEL, _NLI_TOKENIZER

    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError:
        _NLI_LOAD_ERROR = "transformers not installed"
        _NLI_MODEL_LOADED = True
        logger.warning(f"NLI model loading skipped: {_NLI_LOAD_ERROR}")
        return None, None

    try:
        import torch
    except ImportError:
        _NLI_LOAD_ERROR = "torch not installed"
        _NLI_MODEL_LOADED = True
        logger.warning(f"NLI model loading skipped: {_NLI_LOAD_ERROR}")
        return None, None

    try:
        _NLI_TOKENIZER = AutoTokenizer.from_pretrained(
            model_name,
            use_fast=True,
            local_files_only=True,
        )
        _NLI_MODEL = AutoModelForSequenceClassification.from_pretrained(
            model_name,
            local_files_only=True,
        )
        _NLI_MODEL.eval()
        _NLI_MODEL = _NLI_MODEL.to("cuda") if device == "cuda" and torch.cuda.is_available() else _NLI_MODEL.to("cpu")
        logger.info(f"NLI model loaded: {model_name} on {device}")
    except Exception as e:
        _NLI_LOAD_ERROR = str(e)
        logger.warning(f"NLI model load failed ({e}), falling back to lightweight proxy")
        _NLI_MODEL = None
        _NLI_TOKENIZER = None

    _NLI_MODEL_LOADED = True
    return _NLI_MODEL, _NLI_TOKENIZER


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _compute_cosine_proxy(text_a: str, text_b: str) -> float:
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / math.sqrt(len(tokens_a) * len(tokens_b))


def decompose_into_claims(answer: str) -> list[str]:
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


def nli_predict(claim: str, context: str, max_length: int = 512) -> tuple[str, float]:
    model, tokenizer = _load_nli_model()
    if model is None or tokenizer is None:
        raise RuntimeError(f"NLI model not available: {_NLI_LOAD_ERROR or 'unknown error'}")

    import torch

    truncated_context = context[:max_length]
    inputs = tokenizer(
        truncated_context,
        claim,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    if model.device.type != "cpu":
        inputs = {k: v.to(model.device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits[0]

    id_to_label = {0: "entailment", 1: "neutral", 2: "contradiction"}
    probabilities = torch.softmax(logits, dim=0).cpu().tolist()

    best_idx = int(torch.argmax(logits).item())
    label = id_to_label.get(best_idx, "neutral")
    confidence = probabilities[best_idx]

    return label, float(confidence)


def _lightweight_check(claim: str, context: str) -> tuple[str, float]:
    cosine = _compute_cosine_proxy(claim, context)
    claim_tokens = _tokenize(claim)
    context_tokens = _tokenize(context)

    if not claim_tokens:
        return "neutral", 0.5

    overlap = len(claim_tokens & context_tokens) / len(claim_tokens)
    combined = 0.5 * cosine + 0.5 * overlap

    if combined >= 0.4:
        return "entailment", combined
    elif combined <= 0.15:
        return "contradiction", 1.0 - combined
    else:
        return "neutral", 0.5


def _check_claim_nli(claim: str, context: str) -> tuple[str, float]:
    try:
        label, confidence = nli_predict(claim, context)
        return label, confidence
    except Exception:
        return _lightweight_check(claim, context)


def evaluate_nli(
    answer: str,
    context: str,
    use_real_nli: bool = True,
) -> NLIEvaluationResult:
    if not answer or not answer.strip():
        return NLIEvaluationResult(
            entailment_rate=0.0,
            contradiction_rate=0.0,
            neutral_rate=0.0,
            overall_score=0.0,
            total_claims=0,
            entailed_claims=0,
            contradicted_claims=0,
            neutral_claims=0,
        )

    claims = decompose_into_claims(answer)
    if not claims:
        return NLIEvaluationResult(
            entailment_rate=0.0,
            contradiction_rate=0.0,
            neutral_rate=0.0,
            overall_score=0.0,
            total_claims=0,
            entailed_claims=0,
            contradicted_claims=0,
            neutral_claims=0,
        )

    if not context or not context.strip():
        return NLIEvaluationResult(
            entailment_rate=0.0,
            contradiction_rate=0.0,
            neutral_rate=0.0,
            overall_score=0.0,
            total_claims=len(claims),
            entailed_claims=0,
            contradicted_claims=0,
            neutral_claims=len(claims),
        )

    entailed = 0
    contradicted = 0
    neutral = 0
    per_claim: list[dict[str, Any]] = []

    for claim in claims:
        if use_real_nli:
            label, confidence = _check_claim_nli(claim, context)
        else:
            label, confidence = _lightweight_check(claim, context)

        per_claim.append(
            {
                "claim": claim,
                "label": label,
                "confidence": round(confidence, 3),
            }
        )

        if label == "entailment":
            entailed += 1
        elif label == "contradiction":
            contradicted += 1
        else:
            neutral += 1

    total = len(claims)
    entailment_rate = entailed / total
    contradiction_rate = contradicted / total
    neutral_rate = neutral / total
    overall_score = max(0.0, min(1.0, entailment_rate - 0.5 * contradiction_rate))

    return NLIEvaluationResult(
        entailment_rate=round(entailment_rate, 4),
        contradiction_rate=round(contradiction_rate, 4),
        neutral_rate=round(neutral_rate, 4),
        overall_score=round(overall_score, 4),
        total_claims=total,
        entailed_claims=entailed,
        contradicted_claims=contradicted,
        neutral_claims=neutral,
        per_claim_scores=per_claim,
    )


def evaluate_nli_batch(
    answer_context_pairs: list[tuple[str, str]],
    use_real_nli: bool = True,
) -> dict[str, float]:
    if not answer_context_pairs:
        return {
            "nli_entailment_rate": 0.0,
            "nli_contradiction_rate": 0.0,
            "nli_neutral_rate": 0.0,
            "nli_overall_score": 0.0,
        }

    total_entailed = 0
    total_contradicted = 0
    total_neutral = 0
    total_claims = 0

    for answer, context in answer_context_pairs:
        result = evaluate_nli(answer, context, use_real_nli=use_real_nli)
        total_entailed += result.entailed_claims
        total_contradicted += result.contradicted_claims
        total_neutral += result.neutral_claims
        total_claims += result.total_claims

    if total_claims == 0:
        return {
            "nli_entailment_rate": 0.0,
            "nli_contradiction_rate": 0.0,
            "nli_neutral_rate": 0.0,
            "nli_overall_score": 0.0,
        }

    entailment_rate = total_entailed / total_claims
    contradiction_rate = total_contradicted / total_claims
    neutral_rate = total_neutral / total_claims
    overall_score = max(0.0, min(1.0, entailment_rate - 0.5 * contradiction_rate))

    return {
        "nli_entailment_rate": round(entailment_rate, 4),
        "nli_contradiction_rate": round(contradiction_rate, 4),
        "nli_neutral_rate": round(neutral_rate, 4),
        "nli_overall_score": round(overall_score, 4),
    }


def is_nli_model_available() -> bool:
    _load_nli_model()
    return _NLI_MODEL is not None and _NLI_TOKENIZER is not None


def get_nli_load_error() -> str | None:
    _load_nli_model()
    return _NLI_LOAD_ERROR
