"""Tests for proxy/app/rate_limiter.py - token bucket rate limiter."""
import time
import sys
from unittest.mock import patch, MagicMock

import pytest


class TestTokenBucket:
    """Tests for TokenBucket class."""

    def test_initial_tokens_equal_burst(self):
        from app.rate_limiter import TokenBucket
        bucket = TokenBucket(rate=1.0, burst=5)
        assert bucket.tokens == 5.0

    def test_allow_requests_within_burst(self):
        from app.rate_limiter import TokenBucket
        bucket = TokenBucket(rate=1.0, burst=3)
        for _ in range(3):
            allowed, _ = bucket.consume()
            assert allowed is True

    def test_block_requests_exceeding_burst(self):
        from app.rate_limiter import TokenBucket
        bucket = TokenBucket(rate=1.0, burst=2)
        for _ in range(2):
            bucket.consume()
        allowed, retry_after = bucket.consume()
        assert allowed is False
        assert retry_after > 0

    def test_token_refill_over_time(self):
        from app.rate_limiter import TokenBucket
        bucket = TokenBucket(rate=5.0, burst=2)
        # Exhaust all tokens
        for _ in range(2):
            bucket.consume()
        # Simulate time passing: manually manipulate last_refill
        bucket.last_refill = time.monotonic() - 0.4  # 0.4s * 5 token/s = 2 tokens
        allowed, _ = bucket.consume()
        assert allowed is True

    def test_refill_capped_at_burst(self):
        from app.rate_limiter import TokenBucket
        bucket = TokenBucket(rate=100.0, burst=2)
        bucket.last_refill = time.monotonic() - 100.0  # enough time for 10000 tokens
        bucket._refill()
        assert bucket.tokens <= bucket.burst


class TestRateLimiter:
    """Tests for RateLimiter with in-memory storage."""

    def test_allows_requests_within_rate(self):
        from app.rate_limiter import RateLimiter
        import asyncio
        async def run():
            limiter = RateLimiter(rate_per_minute=600, burst=5)
            for _ in range(5):
                allowed, _ = await limiter.is_allowed("test_key")
                assert allowed is True
        asyncio.run(run())

    def test_blocks_after_exhaustion(self):
        from app.rate_limiter import RateLimiter
        import asyncio
        async def run():
            limiter = RateLimiter(rate_per_minute=1, burst=2)
            for _ in range(2):
                await limiter.is_allowed("test_key")
            allowed, retry_after = await limiter.is_allowed("test_key")
            assert allowed is False
            assert retry_after > 0
        asyncio.run(run())

    def test_per_key_isolation(self):
        from app.rate_limiter import RateLimiter
        import asyncio
        async def run():
            limiter = RateLimiter(rate_per_minute=1, burst=3)
            # Exhaust key1
            for _ in range(3):
                await limiter.is_allowed("key1")
            # key2 should still be allowed
            allowed, _ = await limiter.is_allowed("key2")
            assert allowed is True
        asyncio.run(run())

    def test_cleanup_expired_buckets(self):
        from app.rate_limiter import RateLimiter
        import asyncio
        async def run():
            limiter = RateLimiter(rate_per_minute=60, burst=5)
            await limiter.is_allowed("temp_key")
            assert "temp_key" in limiter._buckets
            # Expire the bucket
            bucket = limiter._buckets["temp_key"]
            bucket.last_refill = time.monotonic() - 1000.0
            await limiter.cleanup_expired(max_age=10.0)
            assert "temp_key" not in limiter._buckets
        asyncio.run(run())


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    @pytest.fixture
    def async_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.rate_limiter import RateLimitMiddleware, RateLimiter

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        limiter = RateLimiter(rate_per_minute=600, burst=3)
        app.add_middleware(RateLimitMiddleware, limiter=limiter)

        with TestClient(app) as c:
            yield c

    def test_allows_requests_within_limit(self, async_client):
        for i in range(3):
            response = async_client.get("/test")
            assert response.status_code == 200, f"Request {i} failed"

    def test_blocks_requests_exceeding_limit(self, async_client):
        for _ in range(3):
            async_client.get("/test")
        response = async_client.get("/test")
        assert response.status_code == 429

    def test_retry_after_header_present(self, async_client):
        for _ in range(3):
            async_client.get("/test")
        response = async_client.get("/test")
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        retry_after = int(response.headers["Retry-After"])
        assert retry_after >= 1

    def test_error_response_is_json(self, async_client):
        for _ in range(3):
            async_client.get("/test")
        response = async_client.get("/test")
        assert response.status_code == 429
        data = response.json()
        assert "error" in data


class TestRateLimiterIntegration:
    """Integration tests for rate limiter with FastAPI app."""

    def test_add_rate_limit_middleware(self):
        from fastapi import FastAPI
        from app.rate_limiter import add_rate_limit_middleware, get_rate_limiter

        app = FastAPI()
        limiter = add_rate_limit_middleware(app, rate_per_minute=30, burst=5)
        assert get_rate_limiter() is limiter

    def test_extract_key_ip(self):
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from app.rate_limiter import RateLimitMiddleware, RateLimiter

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        limiter = RateLimiter(rate_per_minute=600, burst=5)
        app.add_middleware(RateLimitMiddleware, limiter=limiter)

        with TestClient(app) as c:
            response = c.get("/test")
            assert response.status_code == 200

    def test_extract_key_api_key(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.rate_limiter import RateLimitMiddleware, RateLimiter

        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        limiter = RateLimiter(rate_per_minute=600, burst=3)
        app.add_middleware(RateLimitMiddleware, limiter=limiter)

        with TestClient(app) as c:
            # Different API keys get separate buckets
            for _ in range(3):
                resp = c.get("/test", headers={"Authorization": "Bearer key1"})
                assert resp.status_code == 200
            # key1 exhausted, key2 fresh
            resp = c.get("/test", headers={"Authorization": "Bearer key2"})
            assert resp.status_code == 200
            # key1 should be blocked
            resp = c.get("/test", headers={"Authorization": "Bearer key1"})
            assert resp.status_code == 429
