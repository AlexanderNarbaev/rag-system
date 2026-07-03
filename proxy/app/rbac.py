"""Role-Based Access Control for RAG proxy.

Defines roles and permissions, enforces endpoint access based on user role.
Roles (hierarchical, higher inherits lower):
    ADMIN     → all endpoints
    EXPERT    → chat + feedback
    USER      → chat only
    READ_ONLY → models list + health
"""

import os
from enum import Enum

from fastapi import Depends, HTTPException

from app.auth import UserContext, get_auth_context

RBAC_ENABLED = os.getenv("RBAC_ENABLED", "false").lower() == "true"


class Role(str, Enum):
    ADMIN = "admin"
    EXPERT = "expert"
    USER = "user"
    READ_ONLY = "read_only"


ROLE_RANK = {Role.ADMIN: 4, Role.EXPERT: 3, Role.USER: 2, Role.READ_ONLY: 1}

_PERMISSION_MAP: dict[str, Role] = {
    "admin:config": Role.ADMIN,
    "admin:users": Role.ADMIN,
    "admin:stats": Role.ADMIN,
    "admin:metrics": Role.ADMIN,
    "admin:warmup": Role.ADMIN,
    "feedback": Role.EXPERT,
    "feedback:submit": Role.EXPERT,
    "feedback:review": Role.EXPERT,
    "enrichment:trigger": Role.EXPERT,
    "chat": Role.USER,
    "chat:stream": Role.USER,
    "widget:access": Role.USER,
    "models:list": Role.READ_ONLY,
    "health:check": Role.READ_ONLY,
    "auth:login": Role.READ_ONLY,
    "auth:refresh": Role.READ_ONLY,
    "auth:register": Role.READ_ONLY,
    "auth:logout": Role.READ_ONLY,
    "auth:me": Role.READ_ONLY,
}


def get_user_role(user: UserContext) -> Role:
    """Determine the highest role for a user from their claims.

    If user has multiple roles, returns the most privileged one.
    Anonymous or role-less users get READ_ONLY.
    """
    role_set = {role.lower() for role in user.roles}

    for role in (Role.ADMIN, Role.EXPERT, Role.USER, Role.READ_ONLY):
        if role.value in role_set:
            return role

    return Role.READ_ONLY


def has_permission(user: UserContext, action: str) -> bool:
    """Check if a user has permission to perform an action.

    Actions are strings like 'chat', 'feedback', 'admin:config'.
    Returns True if the user's highest role meets or exceeds the required role.
    """
    if not RBAC_ENABLED:
        return True

    required_role = _PERMISSION_MAP.get(action)
    if required_role is None:
        return False

    user_role = get_user_role(user)
    return ROLE_RANK.get(user_role, 0) >= ROLE_RANK.get(required_role, 0)


def require_role(required_role: Role):
    """FastAPI dependency factory — returns a dependency that checks the user's role.

    Usage:
        @app.post("/v1/feedback")
        async def feedback(user: UserContext = Depends(require_role(Role.EXPERT))):
            ...

    If the user's role is insufficient, raises 403 Forbidden.
    """

    async def _check_role(user: UserContext = Depends(get_auth_context)) -> UserContext:
        if not RBAC_ENABLED:
            return user

        user_role = get_user_role(user)
        if ROLE_RANK.get(user_role, 0) < ROLE_RANK.get(required_role, 0):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user_role.value}' is not sufficient. Required: '{required_role.value}'",
            )
        return user

    return _check_role
