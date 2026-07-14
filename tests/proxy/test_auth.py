"""Tests for proxy/app/auth.py — JWT token creation, validation, and auth dependencies."""

import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException

from proxy.app.auth import (
  UserContext, create_token, get_auth_context, get_optional_auth_context, verify_token,
)
from proxy.app.auth.jwt import get_user_from_token


# Override JWT_SECRET for reproducible tests
@pytest.fixture (autouse = True)
def _set_jwt_secret (monkeypatch):
  monkeypatch.setenv ("JWT_SECRET", "test-secret-key-for-unit-tests")
  monkeypatch.setattr ("proxy.app.shared.config.JWT_SECRET", "test-secret-key-for-unit-tests")
  monkeypatch.setattr ("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-unit-tests")
  monkeypatch.setattr ("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
  monkeypatch.setattr ("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")
  monkeypatch.setattr ("proxy.app.shared.config.AUTH_ENABLED", False)
  monkeypatch.setattr ("proxy.app.auth.jwt.AUTH_ENABLED", False)


# ---------------------------------------------------------------------------
# UserContext
# ---------------------------------------------------------------------------


class TestUserContext:
  def test_anonymous_has_viewer_role (self):
    ctx = UserContext.anonymous ()
    assert ctx.user_id == "anonymous"
    assert ctx.username == "anonymous"
    assert "viewer" in ctx.roles
    assert ctx.access_level == "public"
  
  def test_is_admin (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    assert ctx.is_admin is True
    assert ctx.is_expert is False
  
  def test_is_expert_includes_admin (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["expert"])
    assert ctx.is_expert is True
    assert ctx.is_admin is False
  
  def test_is_authenticated (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["developer"])
    assert ctx.is_authenticated is True
    anon = UserContext.anonymous ()
    assert anon.is_authenticated is False
  
  def test_fields_default_to_empty_lists (self):
    ctx = UserContext (user_id = "x", username = "y")
    assert ctx.roles == []
    assert ctx.groups == []


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


class TestCreateToken:
  def test_creates_valid_token (self):
    token = create_token (user_id = "u1", username = "alice", roles = ["developer"], groups = ["engineering"],
        access_level = "internal", )
    assert isinstance (token, str)
    assert len (token) > 0
    
    decoded = jwt.decode (token, key = "test-secret-key-for-unit-tests", algorithms = ["HS256"],
        options = {"verify_exp": False}, )
    assert decoded ["sub"] == "u1"
    assert decoded ["preferred_username"] == "alice"
    assert decoded ["roles"] == ["developer"]
    assert decoded ["groups"] == ["engineering"]
    assert decoded ["access_level"] == "internal"
    assert "iat" in decoded
    assert "exp" in decoded
  
  def test_expiration_set_correctly (self):
    token = create_token (user_id = "u1", username = "bob", expires_in_hours = 1, )
    decoded = jwt.decode (token, key = "test-secret-key-for-unit-tests", algorithms = ["HS256"],
        options = {"verify_exp": False}, )
    delta = decoded ["exp"] - decoded ["iat"]
    assert delta == 3600
  
  def test_defaults (self):
    token = create_token (user_id = "u1", username = "bob")
    decoded = jwt.decode (token, key = "test-secret-key-for-unit-tests", algorithms = ["HS256"],
        options = {"verify_exp": False}, )
    assert decoded ["roles"] == []
    assert decoded ["groups"] == []
    assert decoded ["access_level"] == "internal"
  
  def test_custom_secret (self):
    token = create_token (user_id = "u1", username = "alice", secret = "custom-secret-key", )
    decoded = jwt.decode (token, key = "custom-secret-key", algorithms = ["HS256"], options = {"verify_exp": False}, )
    assert decoded ["sub"] == "u1"
  
  def test_raises_without_secret (self, monkeypatch):
    monkeypatch.setattr ("proxy.app.shared.config.JWT_SECRET", "")
    monkeypatch.setattr ("proxy.app.auth.jwt.JWT_SECRET", "")
    with pytest.raises (ValueError, match = "JWT_SECRET is not configured"):
      create_token (user_id = "u1", username = "alice")


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


class TestVerifyToken:
  def test_valid_token_returns_user_context (self):
    token = create_token (user_id = "u1", username = "alice", roles = ["developer"], groups = ["engineering"],
        access_level = "confidential", )
    ctx = verify_token (token)
    assert isinstance (ctx, UserContext)
    assert ctx.user_id == "u1"
    assert ctx.username == "alice"
    assert ctx.roles == ["developer"]
    assert ctx.groups == ["engineering"]
    assert ctx.access_level == "confidential"
  
  def test_expired_token_raises_401 (self):
    token = create_token (user_id = "u1", username = "alice", expires_in_hours = -1, )
    with pytest.raises (HTTPException) as exc_info:
      verify_token (token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower ()
  
  def test_invalid_token_raises_401 (self):
    with pytest.raises (HTTPException) as exc_info:
      verify_token ("not.a.valid.token")
    assert exc_info.value.status_code == 401
    assert "invalid" in exc_info.value.detail.lower ()
  
  def test_tampered_token_raises_401 (self):
    token = create_token (user_id = "u1", username = "alice")
    parts = token.split (".")
    tampered = parts [0] + "." + "tampered" + "." + parts [2]
    with pytest.raises (HTTPException) as exc_info:
      verify_token (tampered)
    assert exc_info.value.status_code == 401
  
  def test_wrong_secret_raises_401 (self, monkeypatch):
    token = create_token (user_id = "u1", username = "alice")
    monkeypatch.setattr ("proxy.app.shared.config.JWT_SECRET", "different-key")
    monkeypatch.setattr ("proxy.app.auth.jwt.JWT_SECRET", "different-key")
    with pytest.raises (HTTPException) as exc_info:
      verify_token (token)
    assert exc_info.value.status_code == 401
  
  def test_realm_access_roles (self):
    now = int (time.time ())
    payload = {
        "sub": "u2", "preferred_username": "bob", "realm_access": {"roles": ["admin", "viewer"]}, "groups": [],
        "access_level": "internal", "iat": now, "exp": now + 3600,
    }
    token = jwt.encode (payload, key = "test-secret-key-for-unit-tests", algorithm = "HS256", )
    ctx = verify_token (token)
    assert ctx.roles == ["admin", "viewer"]


# ---------------------------------------------------------------------------
# get_user_from_token (non-raising)
# ---------------------------------------------------------------------------


class TestGetUserFromToken:
  def test_valid_token_returns_context (self):
    token = create_token (user_id = "u1", username = "alice")
    ctx = get_user_from_token (token)
    assert ctx is not None
    assert ctx.user_id == "u1"
  
  def test_expired_token_returns_none (self):
    token = create_token (user_id = "u1", username = "alice", expires_in_hours = -1)
    ctx = get_user_from_token (token)
    assert ctx is None
  
  def test_invalid_token_returns_none (self):
    ctx = get_user_from_token ("garbage")
    assert ctx is None
  
  def test_empty_string_returns_none (self):
    ctx = get_user_from_token ("")
    assert ctx is None


# ---------------------------------------------------------------------------
# get_auth_context dependency (auth disabled — default mode)
# ---------------------------------------------------------------------------


class TestGetAuthContext:
  @pytest.mark.asyncio
  async def test_returns_anonymous_when_auth_disabled (self):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", False):
      mock_request = MagicMock ()
      ctx = await get_auth_context (mock_request, credentials = None)
      assert ctx.user_id == "anonymous"
      assert "viewer" in ctx.roles
  
  @pytest.mark.asyncio
  async def test_raises_401_when_auth_enabled_and_no_token (self):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      mock_request = MagicMock ()
      mock_request.headers = {}
      with pytest.raises (HTTPException) as exc_info:
        await get_auth_context (mock_request, credentials = None)
      assert exc_info.value.status_code == 401
  
  @pytest.mark.asyncio
  async def test_uses_bearer_token (self):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      mock_request = MagicMock ()
      mock_request.headers = {}
      token = create_token (user_id = "u1", username = "alice")
      mock_credentials = MagicMock ()
      mock_credentials.credentials = token
      ctx = await get_auth_context (mock_request, credentials = mock_credentials)
      assert ctx.user_id == "u1"
  
  @pytest.mark.asyncio
  async def test_uses_x_auth_token_header (self):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      mock_request = MagicMock ()
      token = create_token (user_id = "u1", username = "alice")
      mock_request.headers = {"x-auth-token": token}
      ctx = await get_auth_context (mock_request, credentials = None)
      assert ctx.user_id == "u1"


# ---------------------------------------------------------------------------
# get_optional_auth_context dependency
# ---------------------------------------------------------------------------


class TestGetOptionalAuthContext:
  @pytest.mark.asyncio
  async def test_returns_anonymous_when_no_token (self):
    mock_request = MagicMock ()
    mock_request.headers = {}
    ctx = await get_optional_auth_context (mock_request, credentials = None)
    assert ctx.user_id == "anonymous"
  
  @pytest.mark.asyncio
  async def test_returns_context_when_token_present (self):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      mock_request = MagicMock ()
      mock_request.headers = {}
      token = create_token (user_id = "u1", username = "alice")
      mock_credentials = MagicMock ()
      mock_credentials.credentials = token
      ctx = await get_optional_auth_context (mock_request, credentials = mock_credentials)
      assert ctx.user_id == "u1"
  
  @pytest.mark.asyncio
  async def test_returns_anonymous_on_invalid_token (self):
    mock_request = MagicMock ()
    mock_request.headers = {"x-auth-token": "invalid_token"}
    ctx = await get_optional_auth_context (mock_request, credentials = None)
    assert ctx.user_id == "anonymous"
