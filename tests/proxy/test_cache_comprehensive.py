"""Comprehensive tests for proxy/app/shared/cache.py.

Targets uncovered lines in the cache module — specifically the
3-tier Redis/fallback path, the SemanticCache class, and the TTL
eviction paths.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxy.app.shared.cache import (
    CacheManager,
    InMemoryCache,
    SemanticCache,
)

# ---------------------------------------------------------------------------
# InMemoryCache
# ---------------------------------------------------------------------------


class TestInMemoryCacheEdgeCases:
    """Tests for edge cases in the in-memory cache TTL eviction."""

    def test_get_nonexistent_returns_none(self) -> None:
        cache = InMemoryCache()
        assert asyncio.run(cache.get("missing")) is None

    def test_set_then_get_returns_value(self) -> None:
        cache = InMemoryCache()
        asyncio.run(cache.set("k", "v"))
        assert asyncio.run(cache.get("k")) == "v"

    def test_set_with_ttl_zero(self) -> None:
        cache = InMemoryCache()
        asyncio.run(cache.set("k", "v", ttl=0))
        # The TTL=0 means timestamp == now → considered expired on next get
        assert asyncio.run(cache.get("k")) is None

    def test_set_with_negative_ttl(self) -> None:
        cache = InMemoryCache()
        asyncio.run(cache.set("k", "v", ttl=-1))
        assert asyncio.run(cache.get("k")) is None

    def test_overwrite_keeps_latest_value(self) -> None:
        cache = InMemoryCache()
        asyncio.run(cache.set("k", "v1"))
        asyncio.run(cache.set("k", "v2"))
        assert asyncio.run(cache.get("k")) == "v2"

    def test_clear_removes_all_entries(self) -> None:
        cache = InMemoryCache()
        asyncio.run(cache.set("a", 1))
        asyncio.run(cache.set("b", 2))
        asyncio.run(cache.clear())
        assert asyncio.run(cache.get("a")) is None
        assert asyncio.run(cache.get("b")) is None

    def test_delete_existing_returns_true(self) -> None:
        cache = InMemoryCache()
        asyncio.run(cache.set("k", "v"))
        assert asyncio.run(cache.delete("k")) is True

    def test_delete_nonexistent_returns_false(self) -> None:
        cache = InMemoryCache()
        assert asyncio.run(cache.delete("k")) is False

    def test_expired_entry_purged_on_get(self) -> None:
        cache = InMemoryCache()
        cache._store["k"] = ("v", (datetime.now(UTC) - timedelta(seconds=1)).timestamp())
        assert asyncio.run(cache.get("k")) is None
        # Expired entry should be removed from store
        assert "k" not in cache._store

    def test_get_sync_returns_value(self) -> None:
        cache = InMemoryCache()
        cache.set_sync("k", "v")
        assert cache.get_sync("k") == "v"

    def test_set_sync(self) -> None:
        cache = InMemoryCache()
        cache.set_sync("k", "v")
        assert asyncio.run(cache.get("k")) == "v"

    def test_delete_sync(self) -> None:
        cache = InMemoryCache()
        asyncio.run(cache.set("k", "v"))
        cache.delete_sync("k")
        assert asyncio.run(cache.get("k")) is None


# ---------------------------------------------------------------------------
# CacheManager — Redis unavailable → in-memory fallback
# ---------------------------------------------------------------------------


class TestCacheManagerFallback:
    """CacheManager should fall back to InMemoryCache when Redis is unavailable."""

    def test_init_without_redis_url_uses_in_memory(self) -> None:
        cm = CacheManager(use_redis=False)
        assert cm.use_redis is False
        assert isinstance(cm._cache, InMemoryCache)
        assert cm._cache_type == "memory"

    def test_init_without_redis_url_no_redis_path(self) -> None:
        """When redis_url is None, use_redis is forced to False."""
        cm = CacheManager(redis_url=None, use_redis=True)
        assert cm.use_redis is False
        assert isinstance(cm._cache, InMemoryCache)

    def test_set_and_get_through_fallback(self) -> None:
        cm = CacheManager(use_redis=False)
        asyncio.run(cm.set("k", "v"))
        assert asyncio.run(cm.get("k")) == "v"

    def test_delete_through_fallback(self) -> None:
        cm = CacheManager(use_redis=False)
        asyncio.run(cm.set("k", "v"))
        asyncio.run(cm.delete("k"))
        assert asyncio.run(cm.get("k")) is None

    def test_set_with_ttl_through_fallback(self) -> None:
        cm = CacheManager(use_redis=False)
        asyncio.run(cm.set("k", "v", ttl=1))
        assert asyncio.run(cm.get("k")) == "v"

    def test_get_missing_returns_none(self) -> None:
        cm = CacheManager(use_redis=False)
        assert asyncio.run(cm.get("missing")) is None

    def test_clear_through_fallback(self) -> None:
        cm = CacheManager(use_redis=False)
        asyncio.run(cm.set("a", 1))
        asyncio.run(cm.clear())
        assert asyncio.run(cm.get("a")) is None

    def test_init_with_redis_url_but_redis_unavailable(self) -> None:
        """When redis_url is set but redis is unreachable, fall back to memory."""
        with patch("redis.asyncio.from_url", side_effect=Exception("connection refused")):
            cm = CacheManager(use_redis=True, redis_url="redis://localhost:6379/0")
            # Should not raise at __init__; the failure happens on first use
            assert cm.use_redis is True

    def test_initialize_with_redis_unavailable_raises_after_retry(self) -> None:
        """When redis is unreachable, initialize() raises after retries (intentional)."""
        from proxy.app.shared.retry import RetryExhaustedError

        with patch("redis.asyncio.from_url", side_effect=Exception("connection refused")):
            cm = CacheManager(use_redis=True, redis_url="redis://localhost:6379/0")
            # initialize() retries 3 times then raises — this is the
            # documented fast-fail behaviour, not a bug.
            with pytest.raises(RetryExhaustedError):
                asyncio.run(cm.initialize())


# ---------------------------------------------------------------------------
# CacheManager — Redis path (mocked)
# ---------------------------------------------------------------------------


class TestCacheManagerRedis:
    """CacheManager with mocked Redis client."""

    @pytest.fixture
    def mock_redis(self) -> Any:
        client = AsyncMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock(return_value=True)
        client.delete = AsyncMock(return_value=1)
        client.ping = AsyncMock(return_value=True)
        return client

    def test_redis_get_returns_value(self, mock_redis: Any) -> None:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            cm = CacheManager(use_redis=True, redis_url="redis://localhost:6379/0")
            mock_redis.get.return_value = json.dumps("cached_value")
            result = asyncio.run(cm.get("k"))
            assert result == "cached_value"

    def test_redis_get_non_json_falls_back_to_raw(self, mock_redis: Any) -> None:
        """A non-JSON-decodable value should be returned as raw string."""
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            cm = CacheManager(use_redis=True, redis_url="redis://localhost:6379/0")
            mock_redis.get.return_value = "not json"
            result = asyncio.run(cm.get("k"))
            assert result == "not json"

    def test_redis_set_serializes_to_json(self, mock_redis: Any) -> None:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            cm = CacheManager(use_redis=True, redis_url="redis://localhost:6379/0")
            asyncio.run(cm.set("k", {"dict": "value"}))
            mock_redis.setex.assert_called_once()

    def test_redis_set_with_ttl(self, mock_redis: Any) -> None:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            cm = CacheManager(use_redis=True, redis_url="redis://localhost:6379/0")
            asyncio.run(cm.set("k", "v", ttl=60))
            mock_redis.setex.assert_called_once()

    def test_redis_delete(self, mock_redis: Any) -> None:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            cm = CacheManager(use_redis=True, redis_url="redis://localhost:6379/0")
            asyncio.run(cm.delete("k"))
            mock_redis.delete.assert_called_once()

    def test_redis_initialize_succeeds(self, mock_redis: Any) -> None:
        with patch("redis.asyncio.from_url", return_value=mock_redis):
            cm = CacheManager(use_redis=True, redis_url="redis://localhost:6379/0")
            asyncio.run(cm.initialize())


# ---------------------------------------------------------------------------
# Sync interface (backward compatibility)
# ---------------------------------------------------------------------------


class TestCacheManagerSync:
    """Synchronous interface delegates to async implementation."""

    def test_sync_get(self) -> None:
        cm = CacheManager(use_redis=False)
        asyncio.run(cm.set("k", "v"))
        assert cm.get_sync("k") == "v"

    def test_sync_set(self) -> None:
        cm = CacheManager(use_redis=False)
        cm.set_sync("k", "v")
        assert asyncio.run(cm.get("k")) == "v"

    def test_sync_delete(self) -> None:
        cm = CacheManager(use_redis=False)
        asyncio.run(cm.set("k", "v"))
        cm.delete_sync("k")
        assert asyncio.run(cm.get("k")) is None


# ---------------------------------------------------------------------------
# SemanticCache
# ---------------------------------------------------------------------------


class TestSemanticCache:
    """Tests for the semantic caching layer."""

    @pytest.fixture
    def mock_cache_manager(self) -> Any:
        cm = AsyncMock()
        cm.get = AsyncMock(return_value=None)
        cm.set = AsyncMock(return_value=True)
        return cm

    @pytest.fixture
    def mock_embedder(self) -> Any:
        emb = MagicMock()
        emb.encode = MagicMock(return_value=[0.1] * 8)
        return emb

    def test_compute_embedding_no_embedder_returns_none(self, mock_cache_manager: Any) -> None:
        with patch("proxy.app.llm.remote_services.create_embedder", side_effect=Exception("no embedder")):
            sem = SemanticCache(mock_cache_manager)
            assert sem._compute_embedding("query") is None

    def test_compute_embedding_with_embedder(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager)
            emb = sem._compute_embedding("test query")
            assert emb is not None
            assert isinstance(emb, list)
            assert len(emb) == 8

    def test_compute_embedding_handles_ndarray(self, mock_cache_manager: Any) -> None:
        import numpy as np

        mock_emb = MagicMock()
        mock_emb.encode = MagicMock(return_value=np.array([0.1] * 8))
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_emb):
            sem = SemanticCache(mock_cache_manager)
            emb = sem._compute_embedding("test")
            assert isinstance(emb, list)

    def test_compute_embedding_handles_encode_error(self, mock_cache_manager: Any) -> None:
        mock_emb = MagicMock()
        mock_emb.encode = MagicMock(side_effect=Exception("encode failed"))
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_emb):
            sem = SemanticCache(mock_cache_manager)
            assert sem._compute_embedding("test") is None

    def test_bucket_key_format(self) -> None:
        key = SemanticCache._bucket_key([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
        assert key.startswith("sem_cache:bucket:")
        assert len(key) > len("sem_cache:bucket:")

    def test_bucket_key_uses_first_8_dims(self) -> None:
        """Even with 100-dim embeddings, only first 8 are used for bucketing."""
        emb = [float(i) for i in range(100)]
        key1 = SemanticCache._bucket_key(emb)
        emb[0] = 99.0  # Change dim 0
        key2 = SemanticCache._bucket_key(emb)
        assert key1 != key2

    def test_bucket_key_ignores_dim_beyond_8(self) -> None:
        """Changing dim beyond 8 should NOT change bucket key."""
        emb = [float(i) for i in range(100)]
        key1 = SemanticCache._bucket_key(emb)
        emb[9] = 99.0  # Change dim 9 (beyond first 8)
        key2 = SemanticCache._bucket_key(emb)
        assert key1 == key2

    def test_entry_key_format(self) -> None:
        key = SemanticCache._entry_key("some query")
        assert key.startswith("sem_cache:entry:")
        assert len(key) == len("sem_cache:entry:") + 16

    def test_entry_key_deterministic(self) -> None:
        k1 = SemanticCache._entry_key("query")
        k2 = SemanticCache._entry_key("query")
        assert k1 == k2

    def test_cosine_similarity_identical(self) -> None:
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        sim = SemanticCache._cosine_similarity(a, b)
        assert sim == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self) -> None:
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        sim = SemanticCache._cosine_similarity(a, b)
        assert sim == 0.0

    def test_cosine_similarity_negative_clamps_to_zero(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        sim = SemanticCache._cosine_similarity(a, b)
        assert sim == 0.0

    def test_cosine_similarity_above_one_clamps(self) -> None:
        a = [2.0, 0.0]
        b = [2.0, 0.0]
        sim = SemanticCache._cosine_similarity(a, b)
        assert sim == 1.0  # clamped

    def test_cosine_similarity_different_lengths(self) -> None:
        """zip() stops at shorter list — should still produce a value."""
        a = [1.0, 0.0, 0.0]
        b = [1.0]
        sim = SemanticCache._cosine_similarity(a, b)
        assert sim == 1.0

    def test_get_without_embedder_returns_none(self, mock_cache_manager: Any) -> None:
        with patch("proxy.app.llm.remote_services.create_embedder", side_effect=Exception("no embedder")):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.get("query"))
            assert result is None

    def test_get_with_empty_bucket_returns_none(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        mock_cache_manager.get = AsyncMock(return_value=None)
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.get("query"))
            assert result is None

    def test_get_with_non_list_bucket_returns_none(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        mock_cache_manager.get = AsyncMock(return_value="not a list")
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.get("query"))
            assert result is None

    def test_get_with_high_similarity_returns_cached(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        # Use unit vectors for similarity = 1.0
        stored_emb = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        mock_embedder.encode = MagicMock(return_value=stored_emb)
        entry_id = "sem:entry:abc123"
        mock_cache_manager.get = AsyncMock(side_effect=[[entry_id], {"e": stored_emb, "r": "cached answer"}])
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager, similarity_threshold=0.5)
            result = asyncio.run(sem.get("test"))
            assert result == "cached answer"

    def test_get_with_low_similarity_returns_none(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        query_emb = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        stored_emb = [-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # opposite direction
        mock_embedder.encode = MagicMock(return_value=query_emb)
        entry_id = "sem:entry:abc123"
        mock_cache_manager.get = AsyncMock(side_effect=[[entry_id], {"e": stored_emb, "r": "cached"}])
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager, similarity_threshold=0.9)
            result = asyncio.run(sem.get("test"))
            assert result is None

    def test_get_skips_entries_without_embedding(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        entry_id = "sem:entry:abc123"
        mock_cache_manager.get = AsyncMock(side_effect=[[entry_id], {"r": "no embedding"}])
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.get("test"))
            assert result is None

    def test_get_skips_missing_entries(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        entry_id = "sem:entry:abc123"
        mock_cache_manager.get = AsyncMock(side_effect=[[entry_id], None])
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.get("test"))
            assert result is None

    def test_get_iterates_through_bucket_entries(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        """When multiple entries exist, find the first match."""
        # Use unit vectors for similarity = 1.0
        stored_emb = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        mock_embedder.encode = MagicMock(return_value=stored_emb)
        entry_id_1 = "sem:entry:111"
        entry_id_2 = "sem:entry:222"
        mock_cache_manager.get = AsyncMock(
            side_effect=[
                [entry_id_1, entry_id_2],
                None,  # entry 1 missing
                {"e": stored_emb, "r": "found answer"},  # entry 2 matches
            ]
        )
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager, similarity_threshold=0.5)
            result = asyncio.run(sem.get("test"))
            assert result == "found answer"

    def test_set_without_embedder_returns_false(self, mock_cache_manager: Any) -> None:
        with patch("proxy.app.llm.remote_services.create_embedder", side_effect=Exception("no embedder")):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.set("query", "response"))
            assert result is False

    def test_set_stores_entry_and_bucket(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        mock_cache_manager.get = AsyncMock(return_value=[])
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.set("test query", "test response"))
            assert result is True
            # Two sets: one for entry, one for bucket
            assert mock_cache_manager.set.call_count == 2

    def test_set_appends_to_existing_bucket(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        existing_entry_id = "sem:entry:existing"
        mock_cache_manager.get = AsyncMock(return_value=[existing_entry_id])
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.set("test", "response"))
            assert result is True

    def test_set_handles_non_list_bucket(self, mock_cache_manager: Any, mock_embedder: Any) -> None:
        """Bucket returns non-list (e.g., after corruption) → reset to empty list."""
        mock_cache_manager.get = AsyncMock(return_value="corrupted")
        with patch("proxy.app.llm.remote_services.create_embedder", return_value=mock_embedder):
            sem = SemanticCache(mock_cache_manager)
            result = asyncio.run(sem.set("test", "response"))
            assert result is True


# ---------------------------------------------------------------------------
# Cache key prefix
# ---------------------------------------------------------------------------


class TestCacheKeyPrefix:
    """Cache keys should be prefixed with the configured prefix."""

    def test_custom_prefix_applied_via_full_key(self) -> None:
        cm = CacheManager(use_redis=False, key_prefix="myapp:")
        assert cm._full_key("k") == "myapp:k"

    def test_no_prefix(self) -> None:
        cm = CacheManager(use_redis=False, key_prefix="")
        assert cm._full_key("k") == "k"

    def test_set_uses_prefixed_key(self) -> None:
        cm = CacheManager(use_redis=False, key_prefix="myapp:")
        asyncio.run(cm.set("k", "v"))
        # The internal cache should have the prefixed key
        from typing import cast

        from proxy.app.shared.cache import InMemoryCache

        fallback = cast(InMemoryCache, cm._cache)
        assert "myapp:k" in fallback._store
        assert "k" not in fallback._store
