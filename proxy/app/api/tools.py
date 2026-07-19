# proxy/app/api/tools.py
"""Tool discovery endpoints — list and inspect registered tools."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from proxy.app.auth import UserContext, get_optional_auth_context

logger = logging.getLogger("rag-proxy")

router = APIRouter(tags=["tools"])


def _highest_role_from_user(user: UserContext) -> str | None:
    """Map a UserContext to the highest visibility role string for tool filtering.

    Returns 'admin', 'expert', 'user', or None (public only).
    """
    roles_lower = {r.lower() for r in user.roles}
    for role in ("admin", "expert", "user"):
        if role in roles_lower:
            return role
    return None


@router.get("/v1/tools")
async def list_tools(
    category: str | None = None,
    tag: str | None = None,
    provider: str | None = None,
    user: UserContext = Depends(get_optional_auth_context),  # noqa: B008
) -> dict[str, Any]:
    """List available tools with optional filters. RBAC: visibility-filtered by user role."""
    # Deferred import — tests mock at proxy.app.main.get_enhanced_registry
    import proxy.app.main as _main

    registry = _main.get_enhanced_registry()  # type: ignore[attr-defined]
    user_role = _main._highest_role_from_user(user)  # type: ignore[attr-defined]
    tags = [tag] if tag else None
    tools = registry.list_tools(
        category=category,
        tags=tags,
        provider=provider,
        visibility_filter=user_role or "read_only",
    )
    return {
        "count": len(tools),
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "tags": t.tags,
                "version": t.version,
                "parameters": t.to_json_schema(),
                "provider": t.provider,
            }
            for t in tools
        ],
    }


@router.get("/v1/tools/{name}")
async def get_tool(
    name: str,
    user: UserContext = Depends(get_optional_auth_context),  # noqa: B008
) -> dict[str, Any]:
    """Get a single tool's details by name. Never exposes handler code."""
    import proxy.app.main as _main

    registry = _main.get_enhanced_registry()  # type: ignore[attr-defined]
    tool = registry.get_tool(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")
    user_role = _main._highest_role_from_user(user)  # type: ignore[attr-defined]
    visible = registry.list_tools(visibility_filter=user_role or "read_only")
    if tool not in visible:
        raise HTTPException(status_code=403, detail="Tool not visible to your role")
    return {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "tags": tool.tags,
        "version": tool.version,
        "visibility": tool.visibility.value,
        "timeout_seconds": tool.timeout_seconds,
        "parameters": tool.to_json_schema(),
        "provider": tool.provider,
        "depends_on": tool.depends_on,
    }
