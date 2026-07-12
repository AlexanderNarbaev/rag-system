# proxy/app/cache.py
"""
Cache manager with Redis and in-memory fallback.

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
import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class InMemoryCache:
    """Simple in-memory cache with TTL expiration."""

    # Default TTL for cache entries (1 hour)
    DEFAULT_TTL_SECONDS = 3600

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expire_timestamp)

    def _is_expired(self, expire_ts: float) -> bool:
        return expire_ts < datetime.now(UTC).timestamp()

    async def get(self, key: str) -> Any | None:
        if key not in self._store:
            return None
        value, expire_ts = self._store[key]
        if self._is_expired(expire_ts):
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        expire_ts = datetime.now(UTC).timestamp() + ttl
        self._store[key] = (value, expire_ts)
        return True

    async def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def clear(self) -> None:
        self._store.clear()

    # Синхронные методы для совместимости
    def get_sync(self, key: str) -> Any | None:
        try:
            _loop = asyncio.get_running_loop()
            # Если уже в асинхронном контексте, создаём задачу
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.get(key))
                return future.result()
        except RuntimeError:
            # Нет запущенного цикла – запускаем свой
            return asyncio.run(self.get(key))

    def set_sync(self, key: str, value: Any, ttl: int = 3600) -> bool:
        try:
            _loop = asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.set(key, value, ttl))
                return future.result()
        except RuntimeError:
            return asyncio.run(self.set(key, value, ttl))


class RedisCache:
    """Redis-based cache with async interface."""

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._client = None

    async def _get_client(self) -> Any:
        if self._client is None:
            try:
                import redis.asyncio as redis

                self._client = redis.from_url(self.redis_url, decode_responses=True)
                # Проверяем соединение
                await self._client.ping()
                logger.info(f"Connected to Redis at {self.redis_url}")
            except ImportError:
                logger.error("redis.asyncio not installed. Install: pip install redis")
                raise
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
        return self._client

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
        deleted = await client.delete(key)
        return deleted > 0

    async def clear(self) -> None:
        client = await self._get_client()
        await client.flushdb()

    # Синхронные обёртки (используют run_until_complete)
    def get_sync(self, key: str) -> Any | None:
        try:
            _loop = asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.get(key))
                return future.result()
        except RuntimeError:
            return asyncio.run(self.get(key))

    def set_sync(self, key: str, value: Any, ttl: int = 3600) -> bool:
        try:
            _loop = asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.set(key, value, ttl))
                return future.result()
        except RuntimeError:
            return asyncio.run(self.set(key, value, ttl))

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None


class CacheManager:
    """
    Унифицированный менеджер кэша. Использует Redis (если задан URL) или in-memory.
    """

    def __init__(self, redis_url: str | None = None, use_redis: bool = True) -> None:
        self.use_redis = use_redis and redis_url is not None
        if self.use_redis:
            self._cache = RedisCache(redis_url)
        else:
            self._cache = InMemoryCache()
        logger.info(f"CacheManager initialized with {type(self._cache).__name__}")

    async def initialize(self) -> None:
        """Для Redis: проверка подключения при старте."""
        if self.use_redis:
            await self._cache._get_client()

    async def get(self, key: str) -> Any | None:
        return await self._cache.get(key)

    async def set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        return await self._cache.set(key, value, ttl)

    async def delete(self, key: str) -> bool:
        return await self._cache.delete(key)

    async def clear(self) -> None:
        await self._cache.clear()

    async def close(self) -> None:
        if hasattr(self._cache, "close"):
            await self._cache.close()

    # Синхронные методы для обратной совместимости (используются в retrieval и rerank)
    def get_sync(self, key: str) -> Any | None:
        return self._cache.get_sync(key)

    def set_sync(self, key: str, value: Any, ttl: int = 3600) -> bool:
        return self._cache.set_sync(key, value, ttl)

    def delete_sync(self, key: str) -> bool:
        return self._cache.delete_sync(key) if hasattr(self._cache, "delete_sync") else asyncio.run(self.delete(key))


# Пример использования
if __name__ == "__main__":

    async def test():
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
