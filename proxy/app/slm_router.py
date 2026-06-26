# proxy/app/slm_router.py
"""
Маршрутизация и вспомогательные задачи с использованием SLM (Small Language Model).
SLM используется для быстрых, дешёвых операций:
- Классификация интента
- Декомпозиция сложных запросов
- Переписывание запроса (лёгкая версия)
- Извлечение ключевых сущностей

Поддерживает любой OpenAI-совместимый API (vLLM, llama.cpp, Ollama, LiteLLM и др.).
"""

import json
import logging
from enum import Enum

from app.config import SLM_API_KEY, SLM_ENDPOINT, SLM_MODEL_NAME

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Типы интентов пользователя."""

    GREETING = "greeting"  # Приветствие/общие фразы
    SIMPLE_FACT = "simple_fact"  # Простой факт (да/нет, определение)
    FACTUAL = "factual"  # Простой факт (требует контекст)
    PROCEDURAL = "procedural"  # "как сделать" (требует инструкций)
    COMPARISON = "comparison"  # Сравнение нескольких сущностей
    SUMMARIZATION = "summarize"  # Суммаризация документа
    COMPLEX = "complex"  # Многочастный запрос, требующий декомпозиции
    UNKNOWN = "unknown"


# Complexity scores for each intent type (1-10)
INTENT_COMPLEXITY_MAP: dict[IntentType, int] = {
    IntentType.GREETING: 1,
    IntentType.SIMPLE_FACT: 3,
    IntentType.FACTUAL: 5,
    IntentType.PROCEDURAL: 7,
    IntentType.COMPARISON: 8,
    IntentType.SUMMARIZATION: 6,
    IntentType.COMPLEX: 10,
    IntentType.UNKNOWN: 5,
}


# Вспомогательная функция для вызова SLM (синхронная, так как используется в основном коде)
def _call_slm_sync(prompt: str, max_tokens: int = 256, temperature: float = 0.1) -> str:
    """
    Вызов SLM в синхронном режиме. Поддерживает два режима:
    1. Локальный llama.cpp через subprocess (TODO)
    2. OpenAI-совместимый API (vLLM)
    """
    if not SLM_ENDPOINT:
        logger.warning("SLM endpoint not configured, falling back to heuristics")
        return ""

    import requests

    url = f"{SLM_ENDPOINT}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if SLM_API_KEY:
        headers["Authorization"] = f"Bearer {SLM_API_KEY}"

    payload = {
        "model": SLM_MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"SLM call failed: {e}")
        return ""


def classify_intent(query: str) -> tuple[IntentType, float]:
    """
    Классифицирует интент пользователя. Возвращает (тип, уверенность).
    """
    prompt = f"""Классифицируй следующий вопрос пользователя по типу:
- greeting: приветствие, благодарность, общая фраза без запроса информации
- simple_fact: простой вопрос да/нет или об одном известном понятии
- factual: вопрос о фактах, определении, дате, свойстве (требует поиска)
- procedural: вопрос о том, как что-то сделать, инструкция, руководство
- comparison: сравнение двух или более сущностей
- summarize: запрос на суммаризацию документа, краткое изложение
- complex: многочастный запрос, требующий разбора на подвопросы

Вопрос: {query}

Ответь только одним словом из списка: greeting, simple_fact, factual, procedural, comparison, summarize, complex.
"""
    result = _call_slm_sync(prompt, max_tokens=10, temperature=0).lower()
    confidence = 0.8  # простая эвристика
    for intent in IntentType:
        if intent.value == result:
            return intent, confidence
    return IntentType.UNKNOWN, 0.5


def get_complexity_score(intent: IntentType) -> int:
    """Return complexity score (1-10) for a given intent type."""
    return INTENT_COMPLEXITY_MAP.get(intent, 5)


def get_query_complexity(query: str) -> int:
    """Classify query intent and return its complexity score (1-10).
    Falls back to 5 if SLM is unavailable."""
    intent, _ = classify_intent(query)
    return get_complexity_score(intent)


def decompose_query(query: str, max_subqueries: int = 3) -> list[str]:
    """
    Разбивает сложный запрос на несколько подзапросов.
    Возвращает список подзапросов (строки).
    """
    prompt = f"""Разбей следующий сложный вопрос на {max_subqueries} простых подвопроса, которые можно искать отдельно.
Вопрос: {query}
Ответь в формате JSON список строк.

Пример: ["Подвопрос 1", "Подвопрос 2", "Подвопрос 3"]
"""
    result = _call_slm_sync(prompt, max_tokens=256)
    try:
        subqueries = json.loads(result)
        if isinstance(subqueries, list) and all(isinstance(q, str) for q in subqueries):
            return subqueries[:max_subqueries]
    except json.JSONDecodeError:
        # Пытаемся извлечь строки вручную
        import re

        lines = re.findall(r'"([^"]+)"', result)
        if lines:
            return lines[:max_subqueries]
    # Fallback: возвращаем исходный запрос
    return [query]


def needs_retrieval(intent: IntentType) -> bool:
    """
    Определяет, нужен ли поиск в базе знаний для данного интента.
    """
    if intent in (IntentType.GREETING, IntentType.SIMPLE_FACT, IntentType.UNKNOWN):
        return False
    return True


def rewrite_query_slm(query: str) -> str:
    """
    Переписывает запрос для улучшения ретривала.
    Более лёгкая версия, чем в orchestator, использует SLM.
    """
    prompt = f"""Перепиши следующий вопрос в эффективный поисковый запрос для технической документации.
Сохрани ключевые термины, номера задач, технологии.
Выдай только переписанный запрос, без пояснений.

Оригинал: {query}
Переписанный запрос:
"""
    rewritten = _call_slm_sync(prompt, max_tokens=100)
    if rewritten:
        return rewritten
    return query


def extract_entities_slm(query: str) -> list[str]:
    """
    Извлекает ключевые сущности (технологии, проекты, имена) из запроса.
    """
    prompt = f"""Извлеки из следующего вопроса ключевые сущности: технологии, проекты, номера задач, имена людей.
Верни ответ в виде JSON списка строк.

Вопрос: {query}

Пример: ["GitLab", "CI/CD", "PROJ-123", "Иван"]
"""
    result = _call_slm_sync(prompt, max_tokens=150)
    try:
        entities = json.loads(result)
        if isinstance(entities, list):
            return entities
    except json.JSONDecodeError:
        import re

        # Ищем слова с заглавной буквы или цифрами
        words = re.findall(r"\b[A-ZА-Я][A-Za-zА-Яа-я0-9_-]+\b", query)
        return words
    return []


def score_query_complexity(query: str) -> int:
    """
    Score query complexity on a 1-10 scale based on heuristics and SLM classification.

    Complexity factors:
    - Word count (more words = more complex)
    - Number of key comparison/relational words
    - Intent type (comparison/summarization > procedural > factual)
    - Question marks (multi-part questions)

    Returns:
        Complexity score from 1 (simple) to 10 (highly complex).
    """
    score = 1
    word_count = len(query.split())

    # Heuristic: word count contributes to complexity
    if word_count <= 3:
        score = 1
    elif word_count <= 6:
        score = 3
    elif word_count <= 12:
        score = 5
    elif word_count <= 20:
        score = 7
    else:
        score = 9

    # Comparison/relational words increase complexity
    comparison_words = [
        "сравн", "compar", "difference", "versus", "vs", "лучше", "better",
        "отличие", "difference", "плюсы", "минусы", "pros", "cons",
        "альтернатив", "alternative",
    ]
    query_lower = query.lower()
    comp_count = sum(1 for w in comparison_words if w in query_lower)
    score += min(comp_count, 3)

    # Multi-question indicator
    if query_lower.count("?") > 1 or query_lower.count("?") == 1 and word_count > 10:
        score += 1

    # SLM-based refinement (if available)
    try:
        intent, _ = classify_intent(query)
        if intent == IntentType.COMPARISON:
            score = max(score, 7)
        elif intent == IntentType.SUMMARIZATION:
            score = max(score, 6)
        elif intent == IntentType.PROCEDURAL:
            score = max(score, 5)
        elif intent == IntentType.FACTUAL:
            score = max(score, 3)
    except Exception:
        pass

    return max(1, min(10, score))


def dynamic_top_k_from_complexity(complexity: int, max_default: int = 50) -> int:
    """
    Map query complexity score (1-10) to a retrieval top_k value.

    Mapping:
      1 → 5, 2 → 5, 3 → 10, 4 → 10, 5 → 15,
      6 → 20, 7 → 25, 8 → 35, 9 → 40, 10 → 50
    """
    mapping = {1: 5, 2: 5, 3: 10, 4: 10, 5: 15, 6: 20, 7: 25, 8: 35, 9: 40, 10: 50}
    return mapping.get(complexity, max_default)


def should_use_graph(intent: IntentType, query: str) -> bool:
    """
    Определяет, стоит ли использовать граф знаний для расширения.
    """
    # Если запрос содержит явные связи между сущностями
    relation_words = ["связан", "зависит", "использует", "относится", "принадлежит", "содержит"]
    has_relation = any(word in query.lower() for word in relation_words)
    return intent == IntentType.COMPARISON or has_relation


# ── F2: Multilingual Intent Classification ──

_NON_EN_GREETING_PATTERNS = {
    "de": ["hallo", "guten tag", "guten morgen", "guten abend", "hi", "hey", "moin", "servus", "grüß"],
    "fr": ["bonjour", "bonsoir", "salut", "coucou", "hello", "hi"],
    "zh": ["你好", "您好", "嗨", "哈喽"],
}

_NON_EN_HOWTO_PATTERNS = {
    "de": ["wie", "anleitung", "konfigurieren", "einrichten", "erstellen", "installieren"],
    "fr": ["comment", "configurer", "installer", "créer", "mettre en place", "guide"],
    "zh": ["如何", "怎么", "怎样", "如何做", "攻略", "教程"],
}

_NON_EN_COMPARE_PATTERNS = {
    "de": ["vergleich", "unterschied", "besser", "schlechter", "vs", "oder"],
    "fr": ["comparaison", "différence", "mieux", "moins bien", "vs", "ou"],
    "zh": ["对比", "区别", "哪个更好", "比较", "差异"],
}


def classify_intent_multilingual(query: str) -> tuple[IntentType, float]:
    """Classify intent for any language, using linguistic heuristics for non-EN/RU.

    For EN and RU queries, delegates to the SLM-based classify_intent().
    For DE, FR, ZH queries, uses keyword-based heuristics with simplified
    intent mapping (GREETING, PROCEDURAL, COMPARISON, FACTUAL).

    Args:
        query: User query in any supported language.

    Returns:
        Tuple of (IntentType, confidence 0.0-1.0).
    """
    if not query:
        return IntentType.UNKNOWN, 0.0

    try:
        from app.i18n import detect_language
        lang = detect_language(query)
    except Exception:
        logger.warning("Language detection failed, falling back to classify_intent")
        return classify_intent(query)

    if lang in ("en", "ru"):
        return classify_intent(query)

    query_lower = query.lower()

    greetings = _NON_EN_GREETING_PATTERNS.get(lang, [])
    howto = _NON_EN_HOWTO_PATTERNS.get(lang, [])
    compare = _NON_EN_COMPARE_PATTERNS.get(lang, [])

    if any(g in query_lower for g in greetings):
        return IntentType.GREETING, 0.85

    if any(c in query_lower for c in compare):
        return IntentType.COMPARISON, 0.70

    if any(h in query_lower for h in howto):
        return IntentType.PROCEDURAL, 0.70

    return IntentType.FACTUAL, 0.50


# Пример использования
if __name__ == "__main__":
    # Требуется настроенный SLM_ENDPOINT
    test_query = "Как настроить CI/CD пайплайн в GitLab и чем он отличается от GitHub Actions?"
    intent, confidence = classify_intent(test_query)
    print(f"Intent: {intent.value}, confidence: {confidence}")

    subqueries = decompose_query(test_query, max_subqueries=3)
    print(f"Subqueries: {subqueries}")

    rewritten = rewrite_query_slm(test_query)
    print(f"Rewritten: {rewritten}")

    entities = extract_entities_slm(test_query)
    print(f"Entities: {entities}")

    print(f"Use graph: {should_use_graph(intent, test_query)}")
