# RAG System — Unified Requirements & Sprint Plan S5-2026

**Status:** Draft  
**Date:** 2026-07-17  
**Author:** Product Manager & Business Analyst  
**Previous sprint:** [S4-2026](sprint-plan-2026-s4.md) — Complete  
**Input:** Cross-team research gap analysis (R1–R13)

---

## Executive Summary

Three parallel research teams identified 12 requirement gaps across the RAG system, spanning critical functionality blocks through performance optimization. This document synthesizes all findings into a unified FR catalog, NFR catalog, and a 5-wave sprint plan for S5-2026.

**Scope:** 24 total items — 12 CRITICAL, 12 HIGH — organized into 5 waves over ~10 weeks.  
**Target:** Resolve all CRITICAL items. Address HIGH items based on team velocity.

---

## 1. Functional Requirements

### FR-01: Knowledge Status Flag in API Response
**Source:** R6-Knowledge | **Priority:** CRITICAL | **Estimate:** S (4h)

The chat completion response MUST include a structured `rag_knowledge_status` field indicating the quality and completeness of the knowledge used to generate the answer.

**Acceptance Criteria:**
- [ ] `rag_knowledge_status` is present in every `/v1/chat/completions` response (streaming and non-streaming)
- [ ] The field contains at minimum: `status` (enum: `sufficient`, `partial`, `insufficient`, `absent`), `chunks_found` (int), `chunks_used` (int), `confidence_threshold_met` (bool)
- [ ] When `status` is `insufficient` or `absent`, the response body signals this clearly to the client
- [ ] The field is documented in the OpenAPI spec
- [ ] Tests verify: sufficient retrieval, empty retrieval, partial retrieval, edge cases

**Files to Modify:**
```
proxy/app/api/chat.py                  — Populate rag_knowledge_status in response
proxy/app/core/retrieval.py            — Expose retrieval-quality metadata
proxy/app/core/context/builder.py      — Track chunks_found vs chunks_used
```

---

### FR-02: Conversational Context Management
**Source:** R13-Conversation | **Priority:** CRITICAL | **Estimate:** M (12h)

The chat endpoint MUST accumulate conversational context across a multi-turn session and use it to improve retrieval relevance and answer coherence.

**Acceptance Criteria:**
- [ ] `ConversationMemory` class is wired into the `/v1/chat/completions` handler
- [ ] Messages from the same `session_id` are accumulated and passed to the retriever as context
- [ ] Previous Q&A pairs in the session influence query expansion (e.g., pronoun resolution, topic tracking)
- [ ] Session context is bounded (last N turns or token cap) to prevent context overflow
- [ ] Session expires after configurable TTL (default: 30 min)
- [ ] Redis-backed session storage when Redis is available; in-memory fallback otherwise
- [ ] Tests verify: multi-turn context accumulation, session expiration, context bounding

**Files to Modify:**
```
proxy/app/api/chat.py                  — Pass session_id, wire ConversationMemory
proxy/app/core/query_enhancer.py       — Use conversation context for query expansion
proxy/app/shared/cache.py              — Session storage (Redis + in-memory fallback)
```

---

### FR-03: Clarifying Questions When Knowledge Insufficient
**Source:** R13-Conversation | **Priority:** CRITICAL | **Estimate:** M (8h)

When the system determines that available knowledge is insufficient to answer a query, it MUST generate clarifying questions rather than producing a low-confidence or hallucinated answer.

**Acceptance Criteria:**
- [ ] When `rag_knowledge_status.status` is `insufficient` or `absent`, the LLM is prompted to generate clarifying questions
- [ ] Clarifying questions are specific to the query topic (not generic fallbacks)
- [ ] The response container includes `"clarifying": true` and lists 1–3 specific questions
- [ ] A configurable threshold controls when clarification mode activates (based on confidence score)
- [ ] The user can respond to clarifying questions in the same session context
- [ ] Tests verify: low-confidence triggering, sufficient-knowledge passthrough, question specificity

**Files to Modify:**
```
proxy/app/api/chat.py                  — Clarification mode in response builder
proxy/app/core/confidence.py           — Clarification threshold configuration
proxy/app/llm/router.py                — Clarifying-question prompt template
```

---

### FR-04: Post-Indexing Data Cleanup Pipeline
**Source:** R8-ETL | **Priority:** CRITICAL | **Estimate:** M (16h)

The ETL pipeline MUST clean up raw extracts, intermediate chunks, and obsolete vector data after successful indexing. WAL state MUST be persisted to survive container restarts.

**Acceptance Criteria:**
- [ ] A cleanup stage executes after successful Qdrant indexing, removing:
  - Raw extract files (text already stored in Qdrant)
  - Intermediate chunk artifacts
  - Cold storage artifacts older than `RETENTION_DAYS`
- [ ] Cleanup is configurable: `ETL_CLEANUP_ENABLED`, `ETL_CLEANUP_RETENTION_DAYS`, `ETL_CLEANUP_RAW_EXTRACTS`
- [ ] WAL state is persisted to a durable volume (PVC or host path), not ephemeral container storage
- [ ] WAL includes checkpoint snapshots so a restarted ETL resumes from the last checkpoint
- [ ] Dry-run mode (`--dry-run-cleanup`) reports what would be deleted without deleting
- [ ] Tests verify: cleanup after successful index, WAL resume after restart, dry-run reporting

**Files to Modify:**
```
etl/indexer/wal_manager.py             — Durable WAL persistence, checkpoint snapshots
etl/scheduler/run_etl.py               — Cleanup stage in pipeline
etl/config/etl_config.yaml             — Cleanup configuration
```

---

### FR-05: OCR Pipeline for Scanned Documents
**Source:** R10-Multimodal | **Priority:** CRITICAL | **Estimate:** HIGH (24h)

The ETL pipeline MUST extract text from scanned documents (PDFs, images) using an OCR engine, enabling retrieval over scanned content.

**Acceptance Criteria:**
- [ ] Tesseract OCR engine is integrated into the document extraction pipeline
- [ ] PDF pages that yield no text from direct extraction fall through to OCR automatically
- [ ] Supported image formats: PNG, JPEG, TIFF, BMP (both standalone and embedded in PDFs)
- [ ] OCR language is configurable via `OCR_LANGUAGE` environment variable (default: `eng+rus`)
- [ ] OCR results are merged with extracted text and chunked together
- [ ] OCR processing is logged with page-level statistics (pages scanned, chars extracted)
- [ ] Performance: a 100-page scanned PDF processes within 5 minutes on CPU
- [ ] Tests verify: scanned PDF extraction, embedded image OCR, language fallback

**Files to Modify:**
```
etl/extractors/docs.py                  — OCR fallback for PDF pages
etl/requirements_etl.txt                — Add pytesseract, pdf2image
```

---

### FR-06: Image Embedding Pipeline
**Source:** R10-Multimodal | **Priority:** CRITICAL | **Estimate:** HIGH (20h)

The image embedding module MUST produce meaningful vector representations for images found in documents, rather than returning empty placeholder vectors.

**Acceptance Criteria:**
- [ ] A CLIP-based (or equivalent) vision model generates embeddings for extracted images
- [ ] Image embeddings are stored in Qdrant alongside text chunks with `content_type: "image"`
- [ ] Images are associated with their parent document via `parent_doc_id`
- [ ] Image descriptions (caption) are generated by the vision model and stored as metadata
- [ ] Image retrieval is supported in hybrid search when `rag_include_images` is set
- [ ] The vision model is pre-downloaded for air-gapped environments
- [ ] Tests verify: image embedding generation, Qdrant storage, hybrid search with images, caption quality

**Files to Modify:**
```
etl/indexer/qdrant_hybrid.py            — Store image embeddings with content_type
etl/extractors/docs.py                  — Extract embedded images from PDFs
proxy/app/core/retrieval.py             — Image content type filter
```

---

### FR-07: User Feedback Submission
**Source:** R11-Feedback | **Priority:** CRITICAL | **Estimate:** M (12h)

All authenticated users MUST be able to submit feedback on RAG responses, not just experts.

**Acceptance Criteria:**
- [ ] `/v1/feedback` endpoint accepts submissions from any authenticated user (not just `expert` role)
- [ ] Feedback includes: rating (positive/negative), optional correction text, `rag_feedback_id` reference
- [ ] A new `feedback_dimension: "retrieval_quality"` is supported alongside existing dimensions
- [ ] Users see their own feedback history via `GET /v1/feedback?user_id=self`
- [ ] Abuse prevention: rate limit of 100 feedback submissions per user per hour
- [ ] Tests verify: regular user submission, expert submission, retrieval-quality dimension, rate limiting

**Files to Modify:**
```
proxy/app/api/feedback.py               — Relax role check, add retrieval_quality dimension
proxy/app/auth/rbac.py                  — Add feedback:submit permission for all roles
proxy/app/shared/rate_limiter.py         — Feedback-specific rate limit
```

---

### FR-08: Feedback Review & Moderation Workflow
**Source:** R11-Feedback | **Priority:** CRITICAL | **Estimate:** M (12h)

Administrators and experts MUST have tools to review, moderate, and act on user-submitted feedback.

**Acceptance Criteria:**
- [ ] `GET /v1/admin/feedback` returns paginated, filterable feedback list (admin/expert only)
- [ ] Filters: by status (pending/reviewed/dismissed), by rating, by dimension, by date range
- [ ] `POST /v1/admin/feedback/{id}/review` marks feedback as reviewed with moderator notes
- [ ] `POST /v1/admin/feedback/{id}/dismiss` dismisses feedback with reason
- [ ] Reviewed feedback with corrections can trigger self-enrichment (optional flag)
- [ ] Moderation actions are audit-logged
- [ ] Tests verify: list/filter/review/dismiss workflows, audit trail, self-enrichment trigger

**Files to Modify:**
```
proxy/app/api/admin.py                  — Feedback management endpoints
proxy/app/core/hitl.py                  — Moderation state machine
proxy/app/core/enricher.py              — Self-enrichment from moderated feedback
```

---

### FR-09: Stale Document Detection
**Source:** R12-Stale | **Priority:** CRITICAL | **Estimate:** M (12h)

The system MUST detect documents that are likely outdated and flag them for review or reindexing.

**Acceptance Criteria:**
- [ ] A metadata field `last_verified_at` is stored per document in Qdrant
- [ ] A scheduled job scans documents where `last_verified_at` is older than `STALE_THRESHOLD_DAYS` (configurable, default: 90)
- [ ] Stale documents are flagged with `stale: true` in metadata (visible in retrieval results)
- [ ] When a stale document is retrieved, the response includes a `rag_stale_sources` field listing potentially outdated sources
- [ ] A `POST /v1/admin/stale/report` endpoint returns a report of stale documents grouped by source
- [ ] Sources with live APIs (Confluence, Jira) can be checked for updated versions
- [ ] Tests verify: stale detection job, response flagging, report generation, live-source version check

**Files to Modify:**
```
etl/scheduler/run_etl.py                — Stale detection scheduled job
proxy/app/core/live_sources.py          — Live version check for Confluence/Jira
proxy/app/core/retrieval.py             — Stale flag in retrieval results
proxy/app/api/admin.py                  — Stale report endpoint
```

---

### FR-10: Automated Reindexing Triggers
**Source:** R12-Stale | **Priority:** CRITICAL | **Estimate:** M (12h)

Stale or changed documents MUST be automatically reindexed without manual intervention.

**Acceptance Criteria:**
- [ ] When a live source check identifies an updated document version, a reindexing job is queued
- [ ] Reindexing preserves `feedback_count`, `positive_feedback`, and user-contributed corrections from the old version
- [ ] Old vector entries are removed after successful reindex (no duplicates)
- [ ] A webhook endpoint `POST /v1/admin/reindex/trigger` accepts external reindexing signals (e.g., from CI/CD)
- [ ] Reindexing job status is trackable via `GET /v1/admin/reindex/status/{job_id}`
- [ ] Failed reindexing jobs retry up to 3 times with exponential backoff
- [ ] Tests verify: live-source trigger, webhook trigger, feedback preservation, dedup after reindex, retry logic

**Files to Modify:**
```
etl/scheduler/run_etl.py                — Reindex job queue and orchestrator
proxy/app/api/admin.py                  — Reindex trigger and status endpoints
etl/indexer/qdrant_hybrid.py            — Preserve metadata during reindex
```

---

### FR-11: Runtime Configuration Management API
**Source:** R9-Admin | **Priority:** HIGH | **Estimate:** M (12h)

Administrators MUST be able to view and modify system configuration at runtime without restarting the proxy.

**Acceptance Criteria:**
- [ ] `GET /v1/admin/config` returns all non-secret configuration values
- [ ] `PATCH /v1/admin/config` updates specified configuration values
- [ ] Changes are validated (type checking, range checking) before application
- [ ] Hot-reloadable settings take effect immediately; others require a restart (clearly documented)
- [ ] Configuration changes are audit-logged with timestamp and admin identity
- [ ] Critical settings (LLM endpoint, model name, Qdrant host) require confirmation
- [ ] Tests verify: read/write/validate cycle, audit trail, restart-required notification

**Files to Modify:**
```
proxy/app/api/admin.py                  — Config endpoints
proxy/app/shared/config.py              — Runtime config override mechanism
proxy/app/shared/audit.py               — Config change audit events
```

---

### FR-12: Usage Analytics Endpoint
**Source:** R9-Admin | **Priority:** HIGH | **Estimate:** M (8h)

Administrators MUST have access to aggregated usage analytics to monitor system health and adoption.

**Acceptance Criteria:**
- [ ] `GET /v1/admin/analytics` returns time-series usage data with configurable window (24h/7d/30d)
- [ ] Metrics include: total requests, unique users, avg/p50/p95/p99 latency, cache hit rate, feedback ratio
- [ ] Metrics include: top queries, top sources, retrieval-quality distribution, confidence-score distribution
- [ ] Data is sourced from Prometheus counters (when available) with JSON aggregation fallback
- [ ] Response is JSON with a `summary` block and `time_series` array
- [ ] Tests verify: metric aggregation, time window filtering, Prometheus vs fallback

**Files to Modify:**
```
proxy/app/api/admin.py                  — Analytics endpoint
proxy/app/shared/metrics.py             — Metric aggregation queries
proxy/app/shared/cache.py               — Analytics caching (5-min TTL)
```

---

### FR-13: Data Quality Dashboard
**Source:** R9-Admin | **Priority:** HIGH | **Estimate:** M (10h)

A programmatic API MUST expose data quality metrics so the Streamlit dashboard can render quality visualizations.

**Acceptance Criteria:**
- [ ] `GET /v1/admin/data-quality` returns aggregated quality metrics per source
- [ ] Metrics: documents indexed, stale count, avg chunks per doc, feedback score, last index time
- [ ] Metrics: chunk size distribution (histogram), content type breakdown
- [ ] Response includes per-source breakdown and overall summary
- [ ] Compatible with Streamlit dashboard data model (JSON format)
- [ ] Tests verify: metric accuracy, source grouping, histogram generation

**Files to Modify:**
```
proxy/app/api/admin.py                  — Data quality endpoint
proxy/app/core/retrieval.py             — Qdrant count/facet queries
dashboard/app.py                        — Consume data-quality API
```

---

### FR-14: Collection-Level ACL in Qdrant
**Source:** R7-RBAC | **Priority:** HIGH | **Estimate:** M (12h)

RBAC access restrictions MUST be enforced at the Qdrant query level, not just at the API level, so that unauthorized documents are never retrieved.

**Acceptance Criteria:**
- [ ] Qdrant queries include a `must` filter with the user's permitted collections/access groups
- [ ] The access filter is derived from the user's JWT roles and applied transparently in `retrieval.py`
- [ ] Users without any permitted collections receive empty results (not 403) with `rag_knowledge_status: absent`
- [ ] Collections are assigned access labels via ETL metadata (`access_groups: ["engineering", "finance"]`)
- [ ] The access filter works with both dense and sparse vector search
- [ ] Tests verify: restricted user sees only permitted content, unrestricted user sees all, no-collection user sees empty

**Files to Modify:**
```
proxy/app/core/retrieval.py             — Apply access filter to Qdrant queries
proxy/app/auth/rbac.py                  — JWT-to-access-group mapping
etl/indexer/qdrant_hybrid.py            — Store access_groups in payload
```

---

### FR-15: Expert Knowledge Base Management Endpoints
**Source:** R7-RBAC | **Priority:** HIGH | **Estimate:** M (8h)

Experts MUST have API endpoints to manage knowledge base content: view indexed documents, trigger partial reindexes, and review document metadata.

**Acceptance Criteria:**
- [ ] `GET /v1/expert/documents` lists indexed documents with metadata (source, date, status, feedback)
- [ ] `POST /v1/expert/documents/{id}/reindex` triggers reindex of a specific document
- [ ] `POST /v1/expert/documents/{id}/flag` flags a document for review with reason
- [ ] `GET /v1/expert/documents/{id}/chunks` lists all chunks for a document
- [ ] All expert endpoints require `expert` or `admin` role
- [ ] Tests verify: RBAC enforcement, document listing, single-document reindex, chunk listing

**Files to Modify:**
```
proxy/app/api/admin.py                  — Expert KB management endpoints
proxy/app/auth/rbac.py                  — Expert role permissions
```

---

### FR-16: ETL Kubernetes & Unified Deployment Manifests
**Source:** R1-Deploy | **Priority:** HIGH | **Estimate:** M (12h)

The ETL component MUST be deployable via Kubernetes Helm chart and Docker Compose. A unified distributed deployment MUST be documented and tested.

**Acceptance Criteria:**
- [ ] ETL is added to the Helm chart as an optional component (`etl.enabled: true`)
- [ ] ETL Helm values include: image, WAL PVC, config mount, cron schedule, resource limits
- [ ] ETL has a `docker-compose.etl.yml` that integrates with the shared network
- [ ] A unified `docker-compose.distributed.yml` is created for multi-machine deployment
- [ ] OpenWebUI is added to the Helm chart (was missing)
- [ ] Deployment documentation covers both single-machine and distributed scenarios
- [ ] Tests verify: Helm template renders correctly, compose files start services

**Files to Modify:**
```
deploy/k8s/helm/rag-system/templates/etl-deployment.yaml
deploy/k8s/helm/rag-system/values.yaml
proxy/docker-compose.yml                — Add ETL service
deploy/docker/docker-compose.distributed.yml  (NEW)
etl/Dockerfile.etl
```

---

### FR-17: Qdrant Scalar Quantization
**Source:** R3-Performance | **Priority:** HIGH | **Estimate:** S (4h)

Qdrant MUST use scalar quantization to reduce memory footprint and improve query throughput.

**Acceptance Criteria:**
- [ ] Qdrant collections are created with `quantization: ScalarQuantization` (default in `init_collections.py`)
- [ ] Quantization type is configurable: `SCALAR` (default), `PRODUCT`, `BINARY`, or `NONE`
- [ ] Existing collections can be migrated to quantization via `recreate_on_quantization_change` flag
- [ ] Quantization reduces memory usage by at least 50% (benchmark required)
- [ ] Retrieval quality (MRR) does not degrade by more than 2% with quantization enabled
- [ ] Tests verify: collection creation with quantization, migration, quality regression gate

**Files to Modify:**
```
scripts/init_collections.py             — Quantization config on collection creation
etl/indexer/qdrant_hybrid.py            — Quantization during indexing
proxy/app/shared/config.py              — QUANTIZATION_TYPE setting
```

---

### FR-18: Qdrant gRPC Client
**Source:** R3-Performance | **Priority:** HIGH | **Estimate:** M (8h)

The Qdrant client MUST use gRPC protocol for lower latency and higher throughput compared to HTTP.

**Acceptance Criteria:**
- [ ] `QdrantClient` is initialized with `prefer_grpc=True` when `QDRANT_GRPC_PORT` is configured
- [ ] gRPC is the default when both HTTP and gRPC ports are available
- [ ] HTTP fallback is seamless when gRPC is unavailable (graceful degradation)
- [ ] Connection pooling is enabled for gRPC (min 4, max 16 connections)
- [ ] p50 latency improvement of at least 30% vs HTTP (benchmark required)
- [ ] Tests verify: gRPC connection, HTTP fallback, connection pool behavior

**Files to Modify:**
```
proxy/app/core/retrieval.py             — QdrantClient with gRPC preference
proxy/app/shared/config.py              — QDRANT_GRPC_PORT setting
etl/indexer/qdrant_hybrid.py            — gRPC for indexing throughput
```

---

### FR-19: vLLM Prefix Caching
**Source:** R3-Performance | **Priority:** HIGH | **Estimate:** S (3h)

vLLM prefix caching MUST be enabled in the LLM backend configuration to reduce time-to-first-token for repeated system prompts.

**Acceptance Criteria:**
- [ ] vLLM server is configured with `--enable-prefix-caching` flag
- [ ] The proxy's LLM client uses consistent system prompt formatting to maximize cache hits
- [ ] Time-to-first-token for cached prompts is reduced by at least 50% (benchmark required)
- [ ] Caching behavior is documented for operators
- [ ] Tests verify: cache hit detection, latency improvement

**Files to Modify:**
```
deploy/k8s/helm/rag-system/templates/vllm-deployment.yaml  — Add --enable-prefix-caching
proxy/app/llm/router.py                — Consistent prompt formatting
proxy/docker-compose.yml                — vLLM service flags
```

---

### FR-20: MinIO in Helm Chart
**Source:** R4-ProxyData | **Priority:** HIGH | **Estimate:** M (8h)

MinIO object storage MUST be deployable via the Helm chart for model artifacts, backup storage, and file uploads.

**Acceptance Criteria:**
- [ ] MinIO is added to the Helm chart as an optional component (`minio.enabled: true`)
- [ ] Helm values include: image, PVC, access key, secret key, bucket auto-creation
- [ ] MinIO is integrated with the model evolution pipeline (MLflow artifact store)
- [ ] MinIO is integrated with the backup scripts
- [ ] PostgreSQL is added to the Helm chart for structured data (user DB, feedback store)
- [ ] Tests verify: Helm template renders MinIO, bucket creation, S3-compatible API health

**Files to Modify:**
```
deploy/k8s/helm/rag-system/templates/minio-deployment.yaml  (NEW)
deploy/k8s/helm/rag-system/templates/postgres-deployment.yaml  (NEW)
deploy/k8s/helm/rag-system/values.yaml
```

---

### FR-21: Redis Deduplication (Merge Proxy + OpenWebUI)
**Source:** R4-ProxyData | **Priority:** HIGH | **Estimate:** S (3h)

The Redis instances for the proxy and OpenWebUI MUST be merged into a single shared instance to reduce resource duplication.

**Acceptance Criteria:**
- [ ] A single Redis service is defined in `docker-compose.yml` (not separate proxy + OpenWebUI instances)
- [ ] Cache keys are namespaced by service (e.g., `proxy:cache:*`, `openwebui:session:*`) to avoid collisions
- [ ] Helm chart exposes a single Redis deployment with namespace configuration
- [ ] Migration guide documents how to consolidate existing Redis data
- [ ] Tests verify: proxy cache access, OpenWebUI session access, no key collisions

**Files to Modify:**
```
proxy/docker-compose.yml                — Single Redis service
deploy/docker/docker-compose.openwebui.yml  — Use shared Redis
deploy/k8s/helm/rag-system/templates/redis-deployment.yaml
```

---

### FR-22: ETL Persistent WAL Volume
**Source:** R4-ProxyData | **Priority:** HIGH | **Estimate:** S (4h)

The ETL WAL MUST be stored on a persistent volume to survive container restarts and enable incremental processing.

**Acceptance Criteria:**
- [ ] ETL Docker Compose service mounts a named volume for `/var/lib/etl/wal`
- [ ] Helm chart defines a PVC for ETL WAL data
- [ ] WAL data persists across `docker-compose down && docker-compose up`
- [ ] WAL includes checkpoint markers so a new ETL container resumes correctly
- [ ] Tests verify: WAL persistence across restarts, checkpoint resume

**Files to Modify:**
```
etl/docker-compose.etl.yml              — Named volume mount (already referenced in FR-16)
etl/indexer/wal_manager.py             — Checkpoint markers (already referenced in FR-04)
```

---

### FR-23: Progressive Context Gathering
**Source:** R6-Knowledge | **Priority:** HIGH | **Estimate:** M (8h)

When the initial retrieval yields insufficient results, the system MUST progressively expand its search using alternative strategies before falling back to clarification.

**Acceptance Criteria:**
- [ ] If initial retrieval yields fewer than `MIN_CHUNKS_THRESHOLD` (default: 3) relevant chunks, the system:
  1. Retries with HyDE query expansion
  2. Retries with keyword-only sparse search
  3. Expands to live sources (Confluence/Jira API)
  4. Falls back to clarification (FR-03)
- [ ] Each progressive step is logged with the number of chunks found
- [ ] The `rag_knowledge_status` reports which strategies were attempted
- [ ] Configurable: `PROGRESSIVE_RETRIEVAL_ENABLED`, `MIN_CHUNKS_THRESHOLD`, `MAX_RETRIEVAL_ROUNDS`
- [ ] Tests verify: progressive expansion chain, each strategy's contribution, fallback to clarification

**Files to Modify:**
```
proxy/app/core/retrieval.py             — Progressive retrieval orchestrator
proxy/app/core/hyde.py                  — HyDE expansion in progressive chain
proxy/app/core/live_sources.py          — Live-source fallback in chain
```

---

### FR-24: HNSW Tuning Parameters
**Source:** R3-Performance | **Priority:** HIGH | **Estimate:** S (3h)

Qdrant HNSW index parameters MUST be tuned for the dataset characteristics to optimize recall vs latency trade-off.

**Acceptance Criteria:**
- [ ] HNSW parameters are configurable per collection: `HNSW_M`, `HNSW_EF_CONSTRUCT`, `HNSW_EF_SEARCH`
- [ ] Sensible defaults are set: `m=16`, `ef_construct=200`, `ef_search=128` (tunable)
- [ ] A benchmark script measures recall@k vs query latency for different parameter combinations
- [ ] Tuning recommendations are documented for different dataset sizes (<100K, 100K–1M, >1M vectors)
- [ ] Tests verify: parameter application, benchmark script runs

**Files to Modify:**
```
scripts/init_collections.py             — HNSW config parameters
etl/indexer/qdrant_hybrid.py            — HNSW config on collection creation
scripts/benchmark_hnsw.py               (NEW)
```

---

## 2. Non-Functional Requirements

### NFR-1: Performance

| ID    | Requirement                      | Target                                | Measurement                          |
|-------|----------------------------------|---------------------------------------|--------------------------------------|
| NFR-1.1 | Retrieval latency (p95)       | <200ms (HTTP), <130ms (gRPC)         | Prometheus histogram `retrieval_duration_seconds` |
| NFR-1.2 | End-to-end latency (p95)       | <3s (simple), <8s (agentic)          | Prometheus histogram `request_duration_seconds` |
| NFR-1.3 | Qdrant memory (quantized)      | ≤50% of unquantized                   | Qdrant `/metrics` endpoint            |
| NFR-1.4 | Cache hit rate                  | ≥60% embedding cache, ≥30% rerank    | Prometheus counter `cache_hits_total` / `cache_requests_total` |
| NFR-1.5 | Prefix cache hit rate (vLLM)   | ≥40% for system prompt tokens        | vLLM metrics endpoint                 |
| NFR-1.6 | ETL OCR throughput              | ≤5 min per 100-page scanned PDF       | ETL job logs                          |
| NFR-1.7 | Retrieval quality regression    | MRR drop ≤2% with quantization       | Evaluation pipeline (`evaluate_retrieval.py`) |

### NFR-2: Security

| ID    | Requirement                      | Target                                | Measurement                          |
|-------|----------------------------------|---------------------------------------|--------------------------------------|
| NFR-2.1 | ACL enforcement                | Access filter pushed to Qdrant query  | Integration test: restricted user receives only permitted chunks |
| NFR-2.2 | Audit trail                     | All config changes and moderation actions logged | Audit log query |
| NFR-2.3 | Feedback abuse prevention       | 100 submissions/user/hour max         | Rate limiter counter                  |
| NFR-2.4 | RBAC default                    | RBAC enabled by default for all endpoints | Integration test: unauthorized requests return 403 |
| NFR-2.5 | Secret isolation                | MinIO/PostgreSQL credentials in K8s secrets, not configmaps | Helm template validation |

### NFR-3: Deployability

| ID    | Requirement                      | Target                                | Measurement                          |
|-------|----------------------------------|---------------------------------------|--------------------------------------|
| NFR-3.1 | Helm chart completeness         | Covers proxy, ETL, Qdrant, Redis, Neo4j, MinIO, PostgreSQL, vLLM | `helm template` renders all components |
| NFR-3.2 | Distributed compose             | Single `docker-compose.distributed.yml` for multi-machine | `docker-compose config` validates |
| NFR-3.3 | ETL network configurability     | Qdrant/Neo4j endpoints configurable via env vars | `docker-compose config` shows env var interpolation |
| NFR-3.4 | WAL persistence                 | Survives ETL container restart        | Integration test: restart ETL, verify checkpoint resume |
| NFR-3.5 | Air-gapped compatibility        | All models and dependencies pre-downloadable | `download_models_offline.py` includes vision model |

### NFR-4: Maintainability

| ID    | Requirement                      | Target                                | Measurement                          |
|-------|----------------------------------|---------------------------------------|--------------------------------------|
| NFR-4.1 | Runtime config                  | Non-secret settings hot-reloadable    | Integration test: PATCH config, verify effect without restart |
| NFR-4.2 | Stale document monitoring       | Automated detection every 24h         | Cron schedule in Helm chart           |
| NFR-4.3 | Reindexing resilience           | Retry 3x with exponential backoff     | ETL log verification                  |
| NFR-4.4 | Cache key namespacing           | No collisions between services        | Integration test: proxy and OpenWebUI keys don't overlap |
| NFR-4.5 | Feedback data preservation      | Corrections survive reindex           | Integration test: feedback preserved after reindex |

---

## 3. Sprint Plan — S5-2026

### Overview

| Wave  | Theme                        | Items   | Est. Hours | Target         |
|-------|------------------------------|---------|------------|----------------|
| 1     | RAG Core Quality             | FR-01, FR-02, FR-03, FR-23 | 32h   | Week 1–2       |
| 2     | Data Pipeline                | FR-04, FR-05, FR-06, FR-22 | 64h   | Week 2–4       |
| 3     | Feedback & Evolution         | FR-07, FR-08, FR-09, FR-10 | 48h   | Week 4–6       |
| 4     | Admin & RBAC                 | FR-11, FR-12, FR-13, FR-14, FR-15 | 50h | Week 6–8   |
| 5     | Deployment & Performance     | FR-16, FR-17, FR-18, FR-19, FR-20, FR-21, FR-24 | 43h | Week 8–10 |
| **Total** |                          | **24**   | **237h**   | **10 weeks**   |

---

### Wave 1: RAG Core Quality (Week 1–2) — 32h

> **Goal:** Make the RAG experience user-visible and trustworthy. Every response carries a knowledge quality signal. Conversations persist across turns. Insufficient knowledge triggers clarification instead of hallucination.

| ID     | Description                           | Est. | Role               | Dependencies |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-01  | Knowledge status flag in API response | 4h   | Backend Developer  | —            |
| FR-02  | Conversational context management     | 12h  | Backend Developer  | FR-01        |
| FR-03  | Clarifying questions                  | 8h   | Backend + LLM      | FR-01, FR-02 |
| FR-23  | Progressive context gathering         | 8h   | Backend + ML       | FR-03        |

**Wave 1 Definition of Done:**
- [ ] All 4 FRs have passing tests
- [ ] `rag_knowledge_status` present in all chat responses
- [ ] Multi-turn conversation preserves context within TTL
- [ ] Low-confidence queries generate specific clarifying questions
- [ ] Progressive retrieval chain attempts all strategies before fallback
- [ ] OpenAPI spec updated with new response fields

---

### Wave 2: Data Pipeline (Week 2–4) — 64h

> **Goal:** Complete the ETL pipeline with cleanup, OCR, image embeddings, and durable WAL. Every document type is fully indexed.

| ID     | Description                           | Est. | Role               | Dependencies |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-04  | Post-indexing data cleanup            | 16h  | Backend + DevOps   | —            |
| FR-22  | ETL persistent WAL volume             | 4h   | DevOps             | FR-04        |
| FR-05  | OCR pipeline for scanned documents    | 24h  | ML Engineer        | —            |
| FR-06  | Image embedding pipeline              | 20h  | ML Engineer        | FR-05        |

**Wave 2 Definition of Done:**
- [ ] ETL cleanup deletes raw extracts after indexing (dry-run tested)
- [ ] WAL persists across container restarts with checkpoint resume
- [ ] OCR extracts text from scanned PDFs (eng+rus)
- [ ] CLIP embeddings stored in Qdrant with `content_type: image`
- [ ] Image captions generated and searchable
- [ ] Vision model added to offline download script

---

### Wave 3: Feedback & Evolution (Week 4–6) — 48h

> **Goal:** Open feedback to all users, add moderation workflow, detect stale documents, automate reindexing.

| ID     | Description                           | Est. | Role               | Dependencies |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-07  | User feedback submission              | 12h  | Backend Developer  | —            |
| FR-08  | Feedback review & moderation          | 12h  | Backend Developer  | FR-07        |
| FR-09  | Stale document detection              | 12h  | Backend + DevOps   | —            |
| FR-10  | Automated reindexing triggers         | 12h  | Backend + DevOps   | FR-09        |

**Wave 3 Definition of Done:**
- [ ] All authenticated users can submit feedback (rate-limited)
- [ ] `retrieval_quality` dimension available in feedback
- [ ] Admins/experts can review, dismiss, and trigger enrichment from feedback
- [ ] Scheduled job flags stale documents daily
- [ ] Live-source version changes trigger automatic reindex
- [ ] Reindex preserves feedback metadata

---

### Wave 4: Admin & RBAC (Week 6–8) — 50h

> **Goal:** Administrators get runtime config, analytics, and data quality dashboards. RBAC is enforced at the vector database level.

| ID     | Description                           | Est. | Role               | Dependencies |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-11  | Runtime config management API         | 12h  | Backend Developer  | —            |
| FR-12  | Usage analytics endpoint              | 8h   | Backend + DevOps   | —            |
| FR-13  | Data quality dashboard API            | 10h  | Backend + Frontend | FR-12        |
| FR-14  | Collection-level ACL in Qdrant        | 12h  | Backend + Auth     | —            |
| FR-15  | Expert KB management endpoints        | 8h   | Backend Developer  | FR-14        |

**Wave 4 Definition of Done:**
- [ ] Runtime config PATCHable with validation and audit
- [ ] Analytics endpoint returns time-series usage data
- [ ] Data quality API serves metrics for Streamlit dashboard
- [ ] Qdrant queries include user-specific access filters
- [ ] Experts can list, flag, and reindex individual documents
- [ ] RBAC enabled by default for all endpoints

---

### Wave 5: Deployment & Performance (Week 8–10) — 43h

> **Goal:** Production-grade deployment with K8s/Compose completeness. Performance optimizations for latency and throughput.

| ID     | Description                           | Est. | Role               | Dependencies |
|--------|---------------------------------------|------|--------------------|--------------|
| FR-16  | ETL K8s + unified deployment          | 12h  | DevOps             | FR-22        |
| FR-20  | MinIO + PostgreSQL in Helm chart      | 8h   | DevOps             | —            |
| FR-21  | Redis deduplication                   | 3h   | DevOps             | —            |
| FR-17  | Qdrant scalar quantization            | 4h   | ML + Backend       | —            |
| FR-18  | Qdrant gRPC client                    | 8h   | Backend Developer  | —            |
| FR-19  | vLLM prefix caching                   | 3h   | ML + DevOps        | —            |
| FR-24  | HNSW tuning                           | 3h   | ML Engineer        | FR-17        |

**Wave 5 Definition of Done:**
- [ ] ETL deployable via Helm (`etl.enabled: true`) and Compose
- [ ] Unified distributed compose validated
- [ ] OpenWebUI in Helm chart
- [ ] MinIO and PostgreSQL in Helm chart
- [ ] Single Redis instance (namespaced keys) for proxy + OpenWebUI
- [ ] Qdrant quantization enabled (MRR regression ≤2%)
- [ ] gRPC default with HTTP fallback (p95 latency ≤130ms)
- [ ] vLLM prefix caching enabled (TTFT reduced ≥50%)
- [ ] HNSW parameters tuned and benchmarked
- [ ] Performance benchmarks rerun and published

---

## 4. Risk Matrix

| Risk                                    | Prob  | Impact | Mitigation                                              |
|-----------------------------------------|-------|--------|---------------------------------------------------------|
| OCR quality insufficient for scanned RU docs | MED | HIGH | Pre-test Tesseract with Russian + English mixed docs; fallback to EasyOCR |
| CLIP model too large for air-gapped env | LOW   | HIGH   | Use ONNX-optimized CLIP-ViT-B/32 (580MB); document size |
| Scalar quantization degrades MRR >2%    | LOW   | MED    | Gate with retrieval eval pipeline; fallback to no quantization |
| ConversationMemory race conditions       | MED   | MED    | Redis locking for concurrent session writes |
| Feedback spam from regular users        | MED   | LOW    | Rate limiting + moderation queue |
| gRPC breaks in certain network configs  | LOW   | MED    | HTTP fallback is automatic and tested |
| ETL cleanup deletes needed raw data      | MED   | HIGH   | Dry-run mode mandatory before enable; retention period buffer |
| Stale detection false positives          | MED   | LOW    | Configurable threshold; human review in moderation flow |
| Helm chart complexity grows unmaintainable | LOW | MED  | Template helper functions; validation in CI |

---

## 5. Effort Summary

| Wave  | Theme                    | FR Count | Hours | Cumulative |
|-------|--------------------------|----------|-------|------------|
| 1     | RAG Core Quality         | 4        | 32    | 32h        |
| 2     | Data Pipeline            | 4        | 64    | 96h        |
| 3     | Feedback & Evolution     | 4        | 48    | 144h       |
| 4     | Admin & RBAC             | 5        | 50    | 194h       |
| 5     | Deployment & Performance | 7        | 43    | 237h       |
| **Total** |                      | **24**   | **237h** | —        |

---

## 6. Human Decisions Required

1. **FR-05 OCR:** Tesseract vs EasyOCR for Russian-language documents? Tesseract recommended for broader language support, EasyOCR for better accuracy on complex layouts.
2. **FR-06 Vision Model:** CLIP-ViT-B/32 (580MB, fast) vs CLIP-ViT-L/14 (1.7GB, more accurate)? Recommend ViT-B/32 for air-gapped constraints.
3. **FR-14 RBAC:** Should RBAC be enabled by default (breaking change for existing deployments)? Recommend yes, with migration guide.
4. **FR-17 Quantization:** Apply quantization to existing collections or only new ones? Recommend migration script with opt-in flag.
5. **Sprint cadence:** Single 10-week sprint or 2×5-week sprints with midpoint review? Recommend 10-week with bi-weekly checkpoints.

---

## 7. Traceability Matrix

| FR      | Source Gap       | Wave | Priority |
|---------|------------------|------|----------|
| FR-01   | R6-Knowledge     | 1    | CRITICAL |
| FR-02   | R13-Conversation | 1    | CRITICAL |
| FR-03   | R13-Conversation | 1    | CRITICAL |
| FR-04   | R8-ETL           | 2    | CRITICAL |
| FR-05   | R10-Multimodal   | 2    | CRITICAL |
| FR-06   | R10-Multimodal   | 2    | CRITICAL |
| FR-07   | R11-Feedback     | 3    | CRITICAL |
| FR-08   | R11-Feedback     | 3    | CRITICAL |
| FR-09   | R12-Stale        | 3    | CRITICAL |
| FR-10   | R12-Stale        | 3    | CRITICAL |
| FR-11   | R9-Admin         | 4    | HIGH     |
| FR-12   | R9-Admin         | 4    | HIGH     |
| FR-13   | R9-Admin         | 4    | HIGH     |
| FR-14   | R7-RBAC          | 4    | HIGH     |
| FR-15   | R7-RBAC          | 4    | HIGH     |
| FR-16   | R1-Deploy        | 5    | HIGH     |
| FR-17   | R3-Performance   | 5    | HIGH     |
| FR-18   | R3-Performance   | 5    | HIGH     |
| FR-19   | R3-Performance   | 5    | HIGH     |
| FR-20   | R4-ProxyData     | 5    | HIGH     |
| FR-21   | R4-ProxyData     | 5    | HIGH     |
| FR-22   | R4-ProxyData     | 2    | HIGH     |
| FR-23   | R6-Knowledge     | 1    | HIGH     |
| FR-24   | R3-Performance   | 5    | HIGH     |

---

## 8. Appendix: Gap Coverage Verification

| Source Gap         | Covered By                              | Status |
|---------------------|----------------------------------------|--------|
| R1-Deploy           | FR-16 (ETL K8s + unified deploy)       | ✅     |
| R2-Coupling         | FR-16 (unified compose), FR-21 (Redis merge) | ✅  |
| R3-Performance      | FR-17 (quantization), FR-18 (gRPC), FR-19 (vLLM cache), FR-24 (HNSW) | ✅ |
| R4-ProxyData        | FR-20 (MinIO Helm), FR-21 (Redis merge), FR-22 (WAL PVC) | ✅ |
| R6-Knowledge        | FR-01 (knowledge_status), FR-23 (progressive context) | ✅ |
| R7-RBAC             | FR-14 (collection ACL), FR-15 (expert KB) | ✅     |
| R8-ETL              | FR-04 (data cleanup), FR-22 (WAL persistence) | ✅ |
| R9-Admin            | FR-11 (runtime config), FR-12 (analytics), FR-13 (data quality) | ✅ |
| R10-Multimodal      | FR-05 (OCR), FR-06 (image embedding)    | ✅     |
| R11-Feedback        | FR-07 (user feedback), FR-08 (moderation) | ✅   |
| R12-Stale           | FR-09 (stale detection), FR-10 (reindexing) | ✅  |
| R13-Conversation    | FR-02 (conversation context), FR-03 (clarifying questions) | ✅ |
