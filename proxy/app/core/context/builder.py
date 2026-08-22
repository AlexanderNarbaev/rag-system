# proxy/app/core/context/builder.py
"""Context building, deduplication, and assembly for RAG proxy."""

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeStrip:
    """A single knowledge strip from CRAG decomposition."""

    text: str
    score: float
    source_type: str = "unknown"
    doc_title: str = ""
    chunk_index: int = 0
    sentence_index: int = 0


def compute_chunk_hash(chunk: dict[str, Any]) -> str:
    """Computes a chunk hash from the text and key metadata (ignores score, position, etc.).
    Used for deduplication.
    """
    text = chunk.get("text", "")
    source_type = chunk.get("source_type", "")
    source_id = chunk.get("source_id", "")
    version = chunk.get("version", "")
    doc_title = chunk.get("doc_title", "")
    content = f"{text}|{source_type}|{source_id}|{version}|{doc_title}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def deduplicate_chunks(
    chunks_with_scores: list[tuple[dict[str, Any], float]],
    method: str = "hash",
) -> list[tuple[dict[str, Any], float]]:
    """Deduplicates a list of chunks.
    :param chunks_with_scores: list of (chunk_dict, score) pairs
    :param method: "hash" (by SHA-256), "similarity" (by cosine similarity threshold, not implemented yet)
    :return: filtered list (the first chunk encountered with a given hash is kept)
    """
    seen = set()
    unique = []
    for chunk, score in chunks_with_scores:
        h = compute_chunk_hash(chunk)
        if h not in seen:
            seen.add(h)
            unique.append((chunk, score))
    logger.debug(f"Deduplication: {len(chunks_with_scores)} -> {len(unique)} chunks")
    return unique


def group_by_semantic_key(chunks_with_scores: list[tuple[dict[str, Any], float]]) -> list[tuple[dict[str, Any], float]]:
    """Groups chunks with the same semantic_key (a chunk field) and merges their text.
    This allows returning related fragments as a single block.
    """
    groups = defaultdict(list)
    for chunk, score in chunks_with_scores:
        key = chunk.get("semantic_key", chunk.get("hash", ""))
        groups[key].append((chunk, score))

    merged = []
    for _key, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
        else:
            # Merge the texts
            combined_text = "\n\n".join([ch["text"] for ch, _ in group])
            combined_chunk = group[0][0].copy()
            combined_chunk["text"] = combined_text
            # Average score (or maximum — your choice)
            avg_score = sum(sc for _, sc in group) / len(group)
            merged.append((combined_chunk, avg_score))
    return merged


def estimate_tokens(text: str) -> int:
    """Rough token count estimate (4 characters ~ 1 token for Russian/English).
    Use tiktoken for accuracy.
    """
    return len(text) // 4


def reorder_chunks(
    chunks_with_scores: list[tuple[dict[str, Any], float]],
) -> list[tuple[dict[str, Any], float]]:
    """Reorder chunks to counter the 'Lost in the Middle' U-shaped recall curve.

    Places highest-relevance chunks at START and END of the prompt;
    medium-relevance chunks go in the middle.

    Algorithm:
    1. Sort by score descending
    2. Interleave: pick best → put at start, pick next → put at end, repeat
    3. Remaining (medium) chunks stay in score order in the middle
    """
    if len(chunks_with_scores) <= 2:
        return list(chunks_with_scores)

    sorted_chunks = sorted(chunks_with_scores, key=lambda x: x[1], reverse=True)
    positions_high = []
    positions_low = []

    for i, item in enumerate(sorted_chunks):
        if i % 2 == 0:
            positions_high.append(item)
        else:
            positions_low.append(item)

    # Reverse the "low" group so the second-best goes last, fourth-best second-to-last, etc.
    positions_low.reverse()

    return positions_high + positions_low


def extract_relevant_segments(text: str, query: str) -> str:
    """Find query-relevant sentences in text.
    Uses word overlap scoring at the sentence level — keeps sentences
    that share significant vocabulary with the query.
    """
    if not text or not query:
        return text

    query_tokens = set(re.findall(r"\w+", query.lower()))
    if not query_tokens:
        return text

    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) <= 3:
        return text

    scored = []
    for s in sentences:
        s_tokens = set(re.findall(r"\w+", s.lower()))
        if not s_tokens:
            scored.append((s, 0.0))
            continue
        overlap = len(query_tokens & s_tokens)
        score = overlap / len(query_tokens)
        scored.append((s, score))

    threshold = max(0.05, sum(sc for _, sc in scored) / len(scored) * 0.5)
    relevant = [s for s, sc in scored if sc >= threshold]

    if relevant:
        return " ".join(relevant)
    return " ".join(s for s, _ in scored[:3])


def build_context(
    chunks_with_scores: list[tuple[dict[str, Any], float]],
    max_tokens: int = 120000,
    include_metadata: bool = True,
    sort_by_score: bool = True,
    lang: str | None = None,
) -> str:
    """Builds the context from reranked and deduplicated chunks.
    :param chunks_with_scores: list of (chunk, score) pairs
    :param max_tokens: maximum number of tokens in the final context
    :param include_metadata: whether to add metadata headers before each chunk
    :param sort_by_score: whether to sort chunks by descending relevance (score)
    :param lang: detected query language for multi-lingual prioritization (optional)
    :return: context text
    """
    if not chunks_with_scores:
        return ""

    # F4: LongContextReorder — place best at start/end, medium in middle
    try:
        from proxy.app.shared.config import REORDER_ENABLED
    except ImportError:
        REORDER_ENABLED = True  # noqa: N806
    if REORDER_ENABLED:
        chunks_with_scores = reorder_chunks(chunks_with_scores)

    # Sort by score (descending)
    if sort_by_score:
        chunks_with_scores.sort(key=lambda x: x[1], reverse=True)

    context_parts = []
    total_tokens = 0

    for chunk, score in chunks_with_scores:
        text = chunk.get("text", "").strip()
        if not text:
            continue

        # Add metadata if needed
        if include_metadata:
            source_type = chunk.get("source_type", "unknown")
            title = chunk.get("title", "")
            doc_title = chunk.get("doc_title", "")
            version = chunk.get("version", "latest")
            # Build a compact header
            header = f"[{source_type}] {doc_title} / {title} (v{version}) [rel={score:.3f}]\n"
        else:
            header = ""

        part = header + text + "\n\n"
        part_tokens = estimate_tokens(part)

        if total_tokens + part_tokens > max_tokens:
            # If the limit is exceeded, try to shrink the last chunk or stop
            remaining = max_tokens - total_tokens
            if remaining > 50:
                # Truncate the text of the last chunk
                truncated_text = text[: remaining * 4]
                part = header + truncated_text + "...\n\n"
                context_parts.append(part)
            break

        context_parts.append(part)
        total_tokens += part_tokens

    final_context = "".join(context_parts)
    logger.info(f"Context built: {len(final_context)} chars, ~{total_tokens} tokens")

    # Token optimizer integration: apply compression if token budget exceeded
    try:
        from proxy.app.shared.config import TOKEN_OPTIMIZER_ENABLED
    except ImportError:
        TOKEN_OPTIMIZER_ENABLED = False  # noqa: N806

    if TOKEN_OPTIMIZER_ENABLED and total_tokens > max_tokens and chunks_with_scores:
        try:
            from proxy.app.core.token_optimizer import TokenOptimizer

            optimizer = TokenOptimizer()
            compressed = optimizer.compress_context(
                [c for c, _ in chunks_with_scores],
                max_tokens=max_tokens,
                strategy="hierarchical",
            )
            if compressed:
                final_context = compressed
                logger.info(f"Context compressed via TokenOptimizer: {len(final_context)} chars")
        except Exception:
            logger.warning("Token optimizer compression failed, using truncated context", exc_info=True)

    return final_context


def prepare_context(
    chunks_with_scores: list[tuple[dict[str, Any], float]],
    requested_version: str | None = None,
    max_tokens: int = 120000,
    deduplicate: bool = True,
    resolve_versions_flag: bool = True,
    group_semantic: bool = False,
    lang: str | None = None,
) -> str:
    """High-level function: dedup, version resolution, grouping, context assembly."""
    if not chunks_with_scores:
        return ""

    result = chunks_with_scores

    if deduplicate:
        result = deduplicate_chunks(result)

    if resolve_versions_flag:
        from proxy.app.core.context.versioning import resolve_versions

        result = resolve_versions(result, requested_version=requested_version)

    if group_semantic:
        result = group_by_semantic_key(result)

    context = build_context(result, max_tokens=max_tokens, lang=lang)
    return context
