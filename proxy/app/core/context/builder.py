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
    """
    Вычисляет хеш чанка на основе текста и ключевых метаданных (игнорирует score, position и т.д.).
    Используется для дедупликации.
    """
    text = chunk.get("text", "")
    source_type = chunk.get("source_type", "")
    source_id = chunk.get("source_id", "")
    version = chunk.get("version", "")
    doc_title = chunk.get("doc_title", "")
    content = f"{text}|{source_type}|{source_id}|{version}|{doc_title}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def deduplicate_chunks(
    chunks_with_scores: list[tuple[dict[str, Any], float]], method: str = "hash"
) -> list[tuple[dict[str, Any], float]]:
    """
    Дедупликация списка чанков.
    :param chunks_with_scores: список пар (chunk_dict, score)
    :param method: "hash" (по SHA-256), "similarity" (по порогу косинусного сходства, пока не реализован)
    :return: отфильтрованный список (сохраняется первый встреченный чанк с данным хешом)
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
    """
    Группирует чанки с одинаковым semantic_key (поле в чанке) и объединяет их текст.
    Это позволяет вернуть связанные фрагменты как один блок.
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
            # Объединяем тексты
            combined_text = "\n\n".join([ch["text"] for ch, _ in group])
            combined_chunk = group[0][0].copy()
            combined_chunk["text"] = combined_text
            # Средний скор (или максимальный – на выбор)
            avg_score = sum(sc for _, sc in group) / len(group)
            merged.append((combined_chunk, avg_score))
    return merged


def estimate_tokens(text: str) -> int:
    """
    Грубая оценка количества токенов (4 символа ~ 1 токен для рус/англ).
    Для точности использовать tiktoken.
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
    """
    Find query-relevant sentences in text.
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
    """
    Собирает контекст из отреранжированных и продедуплицированных чанков.
    :param chunks_with_scores: список пар (chunk, score)
    :param max_tokens: максимальное количество токенов в финальном контексте
    :param include_metadata: добавлять ли заголовки с метаданными перед каждым чанком
    :param sort_by_score: сортировать ли чанки по убыванию релевантности (score)
    :param lang: detected query language for multi-lingual prioritization (optional)
    :return: текст контекста
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

    # Сортировка по скору (убывание)
    if sort_by_score:
        chunks_with_scores.sort(key=lambda x: x[1], reverse=True)

    context_parts = []
    total_tokens = 0

    for chunk, score in chunks_with_scores:
        text = chunk.get("text", "").strip()
        if not text:
            continue

        # Добавляем метаданные, если нужно
        if include_metadata:
            source_type = chunk.get("source_type", "unknown")
            title = chunk.get("title", "")
            doc_title = chunk.get("doc_title", "")
            version = chunk.get("version", "latest")
            # Формируем компактный заголовок
            header = f"[{source_type}] {doc_title} / {title} (v{version}) [rel={score:.3f}]\n"
        else:
            header = ""

        part = header + text + "\n\n"
        part_tokens = estimate_tokens(part)

        if total_tokens + part_tokens > max_tokens:
            # Если превышаем лимит, пытаемся сократить последний чанк или остановиться
            remaining = max_tokens - total_tokens
            if remaining > 50:
                # Обрезаем текст последнего чанка
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
                [c for c, _ in chunks_with_scores], max_tokens=max_tokens, strategy="hierarchical"
            )
            if compressed:
                final_context = compressed
                logger.info(f"Context compressed via TokenOptimizer: {len(final_context)} chars")
        except Exception:
            logger.warning("Token optimizer compression failed, using truncated context", exc_info=True)

    return final_context


def build_proposition_context(chunks: list[tuple[dict[str, Any], float]], max_tokens: int) -> str:
    """
    Convert chunks to atomic proposition-like sentences.
    Each sentence becomes a standalone fact unit, then assembled up to max_tokens.
    """
    if not chunks:
        return ""

    propositions = []
    for chunk, _ in chunks:
        text = chunk.get("text", "").strip()
        if not text:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s = s.strip()
            if len(s) > 20:
                propositions.append((s, chunk.get("source_type", "unknown"), chunk.get("doc_title", "")))

    result_parts = []
    total_tokens = 0
    for prop, stype, title in propositions:
        if title and title not in str(result_parts[-1:]):  # noqa: SIM108
            prefix = f"[{stype}] {title}: "
        else:
            prefix = ""
        candidate = prefix + prop + " "
        candidate_tokens = estimate_tokens(candidate)
        if total_tokens + candidate_tokens > max_tokens:
            break
        result_parts.append(candidate)
        total_tokens += candidate_tokens

    return "".join(result_parts).strip()


def build_hierarchical_context(chunks: list[tuple[dict[str, Any], float]], max_tokens: int) -> str:
    """
    Tiered detail levels:
    - Top-3 chunks by score: full text
    - Next 5: first 3 sentences (summary)
    - Rest: title + first sentence only
    """
    if not chunks:
        return ""

    sorted_chunks = sorted(chunks, key=lambda x: x[1], reverse=True)
    parts = []
    total_tokens = 0

    for i, (chunk, score) in enumerate(sorted_chunks):
        text = chunk.get("text", "").strip()
        if not text:
            continue

        source_type = chunk.get("source_type", "unknown")
        title = chunk.get("title", chunk.get("doc_title", ""))
        header = f"[{source_type}] {title} (rel={score:.3f})\n"

        if i < 3:
            segment = header + text
        elif i < 8:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            summary = " ".join(sentences[:3])
            segment = header + summary + " [...]"
        else:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            first = sentences[0] if sentences else text[:200]
            segment = header + first + " [...]"

        seg_tokens = estimate_tokens(segment)
        if total_tokens + seg_tokens > max_tokens:
            remaining = max_tokens - total_tokens
            if remaining > 50:
                parts.append(segment[: remaining * 4])
            break
        parts.append(segment)
        total_tokens += seg_tokens

    return "\n\n".join(parts)


def prepare_context(
    chunks_with_scores: list[tuple[dict[str, Any], float]],
    requested_version: str | None = None,
    max_tokens: int = 120000,
    deduplicate: bool = True,
    resolve_versions_flag: bool = True,
    group_semantic: bool = False,
    lang: str | None = None,
) -> str:
    """
    High-level function: dedup, version resolution, grouping, context assembly.
    """
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
