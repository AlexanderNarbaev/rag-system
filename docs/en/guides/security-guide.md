# Security Guide

This guide covers the security model, authentication, authorization, input sanitization, rate limiting, audit logging, and deployment hardening for the RAG System proxy.

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Authorization (RBAC)](#authorization-rbac)
4. [Input Sanitization](#input-sanitization)
5. [Rate Limiting](#rate-limiting)
6. [Audit Logging](#audit-logging)
7. [Secrets Management](#secrets-management)
8. [Network Security](#network-security)
9. [Air-Gapped Deployment](#air-gapped-deployment)
10. [Security Checklist](#security-checklist)

---

## Overview

The RAG System follows a defense-in-depth security model with multiple layers:

| Layer | Component | File |
|-------|-----------|------|
| **Authentication** | JWT tokens, Keycloak OIDC, LDAP/AD | `proxy/app/auth/jwt.py` |
| **Authorization** | Role-based access control (RBAC) | `proxy/app/auth/rbac.py` |
| **User Store** | SQLite with bcrypt passwords | `proxy/app/auth/user_db.py` |
| **LDAP Integration** | Active Directory / LDAP bind | `proxy/app/auth/ldap.py` |
| **Input Sanitization** | SQL injection, XSS, length limits | `proxy/app/shared/sanitizer.py` |
| **Security Utilities** | Validation, secrets, headers | `proxy/app/shared/security.py` |
| **Rate Limiting** | Token bucket per-IP/API-key | `proxy/app/shared/rate_limiter.py` |
| **Audit Logging** | JSONL event log | `proxy/app/shared/audit.py` |
| **Middleware** | Request ID, CORS, security headers | `proxy/app/shared/middleware.py` |

### Design Principles

- **Air-gapped first**: no external API calls at runtime. All models are pre-downloaded.
- **Graceful degradation**: every component can fail independently without crashing the proxy.
- **Defense in depth**: multiple independent security layers — even if one fails, others protect.
- **Least privilege**: RBAC enforces minimum required permissions per role.
- **Zero trust input**: all user input is sanitized before processing.

---

## Authentication

### JWT Token Authentication

The system supports two JWT algorithms:

| Algorithm | Use Case | Key Source |
|-----------|----------|------------|
| **HS256** (default) | Local dev, service accounts | `JWT_SECRET` env var |
| **RS256** | Keycloak OIDC, production SSO | `JWT_PUBLIC_KEY` or JWKS endpoint |

#### Configuration

```bash
AUTH_ENABLED=true                    # Enable authentication (default: false)
JWT_SECRET=your-secret-key           # HS256 signing key
JWT_ALGORITHM=HS256                  # or RS256
JWT_PUBLIC_KEY=""                    # PEM public key for RS256
TOKEN_EXPIRE_HOURS=24                # Token lifetime
ACCESS_TOKEN_MINUTES=60              # Access token lifetime
REFRESH_TOKEN_DAYS=7                 # Refresh token lifetime
```

#### Token Structure

```json
{
  "sub": "user-uuid",
  "preferred_username": "alice",
  "roles": ["user"],
  "groups": ["engineering"],
  "access_level": "internal",
  "namespace": "engineering",
  "iat": 1699900000,
  "exp": 1700000000,
  "jti": "unique-token-id"
}
```

#### Token Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/auth/login` | POST | Username/password login, returns access + refresh token pair |
| `/v1/auth/register` | POST | Self-registration (bcrypt-hashed passwords in SQLite) |
| `/v1/auth/refresh` | POST | Exchange refresh token for new access + refresh pair |
| `/v1/auth/logout` | POST | Revoke refresh tokens, blacklist access token |
| `/v1/auth/me` | GET | Current user context |

#### Authentication Modes

1. **Disabled** (`AUTH_ENABLED=false`, default): All requests use anonymous context with full access.
2. **Enabled** (`AUTH_ENABLED=true`): Requires valid Bearer token on all `/v1/*` endpoints.
3. **Keycloak OIDC** (`KEYCLOAK_URL` set): Auto-discovers OIDC configuration, validates RS256 tokens via JWKS.

#### Public Endpoints (no auth required even when enabled)

- `/v1/auth/login`, `/v1/auth/register`, `/v1/auth/refresh`
- `/v1/health`, `/v1/health/live`, `/v1/health/ready`
- `/v1/models`, `/v1/widget`, `/v1/widget.js`
- `/metrics`

### Keycloak OIDC Integration

When `KEYCLOAK_URL` is configured:

```bash
KEYCLOAK_URL=https://keycloak.example.com
KEYCLOAK_REALM=master
KEYCLOAK_CLIENT_ID=rag-proxy
```

The system automatically:
1. Fetches JWKS from `{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs`
2. Caches keys for 1 hour
3. Validates RS256 tokens against the fetched public keys
4. Falls back to `JWT_PUBLIC_KEY` if JWKS is unavailable (air-gapped)

### LDAP / Active Directory

When `AD_ENABLED=true`, the login endpoint first attempts LDAP bind before falling back to local SQLite authentication.

```bash
AD_ENABLED=true
AD_URL=ldap://ldap.example.com:389
AD_BASE_DN=dc=example,dc=com
AD_USER_DN_TEMPLATE=cn={username},{base_dn}
```

**Behavior:**
- On successful LDAP bind, the user is auto-created in the local SQLite database with default `user` role.
- If LDAP server is unreachable, falls through to local authentication with a warning log.
- LDAP users get a random local password (not used for auth).

---

## Authorization (RBAC)

### Roles

Roles are hierarchical — higher roles inherit all permissions of lower roles:

| Role | Rank | Permissions |
|------|------|-------------|
| `admin` | 4 | All endpoints, user management, configuration, warmup |
| `expert` | 3 | Chat, feedback submission/review, enrichment trigger |
| `user` | 2 | Chat, streaming, widget access |
| `read_only` | 1 | Models list, health checks, auth endpoints |

### Configuration

```bash
RBAC_ENABLED=true    # Enable RBAC enforcement (default: false)
```

When RBAC is disabled, all users have full access regardless of role.

### Permission Map

```
admin:config      → ADMIN
admin:users       → ADMIN
admin:stats       → ADMIN
feedback          → EXPERT
feedback:submit   → EXPERT
feedback:review   → EXPERT
enrichment:trigger → EXPERT
chat              → USER
chat:stream       → USER
widget:access     → USER
models:list       → READ_ONLY
health:check      → READ_ONLY
auth:login        → READ_ONLY
auth:register     → READ_ONLY
```

### Usage in Code

```python
from proxy.app.auth.rbac import Role, require_role

@app.post("/v1/feedback")
async def submit_feedback(user: UserContext = Depends(require_role(Role.EXPERT))):
    # Only experts and admins can reach this point
    ...
```

---

## Input Sanitization

### Sanitizer Module (`proxy/app/shared/sanitizer.py`)

Provides three sanitization functions:

#### `sanitize_query(text)`

Strips from user search queries:
- SQL/DQL injection keywords (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `DROP`, etc.)
- SQL comments (`--`)
- Semicolons
- HTML tags
- JavaScript/VBScript protocols
- Event handlers (`onclick`, `onload`, etc.)
- CSS expressions
- Control characters
- Maximum length: 8,000 characters

#### `sanitize_feedback(text)`

Strips from expert feedback:
- Script tags, iframes
- HTML tags
- JavaScript/VBScript/data protocols
- Event handlers
- CSS expressions
- Entity-encoded XSS (`&#x...;`)
- Control characters
- Maximum length: 32,000 characters

#### `validate_length(text, max_len)`

Truncates text to specified maximum length.

### Security Utilities (`proxy/app/shared/security.py`)

#### InputValidator

| Method | Description |
|--------|-------------|
| `validate_query(query)` | Sanitize user query (8000 char max) |
| `validate_non_empty(s, max_len)` | Validate non-empty string within length |
| `sanitize_for_log(text)` | Mask emails, IPs, API keys for safe logging |
| `validate_model_name(name)` | Check model name contains only safe characters |
| `validate_path_traversal(path)` | Check for `..`, `~`, `\x00` path traversal |
| `sanitize_headers(headers)` | Redact sensitive headers (Authorization, Cookie, etc.) |
| `escape_shell_arg(arg)` | Strip shell-unsafe characters |

#### SecretsManager

| Method | Description |
|--------|-------------|
| `generate_api_key(prefix)` | Generate cryptographically secure API key |
| `hash_secret(secret)` | SHA-256 hash for storage |
| `verify_secret(secret, hashed)` | Verify against hash |
| `mask_in_response(data)` | Deep-mask sensitive fields in response dicts |
| `generate_token(length)` | Random URL-safe token |
| `constant_time_compare(a, b)` | Timing-attack-safe string comparison |

### Middleware-Level Sanitization

The `InputSanitizationMiddleware` automatically sanitizes query parameters on every request.

---

## Rate Limiting

### Token Bucket Algorithm

The rate limiter uses a token bucket algorithm with per-IP and per-API-key tracking.

#### Configuration

```bash
RATE_LIMIT_ENABLED=true       # Enable rate limiting (default: false)
RATE_LIMIT_PER_MINUTE=60      # Requests per minute per key
RATE_LIMIT_BURST=10           # Maximum burst size
```

#### Behavior

1. Each client IP (or API key from Bearer token) gets an independent token bucket.
2. Tokens refill at `RATE_LIMIT_PER_MINUTE / 60` per second.
3. Bucket capacity is `RATE_LIMIT_BURST` tokens.
4. When exhausted, returns HTTP 429 with `Retry-After` header.
5. Expired buckets (unused for 5+ minutes) are cleaned up automatically.

#### Key Extraction

- If `Authorization: Bearer <token>` is present → key is `apikey:<token>`
- Otherwise → key is `ip:<client-ip>` (respects `X-Forwarded-For`)

#### Response

```json
// HTTP 429
{
  "error": "Rate limit exceeded"
}
// Headers: Retry-After: <seconds>
```

---

## Audit Logging

### Configuration

```bash
AUDIT_ENABLED=true    # Enable audit logging (default: true)
LOG_DIR=./logs        # Audit log directory
```

### Event Types

| Event Type | Description | Logged Fields |
|------------|-------------|---------------|
| `query` | RAG query execution | user_id, query_preview, response_preview, chunks, duration, tokens |
| `login` | Authentication attempt | user_id, action, success |
| `auth` | Auth events (logout, refresh) | user_id, action, success |
| `access_denied` | Permission denied | user_id, resource, reason |
| `config_change` | Configuration modification | key, old_value (masked), new_value (masked) |
| `error` | Application errors | error_type, message, stack_trace |
| `trace` | Detailed per-request trace | query, chunks, rerank scores, token breakdown, confidence |

### Log Format

Audit events are written to `/var/log/rag-system/audit.jsonl` as JSON Lines:

```json
{
  "event_id": "evt_1699900000_abc123",
  "timestamp": "2024-01-15T10:30:00+00:00",
  "event_type": "query",
  "user_id": "alice",
  "client_ip": "10.0.0.1",
  "endpoint": "/v1/chat/completions",
  "request_hash": "a1b2c3d4e5f6g7h8",
  "details": {
    "query_preview": "How to configure...",
    "chunks_retrieved": 5,
    "metadata": {}
  },
  "duration_ms": 1234.56,
  "tokens_used": 1500,
  "result_status": "success"
}
```

### Sensitive Data Handling

- Query content is truncated to 200 characters in audit logs
- Configuration values are masked (first 4 + last 4 characters)
- Request hashes use SHA-256 (first 16 hex chars)

---

## Secrets Management

### Environment Variables

All secrets are configured via environment variables or `.env` file:

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET` | JWT signing key |
| `JWT_PUBLIC_KEY` | RS256 public key (PEM) |
| `LLM_API_KEY` | LLM backend API key |
| `EMBEDDER_API_KEY` | Embedding service API key |
| `RERANKER_API_KEY` | Reranker service API key |
| `NEO4J_PASSWORD` | Neo4j database password |
| `AD_BASE_DN` | LDAP base DN |

### Best Practices

1. **Never commit `.env` files** to version control.
2. **Use different secrets** per environment (dev/staging/prod).
3. **Rotate secrets** regularly — the system supports hot-reload of configuration.
4. **Mask secrets in logs** — the logging module automatically masks API keys, passwords, and tokens.
5. **Use Kubernetes secrets** or HashiCorp Vault in production.

### Log Masking

The logging module (`proxy/app/shared/logging.py`) automatically masks:
- `api_key`, `API_KEY` values
- `Authorization: Bearer` tokens
- `password` values
- `secret` values
- `token` values

---

## Network Security

### CORS Configuration

```bash
CORS_ORIGINS=*                    # Allowed origins (comma-separated or *)
```

The CORS middleware exposes these headers to clients:
- `X-Request-ID`
- `X-Correlation-ID`
- `Retry-After`

### Security Headers

The `SecurityHeadersMiddleware` injects these headers into every response:

| Header | Value |
|--------|-------|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `Content-Security-Policy` | `default-src 'self'` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `Cache-Control` | `no-store, no-cache, must-revalidate` |

### HTTPS

The proxy itself runs over HTTP. Terminate TLS at the reverse proxy (nginx, Traefik, Kubernetes Ingress).

---

## Air-Gapped Deployment

The system is designed to run without internet access:

1. **All models are pre-downloaded** using `scripts/download_models_offline.py`.
2. **No external API calls** at runtime — Keycloak JWKS fetch is optional and fails gracefully.
3. **Local fallbacks** — when remote embedder/reranker is unavailable, falls back to local models.
4. **No telemetry** — OpenTelemetry is disabled by default and only sends to local collector.

---

## Security Checklist

### Production Deployment

- [ ] `AUTH_ENABLED=true` — authentication is enabled
- [ ] `RBAC_ENABLED=true` — role-based access control is enforced
- [ ] `RATE_LIMIT_ENABLED=true` — rate limiting is active
- [ ] `SANITIZE_INPUT=true` — input sanitization is enabled
- [ ] `AUDIT_ENABLED=true` — audit logging is active
- [ ] `JWT_SECRET` is set to a strong random value (32+ characters)
- [ ] `JWT_ALGORITHM=RS256` with Keycloak OIDC for production SSO
- [ ] `CORS_ORIGINS` is restricted to specific domains (not `*`)
- [ ] TLS is terminated at the reverse proxy
- [ ] `.env` file is not committed to version control
- [ ] Secrets are rotated regularly
- [ ] Audit logs are monitored and retained
- [ ] `WORKERS=1` to protect shared state (embedder, cache)
- [ ] `LOG_FORMAT=json` for structured log aggregation
- [ ] Health endpoints are accessible for Kubernetes probes

### Development

- [ ] `AUTH_ENABLED=false` for local development
- [ ] Use `create_mock_token()` for testing
- [ ] Rate limiting disabled for load testing
- [ ] Audit logging enabled even in dev for debugging

---

## Related Documentation

- [Access Control & RBAC](access-control-rbac.md) — detailed RBAC design
- [Deployment Guide](deployment-guide.md) — production deployment procedures
- [Operations Guide](operations-guide.md) — operational procedures
- [Troubleshooting](troubleshooting.md) — common issues and resolutions
