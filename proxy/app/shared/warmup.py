# proxy/app/warmup.py
"""Model warm-up utilities for RAG proxy.

Pre-loads models into GPU/RAM on startup or via admin endpoint
to avoid cold-start latency on the first real request.

Each warmup function uses graceful degradation:
failure is logged but never crashes the process.
"""

import asyncio
import logging
from typing import Any

from proxy.app.shared.config import (
    LLM_ENDPOINT,
    LLM_MODEL_NAME,
    WARMUP_ENABLED,
)

logger = logging.getLogger(__name__)

WARMUP_TEXT = "RAG system warm-up probe. This is a test sentence for model initialization."
WARMUP_QUERY = "warm-up probe"
WARMUP_DOC = "This is a warm-up document for reranker initialization."


async def warmup_embedder() -> bool:
    """Encode dummy text to load embedder model into memory.

    Uses hybrid_search with a dummy query to initialize both
    dense and sparse embedders.

    Returns True on success, False on failure.
    """
    try:
        from proxy.app.core.retrieval import hybrid_search

        _ = hybrid_search(query=WARMUP_QUERY, top_k=1)
        logger.info("Embedder warm-up completed")
        return True
    except Exception as e:
        logger.warning(f"Embedder warm-up skipped: {e}")
        return False


async def warmup_reranker() -> bool:
    """Score dummy (query, doc) pair to load reranker model into memory.

    Returns True on success, False on failure.
    """
    try:
        from proxy.app.core.rerank import rerank_chunks

        _ = rerank_chunks(WARMUP_QUERY, [WARMUP_DOC], top_k=1)
        logger.info("Reranker warm-up completed")
        return True
    except Exception as e:
        logger.warning(f"Reranker warm-up skipped: {e}")
        return False


async def warmup_llm() -> bool:
    """Send single-token inference to pre-load LLM KV cache.

    Returns True on success, False on failure.
    """
    if not LLM_ENDPOINT or not LLM_MODEL_NAME:
        logger.info("LLM warm-up skipped: no LLM configured")
        return False
    try:
        from proxy.app.llm.provider import non_stream_completion

        await non_stream_completion(
            [{"role": "user", "content": WARMUP_TEXT}],
            temperature=0.0,
            max_tokens=1,
        )
        logger.info("LLM warm-up completed")
        return True
    except Exception as e:
        logger.warning(f"LLM warm-up skipped: {e}")
        return False


async def warmup_all() -> dict[str, Any]:
    """Run all warmups concurrently. Returns status dict.

    Uses graceful degradation: individual failures don't
    prevent other warmups from running.
    """
    if not WARMUP_ENABLED:
        return {"status": "disabled", "embedder": False, "reranker": False, "llm": False}

    results = await asyncio.gather(
        warmup_embedder(),
        warmup_reranker(),
        warmup_llm(),
        return_exceptions=True,
    )

    embedder_ok = results[0] if not isinstance(results[0], BaseException) else False
    reranker_ok = results[1] if not isinstance(results[1], BaseException) else False
    llm_ok = results[2] if not isinstance(results[2], BaseException) else False

    all_ok = embedder_ok and reranker_ok and llm_ok
    return {
        "status": "ok" if all_ok else "partial",
        "embedder": embedder_ok,
        "reranker": reranker_ok,
        "llm": llm_ok,
    }
