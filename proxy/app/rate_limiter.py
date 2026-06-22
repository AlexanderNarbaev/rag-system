# proxy/app/rate_limiter.py
"""
Token bucket rate limiter middleware.
Supports per-IP and per-API-key rate limiting with configurable limits.
"""
import time
import asyncio
from typing import Dict, Tuple, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import FastAPI


class TokenBucket:
    """Single token bucket for rate limiting."""

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(float(self.burst), self.tokens + elapsed * self.rate)
        self.last_refill = now

    def consume(self, tokens: int = 1) -> Tuple[bool, float]:
        """Try to consume tokens. Returns (allowed, retry_after_seconds)."""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True, 0.0
        wait = (tokens - self.tokens) / self.rate
        return False, wait


class RateLimiter:
    """In-memory rate limiter with token bucket algorithm."""

    def __init__(self, rate_per_minute: int = 60, burst: int = 10):
        self.rate_per_minute = rate_per_minute
        self.burst = burst
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = asyncio.Lock()

    @property
    def rate_per_second(self) -> float:
        return self.rate_per_minute / 60.0

    async def _get_bucket(self, key: str) -> TokenBucket:
        async with self._lock:
            if key not in self._buckets:
                self._buckets[key] = TokenBucket(self.rate_per_second, self.burst)
            return self._buckets[key]

    async def is_allowed(self, key: str) -> Tuple[bool, float]:
        bucket = await self._get_bucket(key)
        return bucket.consume()

    async def cleanup_expired(self, max_age: float = 300.0):
        """Remove buckets not used for max_age seconds."""
        now = time.monotonic()
        async with self._lock:
            expired = [
                k for k, b in self._buckets.items()
                if now - b.last_refill > max_age
            ]
            for k in expired:
                del self._buckets[k]


_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> Optional[RateLimiter]:
    return _limiter


def init_rate_limiter(rate_per_minute: int = 60, burst: int = 10) -> RateLimiter:
    global _limiter
    _limiter = RateLimiter(rate_per_minute=rate_per_minute, burst=burst)
    return _limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces rate limits on incoming requests."""

    def __init__(self, app, limiter: RateLimiter):
        super().__init__(app)
        self._limiter = limiter

    def _extract_key(self, request: Request) -> str:
        """Extract rate limit key from request (IP or API key)."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return f"apikey:{auth_header[7:]}"
        client_host = request.client.host if request.client else "unknown"
        x_forwarded = request.headers.get("X-Forwarded-For")
        if x_forwarded:
            client_host = x_forwarded.split(",")[0].strip()
        return f"ip:{client_host}"

    async def dispatch(self, request: Request, call_next) -> Response:
        key = self._extract_key(request)
        allowed, retry_after = await self._limiter.is_allowed(key)
        if not allowed:
            retry_seconds = max(1, int(retry_after) + 1)
            return Response(
                content='{"error": "Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_seconds)},
            )
        response = await call_next(request)
        return response


def add_rate_limit_middleware(app: FastAPI, rate_per_minute: int = 60, burst: int = 10):
    """Add rate limiting middleware to a FastAPI app."""
    limiter = init_rate_limiter(rate_per_minute=rate_per_minute, burst=burst)
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
    return limiter
