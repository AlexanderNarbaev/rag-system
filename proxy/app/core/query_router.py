"""Adaptive Query Routing

Classifies queries by complexity and routes to an appropriate retrieval strategy:
- direct: No retrieval needed (FAQ, greetings)
- single: Moderate queries needing single-step RAG
- multi: Complex queries needing multi-step iterative RAG

The router supports both English (EN) and Russian (RU) queries, and combines
several signals:

- Lexical greeting/small-talk detection (multi-language)
- Domain-specific boosters (compare, list, vs., etc.) — EN + RU
- Multi-language "what is" / "как" starters that down-classify queries
- Lightweight readability statistics: Flesch-Kincaid for EN, the Russian
  Flesh-Kincaid-style ratio for Cyrillic text
- Question punctuation and word-count heuristics

Based on: Adaptive-RAG (arxiv:2403.14403).

Expected impact: 40-60% latency reduction for simple queries.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Literal

logger = logging.getLogger(__name__)

Complexity = Literal["direct", "single", "multi"]

# ─────────────────────────────────────────────────────────────────────────────
# Multi-language greeting patterns (EN + RU)
# ─────────────────────────────────────────────────────────────────────────────

# Patterns for direct (no-retrieval) queries. Both EN and RU.
DIRECT_PATTERNS = [
    # English
    r"^(hi|hello|hey|good morning|good afternoon|good evening)\b",
    r"^(thank|thanks|thank you)\b",
    r"^(yes|no|ok|okay|sure)\b",
    r"^(bye|goodbye|see you)\b",
    r"^(what time|what date|what day)\b",
    r"^(how are you|how do you do)\b",
    r"^(help|menu|options)\b",
    # Russian
    r"^(привет|здравствуй|здравствуйте|добр(ое|ый)\s+(утро|день|вечер))\b",
    r"^(спасибо|благодарю)\b",
    r"^(да|нет|ок|окей|хорошо|ладно)\b",
    r"^(пока|до\s+свидания|до\s+встречи)\b",
    r"^(как\s+(дела|ты))\b",
    r"^(помощь|меню|справка)\b",
]

# ─────────────────────────────────────────────────────────────────────────────
# Domain-specific boosters (EN + RU)
# ─────────────────────────────────────────────────────────────────────────────

# Phrases that strongly suggest a complex query (multi-step retrieval).
COMPLEX_BOOSTERS = {
    # English
    "compare": 3,
    "contrast": 3,
    "differences between": 3,
    "vs": 2,
    "versus": 2,
    "pros and cons": 3,
    "advantages and disadvantages": 3,
    "step by step": 2,
    "explain the relationship": 3,
    "how does .* affect": 2,
    "what would happen if": 2,
    "first .* then .* finally": 2,
    "trade-?off": 2,
    "alternative": 1,
    "analyze": 2,
    "evaluate": 2,
    "benchmark": 2,
    # Russian
    "сравн": 3,
    "отлич": 3,
    "различи": 3,
    "против": 2,
    "плюсы и минусы": 3,
    "преимущества и недостатки": 3,
    "шаг за шагом": 2,
    "пошагово": 2,
    "как .* влияет": 2,
    "что будет если": 2,
    "альтернатив": 1,
    "анализ": 2,
    "оцен": 2,
}

# Phrases that suggest a simpler query (single-step RAG).
SIMPLE_BOOSTERS = {
    # English
    "what is": 2,
    "what are": 2,
    "how to": 1,
    "how do": 1,
    "how can": 1,
    "where is": 1,
    "when is": 1,
    "define": 2,
    "meaning of": 2,
    "list of": 1,
    "give me": 1,
    "show me": 1,
    "find": 1,
    # Russian
    "что такое": 2,
    "что это": 2,
    "как сделать": 1,
    "как настроить": 1,
    "как получить": 1,
    "где находится": 1,
    "определение": 2,
    "значение": 2,
    "список": 1,
    "покажи": 1,
    "найди": 1,
}

# Words/phrases that typically require retrieval (not exhaustive).
RETRIEVAL_KEYWORDS = [
    "document",
    "documentation",
    "guide",
    "manual",
    "specification",
    "config",
    "configuration",
    "setting",
    "parameter",
    "option",
    "error",
    "issue",
    "problem",
    "bug",
    "fix",
    "solution",
    "how to",
    "how do",
    "how can",
    "what is",
    "what are",
    "explain",
    "describe",
    "define",
    "meaning",
    "example",
    "sample",
    "template",
    "pattern",
    "version",
    "release",
    "changelog",
    "update",
    # Russian
    "документ",
    "документация",
    "руководство",
    "инструкция",
    "спецификация",
    "настройка",
    "параметр",
    "ошибка",
    "проблема",
    "решение",
    "пример",
    "шаблон",
    "версия",
    "обновление",
    # Russian question-starters that imply information needs
    "что такое",
    "что это",
    "как",
    "где",
    "когда",
    "почему",
    "зачем",
    "кто",
    "какой",
    "расскажи",
    "объясни",
]

# Cyrillic range for Russian-text detection.
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _has_cyrillic(text: str) -> bool:
    """Return True if the text contains any Cyrillic characters."""
    return bool(_CYRILLIC_RE.search(text))


def _word_count(text: str) -> int:
    """Whitespace-delimited word count. Works for EN and RU."""
    return len([w for w in text.split() if w])


def _sentence_count(text: str) -> int:
    """Approximate sentence count based on sentence-ending punctuation."""
    return max(1, len(re.findall(r"[.!?]+", text)))


def _syllable_count_en(word: str) -> int:
    """Approximate English syllable count using vowel groups."""
    word = word.lower().strip(".,;:!?\"'()[]{}")
    if not word:
        return 0
    # Drop trailing silent-e
    word = re.sub(r"e\b", "", word)
    syllables = len(re.findall(r"[aeiouy]+", word))
    return max(1, syllables)


def _syllable_count_ru(word: str) -> int:
    """Approximate Russian syllable count using vowel groups.

    Russian syllables map closely to vowel groups in the Cyrillic vowel set
    (а, е, ё, и, о, у, ы, э, ю, я). This is the standard heuristic used
    by readability tooling for Cyrillic text.
    """
    word = word.lower().strip(".,;:!?\"'()[]{}")
    if not word:
        return 0
    syllables = len(re.findall(r"[аеёиоуыэюя]+", word))
    return max(1, syllables)


def flesch_kincaid_grade(text: str) -> float:
    """Flesch-Kincaid grade level for English text.

    Returns 0.0 for empty text. Higher = more complex.
    """
    words = re.findall(r"[A-Za-z]+", text)
    if not words:
        return 0.0
    sentences = max(1, _sentence_count(text))
    syllables = sum(_syllable_count_en(w) for w in words)
    words_n = len(words)
    return 0.39 * (words_n / sentences) + 11.8 * (syllables / words_n) - 15.59


def russian_readability_grade(text: str) -> float:
    """Russian readability grade (Flesch-Kincaid style).

    Returns 0.0 for empty text. Higher = more complex.
    """
    words = re.findall(r"[А-Яа-яЁё]+", text)
    if not words:
        return 0.0
    sentences = max(1, _sentence_count(text))
    syllables = sum(_syllable_count_ru(w) for w in words)
    words_n = len(words)
    return 0.39 * (words_n / sentences) + 11.8 * (syllables / words_n) - 15.59


def complexity_score(query: str) -> int:
    """Heuristic complexity score in [1, 10].

    Combines lexical boosters (multi-language), word count, question count,
    and a readability signal (Flesch-Kincaid for EN, Cyrillic variant for RU).
    """
    text = query.strip()
    if not text:
        return 1

    text_lower = text.lower()
    score = 0

    # Word-count base
    words_n = _word_count(text)
    if words_n <= 2:
        score = 1
    elif words_n <= 5:
        score = 3
    elif words_n <= 10:
        score = 5
    elif words_n <= 18:
        score = 7
    else:
        score = 9

    # Domain boosters (multi-language)
    for phrase, boost in COMPLEX_BOOSTERS.items():
        if phrase in text_lower:
            score += boost
    for phrase, boost in SIMPLE_BOOSTERS.items():
        if phrase in text_lower:
            score -= boost

    # Multi-question indicator
    if text_lower.count("?") > 1:
        score += 2
    elif text_lower.count("?") == 1 and words_n > 8:
        score += 1

    # Readability penalty: long sentences with many syllables push complexity up.
    readability = russian_readability_grade(text) if _has_cyrillic(text) else flesch_kincaid_grade(text)
    if readability > 12:
        score += 2
    elif readability > 8:
        score += 1

    # Clamp into [1, 10]
    return max(1, min(10, int(round(score))))


class QueryComplexityRouter:
    """Route queries based on complexity level.

    Classification:
    - direct: Simple queries that don't need retrieval (greetings, FAQ)
    - single: Moderate queries needing single-step RAG
    - multi: Complex queries needing multi-step iterative RAG

    Usage:
        router = QueryComplexityRouter()
        strategy = router.classify("What is RAG?")  # Returns "single"
        strategy = router.classify("Hello")  # Returns "direct"
        score = router.score("Compare X and Y")  # Returns 7
    """

    # Patterns for direct (no-retrieval) queries (EN + RU)
    DIRECT_PATTERNS = DIRECT_PATTERNS

    # Keywords that suggest retrieval is needed (EN + RU)
    RETRIEVAL_KEYWORDS = RETRIEVAL_KEYWORDS

    # Complexity threshold for upgrading to "multi"
    MULTI_THRESHOLD = 7

    # Complexity threshold below which short queries skip retrieval
    DIRECT_THRESHOLD = 3

    def classify(self, query: str) -> Complexity:
        """Classify query complexity.

        Returns:
            "direct" - no retrieval needed
            "single" - single-step RAG
            "multi" - multi-step iterative RAG

        """
        query_lower = query.lower().strip()
        if not query_lower:
            return "direct"

        # 1. Direct (small talk / FAQ) patterns — exact and very short matches
        for pattern in self.DIRECT_PATTERNS:
            if re.match(pattern, query_lower):
                logger.debug("Query classified as 'direct': %s...", query[:50])
                return "direct"

        # 2. Compute the complexity score
        score = complexity_score(query)
        logger.debug("Query complexity score: %d for %r", score, query[:60])

        # 3. Very short queries without retrieval keywords → direct
        words = query_lower.split()
        has_retrieval_kw = any(kw in query_lower for kw in self.RETRIEVAL_KEYWORDS)
        if len(words) <= 3 and not has_retrieval_kw and score <= self.DIRECT_THRESHOLD:
            logger.debug("Query classified as 'direct' (short, no keywords): %s...", query[:50])
            return "direct"

        # 4. Threshold-based classification
        if score >= self.MULTI_THRESHOLD:
            logger.debug("Query classified as 'multi': %s...", query[:50])
            return "multi"
        logger.debug("Query classified as 'single': %s...", query[:50])
        return "single"

    def score(self, query: str) -> int:
        """Return the heuristic complexity score in [1, 10]."""
        return complexity_score(query)

    def get_retrieval_params(
        self,
        complexity: Complexity,
    ) -> dict[str, Any]:
        """Get retrieval parameters for the complexity level.

        Returns dict with:
        - retrieve: whether to retrieve
        - top_k: number of results to retrieve
        - rerank: whether to rerank
        - max_iterations: max retrieval iterations (for multi)
        """
        if complexity == "direct":
            return {
                "retrieve": False,
                "top_k": 0,
                "rerank": False,
                "max_iterations": 0,
            }
        if complexity == "single":
            return {
                "retrieve": True,
                "top_k": 10,
                "rerank": True,
                "max_iterations": 1,
            }
        # multi
        return {
            "retrieve": True,
            "top_k": 15,
            "rerank": True,
            "max_iterations": 3,
        }


# Global router instance
_query_router = QueryComplexityRouter()


def get_query_router() -> QueryComplexityRouter:
    """Get the global query complexity router."""
    return _query_router


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatible top-level helpers
# ─────────────────────────────────────────────────────────────────────────────


# These names mirror the slm.py helpers used elsewhere in the codebase so that
# downstream callers do not need to import from two places.
def score_query_complexity(query: str) -> int:  # pragma: no cover - thin wrapper
    """Backward-compatible alias for :func:`complexity_score`."""
    return complexity_score(query)


def dynamic_top_k_from_complexity(complexity: int, max_default: int = 50) -> int:
    """Map a 1-10 complexity score to a retrieval top_k value.

    Mapping:
      1 → 5, 2 → 5, 3 → 10, 4 → 10, 5 → 15,
      6 → 20, 7 → 25, 8 → 35, 9 → 40, 10 → 50
    """
    mapping = {1: 5, 2: 5, 3: 10, 4: 10, 5: 15, 6: 20, 7: 25, 8: 35, 9: 40, 10: 50}
    return mapping.get(complexity, max_default)


# Convenience: ensure unused math import doesn't get linted out
_ = math.log2(2)
