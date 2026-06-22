# proxy/app/rerank.py
"""
Модуль реранкинга для RAG-прокси.
Использует кросс-энкодер (Cross-Encoder) для точного ранжирования чанков.
Поддерживает:
- Пакетный реранкинг (batch processing)
- Кэширование результатов (Redis/in-memory)
- Автоматическую обрезку текста до max_length модели
"""
import logging
import hashlib
import json
from typing import List, Tuple, Optional, Any
from functools import lru_cache

try:
    from sentence_transformers import CrossEncoder
    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False

from app.config import (
    RERANKER_MODEL, RERANKER_MAX_LENGTH, RERANKER_BATCH_SIZE,
    USE_REDIS, REDIS_URL
)
from app.cache import CacheManager

logger = logging.getLogger(__name__)

# Глобальные объекты
reranker = None
cache_manager = None


def initialize_reranker():
    """Инициализирует кросс-энкодер и кэш (вызывается при старте прокси)."""
    global reranker, cache_manager
    if not CROSS_ENCODER_AVAILABLE:
        raise ImportError("sentence-transformers is required for cross-encoder")
    
    reranker = CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)
    logger.info(f"Cross-encoder {RERANKER_MODEL} loaded (max_length={RERANKER_MAX_LENGTH})")
    
    # Инициализация кэша (если используется Redis)
    if USE_REDIS and REDIS_URL:
        cache_manager = CacheManager(redis_url=REDIS_URL)
    else:
        cache_manager = CacheManager(use_redis=False)


def _truncate_text(text: str, max_tokens: int = None) -> str:
    """Обрезает текст до указанного количества токенов (приближённо)."""
    if max_tokens is None:
        max_tokens = RERANKER_MAX_LENGTH
    # Грубая оценка: 1 токен ~ 4 символа
    max_chars = max_tokens * 4
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _get_cache_key(query: str, chunk_text: str) -> str:
    """Генерирует ключ кэша для пары (запрос, чанк)."""
    content = f"{query}|{chunk_text}"
    return f"rerank:{hashlib.md5(content.encode()).hexdigest()}"


def rerank_chunks(
    query: str,
    chunks: List[str],
    top_k: int = 20,
    use_cache: bool = True
) -> List[int]:
    """
    Выполняет реранкинг списка чанков по релевантности запросу.
    
    :param query: поисковый запрос
    :param chunks: список текстов чанков
    :param top_k: количество лучших чанков после реранкинга
    :param use_cache: использовать ли кэш
    :return: индексы чанков в порядке убывания релевантности (первые top_k)
    """
    if not reranker:
        initialize_reranker()
    
    if not chunks:
        return []
    
    # Обрезаем тексты до максимальной длины модели
    truncated_chunks = [_truncate_text(chunk) for chunk in chunks]
    
    # Подготовка пар (запрос, чанк)
    pairs = [(query, chunk) for chunk in truncated_chunks]
    
    # Получение скоров с кэшированием
    scores = []
    if use_cache and cache_manager:
        for i, (q, c) in enumerate(pairs):
            cache_key = _get_cache_key(q, c)
            cached = cache_manager.get_sync(cache_key)
            if cached is not None:
                scores.append(float(cached))
            else:
                # Если нет в кэше, будем вычислять пачкой
                scores = None
                break
        if scores is None:
            # Вычисляем скоры для всех пар, где нет кэша
            # Для простоты вычисляем все заново, но можно вычислить только отсутствующие
            scores = reranker.predict(pairs)
            # Сохраняем в кэш
            for i, (q, c) in enumerate(pairs):
                cache_key = _get_cache_key(q, c)
                cache_manager.set_sync(cache_key, str(scores[i]), ttl=3600)
    else:
        scores = reranker.predict(pairs)
    
    # Сортировка индексов по убыванию скора
    indexed_scores = list(enumerate(scores))
    indexed_scores.sort(key=lambda x: x[1], reverse=True)
    
    # Возвращаем индексы top_k
    return [idx for idx, _ in indexed_scores[:top_k]]


def rerank_chunks_with_scores(
    query: str,
    chunks: List[str],
    top_k: int = 20,
    use_cache: bool = True
) -> List[Tuple[int, float]]:
    """
    Возвращает пары (индекс, score) для top_k чанков.
    """
    indices = rerank_chunks(query, chunks, top_k, use_cache)
    # Получаем скоры для этих индексов
    if not reranker:
        initialize_reranker()
    truncated = [_truncate_text(ch) for ch in chunks]
    pairs = [(query, truncated[i]) for i in indices]
    scores = reranker.predict(pairs)
    return list(zip(indices, scores.tolist()))


# Если кэш-менеджер не был инициализирован, создаём заглушку
if cache_manager is None:
    cache_manager = CacheManager(use_redis=False)


# Пример использования (для тестирования)
if __name__ == "__main__":
    # Тестовый запуск (требуется настроенная конфигурация)
    import sys
    sys.path.insert(0, ".")
    from app.config import set_test_config
    set_test_config()
    
    initialize_reranker()
    query = "Как настроить CI/CD pipeline?"
    chunks = [
        "CI/CD pipeline настраивается через файл .gitlab-ci.yml",
        "Docker позволяет контейнеризировать приложения",
        "Для автоматической сборки используйте GitLab Runners"
    ]
    indices = rerank_chunks(query, chunks, top_k=2)
    print(f"Top indices: {indices}")
    for i in indices:
        print(f"Score: {chunks[i]}")