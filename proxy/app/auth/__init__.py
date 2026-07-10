# proxy/app/auth/__init__.py
"""Authentication and authorization — JWT, RBAC, user store, LDAP."""

from proxy.app.auth.jwt import (
    AuthMiddleware,
    UserContext,
    create_token,
    get_auth_context,
    get_optional_auth_context,
    verify_token,
)
from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.config import AUTH_ENABLED

__all__ = [
    "AUTH_ENABLED",
    "AuthMiddleware",
    "UserContext",
    "Role",
    "create_token",
    "get_auth_context",
    "get_optional_auth_context",
    "require_role",
    "verify_token",
]
