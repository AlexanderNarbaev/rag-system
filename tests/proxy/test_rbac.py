"""Tests for proxy/app/rbac.py — role-based access control."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from proxy.app.auth import UserContext
from proxy.app.auth.rbac import Role, get_user_role, has_permission, require_role

_ENABLE_RBAC = patch ("proxy.app.auth.rbac.RBAC_ENABLED", True)


@pytest.fixture (autouse = True)
def _enable_rbac ():
  with _ENABLE_RBAC:
    yield


class TestRoleEnum:
  def test_role_values (self):
    assert Role.ADMIN.value == "admin"
    assert Role.EXPERT.value == "expert"
    assert Role.USER.value == "user"
    assert Role.READ_ONLY.value == "read_only"

  def test_role_from_string (self):
    assert Role ("admin") == Role.ADMIN
    assert Role ("expert") == Role.EXPERT

  def test_role_from_string_invalid (self):
    with pytest.raises (ValueError):
      Role ("superuser")


class TestGetUserRole:
  def test_admin_role (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin", "expert"])
    assert get_user_role (ctx) == Role.ADMIN

  def test_expert_role (self):
    ctx = UserContext (user_id = "2", username = "bob", roles = ["expert"])
    assert get_user_role (ctx) == Role.EXPERT

  def test_user_role (self):
    ctx = UserContext (user_id = "3", username = "carol", roles = ["user", "viewer"])
    assert get_user_role (ctx) == Role.USER

  def test_read_only_role (self):
    ctx = UserContext (user_id = "4", username = "dave", roles = ["read_only"])
    assert get_user_role (ctx) == Role.READ_ONLY

  def test_default_to_read_only (self):
    ctx = UserContext (user_id = "5", username = "eve", roles = [])
    assert get_user_role (ctx) == Role.READ_ONLY

  def test_anonymous_is_read_only (self):
    ctx = UserContext.anonymous ()
    assert get_user_role (ctx) == Role.READ_ONLY

  def test_highest_role_wins (self):
    ctx = UserContext (user_id = "6", username = "frank", roles = ["user", "admin"])
    assert get_user_role (ctx) == Role.ADMIN


class TestHasPermission:
  def test_admin_has_all_permissions (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    assert has_permission (ctx, "chat") is True
    assert has_permission (ctx, "feedback") is True
    assert has_permission (ctx, "admin:config") is True

  def test_expert_can_feedback (self):
    ctx = UserContext (user_id = "2", username = "bob", roles = ["expert"])
    assert has_permission (ctx, "feedback") is True
    assert has_permission (ctx, "chat") is True

  def test_expert_cannot_admin (self):
    ctx = UserContext (user_id = "2", username = "bob", roles = ["expert"])
    assert has_permission (ctx, "admin:config") is False

  def test_user_can_chat (self):
    ctx = UserContext (user_id = "3", username = "carol", roles = ["user"])
    assert has_permission (ctx, "chat") is True

  def test_user_cannot_feedback (self):
    ctx = UserContext (user_id = "3", username = "carol", roles = ["user"])
    assert has_permission (ctx, "feedback") is False

  def test_read_only_cannot_chat (self):
    ctx = UserContext (user_id = "4", username = "dave", roles = ["read_only"])
    assert has_permission (ctx, "chat") is False

  def test_read_only_can_list_models (self):
    ctx = UserContext (user_id = "4", username = "dave", roles = ["read_only"])
    assert has_permission (ctx, "models:list") is True

  def test_unknown_action_returns_false (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["user"])
    assert has_permission (ctx, "unknown_action") is False


class TestRequireRole:
  @pytest.mark.asyncio
  async def test_admin_required_with_admin (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    result = await require_role (Role.ADMIN) (ctx)
    assert result == ctx

  @pytest.mark.asyncio
  async def test_expert_required_with_expert (self):
    ctx = UserContext (user_id = "2", username = "bob", roles = ["expert"])
    result = await require_role (Role.EXPERT) (ctx)
    assert result == ctx

  @pytest.mark.asyncio
  async def test_expert_required_with_admin (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    result = await require_role (Role.EXPERT) (ctx)
    assert result == ctx

  @pytest.mark.asyncio
  async def test_admin_required_with_user_raises (self):
    ctx = UserContext (user_id = "3", username = "carol", roles = ["user"])
    with pytest.raises (HTTPException) as exc_info:
      await require_role (Role.ADMIN) (ctx)
    assert exc_info.value.status_code == 403

  @pytest.mark.asyncio
  async def test_expert_required_with_read_only_raises (self):
    ctx = UserContext (user_id = "4", username = "dave", roles = ["read_only"])
    with pytest.raises (HTTPException) as exc_info:
      await require_role (Role.EXPERT) (ctx)
    assert exc_info.value.status_code == 403

  @pytest.mark.asyncio
  async def test_user_required_with_read_only_raises (self):
    ctx = UserContext (user_id = "5", username = "eve", roles = ["read_only"])
    with pytest.raises (HTTPException) as exc_info:
      await require_role (Role.USER) (ctx)
    assert exc_info.value.status_code == 403

  @pytest.mark.asyncio
  async def test_user_required_with_user (self):
    ctx = UserContext (user_id = "3", username = "carol", roles = ["user"])
    result = await require_role (Role.USER) (ctx)
    assert result == ctx

  @pytest.mark.asyncio
  async def test_read_only_required_with_anonymous (self):
    ctx = UserContext.anonymous ()
    result = await require_role (Role.READ_ONLY) (ctx)
    assert result == ctx


class TestRoleHierarchy:
  RANK = {Role.ADMIN: 4, Role.EXPERT: 3, Role.USER: 2, Role.READ_ONLY: 1}

  def test_admin_is_highest (self):
    assert self.RANK [Role.ADMIN] > self.RANK [Role.EXPERT]
    assert self.RANK [Role.ADMIN] > self.RANK [Role.USER]

  def test_expert_above_user (self):
    assert self.RANK [Role.EXPERT] > self.RANK [Role.USER]

  def test_user_above_read_only (self):
    assert self.RANK [Role.USER] > self.RANK [Role.READ_ONLY]
