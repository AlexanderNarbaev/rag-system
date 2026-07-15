# proxy/app/rate_limiter.py
"""
Token bucket rate limiter middleware.
Supports per-IP and per-API-key rate limiting with configurable limits.
"""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from proxy.app.shared.config import TRUSTED_PROXY_COUNT


class TokenBucket:
  """Single token bucket for rate limiting.

  Implements the token bucket algorithm where tokens are refilled
  at a constant rate up to a maximum burst capacity.
  """

  def __init__ (self, rate: float, burst: int):
    self.rate = rate
    self.burst = burst
    self.tokens = float (burst)
    self.last_refill = time.monotonic ()

  def _refill (self) -> None:
    """Refill tokens based on elapsed time since last refill."""
    now = time.monotonic ()
    elapsed = now - self.last_refill
    self.tokens = min (float (self.burst), self.tokens + elapsed * self.rate)
    self.last_refill = now

  def consume (self, tokens: int = 1) -> tuple [bool, float]:
    """Try to consume tokens. Returns (allowed, retry_after_seconds)."""
    self._refill ()
    if self.tokens >= tokens:
      self.tokens -= tokens
      return True, 0.0
    wait = (tokens - self.tokens) / self.rate
    return False, wait


class RateLimiter:
  """In-memory rate limiter with token bucket algorithm.

  Maintains per-key token buckets with configurable rate and burst.
  Supports async operations and automatic cleanup of expired buckets.
  """

  def __init__ (self, rate_per_minute: int = 60, burst: int = 10):
    self.rate_per_minute = rate_per_minute
    self.burst = burst
    self._buckets: dict [str, TokenBucket] = {}
    self._lock = asyncio.Lock ()

  @property
  def rate_per_second (self) -> float:
    """Convert rate_per_minute to tokens per second."""
    return self.rate_per_minute / 60.0

  async def _get_bucket (self, key: str) -> TokenBucket:
    async with self._lock:
      if key not in self._buckets:
        self._buckets [key] = TokenBucket (self.rate_per_second, self.burst)
      return self._buckets [key]

  async def is_allowed (self, key: str) -> tuple [bool, float]:
    """Check if a request is allowed for the given key.

    Returns:
        Tuple of (allowed, retry_after_seconds).
    """
    bucket = await self._get_bucket (key)
    return bucket.consume ()

  async def cleanup_expired (self, max_age: float = 300.0) -> None:
    """Remove buckets not used for max_age seconds."""
    now = time.monotonic ()
    async with self._lock:
      expired = [k for k, b in self._buckets.items () if now - b.last_refill > max_age]
      for k in expired:
        del self._buckets [k]


_limiter: RateLimiter | None = None


def get_rate_limiter () -> RateLimiter | None:
  """Return the global rate limiter instance (or None if not initialized)."""
  return _limiter


def init_rate_limiter (rate_per_minute: int = 60, burst: int = 10) -> RateLimiter:
  """Initialize and return the global rate limiter.

  Args:
      rate_per_minute: Maximum requests per minute per key.
      burst: Maximum burst size (token bucket capacity).

  Returns:
      The initialized RateLimiter instance.
  """
  global _limiter
  _limiter = RateLimiter (rate_per_minute = rate_per_minute, burst = burst)
  return _limiter


class RateLimitMiddleware (BaseHTTPMiddleware):
  """Middleware that enforces rate limits on incoming requests.

  Uses token bucket algorithm with per-IP or per-API-key tracking.
  Returns 429 with Retry-After header when limit is exceeded.
  """

  def __init__ (self, app: Any, limiter: RateLimiter):
    super ().__init__ (app)
    self._limiter = limiter

  def _extract_key (self, request: Request) -> str:
    """Extract rate limit key from request (IP or API key).

    Checks Authorization header for API keys, then falls back to
    client IP (considering X-Forwarded-For for proxied requests).
    """
    auth_header = request.headers.get ("Authorization", "")
    if auth_header.startswith ("Bearer "):
      return f"apikey:{auth_header [7:]}"
    client_host = request.client.host if request.client else "unknown"
    x_forwarded = request.headers.get ("X-Forwarded-For")
    if x_forwarded and TRUSTED_PROXY_COUNT > 0:
      # X-Forwarded-For: client, proxy1, proxy2, ...
      # Take the N-th IP from the right (TRUSTED_PROXY_COUNT=1 → last IP)
      ips = [ip.strip () for ip in x_forwarded.split (",")]
      idx = len (ips) - TRUSTED_PROXY_COUNT
      if idx >= 0:
        client_host = ips [idx]
    return f"ip:{client_host}"

  async def dispatch (self, request: Request, call_next: Callable [..., Any]) -> Response:
    """Enforce rate limits on incoming requests.

    Returns 429 with Retry-After header when limit is exceeded.
    """
    key = self._extract_key (request)
    allowed, retry_after = await self._limiter.is_allowed (key)
    if not allowed:
      retry_seconds = max (1, int (retry_after) + 1)
      return Response (content = json.dumps ({
          "error": {
              "message": "Rate limit exceeded. Please wait before retrying.", "type": "rate_limit_error",
              "retry_after_seconds": retry_seconds,
          }
      }), status_code = 429, media_type = "application/json", headers = {"Retry-After": str (retry_seconds)}, )
    response: Response = await call_next (request)
    return response


def add_rate_limit_middleware (app: FastAPI, rate_per_minute: int = 60, burst: int = 10) -> RateLimiter:
  """Add rate limiting middleware to a FastAPI app.

  Args:
      app: FastAPI application instance.
      rate_per_minute: Maximum requests per minute per key.
      burst: Maximum burst size.

  Returns:
      The initialized RateLimiter instance.
  """
  limiter = init_rate_limiter (rate_per_minute = rate_per_minute, burst = burst)
  app.add_middleware (RateLimitMiddleware, limiter = limiter)
  return limiter
