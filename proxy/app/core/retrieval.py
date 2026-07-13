# proxy/app/retrieval.py
"""
Retrieval module for the RAG proxy.

Implements hybrid search (dense + sparse) with RRF fusion, embedding cache
via Redis/In-Memory, optional graph expansion via Neo4j, and Qdrant integration
for nearest-neighbor search with version filtering.

Модуль поиска для RAG-прокси.
Реализует:
- Гибридный поиск (dense + sparse) с RRF-слиянием
- Кэширование эмбеддингов через Redis/In-Memory
- Опциональное графовое расширение (Neo4j)
- Интеграцию с Qdrant (ближний сосед + фильтрация по версии)
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from math import exp

import numpy as np

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

# Импорт конфигурации (будет создан отдельно)
from proxy.app.shared.cache import CacheManager
from proxy.app.shared.config import (
    COLLECTION_NAME,
    GRAPH_ENABLED,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_HOST,
    QDRANT_PORT,
    REDIS_URL,
    USE_REDIS,
)

logger = logging.getLogger(__name__)

# Two-level score filtering thresholds (from DRAG research)
STRONG_SCORE_THRESHOLD = 0.32
BORDERLINE_SCORE_THRESHOLD = 0.25
MIN_STRONG_SOURCES = 2

# Knee-point pruning settings (from DRAG with KNEE research)
USE_KNEE_POINT_PRUNING = True
KNEE_SENSITIVITY = 0.5  # 0=keep all, 1=aggressive pruning

# Глобальные объекты (инициализируются при старте)
qdrant_client = None
embedder = None
cache_manager = None

# Для графа (опционально)
neo4j_driver = None
_GRAPH_ENABLED = GRAPH_ENABLED
if _GRAPH_ENABLED:
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.warning("Neo4j driver not installed, graph expansion disabled")
        _GRAPH_ENABLED = False

# Circuit breaker for Qdrant service calls (graceful degradation)
try:
    from proxy.app.shared.circuit_breaker import CircuitBreakerOpenError
    from proxy.app.shared.circuit_breaker import get_breaker as _get_cb  # noqa: F811
except ImportError:
    _get_cb = None  # type: ignore[assignment]
    CircuitBreakerOpenError = RuntimeError  # type: ignore[assignment,misc]


def initialize_retrieval() -> None:
    """Инициализирует клиенты и кэш (вызывается при старте прокси)."""
    global qdrant_client, embedder, cache_manager, neo4j_driver, _GRAPH_ENABLED
    if not QDRANT_AVAILABLE:
        raise ImportError("qdrant-client is required. Install with: pip install qdrant-client")

    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, check_compatibility=False)

    # Use factory to select remote or local embedder
    from proxy.app.llm.remote_services import create_embedder

    embedder = create_embedder()
    embedder_name = getattr(embedder, "__class__", type(embedder)).__name__
    logger.info("Embedder initialized: %s", embedder_name)

    # Кэш (если используется Redis)
    if USE_REDIS and REDIS_URL:  # noqa: SIM108
        cache_manager = CacheManager(redis_url=REDIS_URL)
        # Асинхронная инициализация будет вызвана в main.py
    else:
        cache_manager = CacheManager(use_redis=False)

    # Граф Neo4j
    if _GRAPH_ENABLED:
        try:
            neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            neo4j_driver.verify_connectivity()
            logger.info("Neo4j driver initialized")
        except Exception as e:
            logger.warning(f"Neo4j connection failed: {e}. Graph expansion disabled.")
            _GRAPH_ENABLED = False


def _compute_dense_embedding(text: str) -> list[float]:
    """Вычисляет dense вектор с кэшированием."""
    cache_key = f"embed:{hashlib.md5(text.encode()).hexdigest()}"
    # Проверяем кэш
    if cache_manager:
        cached = cache_manager.get_sync(cache_key)
        if cached is not None:
            # Cache may return already-parsed list or raw JSON string
            if isinstance(cached, list):
                return cached
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, TypeError):
                return cached
    vec = embedder.encode(text, normalize_embeddings=True).tolist()
    if cache_manager:
        cache_manager.set_sync(cache_key, json.dumps(vec), ttl=3600)
    return vec


def _compute_sparse_embedding(text: str) -> models.SparseVector | None:
    """
    Вычисляет sparse вектор через bge-m3 (если поддерживается).
    Возвращает SparseVector или None.
    """
    if hasattr(embedder, "encode_sparse"):
        sparse = embedder.encode_sparse(text)
        if isinstance(sparse, dict) and "indices" in sparse and "values" in sparse:
            return models.SparseVector(indices=sparse["indices"], values=sparse["values"])
    return None


def reciprocal_rank_fusion(results_dense: list, results_sparse: list, k: int = 60) -> list:
    """
    RRF слияние двух списков результатов (каждый элемент должен иметь .id и .score).
    Возвращает объединённый список, отсортированный по RRF-скорy.
    """
    scores = {}
    for rank, hit in enumerate(results_dense, start=1):
        scores[hit.id] = scores.get(hit.id, 0) + 1.0 / (k + rank)
    for rank, hit in enumerate(results_sparse, start=1):
        scores[hit.id] = scores.get(hit.id, 0) + 1.0 / (k + rank)
    # Сортировка по убыванию RRF score
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    # Восстанавливаем объекты из первого списка (или второго) – лучше по id достать из dense первым
    all_results = {hit.id: hit for hit in results_dense}
    all_results.update({hit.id: hit for hit in results_sparse})
    return [all_results[hid] for hid in sorted_ids if hid in all_results]


def knee_point_pruning(results: list, sensitivity: float = 0.5) -> list:
    """
    Dynamic top-k using knee-point detection on score curve.

    Finds the optimal cutoff point where score drops significantly.
    Based on DRAG with KNEE research: https://habr.com/ru/articles/1016438/

    Args:
        results: List of results with 'score' field, sorted by score desc
        sensitivity: 0-1, how aggressively to prune (0=keep all, 1=standard knee)

    Returns:
        Pruned results up to the knee point
    """
    if len(results) <= 2:
        return results

    scores = np.array([r.score for r in results])
    n = len(scores)

    # Normalize scores to 0-1
    if scores.max() == scores.min():
        return results[: max(2, int(n * sensitivity))]

    y_norm = (scores - scores.min()) / (scores.max() - scores.min())
    x_norm = np.linspace(0, 1, n)

    # Line from first to last point
    p1 = np.array([x_norm[0], y_norm[0]])
    p2 = np.array([x_norm[-1], y_norm[-1]])
    line_vec = p2 - p1
    line_len = np.linalg.norm(line_vec)

    if line_len == 0:
        return results[: max(2, int(n * sensitivity))]

    line_unit = line_vec / line_len

    # Distance of each point from the line
    distances = []
    for i in range(n):
        point = np.array([x_norm[i], y_norm[i]])
        vec_to_point = point - p1
        # Project onto line, find perpendicular distance
        proj_length = np.dot(vec_to_point, line_unit)
        proj_point = p1 + proj_length * line_unit
        dist = np.linalg.norm(point - proj_point)
        distances.append(dist)

    distances = np.array(distances)

    # Apply sensitivity: scale distances
    distances = distances * (1 + sensitivity)

    # Knee point is where distance is maximum
    knee_idx = np.argmax(distances)

    # Ensure minimum 2 results
    knee_idx = max(knee_idx, 1)

    return results[: knee_idx + 1]


def filter_results_by_score(results: list) -> tuple[list, str]:
    """
    Two-level score filtering: strong vs borderline sources.

    Returns (filtered_results, quality_level) where quality_level is
    'strong', 'borderline', or 'insufficient'.
    If insufficient, caller should NOT generate an answer.
    """
    if not results:
        return [], "insufficient"

    strong = [r for r in results if r.score >= STRONG_SCORE_THRESHOLD]
    borderline = [
        r for r in results if BORDERLINE_SCORE_THRESHOLD <= r.score < STRONG_SCORE_THRESHOLD
    ]

    if len(strong) >= MIN_STRONG_SOURCES:
        # Good quality — use strong + some borderline
        return strong + borderline[:2], "strong"
    elif strong:
        # Some strong sources but not enough
        return strong + borderline[:1], "borderline"
    elif borderline:
        # Only borderline sources
        return borderline[:3], "borderline"
    else:
        # No relevant sources
        return [], "insufficient"


def hybrid_search(
    query: str,
    version: str | None = None,
    top_k: int = 50,
    namespace: str | None = None,
    lang: str | None = None,
) -> list:
    """
    Гибридный поиск в Qdrant: dense + sparse.
    Фильтрация по версии и namespace (для мультитенантности).
    Поддержка кросс-языкового поиска через bge-m3.
    Возвращает список объектов Qdrant ScoredPoint.

    Args:
        query: Search query text.
        version: Optional version filter.
        top_k: Maximum number of results.
        namespace: Optional tenant namespace filter.
        lang: Optional detected language code (for logging/metrics).
              bge-m3 supports cross-lingual retrieval natively —
              a query in German can find chunks in English.
    """
    if not qdrant_client or not embedder:
        initialize_retrieval()

    if lang:
        logger.debug(f"Cross-lingual search: query language = {lang}")

    # Build filter conditions
    filter_conditions = []
    if version:
        filter_conditions.append(models.FieldCondition(key="version", match=models.MatchValue(value=version)))
    if namespace:
        filter_conditions.append(models.FieldCondition(key="namespace", match=models.MatchValue(value=namespace)))

    q_filter = models.Filter(must=filter_conditions) if filter_conditions else None

    # Dense поиск
    dense_vec = _compute_dense_embedding(query)
    if _get_cb:
        try:
            dense_response = _get_cb("qdrant").call_sync(
                lambda: qdrant_client.query_points(
                    collection_name=COLLECTION_NAME,
                    query=dense_vec,
                    using="dense",
                    limit=top_k,
                    query_filter=q_filter,
                    with_payload=True,
                )
            )
            dense_results = dense_response.points
        except CircuitBreakerOpenError:
            logger.warning("Qdrant circuit breaker OPEN — returning empty dense results")
            dense_results = []
    else:
        dense_response = qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_vec,
            using="dense",
            limit=top_k,
            query_filter=q_filter,
            with_payload=True,
        )
        dense_results = dense_response.points

    # Sparse поиск (если поддерживается)
    sparse_vec = _compute_sparse_embedding(query)
    sparse_results = []
    if sparse_vec is not None:
        if _get_cb:
            try:
                sparse_response = _get_cb("qdrant").call_sync(
                    lambda: qdrant_client.query_points(
                        collection_name=COLLECTION_NAME,
                        query=sparse_vec,
                        using="sparse",
                        limit=top_k,
                        query_filter=q_filter,
                        with_payload=True,
                    )
                )
                sparse_results = sparse_response.points
            except CircuitBreakerOpenError:
                logger.warning("Qdrant circuit breaker OPEN — returning empty sparse results")
        else:
            sparse_response = qdrant_client.query_points(
                collection_name=COLLECTION_NAME,
                query=sparse_vec,
                using="sparse",
                limit=top_k,
                query_filter=q_filter,
                with_payload=True,
            )
            sparse_results = sparse_response.points

    # Слияние
    if sparse_results:
        combined_results = reciprocal_rank_fusion(dense_results, sparse_results)[:top_k]
    else:
        combined_results = dense_results

    # Apply two-level score filtering
    filtered_results, quality = filter_results_by_score(combined_results)
    if quality == "insufficient":
        logger.warning(f"No relevant sources found for query: {query[:50]}...")

    # Apply knee-point pruning if enabled
    if USE_KNEE_POINT_PRUNING and len(filtered_results) > 5:
        filtered_results = knee_point_pruning(filtered_results, sensitivity=KNEE_SENSITIVITY)
        logger.debug(f"Knee-point pruning: kept {len(filtered_results)} results")

    return filtered_results


def graph_expand_query(query: str, max_entities: int = 5) -> str:
    """
    Расширяет запрос с помощью графа знаний (Neo4j).
    Извлекает связанные сущности из графа и возвращает их в виде текста.
    """
    if not _GRAPH_ENABLED or not neo4j_driver:
        return ""

    # Извлекаем ключевые слова из запроса (простейшая эвристика)
    # В реальном применении лучше использовать NER или запрос к графу по full-text поиску
    keywords = [w for w in query.split() if len(w) > 3][:3]
    if not keywords:
        return ""

    # Cypher запрос: ищем сущности, связанные с этими ключевыми словами
    cypher = """
    MATCH (e:Entity)
    WHERE e.name CONTAINS $keyword OR ANY(k in $keywords WHERE e.name CONTAINS k)
    OPTIONAL MATCH (e)-[r]-(related:Entity)
    RETURN e.name as entity, e.type as type, collect(DISTINCT related.name) as related
    LIMIT $limit
    """
    context_lines = []
    with neo4j_driver.session() as session:
        for kw in keywords:
            result = session.run(cypher, {"keyword": kw, "keywords": keywords, "limit": max_entities})
            for record in result:
                entity = record["entity"]
                etype = record["type"]
                related = record["related"][:3]
                if related:
                    context_lines.append(f"- {entity} ({etype}) связан с: {', '.join(related)}")
                else:
                    context_lines.append(f"- {entity} ({etype})")
    if context_lines:
        return "Связанные сущности из графа знаний:\n" + "\n".join(context_lines)
    return ""


# Если нужен синхронный доступ к кэшу, добавим методы в CacheManager
# Для совместимости с уже написанным кодом, добавим синхронные обёртки
if cache_manager is None:
    cache_manager = CacheManager(use_redis=False)


def _parse_timestamp(value: str | int | float | None) -> float | None:
    """Parse a timestamp from a string or numeric value, returning Unix epoch seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def apply_time_decay(chunks: list[dict], decay_days: int = 180) -> list[dict]:
    """Boost scores for newer chunks, decay older ones.

    Uses exponential decay: boost = exp(-age_days / decay_days).
    Looks for 'updated_at' or 'created_at' in chunk payload or top-level fields.
    """
    if not chunks:
        return chunks

    now = datetime.now(timezone.utc).timestamp()  # noqa: UP017
    result = []
    for chunk in chunks:
        payload = chunk.get("payload", {})
        ts_raw = (
            payload.get("updated_at") or payload.get("created_at") or chunk.get("updated_at") or chunk.get("created_at")
        )
        ts = _parse_timestamp(ts_raw)
        if ts is None:
            result.append(chunk)
            continue

        age_seconds = now - ts
        age_days = max(0, age_seconds / 86400)
        boost = exp(-age_days / decay_days)
        boosted = dict(chunk)
        boosted["score"] = chunk.get("score", 0.0) * (1.0 + boost)
        boosted["time_boost"] = boost
        result.append(boosted)

    return result


# Утилита для проверки доступности Qdrant
def check_qdrant_health() -> bool:
    try:
        qdrant_client.get_collections()
        return True
    except Exception:
        return False


def compute_dynamic_top_k(query: str, default: int = 50) -> int:
    """
    Compute the optimal number of chunks to retrieve based on query complexity.

    Uses SLM-based complexity scoring when available, falling back to
    word-count heuristics.

    Args:
        query: The user query string.
        default: Fallback top_k when complexity scoring is unavailable.

    Returns:
        Optimal top_k value (between 5 and 50).
    """
    from proxy.app.llm.slm import dynamic_top_k_from_complexity, score_query_complexity

    try:
        complexity = score_query_complexity(query)
        return dynamic_top_k_from_complexity(complexity, max_default=default)
    except Exception:
        logger.warning("Dynamic top-k computation failed, using default", exc_info=True)
        return default
