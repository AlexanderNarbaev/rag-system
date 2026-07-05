"""Tests for proxy/app/tools/security.py — ToolVisibilityFilter, ToolInputSanitizer.

TDD for security: role-based visibility filtering, input sanitization, type validation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))

from tools.definition import (
    ToolDefinition,
    ToolParam,
    ToolVisibility,
)
from tools.registry import EnhancedToolRegistry


def _make_tool(name, description="Test tool", visibility=ToolVisibility.PUBLIC,
               parameters=None, category="general", tags=None, handler=None,
               provider="sdk"):
    if parameters is None:
        parameters = [ToolParam(name="query", type=str, description="Query")]
    if handler is None:
        def _default_handler(**kw):
            return f"Result: {kw}"
        handler = _default_handler
    return ToolDefinition(
        name=name, description=description, parameters=parameters,
        handler=handler, category=category, tags=tags or [],
        visibility=visibility, provider=provider,
    )


def _make_registry(tools=None):
    registry = EnhancedToolRegistry()
    for t in (tools or []):
        registry.register(t)
    return registry


# ---------------------------------------------------------------------------
# ToolVisibilityFilter
# ---------------------------------------------------------------------------

class TestToolVisibilityFilter:
    def test_rbac_matrix_maps_role_to_visible_levels(self):
        from tools.security import ToolVisibilityFilter

        # admin sees all
        assert "public" in ToolVisibilityFilter.RBAC_MATRIX["admin"]
        assert "user" in ToolVisibilityFilter.RBAC_MATRIX["admin"]
        assert "expert" in ToolVisibilityFilter.RBAC_MATRIX["admin"]
        assert "admin" in ToolVisibilityFilter.RBAC_MATRIX["admin"]

        # expert sees public+user+expert
        assert "public" in ToolVisibilityFilter.RBAC_MATRIX["expert"]
        assert "user" in ToolVisibilityFilter.RBAC_MATRIX["expert"]
        assert "expert" in ToolVisibilityFilter.RBAC_MATRIX["expert"]
        assert "admin" not in ToolVisibilityFilter.RBAC_MATRIX["expert"]

        # user sees public+user
        assert "public" in ToolVisibilityFilter.RBAC_MATRIX["user"]
        assert "user" in ToolVisibilityFilter.RBAC_MATRIX["user"]
        assert "expert" not in ToolVisibilityFilter.RBAC_MATRIX["user"]
        assert "admin" not in ToolVisibilityFilter.RBAC_MATRIX["user"]

        # read_only sees public only
        assert "public" in ToolVisibilityFilter.RBAC_MATRIX["read_only"]
        assert "user" not in ToolVisibilityFilter.RBAC_MATRIX["read_only"]
        assert "expert" not in ToolVisibilityFilter.RBAC_MATRIX["read_only"]
        assert "admin" not in ToolVisibilityFilter.RBAC_MATRIX["read_only"]

    def test_unauthenticated_user_is_supported(self):
        from tools.security import ToolVisibilityFilter

        assert ToolVisibilityFilter.UNAUTHENTICATED in ToolVisibilityFilter.RBAC_MATRIX
        assert ToolVisibilityFilter.RBAC_MATRIX[ToolVisibilityFilter.UNAUTHENTICATED] == ["public"]

    def test_public_tool_visible_to_all(self):
        from tools.security import ToolVisibilityFilter

        tools = [
            _make_tool("search", visibility=ToolVisibility.PUBLIC),
            _make_tool("health", visibility=ToolVisibility.PUBLIC),
        ]
        registry = _make_registry(tools)
        filter_obj = ToolVisibilityFilter()

        for role in ["admin", "expert", "user", "read_only", None]:
            visible = filter_obj.filter(registry, role=role)
            names = {t.name for t in visible}
            assert "search" in names
            assert "health" in names

    def test_admin_tool_only_visible_to_admin(self):
        from tools.security import ToolVisibilityFilter

        tools = [
            _make_tool("dangerous_action", visibility=ToolVisibility.ADMIN),
            _make_tool("search", visibility=ToolVisibility.PUBLIC),
        ]
        registry = _make_registry(tools)
        filter_obj = ToolVisibilityFilter()

        admin_visible = filter_obj.filter(registry, role="admin")
        assert "dangerous_action" in {t.name for t in admin_visible}
        assert "search" in {t.name for t in admin_visible}

        for role in ["expert", "user", "read_only", None]:
            visible = filter_obj.filter(registry, role=role)
            names = {t.name for t in visible}
            assert "search" in names
            assert "dangerous_action" not in names

    def test_expert_tool_visible_to_admin_and_expert(self):
        from tools.security import ToolVisibilityFilter

        tools = [
            _make_tool("review_tool", visibility=ToolVisibility.EXPERT),
        ]
        registry = _make_registry(tools)
        filter_obj = ToolVisibilityFilter()

        for role in ["admin", "expert"]:
            visible = filter_obj.filter(registry, role=role)
            assert "review_tool" in {t.name for t in visible}

        for role in ["user", "read_only", None]:
            visible = filter_obj.filter(registry, role=role)
            assert "review_tool" not in {t.name for t in visible}

    def test_user_tool_visible_to_authenticated(self):
        from tools.security import ToolVisibilityFilter

        tools = [
            _make_tool("profile", visibility=ToolVisibility.USER),
        ]
        registry = _make_registry(tools)
        filter_obj = ToolVisibilityFilter()

        for role in ["admin", "expert", "user"]:
            visible = filter_obj.filter(registry, role=role)
            assert "profile" in {t.name for t in visible}

        for role in ["read_only", None]:
            visible = filter_obj.filter(registry, role=role)
            assert "profile" not in {t.name for t in visible}

    def test_filter_by_name_single(self):
        from tools.security import ToolVisibilityFilter

        tools = [
            _make_tool("search", visibility=ToolVisibility.PUBLIC),
            _make_tool("health", visibility=ToolVisibility.PUBLIC),
            _make_tool("admin_task", visibility=ToolVisibility.ADMIN),
        ]
        registry = _make_registry(tools)
        filter_obj = ToolVisibilityFilter()

        filtered = filter_obj.filter_by_name(registry, "admin_task", role="admin")
        assert filtered is not None
        assert filtered.name == "admin_task"

    def test_filter_by_name_denied_role(self):
        from tools.security import ToolVisibilityFilter

        tools = [_make_tool("admin_task", visibility=ToolVisibility.ADMIN)]
        registry = _make_registry(tools)
        filter_obj = ToolVisibilityFilter()

        assert filter_obj.filter_by_name(registry, "admin_task", role="user") is None
        assert filter_obj.filter_by_name(registry, "admin_task", role=None) is None

    def test_filter_by_name_missing_tool(self):
        from tools.security import ToolVisibilityFilter

        filter_obj = ToolVisibilityFilter()
        registry = _make_registry([])
        assert filter_obj.filter_by_name(registry, "nonexistent", role="admin") is None

    def test_check_visibility_helper(self):
        from tools.security import ToolVisibilityFilter

        filter_obj = ToolVisibilityFilter()
        assert filter_obj.check_visibility(ToolVisibility.PUBLIC, role="admin") is True
        assert filter_obj.check_visibility(ToolVisibility.PUBLIC, role=None) is True
        assert filter_obj.check_visibility(ToolVisibility.ADMIN, role="admin") is True
        assert filter_obj.check_visibility(ToolVisibility.ADMIN, role="user") is False
        assert filter_obj.check_visibility(ToolVisibility.EXPERT, role="expert") is True
        assert filter_obj.check_visibility(ToolVisibility.EXPERT, role="user") is False


# ---------------------------------------------------------------------------
# ToolInputSanitizer
# ---------------------------------------------------------------------------

class TestToolInputSanitizer:
    def test_strips_null_bytes_and_control_chars(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        result = sanitizer.sanitize({"query": "hello\x00world", "text": "ctrl\r\nchars"})
        assert "\x00" not in result["query"]
        assert "\r" not in result["text"]
        assert "\n" not in result["text"]

    def test_handles_non_string_values(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        result = sanitizer.sanitize({"top_k": 5, "flag": True, "items": [1, 2, 3]})
        assert result["top_k"] == 5
        assert result["flag"] is True
        assert result["items"] == [1, 2, 3]

    def test_sanitize_empty_dict(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        assert sanitizer.sanitize({}) == {}

    def test_sanitize_none_input(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        assert sanitizer.sanitize(None) == {}

    def test_validate_against_schema_valid(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [
            ToolParam(name="query", type=str, required=True),
            ToolParam(name="top_k", type=int, required=False, default=5),
        ]
        errors = sanitizer.validate(params, {"query": "hello", "top_k": 10})
        assert errors == []

    def test_validate_against_schema_missing_required(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [
            ToolParam(name="query", type=str, required=True),
            ToolParam(name="top_k", type=int, required=True),
        ]
        errors = sanitizer.validate(params, {"query": "hello"})
        assert len(errors) >= 1
        assert any("top_k" in e for e in errors)

    def test_validate_against_schema_type_mismatch(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [ToolParam(name="top_k", type=int, required=True)]
        errors = sanitizer.validate(params, {"top_k": "not_an_int"})
        assert len(errors) >= 1
        assert any("top_k" in e for e in errors)

    def test_validate_against_schema_enum(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [
            ToolParam(name="sort", type=str, required=True, enum=["asc", "desc"]),
        ]
        assert sanitizer.validate(params, {"sort": "asc"}) == []
        errors = sanitizer.validate(params, {"sort": "invalid"})
        assert len(errors) >= 1

    def test_validate_against_schema_array_type(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [
            ToolParam(name="ids", type=list, required=True, items_type=str),
        ]
        assert sanitizer.validate(params, {"ids": ["a", "b", "c"]}) == []
        errors = sanitizer.validate(params, {"ids": [1, 2, 3]})
        assert len(errors) >= 1

    def test_sanitize_and_validate_combined(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [
            ToolParam(name="query", type=str, required=True),
            ToolParam(name="top_k", type=int, required=False, default=5),
        ]
        raw_input = {"query": "valid\x00query\n", "top_k": 10}
        sanitized = sanitizer.sanitize(raw_input)
        assert "\x00" not in sanitized["query"]
        errors = sanitizer.validate(params, sanitized)
        assert errors == []

    def test_validate_against_schema_missing_required_is_empty_errors(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [ToolParam(name="required_field", type=str, required=True)]
        errors = sanitizer.validate(params, {})
        assert len(errors) == 1
        assert "required_field" in errors[0]

    def test_validate_empty_params_always_passes(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        errors = sanitizer.validate([], {"anything": "goes"})
        assert errors == []

    def test_validate_optional_param_can_be_missing(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        params = [
            ToolParam(name="query", type=str, required=True),
            ToolParam(name="top_k", type=int, required=False),
        ]
        errors = sanitizer.validate(params, {"query": "hello"})
        assert errors == []

    def test_strips_dangerous_sql_patterns(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        result = sanitizer.sanitize({"name": "Robert'); DROP TABLE Students;--"})
        assert "DROP" in result["name"]  # keep the content but log it

    def test_handles_nested_dict(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        result = sanitizer.sanitize({"outer": {"inner": "val\x00ue"}})
        assert "\x00" not in result["outer"]["inner"]

    def test_handles_list_of_strings(self):
        from tools.security import ToolInputSanitizer

        sanitizer = ToolInputSanitizer()
        result = sanitizer.sanitize({"items": ["a\x00", "b\r\n", "c"]})
        assert "\x00" not in result["items"][0]
        assert "\r" not in result["items"][1]
        assert result["items"][2] == "c"
