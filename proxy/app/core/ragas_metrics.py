"""Lightweight RAGAS-style evaluation metrics using existing NLI + embedding infrastructure.

No external ragas dependency — reuses:
- DeBERTa NLI model (MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli) for faithfulness
- bge-m3 embedder for answer relevancy via cosine similarity
- Token-set overlap for context precision

Metrics:
- faithfulness_score(answer, context) — NLI-based claim verification
- answer_relevancy(answer, query) — embedding cosine similarity
- context_precision(contexts, answer) — fraction of contexts actually used
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

_EMBEDDER: Any = None
_SCORED_CACHE: dict[tuple[str, str], float] = {}
_CACHE_MAX_SIZE = 500


def _get_embedder() -> Any:
    global _EMBEDDER
    if _EMBEDDER is None:
        try:
            from proxy.app.llm.remote_services import create_embedder

            _EMBEDDER = create_embedder()
        except Exception:
            logger.warning("Embedder not available for RAGAS metrics", exc_info=True)
            return None
    return _EMBEDDER


def _embed_text(text: str) -> Any:
    embedder = _get_embedder()
    if embedder is None:
        return None
    try:
        return embedder.encode(text, normalize_embeddings=True)
    except Exception:
        logger.debug("Embedding failed for RAGAS metrics", exc_info=True)
        return None


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _extract_claims(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n|(?<=;)\s+", text.strip())
    claims = []
    for part in parts:
        stripped = part.strip().rstrip(";.")
        stripped = re.sub(r"^[-*•]\s*", "", stripped).strip()
        if len(stripped) >= 10:
            claims.append(stripped)
    return claims


def faithfulness_score(answer: str, context: str) -> float:
    """Compute faithfulness: fraction of answer claims supported by context via NLI.

    Uses DeBERTa NLI model when available; falls back to keyword-overlap proxy.
    Returns 0.0-1.0 where 1.0 = fully faithful.
    """
    if not answer or not answer.strip():
        return 0.0
    if not context or not context.strip():
        return 0.0

    claims = _extract_claims(answer)
    if not claims:
        return 1.0

    try:
        from proxy.app.model_evolution.nli_evaluator import _check_claim_nli

        supported = 0
        for claim in claims:
            label, _ = _check_claim_nli(claim, context)
            if label == "entailment":
                supported += 1

        score = supported / len(claims)
        return round(score, 4)
    except Exception:
        logger.debug("NLI-based faithfulness failed, using proxy", exc_info=True)

    context_tokens = _tokenize(context)
    supported = 0
    for claim in claims:
        claim_tokens = _tokenize(claim)
        if not claim_tokens:
            continue
        overlap = len(claim_tokens & context_tokens) / len(claim_tokens)
        cosine_proxy = (
            len(claim_tokens & context_tokens) / math.sqrt(len(claim_tokens) * len(context_tokens))
            if context_tokens
            else 0.0
        )
        combined = 0.5 * overlap + 0.5 * cosine_proxy
        if combined >= 0.30:
            supported += 1

    return round(supported / len(claims), 4)


def answer_relevancy(answer: str, query: str) -> float:
    """Compute answer relevancy via cosine similarity of embeddings.

    Returns 0.0-1.0 where 1.0 = fully relevant.
    """
    if not answer or not query:
        return 0.0

    cache_key = (query[:200], answer[:200])
    if cache_key in _SCORED_CACHE:
        return _SCORED_CACHE[cache_key]

    answer_emb = _embed_text(answer)
    query_emb = _embed_text(query)

    if answer_emb is None or query_emb is None:
        answer_tokens = _tokenize(answer)
        query_tokens = _tokenize(query)
        if not query_tokens:
            return 0.5
        matched = sum(1 for kw in query_tokens if kw in answer_tokens)
        score = matched / len(query_tokens)
    else:
        import numpy as np

        score = float(np.dot(answer_emb, query_emb))
        score = max(0.0, min(1.0, score))

    score = round(score, 4)
    if len(_SCORED_CACHE) < _CACHE_MAX_SIZE:
        _SCORED_CACHE[cache_key] = score
    return score


def context_precision(contexts: list[str], answer: str) -> float:
    """Compute context precision: fraction of contexts that contributed to the answer.

    A context is considered "used" if significant token overlap exists between
    the context and the answer. Returns 0.0-1.0.
    """
    if not contexts or not answer:
        return 0.0

    answer_tokens = _tokenize(answer)
    if not answer_tokens:
        return 0.0

    used = 0
    for ctx in contexts:
        ctx_tokens = _tokenize(ctx)
        if not ctx_tokens:
            continue
        overlap = len(answer_tokens & ctx_tokens) / len(ctx_tokens)
        if overlap >= 0.15:
            used += 1

    return round(used / len(contexts), 4)


def compute_all_ragas_metrics(
    question: str,
    answer: str,
    contexts: list[str],
) -> dict[str, float]:
    """Compute all lightweight RAGAS metrics for a RAG response."""
    context_text = " ".join(contexts) if contexts else ""

    faith = faithfulness_score(answer, context_text)
    relevancy = answer_relevancy(answer, question)
    precision = context_precision(contexts, answer)

    return {
        "ragas_faithfulness": faith,
        "ragas_relevancy": relevancy,
        "ragas_precision": precision,
    }
