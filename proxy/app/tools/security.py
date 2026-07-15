# proxy/app/tools/security.py
"""Tool security: role-based visibility filtering and input sanitization.

Provides:
- ToolVisibilityFilter: filter tools by user role against RBAC matrix.
  PUBLIC visible to all, USER to authenticated, EXPERT to expert+,
  ADMIN to admin only.
- ToolInputSanitizer: sanitize tool inputs by stripping dangerous
  characters and validating types against ToolParam schemas.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .definition import ToolDefinition, ToolParam, ToolVisibility
from .registry import EnhancedToolRegistry

logger = logging.getLogger (__name__)

# ---------------------------------------------------------------------------
# Invisible characters pattern
# ---------------------------------------------------------------------------

_CONTROL_CHARS_RE = re.compile (r"[\x00-\x08\x0a-\x1f]")


def _strip_control (string: str) -> str:
  return _CONTROL_CHARS_RE.sub ("", string)


# ---------------------------------------------------------------------------
# ToolVisibilityFilter
# ---------------------------------------------------------------------------


class ToolVisibilityFilter:
  """Filter tool definitions by user role against the RBAC visibility matrix.

  Visibility levels (least → most restricted):
    - PUBLIC:  visible to everyone including unauthenticated
    - USER:     visible to any authenticated user
    - EXPERT:   visible to expert+ roles (expert, admin)
    - ADMIN:    visible to admin only

  RBAC matrix:
    admin      → PUBLIC, USER, EXPERT, ADMIN
    expert     → PUBLIC, USER, EXPERT
    user       → PUBLIC, USER
    read_only  → PUBLIC
    None (anon) → PUBLIC
  """

  UNAUTHENTICATED: str = "anonymous"

  RBAC_MATRIX: dict [str, list [str]] = {
      "admin": ["public", "user", "expert", "admin"], "expert": ["public", "user", "expert"],
      "user": ["public", "user"], "read_only": ["public"], UNAUTHENTICATED: ["public"],
  }

  # ------------------------------------------------------------------
  # Public API
  # ------------------------------------------------------------------

  def check_visibility (
      self, visibility: ToolVisibility, *, role: str | None = None, ) -> bool:
    """Return True if ``visibility`` is allowed for the given role."""
    effective_role = role if role else self.UNAUTHENTICATED
    allowed = self.RBAC_MATRIX.get (effective_role, self.RBAC_MATRIX [self.UNAUTHENTICATED])
    return visibility.value in allowed

  def filter (
      self, registry: EnhancedToolRegistry, *, role: str | None = None, ) -> list [ToolDefinition]:
    """Return tools from *registry* that are visible to *role*."""
    return [tool for tool in registry.get_all () if self.check_visibility (tool.visibility, role = role)]

  def filter_by_name (
      self, registry: EnhancedToolRegistry, name: str, *, role: str | None = None, ) -> ToolDefinition | None:
    """Look up a specific tool by name, respecting role visibility."""
    tool = registry.get_tool (name)
    if tool is None:
      return None
    if not self.check_visibility (tool.visibility, role = role):
      return None
    return tool


# ---------------------------------------------------------------------------
# ToolInputSanitizer
# ---------------------------------------------------------------------------


class ToolInputSanitizer:
  """Sanitize and validate tool inputs against parameter schemas.

  Sanitization: strip null bytes and control characters from all
  string values (recursively through dicts and lists).

  Validation: check required params are present and value types
  match the declared ToolParam schema.
  """

  # ------------------------------------------------------------------
  # Sanitization
  # ------------------------------------------------------------------

  def sanitize (self, inputs: dict [str, Any] | None) -> dict [str, Any]:
    """Recursively strip dangerous chars from string values."""
    if inputs is None:
      return {}
    return self._sanitize_dict (inputs)

  def _sanitize_dict (self, data: dict [str, Any]) -> dict [str, Any]:
    result: dict [str, Any] = {}
    for key, value in data.items ():
      result [key] = self._sanitize_value (value)
    return result

  def _sanitize_value (self, value: Any) -> Any:
    if isinstance (value, str):
      return _strip_control (value)
    if isinstance (value, dict):
      return self._sanitize_dict (value)
    if isinstance (value, list):
      return [self._sanitize_value (item) for item in value]
    return value

  # ------------------------------------------------------------------
  # Validation
  # ------------------------------------------------------------------

  def validate (
      self, params: list [ToolParam], inputs: dict [str, Any], ) -> list [str]:
    """Validate *inputs* against a list of ToolParam schemas.

    Returns a list of error messages; empty list means valid.
    """
    errors: list [str] = []

    for param in params:
      value = inputs.get (param.name)

      if param.required and param.name not in inputs:
        errors.append (f"Missing required parameter '{param.name}'")
        continue

      if value is None:
        continue

      errors.extend (self._validate_type (param, value))

    return errors

  # ------------------------------------------------------------------
  # Type checking
  # ------------------------------------------------------------------

  def _validate_type (self, param: ToolParam, value: Any) -> list [str]:
    errors: list [str] = []

    param_type = param.type
    if isinstance (param_type, str):
      param_type = _resolve_string_type (param_type)

    if param_type is str:
      if not isinstance (value, str):
        errors.append (f"Parameter '{param.name}' must be of type str, got {type (value).__name__}")
      elif param.enum is not None and value not in param.enum:
        errors.append (f"Parameter '{param.name}' must be one of {param.enum}, got '{value}'")

    elif param_type is int:
      if isinstance (value, bool) or not isinstance (value, int):
        errors.append (f"Parameter '{param.name}' must be of type int, got {type (value).__name__}")

    elif param_type is float:
      if not isinstance (value, (int, float)) or isinstance (value, bool):
        errors.append (f"Parameter '{param.name}' must be of type float, got {type (value).__name__}")

    elif param_type is bool:
      if not isinstance (value, bool):
        errors.append (f"Parameter '{param.name}' must be of type bool, got {type (value).__name__}")

    elif param_type is list:
      if not isinstance (value, list):
        errors.append (f"Parameter '{param.name}' must be of type list/array, got {type (value).__name__}")
      elif param.items_type is not None:
        items_type = param.items_type
        if isinstance (items_type, str):
          items_type = _resolve_string_type (items_type)
        for i, item in enumerate (value):
          if items_type is str and not isinstance (item, str):
            errors.append (f"Parameter '{param.name}' items must be str, item[{i}] is {type (item).__name__}")
          elif items_type is int and (isinstance (item, bool) or not isinstance (item, int)):
            errors.append (f"Parameter '{param.name}' items must be int, item[{i}] is {type (item).__name__}")

    elif param_type is dict and not isinstance (value, dict):
      errors.append (f"Parameter '{param.name}' must be of type dict/object, got {type (value).__name__}")

    return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_string_type (name: str) -> type:
  return {
      "str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict,
  }.get (name, str)
