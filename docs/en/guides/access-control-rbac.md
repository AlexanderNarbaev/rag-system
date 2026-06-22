# Access Control & RBAC — Definitive Security Reference

This document is the **authoritative security guide** for the RAG proxy. It covers every
security mechanism implemented in the system: authentication methods, token lifecycle,
RBAC permissions, data classification, input sanitization, and audit logging.

**Implementation Status:** ✅ Fully implemented. All features described below are present
in the running codebase. See `proxy/app/auth.py`, `proxy/app/rbac.py`, `proxy/app/user_db.py`,
`proxy/app/ldap_auth.py`, `proxy/app/sanitizer.py`, and `proxy/app/security.py`.

---

## Table of Contents

1. [Authentication Methods](#1-authentication-methods)
2. [Token Management](#2-token-management)
3. [RBAC Model](#3-rbac-model)
4. [Data Classification & Row-Level Security](#4-data-classification--row-level-security)
5. [Endpoint Security](#5-endpoint-security)
6. [Configuration Reference](#6-configuration-reference)
7. [Input Sanitization](#7-input-sanitization)
8. [Audit Logging](#8-audit-logging)
9. [Setup Guide](#9-setup-guide)
10. [Security Checklist](#10-security-checklist)

---

## 1. Authentication Methods

The proxy supports **five authentication methods**, all enabled or disabled via
environment variables. When `AUTH_ENABLED=false` (the default), every request
receives an anonymous context with `viewer` role and `public` access level.

### 1.1 JWT — Internal Token Auth (HS256 / RS256)

Default mode when `AUTH_ENABLED=true` and no external IdP is configured. The proxy
**issues and verifies its own JWT tokens**.

**Algorithm:** HS256 (default) or RS256 (when `JWT_PUBLIC_KEY` is set).

**Token creation example (internal):**

```python
from proxy.app.auth import create_token

token = create_token(
    user_id="usr-alice-001",
    username="alice",
    roles=["user"],
    groups=["engineering"],
    access_level="internal",
    namespace="engineering",
)
# Returns: "eyJhbGciOiJIUzI1NiIs..."
```

**Token payload structure:**

```json
{
  "sub": "usr-alice-001",
  "preferred_username": "alice",
  "roles": ["user"],
  "groups": ["engineering"],
  "access_level": "internal",
  "namespace": "engineering",
  "iat": 1719000000,
  "exp": 1719086400
}
```

**Token delivery:**

Tokens are accepted in two forms:
- `Authorization: Bearer <token>` (standard)
- `X-Auth-Token: <token>` (alternative, for clients that cannot set Bearer)

### 1.2 Keycloak OIDC (RS256)

When `KEYCLOAK_URL` is set, the proxy auto-discovers OIDC configuration and validates
RS256 tokens issued by Keycloak. No HS256 fallback — the proxy validates against
Keycloak's JWKS endpoint.

**How it works:**

1. The proxy fetches JWKS from `{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs`
2. JWKS is cached for 1 hour (`_JWKS_CACHE_TTL = 3600`)
3. Token validation uses the cached public key via `kid` matching
4. If Keycloak is unreachable, validation falls back to `JWT_PUBLIC_KEY` (air-gapped mode)

**Keycloak token payload (expected):**

```json
{
  "sub": "f47ac10b-58cc-4372-e567-0e02b2c3d479",
  "preferred_username": "alice",
  "realm_access": {"roles": ["user", "expert"]},
  "groups": ["engineering", "platform"],
  "access_level": "internal",
  "namespace": "engineering"
}
```

The proxy maps `realm_access.roles` → `UserContext.roles` automatically.

### 1.3 LDAP / Active Directory

When `AD_ENABLED=true`, the login endpoint attempts LDAP bind **before** falling back
to local SQLite authentication.

**Flow:**

1. Build user DN from `AD_USER_DN_TEMPLATE`: `cn={username},{base_dn}`
2. Attempt LDAP bind against `AD_URL` with the provided password
3. On success, check if the user exists in SQLite
4. If not found, **auto-create** a local user record (default role: `user`)
5. Return a JWT token pair for the local user

**Graceful degradation:** If `ldap3` is not installed or the LDAP server is unreachable,
the module logs a warning and passes through to local auth. No crash, no auth outage.

### 1.4 API Keys

API keys follow the format `rag_<random_base64>`. Generated via:

```python
from proxy.app.security import SecretsManager

api_key = SecretsManager.generate_api_key()
# Returns: "rag_Xk7mPq2VwN9aBtRcLfJh3YsDgEoKpMnQ"
```

API keys are included in the `Authorization: Bearer` header. Rate-limiting middleware
detects Bearer tokens and uses the key (rather than IP) for rate-limit buckets.

### 1.5 Self-Registration

The `/v1/auth/register` endpoint accepts `{username, password, email}` and creates a
new SQLite user with:
- `roles: ["user"]` (default)
- `access_level: "user"`
- Bcrypt-hashed password (12 rounds by default, configurable via `BCRYPT_ROUNDS`)

Registration is always available (even when `AUTH_ENABLED=false`). When auth is enabled,
only registration and login/refresh are public — all other endpoints require a valid token.

### 1.6 Auth Status Table

| `AUTH_ENABLED` | `KEYCLOAK_URL` set | `AD_ENABLED` | Behavior |
|---|---|---|---|
| `false` | — | — | Anonymous context, all endpoints open |
| `true` | No | No | HS256 JWT, SQLite login, self-registration |
| `true` | Yes | No | Keycloak RS256 validation + SQLite login fallback |
| `true` | Yes | Yes | LDAP bind → Keycloak RS256 → SQLite (chain) |
| `true` | No | Yes | LDAP bind → SQLite login fallback |

---

## 2. Token Management

### 2.1 Access & Refresh Token Pairs

The `/v1/auth/login` endpoint returns a token pair:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "dGhpcyBpcyBhbiBvcGFxdWUgcmFuZG9tIHN0cmluZw...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

| Property | Config Variable | Default | Description |
|---|---|---|---|
| Access token TTL | `ACCESS_TOKEN_MINUTES` | 60 min | How long the access token is valid |
| Refresh token TTL | `REFRESH_TOKEN_DAYS` | 7 days | How long refresh tokens persist in DB |
| Token hash rounds | `BCRYPT_ROUNDS` | 12 | Bcrypt cost factor for password hashing |

**Access tokens** are JWTs with:
- `type: "access"` claim
- `jti` (JWT ID) claim for blacklisting
- Short lifetime (60 min default)

**Refresh tokens** are opaque random strings (48 bytes, URL-safe base64). They are stored
in SQLite as SHA-256 hashes, never in plaintext.

### 2.2 Refresh Flow

```bash
# Step 1: Login to get tokens
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}'

# Response (capture refresh_token):
# {"access_token": "...", "refresh_token": "abc...", "token_type": "bearer", "expires_in": 3600}

# Step 2: Exchange refresh token for new pair
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "abc..."}'

# Response (new access + new refresh, old refresh consumed):
# {"access_token": "...", "refresh_token": "def...", "token_type": "bearer", "expires_in": 3600}
```

**One-time use:** Each refresh token is consumed (marked `revoked=1`) on use. A new
refresh token is issued with each refresh. This provides **refresh token rotation**.

### 2.3 Token Revocation & Blacklist

**Logout flow** (`/v1/auth/logout`):

1. Revokes all refresh tokens for the authenticated user
2. Adds the current access token's `jti` to the blacklist table
3. Blacklist has TTL-based auto-cleanup (entries expire when the token would have expired)

```bash
curl -X POST http://localhost:8080/v1/auth/logout \
  -H "Authorization: Bearer <access_token>"
```

**Blacklist capacity:** Default max 10,000 entries (`TOKEN_BLACKLIST_MAX_ENTRIES`).
Oldest entries are evicted when the limit is exceeded.

### 2.4 Token Storage Best Practices

**Client side:**

| Storage | Recommendation | Reason |
|---|---|---|
| `localStorage` | ❌ Avoid | Accessible to any XSS |
| `sessionStorage` | ⚠️ Acceptable | Cleared on tab close, still XSS-vulnerable |
| `httpOnly` cookie | ✅ Preferred | Not accessible to JavaScript |
| In-memory variable | ✅ Preferred | Cleared on page refresh, no persistence |
| `Authorization` header | ✅ Transport | Use Bearer scheme, never in URL params |

**Server side:**

- Refresh tokens are stored as SHA-256 hashes, never plaintext
- Passwords are bcrypt-hashed with configurable rounds (default 12)
- JWT secrets are environment variables, never committed to version control
- Public keys for RS256 are loaded from mounted volumes or environment

---

## 3. RBAC Model

### 3.1 Role Hierarchy

Roles are hierarchical — higher roles inherit all permissions of lower roles:

| Rank | Role | Capabilities |
|---|---|---|
| 4 | **admin** | Full system access: all endpoints, admin panel, model evolution, canary control |
| 3 | **expert** | Chat + feedback submission/review + enrichment triggers |
| 2 | **user** | Chat completions, widget access, auth endpoints |
| 1 | **read_only** | Model listing, health checks, auth endpoints only |

The role is extracted from JWT claims. For Keycloak tokens: `realm_access.roles`.
For internal tokens: `roles`. If a user has multiple roles, the **highest** wins.

```python
from proxy.app.rbac import get_user_role, Role

user = UserContext(user_id="1", username="alice", roles=["user", "admin"])
assert get_user_role(user) == Role.ADMIN  # highest wins
```

### 3.2 Permission Matrix

| Action | admin | expert | user | read_only |
|---|---|---|---|---|
| `admin:config` | ✅ | ❌ | ❌ | ❌ |
| `admin:users` | ✅ | ❌ | ❌ | ❌ |
| `admin:stats` | ✅ | ❌ | ❌ | ❌ |
| `admin:metrics` | ✅ | ❌ | ❌ | ❌ |
| `admin:warmup` | ✅ | ❌ | ❌ | ❌ |
| `feedback`, `feedback:submit` | ✅ | ✅ | ❌ | ❌ |
| `feedback:review` | ✅ | ✅ | ❌ | ❌ |
| `enrichment:trigger` | ✅ | ✅ | ❌ | ❌ |
| `chat`, `chat:stream` | ✅ | ✅ | ✅ | ❌ |
| `widget:access` | ✅ | ✅ | ✅ | ❌ |
| `models:list` | ✅ | ✅ | ✅ | ✅ |
| `health:check` | ✅ | ✅ | ✅ | ✅ |
| `auth:*` (login/refresh/register/logout/me) | ✅ | ✅ | ✅ | ✅ |

### 3.3 Role Enforcement in Endpoints

```python
from fastapi import Depends
from proxy.app.rbac import Role, require_role

# Admin-only endpoint
@app.post("/v1/admin/warmup")
async def warmup(user: UserContext = Depends(require_role(Role.ADMIN))):
    ...

# Expert+ endpoint
@app.post("/v1/feedback")
async def submit_feedback(
    user: UserContext = Depends(require_role(Role.EXPERT)),
):
    ...

# Authenticated user endpoint
@app.post("/v1/chat/completions")
async def chat_completions(
    user: UserContext = Depends(get_auth_context),
):
    ...
```

When RBAC check fails, the response is:

```json
{
  "detail": "Role 'user' is not sufficient. Required: 'expert'"
}
```
HTTP status: `403 Forbidden`.

### 3.4 Tool Visibility Levels

Tools (agentic tool calling) have visibility levels matching the RBAC model:

| Visibility | Accessible By | Usage |
|---|---|---|
| `public` | All authenticated users | General knowledge retrieval |
| `user` | user+ | Team-specific tools |
| `internal` | expert+ | Debugging, internal APIs |
| `admin` | admin only | System configuration, model management |

---

## 4. Data Classification & Row-Level Security

### 4.1 Classification Levels

Every document and chunk in Qdrant carries an `access_level` field:

| Level | Description | Who Can See |
|---|---|---|
| `public` | Accessible to all users | Everyone (even anonymous) |
| `internal` | All employees | All authenticated users |
| `confidential` | Restricted to specific groups | Users in `allowed_groups` |
| `restricted` | Named individuals only | Users in `allowed_users` |

### 4.2 Qdrant Payload Format

```json
{
  "chunk_id": "doc-123-chunk-5",
  "text": "...",
  "access_level": "confidential",
  "allowed_groups": ["engineering", "security"],
  "allowed_users": ["alice"],
  "namespace": "engineering",
  "source": "confluence.engineering-space"
}
```

### 4.3 Query-Time Access Filtering

The access filter is built per-request and pushed down to Qdrant as a payload filter.
This means restricted documents never leave the database:

```python
def build_access_filter(auth: UserContext) -> Filter:
    """Admins see everything. Others get filtered by access_level + groups/users."""
    if auth.is_admin:
        return None  # no filter → see everything

    return Filter(should=[
        # Public + Internal: always visible
        Filter(must=[
            FieldCondition(key="access_level", match=MatchAny(any=["public", "internal"]))
        ]),
        # Confidential: visible if user is in allowed_groups
        Filter(must=[
            FieldCondition(key="access_level", match=MatchValue(value="confidential")),
            FieldCondition(key="allowed_groups", match=MatchAny(any=auth.groups)),
        ]),
        # Restricted: visible if user is in allowed_users
        Filter(must=[
            FieldCondition(key="access_level", match=MatchValue(value="restricted")),
            FieldCondition(key="allowed_users", match=MatchValue(value=auth.username)),
        ]),
    ])
```

### 4.4 Namespace Isolation

When `NAMESPACE_ISOLATION_ENABLED=true`, users can only access chunks within their
namespace. This is enforced via an additional Qdrant filter:

```python
# User's effective namespace:
#   1. Explicit namespace from JWT claim
#   2. First group if namespace is empty
#   3. Empty string (global) if neither is set
FieldCondition(key="namespace", match=MatchValue(value=auth.effective_namespace))
```

This provides multi-tenant isolation at the vector DB level.

### 4.5 Context Trimming (Defense in Depth)

Even after Qdrant filtering, a **second pass** trims restricted chunks from the
assembled context before they reach the LLM:

```python
# In orchestrator.py:
visible_chunks = trim_restricted_context(retrieved_chunks, auth)
context = build_context(visible_chunks)
```

---

## 5. Endpoint Security

### 5.1 Public vs Authenticated Endpoints

| Endpoint | Auth Required | Notes |
|---|---|---|
| `GET /v1/health`, `/v1/health/live`, `/v1/health/ready` | No | Liveness/readiness probes |
| `GET /metrics` | No | Prometheus scraping |
| `GET /v1/models` | No | Model listing |
| `GET /v1/widget`, `/v1/widget.js` | No | Embeddable chat widget |
| `POST /v1/auth/login` | No | Token generation |
| `POST /v1/auth/register` | No | Self-registration |
| `POST /v1/auth/refresh` | No | Token refresh |
| `POST /v1/auth/logout` | Optional | Revokes tokens if authenticated |
| `GET /v1/auth/me` | **Yes** | Current user context |
| `POST /v1/chat/completions` | **Yes** | RAG chat (when AUTH_ENABLED=true) |
| `GET /v1/tools`, `/v1/tools/{name}` | Optional | Tool discovery |
| `POST /v1/feedback` | **Yes** (expert+) | Expert feedback |
| `POST /v1/admin/*` | **Yes** (admin) | Admin panel, model evolution, canary |

### 5.2 Rate Limiting

When `RATE_LIMIT_ENABLED=true`, a **token bucket** algorithm is applied:

| Config | Default | Description |
|---|---|---|
| `RATE_LIMIT_PER_MINUTE` | 60 | Sustained requests/minute per key |
| `RATE_LIMIT_BURST` | 10 | Maximum burst capacity |

**Key extraction priority:**
1. If `Authorization: Bearer <token>` is present → `apikey:<token>`
2. If `X-Forwarded-For` header is present → `ip:<client-ip>` (first entry)
3. Fallback → `ip:<direct-ip>`

**Rate-limit exceeded response:**

```json
{
  "error": "Rate limit exceeded"
}
```
HTTP status: `429 Too Many Requests`, with `Retry-After` header.

### 5.3 CORS Configuration

Default: `*` (all origins). For production, restrict to your frontend's origin:

```bash
CORS_ORIGINS="https://myapp.example.com,https://admin.example.com"
```

### 5.4 Security Headers

Every response includes:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
Cache-Control: no-store, no-cache, must-revalidate
X-Request-ID: <uuid>
X-Correlation-ID: <uuid>
```

---

## 6. Configuration Reference

All authentication and RBAC configuration is via environment variables (or `.env` file).

### 6.1 Core Auth Variables

```bash
# ── Master switch ──
AUTH_ENABLED=false               # Enable authentication (true/false)

# ── JWT settings ──
JWT_SECRET=""                    # HS256 signing key (min 32 chars in production)
JWT_ALGORITHM=HS256              # HS256 or RS256
JWT_PUBLIC_KEY=""                # RS256 public key PEM (for Keycloak or external IdP)

# ── Token lifetimes ──
TOKEN_EXPIRE_HOURS=24            # Internal token TTL (used by create_token)
ACCESS_TOKEN_MINUTES=60          # Access token TTL for /v1/auth/login
REFRESH_TOKEN_DAYS=7             # Refresh token TTL
TOKEN_BLACKLIST_MAX_ENTRIES=10000  # Max blacklist entries before eviction

# ── Legacy user import ──
AUTH_VALID_USERS={}              # JSON: {"username": {"password":"...","roles":["user"]}}
                                # Auto-migrated to SQLite on first startup
```

### 6.2 Keycloak OIDC Variables

```bash
KEYCLOAK_URL=""                  # Keycloak server URL (e.g., http://keycloak:8080)
KEYCLOAK_REALM=master            # Keycloak realm name
KEYCLOAK_CLIENT_ID=rag-proxy     # OIDC client ID registered in Keycloak
```

When `KEYCLOAK_URL` is set:
- The proxy fetches JWKS from `{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs`
- Token validation uses RS256 with the fetched public keys
- JWKS is cached for 1 hour
- If Keycloak is unreachable, falls back to `JWT_PUBLIC_KEY`

### 6.3 LDAP / Active Directory Variables

```bash
AD_ENABLED=false                 # Enable LDAP authentication
AD_URL=""                        # LDAP server URL (e.g., ldap://dc.example.com:389)
AD_BASE_DN=""                    # Base DN (e.g., dc=example,dc=com)
AD_USER_DN_TEMPLATE="cn={username},{base_dn}"  # DN template for bind
AD_GROUP_DN=""                   # Group search base (reserved for future group sync)
```

### 6.4 RBAC Variables

```bash
RBAC_ENABLED=false               # Enable role-based access control
```

When `RBAC_ENABLED=true`, endpoint role checks are enforced. When `false`,
all role checks pass (full access), but auth is still verified if `AUTH_ENABLED=true`.

### 6.5 User Database Variables

```bash
USER_DB_PATH="./data/users.db"   # SQLite database file path
BCRYPT_ROUNDS=12                 # Bcrypt cost factor (higher = slower but more secure)
```

The SQLite database is auto-created on first access. Schema includes:
- `users` — user records with bcrypt hashes
- `refresh_tokens` — token hashes with revocation status
- `token_blacklist` — JWT IDs of logged-out tokens

### 6.6 Sanitization & Audit Variables

```bash
SANITIZE_INPUT=true              # Enable input sanitization middleware
AUDIT_ENABLED=true               # Enable audit logging
```

### 6.7 Namespace Isolation

```bash
NAMESPACE_ISOLATION_ENABLED=false  # Multi-tenant namespace filtering
```

### 6.8 Rate Limiting

```bash
RATE_LIMIT_ENABLED=false         # Enable rate limiting
RATE_LIMIT_PER_MINUTE=60         # Sustained rate
RATE_LIMIT_BURST=10              # Burst capacity
```

---

## 7. Input Sanitization

### 7.1 What Gets Sanitized

All user-provided inputs pass through sanitization layers:

| Input Type | Max Length | Protections |
|---|---|---|
| Chat queries | 8,000 chars | SQL injection, HTML tags, control chars, whitespace collapse |
| Feedback text | 32,000 chars | XSS, script/iframe tags, event handlers, JS protocols, entity encoding |
| URL query params | 4,096 chars per value | HTML tags, control chars |
| Header values | 256 chars (keys) | — |

### 7.2 SQL Injection Prevention

The sanitizer strips SQL/DQL keywords from queries:

```python
# Blocked patterns (case-insensitive):
_SQL_KEYWORDS = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|EXEC|EXECUTE"
    r"|UNION|MERGE|REPLACE|GRANT|REVOKE|DECLARE|FETCH|OPEN)\b",
    re.IGNORECASE,
)

# Also blocked:
# - SQL comments (--)
# - Semicolons (;)
# - DQL injection ({$where:})
# - Function injection (function())
```

**Example — before/after:**

```
Input:  "SELECT * FROM users; DROP TABLE users--"
Output: "  *   users    users"
```

### 7.3 XSS Protection

```python
# Stripped from all input:
_HTML_TAG_RE        = re.compile(r"<[^>]*>")           # All HTML tags
_SCRIPT_TAG_RE      = re.compile(r"<script[\s>].*?</script>")  # Script blocks
_IFRAME_RE          = re.compile(r"<iframe[\s>].*?</iframe>")  # Iframe blocks
_JS_PROTOCOL_RE     = re.compile(r"javascript\s*:", re.IGNORECASE)
_VB_PROTOCOL_RE     = re.compile(r"vbscript\s*:", re.IGNORECASE)
_DATA_PROTOCOL_RE   = re.compile(r"data\s*:.*?base64", re.IGNORECASE)
_EVENT_HANDLER_RE   = re.compile(r"\bon(click|load|error|...)\s*=")
_CSS_EXPRESSION_RE  = re.compile(r"expression\s*\(", re.IGNORECASE)
_ENTITY_ENCODED_RE  = re.compile(r"&#x?[0-9a-f]+;", re.IGNORECASE)
_CONTROL_CHARS_RE   = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
```

### 7.4 Path Traversal Prevention

```python
def validate_path_traversal(path: str) -> bool:
    dangerous = ["..", "~", "\x00"]
    return not any(d in path for d in dangerous)
```

### 7.5 Log Sanitization

Before any data is written to logs, it passes through log sanitization:

```python
# Masks:
# - Email addresses  → [EMAIL]
# - IP addresses     → [IP]
# - Long tokens      → [REDACTED]
# - Auth headers     → [REDACTED]
# - API keys         → ***
# - Passwords        → ***
# - Secrets          → ***
```

---

## 8. Audit Logging

### 8.1 What Gets Logged

| Event | Log Level | Fields |
|---|---|---|
| Failed login attempt | WARNING | username, client IP, reason |
| Successful login | INFO | username, client IP |
| Token refresh | INFO | user_id, client IP |
| Token logout / revocation | INFO | user_id |
| LDAP bind failure | WARNING | username, error |
| LDAP auto-user creation | INFO | username |
| User registration | INFO | username, user_id |
| User deletion | INFO | user_id |
| Role/permission denied (403) | WARNING | user_id, required_role, actual_role, endpoint |
| Auth failure (401) | WARNING | client IP, endpoint, reason |
| Rate limit exceeded (429) | WARNING | key (masked), endpoint |
| HTTP 4xx errors | WARNING | method, path, status, client_ip |
| HTTP 5xx errors | ERROR | method, path, status, client_ip |

### 8.2 Log Format

**JSON format** (`LOG_FORMAT=json`):

```json
{
  "timestamp": "2026-07-06T14:30:00.123456+00:00",
  "level": "WARNING",
  "logger": "rag-proxy.auth",
  "message": "Failed login attempt for user 'alice' from 192.168.1.10: invalid password",
  "module": "auth",
  "function": "login",
  "line": 756,
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Text format** (`LOG_FORMAT=text`, default):

```
2026-07-06 14:30:00 [rag-proxy.auth] [WARNING] [a1b2c3d4] Failed login attempt for user 'alice' from 192.168.1.10: invalid password
```

### 8.3 Sensitive Data Protection in Logs

The following patterns are automatically masked before reaching log output:

- `Authorization: Bearer <token>` → `Authorization: Bearer ***`
- `api_key=<key>` → `api_key=***`
- `password=<value>` → `password=***`
- `secret=<value>` → `secret=***`
- `token=<value>` → `token=***`

Additional sensitive patterns can be added via `SENSITIVE_SECRETS` env var (comma-separated).

### 8.4 Audit Retention

- Logs are written to stdout/stderr (configured via `LOG_DIR`)
- For production, forward to your log aggregation system (ELK, Loki, CloudWatch)
- Recommend **90-day minimum retention** for security audit logs
- Token blacklist entries auto-expire after token TTL

---

## 9. Setup Guide

### Step 1: Enable Authentication

```bash
# proxy/.env
AUTH_ENABLED=true
JWT_SECRET=$(openssl rand -hex 32)   # Generate a strong random secret
# →
AUTH_ENABLED=true
JWT_SECRET=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0
```

Restart the proxy. Verify:

```bash
# Should return 401
curl -i http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
# HTTP/1.1 401 Unauthorized

# Health check still works
curl http://localhost:8080/v1/health
# {"status":"ok","qdrant":"connected","llm":"available"}
```

### Step 2: Create Initial Users

**Option A: Via environment variable (legacy import):**

```bash
export AUTH_VALID_USERS='{
  "admin": {
    "password": "admin-secure-password-123",
    "roles": ["admin"],
    "groups": ["engineering"],
    "access_level": "admin",
    "namespace": ""
  },
  "alice": {
    "password": "alice-pass-456",
    "roles": ["user"],
    "groups": ["engineering"],
    "access_level": "internal",
    "namespace": "engineering"
  }
}'
```

On first startup, these users are migrated to SQLite. **Remove `AUTH_VALID_USERS` after migration.**

**Option B: Via self-registration:**

```bash
# Register
curl -X POST http://localhost:8080/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "alice-pass-456", "email": "alice@example.com"}'

# Response:
# {"user_id": "a1b2c3d4e5f6a7b8...", "username": "alice", "created_at": "..."}
```

Then manually promote the user to admin via SQLite:

```bash
sqlite3 ./data/users.db "UPDATE users SET roles = '[\"admin\"]' WHERE username = 'alice';"
```

### Step 3: Configure RBAC

```bash
# proxy/.env
RBAC_ENABLED=true
```

Verify role checks:

```bash
# Get a user token
TOKEN=$(curl -s -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"alice-pass-456"}' \
  | jq -r '.access_token')

# Check current user
curl -s http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" | jq .

# Try feedback (requires expert+)
curl -X POST http://localhost:8080/v1/feedback \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query_id":"test","rating":"positive"}'
# If role is "user": HTTP/1.1 403 Forbidden
# {"detail":"Role 'user' is not sufficient. Required: 'expert'"}
```

### Step 4: Set Up Keycloak (Optional)

**4a. Run Keycloak:**

```yaml
# docker-compose.yml addition:
keycloak:
  image: quay.io/keycloak/keycloak:25.0
  environment:
    KC_BOOTSTRAP_ADMIN_USERNAME: admin
    KC_BOOTSTRAP_ADMIN_PASSWORD: admin
  command: start-dev
  ports:
    - "8082:8080"
```

**4b. Create a realm and client:**

1. Open `http://localhost:8082` → Administration Console
2. Create realm: `rag-system`
3. Create client: `rag-proxy` (Access Type: public, Standard Flow: ON)
4. Create roles: `admin`, `expert`, `user`, `read_only`
5. Create groups: `engineering`, `platform`, `security`
6. Create a user, assign roles and groups

**4c. Configure the proxy:**

```bash
KEYCLOAK_URL=http://keycloak:8080
KEYCLOAK_REALM=rag-system
KEYCLOAK_CLIENT_ID=rag-proxy
```

**4d. Test with a Keycloak token:**

```bash
# Get token from Keycloak (Resource Owner Password Credentials)
KC_TOKEN=$(curl -s -X POST http://localhost:8082/realms/rag-system/protocol/openid-connect/token \
  -d "client_id=rag-proxy" \
  -d "username=alice" \
  -d "password=alice-keycloak-pass" \
  -d "grant_type=password" \
  | jq -r '.access_token')

# Use it with the proxy
curl -s http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer $KC_TOKEN" | jq .
```

### Step 5: Configure LDAP (Optional)

```bash
AD_ENABLED=true
AD_URL=ldap://dc.example.com:389
AD_BASE_DN=dc=example,dc=com
AD_USER_DN_TEMPLATE=cn={username},ou=users,{base_dn}
```

Test LDAP login:

```bash
# This will attempt LDAP bind first, then create/find local user
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "alice-ldap-pass"}'
```

### Step 6: Enable Rate Limiting

```bash
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=100
RATE_LIMIT_BURST=20
```

### Step 7: Enable Namespace Isolation

```bash
NAMESPACE_ISOLATION_ENABLED=true
```

Users will only see chunks with a matching namespace. The namespace is determined by:
1. `namespace` claim in JWT
2. First `groups` entry if namespace is empty
3. Empty string (global) if neither is set

---

## 10. Security Checklist

### 10.1 Production Hardening

| # | Item | Verification Command |
|---|---|---|
| 1 | **JWT secret is strong** (≥32 random bytes) | `echo ${#JWT_SECRET}` — should be ≥64 chars for hex |
| 2 | **AUTH_ENABLED=true** in production | Check `.env`: `grep AUTH_ENABLED proxy/.env` |
| 3 | **RBAC_ENABLED=true** | Check `.env`: `grep RBAC_ENABLED proxy/.env` |
| 4 | **BCRYPT_ROUNDS ≥ 12** | Check `.env`: `grep BCRYPT_ROUNDS proxy/.env` |
| 5 | **Short access token TTL** (≤ 30 min) | Check: `grep ACCESS_TOKEN_MINUTES proxy/.env` |
| 6 | **Refresh token rotation enabled** | Default — tokens are consumed on use |
| 7 | **RATE_LIMIT_ENABLED=true** | Check `.env`: `grep RATE_LIMIT_ENABLED proxy/.env` |
| 8 | **CORS restricted** (not `*`) | Check `.env`: `grep CORS_ORIGINS proxy/.env` — should be specific origins |
| 9 | **HTTPS enforced** (via reverse proxy) | `curl -I https://your-proxy/v1/health` — should return `Strict-Transport-Security` header |
| 10 | **LOG_FORMAT=json** for structured logging | Check `.env`: `grep LOG_FORMAT proxy/.env` |
| 11 | **SANITIZE_INPUT=true** | Default is `true` — verify: `grep SANITIZE_INPUT proxy/.env` |
| 12 | **AUDIT_ENABLED=true** | Default is `true` — verify: `grep AUDIT_ENABLED proxy/.env` |
| 13 | **No secrets in version control** | `git log --all --full-history -- '*.env' '*.pem' '*.key'` — should be empty |
| 14 | **SQLite DB on persistent volume** | Check Docker/K8s mount: `USER_DB_PATH` should be on a volume |
| 15 | **Token blacklist has reasonable limit** | Check: `grep TOKEN_BLACKLIST_MAX_ENTRIES proxy/.env` |
| 16 | **Health endpoints NOT behind auth** | `curl http://proxy/v1/health` — should return 200 without token |
| 17 | **Admin endpoints behind auth + RBAC** | `curl http://proxy/v1/admin/models` — should return 401 or 403 without admin token |

### 10.2 Quick Security Audit Script

```bash
#!/bin/bash
# security-audit.sh — quick security posture check for RAG proxy

PROXY="http://localhost:8080"

echo "=== 1. Health check (should be public) ==="
curl -s -o /dev/null -w "Status: %{http_code}\n" "$PROXY/v1/health"

echo "=== 2. Chat without auth (should be 401 if AUTH_ENABLED) ==="
curl -s -o /dev/null -w "Status: %{http_code}\n" \
  -X POST "$PROXY/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"test"}]}'

echo "=== 3. Admin endpoint without auth (should be 401) ==="
curl -s -o /dev/null -w "Status: %{http_code}\n" "$PROXY/v1/admin/models"

echo "=== 4. Security headers check ==="
curl -sI "$PROXY/v1/health" | grep -E "X-Content-Type-Options|X-Frame-Options|Strict-Transport-Security"

echo "=== 5. Rate limiting check ==="
for i in $(seq 1 15); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$PROXY/v1/health")
  echo "Request $i: $STATUS"
done

echo "=== 6. SQL injection attempt on query ==="
curl -s -o /dev/null -w "Status: %{http_code}\n" \
  -X POST "$PROXY/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer invalid-token" \
  -d '{"messages":[{"role":"user","content":"SELECT * FROM users; DROP TABLE users--"}]}'

echo "=== Done ==="
```

### 10.3 JWT Token Inspection

To decode and inspect a JWT token (for debugging, do not do this in production logs):

```bash
# Decode without verification (inspect payload only)
echo "eyJhbGciOiJIUzI1NiIs..." | cut -d'.' -f2 | base64 -d 2>/dev/null | jq .

# Verify with key
python3 -c "
import jwt
token = 'eyJhbGciOiJIUzI1NiIs...'
secret = 'your-jwt-secret'
payload = jwt.decode(token, secret, algorithms=['HS256'])
print(payload)
"
```

### 10.4 Generate a Production-Grade JWT Secret

```bash
# Method 1: OpenSSL (hex, 64 chars)
openssl rand -hex 32

# Method 2: Python
python3 -c "import secrets; print(secrets.token_hex(32))"

# Method 3: /dev/urandom
head -c 32 /dev/urandom | base64 | tr -d '='
```

### 10.5 Common Pitfalls

| Problem | Cause | Solution |
|---|---|---|
| 401 on all endpoints | `AUTH_ENABLED=true` but no token sent | Include `Authorization: Bearer <token>` header |
| 403 on chat | `RBAC_ENABLED=true` but user has no `user` role | Ensure JWT claim includes `"roles": ["user"]` |
| "Invalid token" error | Wrong `JWT_SECRET` or `JWT_ALGORITHM` mismatch | Check `.env` values match the token issuer |
| Keycloak tokens rejected | Proxy using local JWT_SECRET instead of Keycloak JWKS | Set `KEYCLOAK_URL`; proxy auto-switches to RS256 |
| LDAP bind fails | Wrong DN template | Test DN: `ldapsearch -x -H ldap://dc:389 -D "cn=user,..." -w pass -b "dc=..."` |
| Registration fails | Username already exists (unique constraint) | Use a different username |
| Refresh returns "invalid" | Token was already consumed or expired | Get a new pair via login |
| Rate limited | Exceeded RATE_LIMIT_PER_MINUTE | Increase limit or wait for bucket refill |
| No audit logs | `AUDIT_ENABLED=false` or `LOG_FORMAT` not configured | Set `AUDIT_ENABLED=true`, `LOG_FORMAT=json` |

---

## Appendix A: Full JWT Token Example (HS256)

**Decoded header:**
```json
{"alg": "HS256", "typ": "JWT"}
```

**Decoded payload:**
```json
{
  "sub": "usr-alice-001",
  "preferred_username": "alice",
  "roles": ["user"],
  "groups": ["engineering", "platform"],
  "access_level": "internal",
  "namespace": "engineering",
  "iat": 1719000000,
  "exp": 1719086400,
  "jti": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "type": "access"
}
```

**Complete token (for testing; secret: `test-secret-key-for-unit-tests`):**
```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c3ItYWxpY2UtMDAxIiwicHJlZmVycmVkX3VzZXJuYW1lIjoiYWxpY2UiLCJyb2xlcyI6WyJ1c2VyIl0sImdyb3VwcyI6WyJlbmdpbmVlcmluZyIsInBsYXRmb3JtIl0sImFjY2Vzc19sZXZlbCI6ImludGVybmFsIiwibmFtZXNwYWNlIjoiZW5naW5lZXJpbmciLCJpYXQiOjE3MTkwMDAwMDAsImV4cCI6MTcxOTA4NjQwMCwianRpIjoiYTFiMmMzZDRlNWY2YTdiOGM5ZDBlMWYyYTNiNGM1ZDYiLCJ0eXBlIjoiYWNjZXNzIn0.signature_here
```

## Appendix B: Full Curl Examples for All Auth Flows

```bash
# ── Registration ──
curl -X POST http://localhost:8080/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "bob",
    "password": "bob-secure-password",
    "email": "bob@example.com"
  }'

# ── Login ──
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "bob", "password": "bob-secure-password"}'

# ── Get current user ──
curl http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer <access_token>"

# ── Refresh tokens ──
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<refresh_token>"}'

# ── Logout ──
curl -X POST http://localhost:8080/v1/auth/logout \
  -H "Authorization: Bearer <access_token>"

# ── Authenticated chat ──
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3",
    "messages": [{"role": "user", "content": "What is our deployment process?"}]
  }'

# ── Submit feedback (expert+) ──
curl -X POST http://localhost:8080/v1/feedback \
  -H "Authorization: Bearer <admin_or_expert_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "query_id": "q-123",
    "rating": "positive",
    "correction": "The deployment uses ArgoCD, not Flux."
  }'

# ── Admin: list models ──
curl http://localhost:8080/v1/admin/models \
  -H "Authorization: Bearer <admin_token>"

# ── Admin: trigger warmup ──
curl -X POST http://localhost:8080/v1/admin/warmup \
  -H "Authorization: Bearer <admin_token>"
```

## Appendix C: Quick Reference Card

```
┌──────────────────────────────────────────────────────────────────┐
│                     RAG PROXY SECURITY                           │
├──────────────┬───────────────────────────────────────────────────┤
│ Auth methods │ JWT (HS256/RS256) • Keycloak OIDC • LDAP/AD      │
│              │ API keys • Self-registration                      │
├──────────────┼───────────────────────────────────────────────────┤
│ Token types  │ Access (JWT, short-lived) • Refresh (opaque, 1×)  │
│ Revocation   │ Logout → full revocation + JTI blacklist          │
├──────────────┼───────────────────────────────────────────────────┤
│ Roles        │ admin (4) > expert (3) > user (2) > read_only (1) │
│ Hierarchical │ Higher role inherits all lower permissions        │
├──────────────┼───────────────────────────────────────────────────┤
│ Data levels  │ public < internal < confidential < restricted     │
│ Qdrant RLS   │ Payload filter at query time + context trimming   │
│ Namespace    │ Optional multi-tenant isolation                   │
├──────────────┼───────────────────────────────────────────────────┤
│ Rate limit   │ Token bucket: 60 req/min + 10 burst (default)     │
│ Headers      │ STS, CSP, XFO, XSS, Referrer-Policy, Permissions  │
├──────────────┼───────────────────────────────────────────────────┤
│ Sanitization │ SQL injection • XSS • Path traversal • Length     │
│ Audit log    │ Logins, 401/403, admin actions, 4xx/5xx           │
├──────────────┼───────────────────────────────────────────────────┤
│ Config       │ ~20 env vars, all in proxy/.env                   │
│ Quick start  │ AUTH_ENABLED=true + JWT_SECRET=<random>           │
└──────────────┴───────────────────────────────────────────────────┘
```
