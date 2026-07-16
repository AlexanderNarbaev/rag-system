# proxy/app/auth/__init__.py
"""Authentication and authorization — JWT, RBAC, user store, LDAP, API keys, secret rotation."""

from proxy.app.auth.api_keys import ApiKey, ApiKeyManager, api_key_manager
from proxy.app.auth.jwt import (
  AuthMiddleware,
  UserContext,
  create_token,
  get_auth_context,
  get_optional_auth_context,
  verify_token,
)
from proxy.app.auth.rbac import Role, require_role
from proxy.app.auth.secret_rotation import SecretRotationManager, get_rotation_manager
from proxy.app.shared.config import AUTH_ENABLED

__all__ = [
    "AUTH_ENABLED", "ApiKey", "ApiKeyManager", "AuthMiddleware", "SecretRotationManager",
    "UserContext", "Role", "api_key_manager", "create_token", "get_auth_context",
    "get_optional_auth_context", "get_rotation_manager", "require_role", "verify_token",
]
