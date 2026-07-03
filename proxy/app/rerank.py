# proxy/app/rerank.py
"""
Модуль реранкинга для RAG-прокси.
Использует кросс-энкодер (Cross-Encoder) для точного ранжирования чанков.
Поддерживает:
- Пакетный реранкинг (batch processing)
- Кэширование результатов (Redis/in-memory)
- Автоматическую обрезку текста до max_length модели
- Fine-tuning from HITL feedback data
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from sentence_transformers import CrossEncoder

    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False

from app.cache import CacheManager
from app.config import REDIS_URL, RERANKER_MAX_LENGTH, RERANKER_MODEL, USE_REDIS

logger = logging.getLogger(__name__)

RERANKER_FT_ENABLED = os.getenv("RERANKER_FT_ENABLED", "false").lower() == "true"
FEEDBACK_LOG_DIR = os.getenv("FEEDBACK_LOG_DIR", "./logs/feedback")
FT_MODEL_DIR = os.getenv("FT_MODEL_DIR", "./models/reranker_ft")

# Глобальные объекты
reranker = None
cache_manager = None


def initialize_reranker():
    """Инициализирует реранкер и кэш (вызывается при старте прокси).

    Uses remote_services.create_reranker() to select between remote HTTP service
    and local CrossEncoder with graceful fallback.
    """
    global reranker, cache_manager

    from app.remote_services import create_reranker

    reranker = create_reranker()
    reranker_name = getattr(reranker, "__class__", type(reranker)).__name__
    logger.info("Reranker initialized: %s", reranker_name)

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


def _call_reranker_safe(pairs: list[tuple[str, str]]) -> "list[float]":  # type: ignore[no-untyped-def]
    """Call reranker.predict() with circuit breaker protection.

    When the circuit breaker is open, returns neutral scores (0.5) for all pairs
    to allow graceful degradation of the ranking pipeline.
    """
    try:
        from app.circuit_breaker import get_breaker as _get_cb, CircuitBreakerOpenError

        return _get_cb("reranker").call_sync(lambda: reranker.predict(pairs))
    except ImportError:
        pass  # circuit_breaker module not available — direct call
    except CircuitBreakerOpenError:
        logger.warning("Reranker circuit breaker OPEN — returning neutral scores")
        return [0.5] * len(pairs)

    # Fallback: direct call without circuit breaker
    return reranker.predict(pairs)


def _get_cache_key(query: str, chunk_text: str) -> str:
    """Генерирует ключ кэша для пары (запрос, чанк)."""
    content = f"{query}|{chunk_text}"
    return f"rerank:{hashlib.md5(content.encode()).hexdigest()}"


def rerank_chunks(query: str, chunks: list[str], top_k: int = 20, use_cache: bool = True) -> list[int]:
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
            scores = _call_reranker_safe(pairs)
            # Сохраняем в кэш
            for i, (q, c) in enumerate(pairs):
                cache_key = _get_cache_key(q, c)
                cache_manager.set_sync(cache_key, str(scores[i]), ttl=3600)
    else:
        scores = _call_reranker_safe(pairs)

    # Сортировка индексов по убыванию скора
    indexed_scores = list(enumerate(scores))
    indexed_scores.sort(key=lambda x: x[1], reverse=True)

    # Возвращаем индексы top_k
    return [idx for idx, _ in indexed_scores[:top_k]]


def rerank_chunks_with_scores(
    query: str, chunks: list[str], top_k: int = 20, use_cache: bool = True
) -> list[tuple[int, float]]:
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


def collect_training_pairs() -> list[tuple[str, str, float]]:
    """Collect training pairs from HITL feedback logs for reranker fine-tuning.

    Reads JSON feedback files from FEEDBACK_LOG_DIR.
    Each feedback entry must have: query, chunks (list of {text, id}),
    positive_chunk_ids, negative_chunk_ids.

    :return: list of (query, chunk_text, score) tuples where score is 1.0 or 0.0
    """
    if not RERANKER_FT_ENABLED:
        return []

    feedback_dir = Path(FEEDBACK_LOG_DIR)
    if not feedback_dir.is_dir():
        logger.warning("Feedback directory not found: %s", FEEDBACK_LOG_DIR)
        return []

    pairs = []
    for fpath in sorted(feedback_dir.glob("*.json")):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read feedback file: %s", fpath)
            continue

        query = data.get("query", "")
        chunks = data.get("chunks", [])
        positive_ids = set(data.get("positive_chunk_ids", []))
        negative_ids = set(data.get("negative_chunk_ids", []))

        chunk_map = {c.get("id", ""): c.get("text", "") for c in chunks}

        for cid, text in chunk_map.items():
            if not text:
                continue
            if cid in positive_ids:
                pairs.append((query, text, 1.0))
            elif cid in negative_ids:
                pairs.append((query, text, 0.0))

    logger.info("Collected %d training pairs from HITL feedback", len(pairs))
    return pairs


def fine_tune_reranker(pairs: list[tuple[str, str, float]], epochs: int = 3) -> Any:
    """Fine-tune the cross-encoder reranker on pairs from HITL feedback.

    Uses SentenceTransformer CrossEncoder.fit() for training.
    Saves the fine-tuned model to FT_MODEL_DIR.

    :param pairs: list of (query, chunk_text, relevance_score) tuples
    :param epochs: number of training epochs
    :return: trained model path or None on failure
    """
    if not RERANKER_FT_ENABLED:
        logger.info("Reranker fine-tuning is disabled")
        return None

    if not pairs:
        logger.warning("No training pairs provided for fine-tuning")
        return None

    if not CROSS_ENCODER_AVAILABLE:
        logger.error("sentence-transformers not available for fine-tuning")
        return None

    global reranker
    if reranker is None:
        logger.warning("Reranker not initialized, loading model for fine-tuning")
        reranker = CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)

    try:
        train_inputs = [(q, c) for q, c, _ in pairs]
        train_scores = [s for _, _, s in pairs]

        logger.info("Fine-tuning reranker on %d pairs for %d epochs", len(pairs), epochs)
        reranker.fit(
            train_inputs=train_inputs,
            train_labels=train_scores,
            epochs=epochs,
            show_progress_bar=False,
        )

        output_dir = Path(FT_MODEL_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        reranker.save(str(output_dir))
        logger.info("Fine-tuned reranker saved to %s", output_dir)
        return str(output_dir)

    except Exception as e:
        logger.error("Reranker fine-tuning failed: %s", e)
        return None


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
        "Для автоматической сборки используйте GitLab Runners",
    ]
    indices = rerank_chunks(query, chunks, top_k=2)
    print(f"Top indices: {indices}")
    for i in indices:
        print(f"Score: {chunks[i]}")
