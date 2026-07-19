# proxy/app/cache.py
"""Cache manager with Redis and in-memory fallback.

Used for:
- Embedding vectors (dense)
- Reranking results
- LLM responses (optional)
- Search queries (optional)

Provides both async and sync interfaces for backward compatibility.

Кэш-менеджер с поддержкой Redis и fallback на in-memory.
Используется для:
- Эмбеддингов (dense векторы)
- Результатов реранкинга
- Ответов LLM (опционально)
- Поисковых запросов (опционально)
"""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class InMemoryCache:
    """Simple in-memory cache with TTL expiration."""

    # Default TTL for cache entries (1 hour)
    DEFAULT_TTL_SECONDS = 3600

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expire_timestamp)

    def _is_expired(self, expire_ts: float) -> bool:
        return expire_ts < datetime.now(UTC).timestamp()

    def _get_value(self, key: str) -> Any | None:
        """Internal sync get — used by both async and sync interfaces."""
        if key not in self._store:
            return None
        value, expire_ts = self._store[key]
        if self._is_expired(expire_ts):
            del self._store[key]
            return None
        return value

    def _set_value(self, key: str, value: Any, ttl: int = 3600) -> bool:
        """Internal sync set — used by both async and sync interfaces."""
        expire_ts = datetime.now(UTC).timestamp() + ttl
        self._store[key] = (value, expire_ts)
        return True

    async def get(self, key: str) -> Any | None:
        return self._get_value(key)

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        return self._set_value(key, value, ttl)

    async def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def clear(self) -> None:
        self._store.clear()

    # Синхронные методы — InMemoryCache не требует asyncio (данные в памяти)
    def get_sync(self, key: str) -> Any | None:
        return self._get_value(key)

    def set_sync(self, key: str, value: Any, ttl: int = 3600) -> bool:
        return self._set_value(key, value, ttl)

    def delete_sync(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False


class RedisCache:
    """Redis-based cache with async and sync interfaces."""

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._client: Any = None
        self._sync_client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as redis

                from proxy.app.shared.retry import RetryConfig, async_retry

                async def _connect() -> Any:
                    client = redis.from_url(self.redis_url, decode_responses=True)
                    await client.ping()
                    return client

                self._client = await async_retry(
                    _connect,
                    config=RetryConfig(
                        max_attempts=3,
                        base_delay=1.0,
                        jitter=True,
                    ),
                )
                logger.info(f"Connected to Redis at {self.redis_url}")
            except ImportError:
                logger.error("redis.asyncio not installed. Install: pip install redis")
                raise
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
        return self._client

    def _get_sync_client(self) -> Any:
        """Get or create a sync Redis client for sync operations."""
        if self._sync_client is None:
            try:
                import redis as sync_redis

                from proxy.app.shared.retry import RetryConfig, sync_retry

                def _connect() -> Any:
                    client = sync_redis.from_url(self.redis_url, decode_responses=True)
                    client.ping()
                    return client

                self._sync_client = sync_retry(
                    _connect,
                    config=RetryConfig(
                        max_attempts=3,
                        base_delay=1.0,
                        jitter=True,
                    ),
                )
            except ImportError:
                logger.error("redis not installed. Install: pip install redis")
                raise
            except Exception as e:
                logger.error("Failed to create sync Redis client: %s", e)
                raise
        return self._sync_client

    async def get(self, key: str) -> Any | None:
        client = await self._get_client()
        value = await client.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value  # строка

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        client = await self._get_client()
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        await client.setex(key, ttl, value)
        return True

    async def delete(self, key: str) -> bool:
        client = await self._get_client()
        deleted: int = await client.delete(key)
        return deleted > 0

    async def clear(self) -> None:
        client = await self._get_client()
        await client.flushdb()

    # Синхронные обёртки — используют отдельный sync Redis клиент
    def get_sync(self, key: str) -> Any | None:
        try:
            client = self._get_sync_client()
            value = client.get(key)
            if value is None:
                return None
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        except Exception as e:
            logger.debug("Redis get_sync failed: %s", e)
            return None

    def set_sync(self, key: str, value: Any, ttl: int = 3600) -> bool:
        try:
            client = self._get_sync_client()
            if not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            client.setex(key, ttl, value)
            return True
        except Exception as e:
            logger.debug("Redis set_sync failed: %s", e)
            return False

    def delete_sync(self, key: str) -> bool:
        try:
            client = self._get_sync_client()
            deleted: int = client.delete(key)
            return deleted > 0
        except Exception as e:
            logger.debug("Redis delete_sync failed: %s", e)
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None


class CacheManager:
    """Унифицированный менеджер кэша. Использует Redis (если задан URL) или in-memory."""

    def __init__(
        self,
        redis_url: str | None = None,
        use_redis: bool = True,
        key_prefix: str = "",
    ) -> None:
        self.use_redis = use_redis and redis_url is not None
        self._cache: RedisCache | InMemoryCache
        self._cache_type: str
        self._key_prefix = key_prefix
        if self.use_redis and redis_url is not None:
            self._cache = RedisCache(redis_url)
            self._cache_type = "redis"
        else:
            self._cache = InMemoryCache()
            self._cache_type = "memory"
        logger.info(f"CacheManager initialized with {type(self._cache).__name__}, prefix='{self._key_prefix}'")

    def _full_key(self, key: str) -> str:
        """Prefix all cache keys for namespace isolation."""
        return f"{self._key_prefix}{key}" if self._key_prefix else key

    async def initialize(self) -> None:
        """Для Redis: проверка подключения при старте."""
        if self.use_redis and hasattr(self._cache, "_get_client"):
            await self._cache._get_client()

    async def get(self, key: str) -> Any | None:
        result = await self._cache.get(self._full_key(key))
        if result is not None:
            from proxy.app.shared.metrics import record_cache_hit

            record_cache_hit(self._cache_type)
        else:
            from proxy.app.shared.metrics import record_cache_miss

            record_cache_miss(self._cache_type)
        return result

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        return await self._cache.set(self._full_key(key), value, ttl)

    async def delete(self, key: str) -> bool:
        return await self._cache.delete(self._full_key(key))

    async def clear(self) -> None:
        await self._cache.clear()

    async def close(self) -> None:
        if hasattr(self._cache, "close"):
            await self._cache.close()

    # Синхронные методы для обратной совместимости (используются в retrieval и rerank)
    def get_sync(self, key: str) -> Any | None:
        result = self._cache.get_sync(self._full_key(key))
        if result is not None:
            from proxy.app.shared.metrics import record_cache_hit

            record_cache_hit(self._cache_type)
        else:
            from proxy.app.shared.metrics import record_cache_miss

            record_cache_miss(self._cache_type)
        return result

    def set_sync(self, key: str, value: Any, ttl: int = 3600) -> bool:
        return self._cache.set_sync(self._full_key(key), value, ttl)

    def delete_sync(self, key: str) -> bool:
        return self._cache.delete_sync(self._full_key(key))


# ── Semantic Response Cache ──────────────────────────────────────────────────

_SEMANTIC_CACHE_BUCKET_PREFIX = "sem_cache:bucket:"
_SEMANTIC_CACHE_ENTRY_PREFIX = "sem_cache:entry:"
_SEMANTIC_CACHE_BUCKET_SIZE = 50
_SEMANTIC_CACHE_MAX_SCAN_ENTRIES = 200


class SemanticCache:
    """Semantic response cache using embedding similarity.

    Instead of exact query match, computes an embedding of the incoming query
    and searches for cached responses with cosine similarity above a threshold.

    Uses a locality-sensitive bucketing strategy to avoid scanning all entries:
    - Each stored entry is hashed into a bucket based on the first 8 embedding
      dimensions (rounded to 2 decimals).
    - On lookup, only entries in the matching bucket are compared.
    """

    def __init__(
        self,
        cache_manager: "CacheManager",
        similarity_threshold: float = 0.92,
        ttl: int = 300,
    ) -> None:
        self._cache = cache_manager
        self._threshold = similarity_threshold
        self._ttl = ttl
        self._embedder: Any = None

    def _get_embedder(self) -> Any:
        if self._embedder is None:
            try:
                from proxy.app.llm.remote_services import create_embedder

                self._embedder = create_embedder()
            except Exception:
                logger.warning("Embedder not available, semantic cache disabled", exc_info=True)
                return None
        return self._embedder

    def _compute_embedding(self, text: str) -> list[float] | None:
        embedder = self._get_embedder()
        if embedder is None:
            return None
        try:
            emb = embedder.encode(text, normalize_embeddings=True)
            if isinstance(emb, np.ndarray):
                return emb.tolist()
            return list(emb)
        except Exception:
            logger.debug("Failed to compute embedding for semantic cache", exc_info=True)
            return None

    @staticmethod
    def _bucket_key(embedding: list[float]) -> str:
        parts = [f"{round(embedding[i], 2):.2f}" for i in range(min(8, len(embedding)))]
        bucket_hash = hashlib.md5(",".join(parts).encode()).hexdigest()[:8]
        return f"{_SEMANTIC_CACHE_BUCKET_PREFIX}{bucket_hash}"

    @staticmethod
    def _entry_key(query: str) -> str:
        query_hash = hashlib.md5(query.encode()).hexdigest()[:16]
        return f"{_SEMANTIC_CACHE_ENTRY_PREFIX}{query_hash}"

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        return max(0.0, min(1.0, dot))

    async def get(self, query: str) -> str | None:
        query_emb = self._compute_embedding(query)
        if query_emb is None:
            return None

        bucket = self._bucket_key(query_emb)
        bucket_entries_raw = await self._cache.get(bucket)
        if not bucket_entries_raw or not isinstance(bucket_entries_raw, list):
            return None

        entry_ids = bucket_entries_raw[:_SEMANTIC_CACHE_MAX_SCAN_ENTRIES]
        for entry_id in entry_ids:
            entry = await self._cache.get(entry_id)
            if entry is None:
                continue
            stored_emb = entry.get("e")
            if stored_emb is None:
                continue
            sim = self._cosine_similarity(query_emb, stored_emb)
            if sim >= self._threshold:
                logger.info(
                    "Semantic cache hit (sim=%.3f, threshold=%.3f)",
                    sim,
                    self._threshold,
                )
                return entry.get("r")
        return None

    async def set(self, query: str, response: str) -> bool:
        query_emb = self._compute_embedding(query)
        if query_emb is None:
            return False

        entry_id = self._entry_key(query)
        bucket = self._bucket_key(query_emb)

        await self._cache.set(
            entry_id,
            {"e": query_emb, "r": response, "q": query[:200]},
            ttl=self._ttl,
        )

        bucket_entries_raw = await self._cache.get(bucket) or []
        if not isinstance(bucket_entries_raw, list):
            bucket_entries_raw = []
        if entry_id not in bucket_entries_raw:
            bucket_entries_raw.insert(0, entry_id)
            if len(bucket_entries_raw) > _SEMANTIC_CACHE_BUCKET_SIZE:
                bucket_entries_raw = bucket_entries_raw[:_SEMANTIC_CACHE_BUCKET_SIZE]
            await self._cache.set(bucket, bucket_entries_raw, ttl=self._ttl * 2)

        return True


# Пример использования
if __name__ == "__main__":

    async def test() -> None:
        # In-memory
        cache = CacheManager(use_redis=False)
        await cache.set("test_key", "hello", ttl=10)
        val = await cache.get("test_key")
        print(f"In-memory get: {val}")

        # Redis (если доступен)
        cache2 = CacheManager(redis_url="redis://localhost:6379", use_redis=True)
        await cache2.initialize()
        await cache2.set("test_redis", {"data": 123}, ttl=60)
        val2 = await cache2.get("test_redis")
        print(f"Redis get: {val2}")
        await cache2.close()

    asyncio.run(test())
