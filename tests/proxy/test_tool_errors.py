"""Tests for proxy/app/tools/errors.py — Tool error taxonomy."""

from proxy.app.shared.exceptions import RAGError
from proxy.app.tools.errors import (
    ToolDependencyError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRateLimitError,
    ToolTimeoutError,
    ToolValidationError,
    classify_error,
)


class TestToolErrors:
    def test_tool_error_defaults(self):
        err = ToolError("my_tool")
        assert err.tool_name == "my_tool"
        assert err.tool_call_id == ""
        assert err.retryable is False
        assert err.component == "tools"
        assert isinstance(err, RAGError)

    def test_tool_error_custom_message(self):
        err = ToolError("my_tool", message="custom msg", retryable=True)
        assert str(err) == "custom msg"
        assert err.retryable is True

    def test_tool_not_found_error(self):
        err = ToolNotFoundError("missing_tool")
        assert err.tool_name == "missing_tool"
        assert err.retryable is False
        assert "not found" in str(err)

    def test_tool_execution_error(self):
        orig = ValueError("bad input")
        err = ToolExecutionError("calc", original_error=orig)
        assert err.tool_name == "calc"
        assert err.retryable is True
        assert err.original_error is orig

    def test_tool_timeout_error(self):
        err = ToolTimeoutError("slow_tool", timeout_seconds=10.0)
        assert err.tool_name == "slow_tool"
        assert err.retryable is True
        assert err.timeout_seconds == 10.0
        assert "timed out" in str(err)

    def test_tool_permission_error(self):
        err = ToolPermissionError("admin_tool", required_visibility="admin", user_role="user")
        assert err.tool_name == "admin_tool"
        assert err.retryable is False
        assert err.required_visibility == "admin"
        assert err.user_role == "user"

    def test_tool_validation_error(self):
        err = ToolValidationError("input_tool", validation_errors=["field required"])
        assert err.tool_name == "input_tool"
        assert err.retryable is False
        assert err.validation_errors == ["field required"]

    def test_tool_validation_error_default_list(self):
        err = ToolValidationError("input_tool")
        assert err.validation_errors == []

    def test_tool_rate_limit_error(self):
        err = ToolRateLimitError("api", retry_after_seconds=30.0)
        assert err.tool_name == "api"
        assert err.retryable is True
        assert err.retry_after_seconds == 30.0

    def test_tool_dependency_error(self):
        err = ToolDependencyError("chain", dependency_name="dep1")
        assert err.tool_name == "chain"
        assert err.retryable is False
        assert err.dependency_name == "dep1"


class TestClassifyError:
    def test_classify_timeout_error(self):
        result = classify_error("test", TimeoutError("timeout"))
        assert isinstance(result, ToolTimeoutError)
        assert result.tool_name == "test"

    def test_classify_value_error(self):
        result = classify_error("test", ValueError("bad"))
        assert isinstance(result, ToolValidationError)

    def test_classify_type_error(self):
        result = classify_error("test", TypeError("wrong type"))
        assert isinstance(result, ToolValidationError)

    def test_classify_key_error(self):
        result = classify_error("test", KeyError("missing"))
        assert isinstance(result, ToolValidationError)

    def test_classify_attribute_error(self):
        result = classify_error("test", AttributeError("no attr"))
        assert isinstance(result, ToolValidationError)

    def test_classify_permission_error(self):
        result = classify_error("test", PermissionError("denied"))
        assert isinstance(result, ToolPermissionError)

    def test_classify_unknown_error(self):
        result = classify_error("test", RuntimeError("something"))
        assert isinstance(result, ToolExecutionError)
        assert result.original_error is not None

    def test_classify_with_tool_call_id(self):
        result = classify_error("test", TimeoutError(), tool_call_id="call_123")
        assert result.tool_call_id == "call_123"
