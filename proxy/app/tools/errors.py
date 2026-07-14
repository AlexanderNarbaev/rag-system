# proxy/app/tools/errors.py
"""Tool error taxonomy and classification.

Provides typed tool-specific errors extending RAGError for better
error handling, retry decisions, and structured logging.
"""

from __future__ import annotations

from proxy.app.shared.exceptions import RAGError


class ToolError (RAGError):
  """Base error for all tool-related failures."""
  
  def __init__ (
      self, tool_name: str, tool_call_id: str = "", retryable: bool = False, message: str = "", ):
    super ().__init__ (message or f"Error in tool '{tool_name}'", component = "tools")
    self.tool_name = tool_name
    self.tool_call_id = tool_call_id
    self.retryable = retryable


class ToolNotFoundError (ToolError):
  """Requested tool is not registered."""
  
  def __init__ (
      self, tool_name: str, tool_call_id: str = "", message: str = "", ):
    super ().__init__ (tool_name = tool_name, tool_call_id = tool_call_id, retryable = False,
        message = message or f"Tool '{tool_name}' not found", )


class ToolExecutionError (ToolError):
  """Tool execution raised an unhandled exception."""
  
  def __init__ (
      self, tool_name: str, tool_call_id: str = "", original_error: Exception | None = None, message: str = "", ):
    super ().__init__ (tool_name = tool_name, tool_call_id = tool_call_id, retryable = True,
        message = message or f"Tool '{tool_name}' execution failed", )
    self.original_error = original_error


class ToolTimeoutError (ToolError):
  """Tool execution timed out."""
  
  def __init__ (
      self, tool_name: str, tool_call_id: str = "", timeout_seconds: float = 30.0, message: str = "", ):
    super ().__init__ (tool_name = tool_name, tool_call_id = tool_call_id, retryable = True,
        message = message or f"Tool '{tool_name}' timed out after {timeout_seconds}s", )
    self.timeout_seconds = timeout_seconds


class ToolPermissionError (ToolError):
  """Caller lacks required visibility/role for the tool."""
  
  def __init__ (
      self, tool_name: str, tool_call_id: str = "", required_visibility: str = "", user_role: str = "",
      message: str = "", ):
    super ().__init__ (tool_name = tool_name, tool_call_id = tool_call_id, retryable = False,
        message = message or f"Permission denied for tool '{tool_name}' (requires {required_visibility}, "
                             f"user has {user_role})",
        # noqa: E501
    )
    self.required_visibility = required_visibility
    self.user_role = user_role


class ToolValidationError (ToolError):
  """Tool parameters failed validation."""
  
  def __init__ (
      self, tool_name: str, tool_call_id: str = "", validation_errors: list [str] | None = None, message: str = "", ):
    super ().__init__ (tool_name = tool_name, tool_call_id = tool_call_id, retryable = False,
        message = message or f"Validation failed for tool '{tool_name}'", )
    self.validation_errors = validation_errors if validation_errors is not None else []


class ToolRateLimitError (ToolError):
  """Tool rate limit exceeded."""
  
  def __init__ (
      self, tool_name: str, tool_call_id: str = "", retry_after_seconds: float = 60.0, message: str = "", ):
    super ().__init__ (tool_name = tool_name, tool_call_id = tool_call_id, retryable = True,
        message = message or f"Rate limit exceeded for tool '{tool_name}', retry after {retry_after_seconds}s", )
    self.retry_after_seconds = retry_after_seconds


class ToolDependencyError (ToolError):
  """A tool dependency is not satisfied."""
  
  def __init__ (
      self, tool_name: str, tool_call_id: str = "", dependency_name: str = "", message: str = "", ):
    super ().__init__ (tool_name = tool_name, tool_call_id = tool_call_id, retryable = False,
        message = message or f"Tool '{tool_name}' depends on unavailable tool '{dependency_name}'", )
    self.dependency_name = dependency_name


def classify_error (
    tool_name: str, error: Exception, tool_call_id: str = "", ) -> ToolError:
  """Map a Python exception to the most specific ToolError subtype."""
  _classify_map: dict [type [Exception], type [ToolError]] = {
      TimeoutError: ToolTimeoutError, ValueError: ToolValidationError, TypeError: ToolValidationError,
      KeyError: ToolValidationError, AttributeError: ToolValidationError, PermissionError: ToolPermissionError,
  }
  for exc_type, tool_err_type in _classify_map.items ():
    if isinstance (error, exc_type):
      if tool_err_type is ToolTimeoutError:
        return ToolTimeoutError (tool_name = tool_name, tool_call_id = tool_call_id)
      return tool_err_type (tool_name = tool_name, tool_call_id = tool_call_id)
  return ToolExecutionError (tool_name = tool_name, tool_call_id = tool_call_id, original_error = error, )
