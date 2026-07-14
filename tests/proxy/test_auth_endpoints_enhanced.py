# ruff: noqa: E501, E402, N803, B017
"""Tests for proxy/app/api/auth_endpoints.py — auth endpoint coverage."""

import pytest


class TestLoginRateLimit:
  """Tests for _check_login_rate_limit."""
  
  def test_first_attempt_allowed (self):
    from proxy.app.api.auth_endpoints import _LOGIN_ATTEMPTS, _check_login_rate_limit
    
    _LOGIN_ATTEMPTS.clear ()
    _check_login_rate_limit ("test_user_1")
    assert "test_user_1" in _LOGIN_ATTEMPTS
  
  def test_max_attempts_exceeded (self):
    from proxy.app.api.auth_endpoints import _LOGIN_ATTEMPTS, _check_login_rate_limit
    
    _LOGIN_ATTEMPTS.clear ()
    import time
    
    now = time.time ()
    _LOGIN_ATTEMPTS ["locked_user"] = (5, now)
    with pytest.raises (Exception):
      _check_login_rate_limit ("locked_user")
  
  def test_window_expired_resets (self):
    from proxy.app.api.auth_endpoints import _LOGIN_ATTEMPTS, _check_login_rate_limit
    
    _LOGIN_ATTEMPTS.clear ()
    import time
    
    now = time.time () - 400  # past window
    _LOGIN_ATTEMPTS ["old_user"] = (5, now)
    _check_login_rate_limit ("old_user")
    assert _LOGIN_ATTEMPTS ["old_user"] [0] == 1
  
  def test_cooldown_expired_resets (self):
    from proxy.app.api.auth_endpoints import _LOGIN_ATTEMPTS, _check_login_rate_limit
    
    _LOGIN_ATTEMPTS.clear ()
    import time
    
    now = time.time () - 1000  # past cooldown
    _LOGIN_ATTEMPTS ["cool_user"] = (5, now)
    _check_login_rate_limit ("cool_user")
    assert _LOGIN_ATTEMPTS ["cool_user"] [0] == 1


class TestPydanticModels:
  """Test Pydantic models instantiate correctly."""
  
  def test_login_request (self):
    from proxy.app.api.auth_endpoints import LoginRequest
    
    req = LoginRequest (username = "user", password = "pass")
    assert req.username == "user"
    assert req.expires_in_hours == 24
  
  def test_register_request (self):
    from proxy.app.api.auth_endpoints import RegisterRequest
    
    req = RegisterRequest (username = "newuser", password = "password123", email = "test@test.com")
    assert req.username == "newuser"
  
  def test_refresh_request (self):
    from proxy.app.api.auth_endpoints import RefreshRequest
    
    req = RefreshRequest (token = "some-token")
    assert req.token == "some-token"
  
  def test_logout_request (self):
    from proxy.app.api.auth_endpoints import LogoutRequest
    
    req = LogoutRequest (refresh_token = "rt123", all_sessions = True)
    assert req.all_sessions is True
  
  def test_logout_request_defaults (self):
    from proxy.app.api.auth_endpoints import LogoutRequest
    
    req = LogoutRequest ()
    assert req.refresh_token is None
    assert req.all_sessions is False
  
  def test_login_response (self):
    from proxy.app.api.auth_endpoints import LoginResponse
    
    resp = LoginResponse (access_token = "at", refresh_token = "rt", expires_in = 3600, user_id = "u1",
        username = "user", roles = ["user"], groups = [], )
    assert resp.token_type == "bearer"
  
  def test_refresh_response (self):
    from proxy.app.api.auth_endpoints import RefreshResponse
    
    resp = RefreshResponse (access_token = "at", expires_in = 3600)
    assert resp.token_type == "bearer"
  
  def test_register_response (self):
    from proxy.app.api.auth_endpoints import RegisterResponse
    
    resp = RegisterResponse (user_id = "u1", username = "user", created_at = "2025-01-01")
    assert resp.user_id == "u1"
  
  def test_logout_response (self):
    from proxy.app.api.auth_endpoints import LogoutResponse
    
    resp = LogoutResponse (status = "ok", message = "Done")
    assert resp.status == "ok"
  
  def test_user_info_response (self):
    from proxy.app.api.auth_endpoints import UserInfoResponse
    
    resp = UserInfoResponse (user_id = "u1", username = "user", roles = ["user"], groups = [],
        access_level = "internal", is_admin = False, is_authenticated = True, )
    assert resp.is_authenticated is True
