"""Row-level security and access control for RAG queries.

Enforces data classification levels (public/internal/confidential/restricted)
based on user identity, roles, and group membership.

The module produces Qdrant payload filters that are pushed down to the
vector DB at query time, plus post-retrieval chunk filtering.

Classification levels:
    public        — accessible to all authenticated users
    internal      — all employees
    confidential  — restricted to teams/groups
    restricted    — named individuals only

Role hierarchy (higher roles inherit lower roles' access):
    admin      → public, internal, confidential, restricted (all)
    expert     → public, internal, confidential (by group), not restricted
    developer  → public, internal, confidential (by group)
    viewer     → public, internal
    external   → public only
"""

from typing import Any

from proxy.app.auth.jwt import UserContext

# ---------------------------------------------------------------------------
# Access level and role definitions
# ---------------------------------------------------------------------------

ACCESS_LEVELS = ["public", "internal", "confidential", "restricted"]

ACCESS_LEVEL_RANK = {level: i for i, level in enumerate(ACCESS_LEVELS)}

ROLES = ["admin", "expert", "developer", "viewer", "external"]

# Each role is allowed to access documents at or below this rank
ROLE_MAX_LEVEL: dict[str, str] = {
    "admin": "restricted",
    "expert": "confidential",
    "developer": "confidential",
    "viewer": "internal",
    "external": "public",
}

# Role hierarchy: which access levels each role can see
ROLE_ACCESS: dict[str, list[str]] = {
    "admin": ["public", "internal", "confidential", "restricted"],
    "expert": ["public", "internal", "confidential"],
    "developer": ["public", "internal", "confidential"],
    "viewer": ["public", "internal"],
    "external": ["public"],
}


def _role_allowed_levels(user_context: UserContext) -> list[str]:
    """Return the list of access levels the user is allowed to see based on their roles."""
    allowed: set[str] = set()
    for role in user_context.roles:
        allowed.update(ROLE_ACCESS.get(role, []))
    if not allowed:
        allowed = {"public"}
    return sorted(allowed, key=lambda lvl: ACCESS_LEVEL_RANK.get(lvl, 0))


# ---------------------------------------------------------------------------
# Qdrant payload filter builders
# ---------------------------------------------------------------------------


def build_access_filter(user_context: UserContext) -> list[dict[str, Any]] | None:
    """Build a Qdrant-style payload filter for the given user context.

    Returns a list of Qdrant filter conditions that can be used with
    qdrant_client.search(..., query_filter=...).  Returns None when no
    filtering is required (admin/expert can see everything without groups).

    The filter logic:
    - public/internal: always visible
    - confidential: visible if user is in an allowed group
    - restricted: visible if user is in the allowed_users list

    When user has no groups, confidential documents are NOT visible
    (only the levels allowed by their role).
    """
    if user_context.is_admin:
        return None

    allowed_levels = _role_allowed_levels(user_context)

    conditions: list[dict[str, Any]] = []

    # Level-based filter
    conditions.append(
        {
            "key": "access_level",
            "match": {"any": allowed_levels},
        }
    )

    # For confidential documents, additionally check group membership
    if "confidential" in allowed_levels and user_context.groups:
        conditions.append(
            {
                "key": "allowed_groups",
                "match": {"any": user_context.groups},
            }
        )

    # For restricted documents, check user list
    if "restricted" in allowed_levels and user_context.username:
        conditions.append(
            {
                "key": "allowed_users",
                "match": {"value": user_context.username},
            }
        )

    return conditions


def build_access_filter_should(user_context: UserContext) -> dict[str, Any] | None:
    """Build a Qdrant 'should' filter — any condition can match.

    Returns None for admin (no filter) and for anonymous auth-disabled users.
    """
    if user_context.is_admin:
        return None

    allowed_levels = _role_allowed_levels(user_context)

    should_clauses: list[dict[str, Any]] = []

    # Public + Internal: matched by access_level alone
    base_levels = [lvl for lvl in allowed_levels if lvl in ("public", "internal")]
    if base_levels:
        should_clauses.append(
            {
                "key": "access_level",
                "match": {"any": base_levels},
            }
        )

    # Confidential: requires group match
    if "confidential" in allowed_levels and user_context.groups:
        should_clauses.append(
            {
                "must": [
                    {"key": "access_level", "match": {"value": "confidential"}},
                    {"key": "allowed_groups", "match": {"any": user_context.groups}},
                ]
            }
        )

    # Restricted: requires allowed_users match
    if "restricted" in allowed_levels and user_context.username:
        should_clauses.append(
            {
                "must": [
                    {"key": "access_level", "match": {"value": "restricted"}},
                    {"key": "allowed_users", "match": {"value": user_context.username}},
                ]
            }
        )

    if should_clauses:
        return {"should": should_clauses}
    return {"should": []}


# ---------------------------------------------------------------------------
# Chunk-level filtering (post-retrieval)
# ---------------------------------------------------------------------------


def filter_chunks(
    chunks: list[dict[str, Any]],
    user_context: UserContext,
) -> list[dict[str, Any]]:
    """Filter retrieved chunks based on user access level.

    Each chunk may have:
        access_level: str       — "public", "internal", "confidential", "restricted"
        allowed_groups: [str]   — groups allowed to see this chunk
        allowed_users: [str]    — users allowed to see this chunk

    Returns only the chunks the user is allowed to see.
    """
    if user_context.is_admin:
        return chunks

    allowed_levels = _role_allowed_levels(user_context)

    filtered: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_level = chunk.get("access_level", chunk.get("payload", {}).get("access_level", "public"))

        # If the chunk level is not in the user's allowed levels, skip
        if chunk_level not in allowed_levels:
            continue

        # For confidential: check group membership
        if chunk_level == "confidential":
            if not user_context.groups:
                continue
            allowed_groups = chunk.get(
                "allowed_groups",
                chunk.get("payload", {}).get("allowed_groups", []),
            )
            if allowed_groups and not any(g in user_context.groups for g in allowed_groups):
                continue

        # For restricted: check allowed users
        if chunk_level == "restricted":
            allowed_users = chunk.get(
                "allowed_users",
                chunk.get("payload", {}).get("allowed_users", []),
            )
            if allowed_users and user_context.username not in allowed_users:
                continue

        filtered.append(chunk)

    return filtered


def filter_chunks_list(
    chunks: list[dict[str, Any]],
    user_context: UserContext,
) -> list[dict[str, Any]]:
    """Alias for filter_chunks — filter list of raw chunk dicts."""
    return filter_chunks(chunks, user_context)


# ---------------------------------------------------------------------------
# Source-level access checks
# ---------------------------------------------------------------------------


# Access matrix: (role, access_level) -> boolean
# Source types that require special access.
RESTRICTED_SOURCES = {"hr", "security", "finance", "legal", "executive"}


def can_access_source(
    user_context: UserContext,
    source_type: str,
    source_id: str,
) -> bool:
    """Check whether the user can access a specific source.

    source_type and source_id are used to determine which access rules apply.
    Returns True if the user is allowed, False otherwise.
    """
    if user_context.is_admin:
        return True

    # Restricted sources require expert or admin role
    if source_type in RESTRICTED_SOURCES:  # noqa: SIM102
        if not user_context.is_expert:
            return False

    # Check role against access level
    user_max_level_rank = max(
        (ACCESS_LEVEL_RANK.get(ROLE_MAX_LEVEL.get(role, "public"), 0) for role in user_context.roles),
        default=0,
    )

    return user_max_level_rank >= 0


def can_access_document(
    user_context: UserContext,
    access_level: str,
    allowed_groups: list[str] | None = None,
    allowed_users: list[str] | None = None,
) -> bool:
    """Check if a user can access a specific document given its access metadata."""
    if user_context.is_admin:
        return True

    allowed_levels = _role_allowed_levels(user_context)

    if access_level not in allowed_levels:
        return False

    if access_level == "confidential" and allowed_groups:
        if not user_context.groups:
            return False
        if not any(g in user_context.groups for g in allowed_groups):
            return False

    if access_level == "restricted" and allowed_users:  # noqa: SIM102
        if user_context.username not in allowed_users:
            return False

    return True
