# tests/proxy/tools/test_errors.py
"""Tests for tool error taxonomy — Task 2 TDD."""

from proxy.app.tools.errors import (
  ToolDependencyError, ToolError, ToolExecutionError, ToolNotFoundError, ToolPermissionError, ToolRateLimitError,
  ToolTimeoutError, ToolValidationError, classify_error,
)


class TestToolErrorBase:
  def test_tool_error_inherits_from_ragerror (self):
    from proxy.app.shared.exceptions import RAGError
    
    err = ToolError (tool_name = "test_tool", tool_call_id = "call_1", retryable = False, message = "test error", )
    assert isinstance (err, RAGError)
  
  def test_tool_error_attributes (self):
    err = ToolError (tool_name = "test_tool", tool_call_id = "call_1", retryable = False, message = "test error", )
    assert err.tool_name == "test_tool"
    assert err.tool_call_id == "call_1"
    assert err.retryable is False
    assert err.component == "tools"
    assert str (err) == "test error"


class TestToolNotFoundError:
  def test_not_retryable (self):
    err = ToolNotFoundError (tool_name = "missing_tool", tool_call_id = "call_1", )
    assert err.retryable is False
    assert err.tool_name == "missing_tool"


class TestToolExecutionError:
  def test_retryable_with_original_error (self):
    original = RuntimeError ("something broke")
    err = ToolExecutionError (tool_name = "exec_tool", tool_call_id = "call_2", original_error = original, )
    assert err.retryable is True
    assert err.original_error is original


class TestToolTimeoutError:
  def test_retryable_with_timeout_seconds (self):
    err = ToolTimeoutError (tool_name = "slow_tool", tool_call_id = "call_3", timeout_seconds = 30.0, )
    assert err.retryable is True
    assert err.timeout_seconds == 30.0


class TestToolPermissionError:
  def test_not_retryable_with_visibility_and_role (self):
    err = ToolPermissionError (tool_name = "admin_tool", tool_call_id = "call_4", required_visibility = "admin",
        user_role = "user", )
    assert err.retryable is False
    assert err.required_visibility == "admin"
    assert err.user_role == "user"


class TestToolValidationError:
  def test_not_retryable_with_validation_errors (self):
    err = ToolValidationError (tool_name = "validate_tool", tool_call_id = "call_5",
        validation_errors = ["field 'x' is required", "field 'y' must be int"], )
    assert err.retryable is False
    assert err.validation_errors == ["field 'x' is required", "field 'y' must be int"]
  
  def test_default_validation_errors_is_empty (self):
    err = ToolValidationError (tool_name = "validate_tool", tool_call_id = "call_5", )
    assert err.validation_errors == []


class TestToolRateLimitError:
  def test_retryable_with_retry_after (self):
    err = ToolRateLimitError (tool_name = "rate_limited_tool", tool_call_id = "call_6", retry_after_seconds = 60.0, )
    assert err.retryable is True
    assert err.retry_after_seconds == 60.0


class TestToolDependencyError:
  def test_not_retryable_with_dependency_name (self):
    err = ToolDependencyError (tool_name = "dependent_tool", tool_call_id = "call_7", dependency_name = "search_docs", )
    assert err.retryable is False
    assert err.dependency_name == "search_docs"


class TestClassifyError:
  def test_asyncio_timeout_maps_to_timeout (self):
    err = classify_error (tool_name = "test", error = TimeoutError ("timed out"), tool_call_id = "call_8", )
    assert isinstance (err, ToolTimeoutError)
    assert err.tool_name == "test"
    assert err.tool_call_id == "call_8"
  
  def test_value_error_maps_to_validation (self):
    err = classify_error (tool_name = "test", error = ValueError ("bad value"), tool_call_id = "call_9", )
    assert isinstance (err, ToolValidationError)
    assert err.retryable is False
  
  def test_type_error_maps_to_validation (self):
    err = classify_error (tool_name = "test", error = TypeError ("bad type"), tool_call_id = "call_10", )
    assert isinstance (err, ToolValidationError)
  
  def test_key_error_maps_to_validation (self):
    err = classify_error (tool_name = "test", error = KeyError ("missing_key"), tool_call_id = "call_11", )
    assert isinstance (err, ToolValidationError)
  
  def test_attribute_error_maps_to_validation (self):
    err = classify_error (tool_name = "test", error = AttributeError ("no attr"), tool_call_id = "call_12", )
    assert isinstance (err, ToolValidationError)
  
  def test_permission_error_maps_to_permission (self):
    err = classify_error (tool_name = "test", error = PermissionError ("denied"), tool_call_id = "call_13", )
    assert isinstance (err, ToolPermissionError)
  
  def test_generic_exception_maps_to_execution (self):
    err = classify_error (tool_name = "test", error = RuntimeError ("generic error"), tool_call_id = "call_14", )
    assert isinstance (err, ToolExecutionError)
    assert err.retryable is True
