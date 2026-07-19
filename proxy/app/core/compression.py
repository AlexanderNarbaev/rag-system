"""LLMLingua-style token-level context compression.

Implements entropy-based compression that removes low-information tokens
while preserving key facts. Designed for air-gapped environments — no
external model dependencies.

Compression strategy:
1. Split text into sentences
2. Score each sentence by information density (keyword ratio, uniqueness)
3. Keep top-scoring sentences to meet target compression ratio
4. Reassemble compressed text

Target: 2-5x compression, <5% information loss, <100ms for 10K tokens.

Reference: "LLMLingua: Accelerating and Enhancing LLMs with an
Efficient, Easy-to-Use, and Extendable Prompt Compression Framework"
(Jiang et al., 2023)
"""

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# Common English stop words to exclude from information scoring
_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "because",
        "but",
        "and",
        "or",
        "if",
        "while",
        "about",
        "up",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "they",
        "them",
        "their",
        "which",
        "what",
        "who",
        "whom",
        "whose",
    }
)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using punctuation boundaries."""
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def _content_words(text: str) -> set[str]:
    """Extract content words (non-stop-words) from text."""
    words = set(re.findall(r"\w+", text.lower()))
    return words - _STOP_WORDS


def _score_sentence(sentence: str, all_content_words: set[str]) -> float:
    """Score a sentence by information density.

    Factors:
    - Ratio of content words to total words (higher = more dense)
    - Presence of numbers/specific data (boosted)
    - Sentence length (very short = low info, very long = possibly redundant)
    - Uniqueness of content words vs. document average
    """
    words = re.findall(r"\w+", sentence)
    if not words:
        return 0.0

    content = _content_words(sentence)
    total = len(words)

    # Factor 1: Content word ratio
    content_ratio = len(content) / total if total > 0 else 0.0

    # Factor 2: Numeric data presence (facts, dates, measurements)
    has_numbers = bool(re.search(r"\d+", sentence))
    number_boost = 0.15 if has_numbers else 0.0

    # Factor 3: Length penalty for very short or very long sentences
    length_score = 1.0
    if total < 4:
        length_score = 0.5  # Too short
    elif total > 50:
        length_score = 0.8  # Possibly redundant

    # Factor 4: Uniqueness — content words not appearing everywhere
    if all_content_words and content:
        unique_ratio = len(content - all_content_words) / len(content) if content else 0
        # Inverse: words that appear in many sentences are less unique
        uniqueness = 1.0 - (unique_ratio * 0.3)
    else:
        uniqueness = 1.0

    score = (content_ratio * 0.5 + number_boost + 0.35) * length_score * uniqueness
    return max(0.0, min(1.0, score))


def compress_context(
    text: str,
    target_ratio: float = 3.0,
    min_tokens: int = 20,
) -> tuple[str, dict[str, Any]]:
    """Compress text by removing low-information sentences.

    Uses entropy-based scoring to identify and remove sentences that
    contribute the least information, achieving 2-5x compression.

    Args:
        text: The full context text to compress.
        target_ratio: Desired compression ratio (2.0 = 50% reduction, 3.0 = 67%).
        min_tokens: Minimum token count below which no compression is applied.

    Returns:
        Tuple of (compressed_text, stats_dict) where stats contains:
        - compression_ratio: Actual compression achieved
        - original_tokens: Token count of original
        - compressed_tokens: Token count of compressed
        - sentences_removed: Number of sentences removed
        - latency_ms: Compression time in milliseconds

    """
    start_time = time.monotonic()

    if not text or not text.strip():
        return "", {
            "compression_ratio": 1.0,
            "original_tokens": 0,
            "compressed_tokens": 0,
            "sentences_removed": 0,
            "latency_ms": 0.0,
        }

    words = re.findall(r"\w+", text)
    token_count = len(words)

    # Skip compression for short texts
    if token_count < min_tokens:
        elapsed = (time.monotonic() - start_time) * 1000
        return text, {
            "compression_ratio": 1.0,
            "original_tokens": token_count,
            "compressed_tokens": token_count,
            "sentences_removed": 0,
            "latency_ms": round(elapsed, 2),
        }

    sentences = _split_sentences(text)
    if len(sentences) <= 1:
        elapsed = (time.monotonic() - start_time) * 1000
        return text, {
            "compression_ratio": 1.0,
            "original_tokens": token_count,
            "compressed_tokens": token_count,
            "sentences_removed": 0,
            "latency_ms": round(elapsed, 2),
        }

    # Collect all content words for uniqueness scoring
    all_content: set[str] = set()
    for sent in sentences:
        all_content.update(_content_words(sent))

    # Score each sentence
    scored = [(i, sent, _score_sentence(sent, all_content)) for i, sent in enumerate(sentences)]

    # Sort by score descending, keep top portion to meet target ratio
    target_tokens = max(1, int(token_count / target_ratio))
    sorted_by_score = sorted(scored, key=lambda x: x[2], reverse=True)

    kept_sentences: list[tuple[int, str]] = []
    kept_tokens = 0

    for orig_idx, sentence, _score in sorted_by_score:
        sent_tokens = len(re.findall(r"\w+", sentence))
        if kept_tokens + sent_tokens <= target_tokens or not kept_sentences:
            kept_sentences.append((orig_idx, sentence))
            kept_tokens += sent_tokens
        if kept_tokens >= target_tokens:
            break

    # Sort kept sentences by original order to preserve coherence
    kept_sentences.sort(key=lambda x: x[0])

    compressed = " ".join(s for _, s in kept_sentences)
    compressed_tokens = len(re.findall(r"\w+", compressed))
    actual_ratio = token_count / compressed_tokens if compressed_tokens > 0 else 1.0

    elapsed = (time.monotonic() - start_time) * 1000

    stats = {
        "compression_ratio": round(actual_ratio, 2),
        "original_tokens": token_count,
        "compressed_tokens": compressed_tokens,
        "sentences_removed": len(sentences) - len(kept_sentences),
        "latency_ms": round(elapsed, 2),
    }

    logger.debug(
        "Compression: %d → %d tokens (%.1fx), removed %d/%d sentences in %.1fms",
        token_count,
        compressed_tokens,
        actual_ratio,
        stats["sentences_removed"],
        len(sentences),
        elapsed,
    )

    return compressed, stats


def compress_chunks(
    chunks: list[dict[str, Any]],
    target_ratio: float = 3.0,
    text_key: str = "text",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compress a list of chunk dicts by compressing each chunk's text.

    Args:
        chunks: List of chunk dicts with a text field.
        target_ratio: Desired compression ratio per chunk.
        text_key: Key for the text field in each chunk dict.

    Returns:
        Tuple of (compressed_chunks, aggregate_stats).

    """
    if not chunks:
        return [], {
            "compression_ratio": 1.0,
            "original_tokens": 0,
            "compressed_tokens": 0,
            "sentences_removed": 0,
            "latency_ms": 0.0,
        }

    compressed_chunks = []
    total_original = 0
    total_compressed = 0
    total_removed = 0
    total_latency = 0.0

    for chunk in chunks:
        text = chunk.get(text_key, "")
        compressed_text, stats = compress_context(text, target_ratio=target_ratio)

        new_chunk = dict(chunk)
        new_chunk[text_key] = compressed_text
        compressed_chunks.append(new_chunk)

        total_original += stats["original_tokens"]
        total_compressed += stats["compressed_tokens"]
        total_removed += stats["sentences_removed"]
        total_latency += stats["latency_ms"]

    ratio = total_original / total_compressed if total_compressed > 0 else 1.0
    aggregate_stats = {
        "compression_ratio": round(ratio, 2),
        "original_tokens": total_original,
        "compressed_tokens": total_compressed,
        "sentences_removed": total_removed,
        "latency_ms": round(total_latency, 2),
    }

    return compressed_chunks, aggregate_stats
