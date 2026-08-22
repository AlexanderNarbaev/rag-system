# proxy/app/grounding.py
"""Context grounding score for RAG answer verification.

Combines two signals (per the documented "NLI-based answer grounding"
design — cosine + entailment):

1. **Cosine similarity** between the answer embedding and context embedding.
2. **NLI entailment** — the answer is decomposed into atomic claims and each
   claim is checked against the context with the NLI model
   (``proxy.app.model_evolution.nli_evaluator``, same chain as confidence.py).

Graceful degradation: when the NLI model is unavailable the score falls back
to cosine only; when the embedder is unavailable the score falls back to
entailment only; when neither is available the score is 0.0.
Low grounding scores may indicate hallucination.
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_embedder = None
_nli_unavailable_warned = False


def _get_embedder() -> Any:
    global _embedder
    if _embedder is None:
        try:
            from proxy.app.llm.remote_services import create_embedder

            _embedder = create_embedder()
        except Exception:
            logger.warning("Embedder not available, grounding disabled", exc_info=True)
            return None
    return _embedder


def _cosine_grounding(answer: str, context: str) -> float | None:
    """Cosine similarity between answer and context embeddings.

    Returns None when the embedder is unavailable or encoding fails.
    """
    embedder = _get_embedder()
    if embedder is None:
        return None

    try:
        answer_emb = embedder.encode(answer, normalize_embeddings=True)
        context_emb = embedder.encode(context, normalize_embeddings=True)
        similarity = float(np.dot(answer_emb, context_emb))
        return max(0.0, min(1.0, similarity))
    except Exception:
        logger.warning("Grounding cosine computation failed", exc_info=True)
        return None


def _entailment_grounding(answer: str, context: str) -> float | None:
    """NLI entailment score: fraction of answer claims entailed by context.

    Reuses the NLI chain from confidence.py (nli_evaluator). Returns None
    when NLI grounding is disabled in config or the model is unavailable.
    """
    global _nli_unavailable_warned

    try:
        from proxy.app.shared.config import NLI_GROUNDING_ENABLED
    except ImportError:
        NLI_GROUNDING_ENABLED = True  # noqa: N806

    if not NLI_GROUNDING_ENABLED:
        return None

    try:
        from proxy.app.model_evolution.nli_evaluator import evaluate_nli, is_nli_model_available

        if not is_nli_model_available():
            if not _nli_unavailable_warned:
                logger.warning("NLI model unavailable — grounding falls back to cosine similarity only")
                _nli_unavailable_warned = True
            return None

        result = evaluate_nli(answer, context, use_real_nli=True)
    except Exception:
        logger.warning("NLI entailment check failed, falling back to cosine only", exc_info=True)
        return None

    if result.total_claims == 0:
        return None
    return max(0.0, min(1.0, result.overall_score))


def compute_grounding(answer: str, context: str) -> float:
    """Compute a context grounding score for an answer given the context.

    Combines embedding cosine similarity with NLI entailment (equal weights
    when both signals are available). Returns a float in [0.0, 1.0] where
    higher values indicate stronger grounding.

    Args:
        answer: The generated answer text.
        context: The retrieved context text used for generation.

    Returns:
        Grounding score (0.0 = ungrounded, 1.0 = perfectly grounded).
        Returns 0.0 if either string is empty or both signals are unavailable.

    """
    if not answer or not context:
        return 0.0

    cosine = _cosine_grounding(answer, context)
    entailment = _entailment_grounding(answer, context)

    if cosine is None:
        return float(entailment) if entailment is not None else 0.0
    if entailment is None:
        return float(cosine)
    return max(0.0, min(1.0, 0.5 * cosine + 0.5 * entailment))
