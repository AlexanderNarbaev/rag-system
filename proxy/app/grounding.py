# proxy/app/grounding.py
"""
Context grounding score for RAG answer verification.

Computes cosine similarity between the answer embedding and context embedding
to estimate how well the generated answer is grounded in the retrieved context.
Low grounding scores may indicate hallucination.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        try:
            from app.config import EMBEDDER_DEVICE, EMBEDDER_MODEL
            from sentence_transformers import SentenceTransformer

            if EMBEDDER_MODEL:
                _embedder = SentenceTransformer(EMBEDDER_MODEL, device=EMBEDDER_DEVICE)
            else:
                _embedder = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        except ImportError:
            logger.warning("sentence-transformers not available, grounding disabled")
            return None
    return _embedder


def compute_grounding(answer: str, context: str) -> float:
    """
    Compute a context grounding score for an answer given the context.

    Uses cosine similarity between the answer embedding and context embedding.
    Returns a float in [0.0, 1.0] where higher values indicate stronger grounding.

    Args:
        answer: The generated answer text.
        context: The retrieved context text used for generation.

    Returns:
        Grounding score (0.0 = ungrounded, 1.0 = perfectly grounded).
        Returns 0.0 if either string is empty or embedder is unavailable.
    """
    if not answer or not context:
        return 0.0

    embedder = _get_embedder()
    if embedder is None:
        return 0.0

    try:
        answer_emb = embedder.encode(answer, normalize_embeddings=True)
        context_emb = embedder.encode(context, normalize_embeddings=True)
        similarity = float(np.dot(answer_emb, context_emb))
        return max(0.0, min(1.0, similarity))
    except Exception:
        logger.warning("Grounding score computation failed", exc_info=True)
        return 0.0
