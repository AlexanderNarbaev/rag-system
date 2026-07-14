"""Tests for proxy/app/cache.py - InMemoryCache, RedisCache, CacheManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxy.app.shared.cache import CacheManager, InMemoryCache, RedisCache


class TestInMemoryCacheAsync:
  """Tests for InMemoryCache async operations."""
  
  @pytest.mark.asyncio
  async def test_set_and_get (self):
    cache = InMemoryCache ()
    await cache.set ("key1", "value1")
    result = await cache.get ("key1")
    assert result == "value1"
  
  @pytest.mark.asyncio
  async def test_get_missing_key (self):
    cache = InMemoryCache ()
    result = await cache.get ("nonexistent")
    assert result is None
  
  @pytest.mark.asyncio
  async def test_delete (self):
    cache = InMemoryCache ()
    await cache.set ("key1", "value1")
    deleted = await cache.delete ("key1")
    assert deleted is True
    assert await cache.get ("key1") is None
  
  @pytest.mark.asyncio
  async def test_delete_missing (self):
    cache = InMemoryCache ()
    deleted = await cache.delete ("nonexistent")
    assert deleted is False
  
  @pytest.mark.asyncio
  async def test_clear (self):
    cache = InMemoryCache ()
    await cache.set ("a", 1)
    await cache.set ("b", 2)
    await cache.clear ()
    assert await cache.get ("a") is None
    assert await cache.get ("b") is None
  
  @pytest.mark.asyncio
  async def test_ttl_expiration (self):
    cache = InMemoryCache ()
    await cache.set ("key", "value", ttl = 0)
    await asyncio.sleep (0.1)
    result = await cache.get ("key")
    assert result is None
  
  @pytest.mark.asyncio
  async def test_complex_value (self):
    cache = InMemoryCache ()
    data = {"nested": [1, 2, 3], "text": "hello"}
    await cache.set ("complex", data)
    result = await cache.get ("complex")
    assert result == data


class TestInMemoryCacheSync:
  """Tests for InMemoryCache synchronous wrappers."""
  
  def test_set_sync_and_get_sync (self):
    cache = InMemoryCache ()
    cache.set_sync ("skey", "svalue")
    assert cache.get_sync ("skey") == "svalue"
  
  def test_get_sync_missing (self):
    cache = InMemoryCache ()
    assert cache.get_sync ("missing") is None
  
  def test_set_sync_ttl_expired (self):
    cache = InMemoryCache ()
    cache.set_sync ("key", "value", ttl = -1)
    assert cache.get_sync ("key") is None


class TestCacheManagerInMemory:
  """Tests for CacheManager with in-memory backend."""
  
  @pytest.mark.asyncio
  async def test_in_memory_mode (self):
    cm = CacheManager (use_redis = False)
    await cm.set ("k", "v")
    assert await cm.get ("k") == "v"
  
  @pytest.mark.asyncio
  async def test_cache_manager_delete (self):
    cm = CacheManager (use_redis = False)
    await cm.set ("k", "v")
    assert await cm.delete ("k") is True
    assert await cm.get ("k") is None
  
  @pytest.mark.asyncio
  async def test_cache_manager_clear (self):
    cm = CacheManager (use_redis = False)
    await cm.set ("a", 1)
    await cm.set ("b", 2)
    await cm.clear ()
    assert await cm.get ("a") is None
    assert await cm.get ("b") is None
  
  @pytest.mark.asyncio
  async def test_close_in_memory (self):
    cm = CacheManager (use_redis = False)
    await cm.close ()
  
  def test_sync_methods_delegate (self):
    cm = CacheManager (use_redis = False)
    cm.set_sync ("sk", "sv")
    assert cm.get_sync ("sk") == "sv"
  
  def test_delete_sync (self):
    cm = CacheManager (use_redis = False)
    cm.set_sync ("k", "v")
    assert cm.delete_sync ("k") is True


class TestCacheManagerRedisMode:
  """Tests for CacheManager with Redis mode (mocked)."""
  
  def test_redis_mode_creates_redis_cache (self):
    with patch ("proxy.app.shared.cache.RedisCache") as mock_redis:
      cm = CacheManager (redis_url = "redis://localhost:6379", use_redis = True)
      assert cm.use_redis is True
      mock_redis.assert_called_once_with ("redis://localhost:6379")
  
  def test_redis_mode_off_without_url (self):
    cm = CacheManager (redis_url = None, use_redis = True)
    assert cm.use_redis is False
  
  @pytest.mark.asyncio
  async def test_redis_get_set_delegates (self):
    mock_cache = MagicMock ()
    mock_cache.get = AsyncMock (return_value = "cached_val")
    mock_cache.set = AsyncMock (return_value = True)
    
    with patch ("proxy.app.shared.cache.RedisCache", return_value = mock_cache):
      cm = CacheManager (redis_url = "redis://localhost", use_redis = True)
      result = await cm.get ("key")
      assert result == "cached_val"
      await cm.set ("key", "val")
      mock_cache.set.assert_called_once ()
  
  @pytest.mark.asyncio
  async def test_redis_initialization (self):
    mock_cache = MagicMock ()
    mock_cache._get_client = AsyncMock ()
    
    with patch ("proxy.app.shared.cache.RedisCache", return_value = mock_cache):
      cm = CacheManager (redis_url = "redis://localhost", use_redis = True)
      await cm.initialize ()
      mock_cache._get_client.assert_called_once ()


class TestRedisCacheMocked:
  """Tests for RedisCache operations with mocked redis client."""
  
  def test_get_set_via_sync (self):
    mock_client = MagicMock ()
    mock_client.get = AsyncMock (return_value = None)
    mock_client.setex = AsyncMock (return_value = None)
    
    cache = RedisCache ("redis://localhost")
    cache._client = mock_client
    
    run_coro = asyncio.run (cache.set ("k", "v", ttl = 10))
    assert run_coro is True
    mock_client.setex.assert_called_once ()
  
  @pytest.mark.asyncio
  async def test_get_returns_none_when_missing (self):
    mock_client = MagicMock ()
    mock_client.get = AsyncMock (return_value = None)
    
    cache = RedisCache ("redis://localhost")
    cache._client = mock_client
    
    result = await cache.get ("missing")
    assert result is None
  
  @pytest.mark.asyncio
  async def test_delete (self):
    mock_client = MagicMock ()
    mock_client.delete = AsyncMock (return_value = 1)
    
    cache = RedisCache ("redis://localhost")
    cache._client = mock_client
    
    result = await cache.delete ("key")
    assert result is True
  
  @pytest.mark.asyncio
  async def test_delete_missing (self):
    mock_client = MagicMock ()
    mock_client.delete = AsyncMock (return_value = 0)
    
    cache = RedisCache ("redis://localhost")
    cache._client = mock_client
    
    result = await cache.delete ("key")
    assert result is False
  
  @pytest.mark.asyncio
  async def test_clear (self):
    mock_client = MagicMock ()
    mock_client.flushdb = AsyncMock ()
    
    cache = RedisCache ("redis://localhost")
    cache._client = mock_client
    
    await cache.clear ()
    mock_client.flushdb.assert_called_once ()
  
  @pytest.mark.asyncio
  async def test_get_parses_json (self):
    import json
    
    mock_client = MagicMock ()
    mock_client.get = AsyncMock (return_value = json.dumps ({"a": 1}))
    
    cache = RedisCache ("redis://localhost")
    cache._client = mock_client
    
    result = await cache.get ("key")
    assert result == {"a": 1}
  
  @pytest.mark.asyncio
  async def test_close (self):
    mock_client = MagicMock ()
    mock_client.close = AsyncMock ()
    
    cache = RedisCache ("redis://localhost")
    cache._client = mock_client
    
    await cache.close ()
    mock_client.close.assert_called_once ()
    assert cache._client is None
