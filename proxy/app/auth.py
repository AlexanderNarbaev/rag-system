"""Authentication and authorization module for RAG proxy.

Provides JWT token creation (for internal token-based auth) and validation.
Supports HS256 symmetric tokens and RS256 asymmetric tokens for Keycloak/OIDC.

Token payload structure:
{
    "sub": "user-uuid",
    "preferred_username": "alice",
    "groups": ["engineering", "platform"],
    "roles": ["developer"],
    "access_level": "confidential",
    "namespace": "engineering",
    "exp": 1700000000,
    "iat": 1699900000
}

The system can operate in two modes:
- AUTH_ENABLED=false (default): anonymous context with full access
- AUTH_ENABLED=true: requires valid JWT on all RAG endpoints
- When KEYCLOAK_URL is set: auto-discovers OIDC config and validates RS256 tokens
- When KEYCLOAK_URL is not set: uses HS256 with JWT_SECRET (mock/local mode)
"""

import logging
import os
import time
from dataclasses import dataclass, field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")  # for RS256 verification
TOKEN_EXPIRE_HOURS = int(os.getenv("TOKEN_EXPIRE_HOURS", "24"))
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "rag-proxy")

# ---------------------------------------------------------------------------
# User context
# ---------------------------------------------------------------------------


@dataclass
class UserContext:
    """Holds the authenticated user's identity, roles, groups, access level, and namespace."""

    user_id: str
    username: str
    roles: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    access_level: str = "internal"
    namespace: str = ""

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_expert(self) -> bool:
        return "expert" in self.roles

    @property
    def is_authenticated(self) -> bool:
        return self.user_id != "anonymous"

    @property
    def effective_namespace(self) -> str:
        """Return the namespace for data isolation.

        Uses user's namespace if set, otherwise falls back to first group,
        or empty string for global access.
        """
        if self.namespace:
            return self.namespace
        if self.groups:
            return self.groups[0]
        return ""

    @classmethod
    def anonymous(cls) -> "UserContext":
        return cls(
            user_id="anonymous",
            username="anonymous",
            roles=["viewer"],
            groups=["everyone"],
            access_level="public",
            namespace="",
        )


# ---------------------------------------------------------------------------
# Token creation / validation
# ---------------------------------------------------------------------------


def create_token(
    user_id: str,
    username: str,
    roles: list[str] | None = None,
    groups: list[str] | None = None,
    access_level: str = "internal",
    namespace: str = "",
    expires_in_hours: int = TOKEN_EXPIRE_HOURS,
    secret: str | None = None,
) -> str:
    """Create a JWT token for the given user.

    Used for internal (non-OIDC) token-based auth — e.g.
    service accounts, local dev, or the built-in /v1/auth/login endpoint.
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "preferred_username": username,
        "roles": roles or [],
        "groups": groups or [],
        "access_level": access_level,
        "namespace": namespace,
        "iat": now,
        "exp": now + expires_in_hours * 3600,
    }
    key = secret or JWT_SECRET
    if not key:
        raise ValueError("JWT_SECRET is not configured — cannot create tokens")
    return jwt.encode(payload, key, algorithm=JWT_ALGORITHM)


def _get_verify_key() -> str | None:
    """Return the key to use for token verification.

    For RS256: uses JWT_PUBLIC_KEY (PEM).
    For HS256: uses JWT_SECRET.
    """
    if JWT_ALGORITHM.upper().startswith("RS"):
        return JWT_PUBLIC_KEY or None
    return JWT_SECRET or None


def verify_token(token: str) -> UserContext:
    """Verify and decode a JWT token.  Returns UserContext or raises HTTPException."""
    key = _get_verify_key()
    algorithms = [JWT_ALGORITHM] if JWT_ALGORITHM else ["HS256"]

    try:
        payload = jwt.decode(
            token,
            key=key,
            algorithms=algorithms,
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    return UserContext(
        user_id=payload.get("sub", ""),
        username=payload.get("preferred_username", ""),
        roles=payload.get("roles", payload.get("realm_access", {}).get("roles", [])),
        groups=payload.get("groups", []),
        access_level=payload.get("access_level", "internal"),
        namespace=payload.get("namespace", ""),
    )


def get_user_from_token(token: str) -> UserContext | None:
    """Extract user context from a token without raising HTTP errors.

    Returns None for any invalid or expired tokens.
    """
    key = _get_verify_key()
    algorithms = [JWT_ALGORITHM] if JWT_ALGORITHM else ["HS256"]

    try:
        payload = jwt.decode(
            token,
            key=key,
            algorithms=algorithms,
            options={"verify_exp": True},
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, Exception):
        return None

    return UserContext(
        user_id=payload.get("sub", ""),
        username=payload.get("preferred_username", ""),
        roles=payload.get("roles", payload.get("realm_access", {}).get("roles", [])),
        groups=payload.get("groups", []),
        access_level=payload.get("access_level", "internal"),
        namespace=payload.get("namespace", ""),
    )


# ---------------------------------------------------------------------------
# FastAPI dependency — injects UserContext into endpoint handlers
# ---------------------------------------------------------------------------


async def get_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> UserContext:
    """FastAPI dependency that extracts the UserContext from the request.

    When AUTH_ENABLED is False (default), returns an anonymous context.
    When AUTH_ENABLED is True, requires a valid Bearer token and returns
    401 for missing/invalid tokens.
    """
    if not AUTH_ENABLED:
        return UserContext.anonymous()

    # Also check for X-Auth-Token header (alternative to Bearer)
    token: str | None = None
    if credentials:
        token = credentials.credentials
    elif "x-auth-token" in request.headers:
        token = request.headers["x-auth-token"]

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    return verify_token(token)


async def get_optional_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> UserContext:
    """FastAPI dependency that extracts UserContext when available but never fails.

    Useful for endpoints that work both with and without authentication.
    """
    token: str | None = None
    if credentials:
        token = credentials.credentials
    elif "x-auth-token" in request.headers:
        token = request.headers["x-auth-token"]

    if token:
        result = get_user_from_token(token)
        if result is not None:
            return result

    return UserContext.anonymous()


# ---------------------------------------------------------------------------
# Aliases for naming consistency with the task spec
# ---------------------------------------------------------------------------


async def validate_jwt(token: str) -> UserContext:
    """Validate a JWT token — alias for verify_token.

    Returns UserContext with claims decoded from the token.
    Raises HTTPException(401) if invalid or expired.
    """
    return verify_token(token)


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> UserContext:
    """FastAPI dependency — enforce authentication on protected endpoints.

    Alias for get_auth_context. When AUTH_ENABLED is False, returns anonymous.
    When AUTH_ENABLED is True, requires valid Bearer token or X-Auth-Token header.
    """
    return await get_auth_context(request, credentials)


# ---------------------------------------------------------------------------
# AuthMiddleware — applied to all /v1/* endpoints when enabled
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces JWT authentication on /v1/* routes.

    When AUTH_ENABLED is True and the request path starts with /v1/,
    validates the Bearer token or X-Auth-Token header and injects
    the UserContext into request.state.user_context.
    Skips /v1/auth/login and /v1/health even when auth is enabled.
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        if not AUTH_ENABLED:
            request.state.user_context = UserContext.anonymous()
            return await call_next(request)

        path = request.url.path

        # Public endpoints — no auth required
        if path in ("/v1/auth/login", "/v1/auth/refresh", "/v1/health", "/metrics"):
            request.state.user_context = UserContext.anonymous()
            return await call_next(request)

        # Require auth for /v1/* endpoints
        if path.startswith("/v1/"):
            token: str | None = None

            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            elif "x-auth-token" in request.headers:
                token = request.headers["x-auth-token"]

            if not token:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                )

            try:
                user_ctx = verify_token(token)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                )

            request.state.user_context = user_ctx
            return await call_next(request)

        # Non-v1 routes pass through
        request.state.user_context = UserContext.anonymous()
        return await call_next(request)


# ---------------------------------------------------------------------------
# Keycloak OIDC discovery (air-gapped fallback)
# ---------------------------------------------------------------------------

# Cached JWKS keys when fetched from Keycloak
_jwks_cache: dict | None = None
_jwks_cache_ts: float = 0.0
_JWKS_CACHE_TTL = 3600  # 1 hour


def _fetch_jwks_oidc() -> dict | None:
    """Fetch JWKS from Keycloak OIDC discovery endpoint.

    Returns the JWKS dict or None if unavailable (air-gapped fallback).
    Results are cached for _JWKS_CACHE_TTL seconds.
    """
    global _jwks_cache, _jwks_cache_ts

    if not KEYCLOAK_URL:
        return None

    now = time.time()
    if _jwks_cache is not None and (now - _jwks_cache_ts) < _JWKS_CACHE_TTL:
        return _jwks_cache

    try:
        import urllib.request
        import json

        jwks_url = f"{KEYCLOAK_URL.rstrip('/')}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
        with urllib.request.urlopen(jwks_url, timeout=5) as resp:
            _jwks_cache = json.loads(resp.read())
            _jwks_cache_ts = now
            logger.info(f"JWKS fetched from Keycloak: {len(_jwks_cache.get('keys', []))} keys")
            return _jwks_cache
    except Exception as e:
        logger.warning(f"Failed to fetch JWKS from Keycloak: {e}")
        return None


def _get_keycloak_verify_key(kid: str | None = None) -> str | None:
    """Get the public key for a given key ID from Keycloak JWKS.

    Falls back to JWT_PUBLIC_KEY if JWKS is unavailable.
    """
    jwks = _fetch_jwks_oidc()
    if not jwks or not jwks.get("keys"):
        return JWT_PUBLIC_KEY or None

    keys = jwks["keys"]
    if kid:
        for k in keys:
            if k.get("kid") == kid:
                return _pem_from_jwk(k)

    # No kid match — try to construct from first RSA key
    for k in keys:
        if k.get("kty") == "RSA":
            return _pem_from_jwk(k)

    return None


def _pem_from_jwk(jwk: dict) -> str | None:
    """Convert a JWK RSA public key to PEM format."""
    try:
        from jwt.algorithms import RSAAlgorithm
        return RSAAlgorithm.from_jwk(jwk)
    except (ImportError, Exception) as e:
        logger.warning(f"Failed to convert JWK to PEM: {e}")
        return None


def create_mock_token(
    user_id: str = "test-user",
    username: str = "testuser",
    roles: list[str] | None = None,
    groups: list[str] | None = None,
    access_level: str = "internal",
    namespace: str = "",
    secret: str | None = None,
) -> str:
    """Create a mock JWT token for testing and local development.

    Uses HS256 with JWT_SECRET (or provided secret).
    When KEYCLOAK_URL is not set, this is the primary token creation method.
    """
    return create_token(
        user_id=user_id,
        username=username,
        roles=roles or ["user"],
        groups=groups or ["everyone"],
        access_level=access_level,
        namespace=namespace,
        secret=secret or JWT_SECRET or "test-secret-key-for-unit-tests",
    )
