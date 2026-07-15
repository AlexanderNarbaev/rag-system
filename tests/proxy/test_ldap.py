"""Tests for proxy/app/auth/ldap.py — LDAP/AD authentication module."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _inject_mock_ldap3 ():
  """Inject a mock ldap3 module into sys.modules for testing."""
  if "ldap3" not in sys.modules:
    mock_ldap3 = MagicMock ()
    mock_ldap3.ALL = "ALL"
    sys.modules ["ldap3"] = mock_ldap3
  return sys.modules ["ldap3"]


class TestBuildUserDn:
  """Tests for _build_user_dn helper."""

  @patch ("proxy.app.auth.ldap.AD_USER_DN_TEMPLATE", "cn={username},ou=users,dc=example,dc=com")
  @patch ("proxy.app.auth.ldap.AD_BASE_DN", "dc=example,dc=com")
  def test_build_dn_from_template (self):
    from proxy.app.auth.ldap import _build_user_dn

    dn = _build_user_dn ("john")
    assert dn == "cn=john,ou=users,dc=example,dc=com"

  @patch ("proxy.app.auth.ldap.AD_USER_DN_TEMPLATE", "{username}@example.com")
  @patch ("proxy.app.auth.ldap.AD_BASE_DN", "")
  def test_build_dn_without_base_dn_placeholder (self):
    from proxy.app.auth.ldap import _build_user_dn

    dn = _build_user_dn ("john")
    assert dn == "john@example.com"

  @patch ("proxy.app.auth.ldap.AD_USER_DN_TEMPLATE", None)
  @patch ("proxy.app.auth.ldap.AD_BASE_DN", "dc=corp,dc=com")
  def test_build_dn_default_template (self):
    from proxy.app.auth.ldap import _build_user_dn

    dn = _build_user_dn ("alice")
    assert "alice" in dn
    assert "dc=corp,dc=com" in dn

  @patch ("proxy.app.auth.ldap.AD_USER_DN_TEMPLATE", "cn={username},{base_dn}")
  @patch ("proxy.app.auth.ldap.AD_BASE_DN", "")
  def test_build_dn_empty_base_dn (self):
    from proxy.app.auth.ldap import _build_user_dn

    dn = _build_user_dn ("bob")
    # When AD_BASE_DN is empty, {base_dn} is not replaced (falsy check)
    assert dn == "cn=bob,{base_dn}"


class TestAuthenticateLdap:
  """Tests for authenticate_ldap entry point."""

  @pytest.fixture (autouse = True)
  def _cleanup_ldap3_mock (self):
    """Clean up ldap3 mock after each test to avoid test isolation issues."""
    yield
    # Remove the mock ldap3 from sys.modules after each test
    sys.modules.pop ("ldap3", None)

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.AD_ENABLED", False)
  async def test_returns_none_when_disabled (self):
    from proxy.app.auth.ldap import authenticate_ldap

    result = await authenticate_ldap ("user", "pass")
    assert result is None

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.AD_ENABLED", True)
  @patch ("proxy.app.auth.ldap.AD_URL", "")
  async def test_returns_none_when_no_url (self):
    from proxy.app.auth.ldap import authenticate_ldap

    result = await authenticate_ldap ("user", "pass")
    assert result is None

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.AD_ENABLED", True)
  @patch ("proxy.app.auth.ldap.AD_URL", "ldap://dc.example.com")
  @patch ("proxy.app.auth.ldap._build_user_dn", return_value = "")
  async def test_returns_none_when_dn_empty (self, mock_dn):
    from proxy.app.auth.ldap import authenticate_ldap

    result = await authenticate_ldap ("user", "pass")
    assert result is None

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.AD_ENABLED", True)
  @patch ("proxy.app.auth.ldap.AD_URL", "ldap://dc.example.com")
  @patch ("proxy.app.auth.ldap._build_user_dn", return_value = "cn=user,dc=example,dc=com")
  async def test_returns_none_on_bind_failure (self, mock_dn):
    mock_ldap3 = _inject_mock_ldap3 ()
    mock_ldap3.Connection.side_effect = Exception ("Connection refused")

    from proxy.app.auth.ldap import authenticate_ldap

    result = await authenticate_ldap ("user", "pass")
    assert result is None
    mock_ldap3.Connection.side_effect = None  # Reset

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.AD_ENABLED", True)
  @patch ("proxy.app.auth.ldap.AD_URL", "ldap://dc.example.com")
  @patch ("proxy.app.auth.ldap._build_user_dn", return_value = "cn=user,dc=example,dc=com")
  @patch ("proxy.app.auth.ldap._sync_ldap_user")
  async def test_successful_auth (self, mock_sync, mock_dn):
    mock_ldap3 = _inject_mock_ldap3 ()
    mock_ldap3.Connection.side_effect = None

    from proxy.app.auth.ldap import authenticate_ldap

    mock_sync.return_value = {"user_id": "u1", "username": "user"}

    result = await authenticate_ldap ("user", "pass")
    assert result is not None
    assert result ["username"] == "user"
    mock_sync.assert_called_once_with ("user")

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.AD_ENABLED", True)
  @patch ("proxy.app.auth.ldap.AD_URL", "ldap://dc.example.com")
  @patch ("proxy.app.auth.ldap._build_user_dn", return_value = "cn=user,dc=example,dc=com")
  @patch ("proxy.app.auth.ldap._sync_ldap_user")
  async def test_unbind_exception_handled (self, mock_sync, mock_dn):
    """Test that unbind() exception is swallowed gracefully."""
    mock_ldap3 = _inject_mock_ldap3 ()
    mock_ldap3.Connection.side_effect = None

    mock_conn_instance = MagicMock ()
    mock_conn_instance.unbind.side_effect = Exception ("unbind failed")
    mock_ldap3.Connection.return_value = mock_conn_instance

    from proxy.app.auth.ldap import authenticate_ldap

    mock_sync.return_value = {"user_id": "u1", "username": "user"}

    result = await authenticate_ldap ("user", "pass")
    assert result is not None

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.AD_ENABLED", True)
  @patch ("proxy.app.auth.ldap.AD_URL", "ldap://dc.example.com")
  @patch ("proxy.app.auth.ldap._build_user_dn", return_value = "cn=user,dc=example,dc=com")
  async def test_returns_none_when_ldap3_not_installed (self, mock_dn):
    """Test graceful degradation when ldap3 import fails."""
    # Temporarily remove ldap3 from sys.modules and make import fail
    saved = sys.modules.pop ("ldap3", None)
    try:
      # Patch __import__ to fail for ldap3
      real_import = __builtins__.__import__ if hasattr (__builtins__, "__import__") else __import__

      def fake_import (name, *args, **kwargs):
        if name == "ldap3":
          raise ImportError ("No module named 'ldap3'")
        return real_import (name, *args, **kwargs)

      with patch ("builtins.__import__", side_effect = fake_import):
        from proxy.app.auth.ldap import authenticate_ldap

        result = await authenticate_ldap ("user", "pass")
        assert result is None
    finally:
      if saved is not None:
        sys.modules ["ldap3"] = saved


class TestSyncLdapUser:
  """Tests for _sync_ldap_user."""

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.get_user_db")
  async def test_returns_existing_user (self, mock_get_db):
    from proxy.app.auth.ldap import _sync_ldap_user

    mock_db = AsyncMock ()
    mock_db.get_user_by_username.return_value = {"user_id": "u1", "username": "john"}
    mock_get_db.return_value = mock_db

    result = await _sync_ldap_user ("john")
    assert result ["user_id"] == "u1"
    mock_db.create_user.assert_not_called ()

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.get_user_db")
  async def test_creates_new_user (self, mock_get_db):
    from proxy.app.auth.ldap import _sync_ldap_user

    mock_db = AsyncMock ()
    mock_db.get_user_by_username.return_value = None
    mock_db.create_user.return_value = {"user_id": "u_new", "username": "newuser"}
    mock_db.get_user.return_value = {"user_id": "u_new", "username": "newuser", "roles": ["user"]}
    mock_get_db.return_value = mock_db

    await _sync_ldap_user ("newuser")
    mock_db.create_user.assert_called_once ()
    call_kwargs = mock_db.create_user.call_args
    assert call_kwargs [1] ["username"] == "newuser"
    assert call_kwargs [1] ["roles"] == ["user"]

  @pytest.mark.asyncio
  @patch ("proxy.app.auth.ldap.get_user_db")
  async def test_handles_race_condition (self, mock_get_db):
    """Test race condition: user created between check and create."""
    from proxy.app.auth.ldap import _sync_ldap_user

    mock_db = AsyncMock ()
    mock_db.get_user_by_username.side_effect = [None, {"user_id": "u_race", "username": "racer"}]
    mock_db.create_user.side_effect = ValueError ("already exists")
    mock_db.get_user.return_value = None
    mock_get_db.return_value = mock_db

    result = await _sync_ldap_user ("racer")
    assert result ["user_id"] == "u_race"
