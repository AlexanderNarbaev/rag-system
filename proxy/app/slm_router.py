# proxy/app/slm_router.py
"""
Маршрутизация и вспомогательные задачи с использованием SLM (Small Language Model).
SLM используется для быстрых, дешёвых операций:
- Классификация интента
- Декомпозиция сложных запросов
- Переписывание запроса (лёгкая версия)
- Извлечение ключевых сущностей

Поддерживает локальный запуск (llama.cpp) и удалённый OpenAI-совместимый API.
"""
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

from app.config import SLM_ENDPOINT, SLM_MODEL_NAME, SLM_API_KEY, SLM_MAX_TOKENS

logger = logging.getLogger(__name__)


class IntentType(Enum):
    """Типы интентов пользователя."""
    FACTUAL = "factual"           # Простой факт (требует контекст)
    PROCEDURAL = "procedural"     # "как сделать" (требует инструкций)
    COMPARISON = "comparison"     # Сравнение нескольких сущностей
    SUMMARIZATION = "summarize"   # Суммаризация документа
    GREETING = "greeting"         # Приветствие/общие фразы
    UNKNOWN = "unknown"


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
        "temperature": temperature
    }
    
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"SLM call failed: {e}")
        return ""


def classify_intent(query: str) -> Tuple[IntentType, float]:
    """
    Классифицирует интент пользователя. Возвращает (тип, уверенность).
    """
    prompt = f"""Классифицируй следующий вопрос пользователя по типу:
- factual: вопрос о фактах, определении, дате, свойстве
- procedural: вопрос о том, как что-то сделать, инструкция, руководство
- comparison: сравнение двух или более сущностей
- summarize: запрос на суммаризацию документа, краткое изложение
- greeting: приветствие, благодарность, общая фраза без запроса информации

Вопрос: {query}

Ответь только одним словом из списка: factual, procedural, comparison, summarize, greeting.
"""
    result = _call_slm_sync(prompt, max_tokens=10, temperature=0).lower()
    confidence = 0.8  # простая эвристика
    for intent in IntentType:
        if intent.value == result:
            return intent, confidence
    return IntentType.UNKNOWN, 0.5


def decompose_query(query: str, max_subqueries: int = 3) -> List[str]:
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
    if intent in (IntentType.GREETING, IntentType.UNKNOWN):
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


def extract_entities_slm(query: str) -> List[str]:
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
        words = re.findall(r'\b[A-ZА-Я][A-Za-zА-Яа-я0-9_-]+\b', query)
        return words
    return []


def should_use_graph(intent: IntentType, query: str) -> bool:
    """
    Определяет, стоит ли использовать граф знаний для расширения.
    """
    # Если запрос содержит явные связи между сущностями
    relation_words = ["связан", "зависит", "использует", "относится", "принадлежит", "содержит"]
    has_relation = any(word in query.lower() for word in relation_words)
    return intent == IntentType.COMPARISON or has_relation


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