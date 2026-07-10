# User Guide

How to use the RAG Knowledge Assistant: authentication, roles, feedback, and how your input improves the system.

## Overview

The RAG system is designed to learn from user interactions. Every query, every response rating, and every expert correction feeds back into the system to improve future results. This guide explains how to interact with the system effectively and how your feedback drives continuous improvement.

## User Roles

The system implements role-based access control (RBAC) with four hierarchical roles:

| Role | Permissions | Typical User |
|------|------------|--------------|
| **admin** | All endpoints: chat, feedback, user management, configuration, metrics | System administrators |
| **expert** | Chat + feedback submission + review + enrichment triggers | Domain experts, knowledge curators |
| **user** | Chat + widget access | Regular users |
| **read_only** | Models list + health check + auth endpoints | API consumers, monitoring |

Roles are hierarchical — a higher role inherits all permissions of lower roles. When RBAC is disabled (`RBAC_ENABLED=false`), all authenticated users have full access.

## Authentication

### Login

Send a `POST` request to `/v1/auth/login`:

```bash
curl -X POST http://localhost:8080/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "your-password"}'
```

Response:

```json
{
  "access_token": "eyJhbGciOiJIUzI1...",
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2g...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### Registration

Self-registration is available at `/v1/auth/register`:

```bash
curl -X POST http://localhost:8080/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secure-password", "email": "alice@example.com"}'
```

New users are assigned the `user` role by default.

### Using Tokens

Include the access token in requests via the `Authorization` header:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1..." \
  -H "Content-Type: application/json" \
  -d '{"model": "default", "messages": [{"role": "user", "content": "How do I configure CI/CD?"}]}'
```

Alternatively, use the `X-Auth-Token` header (no `Bearer` prefix).

### Token Refresh

Access tokens expire after `ACCESS_TOKEN_MINUTES` (default: 60 minutes). Use the refresh token to obtain a new token pair:

```bash
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "dGhpcyBpcyBhIHJlZnJlc2g..."}'
```

Refresh tokens are single-use — each refresh issues a new pair.

### Logout

Revoke all tokens for the current user:

```bash
curl -X POST http://localhost:8080/v1/auth/logout \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1..."
```

## Chat Interface

### Basic Query

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [{"role": "user", "content": "How do I set up GitLab CI?"}]
  }'
```

### RAG-Specific Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `rag_version` | string | Request a specific document version |
| `rag_force_refresh` | boolean | Bypass response cache and re-retrieve |

Response extensions (in `x-rag-*` headers or response metadata):

| Extension | Description |
|-----------|-------------|
| `rag_feedback_id` | Use this ID to submit feedback on the response |
| `rag_confidence` | Confidence score (0.0–1.0) |
| `rag_sources` | List of source documents used |

### Streaming

Standard OpenAI streaming is supported:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "stream": true,
    "messages": [{"role": "user", "content": "Explain the deployment pipeline"}]
  }'
```

## Providing Feedback

Feedback is the primary mechanism for improving system quality. Every chat response includes a `rag_feedback_id` that you use to rate the answer.

### Positive Feedback

When a response is accurate and helpful:

```bash
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "feedback_id": "fb_abc123def456",
    "rating": "positive"
  }'
```

### Negative Feedback

When a response is incorrect or unhelpful:

```bash
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "feedback_id": "fb_abc123def456",
    "rating": "negative",
    "comment": "The CI/CD steps are outdated for GitLab 16.x"
  }'
```

### Corrections

Experts can provide corrected answers:

```bash
curl -X POST http://localhost:8080/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "feedback_id": "fb_abc123def456",
    "rating": "negative",
    "correction": "To set up GitLab CI in version 16+, create a .gitlab-ci.yml...",
    "comment": "Original answer was for GitLab 14.x syntax"
  }'
```

> **Note:** Submitting feedback requires the `expert` or `admin` role.

## How Feedback Improves Results

Your feedback drives a continuous improvement loop:

### Positive Feedback → Knowledge Enrichment

When `ENRICHMENT_ENABLED=true`:

1. A positive rating on a response is received
2. The system extracts the Q&A pair (query + answer)
3. The pair is chunked and embedded
4. The new chunk is indexed into Qdrant

This means future queries similar to the original will find this confirmed-good answer as a retrieval candidate, improving recall for that topic.

### Negative Feedback → Reranker Fine-Tuning

Negative ratings and corrections are collected as training data:

1. The `export_training_dataset()` function extracts all interactions with corrections or positive feedback
2. These become (query, answer) pairs for fine-tuning the reranker
3. Corrections are preferred over original answers in the training set

Run the export manually:

```python
from pathlib import Path
from proxy.app.core.hitl import export_training_dataset

export_training_dataset(Path("./training_data.jsonl"))
```

### Intent Dataset Export

Interaction logs can also be exported as intent classification training data:

```python
from pathlib import Path
from proxy.app.core.hitl import export_intent_dataset

export_intent_dataset(Path("./intent_data.jsonl"))
```

### User Profile → Personalized Retrieval

User context (roles, groups, namespace) influences retrieval:

- **Namespace isolation**: Users in different namespaces see different document scopes
- **Access level**: Document visibility is filtered by the user's access level
- **Groups**: Group membership can affect which knowledge silos are queried

## Confidence Scores

Every response includes a confidence score between 0.0 and 1.0. This score is computed by combining multiple signals:

### Score Components

| Signal | Weight | Description |
|--------|--------|-------------|
| Context presence | Base | Penalty if retrieved context is empty or very short |
| Context-to-answer ratio | 0.2 | Penalty if context is much shorter than the answer |
| Uncertainty phrases | 0.2 | Penalty for hedging language ("I'm not sure", "possibly") |
| Answer length | 0.15 | Penalty for very short answers |
| NLI grounding | 0.4 | How many answer claims are supported by the context |

### Interpreting Scores

| Score Range | Meaning | Recommended Action |
|-------------|---------|-------------------|
| 0.8–1.0 | High confidence | Trust the answer |
| 0.5–0.8 | Moderate confidence | Verify important details |
| 0.0–0.5 | Low confidence | Answer may contain hallucinations; rephrase your query or consult a human |

### NLI Grounding

When NLI grounding is enabled, the system:

1. Decomposes the answer into atomic claims
2. Checks each claim against the retrieved context
3. Reports which claims are supported and which are not

This helps detect hallucinations — claims in the answer that have no supporting evidence in the source documents.

### Retrieval Quality

The system also evaluates retrieval quality using a CRAG-style classifier:

- **Correct**: Chunks highly relevant to the query
- **Ambiguous**: Chunks partially relevant
- **Incorrect**: Chunks not relevant to the query

If retrieval quality is poor, consider rephrasing your query to be more specific.

## FAQ

### Q: What happens when auth is disabled?

When `AUTH_ENABLED=false` (default), all endpoints are accessible without authentication. The system operates in anonymous mode with full access. This is suitable for local development and internal deployments behind a VPN.

### Q: Can I use the system without Keycloak?

Yes. The system supports two authentication modes:

1. **Local mode** (default): Uses HS256 with `JWT_SECRET`. User registration and login via `/v1/auth/register` and `/v1/auth/login`.
2. **Keycloak/OIDC mode**: When `KEYCLOAK_URL` is set, the system auto-discovers OIDC configuration and validates RS256 tokens from Keycloak.

### Q: How do I get expert role?

By default, new registrations get the `user` role. An admin must promote users to `expert` via the user database. In local mode, you can configure initial users via the `AUTH_VALID_USERS` environment variable.

### Q: Is my feedback stored permanently?

Interaction logs and feedback are stored as JSONL files in the configured `LOG_DIR`. Files are automatically rotated when they exceed the size limit (10 MB for interactions, 5 MB for feedback), with up to 5 backup files retained.

### Q: Can I use the widget without authentication?

Yes. The widget endpoint (`/v1/widget`) and JavaScript (`/v1/widget.js`) are public endpoints that work without authentication. They are listed as public in the auth middleware.

### Q: How does the system handle sensitive data?

- Passwords are hashed with bcrypt (configurable rounds)
- Refresh tokens are stored as SHA-256 hashes
- Token blacklisting prevents reuse of revoked tokens
- Access tokens include JTI (JWT ID) for individual revocation
- All user data is stored locally in SQLite — no external services required

### Q: What metrics are available?

When `METRICS_ENABLED=true`, Prometheus metrics are exposed at `/metrics`, including:

- Request counts and latencies
- Feedback submission rates
- Confidence score distributions
- Cache hit rates
