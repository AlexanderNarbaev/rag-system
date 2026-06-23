# proxy/app/retrieval.py
"""
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

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer

    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

# Импорт конфигурации (будет создан отдельно)
from app.cache import CacheManager
from app.config import (
    COLLECTION_NAME,
    EMBEDDER_DEVICE,
    EMBEDDER_MODEL,
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


def initialize_retrieval():
    """Инициализирует клиенты и кэш (вызывается при старте прокси)."""
    global qdrant_client, embedder, cache_manager, neo4j_driver, _GRAPH_ENABLED
    if not QDRANT_AVAILABLE:
        raise ImportError("qdrant-client is required")
    if not ST_AVAILABLE:
        raise ImportError("sentence-transformers is required")

    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    embedder = SentenceTransformer(EMBEDDER_MODEL, device=EMBEDDER_DEVICE)
    logger.info(f"Embedder {EMBEDDER_MODEL} loaded on {EMBEDDER_DEVICE}")

    # Кэш (если используется Redis)
    if USE_REDIS and REDIS_URL:
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


def hybrid_search(query: str, version: str | None = None, top_k: int = 50) -> list:
    """
    Гибридный поиск в Qdrant: dense + sparse.
    Возвращает список объектов Qdrant ScoredPoint.
    """
    if not qdrant_client or not embedder:
        initialize_retrieval()

    # Построение фильтра по версии (если указана)
    q_filter = None
    if version:
        q_filter = models.Filter(must=[models.FieldCondition(key="version", match=models.MatchValue(value=version))])

    # Dense поиск
    dense_vec = _compute_dense_embedding(query)
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


# Утилита для проверки доступности Qdrant
def check_qdrant_health() -> bool:
    try:
        qdrant_client.get_collections()
        return True
    except Exception:
        return False
