# proxy/app/api/auth_endpoints.py
"""Authentication endpoints — login, register, refresh, logout, user info."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from proxy.app.auth import UserContext, get_auth_context, get_optional_auth_context
from proxy.app.auth.user_db import get_user_db

logger = logging.getLogger ("rag-proxy")

router = APIRouter (tags = ["auth"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class LoginRequest (BaseModel):
  username: str
  password: str
  expires_in_hours: int | None = 24


class LoginResponse (BaseModel):
  access_token: str
  refresh_token: str | None = None
  token_type: str = "bearer"
  expires_in: int
  user_id: str
  username: str
  roles: list [str]
  groups: list [str]


class RefreshRequest (BaseModel):
  token: str


class RefreshResponse (BaseModel):
  access_token: str
  refresh_token: str | None = None
  token_type: str = "bearer"
  expires_in: int


class RegisterRequest (BaseModel):
  username: str = Field (..., min_length = 2, max_length = 64)
  password: str = Field (..., min_length = 8, max_length = 128)
  email: str | None = None


class RegisterResponse (BaseModel):
  user_id: str
  username: str
  created_at: str


class LogoutRequest (BaseModel):
  refresh_token: str | None = None
  all_sessions: bool = False


class LogoutResponse (BaseModel):
  status: str
  message: str


class UserInfoResponse (BaseModel):
  user_id: str
  username: str
  roles: list [str]
  groups: list [str]
  access_level: str
  is_admin: bool
  is_authenticated: bool


# ---------------------------------------------------------------------------
# Brute-force protection (in-memory)
# ---------------------------------------------------------------------------

_LOGIN_ATTEMPTS: dict [str, tuple [int, float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_COOLDOWN_SECONDS = 900


def _check_login_rate_limit (identifier: str) -> None:
  """Check and update login rate limit for an identifier (username or IP).
  Raises HTTPException if rate limit exceeded."""
  now = time.time ()
  if identifier in _LOGIN_ATTEMPTS:
    count, first_attempt = _LOGIN_ATTEMPTS [identifier]
    if now - first_attempt > _LOGIN_WINDOW_SECONDS:
      _LOGIN_ATTEMPTS [identifier] = (1, now)
      return
    if count >= _LOGIN_MAX_ATTEMPTS:
      if now - first_attempt < _LOGIN_COOLDOWN_SECONDS:
        wait = int (_LOGIN_COOLDOWN_SECONDS - (now - first_attempt))
        raise HTTPException (status_code = 429, detail = f"Too many login attempts. Try again in {wait} seconds.", )
      else:
        _LOGIN_ATTEMPTS [identifier] = (1, now)
        return
    _LOGIN_ATTEMPTS [identifier] = (count + 1, first_attempt)
  else:
    _LOGIN_ATTEMPTS [identifier] = (1, now)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post ("/v1/auth/register", response_model = RegisterResponse, status_code = 201)
async def auth_register (request: RegisterRequest, raw_request: Request) -> RegisterResponse:
  """Register a new user account.

  Stores user with bcrypt-hashed password in SQLite.
  Rate-limited to prevent abuse: 3 registrations per IP per minute.
  """
  from proxy.app.shared.config import AUTH_ENABLED

  client_ip = raw_request.client.host if raw_request.client else "unknown"
  _check_login_rate_limit (f"register:{client_ip}")

  if not AUTH_ENABLED:
    raise HTTPException (status_code = 400, detail = "Registration is not enabled. Set AUTH_ENABLED=true.")

  db = get_user_db ()
  try:
    user = await db.create_user (username = request.username, password = request.password,
        email = request.email or "", )
  except ValueError as e:
    raise HTTPException (status_code = 409, detail = str (e)) from None

  logger.info ("User registered: %s from %s", request.username, client_ip)
  return RegisterResponse (user_id = user ["user_id"], username = user ["username"], created_at = user ["created_at"], )


@router.post ("/v1/auth/login", response_model = LoginResponse)
async def auth_login (request: LoginRequest, raw_request: Request) -> LoginResponse:
  """Authenticate user and return a token pair (access + refresh).

  Checks against SQLite user database (with bcrypt password verification).
  Legacy AUTH_VALID_USERS env var is auto-migrated on first startup.
  When AD_ENABLED=true, also attempts LDAP bind before falling back to local.
  """
  client_ip = raw_request.client.host if raw_request.client else "unknown"
  rate_limit_key = f"login:{client_ip}:{request.username}"

  _check_login_rate_limit (rate_limit_key)

  db = get_user_db ()

  # Check local database
  user = await db.verify_password (request.username, request.password)

  # LDAP fallback (if enabled)
  if user is None:
    from proxy.app.shared.config import AD_ENABLED

    if AD_ENABLED:
      try:
        from proxy.app.auth.ldap import authenticate_ldap

        user = await authenticate_ldap (request.username, request.password)
        if user:
          logger.info ("LDAP authentication successful for %s", request.username)
      except Exception as e:
        logger.warning ("LDAP authentication failed for %s: %s", request.username, e)

  if user is None:
    raise HTTPException (status_code = 401, detail = "Invalid credentials")

  if not user.get ("is_active", 1):
    raise HTTPException (status_code = 403, detail = "Account is deactivated")

  # Create token pair
  from proxy.app.auth.jwt import create_token_pair

  token_pair = await create_token_pair (user)

  return LoginResponse (access_token = token_pair ["access_token"], refresh_token = token_pair ["refresh_token"],
      token_type = "bearer", expires_in = token_pair ["expires_in"], user_id = user ["id"],
      username = user ["username"], roles = user.get ("roles", ["user"]), groups = user.get ("groups", []), )


@router.post ("/v1/auth/refresh", response_model = RefreshResponse)
async def auth_refresh (request: RefreshRequest) -> RefreshResponse:
  """Exchange a refresh token (or valid access token) for a new token pair.

  Backward-compatible: tries refresh token first. Falls back to validating
  as an access token for old clients that don't have refresh tokens yet.
  On access token validation, issues a full token pair (upgrade path).
  """
  from proxy.app.auth.jwt import create_token_pair, verify_refresh_token, verify_token
  from proxy.app.shared.config import AUTH_ENABLED

  if not AUTH_ENABLED:
    raise HTTPException (status_code = 400, detail = "Authentication is not enabled")

  # Try refresh token first (preferred path)
  user = await verify_refresh_token (request.token)

  if user is None:
    # Fallback: try as access token (backward compat for old clients)
    try:
      user_ctx = verify_token (request.token)
      user = {
          "id": user_ctx.user_id, "username": user_ctx.username, "roles": user_ctx.roles, "groups": user_ctx.groups,
          "access_level": user_ctx.access_level, "namespace": user_ctx.namespace,
      }
    except Exception:
      raise HTTPException (status_code = 401, detail = "Invalid or expired refresh token") from None

  # Issue new token pair
  token_pair = await create_token_pair (user)

  return RefreshResponse (access_token = token_pair ["access_token"], refresh_token = token_pair ["refresh_token"],
      token_type = "bearer", expires_in = token_pair ["expires_in"], )


@router.post ("/v1/auth/logout", response_model = LogoutResponse)
async def auth_logout (
    request: LogoutRequest, user: UserContext = Depends (get_optional_auth_context),  # noqa: B008
) -> LogoutResponse:
  """Logout: revoke refresh tokens and optionally blacklist the current access token.

  When all_sessions=true, revokes all refresh tokens for the authenticated user.
  When refresh_token is provided, revokes only that specific token.
  """
  db = get_user_db ()

  if request.refresh_token:
    await db.consume_refresh_token (request.refresh_token)
    logger.info ("Refresh token revoked for user %s", user.username)

  if request.all_sessions and user.is_authenticated:
    count = await db.revoke_user_tokens (user.user_id)
    logger.info ("All sessions revoked for user %s (%d tokens)", user.username, count)

  return LogoutResponse (status = "ok", message = "Logged out successfully")


@router.get ("/v1/auth/me", response_model = UserInfoResponse)
async def auth_me (user: UserContext = Depends (get_auth_context)) -> UserInfoResponse:  # noqa: B008
  """Return the current authenticated user's context."""
  return UserInfoResponse (user_id = user.user_id, username = user.username, roles = user.roles, groups = user.groups,
      access_level = user.access_level, is_admin = user.is_admin, is_authenticated = user.is_authenticated, )
