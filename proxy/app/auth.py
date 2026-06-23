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
    "exp": 1700000000,
    "iat": 1699900000
}

The system can operate in two modes:
- AUTH_ENABLED=false (default): anonymous context with full access
- AUTH_ENABLED=true: requires valid JWT on all RAG endpoints
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
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

# ---------------------------------------------------------------------------
# User context
# ---------------------------------------------------------------------------


@dataclass
class UserContext:
    """Holds the authenticated user's identity, roles, groups, and access level."""

    user_id: str
    username: str
    roles: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    access_level: str = "internal"

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_expert(self) -> bool:
        return "expert" in self.roles

    @property
    def is_authenticated(self) -> bool:
        return self.user_id != "anonymous"

    @classmethod
    def anonymous(cls) -> "UserContext":
        return cls(
            user_id="anonymous",
            username="anonymous",
            roles=["viewer"],
            groups=["everyone"],
            access_level="public",
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
