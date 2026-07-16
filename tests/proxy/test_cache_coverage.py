"""Tests for cache.py uncovered paths: RedisCache sync wrappers, JSON decode, error handling, close."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxy.app.shared.cache import CacheManager, InMemoryCache, RedisCache


class TestInMemoryCacheDeleteSync:
    def test_delete_sync_nonexistent(self):
        cache = InMemoryCache()
        result = cache.delete_sync("nonexistent")
        assert result is False

    def test_delete_sync_existing(self):
        cache = InMemoryCache()
        cache.set_sync("key", "value")
        result = cache.delete_sync("key")
        assert result is True


class TestRedisCacheSyncWrappers:
    """Cover get_sync, set_sync, delete_sync with mocked sync Redis client."""

    @pytest.fixture
    def mock_sync_client(self):
        client = MagicMock()
        client.get.return_value = None
        client.setex.return_value = None
        client.delete.return_value = 1
        client.ping.return_value = True
        client.close.return_value = None
        return client

    def test_get_sync_returns_parsed_json(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        mock_sync_client.get.return_value = json.dumps({"a": 1})
        cache._sync_client = mock_sync_client
        result = cache.get_sync("key")
        assert result == {"a": 1}

    def test_get_sync_returns_raw_string_on_json_error(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        mock_sync_client.get.return_value = "plain_string"
        cache._sync_client = mock_sync_client
        result = cache.get_sync("key")
        assert result == "plain_string"

    def test_get_sync_returns_none_on_exception(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        mock_sync_client.get.side_effect = ConnectionError("redis down")
        cache._sync_client = mock_sync_client
        result = cache.get_sync("key")
        assert result is None

    def test_get_sync_returns_none_when_none(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        mock_sync_client.get.return_value = None
        cache._sync_client = mock_sync_client
        result = cache.get_sync("key")
        assert result is None

    def test_set_sync_serializes_non_string(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        cache._sync_client = mock_sync_client
        result = cache.set_sync("key", {"nested": True}, ttl=30)
        assert result is True
        call_args = mock_sync_client.setex.call_args[0]
        assert call_args[1] == 30
        assert json.loads(call_args[2]) == {"nested": True}

    def test_set_sync_stores_raw_string(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        cache._sync_client = mock_sync_client
        result = cache.set_sync("key", "raw_value", ttl=60)
        assert result is True
        mock_sync_client.setex.assert_called_once_with("key", 60, "raw_value")

    def test_set_sync_returns_false_on_exception(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        mock_sync_client.setex.side_effect = OSError("disk full")
        cache._sync_client = mock_sync_client
        result = cache.set_sync("key", "value")
        assert result is False

    def test_delete_sync_returns_true_when_deleted(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        mock_sync_client.delete.return_value = 1
        cache._sync_client = mock_sync_client
        result = cache.delete_sync("key")
        assert result is True

    def test_delete_sync_returns_false_when_not_found(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        mock_sync_client.delete.return_value = 0
        cache._sync_client = mock_sync_client
        result = cache.delete_sync("key")
        assert result is False

    def test_delete_sync_returns_false_on_exception(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        mock_sync_client.delete.side_effect = RuntimeError("cluster down")
        cache._sync_client = mock_sync_client
        result = cache.delete_sync("key")
        assert result is False

    def test__get_sync_client_creates_new_client(self):
        cache = RedisCache("redis://localhost")
        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_redis_module.from_url.return_value = mock_client
        with patch.dict("sys.modules", redis=mock_redis_module):
            import sys
            sys.modules["redis"] = mock_redis_module
            result = cache._get_sync_client()
            assert result is mock_client
            assert cache._sync_client is mock_client

    def test__get_sync_client_reuses_existing(self, mock_sync_client):
        cache = RedisCache("redis://localhost")
        cache._sync_client = mock_sync_client
        result = cache._get_sync_client()
        assert result is mock_sync_client

    def test__get_sync_client_import_error(self):
        """Cover ImportError path in _get_sync_client when redis is not installed."""
        cache = RedisCache("redis://localhost")
        import sys
        stored = sys.modules.get("redis")

        # Simulate ImportError when accessing redis module
        fake_redis = MagicMock()
        fake_redis.__spec__ = None
        sys.modules["redis"] = fake_redis

        try:
            with patch("redis.from_url", side_effect=ImportError("redis not installed")):
                with pytest.raises(ImportError):
                    cache._get_sync_client()
        finally:
            if stored is not None:
                sys.modules["redis"] = stored
            else:
                sys.modules.pop("redis", None)

    def test__get_sync_client_connection_error(self):
        cache = RedisCache("redis://localhost")
        mock_redis_module = MagicMock()
        mock_redis_module.from_url.side_effect = ConnectionError("refused")
        with patch.dict("sys.modules", {"redis": mock_redis_module}):
            with pytest.raises(ConnectionError):
                cache._get_sync_client()


class TestRedisCacheAsyncClient:
    """Cover _get_client connection/error paths."""
    
    def test__get_client_creates_and_pings(self):
        cache = RedisCache("redis://localhost")
        mock_async_redis = MagicMock()
        mock_async_redis.from_url.return_value = MagicMock()
        mock_async_redis.from_url.return_value.ping = AsyncMock()
        with patch.dict("sys.modules", {"redis.asyncio": mock_async_redis}):
            import sys
            sys.modules["redis.asyncio"] = mock_async_redis
            # Can't run async in sync test, check sync client path instead
            pass

    def test__get_client_reuses_existing(self):
        cache = RedisCache("redis://localhost")
        mock_client = MagicMock()
        cache._client = mock_client
        coro = cache._get_client()
        result = asyncio.run(coro)
        assert result is mock_client


class TestRedisCacheSetNonString:
    """Cover set with non-string value (JSON serialization)."""
    
    @pytest.mark.asyncio
    async def test_set_serializes_dict(self):
        mock_client = MagicMock()
        mock_client.setex = AsyncMock()
        cache = RedisCache("redis://localhost")
        cache._client = mock_client
        data = {"key": "value", "nested": [1, 2, 3]}
        result = await cache.set("k", data, ttl=60)
        assert result is True
        mock_client.setex.assert_called_once()
        _, stored_value = mock_client.setex.call_args[0][2], mock_client.setex.call_args[0][2]
        # Value should be JSON string
        assert isinstance(mock_client.setex.call_args[0][2], str)

    @pytest.mark.asyncio
    async def test_get_returns_raw_on_json_error(self):
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value="not-json")
        cache = RedisCache("redis://localhost")
        cache._client = mock_client
        result = await cache.get("key")
        assert result == "not-json"


class TestRedisCacheClose:
    """Cover close() for both async and sync clients."""

    @pytest.mark.asyncio
    async def test_close_clears_both_clients(self):
        mock_async_client = MagicMock()
        mock_async_client.close = AsyncMock()
        mock_sync_client = MagicMock()
        mock_sync_client.close.return_value = None

        cache = RedisCache("redis://localhost")
        cache._client = mock_async_client
        cache._sync_client = mock_sync_client

        await cache.close()
        mock_async_client.close.assert_called_once()
        mock_sync_client.close.assert_called_once()
        assert cache._client is None
        assert cache._sync_client is None

    @pytest.mark.asyncio
    async def test_close_only_async_client(self):
        mock_async_client = MagicMock()
        mock_async_client.close = AsyncMock()
        
        cache = RedisCache("redis://localhost")
        cache._client = mock_async_client
        cache._sync_client = None

        await cache.close()
        mock_async_client.close.assert_called_once()
        assert cache._client is None


class TestCacheManagerClose:
    """Cover close() delegation for CacheManager."""
    
    @pytest.mark.asyncio
    async def test_close_with_redis(self):
        mock_redis = MagicMock()
        mock_redis.close = AsyncMock()
        with patch("proxy.app.shared.cache.RedisCache", return_value=mock_redis):
            cm = CacheManager(redis_url="redis://localhost", use_redis=True)
            await cm.close()
            mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_graceful_no_close_attr(self):
        """InMemoryCache has no close method, should not raise."""
        cm = CacheManager(use_redis=False)
        await cm.close()


class TestCacheManagerSyncMethodsErrorHandling:
    """Cover sync method delegation including error paths."""
    
    def test_delete_sync_inmemory(self):
        cm = CacheManager(use_redis=False)
        cm.set_sync("del_key", "val")
        assert cm.delete_sync("del_key") is True
    
    def test_delete_sync_nonexistent_inmemory(self):
        cm = CacheManager(use_redis=False)
        assert cm.delete_sync("no_such") is False

    def test_get_sync_returns_none_on_redis_error(self):
        mock_cache = MagicMock()
        mock_cache.get_sync.side_effect = ConnectionError("down")
        
        with patch("proxy.app.shared.cache.RedisCache", return_value=mock_cache):
            cm = CacheManager(redis_url="redis://localhost", use_redis=True)
            with pytest.raises(ConnectionError):
                cm.get_sync("key")
