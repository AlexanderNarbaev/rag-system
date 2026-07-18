"""Progressive Retrieval (FR-25, FR-143).

When initial retrieval returns insufficient results, progressively expand:
0. (FR-143) HyDE: generate hypothetical document, search with it
1. Try top_k=5 first
2. If <2 strong sources (score >= 0.32), try top_k=10
3. If still insufficient, try top_k=20 + graph expansion
4. If still insufficient, trigger clarifying questions

Each stage returns only NEW results (deduplicated from previous stages).
Graph expansion only happens at the final stage (expensive).
"""

from __future__ import annotations

import logging
from typing import Any

from proxy.app.core.retrieval import (
    MIN_STRONG_SOURCES,
    STRONG_SCORE_THRESHOLD,
    graph_expand_query,
    hybrid_search,
)
from proxy.app.shared.config import HYDE_ENABLED_IN_PROGRESSIVE
from proxy.app.shared.utils import estimate_tokens

logger = logging.getLogger(__name__)

PROGRESSIVE_STAGE_NAMES = ["hyde", "direct", "expanded", "graph_expanded", "insufficient"]


def _get_score(result: Any) -> float:
    """Extract score from a retrieval result (ScoredPoint or dict)."""
    try:
        return float(getattr(result, "score", 0) or 0)
    except (TypeError, ValueError):
        if isinstance(result, dict):
            return float(result.get("score", 0) or 0)
    return 0.0


def quality_sufficient(results: list[Any]) -> bool:
    """Check if retrieval quality is sufficient: at least 2 sources with score >= 0.32.

    Reuses the same thresholds from retrieval.py (STRONG_SCORE_THRESHOLD, MIN_STRONG_SOURCES)
    and knowledge_status.py.

    Args:
        results: List of ScoredPoint-like objects with a ``.score`` attribute,
                 or list of dicts with a ``"score"`` key.

    Returns:
        True if quality is sufficient for answer generation.
    """
    if not results:
        return False

    strong_count = 0
    for r in results:
        score = getattr(r, "score", None) if hasattr(r, "score") else r.get("score", 0)
        if isinstance(score, (int, float)) and score >= STRONG_SCORE_THRESHOLD:
            strong_count += 1
            if strong_count >= MIN_STRONG_SOURCES:
                return True
    return False


def _get_id(result: Any) -> str:
    """Extract a stable identifier from a result for deduplication."""
    if hasattr(result, "id"):
        return str(result.id)
    if isinstance(result, dict):
        return str(result.get("id", result.get("chunk_id", id(result))))
    return str(id(result))


def _dedup_new_only(existing_ids: set[str], new_results: list[Any]) -> list[Any]:
    """Filter new_results to only include entries not in existing_ids. Updates existing_ids in place."""
    new_only = []
    for r in new_results:
        rid = _get_id(r)
        if rid not in existing_ids:
            existing_ids.add(rid)
            new_only.append(r)
    return new_only


async def progressive_retrieve(
    query: str,
    version: str | None = None,
    stages: list[int] | None = None,
    access_filter: list[dict[str, Any]] | None = None,
    namespace: str | None = None,
    lang: str | None = None,
) -> tuple[list[Any], str]:
    """Progressive retrieval: expand top_k until quality is sufficient or stages exhausted.

    Stage order:
        0. HyDE expansion (FR-143) — generate hypothetical document, search with it
        1. top_k=5  -> "direct"
        2. top_k=10 -> "expanded"
        3. top_k=20 + graph expansion -> "graph_expanded"
        4. Fallback  -> "insufficient"

    Each subsequent stage returns only NEW results (not seen in earlier stages).
    Graph expansion is only attempted at the final stage because it's expensive.

    Args:
        query: Search query text.
        version: Optional version filter.
        stages: Override for stage top_k values (default: [5, 10, 20]).
        access_filter: Optional ACL filter conditions.
        namespace: Optional tenant namespace filter.
        lang: Optional detected language code.

    Returns:
        Tuple of (accumulated_results, stage_name).
    """
    if stages is None:
        stages = [5, 10, 20]

    all_results: list[Any] = []
    seen_ids: set[str] = set()

    search_query = query

    # Stage 0 (FR-143): HyDE expansion — generate hypothetical document, search with it
    if HYDE_ENABLED_IN_PROGRESSIVE:
        try:
            from proxy.app.core.hyde import generate_hypothetical_answer

            hypothetical_doc = generate_hypothetical_answer(query)
            token_count = estimate_tokens(hypothetical_doc)
            logger.info(
                "Progressive retrieval: stage 'hyde' — generated hypothetical doc of %d tokens",
                token_count,
            )

            hyde_results = hybrid_search(
                query=hypothetical_doc,
                version=version,
                top_k=stages[0] if stages else 5,
                access_filter=access_filter,
                namespace=namespace,
                lang=lang,
            )

            if hyde_results:
                for r in hyde_results:
                    seen_ids.add(_get_id(r))
                all_results.extend(hyde_results)
                search_query = hypothetical_doc

                if quality_sufficient(all_results):
                    logger.info(
                        "Progressive retrieval: stage 'hyde' sufficient (%d results)",
                        len(all_results),
                    )
                    return all_results, "hyde"
                logger.info(
                    "Progressive retrieval: stage 'hyde' returned %d results, "
                    "quality insufficient, proceeding to direct retrieval",
                    len(hyde_results),
                )
            else:
                logger.info(
                    "Progressive retrieval: stage 'hyde' returned no results, "
                    "falling back to standard search"
                )
        except Exception as e:
            logger.warning(
                "Progressive retrieval: HyDE expansion failed (%s), "
                "falling back to standard search",
                e,
            )

    # Stage 1: top_k = stages[0] (default 5)
    stage_top_k = stages[0] if stages else 5
    results = hybrid_search(
        query=search_query,
        version=version,
        top_k=stage_top_k,
        access_filter=access_filter,
        namespace=namespace,
        lang=lang,
    )
    new_only = _dedup_new_only(seen_ids, results)
    all_results.extend(new_only)

    if quality_sufficient(all_results):
        logger.info(
            "Progressive retrieval: stage 'direct' sufficient (top_k=%d, %d results)",
            stage_top_k,
            len(all_results),
        )
        return all_results, "direct"

    # Stage 2: top_k = stages[1] (default 10), only new results
    if len(stages) > 1:
        stage_top_k = stages[1]
        expanded_results = hybrid_search(
            query=search_query,
            version=version,
            top_k=stage_top_k,
            access_filter=access_filter,
            namespace=namespace,
            lang=lang,
        )
        new_only = _dedup_new_only(seen_ids, expanded_results)
        all_results.extend(new_only)

        if quality_sufficient(all_results):
            logger.info(
                "Progressive retrieval: stage 'expanded' sufficient (top_k=%d, +%d new)",
                stage_top_k,
                len(new_only),
            )
            return all_results, "expanded"

    # Stage 3: top_k = stages[2] (default 20) + graph expansion
    if len(stages) > 2:
        stage_top_k = stages[2]
        expanded_results = hybrid_search(
            query=search_query,
            version=version,
            top_k=stage_top_k,
            access_filter=access_filter,
            namespace=namespace,
            lang=lang,
        )
        new_only = _dedup_new_only(seen_ids, expanded_results)
        all_results.extend(new_only)

        # Graph expansion (expensive — only at final stage)
        graph_context = graph_expand_query(query)
        if graph_context:
            logger.info(
                "Progressive retrieval: graph expansion returned %d chars",
                len(graph_context),
            )

        if quality_sufficient(all_results):
            logger.info(
                "Progressive retrieval: stage 'graph_expanded' sufficient (top_k=%d, +%d new)",
                stage_top_k,
                len(new_only),
            )
            return all_results, "graph_expanded"

    strong_count = sum(1 for r in all_results if _get_score(r) >= STRONG_SCORE_THRESHOLD)
    logger.warning(
        "Progressive retrieval: all stages exhausted (%d results, %d strong)",
        len(all_results),
        strong_count,
    )
    return all_results, "insufficient"
