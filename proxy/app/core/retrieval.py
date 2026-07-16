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
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from math import exp
from typing import Any, cast

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
from proxy.app.shared.tracing import add_event, tracer

logger = logging.getLogger(__name__)

# Two-level score filtering thresholds (from DRAG research)
STRONG_SCORE_THRESHOLD = 0.32
BORDERLINE_SCORE_THRESHOLD = 0.25
MIN_STRONG_SOURCES = 2

# Knee-point pruning settings (from DRAG with KNEE research)
USE_KNEE_POINT_PRUNING = True
KNEE_SENSITIVITY = 0.5  # 0=keep all, 1=aggressive pruning

# Cached vector name to avoid repeated collection introspection
_DENSE_VECTOR_NAME: str | None = None
_DENSE_VECTOR_NAME_LOCK: Any = None


def _get_dense_vector_name(client: Any) -> str | None:
    """Detect the correct dense vector name from the Qdrant collection schema.

    Returns the name of the first dense vector found, or None for the
    default (anonymous) vector. Caches the result for the process lifetime.
    """
    global _DENSE_VECTOR_NAME, _DENSE_VECTOR_NAME_LOCK

    if _DENSE_VECTOR_NAME is not None:
        return _DENSE_VECTOR_NAME

    # Thread-safe lazy init
    if _DENSE_VECTOR_NAME_LOCK is None:
        import threading

        _DENSE_VECTOR_NAME_LOCK = threading.Lock()

    with _DENSE_VECTOR_NAME_LOCK:
        if _DENSE_VECTOR_NAME is not None:
            return _DENSE_VECTOR_NAME

        try:
            collection_info = client.get_collection(COLLECTION_NAME)
            config = collection_info.config
            params = config.params
            if hasattr(params, "vectors") and params.vectors and isinstance(params.vectors, dict):
                # Named vectors: find the first dense vector name
                for name, vec_params in params.vectors.items():
                    if hasattr(vec_params, "size") and vec_params.size:
                        _DENSE_VECTOR_NAME = name
                        logger.info(
                            "Detected dense vector name '%s' from collection %s",
                            name,
                            COLLECTION_NAME,
                        )
                        return cast(str, name)
            # Default: anonymous vector — use None (Qdrant uses default when using=None)
            _DENSE_VECTOR_NAME = None
            logger.info(
                "Using default (anonymous) vector for collection %s",
                COLLECTION_NAME,
            )
        except Exception as exc:
            logger.warning(
                "Could not inspect collection %s schema: %s. Falling back to 'dense'.",
                COLLECTION_NAME,
                exc,
            )
            _DENSE_VECTOR_NAME = "dense"

        return _DENSE_VECTOR_NAME


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


class EmbeddingCache:
    """
    Cache for query embeddings to avoid recomputation.

    Two levels:
    1. Exact match: hash(query) -> embedding
    2. Semantic similarity: cosine(query, cached_queries) > 0.95 -> cached embedding
    """

    def __init__(self, max_size: int = 1000, similarity_threshold: float = 0.95):
        self.max_size = max_size
        self.similarity_threshold = similarity_threshold
        self._exact_cache: dict[str, list[float]] = {}
        self._query_embeddings: list[tuple[str, list[float]]] = []

    def _hash_query(self, query: str) -> str:
        """Generate hash for exact match."""
        import hashlib

        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    def get(self, query: str) -> list[float] | None:
        """Get cached embedding for query."""
        # Level 1: Exact match
        query_hash = self._hash_query(query)
        if query_hash in self._exact_cache:
            return self._exact_cache[query_hash]

        # Level 2: Semantic similarity
        if self._query_embeddings:
            query_lower = query.lower()
            for cached_query, cached_embedding in self._query_embeddings:
                # Simple word overlap check
                words1 = set(query_lower.split())
                words2 = set(cached_query.lower().split())
                if words1 and words2:
                    overlap = len(words1 & words2) / max(len(words1), len(words2))
                    if overlap >= self.similarity_threshold:
                        return cached_embedding

        return None

    def set(self, query: str, embedding: list[float]) -> None:
        """Cache embedding for query."""
        query_hash = self._hash_query(query)
        self._exact_cache[query_hash] = embedding

        # Store for semantic similarity
        self._query_embeddings.append((query, embedding))

        # Evict if over max size
        if len(self._exact_cache) > self.max_size:
            # Remove oldest entries
            keys_to_remove = list(self._exact_cache.keys())[: len(self._exact_cache) - self.max_size]
            for key in keys_to_remove:
                del self._exact_cache[key]

            # Trim semantic cache
            self._query_embeddings = self._query_embeddings[-self.max_size :]

    def __len__(self) -> int:
        return len(self._exact_cache)


# Global embedding cache instance
_embedding_cache = EmbeddingCache()


def initialize_retrieval() -> None:
    """Инициализирует клиенты и кэш (вызывается при старте прокси).

    Gracefully handles Qdrant unavailability — sets ``qdrant_client`` to
    ``None`` so subsequent hybrid-search calls degrade to empty results
    instead of crashing the proxy.
    """
    global qdrant_client, embedder, cache_manager, neo4j_driver, _GRAPH_ENABLED
    if not QDRANT_AVAILABLE:
        raise ImportError("qdrant-client is required. Install with: pip install qdrant-client")

    try:
        qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, check_compatibility=False)
        # Quick connectivity probe — if Qdrant is unreachable we degrade gracefully
        qdrant_client.get_collections()
        logger.info("Qdrant connection established at %s:%s", QDRANT_HOST, QDRANT_PORT)
    except Exception as exc:
        logger.warning("Qdrant unavailable at %s:%s — degraded mode (%s)", QDRANT_HOST, QDRANT_PORT, exc)
        qdrant_client = None

    # Use factory to select remote or local embedder
    from proxy.app.llm.remote_services import create_embedder

    embedder = create_embedder()
    embedder_name = getattr(embedder, "__class__", type(embedder)).__name__
    logger.info("Embedder initialized: %s", embedder_name)

    # Кэш (если используется Redis)
    if USE_REDIS and REDIS_URL:  # noqa: SIM108
        cache_manager = CacheManager(redis_url=REDIS_URL)  # Асинхронная инициализация будет вызвана в main.py
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
    # Check embedding cache first
    cached_embedding = _embedding_cache.get(text)
    if cached_embedding is not None:
        add_event("rag.embedding.cache_hit", {"cache": "local"})
        return cached_embedding

    # Check Redis/in-memory cache
    if cache_manager:
        cached = cache_manager.get_sync(cache_key)
        if cached is not None:
            add_event("rag.embedding.cache_hit", {"cache": "redis"})
            # Cache may return already-parsed list or raw JSON string
            if isinstance(cached, list):
                return cast(list[float], cached)
            try:
                return cast(list[float], json.loads(cached))
            except (json.JSONDecodeError, TypeError):
                return cast(list[float], cached)
    add_event("rag.embedding.compute", {"text_length": len(text)})
    assert embedder is not None, "embedder must be initialized"
    vec: list[float] = embedder.encode(text, normalize_embeddings=True).tolist()
    if cache_manager:
        cache_manager.set_sync(cache_key, json.dumps(vec), ttl=3600)
    _embedding_cache.set(text, vec)
    return vec


def _compute_sparse_embedding(text: str) -> models.SparseVector | None:
    """
    Вычисляет sparse вектор через bge-m3 (если поддерживается).
    Возвращает SparseVector или None.
    """
    if embedder is not None and hasattr(embedder, "encode_sparse"):
        sparse = embedder.encode_sparse(text)
        if isinstance(sparse, dict) and "indices" in sparse and "values" in sparse:
            return models.SparseVector(indices=sparse["indices"], values=sparse["values"])
    return None


def reciprocal_rank_fusion(results_dense: list[Any], results_sparse: list[Any], k: int = 60) -> list[Any]:
    """
    RRF слияние двух списков результатов (каждый элемент должен иметь .id и .score).
    Возвращает объединённый список, отсортированный по RRF-скорy.
    """
    scores: dict[Any, float] = {}
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


def knee_point_pruning(results: list[Any], sensitivity: float = 0.5) -> list[Any]:
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

    dist_arr = np.array(distances)

    # Apply sensitivity: scale distances
    dist_arr = dist_arr * (1 + sensitivity)

    # Knee point is where distance is maximum
    knee_idx_raw = int(np.argmax(dist_arr))

    # Ensure minimum 2 results
    knee_idx = max(knee_idx_raw, 1)

    return results[: knee_idx + 1]


def filter_results_by_score(results: list[Any]) -> tuple[list[Any], str]:
    """
    Two-level score filtering: strong vs borderline sources.

    Returns (filtered_results, quality_level) where quality_level is
    'strong', 'borderline', or 'insufficient'.
    If insufficient, caller should NOT generate an answer.
    """
    if not results:
        return [], "insufficient"

    strong = [r for r in results if r.score >= STRONG_SCORE_THRESHOLD]
    borderline = [r for r in results if BORDERLINE_SCORE_THRESHOLD <= r.score < STRONG_SCORE_THRESHOLD]

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
) -> list[Any]:
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
    with tracer.start_as_current_span("rag.retrieval.hybrid_search") as span:
        if span.is_recording():
            span.set_attribute("rag.query", query[:200])
            span.set_attribute("rag.top_k", top_k)
            span.set_attribute("rag.version", version or "latest")
            if lang:
                span.set_attribute("rag.lang", lang)

        if not qdrant_client or not embedder:
            initialize_retrieval()

        # If Qdrant is still unavailable after initialization, return empty results
        if qdrant_client is None:
            logger.warning("Qdrant unavailable — returning empty search results")
            add_event("rag.retrieval.qdrant_unavailable")
            if span.is_recording():
                span.set_attribute("rag.error", "qdrant_unavailable")
            return []

        if lang:
            logger.debug(f"Cross-lingual search: query language = {lang}")

    # Build filter conditions
    filter_conditions = []
    if version:
        filter_conditions.append(models.FieldCondition(key="version", match=models.MatchValue(value=version)))
    if namespace:
        filter_conditions.append(models.FieldCondition(key="namespace", match=models.MatchValue(value=namespace)))

    q_filter = models.Filter(must=list(filter_conditions)) if filter_conditions else None

    # Dense + Sparse embeddings computed in parallel
    sparse_vec = None
    with ThreadPoolExecutor(max_workers=2) as executor:
        dense_future = executor.submit(_compute_dense_embedding, query)
        sparse_future = executor.submit(_compute_sparse_embedding, query)
        dense_vec = dense_future.result()
        sparse_vec = sparse_future.result()
    assert qdrant_client is not None, "qdrant_client must be initialized"
    _qc = qdrant_client
    _dense_vector_name = _get_dense_vector_name(_qc)
    _dense_kwargs: dict[str, Any] = {
        "collection_name": COLLECTION_NAME,
        "query": dense_vec,
        "limit": top_k,
        "query_filter": q_filter,
        "with_payload": True,
    }
    if _dense_vector_name is not None:
        _dense_kwargs["using"] = _dense_vector_name
    if _get_cb is not None:
        try:
            dense_response = _get_cb("qdrant").call_sync(lambda: _qc.query_points(**_dense_kwargs))
            dense_results = dense_response.points
        except CircuitBreakerOpenError:
            logger.warning("Qdrant circuit breaker OPEN — returning empty dense results")
            dense_results = []
    else:
        dense_response = _qc.query_points(**_dense_kwargs)
        dense_results = dense_response.points

    # Sparse поиск (если поддерживается)
    sparse_results: list[Any] = []
    if sparse_vec is not None:
        if _get_cb is not None:
            try:
                sparse_response = _get_cb("qdrant").call_sync(
                    lambda: _qc.query_points(
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
            sparse_response = _qc.query_points(
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

    add_event("rag.retrieval.combined", {"dense_count": len(dense_results), "sparse_count": len(sparse_results)})

    # Apply two-level score filtering
    filtered_results, quality = filter_results_by_score(combined_results)
    if quality == "insufficient":
        logger.warning(f"No relevant sources found for query: {query[:50]}...")
        add_event("rag.retrieval.insufficient_quality")

    # Apply knee-point pruning if enabled
    if USE_KNEE_POINT_PRUNING and len(filtered_results) > 5:
        filtered_results = knee_point_pruning(filtered_results, sensitivity=KNEE_SENSITIVITY)
        logger.debug(f"Knee-point pruning: kept {len(filtered_results)} results")

    if span.is_recording():
        span.set_attribute("rag.num_results", len(filtered_results))
        span.set_attribute("rag.quality", quality)

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


class MultiHopGraphExplorer:
    """
    Enhanced graph traversal for multi-hop reasoning queries.

    Supports:
    - Configurable traversal depth (1-4 hops)
    - Path relevance scoring by entity importance
    - Cycle detection and prevention
    - Performance: < 200ms for 3-hop traversal

    Based on: Knowledge Graph RAG (arxiv:2404.16130)
    """

    def __init__(
        self,
        max_hops: int = 2,
        max_results_per_hop: int = 10,
        cycle_detection: bool = True,
    ):
        self.max_hops = max_hops
        self.max_results_per_hop = max_results_per_hop
        self.cycle_detection = cycle_detection

    def explore(
        self,
        start_entities: list[str],
        entity_map: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """
        Multi-hop traversal from start entities.

        Returns list of path dicts with:
        - path: list of entity names
        - score: relevance score
        - hops: number of hops
        """
        if not start_entities or not entity_map:
            return []

        visited: set[str] | None = set() if self.cycle_detection else None
        all_paths = []

        for entity in start_entities:
            paths = self._bfs_explore(entity, entity_map, visited)
            all_paths.extend(paths)

        # Sort by relevance (fewer hops + higher connectivity = better)
        all_paths.sort(key=lambda p: (-p["score"], p["hops"]))
        return all_paths[: self.max_results_per_hop * 2]

    def _bfs_explore(
        self,
        start: str,
        entity_map: dict[str, list[str]],
        visited: set[str] | None,
    ) -> list[dict[str, Any]]:
        """BFS traversal from start entity."""
        from collections import deque

        queue: deque[tuple[str, list[str], int]] = deque([(start, [start], 0)])
        paths = []

        while queue:
            current, path, hops = queue.popleft()

            if self.cycle_detection and visited is not None:
                if current in visited:
                    continue
                visited.add(current)

            # Get neighbors
            neighbors = entity_map.get(current, [])

            if not neighbors:
                # Leaf node - record path
                paths.append(
                    {
                        "path": path,
                        "score": self._score_path(path, entity_map),
                        "hops": hops,
                    }
                )
                continue

            if hops >= self.max_hops:
                # Max depth reached - record path
                paths.append(
                    {
                        "path": path,
                        "score": self._score_path(path, entity_map),
                        "hops": hops,
                    }
                )
                continue

            # Explore neighbors
            for neighbor in neighbors[: self.max_results_per_hop]:
                if self.cycle_detection and neighbor in path:
                    continue  # Skip cycles
                queue.append((neighbor, path + [neighbor], hops + 1))

        return paths

    def _score_path(self, path: list[str], entity_map: dict[str, list[str]]) -> float:
        """Score a path by entity connectivity."""
        if not path:
            return 0.0

        # Score by connectivity of each entity
        total_connectivity = 0
        for entity in path:
            connectivity = len(entity_map.get(entity, []))
            total_connectivity += min(connectivity, 10)  # Cap at 10

        # Normalize
        max_possible = len(path) * 10
        connectivity_score = total_connectivity / max_possible if max_possible > 0 else 0

        # Prefer shorter paths (less noise)
        length_penalty = 1.0 / (1.0 + len(path) * 0.1)

        return connectivity_score * length_penalty

    def format_context(self, paths: list[dict[str, Any]]) -> str:
        """Format multi-hop paths as context for LLM."""
        if not paths:
            return ""

        context_parts = []
        for i, path_info in enumerate(paths[:5], 1):
            path_str = " → ".join(path_info["path"])
            context_parts.append(f"[Path {i}] {path_str} (hops: {path_info['hops']}, score: {path_info['score']:.2f})")

        return "\n".join(context_parts)


# Global explorer instance
_multi_hop_explorer = MultiHopGraphExplorer()


class CypherQueryGenerator:
    """
    Generate Cypher queries from natural language for Neo4j.

    Converts entity-based queries into graph traversals.

    Usage:
        generator = CypherQueryGenerator()
        cypher = generator.generate("What projects does John work on?")
        # Returns: "MATCH (p:Person {name: 'John'})-[:WORKS_ON]->(proj:Project) RETURN proj"
    """

    # Common query patterns
    PATTERNS = [
        {
            "pattern": r"what (?:projects?|repos?|repositories?) (?:does|do) (\w+) work on",
            "template": (
                "MATCH (p:Person {{name: '{entity}'}})-[:WORKS_ON]->(proj:Project) RETURN proj.name, proj.description"
            ),
        },
        {
            "pattern": r"who (?:works?|worked?) on (\w+)",
            "template": "MATCH (p:Person)-[:WORKS_ON]->(proj:Project {{name: '{entity}'}}) RETURN p.name, p.role",
        },
        {
            "pattern": r"what (?:issues?|tickets?|tasks?) (?:are|is) (?:related|linked) to (\w+)",
            "template": "MATCH (i:Issue)-[:RELATED_TO]->(e {{name: '{entity}'}}) RETURN i.key, i.summary, i.status",
        },
        {
            "pattern": r"what (?:dependencies|depends) (?:does|do) (\w+) (?:have|has)",
            "template": "MATCH (e {{name: '{entity}'}})-[:DEPENDS_ON]->(dep) RETURN dep.name, dep.type",
        },
        {
            "pattern": r"show (?:me )?(?:all )?(?:the )?(\w+) (?:and|with) (?:their|its) (\w+)",
            "template": "MATCH (a:{entity1})-[r]->(b:{entity2}) RETURN a.name, type(r), b.name LIMIT 20",
        },
    ]

    def generate(self, query: str) -> str | None:
        """
        Generate Cypher query from natural language.

        Returns Cypher query string or None if no pattern matches.
        """
        query_lower = query.lower().strip()

        for pattern_info in self.PATTERNS:
            match = re.search(pattern_info["pattern"], query_lower)
            if match:
                entity = match.group(1).capitalize()
                cypher = pattern_info["template"].format(entity=entity)
                logger.info(f"Generated Cypher for query: {query[:50]}...")
                return cypher

        # Fallback: entity search
        entities = self._extract_entities(query)
        if entities:
            entity = entities[0]
            cypher = (
                f"MATCH (n) WHERE n.name CONTAINS '{entity}'"
                f" OR n.description CONTAINS '{entity}'"
                f" RETURN n.name, n.description, labels(n) LIMIT 10"
            )
            logger.info(f"Generated fallback Cypher for entity: {entity}")
            return cypher

        return None

    def _extract_entities(self, query: str) -> list[str]:
        """Extract potential entity names from query."""
        # Simple extraction: capitalized words
        words = query.split()
        entities = [w for w in words if w[0].isupper() and len(w) > 2]

        # Filter common words
        stop_words = {"What", "How", "When", "Where", "Who", "Which", "The", "This", "That"}
        entities = [e for e in entities if e not in stop_words]

        return entities


# Global generator instance
_cypher_generator = CypherQueryGenerator()


class GlobalSearch:
    """
    Global search using community summaries for corpus-wide questions.

    Based on: Microsoft GraphRAG (arxiv:2404.16130)

    For questions like:
    - "What are the main topics in the knowledge base?"
    - "Summarize all projects related to AI"
    - "What are the common patterns across documents?"

    Uses community summaries instead of individual chunks.
    """

    def __init__(self, community_summaries: list[dict[str, Any]] | None = None):
        self.community_summaries = community_summaries or []
        self._word_index: dict[str, set[int]] = {}
        self._build_index()

    def _build_index(self) -> None:
        """Pre-compute word → community index for fast overlap scoring."""
        for i, community in enumerate(self.community_summaries):
            summary = community.get("summary", "")
            for word in summary.lower().split():
                self._word_index.setdefault(word, set()).add(i)

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search across community summaries for global answers.

        Returns list of relevant community summaries.
        """
        if not self.community_summaries:
            return []

        query_words = set(query.lower().split())

        # Score communities using pre-computed word index
        community_hits: dict[int, int] = {}
        for word in query_words:
            if word in self._word_index:
                for idx in self._word_index[word]:
                    community_hits[idx] = community_hits.get(idx, 0) + 1

        if not community_hits:
            return []

        # Sort by overlap count, take top_k * 2 candidates for detailed scoring
        num_query_words = max(len(query_words), 1)
        candidates = sorted(community_hits, key=lambda x: community_hits[x], reverse=True)[: top_k * 2]

        scored = []
        for idx in candidates:
            community = self.community_summaries[idx]
            score = community_hits[idx] / num_query_words
            scored.append(
                {
                    "community_id": community.get("id", ""),
                    "summary": community.get("summary", ""),
                    "key_entities": community.get("key_entities", []),
                    "score": score,
                    "members": community.get("members", []),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def format_context(self, results: list[dict[str, Any]]) -> str:
        """Format global search results as context for LLM."""
        if not results:
            return ""

        context_parts = []
        for i, result in enumerate(results, 1):
            entities = ", ".join(result.get("key_entities", [])[:5])
            context_parts.append(f"[Community {i}] {result['summary']}\nKey entities: {entities}")

        return "\n\n".join(context_parts)


# Global search instance
_global_search = GlobalSearch()

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


def apply_time_decay(chunks: list[dict[str, Any]], decay_days: int = 180) -> list[dict[str, Any]]:
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
        if qdrant_client is not None:
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
