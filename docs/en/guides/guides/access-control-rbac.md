# Access Control & RBAC Design

This document defines the access control model for the RAG proxy — from data classification
through Qdrant-level filtering to role-based context trimming.

---

## 1. Data Classification Levels

Every document and chunk inherits a classification label:

| Level        | Description                          | Source Examples                  |
|--------------|--------------------------------------|----------------------------------|
| **Public**   | Accessible to all authenticated users | Shared docs, public READMEs     |
| **Internal** | All employees                         | Team wikis, Jira tasks          |
| **Confidential** | Restricted teams/groups           | Architecture docs, HR tickets   |
| **Restricted** | Named individuals only             | Security incidents, CEO reports |

Classification is assigned at extraction time from source permissions:

- **Confluence** — space-level permissions mapped to `access_level`
- **Jira** — project roles (Administrators, Developers, Viewers)
- **GitLab** — group/project membership → `allowed_groups` array

The label is stored in Qdrant payload as:

```json
{
  "access_level": "confidential",
  "allowed_groups": ["engineering", "security"],
  "allowed_users": ["alice", "bob"]
}
```

---

## 2. User Identity and Authentication

The proxy integrates with corporate SSO via **Keycloak** (air-gapped, Dockerized). Users
authenticate through OIDC and receive a **JWT** containing:

```json
{
  "sub": "user-uuid",
  "preferred_username": "alice",
  "groups": ["engineering", "platform"],
  "realm_access": {"roles": ["developer"]},
  "access_level": "confidential"
}
```

### auth.py — JWT Validation Module

```python
# proxy/app/auth.py
import jwt
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List

security = HTTPBearer(auto_error=False)

class AuthContext:
    def __init__(self, payload: dict):
        self.user_id: str = payload["sub"]
        self.username: str = payload.get("preferred_username", "")
        self.groups: List[str] = payload.get("groups", [])
        self.roles: List[str] = payload.get("realm_access", {}).get("roles", [])
        self.access_level: str = payload.get("access_level", "internal")

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_expert(self) -> bool:
        return "expert" in self.roles or self.is_admin


async def get_auth_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> AuthContext:
    """Extract AuthContext from JWT or return anonymous context in no-auth mode."""
    AUTH_ENABLED = request.app.state.config.get("auth_enabled", False)

    if not AUTH_ENABLED:
        return AuthContext({
            "sub": "anonymous",
            "groups": ["everyone"],
            "realm_access": {"roles": ["developer"]},
            "access_level": "public"
        })

    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    try:
        payload = jwt.decode(
            credentials.credentials,
            key=request.app.state.config["jwt_public_key"],
            algorithms=["RS256"],
            options={"verify_exp": True}
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    return AuthContext(payload)
```

---

## 3. Row-Level Security in Qdrant

Access control is enforced at the vector DB level via payload filters pushed down to Qdrant
at query time. This avoids leaking restricted documents out of the database entirely.

### access_control.py — Retrieval Filtering

```python
# proxy/app/access_control.py
from typing import List, Dict, Any, Optional
from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue, Range
from proxy.app.auth import AuthContext

def build_access_filter(auth: AuthContext) -> Optional[Filter]:
    """Build a Qdrant payload filter for the current user."""
    conditions = []

    # Admins and experts see everything
    if auth.is_admin or auth.is_expert:
        return None

    # Build allowed access_levels: public + internal always visible
    allowed_levels = ["public", "internal"]

    # Add confidential if user is in any group
    if auth.groups:
        allowed_levels.append("confidential")

    conditions.append(FieldCondition(
        key="access_level",
        match=MatchAny(any=allowed_levels)
    ))

    # For restricted content, check allowed_users
    if auth.username:
        conditions.append(FieldCondition(
            key="allowed_users",
            match=MatchValue(value=auth.username)
        ))

    # Group-based filtering
    if auth.groups:
        conditions.append(FieldCondition(
            key="allowed_groups",
            match=MatchAny(any=auth.groups)
        ))

    # At least one condition must be satisfied (OR logic across allowed_users,
    # allowed_groups for restricted content, AND with access_level)
    return Filter(
        should=[
            Filter(
                must=[
                    FieldCondition(key="access_level", match=MatchAny(any=["public", "internal"])),
                ]
            ),
            Filter(
                must=[
                    FieldCondition(key="access_level", match=MatchValue(value="confidential")),
                    FieldCondition(key="allowed_groups", match=MatchAny(any=auth.groups)),
                ]
            ),
            Filter(
                must=[
                    FieldCondition(key="access_level", match=MatchValue(value="restricted")),
                    FieldCondition(key="allowed_users", match=MatchValue(value=auth.username)),
                ]
            ),
        ]
    )


def trim_restricted_context(
    chunks: List[Dict[str, Any]],
    auth: AuthContext
) -> List[Dict[str, Any]]:
    """Post-retrieval context trimming: strip chunks the user shouldn't see."""
    access_filter = build_access_filter(auth)
    if access_filter is None:
        return chunks

    filtered = []
    for chunk in chunks:
        level = chunk.get("payload", {}).get("access_level", "public")
        if level in ("public", "internal"):
            filtered.append(chunk)
        elif level == "confidential" and _user_in_allowed_groups(chunk, auth):
            filtered.append(chunk)
        elif level == "restricted" and _user_is_allowed(chunk, auth):
            filtered.append(chunk)
    return filtered
```

---

## 4. RBAC Model

| Role       | Public | Internal | Confidential | Restricted | Expert Dashboard | Admin Panel |
|------------|--------|----------|--------------|------------|------------------|-------------|
| **Admin**  | Full   | Full     | Full         | Full       | Yes              | Yes         |
| **Expert** | Full   | Full     | By group     | No         | Yes              | No          |
| **Developer** | Full | Full    | By group     | No         | Read-only        | No          |
| **Viewer** | Full   | Full     | No           | No         | No               | No          |
| **External** | Full | No       | No           | No         | No               | No          |

Role-based context trimming removes restricted passages from LLM context before generation:

```python
# In orchestrator.py, before assembling the prompt:
visible_chunks = trim_restricted_context(retrieved_chunks, auth)
context = build_context(visible_chunks)
```

---

## 5. Implementation Changes Needed

| Module                   | Change                                                    |
|--------------------------|-----------------------------------------------------------|
| `proxy/app/auth.py`      | New — JWT validation, AuthContext extraction               |
| `proxy/app/access_control.py` | New — build_access_filter(), trim_restricted_context() |
| `etl/extractors/*.py`    | Add access metadata to each document                      |
| `etl/chunker/semantic_chunker.py` | Propagate access tags to chunks                |
| `etl/indexer/qdrant_hybrid.py` | Store access_level, allowed_groups, allowed_users in payload |
| `proxy/app/config.py`    | Add `auth_enabled`, `jwt_public_key`, `oidc_issuer`       |
| `proxy/app/orchestrator.py` | Integrate access_filter in retrieval pipeline         |
| `scripts/`               | Add `init_keycloak.sh` for bootstrap                     |

---

## 6. Air-Gapped Considerations

- **Keycloak** runs as a Docker service in `docker-compose.yml`; no external IdP dependency.
- **JWT public keys** are loaded from a mounted volume (`/secrets/jwt_public.pem`).
- **Token validation** uses offline RS256 verification — no calls to the IdP at query time.
- **User/group sync** happens via a scheduled internal script that queries the corporate LDAP
  and pushes updates to Keycloak's admin API, offline between sync runs.

---

## 7. Gradual Rollout Strategy

| Phase | Scope                  | Auth Mode         | Filtering Level            |
|-------|------------------------|-------------------|----------------------------|
| 1     | Current state          | None              | No filtering               |
| 2     | Source-level           | JWT + Keycloak    | Block entire sources       |
| 3     | Document-level         | JWT + Keycloak    | Payload filter per doc     |
| 4     | Chunk-level + trimming | JWT + Keycloak    | Qdrant filter + post-trim  |

Each phase is gated by `auth_enabled` and `filtering_level` config flags, allowing teams to
adopt access control incrementally without disrupting existing workflows.
