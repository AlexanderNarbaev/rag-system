# Block G. HITL, Auth and RBAC (FR-73 — FR-94)

---

## FR-73. Expert feedback submission

**Description:**
Experts can submit feedback on system answers:

- `positive` — the answer is correct
- `negative` — the answer is incorrect (with a mandatory `correction` field)
- Feedback is tied to the `rag_feedback_id` from the response

**Acceptance criteria:**

1. POST `/v1/feedback` with `feedback_type=positive` — 200 OK
2. POST `/v1/feedback` with `feedback_type=negative, correction="..."` — 200 OK
3. Feedback without `correction` when `negative` — 400 Bad Request

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR73FeedbackSubmission`)
**Priority:** HIGH
**Reference:** ADR-007

---

## FR-74. Feedback storage (SQLite)

**Description:**
Feedback is stored in SQLite with metadata: user_id, feedback_id, query, answer,
feedback_type, correction, timestamp. Supports export to JSONL for fine-tuning.

**Acceptance criteria:**

1. Feedback is saved to SQLite
2. Export to JSONL — a valid format for fine-tuning
3. Querying feedback by feedback_id — returns the record

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR74FeedbackStorage`)
**Priority:** HIGH
**Reference:** ADR-007

---

## FR-75. Feedback analytics

**Description:**
The admin panel shows feedback statistics:

- Number of positive/negative over a period
- Top-10 queries with negative feedback
- Average confidence score by feedback
- Trends by days/weeks

**Acceptance criteria:**

1. GET `/v1/admin/feedback/stats` — returns statistics
2. Statistics include count_positive, count_negative, avg_confidence
3. Date filtering works

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR75FeedbackAnalytics`)
**Priority:** HIGH
**Reference:** ADR-007

---

## FR-76. Feedback → training dataset export

**Description:**
The system exports feedback in a fine-tuning format:

- Positive feedback → positive pairs (query, good_answer)
- Negative feedback → negative pairs (query, bad_answer, correction)
- Format: JSONL with fields query, response, correction, label

**Acceptance criteria:**

1. Export to JSONL — valid format
2. Positive feedback → positive pair in the export
3. Negative feedback → negative pair with correction in the export

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR76FeedbackExport`)
**Priority:** HIGH
**Reference:** ADR-007, ADR-010

---

## FR-77. Rate limiting for feedback

**Description:**
A single user can submit no more than 100 feedback records per hour.

**Acceptance criteria:**

1. 100 feedback/hour — all are processed
2. The 101st feedback — 429 Too Many Requests

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR77FeedbackRateLimiting`)
**Priority:** MEDIUM
**Reference:** NFR-S12

---

## FR-78. Feedback metadata preservation

**Description:**
When a document is reindexed, feedback is preserved and tied to the new chunk
version (if the content has not changed fundamentally).

**Acceptance criteria:**

1. Document reindexing — feedback is preserved
2. Feedback is tied to the new chunk_id (if the content is the same)
3. Fully changed content — feedback is detached

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR78FeedbackPreservation`)
**Priority:** MEDIUM
**Reference:** NFR-M05

---

## FR-84. JWT authentication (access + refresh)

**Description:**
The system generates JWT tokens:

- **Access token** — lifetime (15 min), contains user_id, roles, permissions
- **Refresh token** — lifetime (7 days), stored in SQLite, can be revoked

On login — a token pair is issued. On refresh — the old refresh token is invalidated
and a new pair is issued.

**Acceptance criteria:**

1. POST `/v1/auth/login` — returns `{access_token, refresh_token, token_type, expires_in}`
2. GET `/v1/auth/me` with access_token — returns the user context
3. POST `/v1/auth/refresh` with refresh_token — returns a new pair
4. An expired access_token — 401 Unauthorized
5. A revoked refresh_token — 401 Unauthorized

**Status:** ✅ Confirmed (`proxy/app/auth/jwt.py`)
**Priority:** CRITICAL
**Reference:** ADR-004

---

## FR-85. Keycloak OIDC integration

**Description:**
The system integrates with Keycloak for corporate SSO. The user
authenticates via Keycloak, the proxy receives the access token and maps
roles from Keycloak to local roles.

**Acceptance criteria:**

1. A Keycloak access token — the proxy authenticates the user
2. Roles from Keycloak are mapped to local ones (admin/expert/user/read_only)
3. An invalid Keycloak token — 401

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR85KeycloakOIDC`)
**Priority:** HIGH
**Reference:** access-control-rbac

---

## FR-86. LDAP/AD authentication

**Description:**
The system connects to LDAP/AD to authenticate corporate users.
Parameters: LDAP URL, base DN, bind DN, bind password.

**Acceptance criteria:**

1. Valid LDAP credentials — authentication succeeds
2. Invalid credentials — 401
3. LDAP unavailable — fallback to the local DB

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR86LDAPAuth`)
**Priority:** HIGH
**Reference:** access-control-rbac

---

## FR-87. API key authentication

**Description:**
The system supports API keys as an alternative authentication method.
Keys are stored in SQLite, tied to a user, and can be revoked.

**Acceptance criteria:**

1. `Authorization: Bearer sk-xxx` — authentication succeeds
2. An invalid key — 401
3. A revoked key — 401

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR87APIKeys`)
**Priority:** HIGH
**Reference:** access-control-rbac

---

## FR-87b. User identification via headers (OpenWebUI)

**Description:**
When OpenWebUI connects to the proxy with a single shared API key, the system identifies
individual users via HTTP headers:

- `X-OpenWebUI-User-Id` — user ID from OpenWebUI
- `X-Forwarded-User` — alternative header
- `user` field in the request body — standard OpenAI API field

Priority chain: X-OpenWebUI-User-Id > X-Forwarded-User > JWT sub > user field > anonymous.

**Acceptance criteria:**

1. A request with `X-OpenWebUI-User-Id: alice` — UserContext.user_id = alice
2. Without headers — UserContext is taken from the API key
3. The log contains 'User identity from header: alice'

**Status:** ✅ Confirmed (`tests/integration/test_openwebui_proxy.py`, `proxy/app/auth/jwt.py::get_auth_context` lines
250-261, `proxy/app/shared/middleware.py::RequestIdMiddleware` lines 39-42)
**Priority:** CRITICAL
**Reference:** access-control-rbac

---

## FR-88. RBAC — 4 roles

**Description:**
The system implements Role-Based Access Control with 4 roles:

- **admin** — full access to all endpoints and the admin panel
- **expert** — access to chat, feedback, knowledge base management
- **user** — access to chat only
- **read_only** — access to chat in "read-only" mode (no feedback)

**Acceptance criteria:**

1. Admin — access to all `/v1/admin/*` endpoints
2. Expert — access to `/v1/feedback`, 403 on `/v1/admin/*`
3. User — access to `/v1/chat/completions`, 403 on `/v1/feedback`
4. Read_only — access to `/v1/chat/completions`, 403 on `/v1/feedback`

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR88RBAC`,
`tests/integration/test_auth_flow.py::TestRBACEnforcement`)
**Priority:** CRITICAL
**Reference:** access-control-rbac

---

## FR-89. ACL in Qdrant queries

**Description:**
Every search query to Qdrant includes an ACL filter. The user sees
only the chunks they have access to. The ACL is stored in the payload of each chunk.

**Acceptance criteria:**

1. A user with role=user — sees only chunks with access_level=public or access_level=user
2. A user with role=admin — sees all chunks
3. A request without authentication — sees only public chunks

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR89ACLQdrant`)
**Priority:** CRITICAL
**Reference:** NFR-S03

---

## FR-90. Secret rotation

**Description:**
The system supports secret rotation (JWT secret, API keys) without downtime.
The old secret remains valid for a grace period (24 hours by default).

**Acceptance criteria:**

1. JWT secret rotation — old tokens are valid during the grace period
2. After the grace period — old tokens are invalid
3. API key rotation — the old key is valid during the grace period

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR90SecretRotation`)
**Priority:** HIGH
**Reference:** secrets-rotation.md

---

## FR-91. Rate limiting ✅

**Description:**
The system limits the number of requests from a single IP: token bucket algorithm
with burst. Parameters: `RATE_LIMIT_PER_MINUTE=60`, `RATE_LIMIT_BURST=10`.

**Acceptance criteria:**

1. 60 requests/minute — all are processed
2. The 61st request — 429 Too Many Requests
3. A burst of up to 10 requests — processed immediately
4. After the burst — the rate limit recovers per the token bucket

**Status:** ✅ Confirmed (`proxy/app/shared/rate_limiter.py`)
**Priority:** HIGH
**Reference:** best-practices-checklist 3.2

---

## FR-92. Input validation ✅

**Description:**
The system validates all input data:

- Query ≤ 10,000 characters
- Messages ≤ 100 messages
- Content is not empty
- JSON is valid
- Temperature 0-2
- Max_tokens > 0

**Acceptance criteria:**

1. Query > 10K characters — 400 Bad Request
2. Empty content — 400
3. Invalid JSON — 400
4. Temperature > 2 — 400

**Status:** ✅ Confirmed (`proxy/app/shared/security.py`)
**Priority:** CRITICAL
**Reference:** best-practices-checklist 3.5

---

## FR-93. Audit logging

**Description:**
All security events are logged to a JSONL file:

- Login/logout (user_id, timestamp, IP, success/failure)
- Admin actions (who, what, when)
- Config changes (who, old_value, new_value)
- Feedback submissions (user_id, feedback_id, timestamp)

**Acceptance criteria:**

1. Login — a record in the audit log with user_id, timestamp, IP
2. Admin action — a record in the audit log
3. Audit log — valid JSONL
4. Secrets are masked (not in plain text)

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR93AuditLogging`)
**Priority:** CRITICAL
**Reference:** best-practices-checklist 3.10

---

## FR-94. CORS configuration

**Description:**
CORS headers are configured via `CORS_ORIGINS` (a list of allowed origins).
By default — `*` (all origins). In production — specific domains.

**Acceptance criteria:**

1. `CORS_ORIGINS=*` — header `Access-Control-Allow-Origin: *`
2. `CORS_ORIGINS=https://example.com` — header `Access-Control-Allow-Origin: https://example.com`
3. Preflight OPTIONS — returns 200 with CORS headers

**Status:** ✅ Confirmed (`tests/proxy/test_auth_rbac.py::TestFR94CORS`,
`tests/integration/test_auth_flow.py::TestCORSIntegration`)
**Priority:** HIGH
**Reference:** middleware.py
