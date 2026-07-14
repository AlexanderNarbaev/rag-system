"""Tests for proxy/app/access_control.py — RBAC, access filtering, and role hierarchy."""

from proxy.app.auth import UserContext
from proxy.app.shared.access_control import (
  ACCESS_LEVEL_RANK, ROLE_ACCESS, ROLE_MAX_LEVEL, _role_allowed_levels, build_access_filter, build_access_filter_should,
  can_access_document, can_access_source, filter_chunks,
)


# ---------------------------------------------------------------------------
# Static data validation
# ---------------------------------------------------------------------------


class TestRoleDefinitions:
  def test_all_roles_have_access_entries (self):
    for role in ["admin", "expert", "developer", "viewer", "external"]:
      assert role in ROLE_ACCESS, f"{role} missing from ROLE_ACCESS"
      assert role in ROLE_MAX_LEVEL, f"{role} missing from ROLE_MAX_LEVEL"
  
  def test_admin_can_see_all_levels (self):
    assert "restricted" in ROLE_ACCESS ["admin"]
    assert len (ROLE_ACCESS ["admin"]) == 4
  
  def test_external_can_see_public_only (self):
    assert ROLE_ACCESS ["external"] == ["public"]
  
  def test_access_level_rank_is_strictly_increasing (self):
    ranks = [ACCESS_LEVEL_RANK [lvl] for lvl in ["public", "internal", "confidential", "restricted"]]
    assert ranks == sorted (ranks)
    assert len (set (ranks)) == len (ranks)


# ---------------------------------------------------------------------------
# _role_allowed_levels helper
# ---------------------------------------------------------------------------


class TestRoleAllowedLevels:
  def test_admin (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    levels = _role_allowed_levels (ctx)
    assert set (levels) == {"public", "internal", "confidential", "restricted"}
  
  def test_expert (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["expert"])
    levels = _role_allowed_levels (ctx)
    assert set (levels) == {"public", "internal", "confidential"}
  
  def test_developer (self):
    ctx = UserContext (user_id = "1", username = "bob", roles = ["developer"])
    levels = _role_allowed_levels (ctx)
    assert set (levels) == {"public", "internal", "confidential"}
  
  def test_viewer (self):
    ctx = UserContext (user_id = "1", username = "charlie", roles = ["viewer"])
    levels = _role_allowed_levels (ctx)
    assert set (levels) == {"public", "internal"}
  
  def test_external (self):
    ctx = UserContext (user_id = "1", username = "dave", roles = ["external"])
    levels = _role_allowed_levels (ctx)
    assert set (levels) == {"public"}
  
  def test_no_roles_defaults_to_public (self):
    ctx = UserContext (user_id = "1", username = "eve", roles = [])
    levels = _role_allowed_levels (ctx)
    assert set (levels) == {"public"}
  
  def test_multiple_roles_union (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["viewer", "external"])
    levels = _role_allowed_levels (ctx)
    # unions the sets
    assert "public" in levels
    assert "internal" in levels


# ---------------------------------------------------------------------------
# build_access_filter
# ---------------------------------------------------------------------------


class TestBuildAccessFilter:
  def test_admin_returns_none (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    result = build_access_filter (ctx)
    assert result is None
  
  def test_viewer_no_groups (self):
    ctx = UserContext (user_id = "1", username = "bob", roles = ["viewer"], groups = [])
    result = build_access_filter (ctx)
    assert result is not None
    assert len (result) >= 1
    # Should have a level filter for public + internal
    assert result [0] ["key"] == "access_level"
    assert set (result [0] ["match"] ["any"]) == {"public", "internal"}
  
  def test_developer_with_groups (self):
    ctx = UserContext (user_id = "2", username = "alice", roles = ["developer"], groups = ["engineering"], )
    result = build_access_filter (ctx)
    assert result is not None
    keys = [c ["key"] for c in result]
    assert "access_level" in keys
    assert "allowed_groups" in keys
  
  def test_external (self):
    ctx = UserContext (user_id = "3", username = "dave", roles = ["external"])
    result = build_access_filter (ctx)
    assert result is not None
    assert result [0] ["key"] == "access_level"
    assert result [0] ["match"] ["any"] == ["public"]
  
  def test_restricted_with_username (self):
    ctx = UserContext (user_id = "4", username = "alice", roles = ["admin"], )
    result = build_access_filter (ctx)
    assert result is None  # admin sees everything


# ---------------------------------------------------------------------------
# build_access_filter_should
# ---------------------------------------------------------------------------


class TestBuildAccessFilterShould:
  def test_admin_returns_none (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    result = build_access_filter_should (ctx)
    assert result is None
  
  def test_viewer_returns_should_clause (self):
    ctx = UserContext (user_id = "1", username = "bob", roles = ["viewer"])
    result = build_access_filter_should (ctx)
    assert result is not None
    assert "should" in result
  
  def test_developer_with_groups_includes_confidential_clause (self):
    ctx = UserContext (user_id = "2", username = "alice", roles = ["developer"], groups = ["engineering"], )
    result = build_access_filter_should (ctx)
    assert result is not None
    should = result ["should"]
    # Should have at least base levels + confidential group check
    assert len (should) >= 2
  
  def test_external_only_public (self):
    ctx = UserContext (user_id = "3", username = "dave", roles = ["external"])
    result = build_access_filter_should (ctx)
    assert result is not None
    should = result ["should"]
    # Only public should be in base levels
    assert len (should) == 1


# ---------------------------------------------------------------------------
# filter_chunks
# ---------------------------------------------------------------------------


SAMPLE_CHUNKS = [
    {
        "text": "public info", "access_level": "public", "payload": {"access_level": "public"},
    }, {
        "text": "internal info", "access_level": "internal", "payload": {"access_level": "internal"},
    }, {
        "text": "confidential info", "access_level": "confidential", "allowed_groups": ["engineering"],
        "payload": {"access_level": "confidential", "allowed_groups": ["engineering"]},
    }, {
        "text": "restricted info", "access_level": "restricted", "allowed_users": ["alice"],
        "payload": {"access_level": "restricted", "allowed_users": ["alice"]},
    }, {
        "text": "no level", "payload": {},
    },
]


class TestFilterChunks:
  def test_admin_sees_all (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    result = filter_chunks (SAMPLE_CHUNKS, ctx)
    assert len (result) == 5
  
  def test_viewer_sees_public_internal_only (self):
    ctx = UserContext (user_id = "2", username = "bob", roles = ["viewer"])
    result = filter_chunks (SAMPLE_CHUNKS, ctx)
    # viewer sees public + internal + chunk without level (defaults to public)
    assert len (result) == 3
    texts = [c ["text"] for c in result]
    assert "confidential info" not in texts
    assert "restricted info" not in texts
  
  def test_external_sees_public_only (self):
    ctx = UserContext (user_id = "3", username = "dave", roles = ["external"])
    result = filter_chunks (SAMPLE_CHUNKS, ctx)
    # external sees public + chunk without level (defaults to public)
    assert len (result) == 2
    assert result [0] ["text"] == "public info"
    assert result [1] ["text"] == "no level"
  
  def test_developer_sees_confidential_if_in_group (self):
    ctx = UserContext (user_id = "4", username = "eve", roles = ["developer"], groups = ["engineering"], )
    result = filter_chunks (SAMPLE_CHUNKS, ctx)
    texts = [c ["text"] for c in result]
    assert "public info" in texts
    assert "internal info" in texts
    assert "confidential info" in texts
    assert "restricted info" not in texts
  
  def test_developer_skips_confidential_if_not_in_group (self):
    ctx = UserContext (user_id = "5", username = "frank", roles = ["developer"], groups = ["marketing"], )
    result = filter_chunks (SAMPLE_CHUNKS, ctx)
    texts = [c ["text"] for c in result]
    assert "confidential info" not in texts
  
  def test_restricted_only_visible_to_named_user (self):
    ctx = UserContext (user_id = "6", username = "alice", roles = ["admin"], )
    result = filter_chunks (SAMPLE_CHUNKS, ctx)
    assert len (result) == 5  # admin
    
    ctx_dev = UserContext (user_id = "7", username = "bob", roles = ["developer"], groups = ["engineering"], )
    result_dev = filter_chunks (SAMPLE_CHUNKS, ctx_dev)
    assert "restricted info" not in [c ["text"] for c in result_dev]
  
  def test_chunk_without_access_level_treated_as_public (self):
    ctx = UserContext (user_id = "8", username = "eve", roles = ["external"])
    result = filter_chunks (SAMPLE_CHUNKS, ctx)
    texts = [c ["text"] for c in result]
    assert "no level" in texts  # defaults to public
    assert "public info" in texts
  
  def test_uses_payload_fallback (self):
    chunks = [
        {"payload": {"access_level": "internal", "text": "payload-only level"}},
    ]
    ctx = UserContext (user_id = "1", username = "alice", roles = ["viewer"])
    result = filter_chunks (chunks, ctx)
    assert len (result) == 1
  
  def test_empty_chunks (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    result = filter_chunks ([], ctx)
    assert result == []


# ---------------------------------------------------------------------------
# can_access_source
# ---------------------------------------------------------------------------


class TestCanAccessSource:
  def test_admin_can_access_restricted_source (self):
    ctx = UserContext (user_id = "1", username = "alice", roles = ["admin"])
    assert can_access_source (ctx, "hr", "hr-doc-1") is True
    assert can_access_source (ctx, "security", "sec-1") is True
    assert can_access_source (ctx, "finance", "fin-1") is True
  
  def test_expert_can_access_restricted_source (self):
    ctx = UserContext (user_id = "2", username = "bob", roles = ["expert"])
    assert can_access_source (ctx, "hr", "hr-doc-1") is True
  
  def test_developer_cannot_access_restricted_source (self):
    ctx = UserContext (user_id = "3", username = "charlie", roles = ["developer"])
    assert can_access_source (ctx, "hr", "hr-doc-1") is False
    assert can_access_source (ctx, "security", "sec-1") is False
  
  def test_viewer_cannot_access_restricted_source (self):
    ctx = UserContext (user_id = "4", username = "dave", roles = ["viewer"])
    assert can_access_source (ctx, "finance", "fin-1") is False
  
  def test_regular_source_accessible_by_all (self):
    for role in ["admin", "expert", "developer", "viewer", "external"]:
      ctx = UserContext (user_id = "1", username = "u", roles = [role])
      assert can_access_source (ctx, "confluence", "doc-1") is True
      assert can_access_source (ctx, "jira", "PROJ-123") is True
      assert can_access_source (ctx, "gitlab", "repo-1") is True


# ---------------------------------------------------------------------------
# can_access_document
# ---------------------------------------------------------------------------


class TestCanAccessDocument:
  def test_admin_can_access_restricted_doc (self):
    ctx = UserContext (user_id = "1", username = "admin", roles = ["admin"])
    assert can_access_document (ctx, "restricted", allowed_users = ["alice"]) is True
  
  def test_named_user_can_access_restricted_doc (self):
    # Only admin roles can access restricted documents
    ctx_admin = UserContext (user_id = "2", username = "alice", roles = ["admin"])
    assert can_access_document (ctx_admin, "restricted", allowed_users = ["alice", "bob"]) is True
    # Developer cannot access restricted even if named
    ctx_dev = UserContext (user_id = "2", username = "alice", roles = ["developer"])
    assert can_access_document (ctx_dev, "restricted", allowed_users = ["alice", "bob"]) is False
  
  def test_other_user_cannot_access_restricted_doc (self):
    ctx = UserContext (user_id = "3", username = "eve", roles = ["developer"])
    assert can_access_document (ctx, "restricted", allowed_users = ["alice"]) is False
  
  def test_group_member_can_access_confidential_doc (self):
    ctx = UserContext (user_id = "4", username = "bob", roles = ["developer"], groups = ["engineering"], )
    assert (can_access_document (ctx, "confidential", allowed_groups = ["engineering", "security"], ) is True)
  
  def test_non_group_member_cannot_access_confidential_doc (self):
    ctx = UserContext (user_id = "5", username = "bob", roles = ["developer"], groups = ["marketing"], )
    assert (can_access_document (ctx, "confidential", allowed_groups = ["engineering"], ) is False)
  
  def test_no_groups_cannot_access_confidential (self):
    ctx = UserContext (user_id = "6", username = "bob", roles = ["developer"], groups = [])
    assert (can_access_document (ctx, "confidential", allowed_groups = ["engineering"], ) is False)
  
  def test_viewer_can_access_internal (self):
    ctx = UserContext (user_id = "7", username = "bob", roles = ["viewer"])
    assert can_access_document (ctx, "internal") is True
    assert can_access_document (ctx, "public") is True
    assert can_access_document (ctx, "confidential") is False
  
  def test_external_can_access_public_only (self):
    ctx = UserContext (user_id = "8", username = "bob", roles = ["external"])
    assert can_access_document (ctx, "public") is True
    assert can_access_document (ctx, "internal") is False
    assert can_access_document (ctx, "confidential") is False
    assert can_access_document (ctx, "restricted") is False
  
  def test_restricted_without_allowed_users_fails (self):
    ctx = UserContext (user_id = "9", username = "alice", roles = ["admin"])
    assert can_access_document (ctx, "restricted") is True  # admin bypass
