# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅ Current |
| 0.1.x   | ❌ Deprecated |

## Reporting a Vulnerability

Report security issues to: alexander.narbayev@gmail.com

Please do NOT open public issues for security vulnerabilities.

## Security Measures

- All external service calls use circuit breaker with exponential backoff
- JWT authentication with HS256/RS256 signing
- RBAC with 5 roles × 4 access levels for data filtering
- Input sanitization on all endpoints
- Secrets masked in logs and responses
- Rate limiting per IP/API key
- Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- Audit logging of all operations (JSONL format)
- No hardcoded secrets — all via environment variables

## Dependency Management

- All Python dependencies pinned to minimum versions in requirements files
- Dependabot configured for automated security updates
- Minimal dependency footprint — optional packages lazily imported

## Data Protection

- Air-gapped deployment supported — no external API calls
- Access levels: public, internal, confidential, restricted
- Chunk-level access filtering in retrieval
- Audit trail for all data access
