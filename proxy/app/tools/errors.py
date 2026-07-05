# proxy/app/tools/errors.py
"""Tool error taxonomy — precise classification for agentic tool execution.

Each error carries tool_name, tool_call_id, and retryable so the
orchestrator can decide whether to retry, report, or escalate.
"""

from __future__ import annotations

from proxy.app.exceptions import RAGError


class ToolError(RAGError):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str = "",
        retryable: bool = False,
        message: str = "",
    ):
        super().__init__(
            message=message or f"Error in tool '{tool_name}'",
            component="tools",
            recoverable=retryable,
        )
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self.retryable = retryable


class ToolNotFoundError(ToolError):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str = "",
        message: str = "",
    ):
        super().__init__(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            retryable=False,
            message=message or f"Tool '{tool_name}' not found",
        )


class ToolExecutionError(ToolError):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str = "",
        original_error: Exception | None = None,
        message: str = "",
    ):
        super().__init__(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            retryable=True,
            message=message or f"Tool '{tool_name}' execution failed"
            + (f": {original_error}" if original_error else ""),
        )
        self.original_error = original_error


class ToolTimeoutError(ToolError):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str = "",
        timeout_seconds: float = 0.0,
        message: str = "",
    ):
        super().__init__(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            retryable=True,
            message=message or f"Tool '{tool_name}' timed out after {timeout_seconds}s",
        )
        self.timeout_seconds = timeout_seconds


class ToolPermissionError(ToolError):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str = "",
        required_visibility: str = "",
        user_role: str = "",
        message: str = "",
    ):
        super().__init__(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            retryable=False,
            message=message
            or f"Insufficient permissions for tool '{tool_name}'"
            f" (required: {required_visibility}, current: {user_role})",
        )
        self.required_visibility = required_visibility
        self.user_role = user_role


class ToolValidationError(ToolError):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str = "",
        validation_errors: list[str] | None = None,
        message: str = "",
    ):
        super().__init__(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            retryable=False,
            message=message or f"Validation failed for tool '{tool_name}'",
        )
        self.validation_errors = validation_errors if validation_errors is not None else []


class ToolRateLimitError(ToolError):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str = "",
        retry_after_seconds: float = 0.0,
        message: str = "",
    ):
        super().__init__(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            retryable=True,
            message=message
            or f"Rate limit exceeded for tool '{tool_name}'"
            f" (retry after {retry_after_seconds}s)",
        )
        self.retry_after_seconds = retry_after_seconds


class ToolDependencyError(ToolError):
    def __init__(
        self,
        tool_name: str,
        tool_call_id: str = "",
        dependency_name: str = "",
        message: str = "",
    ):
        super().__init__(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            retryable=False,
            message=message
            or f"Dependency '{dependency_name}' failed for tool '{tool_name}'",
        )
        self.dependency_name = dependency_name


def classify_error(
    tool_name: str,
    error: Exception,
    tool_call_id: str = "",
) -> ToolError:
    if isinstance(error, TimeoutError):
        return ToolTimeoutError(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            message=str(error),
        )
    if isinstance(error, (ValueError, TypeError, KeyError, AttributeError)):
        return ToolValidationError(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            validation_errors=[str(error)],
        )
    if isinstance(error, PermissionError):
        return ToolPermissionError(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            message=str(error),
        )
    return ToolExecutionError(
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        original_error=error,
        message=str(error),
    )
