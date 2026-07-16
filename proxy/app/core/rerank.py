# proxy/app/rerank.py
"""
Reranking module for the RAG proxy.

Uses a Cross-Encoder model for precise chunk ranking. Supports batch processing,
result caching (Redis/in-memory), automatic text truncation to model max_length,
and fine-tuning from HITL feedback data.

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

from proxy.app.shared.cache import CacheManager
from proxy.app.shared.config import REDIS_URL, RERANKER_MAX_LENGTH, RERANKER_MODEL, USE_REDIS

logger = logging.getLogger(__name__)

RERANKER_FT_ENABLED = os.getenv("RERANKER_FT_ENABLED", "false").lower() == "true"
FEEDBACK_LOG_DIR = os.getenv("FEEDBACK_LOG_DIR", "./logs/feedback")
FT_MODEL_DIR = os.getenv("FT_MODEL_DIR", "./models/reranker_ft")

# Глобальные объекты
reranker: Any = None
cache_manager: "CacheManager | None" = None


def initialize_reranker() -> None:
    """Инициализирует реранкер и кэш (вызывается при старте прокси).

    Uses remote_services.create_reranker() to select between remote HTTP service
    and local CrossEncoder with graceful fallback.
    """
    global reranker, cache_manager

    from proxy.app.llm.remote_services import create_reranker

    reranker = create_reranker()
    reranker_name = getattr(reranker, "__class__", type(reranker)).__name__
    logger.info("Reranker initialized: %s", reranker_name)

    # Инициализация кэша (если используется Redis)
    if USE_REDIS and REDIS_URL:  # noqa: SIM108
        cache_manager = CacheManager(redis_url=REDIS_URL)
    else:
        cache_manager = CacheManager(use_redis=False)


def _truncate_text(text: str, max_tokens: int | None = None) -> str:
    """Обрезает текст до указанного количества токенов (приближённо)."""
    if max_tokens is None:
        max_tokens = RERANKER_MAX_LENGTH
    # Грубая оценка: 1 токен ~ 4 символа
    max_chars = max_tokens * 4
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _call_reranker_safe(pairs: list[tuple[str, str]]) -> list[float]:
    """Call reranker.predict() with circuit breaker protection.

    When the circuit breaker is open, returns neutral scores (0.5) for all pairs
    to allow graceful degradation of the ranking pipeline.
    """
    if reranker is None:
        return [0.5] * len(pairs)

    _circuit_breaker_available = False
    _circuit_breaker_error: type[Exception] = Exception

    try:
        from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError, get_breaker

        _circuit_breaker_available = True
        _circuit_breaker_error = CircuitBreakerOpenError
    except ImportError:
        pass

    if _circuit_breaker_available:
        try:
            result: list[float] = get_breaker("reranker").call_sync(lambda: reranker.predict(pairs))
            return result
        except _circuit_breaker_error:
            logger.warning("Reranker circuit breaker OPEN — returning neutral scores")
            return [0.5] * len(pairs)

    # Fallback: direct call without circuit breaker
    result = reranker.predict(pairs)
    return result


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
    scores: list[float] = []
    if use_cache and cache_manager:
        all_cached = True
        for _i, (q, c) in enumerate(pairs):
            cache_key = _get_cache_key(q, c)
            cached = cache_manager.get_sync(cache_key)
            if cached is not None:
                scores.append(float(cached))
            else:
                # Если нет в кэше, будем вычислять пачкой
                all_cached = False
                break
        if not all_cached:
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
    query: str,
    chunks: list[str],
    top_k: int = 20,
    use_cache: bool = True,
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
    if reranker is None:
        return list(zip(indices, [0.0] * len(indices), strict=False))
    scores_arr = reranker.predict(pairs)
    return list(zip(indices, scores_arr.tolist(), strict=False))


def cosine_similarity_single(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product: float = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def colbert_score(query_tokens: list[list[float]], doc_tokens: list[list[float]]) -> float:
    """
    Compute ColBERT late interaction score.
    Each query token attends to all document tokens, takes max, then sums.

    This is faster than cross-encoder and more accurate than bi-encoder.
    Based on: ColBERTv2 (Stanford 2022)
    """
    if not query_tokens or not doc_tokens:
        return 0.0

    total_score = 0.0
    for q_token in query_tokens:
        max_sim = 0.0
        for d_token in doc_tokens:
            # Cosine similarity between token embeddings
            sim = cosine_similarity_single(q_token, d_token)
            max_sim = max(max_sim, sim)
        total_score += max_sim

    return total_score / len(query_tokens)


def hybrid_rerank(
    query: str,
    documents: list[dict[str, Any]],
    colbert_weight: float = 0.3,
    cross_encoder_weight: float = 0.7,
) -> list[dict[str, Any]]:
    """
    Two-stage reranking:
    1. ColBERT late interaction (fast, token-level)
    2. Cross-encoder (precise, semantic-level)

    Combines scores with configurable weights.
    """
    if not documents:
        return []

    # Stage 1: ColBERT scores (if token embeddings available)
    colbert_scores = []
    for doc in documents:
        if "colbert_tokens" in doc.get("metadata", {}):
            score = colbert_score(
                doc["metadata"]["query_tokens"],
                doc["metadata"]["colbert_tokens"],
            )
            colbert_scores.append(score)
        else:
            colbert_scores.append(0.0)

    # Stage 2: Cross-encoder scores
    cross_scores = rerank_chunks(query, [d["text"] for d in documents])

    # Combine scores
    combined = []
    for i, doc in enumerate(documents):
        final_score = colbert_weight * colbert_scores[i] + cross_encoder_weight * cross_scores[i]
        doc["score"] = final_score
        doc["colbert_score"] = colbert_scores[i]
        doc["cross_encoder_score"] = cross_scores[i]
        combined.append(doc)

    # Sort by combined score
    combined.sort(key=lambda x: x["score"], reverse=True)
    return combined


class TwoStageReranker:
    """
    Two-stage reranking for optimal latency/quality tradeoff.

    Stage 1: Fast embedding-based scoring (30-50ms)
    Stage 2: Cross-encoder scoring (150-400ms) on top-K from stage 1

    Based on: https://habr.com/ru/articles/1024696/

    Usage:
        reranker = TwoStageReranker(
            fast_model="BAAI/bge-small-en-v1.5",
            cross_encoder_model="cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
        results = reranker.rerank(query, documents, final_top_k=5)
    """

    def __init__(
        self,
        fast_model: str | None = None,
        cross_encoder_model: str | None = None,
        fast_top_k: int = 20,
        final_top_k: int = 5,
    ):
        self.fast_model = fast_model
        self.cross_encoder_model = cross_encoder_model
        self.fast_top_k = fast_top_k
        self.final_top_k = final_top_k
        self._fast_encoder: Any = None
        self._cross_encoder: Any = None

    def _get_fast_encoder(self) -> Any:
        """Lazy-load fast embedding model."""
        if self._fast_encoder is None and self.fast_model:
            try:
                from sentence_transformers import SentenceTransformer

                self._fast_encoder = SentenceTransformer(self.fast_model)
                logger.info(f"Loaded fast encoder: {self.fast_model}")
            except Exception as e:
                logger.warning(f"Failed to load fast encoder: {e}")
        return self._fast_encoder

    def fast_score(self, query: str, documents: list[str]) -> list[float]:
        """
        Stage 1: Fast embedding-based scoring.
        Uses cosine similarity between query and document embeddings.
        """
        encoder = self._get_fast_encoder()
        if encoder is None:
            # Fallback: return uniform scores
            return [0.5] * len(documents)

        try:
            query_emb = encoder.encode(query, normalize_embeddings=True)
            doc_embs = encoder.encode(documents, normalize_embeddings=True)

            # Cosine similarity
            import numpy as np

            scores: list[float] = np.dot(doc_embs, query_emb).tolist()
            return scores
        except Exception as e:
            logger.warning(f"Fast scoring failed: {e}")
            return [0.5] * len(documents)

    def cross_encoder_score(self, query: str, documents: list[str]) -> list[float]:
        """Stage 2: Cross-encoder scoring (slow but accurate)."""
        indices = rerank_chunks(query, documents, top_k=len(documents))
        return [float(i) for i in indices]

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        text_key: str = "text",
    ) -> list[dict[str, Any]]:
        """
        Two-stage reranking:
        1. Fast embed scoring → select top fast_top_k
        2. Cross-encoder scoring → select final_top_k
        """
        if not documents:
            return []

        # Stage 1: Fast scoring
        texts = [doc.get(text_key, "") for doc in documents]
        fast_scores = self.fast_score(query, texts)

        # Sort by fast score and take top K
        scored_docs = list(zip(documents, fast_scores, strict=False))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        top_fast = scored_docs[: self.fast_top_k]

        # Stage 2: Cross-encoder scoring
        fast_top_texts = [doc.get(text_key, "") for doc, _ in top_fast]
        cross_scores = self.cross_encoder_score(query, fast_top_texts)

        # Combine scores (weighted)
        results = []
        for i, (doc, fast_score) in enumerate(top_fast):
            cross_score = cross_scores[i] if i < len(cross_scores) else 0.0
            # Weighted combination: 20% fast + 80% cross-encoder
            combined_score = 0.2 * fast_score + 0.8 * cross_score
            doc["fast_score"] = fast_score
            doc["cross_score"] = cross_score
            doc["score"] = combined_score
            results.append(doc)

        # Sort by combined score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[: self.final_top_k]


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

    Two modes:
    - GPU available: delegates to RerankerTrainer for LoRA fine-tuning (~5 MB adapter)
    - CPU only: full fine-tune via CrossEncoder.fit() (existing behavior)

    Saves the fine-tuned model/adapter to FT_MODEL_DIR.

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

    gpu_available = TORCH_AVAILABLE and torch.cuda.is_available()
    use_lora = gpu_available

    if use_lora and gpu_available:
        return _fine_tune_with_lora(pairs, epochs)

    return _fine_tune_full(pairs, epochs)


def _fine_tune_with_lora(pairs: list[tuple[str, str, float]], epochs: int = 3) -> Any:
    """LoRA fine-tune the reranker using RerankerTrainer (GPU mode)."""
    try:
        from proxy.app.model_evolution.env_profile import EnvProfile
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer
        from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig
    except ImportError as e:
        logger.error("Model evolution module not available: %s", e)
        return None

    output_dir = Path(FT_MODEL_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs_file = output_dir / "reranker_train.json"
    pairs_file.write_text(json.dumps(pairs, ensure_ascii=False))

    eval_count = max(1, int(len(pairs) * 0.2))
    eval_pairs = pairs[:eval_count]
    (output_dir / "reranker_eval.json").write_text(json.dumps(eval_pairs, ensure_ascii=False))

    config = TrainingConfig.from_profile(
        TrainerType.RERANKER,
        EnvProfile.PROD if torch.cuda.is_available() else EnvProfile.DEV,
        base_model=RERANKER_MODEL or "cross-encoder/ms-marco-MiniLM-L-6-v2",
        output_dir=str(output_dir),
        epochs=epochs,
        use_lora=True,
        lora_r=RERANKER_LORA_R,
        lora_alpha=RERANKER_LORA_ALPHA,
    )

    try:
        trainer = RerankerTrainer()
        job = trainer.train(config)
        if job.status == "completed":
            logger.info(
                "LoRA fine-tuned reranker saved to %s (mrr=%.4f, ndcg@10=%.4f)",
                job.artifact_uri,
                job.metrics.get("mrr", 0.0),
                job.metrics.get("ndcg_at_10", 0.0),
            )
            return job.artifact_uri
        else:
            logger.error("Reranker LoRA training failed: %s", job.error_message)
            return None
    except Exception as e:
        logger.error("Reranker LoRA training failed: %s", e)
        return None


def _fine_tune_full(pairs: list[tuple[str, str, float]], epochs: int = 3) -> Any:
    """Full fine-tune the reranker via CrossEncoder.fit() (CPU mode, existing behavior)."""
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

        logger.info("Fine-tuning reranker on %d pairs for %d epochs (full FT, CPU)", len(pairs), epochs)
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


RERANKER_LORA_R = 4
RERANKER_LORA_ALPHA = 8

# Пример использования (для тестирования)
if __name__ == "__main__":
    # Тестовый запуск (требуется настроенная конфигурация)
    import sys

    sys.path.insert(0, ".")
    from proxy.app.shared.config import set_test_config  # type: ignore[attr-defined]

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
