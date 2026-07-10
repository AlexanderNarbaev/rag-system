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
        raise ImportError("qdrant-client is required")

    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

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
    # Проверяем кэш
    if cache_manager:
        cached = cache_manager.get_sync(f"embed:{hashlib.md5(text.encode()).hexdigest()}")
        if cached:
            return json.loads(cached)
    vec = embedder.encode(text, normalize_embeddings=True).tolist()
    if cache_manager:
        cache_manager.set_sync(f"embed:{hashlib.md5(text.encode()).hexdigest()}", json.dumps(vec), ttl=3600)
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
            dense_results = _get_cb("qdrant").call_sync(
                lambda: qdrant_client.search(
                    collection_name=COLLECTION_NAME,
                    query_vector=("dense", dense_vec),
                    limit=top_k,
                    query_filter=q_filter,
                    with_payload=True,
                )
            )
        except CircuitBreakerOpenError:
            logger.warning("Qdrant circuit breaker OPEN — returning empty dense results")
            dense_results = []
    else:
        dense_results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=("dense", dense_vec),
            limit=top_k,
            query_filter=q_filter,
            with_payload=True,
        )

    # Sparse поиск (если поддерживается)
    sparse_vec = _compute_sparse_embedding(query)
    sparse_results = []
    if sparse_vec is not None:
        if _get_cb:
            try:
                sparse_results = _get_cb("qdrant").call_sync(
                    lambda: qdrant_client.search(
                        collection_name=COLLECTION_NAME,
                        query_vector=("sparse", sparse_vec),
                        limit=top_k,
                        query_filter=q_filter,
                        with_payload=True,
                    )
                )
            except CircuitBreakerOpenError:
                logger.warning("Qdrant circuit breaker OPEN — returning empty sparse results")
        else:
            sparse_results = qdrant_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=("sparse", sparse_vec),
                limit=top_k,
                query_filter=q_filter,
                with_payload=True,
            )

    # Слияние
    if sparse_results:
        fused = reciprocal_rank_fusion(dense_results, sparse_results)
        return fused[:top_k]
    else:
        return dense_results


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
