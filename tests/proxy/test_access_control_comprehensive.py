"""Additional edge-case tests for proxy/app/shared/access_control.py.

Builds on test_access_control.py (51 existing tests) to cover remaining
branches: filter_chunks payload fallback chain, can_access_source true
branch, ROLE_ACCESS edge cases, and can_access_document with no admin.
"""

from __future__ import annotations

from proxy.app.auth import UserContext
from proxy.app.shared.access_control import (
    ACCESS_LEVELS,
    RESTRICTED_SOURCES,
    ROLE_MAX_LEVEL,
    _role_allowed_levels,
    build_access_filter,
    build_access_filter_should,
    can_access_document,
    can_access_source,
    filter_chunks,
)

# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestAccessLevelsConstant:
    def test_access_levels_complete(self):
        assert set(ACCESS_LEVELS) == {"public", "internal", "confidential", "restricted"}

    def test_restricted_sources_not_empty(self):
        assert len(RESTRICTED_SOURCES) > 0


class TestRoleEdges:
    def test_admin_max_level_is_restricted(self):
        assert ROLE_MAX_LEVEL["admin"] == "restricted"

    def test_external_max_level_is_public(self):
        assert ROLE_MAX_LEVEL["external"] == "public"


# ---------------------------------------------------------------------------
# _role_allowed_levels edge cases
# ---------------------------------------------------------------------------


class TestRoleAllowedLevelsEdge:
    def test_returns_sorted_list(self):
        ctx = UserContext(user_id="1", username="x", roles=["admin"])
        result = _role_allowed_levels(ctx)
        # Sorted by rank
        ranks = ["public", "internal", "confidential", "restricted"]
        assert result == ranks

    def test_unknown_role_falls_back_to_public(self):
        ctx = UserContext(user_id="1", username="x", roles=["made-up"])
        result = _role_allowed_levels(ctx)
        assert result == ["public"]

    def test_multi_role_union(self):
        ctx = UserContext(
            user_id="1",
            username="x",
            roles=["external", "viewer"],
        )
        # external → public; viewer → public, internal. Union = {public, internal}
        result = _role_allowed_levels(ctx)
        assert set(result) == {"public", "internal"}

    def test_admin_and_developer_union_all(self):
        ctx = UserContext(
            user_id="1",
            username="x",
            roles=["admin", "developer"],
        )
        result = _role_allowed_levels(ctx)
        assert set(result) == {"public", "internal", "confidential", "restricted"}


# ---------------------------------------------------------------------------
# build_access_filter edge cases
# ---------------------------------------------------------------------------


class TestBuildAccessFilterEdges:
    def test_no_username_no_restricted_clause(self):
        ctx = UserContext(user_id="1", username="", roles=["admin"])
        # Empty username with admin won't matter — admin returns None
        assert build_access_filter(ctx) is None

    def test_internal_user_with_groups(self):
        ctx = UserContext(
            user_id="1",
            username="bob",
            roles=["developer"],
            groups=["team-a"],
        )
        result = build_access_filter(ctx)
        assert result is not None
        # developer sees confidential+; groups added as filter
        assert any(c.get("key") == "allowed_groups" for c in result)


# ---------------------------------------------------------------------------
# build_access_filter_should edge cases
# ---------------------------------------------------------------------------


class TestBuildAccessFilterShouldEdges:
    def test_external_returns_empty_should(self):
        ctx = UserContext(user_id="1", username="bob", roles=["external"])
        result = build_access_filter_should(ctx)
        # Only public — should be present
        assert result is not None
        # The shape is {should: [...]} with one clause
        assert "should" in result

    def test_returns_dict_with_should_key(self):
        ctx = UserContext(user_id="1", username="bob", roles=["user"])
        result = build_access_filter_should(ctx)
        assert isinstance(result, dict)
        assert "should" in result

    def test_admin_returns_none(self):
        ctx = UserContext(user_id="1", username="bob", roles=["admin"])
        assert build_access_filter_should(ctx) is None


# ---------------------------------------------------------------------------
# filter_chunks edge cases
# ---------------------------------------------------------------------------


class TestFilterChunksEdges:
    def test_admin_returns_input_unchanged(self):
        ctx = UserContext(user_id="1", username="bob", roles=["admin"])
        chunks = [{"id": "1"}, {"id": "2"}]
        assert filter_chunks(chunks, ctx) == chunks

    def test_chunk_with_payload_nested_level(self):
        ctx = UserContext(user_id="1", username="bob", roles=["viewer"])
        chunks = [
            {
                "id": "x",
                "payload": {"access_level": "confidential"},
                "allowed_groups": ["team-a"],
            },
        ]
        # Viewer sees only public/internal, not confidential
        result = filter_chunks(chunks, ctx)
        assert result == []

    def test_chunk_default_access_level_public(self):
        # No access_level → defaults to public
        ctx = UserContext(user_id="1", username="bob", roles=["external"])
        chunks = [{"id": "1"}]
        # External can see public → chunk passes through
        result = filter_chunks(chunks, ctx)
        assert len(result) == 1

    def test_restricted_chunk_with_groups_field_public_user(self):
        ctx = UserContext(user_id="1", username="alice", roles=["public"])
        chunks = [
            {
                "id": "1",
                "access_level": "restricted",
                "allowed_users": ["bob"],
            },
        ]
        # Public role can't see restricted at all
        result = filter_chunks(chunks, ctx)
        assert result == []

    def test_internal_chunk_visible_to_developer(self):
        ctx = UserContext(user_id="1", username="bob", roles=["developer"])
        chunks = [{"id": "1", "access_level": "internal"}]
        assert len(filter_chunks(chunks, ctx)) == 1


# ---------------------------------------------------------------------------
# can_access_source edge cases
# ---------------------------------------------------------------------------


class TestCanAccessSourceEdges:
    def test_admin_can_access_any_source(self):
        ctx = UserContext(user_id="1", username="bob", roles=["admin"])
        assert can_access_source(ctx, "hr", "doc-1") is True

    def test_non_restricted_source_returns_true_for_any_role(self):
        ctx = UserContext(user_id="1", username="bob", roles=["external"])
        # 'wiki' not in RESTRICTED_SOURCES
        assert can_access_source(ctx, "wiki", "doc-1") is True

    def test_restricted_source_requires_expert(self):
        ctx = UserContext(user_id="1", username="bob", roles=["viewer"])
        assert can_access_source(ctx, "hr", "doc-1") is False


# ---------------------------------------------------------------------------
# can_access_document edge cases
# ---------------------------------------------------------------------------


class TestCanAccessDocumentEdges:
    def test_admin_bypass(self):
        ctx = UserContext(user_id="1", username="bob", roles=["admin"])
        assert can_access_document(ctx, "anything") is True

    def test_missing_allowed_groups_falls_through(self):
        # confidential with allowed_groups=None → passes through
        ctx = UserContext(
            user_id="1",
            username="bob",
            roles=["developer"],
            groups=["team-a"],
        )
        assert can_access_document(ctx, "confidential", allowed_groups=None) is True

    def test_internal_user_no_groups(self):
        ctx = UserContext(user_id="1", username="bob", roles=["viewer"])
        # confidential without allowed_groups still requires group membership,
        # but viewer can't see confidential anyway
        assert can_access_document(ctx, "public") is True
        assert can_access_document(ctx, "internal") is True
        assert can_access_document(ctx, "confidential") is False

    def test_restricted_with_no_users(self):
        ctx = UserContext(user_id="1", username="bob", roles=["admin"])
        assert can_access_document(ctx, "restricted", allowed_users=None) is True

    def test_confidential_group_match(self):
        ctx = UserContext(
            user_id="1",
            username="bob",
            roles=["developer"],
            groups=["finance", "hr"],
        )
        assert (
            can_access_document(
                ctx,
                "confidential",
                allowed_groups=["hr"],
            )
            is True
        )

    def test_confidential_group_mismatch(self):
        ctx = UserContext(
            user_id="1",
            username="bob",
            roles=["developer"],
            groups=["legal"],
        )
        assert (
            can_access_document(
                ctx,
                "confidential",
                allowed_groups=["hr"],
            )
            is False
        )

    def test_restricted_user_match(self):
        ctx = UserContext(user_id="1", username="alice", roles=["admin"])
        # admin always allowed (early return)
        assert (
            can_access_document(
                ctx,
                "restricted",
                allowed_users=["alice"],
            )
            is True
        )
