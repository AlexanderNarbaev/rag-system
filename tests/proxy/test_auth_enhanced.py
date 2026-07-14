"""Tests for enhanced auth.py — validate_jwt, require_auth, AuthMiddleware, Keycloak OIDC, mock JWT."""

from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

from proxy.app.auth import (
  AuthMiddleware, UserContext, create_token, verify_token,
)
from proxy.app.auth.jwt import (
  create_mock_token, require_auth, validate_jwt,
)


@pytest.fixture (autouse = True)
def _set_jwt_secret (monkeypatch):
  monkeypatch.setenv ("JWT_SECRET", "test-secret-key-for-unit-tests")
  monkeypatch.setattr ("proxy.app.shared.config.JWT_SECRET", "test-secret-key-for-unit-tests")
  monkeypatch.setattr ("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-unit-tests")
  monkeypatch.setattr ("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
  monkeypatch.setattr ("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")
  monkeypatch.setattr ("proxy.app.shared.config.AUTH_ENABLED", False)
  monkeypatch.setattr ("proxy.app.auth.jwt.AUTH_ENABLED", False)


class TestValidateJwt:
  @pytest.mark.asyncio
  async def test_valid_token_returns_user_context (self):
    token = create_token (user_id = "u1", username = "alice", roles = ["developer"], groups = ["engineering"],
        namespace = "eng", )
    ctx = await validate_jwt (token)
    assert isinstance (ctx, UserContext)
    assert ctx.user_id == "u1"
    assert ctx.namespace == "eng"
  
  @pytest.mark.asyncio
  async def test_expired_token_raises_401 (self):
    token = create_token (user_id = "u1", username = "alice", expires_in_hours = -1)
    with pytest.raises (HTTPException) as exc_info:
      await validate_jwt (token)
    assert exc_info.value.status_code == 401


class TestRequireAuth:
  @pytest.mark.asyncio
  async def test_returns_anonymous_when_auth_disabled (self):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", False):
      mock_request = MagicMock ()
      ctx = await require_auth (mock_request, credentials = None)
      assert ctx.user_id == "anonymous"
  
  @pytest.mark.asyncio
  async def test_raises_401_when_no_token_and_auth_enabled (self):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      mock_request = MagicMock ()
      mock_request.headers = {}
      with pytest.raises (HTTPException) as exc_info:
        await require_auth (mock_request, credentials = None)
      assert exc_info.value.status_code == 401


class TestUserContextNamespace:
  def test_namespace_from_token (self):
    token = create_token (user_id = "u1", username = "alice", namespace = "engineering", )
    ctx = verify_token (token)
    assert ctx.namespace == "engineering"
  
  def test_effective_namespace_uses_explicit (self):
    ctx = UserContext (user_id = "u1", username = "alice", namespace = "explicit_ns", groups = ["group1"])
    assert ctx.effective_namespace == "explicit_ns"
  
  def test_effective_namespace_falls_back_to_group (self):
    ctx = UserContext (user_id = "u1", username = "alice", groups = ["eng-group", "platform"])
    assert ctx.effective_namespace == "eng-group"
  
  def test_effective_namespace_empty (self):
    ctx = UserContext (user_id = "u1", username = "alice")
    assert ctx.effective_namespace == ""
  
  def test_anonymous_has_no_namespace (self):
    ctx = UserContext.anonymous ()
    assert ctx.namespace == ""
    assert ctx.effective_namespace == "everyone"


class TestCreateMockToken:
  def test_creates_valid_mock_token (self):
    token = create_mock_token (user_id = "mock-1", username = "mockuser", roles = ["admin"], groups = ["test-group"],
        namespace = "test-ns", )
    assert isinstance (token, str)
    decoded = jwt.decode (token, key = "test-secret-key-for-unit-tests", algorithms = ["HS256"],
        options = {"verify_exp": False}, )
    assert decoded ["sub"] == "mock-1"
    assert decoded ["roles"] == ["admin"]
    assert decoded ["namespace"] == "test-ns"
  
  def test_mock_token_defaults (self):
    token = create_mock_token ()
    decoded = jwt.decode (token, key = "test-secret-key-for-unit-tests", algorithms = ["HS256"],
        options = {"verify_exp": False}, )
    assert decoded ["sub"] == "test-user"
    assert decoded ["roles"] == ["user"]


class TestAuthMiddleware:
  @pytest.fixture
  def middleware (self):
    async def dummy_app (scope, receive, send):
      pass
    
    return AuthMiddleware (app = dummy_app)
  
  @pytest.mark.asyncio
  async def test_auth_disabled_passes_through (self, middleware):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", False):
      request = MagicMock (spec = StarletteRequest)
      request.url.path = "/v1/chat/completions"
      
      async def call_next (req):
        return JSONResponse ({"status": "ok"}, status_code = 200)
      
      response = await middleware.dispatch (request, call_next)
      assert response.status_code == 200
      assert request.state.user_context.user_id == "anonymous"
  
  @pytest.mark.asyncio
  async def test_public_endpoints_bypass_auth (self, middleware):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      for path in ["/v1/auth/login", "/v1/auth/refresh", "/v1/health", "/metrics"]:
        request = MagicMock (spec = StarletteRequest)
        request.url.path = path
        
        async def call_next (req):
          return JSONResponse ({"status": "ok"}, status_code = 200)
        
        response = await middleware.dispatch (request, call_next)
        assert response.status_code == 200
  
  @pytest.mark.asyncio
  async def test_no_token_returns_401 (self, middleware):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      request = MagicMock (spec = StarletteRequest)
      request.url.path = "/v1/chat/completions"
      request.headers = {}
      
      async def call_next (req):
        return JSONResponse ({}, status_code = 200)
      
      response = await middleware.dispatch (request, call_next)
      assert response.status_code == 401
  
  @pytest.mark.asyncio
  async def test_valid_token_passes (self, middleware):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      request = MagicMock (spec = StarletteRequest)
      request.url.path = "/v1/chat/completions"
      token = create_token (user_id = "u1", username = "alice")
      request.headers = {"authorization": f"Bearer {token}"}
      
      async def call_next (req):
        return JSONResponse ({"status": "ok"}, status_code = 200)
      
      response = await middleware.dispatch (request, call_next)
      assert response.status_code == 200
      assert request.state.user_context.user_id == "u1"
  
  @pytest.mark.asyncio
  async def test_x_auth_token_header (self, middleware):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      request = MagicMock (spec = StarletteRequest)
      request.url.path = "/v1/chat/completions"
      token = create_token (user_id = "u2", username = "bob")
      request.headers = {"x-auth-token": token}
      
      async def call_next (req):
        return JSONResponse ({}, status_code = 200)
      
      response = await middleware.dispatch (request, call_next)
      assert response.status_code == 200
      assert request.state.user_context.user_id == "u2"
  
  @pytest.mark.asyncio
  async def test_non_v1_routes_pass_through (self, middleware):
    with patch ("proxy.app.auth.jwt.AUTH_ENABLED", True):
      request = MagicMock (spec = StarletteRequest)
      request.url.path = "/docs"
      request.headers = {}
      
      async def call_next (req):
        return JSONResponse ({}, status_code = 200)
      
      response = await middleware.dispatch (request, call_next)
      assert response.status_code == 200
