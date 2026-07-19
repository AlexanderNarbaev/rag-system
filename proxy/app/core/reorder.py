"""LongContextReorder — combat 'lost in the middle' effect for LLMs.

Reorders retrieved chunks so that:
- The most relevant chunk is placed FIRST (prime position)
- The second most relevant chunk is placed LAST (recency effect)
- Remaining chunks are in the MIDDLE, sorted by relevance (descending)

Reference: "Lost in the Middle: How Language Models Use Long Contexts"
(Liu et al., 2023) — LLMs pay more attention to information at the
beginning and end of the context window.

This module is air-gapped compatible — no external dependencies.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def reorder_for_long_context(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder chunks to maximize LLM attention on most relevant content.

    Places the most relevant chunk first and second most relevant last,
    with remaining chunks sorted by score in the middle. This combats the
    'lost in the middle' effect where LLMs pay less attention to content
    in the center of long contexts.

    Args:
        chunks: List of chunk dicts, each must have a 'score' key (float).
                All other keys are preserved.

    Returns:
        Reordered list of chunk dicts. Original list is not modified.
        Empty list if input is empty.

    Examples:
        >>> chunks = [
        ...     {"text": "A", "score": 0.5},
        ...     {"text": "B", "score": 0.9},
        ...     {"text": "C", "score": 0.3},
        ...     {"text": "D", "score": 0.8},
        ... ]
        >>> result = reorder_for_long_context(chunks)
        >>> result[0]["text"]  # Most relevant first
        'B'
        >>> result[-1]["text"]  # Second most relevant last
        'D'

    """
    if not chunks:
        return []

    if len(chunks) == 1:
        return [dict(chunks[0])]

    if len(chunks) == 2:
        # Highest score first, lower score last
        sorted_two = sorted(chunks, key=lambda c: c.get("score", 0.0), reverse=True)
        return [dict(c) for c in sorted_two]

    # Sort all chunks by score descending (stable sort preserves original order for ties)
    indexed_chunks = list(enumerate(chunks))
    sorted_indexed = sorted(indexed_chunks, key=lambda ic: ic[1].get("score", 0.0), reverse=True)

    # Extract the top-2 and the rest
    first_idx, first_chunk = sorted_indexed[0]
    second_idx, second_chunk = sorted_indexed[1]
    middle_indexed = sorted_indexed[2:]

    # Middle chunks sorted by score descending (already sorted from above)
    middle = [dict(c) for _, c in middle_indexed]

    # Assemble: first → middle → last
    result = [dict(first_chunk)] + middle + [dict(second_chunk)]

    logger.debug(
        "LongContextReorder: %d chunks reordered (top score=%.3f, second=%.3f)",
        len(chunks),
        first_chunk.get("score", 0.0),
        second_chunk.get("score", 0.0),
    )

    return result
