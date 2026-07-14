# Federated RAG

**Version:** v2.0.0 | **Last Updated:** 2026-07-06

Guide to deploying and operating the Federated RAG Proxy — a standalone service that fans out queries across multiple
independent RAG instances (silos), merges results, and generates answers from the unified corpus.

---

## Table of Contents

1. [Concept](#1-concept)
2. [Architecture](#2-architecture)
3. [Quick Start](#3-quick-start)
4. [Configuration Reference](#4-configuration-reference)
5. [Silo Configuration Schema](#5-silo-configuration-schema)
6. [Federation Modes](#6-federation-modes)
7. [Merge Strategies](#7-merge-strategies)
8. [API Reference](#8-api-reference)
9. [Access Control](#9-access-control)
10. [Generation Delegation](#10-generation-delegation)
11. [Circuit Breakers](#11-circuit-breakers)
12. [Monitoring](#12-monitoring)
13. [Deployment](#13-deployment)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Concept

### What Is Federated RAG?

Federated RAG allows you to query **multiple independent RAG instances** (called "silos") through a single unified
endpoint. Each silo maintains its own vector database, knowledge graph, and document collection. The federation layer:

1. Receives a single query from the user
2. Fans out the query to multiple silos **in parallel** (via `asyncio.gather`)
3. Merges results using configurable strategies
4. Optionally generates a final answer using a shared LLM or delegates to a primary silo

### When to Use It

| Scenario                        | Why Federated RAG                                                                        |
|---------------------------------|------------------------------------------------------------------------------------------|
| **Multi-department knowledge**  | HR, Engineering, Finance each have separate RAG instances with different access controls |
| **Geo-distributed teams**       | Silos in US-East, US-West, EU-West with local latency optimization                       |
| **Mergers & acquisitions**      | Combine RAG systems from different companies without migrating data                      |
| **Data isolation requirements** | Legal/policy mandates keep certain document sets on separate infrastructure              |
| **Independent scaling**         | High-traffic engineering docs and low-traffic HR docs scale independently                |

### Multi-Silo Topology

```
┌──────────────────────────────────────────────────────┐
│                  Federated RAG Proxy                  │
│                    (Port 8001)                        │
│                                                       │
│  /v1/chat/completions   /v1/search   /v1/silos       │
│  /v1/health             /v1/models   /metrics         │
└───────┬─────────────────┬──────────────────┬──────────┘
        │                 │                  │
   ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
   │ HR Silo │       │ Eng Silo│       │ Fin Silo│
   │ Qdrant-A│       │ Qdrant-B│       │ Qdrant-C│
   │ Neo4j-A │       │ Neo4j-B │       │ Neo4j-C │
   │ LLM-A   │       │ LLM-B   │       │ LLM-C   │
   └─────────┘       └─────────┘       └─────────┘
```

**Key principle:** Each silo is a complete, self-contained RAG proxy instance with its own `/v1/chat/completions`
endpoint. The federation layer does **not** have its own vector store — it is purely a router, merger, and generation
delegator.

---

## 2. Architecture

### Component Overview

```
federation/
├── app/
│   ├── main.py              # FastAPI app, 6 endpoints, lifespan management
│   ├── router.py            # federated_search(): fan-out orchestration
│   ├── merger.py            # weighted_rrf, round_robin, top_per_instance strategies
│   ├── silo_client.py       # Async HTTP fan-out to individual silos
│   ├── silo_registry.py     # SiloConfig registry with access group filtering
│   ├── circuit_breaker.py   # Per-silo circuit breaker (CLOSED → OPEN → HALF_OPEN)
│   ├── auto_router.py       # Keyword-based query → silo classification
│   ├── auth.py              # check_silo_access()
│   ├── jwt_auth.py          # JWT token → user_groups extraction
│   ├── models.py            # SiloConfig, SiloSearchResult, FederatedSearchResult, FederationContext
│   ├── config.py            # All FEDERATION_* env vars
│   ├── metrics.py           # 7 Prometheus metrics
│   └── exceptions.py        # FederationError hierarchy
├── tests/                   # 14 test files
├── Dockerfile
├── docker-compose.federation.yml
├── requirements.txt
└── .env.example
```

### Request Flow

```
Client Request
      │
      ▼
┌─────────────────┐
│  JWT Extraction  │  extract_user_groups() → ["admin", "engineering"]
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Mode Resolution │  auto → classify_query() | strict → target_silos | merge → all accessible
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Access Filter   │  list_accessible(user_groups) → [SiloConfig, ...]
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Circuit Breaker  │  For each silo: allow_request()? → active | skipped
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Parallel Fanout │  asyncio.gather(query_silo(s1), query_silo(s2), ...)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Merge Results   │  weighted_rrf() | round_robin() | top_per_instance()
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Generate Answer  │  Direct LLM (FEDERATION_LLM_ENDPOINT) | Primary silo delegation
└────────┬────────┘
         │
         ▼
   Client Response
```

### Key Design Decisions

| Decision                                | Rationale                                                                        |
|-----------------------------------------|----------------------------------------------------------------------------------|
| **Async fan-out (asyncio.gather)**      | Parallelizes silo queries; total latency ≈ max(silo_latency) not sum             |
| **Circuit breaker per silo**            | Prevents cascading failures; 5 consecutive failures → OPEN for 30s               |
| **No vector store in federation**       | Federation is stateless; all retrieval happens in silos                          |
| **Graceful partial failure**            | If 1 of 3 silos times out, the federation returns results from the other 2       |
| **rag_skip_generation on silo queries** | Silos return only `rag_sources` (chunks), not full answers — saves LLM inference |

---

## 3. Quick Start

### Prerequisites

- **Docker** 24.0+ and **Docker Compose** v2.20+
- At least **one running RAG proxy instance** (the federation layer queries silos via their `/v1/chat/completions`
  endpoints)
- Python 3.12+ (if running without Docker)

### 3.1 Docker Deployment (Recommended)

```bash
# From the project root
cd federation

# Copy and edit the environment file
cp .env.example .env

# Edit .env to point to your silos
# Minimum: update FEDERATION_INSTANCES_JSON

# Start the federation proxy
docker compose -f docker-compose.federation.yml up -d

# Verify it's running
curl http://localhost:8001/v1/health
```

### 3.2 Minimal Configuration

Create `federation/.env`:

```bash
# Federation mode: auto | strict | merge
FEDERATION_MODE=auto

# At least one silo (pointing to an existing RAG proxy)
FEDERATION_INSTANCES_JSON='[
  {
    "id": "hr",
    "name": "HR Knowledge Base",
    "proxy_url": "http://localhost:8000/v1",
    "weight": 1.0,
    "access_groups": ["admin", "hr"],
    "collections": ["knowledge_base"],
    "is_primary": true
  }
]'

# Merge strategy
FEDERATION_MERGE_STRATEGY=weighted_rrf
FEDERATION_MERGE_K=60
FEDERATION_RRF_K=60

# Timeouts
FEDERATION_TOTAL_TIMEOUT_S=30
FEDERATION_PER_INSTANCE_TIMEOUT_S=10
```

### 3.3 First Query

```bash
# Chat completion — search + generate
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-federated",
    "messages": [
      {"role": "user", "content": "What is our sick leave policy?"}
    ]
  }'

# Search only — retrieve chunks without generation
curl -X POST http://localhost:8001/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "vacation policy",
    "federation_top_k": 20
  }'

# List accessible silos
curl http://localhost:8001/v1/silos

# List models
curl http://localhost:8001/v1/models

# Health check
curl http://localhost:8001/v1/health
```

---

## 4. Configuration Reference

All configuration is set via environment variables in `federation/.env`.

### Required Variables

| Variable                    | Default | Description                                                                          |
|-----------------------------|---------|--------------------------------------------------------------------------------------|
| `FEDERATION_INSTANCES_JSON` | `[]`    | JSON array of silo configurations. Must contain at least one silo.                   |
| `FEDERATION_MODE`           | `auto`  | Federation mode: `auto`, `strict`, or `merge`. See [Section 6](#6-federation-modes). |

### Merge Configuration

| Variable                    | Default        | Description                                                                                                   |
|-----------------------------|----------------|---------------------------------------------------------------------------------------------------------------|
| `FEDERATION_MERGE_STRATEGY` | `weighted_rrf` | Merge strategy: `weighted_rrf`, `round_robin`, or `top_per_instance`. See [Section 7](#7-merge-strategies).   |
| `FEDERATION_MERGE_K`        | `60`           | Maximum number of chunks returned after merge (top-K). Range: 1–200.                                          |
| `FEDERATION_RRF_K`          | `60`           | RRF smoothing constant. Higher values reduce rank position sensitivity. Used only by `weighted_rrf` strategy. |

### Timeout Configuration

| Variable                            | Default | Description                                                                                                              |
|-------------------------------------|---------|--------------------------------------------------------------------------------------------------------------------------|
| `FEDERATION_PER_INSTANCE_TIMEOUT_S` | `10`    | Timeout for each individual silo HTTP request (seconds).                                                                 |
| `FEDERATION_TOTAL_TIMEOUT_S`        | `30`    | Budgeted total timeout — logged for monitoring, not enforced at the HTTP level (FastAPI handles request-level timeouts). |

### Circuit Breaker Configuration

| Variable                                | Default | Description                                                              |
|-----------------------------------------|---------|--------------------------------------------------------------------------|
| `FEDERATION_CIRCUIT_BREAKER_THRESHOLD`  | `5`     | Consecutive failures before circuit breaker opens.                       |
| `FEDERATION_CIRCUIT_BREAKER_RECOVERY_S` | `30`    | Seconds to wait before attempting recovery (transitioning to HALF_OPEN). |

### LLM / Generation Configuration

| Variable                      | Default | Description                                                                                                                                                             |
|-------------------------------|---------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `FEDERATION_LLM_ENDPOINT`     | `""`    | Direct LLM endpoint for generation. When set, the federation layer generates answers itself instead of delegating to a primary silo. Example: `http://llm-host:8000/v1` |
| `FEDERATION_LLM_MODEL`        | `""`    | Model name to use with `FEDERATION_LLM_ENDPOINT` for direct generation.                                                                                                 |
| `FEDERATION_AUTO_SLM_ENABLED` | `true`  | Enable keyword-based auto-routing in `auto` mode. When `false`, auto mode fans out to all silos.                                                                        |

### Auth Configuration

| Variable                    | Default | Description                                                                                                       |
|-----------------------------|---------|-------------------------------------------------------------------------------------------------------------------|
| `FEDERATION_AUTH_ENABLED`   | `false` | When `true`, the federation extracts user groups from JWT tokens. When `false`, uses `FEDERATION_DEFAULT_GROUPS`. |
| `FEDERATION_JWT_SECRET`     | `""`    | Secret key for JWT signature verification. Falls back to `JWT_SECRET` env var.                                    |
| `FEDERATION_JWT_ALGORITHM`  | `HS256` | JWT signing algorithm. Falls back to `JWT_ALGORITHM` env var.                                                     |
| `FEDERATION_DEFAULT_GROUPS` | `admin` | Comma-separated list of groups assigned when auth is disabled. Example: `admin,engineering,hr`.                   |

### Silo Config File Alternative

| Variable                    | Default | Description                                                                                                                                    |
|-----------------------------|---------|------------------------------------------------------------------------------------------------------------------------------------------------|
| `FEDERATION_INSTANCES_FILE` | `""`    | Path to a JSON file containing silo configurations. When set, overrides `FEDERATION_INSTANCES_JSON`. Useful for mounting via ConfigMap in K8s. |

---

## 5. Silo Configuration Schema

Each silo in `FEDERATION_INSTANCES_JSON` is a JSON object with the following fields:

### Full Schema

```json
{
  "id": "hr",
  "name": "HR Knowledge Base",
  "proxy_url": "http://rag-hr.internal:8000/v1",
  "weight": 1.0,
  "access_groups": ["admin", "hr"],
  "collections": ["knowledge_base"],
  "api_key": "sk-hr-proxy-key-12345",
  "timeout_s": 10,
  "is_primary": true
}
```

### Field Reference

| Field           | Type     | Required | Default | Description                                                                                                                                        |
|-----------------|----------|----------|---------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`            | string   | **Yes**  | —       | Unique silo identifier. Used in federation metadata and circuit breaker naming.                                                                    |
| `name`          | string   | **Yes**  | —       | Human-readable silo name for responses and logs.                                                                                                   |
| `proxy_url`     | string   | **Yes**  | —       | Base URL of the RAG proxy instance. Must include the path prefix (e.g., `http://host:8000/v1`). Trailing slashes are stripped automatically.       |
| `weight`        | float    | No       | `1.0`   | Relative weight for the `weighted_rrf` merge strategy. Higher weight = silo results ranked higher. Must be > 0.                                    |
| `access_groups` | string[] | No       | `[]`    | List of groups that can access this silo. User must be in at least one group for access. Empty list = no group restriction.                        |
| `collections`   | string[] | No       | `[]`    | Qdrant collections available in this silo. Informational — not enforced at the federation layer.                                                   |
| `api_key`       | string   | No       | `null`  | Bearer token sent as `Authorization: Bearer <api_key>` to the silo's proxy.                                                                        |
| `timeout_s`     | int      | No       | `10`    | Per-request timeout for this specific silo (overrides `FEDERATION_PER_INSTANCE_TIMEOUT_S`).                                                        |
| `is_primary`    | boolean  | No       | `false` | When `true`, this silo is used for LLM generation delegation when no direct `FEDERATION_LLM_ENDPOINT` is configured. Only one primary recommended. |

### Validation Rules

The `SiloRegistry.validate()` method enforces:

- Each `id` must be unique (duplicate IDs raise `ConfigError`)
- `weight` must be > 0
- `proxy_url` must be non-empty

### Examples

**Single primary silo (minimal):**

```json
[
  {
    "id": "all",
    "name": "All Knowledge",
    "proxy_url": "http://localhost:8000/v1",
    "is_primary": true
  }
]
```

**Multi-department with access control:**

```json
[
  {
    "id": "eng",
    "name": "Engineering Wiki",
    "proxy_url": "http://rag-eng.internal:8000/v1",
    "weight": 1.2,
    "access_groups": ["engineering", "admin"],
    "collections": ["eng_docs", "eng_wiki"],
    "api_key": "sk-eng-xxx",
    "timeout_s": 8,
    "is_primary": true
  },
  {
    "id": "hr",
    "name": "HR Knowledge Base",
    "proxy_url": "http://rag-hr.internal:8000/v1",
    "weight": 1.0,
    "access_groups": ["hr", "admin"],
    "collections": ["hr_policies", "hr_benefits"],
    "api_key": "sk-hr-xxx",
    "timeout_s": 10
  },
  {
    "id": "finance",
    "name": "Finance Documents",
    "proxy_url": "http://rag-fin.internal:8000/v1",
    "weight": 0.8,
    "access_groups": ["finance", "admin"],
    "collections": ["finance_reports"],
    "api_key": "sk-fin-xxx",
    "timeout_s": 15,
    "is_primary": false
  }
]
```

**Geo-distributed with regional weights:**

```json
[
  {
    "id": "us-east",
    "name": "US East Region",
    "proxy_url": "http://rag-use1.internal:8000/v1",
    "weight": 1.0,
    "timeout_s": 10,
    "is_primary": true
  },
  {
    "id": "us-west",
    "name": "US West Region",
    "proxy_url": "http://rag-usw2.internal:8000/v1",
    "weight": 1.0,
    "timeout_s": 12
  },
  {
    "id": "eu-west",
    "name": "EU West Region",
    "proxy_url": "http://rag-euw1.internal:8000/v1",
    "weight": 0.7,
    "timeout_s": 20
  }
]
```

---

## 6. Federation Modes

Three modes control which silos receive queries. The mode is set via `FEDERATION_MODE` and can be overridden per-request
via the `federation_mode` field in the request body.

### 6.1 `auto` — Keyword-Based Routing (Default)

The federation analyzes the query text and routes it to the most relevant silos using keyword matching.

**How it works:**

1. `classify_query()` in `auto_router.py` checks the query against a keyword map:
    - **hr**: `sick leave`, `vacation`, `hiring`, `onboarding`, `payroll`, `salary`, `benefits`, `hr policy`, and
      Russian equivalents (`больничный`, `отпуск`)
    - **engineering**: `deploy`, `production`, `kubernetes`, `docker`, `pipeline`, `code review`, `merge request`,
      `pull request`, `git`, `jira`, `confluence`, `architecture`, `microservice`, `api`
    - **finance**: `budget`, `expense`, `invoice`, `reimbursement`, `report`, `quarterly`, `annual`, `fiscal`, `tax`
2. Silos are sorted by match count (most matches first).
3. If no keywords match, the query fans out to **all** accessible silos.

**When to use:**

- Queries are domain-specific and keywords are sufficient for routing
- You want to minimize silo load by not fanning out to irrelevant silos
- You have a small number of clearly-separated knowledge domains

**When NOT to use:**

- Queries span multiple domains (e.g., "Compare engineering and HR onboarding processes")
- Your silos have overlapping content that isn't captured by keyword mapping

**Disabling keyword routing:**
Set `FEDERATION_AUTO_SLM_ENABLED=false` to make `auto` mode fan out to all silos unconditionally.

### 6.2 `strict` — Explicit Silo Targeting

Queries only the silo(s) specified by the client in the `federation_silo` request field.

**How it works:**

1. Client sends `"federation_silo": "hr"` in the request body.
2. Only the `hr` silo is queried.
3. Other silos are completely ignored.
4. Access control still applies — the user must have access to the requested silo.

**Example request:**

```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag-federated",
    "federation_silo": "hr",
    "federation_mode": "strict",
    "messages": [
      {"role": "user", "content": "What is our remote work policy?"}
    ]
  }'
```

**When to use:**

- The client (UI or upstream service) already knows which silo to query
- You have a silo selector in your chat UI
- Debugging — isolating a specific silo's behavior

### 6.3 `merge` — Fan-Out to All Accessible Silos

Queries **every** silo the user has access to, regardless of query content.

**How it works:**

1. `list_accessible(user_groups)` returns all silos the user can access.
2. The query is sent to every accessible silo in parallel.
3. Results from all silos are merged.

**When to use:**

- Cross-domain queries (e.g., "What company policies apply to engineering interns?")
- You want maximum recall at the cost of higher latency and silo load
- You have a small number of silos (2–5) where fan-out overhead is acceptable

### Mode Comparison

| Aspect               | `auto`                         | `strict`                            | `merge`                    |
|----------------------|--------------------------------|-------------------------------------|----------------------------|
| Silo selection       | Keyword-based, fallback to all | Client-specified: `federation_silo` | All accessible silos       |
| Latency              | Low (few silos queried)        | Lowest (1 silo)                     | Highest (all silos)        |
| Recall               | Domain-targeted                | Silo-scoped                         | Maximum cross-silo         |
| Per-request override | `federation_mode: "auto"`      | `federation_mode: "strict"`         | `federation_mode: "merge"` |
| Good for             | Domain-separated knowledge     | Silo-isolated queries               | Cross-domain search        |

---

## 7. Merge Strategies

After fan-out, the federation must combine results from multiple silos into a single ranked list. Three strategies are
available.

### 7.1 `weighted_rrf` — Weighted Reciprocal Rank Fusion (Default)

**Formula:**

For each chunk at rank position `r` (0-indexed) from a silo with weight `w`:

```
RRF_Score(chunk) = w / (k + r + 1)
```

Where:

- `w` = the silo's configured `weight` factor (default: 1.0)
- `k` = RRF smoothing constant (`FEDERATION_RRF_K`, default: 60)
- `r` = the chunk's 0-based rank within its silo's results

After scoring, chunks are sorted by descending RRF score, deduplicated (by SHA-256 of text+source+title), and truncated
to `merge_k`.

**Effect of `k`:**

- Higher `k` (e.g., 120) → rank position matters less → more even blending
- Lower `k` (e.g., 20) → rank position dominates → top-ranked chunks from each silo are strongly preferred

**Effect of `weight`:**

- `weight: 2.0` → silo's chunks always outrank identically-positioned chunks from a `weight: 1.0` silo
- Useful for prioritizing primary/authoritative sources

**Example:**

```
Silo A (weight=1.0): [chunk_a1 (rank 0), chunk_a2 (rank 1)]
Silo B (weight=1.2): [chunk_b1 (rank 0), chunk_b2 (rank 1)]

RRF(chunk_a1) = 1.0 / (60 + 0 + 1) = 0.01639
RRF(chunk_a2) = 1.0 / (60 + 1 + 1) = 0.01613
RRF(chunk_b1) = 1.2 / (60 + 0 + 1) = 0.01967  ← top result
RRF(chunk_b2) = 1.2 / (60 + 1 + 1) = 0.01935

Final order: chunk_b1, chunk_b2, chunk_a1, chunk_a2
```

**When to use:**

- You trust the silos' internal ranking (score-aware retrieval)
- You have silos with different authority levels (use weights)
- Default strategy for most deployments

### 7.2 `round_robin` — Interleaved Fairness

Takes the first chunk from each silo, then the second, then the third, etc.

**Example:**

```
Silo A: [a1, a2, a3]
Silo B: [b1, b2]

Round-robin: a1, b1, a2, b2, a3 → deduplicated, truncated to merge_k
```

**When to use:**

- You want equal representation from every silo
- Silo internal rankings are unreliable or incomparable
- You want diversity across silos rather than score optimization

**Limitation:** Does not use `weight` — all silos are treated equally.

### 7.3 `top_per_instance` — Proportional Allocation

Takes the top `merge_k / n` chunks from each of `n` silos, then sorts all selected chunks by score.

**Example (merge_k=60, 3 silos):**

```
Per silo: 20 chunks selected

Silo A top-20: [...]
Silo B top-20: [...]
Silo C top-20: [...]

All 60 chunks sorted by descending score → truncated to merge_k
```

**When to use:**

- You want guaranteed representation from every silo
- Each silo's scoring is comparable across silos
- You want the "best of each" rather than pure interleaving

### Strategy Selection Guide

| Strategy           | Uses Weights | Uses Scores                | Best For                                |
|--------------------|--------------|----------------------------|-----------------------------------------|
| `weighted_rrf`     | Yes          | Yes (indirectly, via rank) | Most deployments; authoritative sources |
| `round_robin`      | No           | No                         | Diversity; equal representation         |
| `top_per_instance` | No           | Yes (silo scores)          | Guaranteed per-silo representation      |

**Per-request override:**

```bash
curl -X POST http://localhost:8001/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "deployment checklist",
    "federation_merge_strategy": "round_robin",
    "federation_top_k": 30
  }'
```

If an unknown strategy is specified, the merger falls back to `weighted_rrf`.

---

## 8. API Reference

All endpoints are served by the federation FastAPI app on port 8001.

### 8.1 `POST /v1/chat/completions`

OpenAI-compatible chat completion with federation. Performs search + merge + generation.

**Request:**

```json
{
  "model": "rag-federated",
  "messages": [
    {"role": "user", "content": "What is our sick leave policy?"}
  ],
  "federation_mode": "auto",
  "federation_silo": null,
  "federation_merge_strategy": "weighted_rrf",
  "federation_top_k": 60,
  "rag_skip_generation": false,
  "temperature": 0.3,
  "stream": false
}
```

**Request Fields:**

| Field                       | Type    | Required | Default                     | Description                                                   |
|-----------------------------|---------|----------|-----------------------------|---------------------------------------------------------------|
| `model`                     | string  | Yes      | —                           | Must be `"rag-federated"`.                                    |
| `messages`                  | array   | Yes      | —                           | Chat messages. Last message `content` is used as the query.   |
| `federation_mode`           | string  | No       | `FEDERATION_MODE`           | Override mode: `auto`, `strict`, or `merge`.                  |
| `federation_silo`           | string  | No       | `null`                      | Target silo ID for `strict` mode.                             |
| `federation_merge_strategy` | string  | No       | `FEDERATION_MERGE_STRATEGY` | Override merge strategy.                                      |
| `federation_top_k`          | int     | No       | `FEDERATION_MERGE_K`        | Max chunks after merge.                                       |
| `rag_skip_generation`       | boolean | No       | `false`                     | When `true`, returns only search results (no LLM generation). |

**Response (with generation):**

```json
{
  "id": "fed-1751234567",
  "object": "chat.completion",
  "model": "rag-federated",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Based on the federated search across HR and Engineering silos, the sick leave policy allows..."
      },
      "finish_reason": "stop"
    }
  ],
  "rag_sources": [
    {
      "chunk_id": "abc123",
      "source": "confluence",
      "title": "Sick Leave Policy 2026",
      "version": "v3.1",
      "silo_id": "hr",
      "silo_name": "HR Knowledge Base",
      "relevance": 0.01967,
      "text_preview": "Employees are entitled to 10 sick days per calendar year..."
    }
  ],
  "rag_confidence": 0.7,
  "federation": {
    "mode": "auto",
    "silos_queried": ["hr"],
    "silos_skipped": [],
    "cross_silo": false,
    "total_latency_ms": 234.5,
    "per_silo_latency_ms": {
      "hr": 215.3
    },
    "warnings": []
  }
}
```

**Response (skip_generation=true or no chunks):**

```json
{
  "id": "fed-1751234567",
  "object": "chat.completion",
  "model": "rag-federated",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": ""
      },
      "finish_reason": "stop"
    }
  ],
  "rag_sources": [...],
  "rag_metadata": {
    "total_retrieved": 12,
    "merged_count": 8,
    "latency_ms": 234.5
  },
  "federation": {...}
}
```

**Error response (all silos down):**

```json
{
  "error": "All silos unavailable: ['hr', 'eng']",
  "type": "AllSilosDownError"
}
```

HTTP Status: 503

### 8.2 `POST /v1/search`

Search-only endpoint. Retrieves and merges chunks without LLM generation.

**Request:**

```json
{
  "query": "deployment pipeline",
  "federation_mode": "merge",
  "federation_silo": null,
  "federation_merge_strategy": "weighted_rrf",
  "federation_top_k": 30
}
```

**Response:**

```json
{
  "rag_sources": [
    {
      "chunk_id": "def456",
      "source": "gitlab",
      "title": "CI/CD Pipeline Setup",
      "version": "v2.0",
      "silo_id": "eng",
      "silo_name": "Engineering Wiki",
      "relevance": 0.02100,
      "text_preview": "The deployment pipeline consists of three stages..."
    }
  ],
  "rag_metadata": {
    "total_retrieved": 45,
    "merged_count": 25,
    "latency_ms": 312.8
  },
  "federation": {
    "mode": "merge",
    "silos_queried": ["eng", "hr"],
    "silos_skipped": [],
    "cross_silo": true,
    "total_latency_ms": 312.8,
    "per_silo_latency_ms": {
      "eng": 180.2,
      "hr": 295.5
    },
    "warnings": []
  }
}
```

### 8.3 `GET /v1/silos`

Lists silos accessible to the authenticated user (or all silos if auth is disabled).

**Response:**

```json
{
  "silos": [
    {
      "id": "hr",
      "name": "HR Knowledge Base",
      "collections": ["knowledge_base"],
      "accessible": true
    },
    {
      "id": "eng",
      "name": "Engineering Wiki",
      "collections": ["eng_docs", "eng_wiki"],
      "accessible": true
    },
    {
      "id": "finance",
      "name": "Finance Documents",
      "collections": ["finance_reports"],
      "accessible": false
    }
  ]
}
```

### 8.4 `GET /v1/health`

Comprehensive health check with silo status.

**Response:**

```json
{
  "status": "healthy",
  "federation": {
    "mode": "auto",
    "total_silos": 3,
    "silos": {
      "hr": {"name": "HR Knowledge Base", "status": "configured"},
      "eng": {"name": "Engineering Wiki", "status": "configured"},
      "finance": {"name": "Finance Documents", "status": "configured"}
    }
  }
}
```

### 8.5 `GET /v1/health/live`

Kubernetes liveness probe. Returns `{"status": "ok"}` if the process is running.

### 8.6 `GET /v1/health/ready`

Kubernetes readiness probe. Returns silo URLs and statuses. Returns `not_ready` if the silo registry hasn't initialized.

### 8.7 `GET /v1/models`

OpenAI-compatible model listing.

**Response:**

```json
{
  "object": "list",
  "data": [
    {
      "id": "rag-federated",
      "object": "model",
      "created": 1751234567,
      "owned_by": "federation"
    }
  ]
}
```

### 8.8 `GET /metrics`

Prometheus metrics endpoint. Returns plain-text metrics in Prometheus exposition format.

---

## 9. Access Control

### How It Works

1. **Auth enabled** (`FEDERATION_AUTH_ENABLED=true`):
    - `extract_user_groups()` reads the JWT from the `Authorization: Bearer <token>` header
    - Decodes the token using `FEDERATION_JWT_SECRET` and `FEDERATION_JWT_ALGORITHM`
    - Extracts groups from `payload.groups` and `payload.realm_access.roles`
    - Combines both lists into a single `user_groups` array

2. **Auth disabled** (default):
    - All users get the groups from `FEDERATION_DEFAULT_GROUPS` (default: `"admin"`)

3. **Silo access check:**
    - `SiloConfig.is_accessible_by(user_groups)` checks if the intersection of `user_groups` and `silo.access_groups` is
      non-empty
    - If `silo.access_groups` is empty, all users can access the silo

4. **Filtering:**
    - `registry.list_accessible(user_groups)` returns only silos the user can access
    - Inaccessible silos are excluded from all queries

### JWT Token Structure

The federation expects JWTs with the following claims:

```json
{
  "sub": "user123",
  "groups": ["admin", "engineering"],
  "realm_access": {
    "roles": ["viewer"]
  },
  "exp": 1751320000
}
```

Both `groups` (direct array) and `realm_access.roles` (Keycloak-style) are supported.

### Fallback: Unsigned Tokens

If `FEDERATION_JWT_SECRET` is empty but a token is provided:

- The token is decoded **without signature verification**
- Groups are extracted from the payload
- A warning is logged: `"No JWT secret configured — returning empty groups"`
- This is useful for development only — **never use in production**

### Access Control Example

```bash
# Silo config:
# hr silo: access_groups=["hr", "admin"]
# eng silo: access_groups=["engineering", "admin"]
# finance silo: access_groups=["finance", "admin"]

# User with groups ["hr"]:
# → Can access: hr
# → Cannot access: eng, finance

# User with groups ["admin"]:
# → Can access: hr, eng, finance (all)

# User with groups ["intern"]:
# → Can access: none (unless a silo has empty access_groups)
```

---

## 10. Generation Delegation

After merging chunks, the federation needs to generate a final answer. It uses a **three-tier fallback** strategy:

### Tier 1: Direct LLM (FEDERATION_LLM_ENDPOINT)

If `FEDERATION_LLM_ENDPOINT` is set, the federation generates the answer directly:

```
Federation ──→ Direct LLM (FEDERATION_LLM_ENDPOINT)
                POST /chat/completions
                {
                  "model": "${FEDERATION_LLM_MODEL}",
                  "messages": [
                    {"role": "system", "content": "You are a federated RAG assistant..."},
                    {"role": "user", "content": "Context:\n{merged_chunks}\n\nQuestion: {query}"}
                  ],
                  "temperature": 0.3
                }
```

**Use when:**

- You have a dedicated LLM for federation (avoids loading silo LLMs)
- You want consistent generation style across all silos
- You don't have a primary silo that should "own" answer generation

### Tier 2: Primary Silo Delegation

If no `FEDERATION_LLM_ENDPOINT` is set, the federation finds the **primary silo** (the one with `is_primary: true`) and
delegates generation to it:

```
Federation ──→ Primary Silo (/v1/chat/completions)
               {
                 "model": "rag-internal",
                 "messages": [
                   {"role": "system", "content": "You are a federated RAG assistant..."},
                   {"role": "user", "content": "Context from federated search:\n{merged_chunks}\n\nQuestion: {query}"}
                 ],
                 "temperature": 0.3
               }
```

The primary silo receives **all merged chunks** (not just its own) and generates a comprehensive answer. The primary
silo's `api_key` is used for authentication.

**Use when:**

- Your primary silo has the most capable LLM
- You want answers to be consistent with the primary silo's generation style
- You don't have a separate LLM endpoint for federation

### Tier 3: Fallback Content

If both direct LLM and primary silo delegation fail (or neither is configured), the federation returns a static fallback
message:

```
"Retrieved {N} chunks from {M} silos. Generation service is currently unavailable.
 Review the rag_sources below for relevant information."
```

The `rag_confidence` is set to `0.3` for fallback responses.

### Generation Flow Summary

```
                ┌──────────────────────┐
                │  Merged chunks ready  │
                └──────────┬───────────┘
                           │
                    ┌──────▼──────┐
                    │ LLM_ENDPOINT │
                    │    set?      │
                    └──┬───────┬───┘
                  Yes  │       │  No
           ┌───────────▼┐  ┌───▼───────────────┐
           │ Generate    │  │ Primary silo      │
           │ directly    │  │ configured?       │
           └──────┬──────┘  └───┬───────────┬───┘
                  │          Yes│           │No
                  │     ┌───────▼──┐   ┌────▼───────────┐
                  │     │ Delegate  │   │ Fallback static │
                  │     │ to primary│   │ message         │
                  │     └──────┬────┘   └────┬────────────┘
                  │            │             │
                  └────────────┼─────────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Return to client    │
                    │ with rag_confidence │
                    └─────────────────────┘
```

---

## 11. Circuit Breakers

Each silo has an independent circuit breaker to prevent cascading failures when a silo is unhealthy.

### State Machine

```
      ┌─────────┐
      │ CLOSED  │  ← Normal operation. All requests pass through.
      └────┬────┘
           │ failure_count >= threshold (5 consecutive failures)
           ▼
      ┌─────────┐
      │  OPEN   │  ← All requests are rejected. Silo is skipped.
      └────┬────┘
           │ recovery_timeout_s elapsed (30s)
           ▼
      ┌──────────┐
      │ HALF_OPEN│  ← Next request is a probe.
      └──┬────┬──┘
   success│    │failure
     ┌────▼┐ ┌─▼────┐
     │CLOSED│ │ OPEN │
     └─────┘ └──────┘
```

### How It Works in Practice

```
Request arrives
      │
      ▼
For each silo:
  breaker = get_breaker("federation_{silo.id}")
  if breaker.allow_request():
      → Query silo
      → On success: breaker.record_success()
      → On failure: breaker.record_failure()
  else:
      → Skip silo (circuit open)
      → Log: "Silo 'eng' skipped (circuit breaker open)"
```

### Configuration

| Parameter         | Env Variable                            | Default | Effect                                                  |
|-------------------|-----------------------------------------|---------|---------------------------------------------------------|
| Failure threshold | `FEDERATION_CIRCUIT_BREAKER_THRESHOLD`  | 5       | Number of consecutive failures before opening           |
| Recovery timeout  | `FEDERATION_CIRCUIT_BREAKER_RECOVERY_S` | 30      | Seconds in OPEN state before transitioning to HALF_OPEN |

### State Transitions

- **CLOSED → OPEN:** `failure_count` reaches threshold (5 consecutive failures)
- **OPEN → HALF_OPEN:** Recovery timeout elapsed (30s since opening)
- **HALF_OPEN → CLOSED:** First request in HALF_OPEN succeeds
- **HALF_OPEN → OPEN:** First request in HALF_OPEN fails
- **CLOSED → CLOSED:** `success_count` reaches threshold (5 consecutive successes) → resets `failure_count` to 0

### Monitoring Circuit Breakers

The `rag_federation_circuit_breaker_state` gauge reports the state per silo. Check the Prometheus `/metrics` endpoint:

```
rag_federation_circuit_breaker_state{silo="hr"} 0.0   # 0 = CLOSED
rag_federation_circuit_breaker_state{silo="eng"} 1.0  # 1 = OPEN
rag_federation_circuit_breaker_state{silo="fin"} 0.5  # 2 = HALF_OPEN
```

Alerts should fire when any silo enters OPEN state for more than 2 minutes.

---

## 12. Monitoring

### Prometheus Metrics

All metrics are exported at `GET /metrics` on the federation proxy (port 8001).

| Metric                                 | Type      | Labels           | Description                                                                                                        |
|----------------------------------------|-----------|------------------|--------------------------------------------------------------------------------------------------------------------|
| `rag_federation_requests_total`        | Counter   | `mode`, `status` | Total federation requests. `status`: `started`, `success`, `error`.                                                |
| `rag_federation_silo_requests_total`   | Counter   | `silo`, `status` | Per-silo request count. Tracked by `silo_client.py`.                                                               |
| `rag_federation_silo_latency_seconds`  | Histogram | `silo`           | Per-silo response latency. Buckets: 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0s.                                    |
| `rag_federation_total_latency_seconds` | Histogram | `mode`           | End-to-end federation latency (fan-out + merge + generation). Buckets: 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0s. |
| `rag_federation_merge_total_chunks`    | Histogram | —                | Distribution of chunk counts after merge. Buckets: 5, 10, 20, 30, 40, 50, 60, 80, 100.                             |
| `rag_federation_circuit_breaker_state` | Gauge     | `silo`           | Circuit breaker state: 0=CLOSED, 1=OPEN, 2=HALF_OPEN.                                                              |
| `rag_federation_silos_active`          | Gauge     | —                | Total number of configured silos at startup.                                                                       |

### Key Monitoring Queries (PromQL)

```promql
# Error rate by mode
rate(rag_federation_requests_total{status="error"}[5m]) /
rate(rag_federation_requests_total[5m])

# P99 total latency by mode
histogram_quantile(0.99,
  rate(rag_federation_total_latency_seconds_bucket[5m]))

# P95 per-silo latency
histogram_quantile(0.95,
  rate(rag_federation_silo_latency_seconds_bucket[5m]))

# Circuit breakers open
rag_federation_circuit_breaker_state == 1

# Average chunks per merge
rate(rag_federation_merge_total_chunks_sum[5m]) /
rate(rag_federation_merge_total_chunks_count[5m])

# Success rate (%)
100 * rate(rag_federation_requests_total{status="success"}[5m]) /
rate(rag_federation_requests_total[5m])
```

### Logging

The federation uses Python's standard `logging` module with logger name `"federation"`. Key log events:

| Event              | Level   | Message Pattern                                                                                |
|--------------------|---------|------------------------------------------------------------------------------------------------|
| Startup            | INFO    | `Federation started: {N} silos, mode={mode}`                                                   |
| Breaker opens      | WARNING | `Breaker 'federation_{silo}' → OPEN ({count} failures)`                                        |
| Breaker closes     | INFO    | `Breaker 'federation_{silo}' → CLOSED (half-open success)`                                     |
| Silo query failure | WARNING | `Silo '{id}' query failed: {error}`                                                            |
| Generation failure | WARNING | `Direct LLM generation failed: {error}` / `Generation via primary silo '{id}' failed: {error}` |
| Rate limiting      | WARNING | *(from middleware, if enabled)*                                                                |
| Shutdown           | INFO    | `Federation shutting down`                                                                     |

---

## 13. Deployment

### 13.1 Docker Compose

The recommended setup runs the federation proxy alongside your RAG silos:

```yaml
# docker-compose.federation.yml
version: "3.8"
services:
  federation:
    build:
      context: ..
      dockerfile: federation/Dockerfile
    ports:
      - "8001:8001"
    environment:
      - FEDERATION_MODE=merge
      - FEDERATION_INSTANCES_JSON='[
          {"id":"hr","name":"HR KB","proxy_url":"http://proxy:8000/v1","weight":1.0,"access_groups":["admin"],"is_primary":true},
          {"id":"eng","name":"Engineering","proxy_url":"http://rag-eng:8000/v1","weight":1.2,"access_groups":["admin","engineering"]}
        ]'
      - FEDERATION_MERGE_STRATEGY=weighted_rrf
      - FEDERATION_MERGE_K=60
      - FEDERATION_RRF_K=60
      - FEDERATION_PER_INSTANCE_TIMEOUT_S=10
      - FEDERATION_CIRCUIT_BREAKER_THRESHOLD=5
      - FEDERATION_CIRCUIT_BREAKER_RECOVERY_S=30
      - FEDERATION_LLM_ENDPOINT=http://llm-host:8000/v1
      - FEDERATION_LLM_MODEL=llama-3-70b
    depends_on:
      - proxy
    networks:
      - rag-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/v1/health/live"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
```

### 13.2 Kubernetes with Helm

**ConfigMap for silo configuration:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: federation-silos
  namespace: rag-system
data:
  silos.json: |
    [
      {
        "id": "eng",
        "name": "Engineering Wiki",
        "proxy_url": "http://rag-eng.rag-system.svc.cluster.local:8000/v1",
        "weight": 1.2,
        "access_groups": ["engineering", "admin"],
        "collections": ["eng_docs"],
        "api_key": "${ENG_API_KEY}",
        "timeout_s": 8,
        "is_primary": true
      },
      {
        "id": "hr",
        "name": "HR Knowledge Base",
        "proxy_url": "http://rag-hr.rag-system.svc.cluster.local:8000/v1",
        "weight": 1.0,
        "access_groups": ["hr", "admin"],
        "collections": ["hr_policies"],
        "api_key": "${HR_API_KEY}",
        "timeout_s": 10
      },
      {
        "id": "finance",
        "name": "Finance Documents",
        "proxy_url": "http://rag-fin.rag-system.svc.cluster.local:8000/v1",
        "weight": 0.8,
        "access_groups": ["finance", "admin"],
        "collections": ["finance_reports"],
        "api_key": "${FIN_API_KEY}",
        "timeout_s": 15
      }
    ]
```

**Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-federation
  namespace: rag-system
  labels:
    app: rag-federation
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rag-federation
  template:
    metadata:
      labels:
        app: rag-federation
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8001"
        prometheus.io/path: "/metrics"
    spec:
      containers:
      - name: federation
        image: rag-system/federation:v2.0.0
        ports:
        - containerPort: 8001
          name: http
        env:
        - name: FEDERATION_MODE
          value: "auto"
        - name: FEDERATION_INSTANCES_FILE
          value: "/etc/federation/silos.json"
        - name: FEDERATION_MERGE_STRATEGY
          value: "weighted_rrf"
        - name: FEDERATION_MERGE_K
          value: "60"
        - name: FEDERATION_RRF_K
          value: "60"
        - name: FEDERATION_PER_INSTANCE_TIMEOUT_S
          value: "10"
        - name: FEDERATION_CIRCUIT_BREAKER_THRESHOLD
          value: "5"
        - name: FEDERATION_CIRCUIT_BREAKER_RECOVERY_S
          value: "30"
        - name: FEDERATION_LLM_ENDPOINT
          value: "http://llm-service.rag-system.svc.cluster.local:8000/v1"
        - name: FEDERATION_LLM_MODEL
          value: "llama-3-70b"
        - name: FEDERATION_AUTH_ENABLED
          value: "true"
        - name: FEDERATION_JWT_SECRET
          valueFrom:
            secretKeyRef:
              name: federation-secrets
              key: jwt-secret
        volumeMounts:
        - name: silo-config
          mountPath: /etc/federation
          readOnly: true
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 2000m
            memory: 1Gi
        livenessProbe:
          httpGet:
            path: /v1/health/live
            port: 8001
          initialDelaySeconds: 10
          periodSeconds: 15
        readinessProbe:
          httpGet:
            path: /v1/health/ready
            port: 8001
          initialDelaySeconds: 5
          periodSeconds: 10
      volumes:
      - name: silo-config
        configMap:
          name: federation-silos
```

**Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: rag-federation
  namespace: rag-system
spec:
  selector:
    app: rag-federation
  ports:
  - port: 8001
    targetPort: 8001
    name: http
```

**Secrets:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: federation-secrets
  namespace: rag-system
type: Opaque
stringData:
  jwt-secret: "your-256-bit-secret-here-change-in-production"
```

### 13.3 Helm Values Snippet

```yaml
# values.yaml — federation section
federation:
  enabled: true
  replicas: 2
  image:
    repository: rag-system/federation
    tag: v2.0.0
  env:
    FEDERATION_MODE: auto
    FEDERATION_MERGE_STRATEGY: weighted_rrf
    FEDERATION_MERGE_K: "60"
    FEDERATION_RRF_K: "60"
    FEDERATION_PER_INSTANCE_TIMEOUT_S: "10"
    FEDERATION_CIRCUIT_BREAKER_THRESHOLD: "5"
    FEDERATION_CIRCUIT_BREAKER_RECOVERY_S: "30"
    FEDERATION_LLM_ENDPOINT: http://llm-service:8000/v1
    FEDERATION_LLM_MODEL: llama-3-70b
    FEDERATION_AUTH_ENABLED: "true"
  silos:
    - id: eng
      name: Engineering Wiki
      proxy_url: http://rag-eng:8000/v1
      weight: 1.2
      access_groups:
        - engineering
        - admin
      collections:
        - eng_docs
      api_key_secret: eng-api-key
      timeout_s: 8
      is_primary: true
    - id: hr
      name: HR Knowledge Base
      proxy_url: http://rag-hr:8000/v1
      weight: 1.0
      access_groups:
        - hr
        - admin
      collections:
        - hr_policies
      api_key_secret: hr-api-key
      timeout_s: 10
```

---

## 14. Troubleshooting

### 14.1 All Silos Return "No accessible silos for user"

**Symptom:** Response contains `"errors": ["No accessible silos for user"]` with zero chunks.

**Causes:**

- Auth is enabled (`FEDERATION_AUTH_ENABLED=true`) but no valid JWT token is provided
- User's JWT groups don't match any silo's `access_groups`
- `FEDERATION_DEFAULT_GROUPS` is set to a group that has no access

**Fix:**

1. Check the JWT token's groups: decode it at [jwt.io](https://jwt.io) and verify `groups` or `realm_access.roles`
   claims
2. Verify silo `access_groups` match the user's groups
3. If testing without auth, set `FEDERATION_AUTH_ENABLED=false` and `FEDERATION_DEFAULT_GROUPS=admin`
4. Check that at least one silo has `"access_groups": ["admin"]` or empty `"access_groups": []`

### 14.2 Specific Silo Always Skipped

**Symptom:** One silo consistently appears in `silos_skipped` in federation metadata.

**Causes:**

- Circuit breaker is OPEN for that silo (5+ consecutive failures)
- Silo's `access_groups` don't include the user's groups
- In `auto` mode, the query doesn't match any keywords for that silo

**Fix:**

1. Check circuit breaker state: look for `WARNING` log messages with `Breaker 'federation_{silo}' → OPEN`
2. Wait for recovery timeout (default 30s) or restart the federation service to reset breakers
3. Verify the silo is actually reachable: `curl http://silo-host:8000/v1/health`
4. Check access groups: `curl http://localhost:8001/v1/silos` to see which silos are accessible

### 14.3 High Federation Latency

**Symptom:** Total latency is significantly higher than individual silo latencies.

**Causes:**

- One slow silo is blocking the fan-out (total latency ≈ max of individual latencies)
- Generation step is slow (LLM inference)
- Network latency to silos is high

**Fix:**

1. Check `per_silo_latency_ms` in the federation metadata to identify the slow silo
2. Reduce `FEDERATION_PER_INSTANCE_TIMEOUT_S` to fail fast on slow silos
3. Lower `FEDERATION_MERGE_K` to reduce context size for generation
4. Consider using `auto` mode instead of `merge` to query fewer silos
5. Deploy silos closer to the federation layer (same cluster/region)

### 14.4 Duplicate Chunks in Results

**Symptom:** The same content appears multiple times in `rag_sources`.

**Causes:**

- Two silos contain the same document (e.g., both Eng and HR silos have the company handbook)
- SHA-256 deduplication didn't catch it due to slight text differences (formatting, metadata)

**Fix:**

- The built-in `deduplicate_chunks()` uses SHA-256 of `text + source_type + title`. If duplicates persist, the chunks
  differ in one of these fields
- Check silo configurations to ensure documents aren't indexed in multiple silos unintentionally
- Review the ETL pipeline for each silo to confirm data source overlap

### 14.5 Generation Returns Fallback Message

**Symptom:** Response contains "Retrieved N chunks from M silos. Generation service is currently unavailable."

**Causes:**

- `FEDERATION_LLM_ENDPOINT` is not set AND no silo has `is_primary: true`
- The direct LLM endpoint is unreachable
- The primary silo's LLM is down or the silo returned an error during generation
- `rag_skip_generation: true` was set in the request

**Fix:**

1. Check logs for: `"Direct LLM generation failed"` or `"Generation via primary silo 'X' failed"`
2. Verify `FEDERATION_LLM_ENDPOINT` is reachable: `curl $FEDERATION_LLM_ENDPOINT/models`
3. Ensure exactly one silo has `"is_primary": true`
4. Check the primary silo's health: `curl http://primary-silo:8000/v1/health`
5. If using delegation, verify `api_key` in the primary silo config is correct

### 14.6 ConfigError on Startup

**Symptom:** Federation fails to start with `ConfigError`.

**Common config errors:**

```
ConfigError: Invalid FEDERATION_INSTANCES_JSON: ...    # Malformed JSON
ConfigError: FEDERATION_INSTANCES_JSON must be a JSON array  # Object instead of array
ConfigError: Missing required field 'id' in silo config       # Missing required field
ConfigError: Missing required field 'name' in silo config     # Missing required field
ConfigError: Missing required field 'proxy_url' in silo config # Missing required field
ConfigError: Duplicate silo id: hr                            # Non-unique ID
ConfigError: Silo 'hr' weight must be > 0, got 0              # Invalid weight
ConfigError: Silo 'hr' proxy_url is empty                     # Empty URL
```

**Fix:**

1. Validate your JSON at [jsonlint.com](https://jsonlint.com)
2. Ensure each silo has `id`, `name`, and `proxy_url` fields
3. Ensure all silo IDs are unique
4. Ensure all weights are positive floats
5. If using `FEDERATION_INSTANCES_FILE`, check that the file exists and is readable

### 14.7 Auto Mode Routes to Wrong Silo

**Symptom:** A query about HR topics gets routed to the Engineering silo (or vice versa).

**Causes:**

- No keywords matched, so auto mode fell back to all silos
- The keyword map doesn't cover the user's query terms

**Fix:**

1. The current keyword map is hardcoded in `auto_router.py`. To customize:
    - Edit the `_KEYWORD_MAP` dictionary in `federation/app/auto_router.py`
    - Add your domain-specific keywords to the appropriate silo entry
    - Rebuild the Docker image
2. Use `strict` mode with `federation_silo` for explicit routing
3. Set `FEDERATION_AUTO_SLM_ENABLED=false` to disable keyword routing and always fan out

### 14.8 Health Check Endpoints

Use these for debugging:

```bash
# Is the federation process alive?
curl http://localhost:8001/v1/health/live
# → {"status": "ok"}

# Is the federation ready to serve requests?
curl http://localhost:8001/v1/health/ready
# → {"status": "ready", "silos": {"hr": {"name": "HR KB", "url": "http://..."}}}

# Full health with silo status
curl http://localhost:8001/v1/health
# → {"status": "healthy", "federation": {"mode": "auto", "total_silos": 3, ...}}

# Which silos can the current user access?
curl http://localhost:8001/v1/silos
# → {"silos": [{"id": "hr", "accessible": true}, ...]}

# Prometheus metrics
curl http://localhost:8001/metrics | grep federation
```

---

## Appendix A: Quick Reference Card

```bash
# ─── Start federation ───
cd federation && docker compose -f docker-compose.federation.yml up -d

# ─── Query federation ───
# Chat completion
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-federated","messages":[{"role":"user","content":"YOUR QUERY"}]}'

# Search only
curl -X POST http://localhost:8001/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"YOUR QUERY","federation_top_k":20}'

# Strict mode (single silo)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-federated","messages":[{"role":"user","content":"YOUR QUERY"}],"federation_mode":"strict","federation_silo":"hr"}'

# Skip generation (chunks only)
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag-federated","messages":[{"role":"user","content":"YOUR QUERY"}],"rag_skip_generation":true}'

# ─── Health ───
curl http://localhost:8001/v1/health
curl http://localhost:8001/v1/health/live
curl http://localhost:8001/v1/health/ready

# ─── Silos ───
curl http://localhost:8001/v1/silos
curl -H "Authorization: Bearer $JWT_TOKEN" http://localhost:8001/v1/silos

# ─── Metrics ───
curl http://localhost:8001/metrics | grep federation

# ─── Logs ───
docker compose -f docker-compose.federation.yml logs -f federation
```

## Appendix B: Environment Variable Quick Reference

```bash
# federation/.env — all available settings

# ─── Required ───
FEDERATION_MODE=auto                                   # auto | strict | merge
FEDERATION_INSTANCES_JSON='[{"id":"hr","name":"HR KB","proxy_url":"http://localhost:8000/v1"}]'

# ─── Optional: File-based config ───
# FEDERATION_INSTANCES_FILE=/etc/federation/silos.json  # Overrides FEDERATION_INSTANCES_JSON

# ─── Merge ───
FEDERATION_MERGE_STRATEGY=weighted_rrf                  # weighted_rrf | round_robin | top_per_instance
FEDERATION_MERGE_K=60                                   # Max chunks after merge
FEDERATION_RRF_K=60                                     # RRF smoothing constant

# ─── Timeouts ───
FEDERATION_TOTAL_TIMEOUT_S=30                           # Budgeted total timeout
FEDERATION_PER_INSTANCE_TIMEOUT_S=10                    # Per-silo request timeout

# ─── Circuit Breakers ───
FEDERATION_CIRCUIT_BREAKER_THRESHOLD=5                  # Failures before opening
FEDERATION_CIRCUIT_BREAKER_RECOVERY_S=30                # Recovery wait time

# ─── Generation ───
FEDERATION_LLM_ENDPOINT=http://llm-host:8000/v1         # Direct LLM endpoint
FEDERATION_LLM_MODEL=llama-3                            # Model name for direct LLM

# ─── Auto Routing ───
FEDERATION_AUTO_SLM_ENABLED=true                        # Enable keyword-based routing

# ─── Auth ───
FEDERATION_AUTH_ENABLED=false                           # Enable JWT auth
FEDERATION_JWT_SECRET=                                  # JWT signing secret
FEDERATION_JWT_ALGORITHM=HS256                          # JWT algorithm
FEDERATION_DEFAULT_GROUPS=admin                         # Default groups when auth is off
```
