# Federated RAG — Design Spec

**Status:** Proposed
**Date:** 2026-07-05
**Author:** Alexandr Narbaev
**Scope:** New `federation/` component for multi-instance RAG search

---

## 1. Overview

Federated RAG introduces a coordination layer that fans out retrieval queries to multiple independent RAG proxy instances (silos), aggregates results, and returns a unified response. Each silo is a self-contained RAG deployment with its own Qdrant, Neo4j, and LLM backend.

### 1.1 Motivation

- **Organizational silos:** HR, Engineering, Finance each maintain their own knowledge base
- **Privacy:** Cross-silo access must be controlled by RBAC
- **Scalability:** Each team owns their infrastructure independently
- **Deployment flexibility:** Silo configuration decided at install time

### 1.2 Non-Goals

- Write-path federation (indexing remains per-silo via ETL)
- Real-time sync between silos
- Cross-silo Neo4j graph merging
- Client-side federation SDK

---

## 2. Architecture

```
Client (OpenAI SDK / curl)
       │
       ▼
┌──────────────────────────────────────┐
│   Federated Proxy  (federation/)     │
│                                      │
│  • /v1/chat/completions             │
│  • /v1/search                        │
│  • /v1/models                        │
│  • /v1/health                        │
│  • /v1/silos                         │
│                                      │
│  Fan-out routing                    │
│  Cross-silo merge (weighted RRF)    │
│  Access policy enforcement          │
│  Per-instance circuit breakers      │
│  Prometheus metrics                  │
└──┬─────────┬─────────┬───────────────┘
   │         │         │
   ▼         ▼         ▼
┌──────┐ ┌──────┐ ┌──────┐
│Proxy A│ │Proxy B│ │Proxy C│    (each — full RAG proxy)
│Qdrant│ │Qdrant│ │Qdrant│
│ Neo4j│ │ Neo4j│ │ Neo4j│
└──────┘ └──────┘ └──────┘
  HR       Eng     Finance
```

### 2.1 Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| Federated Proxy as standalone component | Isolation from existing proxy; each silo remains autonomous |
| HTTP fan-out to silo proxies (not direct Qdrant) | Reuses existing retrieval+rerank pipeline per silo; silos can have different versions |
| Weighted RRF for cross-silo merge | Proven in single-instance Qdrant; weights reflect silo quality/relevance |
| Circuit breaker per silo | Reuses existing `circuit_breaker.py` pattern; prevents cascading failures |
| SLM-based auto-routing | Reduces unnecessary fan-out; classifies query intent → target silos |

---

## 3. Configuration

### 3.1 Environment Variables

```bash
# ── Federation mode ──
FEDERATION_MODE=auto                    # strict | merge | auto
FEDERATION_INSTANCES_JSON='[...]'       # JSON array of silo configs
# or:
FEDERATION_INSTANCES_FILE=/etc/rag/federation.json

# ── Merge strategy ──
FEDERATION_MERGE_STRATEGY=weighted_rrf  # weighted_rrf | round_robin | top_per_instance
FEDERATION_MERGE_K=60                   # Total chunks after merge
FEDERATION_RRF_K=60                     # RRF constant

# ── Timeouts ──
FEDERATION_TOTAL_TIMEOUT_S=30           # Hard deadline for full request
FEDERATION_PER_INSTANCE_TIMEOUT_S=10    # Per-silo timeout
FEDERATION_CIRCUIT_BREAKER_THRESHOLD=5  # Errors before opening breaker
FEDERATION_CIRCUIT_BREAKER_RECOVERY_S=30 # Seconds before half-open

# ── LLM for generation (optional: delegate to primary silo) ──
FEDERATION_LLM_ENDPOINT=http://llm.internal:8000/v1
FEDERATION_LLM_MODEL=llama-3
# If not set, delegate generation to primary silo

# ── SLM for auto-routing (reuses existing SLM infrastructure) ──
FEDERATION_AUTO_SLM_ENABLED=true
```

### 3.2 Silo Configuration Schema

```json
[
  {
    "id": "hr",
    "name": "HR Knowledge Base",
    "proxy_url": "http://rag-hr.internal:8000/v1",
    "api_key": "sk-hr-xxx",
    "weight": 1.0,
    "access_groups": ["hr", "admin"],
    "collections": ["hr_policies", "hr_onboarding"],
    "timeout_s": 10,
    "is_primary": false
  },
  {
    "id": "engineering",
    "name": "Engineering Wiki",
    "proxy_url": "http://rag-eng.internal:8000/v1",
    "api_key": "sk-eng-xxx",
    "weight": 1.2,
    "access_groups": ["engineering", "admin"],
    "collections": ["confluence", "gitlab", "jira"],
    "timeout_s": 10,
    "is_primary": true
  },
  {
    "id": "finance",
    "name": "Finance Docs",
    "proxy_url": "http://rag-fin.internal:8000/v1",
    "api_key": "sk-fin-xxx",
    "weight": 0.8,
    "access_groups": ["finance", "admin"],
    "collections": ["finance_reports", "finance_policies"],
    "timeout_s": 15,
    "is_primary": false
  }
]
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | str | Yes | Unique silo identifier |
| `name` | str | Yes | Human-readable display name |
| `proxy_url` | str | Yes | Base URL of the silo's RAG proxy |
| `api_key` | str | No | API key for auth to silo proxy |
| `weight` | float | Yes | Merge weight (0.0–2.0, default 1.0) |
| `access_groups` | [str] | Yes | User groups allowed to query this silo |
| `collections` | [str] | No | Informational: collections in this silo |
| `timeout_s` | int | No | Per-silo timeout override (default 10) |
| `is_primary` | bool | No | Used as generation target when delegating. Exactly one silo must be primary; if multiple, first wins with warning. If none, federation calls LLM directly. |

---

## 4. Data Model

### 4.1 Core Types

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SiloConfig:
    id: str
    name: str
    proxy_url: str
    weight: float = 1.0
    access_groups: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    api_key: Optional[str] = None
    timeout_s: int = 10
    is_primary: bool = False


@dataclass
class SiloSearchResult:
    silo_id: str
    silo_name: str
    chunks: list[dict]           # {id, text, score, source_type, title, version, ...}
    latency_ms: float
    error: Optional[str] = None
    partial: bool = False        # True if some searches failed


@dataclass
class FederatedSearchResult:
    query: str
    merged_chunks: list[dict]    # After cross-silo RRF + dedup + sort
    silo_results: list[SiloSearchResult]
    total_latency_ms: float
    errors: list[str]
    skipped_silos: list[str]     # Circuit-breaker-open silos


@dataclass
class FederationContext:
    mode: str                    # "strict" | "merge" | "auto"
    target_silos: list[str]      # Which silos to query
    merge_strategy: str          # "weighted_rrf" | "round_robin" | "top_per_instance"
    merge_k: int                 # Total chunks after merge
    rrf_k: int                   # RRF constant
    user_groups: list[str]       # From JWT
    cross_silo: bool             # True if query targets multiple silos (merge mode or auto with multi-domain intent)
```

---

## 5. Request Flow

### 5.1 POST /v1/chat/completions

```
REQ → Auth(JWT) → ResolveSilos(mode, user_groups)
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
    Silo A       Silo B       Silo C
   (fan-out, asyncio.gather, circuit breaker per silo)
        │            │            │
        └────────────┼────────────┘
                     ▼
            Merge (weighted RRF)
                     │
                     ▼
            Generate (delegate to primary silo OR call LLM directly)
                     │
                     ▼
            Response → Client
```

### 5.2 Silo Fan-Out Protocol

Each silo is queried via HTTP POST to `{proxy_url}/chat/completions`:

```json
{
  "model": "rag-internal",
  "messages": [{"role": "user", "content": "original query"}],
  "rag_skip_generation": true,
  "rag_top_k": 30,
  "rag_return_chunks": true,
  "temperature": 0,
  "stream": false
}
```

The silo proxy must support `rag_skip_generation=true` — it performs retrieval, reranking, and returns chunks without calling the LLM. Response format:

```json
{
  "rag_sources": [
    {
      "chunk_id": "sha256:xxx",
      "text": "...",
      "source": "confluence",
      "title": "...",
      "version": "2.1",
      "relevance": 0.94,
      "text_preview": "..."
    }
  ],
  "rag_metadata": {
    "total_retrieved": 30,
    "total_reranked": 10,
    "latency_ms": 280
  }
}
```

### 5.3 Merge Strategies

#### weighted_rrf (default)

```
score(chunk) = Σ (weight_silo / (rrf_k + rank_in_silo))

Where:
  - weight_silo: config weight (0.8–1.2)
  - rrf_k: FEDERATION_RRF_K (default 60)
  - rank_in_silo: 0-based rank from silo's reranker

After scoring:
  1. Deduplicate by SHA-256(chunk text + source_type + title)
  2. Sort by score descending
  3. Take top FEDERATION_MERGE_K
```

#### round_robin

```
interleaved = []
for i in range(max_chunks_per_silo):
    for silo in active_silos:
        interleaved.append(silo.chunks[i])

Take top FEDERATION_MERGE_K (dedup first)
```

#### top_per_instance

```
Each silo contributes min(MERGE_K / N, len(silo.chunks)) top chunks.
Merge, dedup, take top MERGE_K.
```

### 5.4 Generation

Two modes, configurable:

**Mode A: Delegate to primary silo** (default when no `FEDERATION_LLM_ENDPOINT`)

```
POST {primary_silo.proxy_url}/chat/completions
{
  "messages": [...],
  "rag_prebuilt_context": "<assembled context from merge>",
  "rag_skip_retrieval": true,
  "temperature": 0.7,
  "stream": false
}
```

**Mode B: Call LLM directly**

```
POST {FEDERATION_LLM_ENDPOINT}/chat/completions
{
  "model": "{FEDERATION_LLM_MODEL}",
  "messages": [
    {"role": "system", "content": "You are a RAG assistant. Answer using only the provided context."},
    {"role": "user", "content": "Context:\n{assembled_context}\n\nQuery: {query}"}
  ],
  "temperature": 0.7,
  "stream": false
}
```

---

## 6. Isolation Modes

### 6.1 `strict`

- Client MUST specify `federation_silo` in request
- User must belong to `silo.access_groups`
- Single silo search; no merge
- 403 if access denied

### 6.2 `merge`

- No silo parameter needed
- Fan-out to all silos where `user.groups ∩ silo.access_groups ≠ ∅`
- Weighted RRF merge across all eligible silos
- Each source chunk tagged with `silo_id` and `silo_name`

### 6.3 `auto`

- SLM classifies query → intent → target silos
- If confidence > threshold: search only matching silos
- If low confidence or cross-domain: fan-out to all eligible, merge
- Reduces unnecessary fan-out for clearly-scoped queries

### 6.4 RBAC Matrix

| Role | strict | merge | auto |
|------|--------|-------|------|
| `admin` | Any silo | All silos | All silos |
| `expert` | Any authorized | All eligible | Auto-routed |
| `user` | Any authorized | All eligible | Auto-routed |
| `read-only` | Any authorized | All eligible | Auto-routed |

*Authorization*: `user.groups ∩ silo.access_groups ≠ ∅`. In `strict` mode, the user additionally specifies which silo to query.

---

## 7. Error Handling & Resilience

### 7.1 Circuit Breaker (per silo)

Reuses existing `proxy/app/circuit_breaker.py` pattern:

```python
breaker = get_breaker(f"federation_{silo_id}")
# CLOSED → OPEN after FEDERATION_CIRCUIT_BREAKER_THRESHOLD errors
# HALF_OPEN after FEDERATION_CIRCUIT_BREAKER_RECOVERY_S
# OPEN → silo skipped, logged, metric emitted
```

### 7.2 Timeouts

- Per-silo: `silo.timeout_s` (default 10s)
- Total: `FEDERATION_TOTAL_TIMEOUT_S` (default 30s)
- Single retry on timeout or 5xx

### 7.3 Graceful Degradation

| Scenario | Behavior | HTTP Status |
|----------|----------|-------------|
| All silos down | Error response with diagnostics | 503 |
| Some silos down | Partial results + warnings | 200 |
| Circuit breaker open | Silo skipped, rest proceed | 200 |
| Merge returns 0 chunks | "I don't know" + empty sources | 200 |
| Generation fails | Return chunks only (search mode) | 200 |
| Total timeout hit | Return whatever was collected | 200 or 504 |

---

## 8. API Contract

### 8.1 Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/chat/completions` | Federated RAG query + generation |
| `POST` | `/v1/search` | Search-only (no generation) |
| `GET` | `/v1/models` | Aggregated model list |
| `GET` | `/v1/health` | Federation + per-silo health |
| `GET` | `/v1/health/live` | Liveness probe |
| `GET` | `/v1/health/ready` | Readiness probe |
| `GET` | `/v1/silos` | Available silos (RBAC-filtered) |
| `GET` | `/metrics` | Prometheus metrics |

### 8.2 Request Extensions (on /v1/chat/completions)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `federation_silo` | str | null | Explicit silo (strict mode) |
| `federation_mode` | str | config | Override mode per request |
| `federation_top_k` | int | 60 | Chunks after merge |
| `federation_merge_strategy` | str | config | Merge strategy override |

### 8.3 Response Extensions

```json
{
  "rag_sources": [{
    "chunk_id": "sha256:xxx",
    "silo_id": "hr",
    "silo_name": "HR Knowledge Base",
    "relevance": 0.94,
    "...": "..."
  }],
  "federation": {
    "mode": "auto",
    "silos_queried": ["hr", "engineering"],
    "silos_skipped": ["finance"],
    "cross_silo": false,
    "total_latency_ms": 340,
    "per_silo_latency_ms": {"hr": 280, "engineering": 310},
    "warnings": []
  }
}
```

---

## 9. Prometheus Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rag_federation_requests_total` | Counter | mode, status | Total federation requests |
| `rag_federation_silo_requests_total` | Counter | silo, status | Per-silo requests |
| `rag_federation_silo_latency_seconds` | Histogram | silo | Per-silo latency |
| `rag_federation_merge_total_chunks` | Histogram | — | Chunks after merge |
| `rag_federation_circuit_breaker_state` | Gauge | silo | 0=CLOSED, 1=OPEN, 2=HALF_OPEN |
| `rag_federation_silos_active` | Gauge | — | Number of healthy silos |
| `rag_federation_total_latency_seconds` | Histogram | mode | End-to-end latency |

---

## 10. File Structure

```
rag-system/
├── federation/                        # NEW: Federated proxy
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI entry point (7 endpoints)
│   │   ├── config.py                  # Federation configuration
│   │   ├── models.py                  # Dataclasses: SiloConfig, FederatedSearchResult, etc.
│   │   ├── silo_registry.py           # Load & validate silo configs
│   │   ├── router.py                  # Fan-out orchestration
│   │   ├── merger.py                  # RRF/round-robin/top-per-instance merge
│   │   ├── auth.py                    # JWT auth + RBAC gate per silo
│   │   ├── auto_router.py             # SLM-based query → silo routing
│   │   ├── silo_client.py             # HTTP client to silo proxies
│   │   ├── circuit_breaker.py         # Reuses proxy/app/circuit_breaker.py pattern
│   │   ├── metrics.py                 # Prometheus metrics
│   │   └── exceptions.py             # FederationError hierarchy
│   ├── tests/
│   │   ├── test_merger.py
│   │   ├── test_router.py
│   │   ├── test_silo_client.py
│   │   ├── test_auth.py
│   │   ├── test_auto_router.py
│   │   └── test_integration.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── proxy/                             # Existing proxy (unchanged)
│   └── app/
│       └── main.py                    # ADD: rag_skip_generation + rag_return_chunks support
├── docs/
│   └── superpowers/specs/
│       └── 2026-07-05-federated-rag-design.md  # This document
```

---

## 11. Changes to Existing Code

### 11.1 proxy/app/main.py

Add support for `rag_skip_generation` and `rag_return_chunks` in `/v1/chat/completions`:

```python
# In process_rag_query(), after retrieval + rerank:
if request.rag_skip_generation:
    return {
        "rag_sources": [...],
        "rag_metadata": {...}
    }
# else: proceed to LLM generation as before
```

This is a backward-compatible extension — existing clients are unaffected.

### 11.2 proxy/app/circuit_breaker.py

No changes needed. Federation uses the same `get_breaker()` pattern with prefixed names (`federation_{silo_id}`).

---

## 12. Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | Merger (RRF math, dedup) | Pure function tests |
| Unit | Silo registry (config parse, validation) | Pydantic/JSON tests |
| Unit | Auth gate (RBAC matrix) | Table-driven tests |
| Unit | Auto-router (SLM classification) | Mock SLM, test intent→silo mapping |
| Integration | Fan-out orchestration | Mock silo HTTP responses via httpx |
| Integration | Circuit breaker state transitions | Deterministic error injection |
| Integration | Graceful degradation | All-silos-down, partial-failure |
| E2E | Full federation flow | Testcontainers: federation + 2 mock silos |

---

## 13. Rollout Plan

### Phase 1 — Core Federation (Week 1–2)
- `federation/` project scaffold (FastAPI, config, models)
- Silo registry with JSON config loading
- `silo_client.py` — HTTP fan-out with httpx
- `merger.py` — weighted RRF + dedup
- `router.py` — orchestration glue
- `POST /v1/chat/completions` (merge mode only)
- `GET /v1/health` with per-silo status
- Unit tests for merger, silo client, registry

### Phase 2 — Resilience & Modes (Week 3)
- Circuit breaker per silo
- Timeout + retry logic
- `strict` mode
- `POST /v1/search`
- `GET /v1/models`, `GET /v1/silos`
- Prometheus metrics
- Graceful degradation tests

### Phase 3 — Auto-Routing (Week 4)
- `auto_router.py` with SLM classification
- `auto` mode
- Integration tests with mock silos

### Phase 4 — Proxy Changes & E2E (Week 5)
- Add `rag_skip_generation` + `rag_return_chunks` to proxy
- E2E tests with Testcontainers
- Dockerfile, docker-compose integration
- Documentation

---

## 14. Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Silo proxy doesn't support `rag_skip_generation` | Medium | High | Add endpoint to proxy in Phase 4; fallback: parse full response |
| RRF merge degrades result quality vs single-silo | Low | Medium | A/B test merge strategies; keep `strict` mode as baseline |
| SLM misrouting in `auto` mode | Medium | Low | Fallback to `merge` mode on low confidence |
| Latency: N silos × 10s timeout = slow | Low | Medium | Per-silo timeout configurable; `auto` mode reduces fan-out |
| Circuit breaker false positives | Low | Low | HALF_OPEN recovery with gradual ramp-up |

---

## 15. Status History

- **2026-07-05** — Proposed. Design spec written after architecture review.
