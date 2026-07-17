# RAG System — Compliance Requirements

**Version:** v1.0 | **Date:** 2026-07-17 | **Scope:** Full system (Proxy + ETL + MCP + Model Evolution + Dashboard)

This document enumerates every functional requirement, non-functional requirement, constraint, and architectural
decision identified across all project artifacts: 14 ADRs, 12+ guides, source code, and stakeholder specifications.

---

## FR (Functional Requirements)

### Core RAG Pipeline

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-01 | The proxy SHALL expose an OpenAI-compatible `/v1/chat/completions` endpoint supporting both streaming (SSE) and non-streaming modes | ADR-004, README, AGENTS.md | CRITICAL | curl test: OpenAI SDK works against proxy URL |
| FR-02 | The proxy SHALL expose `/v1/models` listing available LLM backends | ADR-004, README | CRITICAL | curl test: returns model list |
| FR-03 | The proxy SHALL expose `/v1/health` reporting Qdrant, Neo4j, Redis, embedder, reranker, and LLM status with 503 on degradation | ADR-004, best-practices-checklist 4.3 | CRITICAL | curl test: returns 200 healthy, 503 degraded |
| FR-04 | The proxy SHALL expose `/v1/health/live` (liveness probe) and `/v1/health/ready` (readiness probe) | roadmap Phase 3, best-practices-checklist 4.7 | CRITICAL | K8s/Docker healthcheck probe passes |
| FR-05 | The proxy SHALL support RAG-specific request parameters: `rag_version`, `rag_force_refresh`, `rag_skip_generation`, `rag_return_chunks`, `rag_top_k` | ADR-004, AGENTS.md | CRITICAL | Integration test: each parameter produces expected behavior |
| FR-06 | The proxy SHALL inject RAG-specific response fields: `rag_feedback_id`, `rag_confidence`, `rag_sources` | ADR-004, roadmap Phase 2 | CRITICAL | Integration test: response includes all three fields |
| FR-07 | Non-streaming responses SHALL be cached in Redis with 1-hour TTL, bypassable via `rag_force_refresh` | ADR-004, performance-quality 1.4 | CRITICAL | Metric check: cache hit ratio > 0 for repeated queries |
| FR-08 | Streaming responses SHALL use Server-Sent Events with `text/event-stream` format and `data: [DONE]` termination | ADR-004 | CRITICAL | curl test: SSE stream terminates with [DONE] |

### Retrieval & Search

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-09 | The system SHALL perform hybrid retrieval combining dense (1024-dim BGE-M3) and sparse (BM25-style lexical) vectors via Reciprocal Rank Fusion with k=60 | ADR-001, ADR-002, rag-maturity-assessment L2 | CRITICAL | Integration test: verify RRF fusion merges both result sets |
| FR-10 | The system SHALL use cross-encoder reranking (MiniLM-L-6-v2, batch_size=32) on top-N retrieval candidates after hybrid search | ADR-002, best-practices-checklist 6.3 | CRITICAL | Integration test: reranked order differs from raw score order for ambiguous queries |
| FR-11 | The system SHALL perform content-based deduplication using SHA-256 chunk hashing during context assembly | ADR-005, rag-maturity-assessment L2.3 | CRITICAL | Unit test: duplicate chunks removed from context |
| FR-12 | The system SHALL support version-aware chunk filtering via Qdrant `FieldCondition` on the `version` field, exposed through `rag_version` parameter | ADR-005, rag-maturity-assessment L2.4 | CRITICAL | Integration test: `rag_version="v1"` returns only v1 chunks |
| FR-13 | The system SHALL embed user queries via BGE-M3 and cache embeddings keyed by MD5 hash (in-memory LRU + optional Redis) | ADR-001, best-practices-checklist 6.1 | CRITICAL | Metric check: embedding cache hit ratio reported per Prometheus |
| FR-14 | The system SHALL support ColBERT late-interaction multi-vector retrieval (produced by BGE-M3) | roadmap Phase 1, performance-quality 8.1 | HIGH | Integration test: ColBERT search returns results |
| FR-15 | The system SHALL support knee-point pruning of retrieval results | roadmap Phase 2 | HIGH | Unit test: pruning reduces result count on score drop-off |
| FR-16 | The system SHALL support FLARE active retrieval (forward-looking active retrieval) | roadmap Phase 5 | HIGH | Unit test: FLARE generates retrieval-augmented content |
| FR-17 | The system SHALL support two-stage reranking | roadmap Phase 5 | HIGH | Unit test: two-stage pipeline improves nDCG vs single stage |
| FR-18 | The system SHALL support dynamic top-k retrieval based on SLM query complexity classification | roadmap Phase 3, token-economy | HIGH | Integration test: simple query retrieves fewer chunks than complex |

### Knowledge Graph (Neo4j)

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-19 | The system SHALL extract entities from documents using spaCy NER and optional SLM augmentation, with 10 entity types and 9 relation types | ADR-006, knowledge-graph-strategy 1.1-1.3, rag-maturity-assessment L3 | HIGH (opt-in) | Integration test: ETL run populates Neo4j with entities and relations |
| FR-20 | The system SHALL load entities into Neo4j using UNWIND-based batch operations with configurable batch_size=500 and max_retries=3 | knowledge-graph-strategy 1.4 | HIGH (opt-in) | Unit test: batch loading succeeds |
| FR-21 | The system SHALL support multi-hop graph traversal (1-hop, 2-hop, N-hop with centrality scoring) for context enrichment | ADR-006, knowledge-graph-strategy 2.2 | HIGH (opt-in) | Integration test: graph_expand node returns entities within N hops |
| FR-22 | The system SHALL support Global Search mode (community-based), Multi-Hop Reasoning, and Text-to-Cypher graph queries | roadmap Phase 3 | HIGH (opt-in) | Integration test: each mode produces valid results |
| FR-23 | The system SHALL support Community Detection in the knowledge graph | roadmap Phase 3 | HIGH (opt-in) | Unit test: communities detected from entity graph |
| FR-24 | The system SHALL gracefully skip graph expansion when Neo4j is unavailable (no crash, no 5xx) | AGENTS.md, ADR-011, resilience 7.3 | CRITICAL | Chaos test: Neo4j down → graph expansion skipped, response still served |
| FR-25 | The system SHALL implement graph schema versioning with 90-day retention on `updated_at` timestamps | knowledge-graph-strategy 1.4 | MEDIUM | Unit test: outdated entities/relations cleanup |

### Agentic Orchestration (LangGraph)

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-26 | The system SHALL implement a LangGraph-based agentic orchestrator with 10 nodes: rewrite, retrieve, check_sufficiency, graph_expand, rerank, build_context, generate, check_confidence, call_tools, and finalize | ADR-006, AGENTS.md | HIGH (opt-in) | Integration test: graph compilation succeeds, all nodes executable |
| FR-27 | The system SHALL perform query rewriting using SLM/LLM before retrieval to improve context quality | ADR-006, rag-maturity-assessment L4.2 | HIGH (opt-in) | Integration test: rewritten query differs from original and returns different chunks |
| FR-28 | The system SHALL evaluate retrieval sufficiency using a score threshold (0.6) and loop back to rewrite if insufficient, bounded by `MAX_RETRIEVAL_LOOPS=3` | ADR-006, rag-maturity-assessment L4.3-4.4 | HIGH (opt-in) | Integration test: 3-loop max enforced, sufficient context exits loop |
| FR-29 | The system SHALL fall back to a simple linear pipeline when `USE_LANGGRAPH=false` | ADR-006, ADR-011, rag-maturity-assessment L4.6 | CRITICAL | Integration test: with flag off, simple RAG path is used |
| FR-30 | The system SHALL support tool/function calling with live Confluence, Jira, and GitLab API queries | ADR-009, roadmap Phase 8.6 | HIGH | Integration test: LLM-initiated tool call executes successfully |
| FR-31 | The system SHALL support parallel tool execution with dependency-aware topological sort and asyncio.gather per dependency level | ADR-009 4.2-4.3 | HIGH | Unit test: independent tools execute concurrently |

### HyDE, CRAG, Self-Reflection, Grounding

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-32 | The system SHALL generate Hypothetical Document Embeddings (HyDE) from queries for improved sparse retrieval | rag-maturity-assessment L5.3, roadmap Phase 8.1 | HIGH | Integration test: HyDE expansion produces additional relevant chunks |
| FR-33 | The system SHALL implement a CRAG-style retrieval evaluator with multi-factor quality scoring (score distribution 0.4, coverage ratio 0.3, result count 0.2, recency decay 0.1) mapping confidence to USE/REWRITE/EXPAND/FALLBACK actions | rag-maturity-assessment L5.1, roadmap Phase 8.2 | HIGH | Integration test: each confidence band triggers correct action |
| FR-34 | The system SHALL perform self-reflection: post-generation LLM critique of answer against retrieved context, scoring for faithfulness | rag-maturity-assessment L5.4, roadmap Phase 8.3 | HIGH | Integration test: self-reflection score computed and logged |
| FR-35 | The system SHALL implement NLI-based answer grounding: cosine similarity embedding check + entailment classification. Answers with grounding score < 0.70 flagged for review | rag-maturity-assessment L5.5, performance-quality 4.4, roadmap Phase 8.4 | HIGH | Integration test: hallucinated answer gets low grounding score |
| FR-36 | The system SHALL perform hallucination detection: unsupported claim flagging in generated answers | rag-maturity-assessment L5.5, performance-quality 4.4 | HIGH | Unit test: hallucination detection flags unsupported claims |
| FR-37 | The system SHALL implement corrective re-generation: low-confidence or ungrounded answers trigger re-generation with expanded context, factuality-focused prompt, or adjusted temperature | rag-maturity-assessment L5.6, roadmap Phase 8.5 | HIGH | Integration test: low-confidence answer triggers regeneration loop |
| FR-38 | The system SHALL implement LLMLingua token-level prompt compression (2-5x compression ratio, <5% info loss) | rag-maturity-assessment L5, roadmap Phase 8.8 | HIGH | Unit test: compressed text preserves key information |
| FR-39 | The system SHALL implement LongContextReorder to combat "lost in the middle" effect | rag-maturity-assessment L5, roadmap Phase 8.9 | HIGH | Unit test: reordered context places key info at extremes |

### ETL Pipeline

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-40 | The ETL pipeline SHALL extract data from Confluence, Jira, GitLab, documents, books, and chat logs | AGENTS.md, README | CRITICAL | Integration test: each source extracts documents |
| FR-41 | The ETL pipeline SHALL operate in two modes: streaming (zero disk, generator-based) and batch (parallel extraction with disk persistence) | etl-operations | CRITICAL | Run both modes: verify streaming produces no disk files, batch saves raw data |
| FR-42 | The ETL pipeline SHALL chunk documents using semantic chunking with configurable parameters (size 256-1024 tokens, p50=512, p95=900, overlap 10-15%) | performance-quality 4.1, roadmap Phase 5 | CRITICAL | Unit test: chunk sizes in range, coherence > 0.75 |
| FR-43 | The ETL pipeline SHALL support adaptive chunking | roadmap Phase 5 | HIGH | Unit test: chunk boundaries adapt to content structure |
| FR-44 | The ETL pipeline SHALL implement RAPTOR hierarchical indexing | roadmap Phase 2 | HIGH | Integration test: hierarchical chunks created |
| FR-45 | The ETL pipeline SHALL implement WAL-based incremental checkpointing with per-pipeline state (confluence, jira, gitlab, indexing, graph_builder) | ADR-005, etl-operations, ADR-011 | CRITICAL | Integration test: interrupted ETL resumes from last checkpoint |
| FR-46 | The ETL pipeline SHALL implement content-addressable chunk versioning via SHA-256 hashing, using the hash as the Qdrant point ID | ADR-005 | CRITICAL | Unit test: same content produces same point ID |
| FR-47 | The ETL pipeline SHALL implement LiveVectorLake with hot (Qdrant) and cold (Parquet/Delta Lake) storage tiers | ADR-005 | CRITICAL | Integration test: current version in Qdrant, history in Parquet |
| FR-48 | The ETL pipeline SHALL support WAL backends: file (JSON with filelock), Redis, and proxy (HTTP) | etl-operations WAL | HIGH | Unit test: each backend reads/writes checkpoints |
| FR-49 | The ETL pipeline SHALL support `--reset-wal`, `--force-reindex`, `--skip-extract`, `--skip-chunk`, `--skip-graph`, `--skip-index` CLI flags | ADR-005, etl-operations | CRITICAL | CLI invocation: each flag produces expected behavior |
| FR-50 | The ETL pipeline SHALL support `--dry-run-cleanup` mode reporting files that would be deleted | requirements-and-sprint-plan FR-04 | HIGH | CLI invocation: dry-run lists files without deleting |
| FR-51 | The ETL pipeline SHALL support webhook-driven ingestion for Confluence/GitLab events via Redis Streams | roadmap Phase 6.1, etl-operations | HIGH | Integration test: webhook triggers incremental indexing |
| FR-52 | The ETL pipeline SHALL support a streaming ETL pipeline with Redis Streams consumer groups (<5s end-to-end latency) | roadmap Phase 6.2, etl-operations | HIGH | Integration test: end-to-end latency < 5s |
| FR-53 | The ETL pipeline SHALL support an event pipeline orchestrator (unified webhook → Redis Streams → consumer coordinator) | roadmap Phase 6.3 | HIGH | Integration test: end-to-end event flow |

### ETL — Remote Services

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-54 | The ETL pipeline SHALL support remote embedder, reranker, and SLM services via OpenAI-compatible endpoints with configurable endpoints, models, API keys, timeouts, batch sizes, retry logic, and connection pooling | etl-operations Remote | CRITICAL | Integration test: ETL runs with remote embedder configured |
| FR-55 | The ETL pipeline SHALL implement exponential backoff retry with jitter for remote embedder calls (retryable statuses: 429, 500, 502, 503, 504) | etl-operations RemoteEmbedder | CRITICAL | Unit test: retry exhausts after max_retries, transient failure recovers |
| FR-56 | The ETL pipeline SHALL use asyncio.Semaphore for concurrency control when calling remote embedders in streaming mode | etl-operations Streaming | HIGH | Unit test: concurrent calls bounded by semaphore |

### ETL — OCR & Multimodal

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-57 | The ETL pipeline SHALL extract text from scanned PDFs and images using Tesseract OCR with configurable language (default: `eng+rus`) | requirements-and-sprint-plan FR-05, etl-operations OCR | HIGH | Integration test: scanned PDF yields text via OCR |
| FR-58 | The ETL pipeline SHALL support CLIP-based image embedding generation with captions stored in Qdrant as `content_type: "image"` | requirements-and-sprint-plan FR-06, roadmap Phase 5.1 | HIGH | Integration test: image indexed with embedding and caption |
| FR-59 | The ETL pipeline SHALL extract embedded images from PDFs, run OCR on each, and append extracted text to document content | etl-operations PDF-Images | HIGH | Integration test: embedded image text merged with document |
| FR-60 | The ETL pipeline SHALL generate extraction quality reports with per-document OCR confidence, table extraction metrics, and overall score | etl-operations Quality-Report | MEDIUM | CLI: `--quality-report path.json` produces valid JSON |

### ETL — Cleanup & Persistence

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-61 | The ETL pipeline SHALL clean up raw extracts, chunk artifacts, and cold storage beyond RETENTION_DAYS after successful indexing | requirements-and-sprint-plan FR-04, etl-operations Cleanup | CRITICAL | Integration test: cleanup removes files after successful index |
| FR-62 | The ETL pipeline SHALL persist WAL state to a durable volume (not ephemeral container storage) with checkpoint snapshots | requirements-and-sprint-plan FR-22, FR-04 | HIGH | Integration test: WAL survives container restart |
| FR-63 | The ETL pipeline SHALL support configurable data retention: `raw_data_days`, `cleanup_after_run`, `keep_cold_storage` | etl-operations Cleanup | HIGH | Config test: retention settings honored |

### SLM & LLM Dual-Model Architecture

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-64 | The system SHALL use a small language model (SLM) for lightweight tasks: intent classification (5 classes), query decomposition (≤3 sub-queries), entity extraction, and query rewriting | ADR-003, AGENTS.md | CRITICAL | Integration test: SLM routes query correctly, extracts entities |
| FR-65 | The system SHALL fall back to heuristic methods (keyword matching, regex) when SLM endpoint is empty or unavailable | ADR-003 | CRITICAL | Integration test: with SLM disabled, keyword intent detection works |
| FR-66 | The system SHALL use the primary LLM for generation of contextual answers via OpenAI-compatible API through provider adapter | ADR-003, AGENTS.md | CRITICAL | Integration test: LLM generates response from assembled context |
| FR-67 | The system SHALL support multi-provider LLM backends (vLLM, llama.cpp, Anthropic, Ollama, generic OpenAI-compatible) via pluggable provider adapters | ADR-004, AGENTS.md, README | CRITICAL | Integration test: each provider type generates a response |
| FR-68 | The system SHALL use consistent system prompt formatting across all providers to maximize prefix cache hits | requirements-and-sprint-plan FR-19 | HIGH | Integration test: same prompt format across providers |

### Token Optimization

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-69 | The system SHALL perform BPE-aware token counting with 4 compression strategies for context assembly | AGENTS.md, rag-maturity-assessment L2.5, token-economy 6.2 | CRITICAL | Unit test: token count accurate within ±10% of model tokenizer |
| FR-70 | The system SHALL implement smart budget allocation across system prompt, context, history, and response with configurable ratios | rag-maturity-assessment 5.2 | HIGH | Unit test: budget split respects configured ratios |
| FR-71 | The system SHALL expand surrounding chunks for same-document adjacent content | rag-maturity-assessment 5.2 | MEDIUM | Unit test: expansion adds preceding/following chunks |
| FR-72 | The system SHALL prepend chunk headers (document title, section path) for context enrichment | rag-maturity-assessment 5.2 | MEDIUM | Unit test: context includes header info |

### Feedback & HITL

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-73 | The system SHALL expose `/v1/feedback` accepting positive, negative, and correction feedback types | ADR-007, AGENTS.md | CRITICAL | curl test: feedback submission returns success |
| FR-74 | The system SHALL log all query-response pairs asynchronously (non-blocking) to `interactions.jsonl` with request ID, timestamp, query, response, and metadata | ADR-007 | CRITICAL | Check: interactions.jsonl has entries after traffic |
| FR-75 | The system SHALL log feedback separately to `feedback.jsonl` with positive/negative/correction types | ADR-007 | CRITICAL | Check: feedback.jsonl populated after submissions |
| FR-76 | The system SHALL support training dataset export from HITL logs: expert-corrected pairs and positively-rated pairs in JSONL format for fine-tuning | ADR-007, ADR-010 | HIGH | CLI: export produces valid prompt-completion pairs |
| FR-77 | The system SHALL provide a Streamlit-based expert review dashboard with browse/filter, feedback submission, corrections, and training dataset export | ADR-007 | HIGH | Manual: dashboard loads, filtering works, corrections save |
| FR-78 | The system SHALL implement self-enrichment: positive feedback with corrections indexed back into Qdrant as Q&A pairs via `enricher.py` | ADR-007, roadmap Phase 2 | HIGH | Integration test: corrected Q&A pair appears in retrieval after enrichment |
| FR-79 | All authenticated users SHALL be able to submit feedback (not just experts) | requirements-and-sprint-plan FR-07 | HIGH | Integration test: user-role submits feedback successfully |
| FR-80 | The system SHALL support `retrieval_quality` as a feedback dimension alongside existing dimensions | requirements-and-sprint-plan FR-07 | HIGH | Integration test: retrieval_quality feedback recorded |
| FR-81 | The system SHALL rate-limit feedback at 100 submissions per user per hour | requirements-and-sprint-plan FR-07 | HIGH | Unit test: 101st submission returns 429 |
| FR-82 | Administrators and experts SHALL have feedback review endpoints: list/filter by status/rating/dimension/date, review with notes, dismiss with reason, trigger enrichment | requirements-and-sprint-plan FR-08 | HIGH | Integration test: admin reviews, dismisses, triggers enrichment |
| FR-83 | The system SHALL support confidence-based alerting: low-confidence answers trigger admin alerts | roadmap Phase 2, rag-maturity-assessment L5.8 | HIGH | Integration test: confidence < threshold triggers alert |

### Authentication & RBAC

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-84 | The system SHALL support JWT authentication with access + refresh token pairs (HS256 or RS256) | ADR-007, best-practices-checklist 3.3, access-control-rbac 1.1 | CRITICAL | curl test: login → token → authenticated request succeeds |
| FR-85 | The system SHALL support user self-registration with bcrypt-hashed passwords stored in SQLite | AGENTS.md | CRITICAL | curl test: register → login with registered credentials |
| FR-86 | The system SHALL support Keycloak OIDC integration with RS256 JWKS validation, auto-discovery, 1-hour JWKS cache, and air-gap fallback to static public key | access-control-rbac 1.2 | HIGH | Integration test: Keycloak-issued token validated |
| FR-87 | The system SHALL support LDAP/AD authentication integration | AGENTS.md, access-control-rbac | HIGH | Integration test: LDAP bind authenticates user |
| FR-88 | The system SHALL support API key management and validation as an alternative auth method | AGENTS.md, access-control-rbac | HIGH | curl test: API key header authenticates request |
| FR-89 | The system SHALL implement RBAC with 4 roles: admin, expert, user, read-only | AGENTS.md, AGENTS.md Key Principles, access-control-rbac 3 | CRITICAL | Integration test: each role has correct permission set |
| FR-90 | The system SHALL support 5 access levels: public, internal, confidential, restricted, secret | access-control-rbac 4 | HIGH | Integration test: lower-access user cannot retrieve higher-access content |
| FR-91 | The system SHALL implement document-level access control via `build_access_filter()` and source-level filtering via `filter_chunks()` | best-practices-checklist 3.4, access-control-rbac 4 | HIGH | Integration test: restricted user receives filtered results |
| FR-92 | The system SHALL enforce collection-level ACL in Qdrant queries so unauthorized documents are never retrieved | requirements-and-sprint-plan FR-14 | HIGH | Integration test: Qdrant query includes user's access filter |
| FR-93 | The system SHALL expose `/v1/auth/login`, `/v1/auth/register`, `/v1/auth/refresh`, `/v1/auth/logout`, `/v1/auth/me` endpoints | AGENTS.md | CRITICAL | curl test: each endpoint works end-to-end |
| FR-94 | The system SHALL refresh expired access tokens using refresh tokens, and blacklist access tokens on logout | AGENTS.md | HIGH | Integration test: refresh → new token pair, old token rejected after logout |

### Admin API

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-95 | The system SHALL expose `/v1/admin/models/train` (POST) to trigger SLM/LLM/Reranker training jobs | ADR-010, AGENTS.md | HIGH | curl test: training job queued, job ID returned |
| FR-96 | The system SHALL expose `/v1/admin/models/status/{job_id}` (GET) to poll training job status and metrics | ADR-010, AGENTS.md | HIGH | curl test: status returned for known job ID |
| FR-97 | The system SHALL expose `/v1/admin/models` (GET) to list registered models with versions and metrics | ADR-010, AGENTS.md | HIGH | curl test: model list returned |
| FR-98 | The system SHALL expose `/v1/admin/models/promote` (POST) to promote a model version to production | ADR-010, AGENTS.md | HIGH | curl test: promoted model listed as Production |
| FR-99 | The system SHALL expose `/v1/admin/models/rollback` (POST) to rollback model to previous version | ADR-010, AGENTS.md | HIGH | curl test: rolled-back model reverts to previous |
| FR-100 | The system SHALL expose `/v1/admin/models/evaluate` (POST) to evaluate model quality against baseline | ADR-010, AGENTS.md | HIGH | curl test: evaluation metrics returned |
| FR-101 | The system SHALL expose `/v1/admin/models/canary/split` (POST) and `/v1/admin/models/canary/status` (GET) for canary traffic control | ADR-010, AGENTS.md | HIGH | curl test: split set, status retrieved |
| FR-102 | The system SHALL expose `/v1/admin/models/reload` (POST) for hot-reload of model adapters | ADR-010 | HIGH | curl test: reload triggers adapter swap |
| FR-103 | The system SHALL expose `POST /v1/admin/warmup` to pre-load embedder, reranker, and SLM models at startup | roadmap Phase 6.6, performance-quality 12 | HIGH | curl test: warmup completes, first request latency = subsequent |
| FR-104 | The system SHALL expose `GET /v1/admin/config` and `PATCH /v1/admin/config` for runtime configuration management with validation and audit logging | requirements-and-sprint-plan FR-11 | HIGH | curl test: config read, modified, audit log entry created |
| FR-105 | The system SHALL expose `GET /v1/admin/analytics` returning time-series usage data (24h/7d/30d) from Prometheus or JSON fallback | requirements-and-sprint-plan FR-12 | HIGH | curl test: analytics JSON returned with expected metrics |
| FR-106 | The system SHALL expose `GET /v1/admin/data-quality` returning per-source aggregated quality metrics for Streamlit dashboard consumption | requirements-and-sprint-plan FR-13 | HIGH | curl test: data-quality JSON includes per-source breakdown |
| FR-107 | The system SHALL expose `GET /v1/admin/stale/report` listing documents flagged as stale grouped by source | requirements-and-sprint-plan FR-09 | HIGH | curl test: stale report returns documents older than threshold |
| FR-108 | The system SHALL expose `POST /v1/admin/reindex/trigger` (webhook) and `GET /v1/admin/reindex/status/{job_id}` for reindexing management | requirements-and-sprint-plan FR-10 | HIGH | curl test: trigger queues job, status trackable |
| FR-109 | The system SHALL expose expert KB management: `GET /v1/expert/documents`, `POST /v1/expert/documents/{id}/reindex`, `POST /v1/expert/documents/{id}/flag`, `GET /v1/expert/documents/{id}/chunks` | requirements-and-sprint-plan FR-15 | HIGH | Integration test: expert lists, reindexes, flags, lists chunks |
| FR-110 | The system SHALL expose `/v1/files` endpoints: POST (upload), GET (list/metadata/download/presigned URL), DELETE | ADR-014, AGENTS.md | HIGH | curl test: upload → list → download → delete cycle |

### Tool System

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-111 | The system SHALL expose `GET /v1/tools` listing all tools with optional category, tag, and provider filters | ADR-009, AGENTS.md | HIGH | curl test: tool list returned with filters working |
| FR-112 | The system SHALL expose `GET /v1/tools/{name}` returning a single tool's details (parameters, visibility, provider) | ADR-009, AGENTS.md | HIGH | curl test: individual tool details returned |
| FR-113 | The system SHALL provide a `@tool` decorator SDK with automatic JSON Schema generation from Python type hints | ADR-009 2.3.2 | HIGH | Unit test: decorated function registered with correct schema |
| FR-114 | The system SHALL provide a `ToolBuilder` API for programmatic tool construction with fluent interface | ADR-009 2.3.2 | HIGH | Unit test: builder produces valid ToolDefinition |
| FR-115 | The system SHALL inject `ToolContext` (user_id, user_role, request_id, cross-tool shared state, streaming) automatically into tool handlers | ADR-009 2.3.2 | HIGH | Unit test: ToolContext populated at invocation |
| FR-116 | The system SHALL support YAML/JSON declarative tool definitions for HTTP and shell commands with variable interpolation, whitelist validation, and safety constraints | ADR-009 2.3.3 | HIGH | Unit test: declarative tool loads from YAML, executes HTTP/shell safely |
| FR-117 | The system SHALL support OpenAPI auto-discovery converting REST API specs to tool definitions (AUTO and LLM_DRIVEN modes) | ADR-009 2.3.4 | HIGH | Unit test: OpenAPI spec parsed, tools generated |
| FR-118 | The system SHALL filter tools by user role via ToolVisibilityFilter (hierarchy: admin > expert > user > read_only) | ADR-009 2.3.7, 3.4 | HIGH | Integration test: read_only user sees only public tools |
| FR-119 | The system SHALL emit Prometheus metrics per tool call: total, duration, active, retries, input/output bytes | ADR-009 2.3.8 | HIGH | Metric check: all 6 metrics present at /metrics |
| FR-120 | The system SHALL produce structured audit logs for all tool calls with SHA-256 hashed params and results | ADR-009 2.3.9 | HIGH | Check: audit log entries for tool executions |

### MCP Server

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-121 | The MCP server SHALL expose three tools: `rag_search`, `rag_chat`, `rag_feedback` | ADR-013 | HIGH | MCP client: all three tools listed and callable |
| FR-122 | The MCP server SHALL expose one resource: `rag://collections` listing available collections | ADR-013 | MEDIUM | MCP client: resource resolves |
| FR-123 | The MCP server SHALL expose one prompt: `rag_help` with usage instructions | ADR-013 | MEDIUM | MCP client: prompt returns help text |
| FR-124 | The MCP server SHALL support dual transport: STDIO (default, for OpenCode/Claude Desktop) and HTTP (for web-based clients) | ADR-013 | HIGH | Start in each mode: client connects |
| FR-125 | The MCP server SHALL be installable as a standalone pip package or script, configurable via env var `RAG_PROXY_URL` | ADR-013 | HIGH | pip install + configure + run |

### Model Evolution

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-126 | The system SHALL support SLM LoRA fine-tuning for intent classification with rank=8, alpha=16 | ADR-010, model-evolution-guide 1.2 | HIGH | Training job: adapter produced, metrics logged |
| FR-127 | The system SHALL support LLM QLoRA fine-tuning (4-bit NF4, rank=16, alpha=32) for domain-specific generation | ADR-010, model-evolution-guide 1.2 | HIGH | Training job: adapter produced, metrics logged |
| FR-128 | The system SHALL support Reranker fine-tuning (both full FT via CrossEncoder.fit() and LoRA path rank=4) | ADR-010, model-evolution-guide 1.2 | HIGH | Training job: adapted model scores differently from base |
| FR-129 | The system SHALL use MLflow for experiment tracking with parameter/metric/artifact logging and S3-compatible (MinIO) artifact storage | ADR-010, ADR-ME-001, model-evolution-guide 2.3 | HIGH | Check: MLflow UI shows runs with params, metrics, artifacts |
| FR-130 | The system SHALL implement MLflow Model Registry with stage transitions (None → Staging → Production → Archived) | ADR-010, ADR-ME-001 | HIGH | Check: MLflow UI shows version stages |
| FR-131 | The system SHALL implement EvalGate CI/CD quality gating with configurable thresholds per model type (SLM F1≥0.85, LLM BertScore≥0.70, hallucination≤0.05, Rouge-L≥0.35, Reranker MRR≥baseline+0.02) | ADR-010 3.4, ADR-ME-001 | HIGH | CI: below-threshold model fails gate, blocked from promotion |
| FR-132 | The system SHALL implement CanaryController with phased traffic splitting (5%→25%→50%→75%→100%) and automatic Prometheus-driven rollback on metric degradation | ADR-010 4.3.3, ADR-ME-004 | HIGH | Integration test: canary phases advance, rollback triggers on degradation |
| FR-133 | The system SHALL implement AdapterManager for hot-reload of LoRA adapters without proxy restart (UNLOADED→LOADING→ACTIVE→DRAINING→RETIRING lifecycle) | ADR-010 4.3.2, ADR-ME-003 | HIGH | Integration test: adapter swap completes, in-flight requests finish, new adapter serves |
| FR-134 | The system SHALL implement HotReloadWatcher with inotify/polling for local dirs plus MLflow registry polling | ADR-010, ADR-ME-003 | HIGH | Integration test: watcher detects new version, triggers reload |
| FR-135 | The system SHALL support three environment training profiles: DEV (CPU, 1 epoch, small), PROD (GPU, 5 epochs, bf16), CI (no GPU, smoke test, 1 epoch) | ADR-010 9.1 | HIGH | Training job: each profile produces expected resource usage |
| FR-136 | The system SHALL compute generation quality metrics: BLEU-4, ROUGE-L, BertScore-F1, hallucination rate, perplexity | ADR-010 4.3.5 | HIGH | Unit test: each metric computed correctly against known references |

### Stale Document Management

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-137 | The system SHALL detect stale documents: a scheduled job scans for `last_verified_at` older than `STALE_THRESHOLD_DAYS` (default 90) and flags them with `stale: true` metadata | requirements-and-sprint-plan FR-09 | HIGH | Integration test: stale document flagged after threshold |
| FR-138 | The system SHALL include `rag_stale_sources` in responses when stale documents are retrieved | requirements-and-sprint-plan FR-09 | HIGH | Integration test: response includes stale flag for aged sources |
| FR-139 | The system SHALL automatically queue reindexing when live-source version checks detect updated documents, preserving feedback metadata from old versions | requirements-and-sprint-plan FR-10 | HIGH | Integration test: Confluence page update triggers reindex, feedback preserved |

### Conversational Context & Clarification

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-140 | The system SHALL accumulate conversational context across multi-turn sessions via `ConversationMemory`, using session context for query expansion (pronoun resolution, topic tracking) | requirements-and-sprint-plan FR-02 | HIGH | Integration test: follow-up question resolves pronouns from prior turn |
| FR-141 | The system SHALL bound session context to last N turns or token cap and expire sessions after configurable TTL (default 30 min) | requirements-and-sprint-plan FR-02 | HIGH | Integration test: old session expires, new session starts |
| FR-142 | The system SHALL generate clarifying questions when knowledge is insufficient (status `insufficient` or `absent`) instead of producing low-confidence or hallucinated answers | requirements-and-sprint-plan FR-03 | HIGH | Integration test: low-confidence query produces specific clarifying questions |
| FR-143 | The system SHALL implement progressive context gathering: HyDE expansion → sparse-only → live sources → clarification when initial retrieval < MIN_CHUNKS_THRESHOLD (default 3) | requirements-and-sprint-plan FR-23 | HIGH | Integration test: each progressive step logged and attempted |

### Knowledge Status

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-144 | Every chat response SHALL include a `rag_knowledge_status` field with: status (sufficient/partial/insufficient/absent), chunks_found, chunks_used, confidence_threshold_met | requirements-and-sprint-plan FR-01 | HIGH | Integration test: all four fields present and correct for each scenario |
| FR-145 | When `rag_knowledge_status` is `insufficient` or `absent`, the response body SHALL clearly signal this to the client | requirements-and-sprint-plan FR-01 | HIGH | Integration test: insufficient retrieval produces clear signal |

### Multi-Language & i18n

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-146 | The system SHALL support full i18n with response generation in RU, EN, DE, FR, ZH via `lang` parameter | rag-maturity-assessment L5, roadmap Phase 8.7 | HIGH | Integration test: `lang=de` produces German response |
| FR-147 | The system SHALL maintain cross-lingual retrieval benchmarks (MRR > 0.75 for all supported languages) | rag-maturity-assessment L5, roadmap Phase 8.7 | HIGH | Evaluation pipeline: per-language MRR within target |
| FR-148 | Documentation SHALL be available in RU and EN with a language switcher | AGENTS.md | HIGH | Check: docs/en/ and docs/ru/ directories populated |

### Deployment & Infra

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-149 | The system SHALL be deployable via Docker Compose with all services (proxy, Qdrant, Neo4j, Redis, MinIO, MLflow) | AGENTS.md, README | CRITICAL | `docker-compose up -d` → all services healthy |
| FR-150 | The system SHALL provide a Helm chart for Kubernetes deployment with HPA, probes, config maps, secrets, network policies | best-practices-checklist 7.4, roadmap Phase 7.5 | CRITICAL | `helm template` renders valid manifests |
| FR-151 | The ETL pipeline SHALL be deployable as a separate Helm component (`etl.enabled: true`) with WAL PVC, config mount, cron schedule, resource limits | requirements-and-sprint-plan FR-16 | HIGH | Helm template renders ETL resources |
| FR-152 | The system SHALL provide a unified `docker-compose.distributed.yml` for multi-machine deployment | requirements-and-sprint-plan FR-16 | HIGH | `docker-compose config` validates the distributed compose |
| FR-153 | MinIO SHALL be deployable via Helm chart (`minio.enabled: true`) for model artifacts, backup storage, and file uploads | requirements-and-sprint-plan FR-20 | HIGH | Helm template renders MinIO with PVC and bucket creation |
| FR-154 | PostgreSQL SHALL be deployable via Helm chart for structured data (user DB, feedback store) | requirements-and-sprint-plan FR-20 | HIGH | Helm template renders PostgreSQL |
| FR-155 | A single shared Redis instance SHALL serve both proxy and OpenWebUI with namespaced keys | requirements-and-sprint-plan FR-21 | HIGH | Integration test: proxy and OWUI keys don't collide |
| FR-156 | The system SHALL provide a setup wizard (`setup.sh`) with interactive dependency checks, configuration, Docker startup, collection initialization, and health verification | deployment-guide 2 | HIGH | Run setup.sh: all steps complete successfully |

### File Management (MinIO)

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-157 | The system SHALL expose file upload/download/delete endpoints via MinIO with presigned URL support and three buckets: rag-documents, rag-artifacts, open-webui | ADR-014, AGENTS.md | HIGH | curl test: upload → list → download → presigned URL → delete |

### Widget & Integration

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-158 | The system SHALL provide an embeddable chat widget at `/v1/widget` (HTML) and `/v1/widget.js` (standalone JS) | AGENTS.md | MEDIUM | Browser: widget loads and sends messages |
| FR-159 | The system SHALL integrate with OpenWebUI via OpenAI-compatible API connection with shared Qdrant, MinIO file storage, and tool server registration | ADR-012, AGENTS.md | HIGH | Integration test: OpenWebUI queries reach proxy and return answers |

### Observability

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-160 | The system SHALL expose Prometheus metrics at `/metrics` with counters, histograms, and gauges (12+ metrics) | AGENTS.md, best-practices-checklist 4.1 | CRITICAL | curl /metrics: all rag_* metrics present |
| FR-161 | The system SHALL support structured JSON logging (LOG_FORMAT=json) with secret masking, component logger names, and request ID propagation | best-practices-checklist 4.2 | CRITICAL | Check: JSON log lines have required fields, secrets masked |
| FR-162 | The system SHALL provide Grafana dashboard JSON for request rate, latency percentiles, error rate, cache hits, token usage, confidence distribution, and feedback stats | best-practices-checklist 4.6 | HIGH | Import JSON → panels populate with data |
| FR-163 | The system SHALL provide Prometheus alert rules for: p95 latency > 5s, error rate > 5%, LLM unavailable > 2 min, Qdrant unavailable > 1 min, cache hit ratio < 20% | best-practices-checklist 4.5 | HIGH | promtool check rules passes |
| FR-164 | The system SHALL implement distributed tracing via OpenTelemetry SDK with W3C traceparent propagation across all endpoints | best-practices-checklist 4.4 | HIGH | Check: trace_id and span_id in logs and headers |

### Backup & Disaster Recovery

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-165 | The system SHALL provide automated backup scripts for Qdrant snapshots (6h), Neo4j dumps (6h), Redis RDB (1h), and ETL WAL state (30min) with S3/MinIO destination | best-practices-checklist 5.5, disaster-recovery-runbook | CRITICAL | Check: backup files present in S3 bucket |
| FR-166 | The system SHALL provide a disaster recovery runbook covering 8 scenarios: Qdrant loss, Neo4j loss, Redis loss, node failure, network partition, complete outage, LLM backend failure, disk full | disaster-recovery-runbook | CRITICAL | DR drill: runbook steps executed, system recovered within RTO |
| FR-167 | The system SHALL support restore from backup via `restore_all.sh` with --latest flag | disaster-recovery-runbook | CRITICAL | DR drill: restore completes successfully |

### Performance Optimization

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-168 | The system SHALL use Qdrant scalar quantization (INT8 default) for vector storage to reduce memory by 4× | requirements-and-sprint-plan FR-17, performance-quality 1.2 | HIGH | Metric: Qdrant memory usage ≤50% of unquantized |
| FR-169 | The system SHALL use Qdrant gRPC client (prefer_grpc=True) with HTTP fallback for lower latency (≥30% improvement vs HTTP) | requirements-and-sprint-plan FR-18 | HIGH | Metric: p50 retrieval latency < 130ms via gRPC |
| FR-170 | The system SHALL enable vLLM prefix caching (`--enable-prefix-caching`) to reduce TTFT by ≥50% for repeated system prompts | requirements-and-sprint-plan FR-19 | HIGH | Metric: TTFT for cached prompts < 50% of uncached |
| FR-171 | The system SHALL configure HNSW parameters per collection size: m=16-32, ef_construct=128-256, ef_search=64-200 | requirements-and-sprint-plan FR-24, performance-quality 1.1 | HIGH | Benchmark: recall@10 within documented ranges |
| FR-172 | The system SHALL implement response compression (gzip level 6 default, brotli level 4 optional) with 60%+ JSON reduction and <5ms CPU overhead | best-practices-checklist 6.10, performance-quality 11 | HIGH | curl: Content-Encoding header present, size reduced |
| FR-173 | The system SHALL implement model warm-up via `POST /v1/admin/warmup` eliminating cold-start latency (first request = subsequent) | best-practices-checklist 6.8, performance-quality 12 | HIGH | Metric: first request latency within 100ms of 10th request |

### Multi-Modal

| ID | Description | Source | Priority | Verification |
|----|------------|--------|----------|-------------|
| FR-174 | The system SHALL support code-aware AST-based chunking for Python/JS/Java at function/class level | roadmap Phase 5.2 | HIGH | Unit test: code chunks preserve function boundaries |
| FR-175 | The system SHALL extract and parse tables from Confluence/Jira into structured representations | roadmap Phase 5.3 | HIGH | Integration test: table query returns structured data |

---

## NFR (Non-Functional Requirements)

### NFR-P: Performance

| ID | Description | Target | Source | Measurement |
|----|------------|--------|--------|-------------|
| NFR-P01 | End-to-end request latency (p95) | < 5s overall; < 2s simple; < 8s agentic | SLI/SLO, best-practices-checklist 6.6 | Prometheus histogram `rag_request_duration_seconds` |
| NFR-P02 | Retrieval latency (p95) | < 200ms HTTP, < 130ms gRPC | requirements-and-sprint-plan NFR-1.1 | Prometheus histogram `retrieval_duration_seconds` |
| NFR-P03 | Time-To-First-Token (p50 streaming) | < 1s (cached), < 2s (uncached), < 5s (agentic) | SLI/SLO, performance-quality 10.1 | Prometheus `rag_ttft_seconds` |
| NFR-P04 | Embedding cache hit ratio | ≥ 60% | requirements-and-sprint-plan NFR-1.4 | Prometheus `rag_cache_hit_ratio{cache_type="embedding"}` |
| NFR-P05 | Response cache hit ratio | ≥ 30% | best-practices-checklist 6.2 | Prometheus counter |
| NFR-P06 | Reranker latency (p95) | < 200ms for top-50→top-20 | best-practices-checklist 6.3 | Prometheus `rag_rerank_duration_seconds` |
| NFR-P07 | Qdrant memory (quantized) | ≤ 50% of unquantized | requirements-and-sprint-plan NFR-1.3 | Qdrant /metrics |
| NFR-P08 | vLLM prefix cache hit rate | ≥ 40% for system prompt tokens | requirements-and-sprint-plan NFR-1.5 | vLLM metrics endpoint |
| NFR-P09 | ETL OCR throughput | ≤ 5 min per 100-page scanned PDF | requirements-and-sprint-plan NFR-1.6 | ETL job logs |
| NFR-P10 | ETL streaming end-to-end latency | < 5s (webhook → searchable) | roadmap Phase 6, performance-quality 9.1 | Prometheus `rag_etl_stream_processing_duration_seconds` |
| NFR-P11 | Response compression reduction | ≥ 60% for JSON/text | best-practices-checklist 6.10 | Content-Length comparison |
| NFR-P12 | Warm-up duration | < 30s (embedder + reranker + SLM) | best-practices-checklist 6.8 | Prometheus `rag_warmup_duration_seconds` |
| NFR-P13 | Retrieval quality regression under quantization | MRR drop ≤ 2% | requirements-and-sprint-plan NFR-1.7 | Evaluation pipeline |

### NFR-A: Availability & Reliability

| ID | Description | Target | Source | Measurement |
|----|------------|--------|--------|-------------|
| NFR-A01 | Service availability | 99.5% (~3.6h downtime/month) | SLI/SLO | Prometheus `up{job="rag-proxy"}` |
| NFR-A02 | Error rate (5xx) | < 1% of requests | SLI/SLO | Prometheus `rag_requests_total{status=~"5.."}` |
| NFR-A03 | Backup RPO (Recovery Point Objective) | < 1 hour | SLI/SLO, disaster-recovery-runbook | Backup schedule verification |
| NFR-A04 | Backup RTO (Recovery Time Objective) | < 30 min | SLI/SLO, disaster-recovery-runbook | DR drill timing |
| NFR-A05 | Graceful degradation: proxy never crashes on component failure | Always return best available answer | AGENTS.md, ADR-011 | Chaos tests pass for all component failures |
| NFR-A06 | ETL WAL survival across restarts | Resume from checkpoint | requirements-and-sprint-plan NFR-3.4 | Integration test: restart ETL, verify resume |

### NFR-S: Security

| ID | Description | Target | Source | Measurement |
|----|------------|--------|--------|-------------|
| NFR-S01 | Authentication | JWT access+refresh, Keycloak OIDC, LDAP/AD, API keys | AGENTS.md, access-control-rbac | Integration test: all 4 methods authenticate |
| NFR-S02 | RBAC enforcement | 4 roles (admin/expert/user/read-only), 5 access levels (public→secret) | AGENTS.md, access-control-rbac 3-4 | Integration test: unauthorized requests return 403 |
| NFR-S03 | ACL pushed to Qdrant query level | Access filter in every query | requirements-and-sprint-plan NFR-2.1 | Integration test: restricted user query includes Qdrant filter |
| NFR-S04 | RBAC enabled by default | All endpoints require auth unless explicitly public | requirements-and-sprint-plan NFR-2.4 | Integration test: unauthenticated → 401 |
| NFR-S05 | Secret masking in logs | All credentials masked with `***` | best-practices-checklist 3.1 | grep logs for secret values |
| NFR-S06 | Rate limiting | Configurable per-IP token bucket with burst | best-practices-checklist 3.2 | curl: 101st request in window → 429 |
| NFR-S07 | Input validation | Query ≤ 10K chars, messages ≤ 100, non-empty content, valid JSON | best-practices-checklist 3.5 | curl: malformed input → 400 |
| NFR-S08 | Dependency scanning | Zero known CVEs; CI fails on critical | best-practices-checklist 3.6 | `pip-audit` or `safety check` in CI |
| NFR-S09 | HTTPS/TLS | TLS 1.3 at reverse proxy, HSTS header, HTTP→HTTPS redirect | best-practices-checklist 3.7 | curl: HSTS header present |
| NFR-S10 | Audit logging | All auth events, admin actions, config changes logged with user/timestamp/IP | best-practices-checklist 3.10 | audit.jsonl populated |
| NFR-S11 | Secrets in K8s Secrets | MinIO/PostgreSQL credentials in secrets, not configmaps | requirements-and-sprint-plan NFR-2.5 | Helm template: secret refs, not literals |
| NFR-S12 | Feedback abuse prevention | 100 submissions/user/hour | requirements-and-sprint-plan NFR-2.3 | Rate limiter: 101st rejected |
| NFR-S13 | Shell tool safety | Whitelist-based (allowed_commands, allowed_paths, no shell metacharacters in params) | ADR-009 ADR-009-6 | Unit test: unsafe shell tool rejected at validation |
| NFR-S14 | Tool handler functions never exposed via API | Raw callables not serialized | ADR-009 3.3 | curl /v1/tools/{name}: no handler field in response |

### NFR-D: Deployability

| ID | Description | Target | Source | Measurement |
|----|------------|--------|--------|-------------|
| NFR-D01 | Docker Compose deployment | Single `docker-compose up -d` starts all services | best-practices-checklist 7.1 | All health checks pass |
| NFR-D02 | Helm chart completeness | Covers proxy, ETL, Qdrant, Redis, Neo4j, MinIO, PostgreSQL, vLLM | requirements-and-sprint-plan NFR-3.1 | `helm template` renders all components |
| NFR-D03 | Distributed Compose | Single `docker-compose.distributed.yml` for multi-machine | requirements-and-sprint-plan NFR-3.2 | `docker-compose config` validates |
| NFR-D04 | Zero-downtime deployment (K8s) | Rolling update: start new, wait healthy, drain old | best-practices-checklist 7.7 | ab test: 0 failures during deploy |
| NFR-D05 | Environment-based configuration | All settings via env vars or .env, no hardcoded hostnames/ports | best-practices-checklist 7.2 | grep: no hardcoded localhost in config |
| NFR-D06 | Air-gapped compatibility | All models and dependencies pre-downloadable | requirements-and-sprint-plan NFR-3.5, AGENTS.md | `download_models_offline.py` includes all models |

### NFR-M: Maintainability

| ID | Description | Target | Source | Measurement |
|----|------------|--------|--------|-------------|
| NFR-M01 | Runtime configuration | Non-secret settings hot-reloadable | requirements-and-sprint-plan NFR-4.1 | PATCH config → effect without restart |
| NFR-M02 | Stale document monitoring | Automated detection every 24h | requirements-and-sprint-plan NFR-4.2 | Cron schedule verification |
| NFR-M03 | Reindexing resilience | Retry 3× with exponential backoff | requirements-and-sprint-plan NFR-4.3 | ETL log: 3 retries then DLQ |
| NFR-M04 | Cache key namespacing | No collisions between proxy and OpenWebUI | requirements-and-sprint-plan NFR-4.4 | Redis keys: proxy:* vs openwebui:* |
| NFR-M05 | Feedback data preservation through reindex | Corrections survive reindex | requirements-and-sprint-plan NFR-4.5 | Integration test: feedback preserved after reindex |
| NFR-M06 | Code quality | ruff lint 0 warnings, ruff format 333 files clean, mypy strict 0 errors, 80% coverage | best-practices-checklist 1, pyproject.toml | `make lint && make typecheck && make test` |
| NFR-M07 | Test suite | 3,468 tests, 80% coverage, CI green | roadmap | `make test` exits 0 |
| NFR-M08 | Log rotation | 100MB per file, keep 10 files, compress old | best-practices-checklist 4.10 | LOG_DIR files under limits |

### NFR-Q: Quality

| ID | Description | Target | Source | Measurement |
|----|------------|--------|--------|-------------|
| NFR-Q01 | Retrieval MRR | > 0.80 | rag-maturity-assessment 7.1 | Evaluation pipeline: `evaluate_retrieval.py` |
| NFR-Q02 | Retrieval Recall@20 | > 0.90 | rag-maturity-assessment 7.1 | Evaluation pipeline |
| NFR-Q03 | Retrieval nDCG@10 | > 0.85 | rag-maturity-assessment 7.1 | Evaluation pipeline |
| NFR-Q04 | Retrieval Precision@5 | > 0.70 | rag-maturity-assessment 7.1 | Evaluation pipeline |
| NFR-Q05 | Context grounding score | > 0.70 for well-grounded | rag-maturity-assessment 7.1 | Cosine similarity(embed(answer), embed(context)) |
| NFR-Q06 | Hallucination rate | < 5% across all query types | rag-maturity-assessment, roadmap Phase 8.4 | NLI entailment check |
| NFR-Q07 | Chunker semantic coherence | > 0.75 intra-chunk cosine | performance-quality 4.1 | Chunker evaluation |
| NFR-Q08 | Chunker boundary precision | > 0.85 at section/heading breaks | performance-quality 4.1 | Chunker evaluation |
| NFR-Q09 | Confidence > 0.5 rate | > 70% of responses | SLI/SLO | Prometheus `rag_confidence_score_high_ratio` |
| NFR-Q10 | Self-reflection score correlation with expert feedback | Statistically significant | rag-maturity-assessment L5.4 | A/B comparison |
| NFR-Q11 | Model evolution eval gate thresholds | SLM F1≥0.85, LLM BertScore≥0.70, hallucination≤0.05, Rouge-L≥0.35 | ADR-010 3.4 | EvalGate run |

### NFR-C: Capacity & Scalability

| ID | Description | Target | Source | Measurement |
|----|------------|--------|--------|-------------|
| NFR-C01 | Concurrent users | 50 concurrent (p95 < 5s) | roadmap Phase 7.2 | Load test |
| NFR-C02 | Qdrant collection size | < 1M vectors (default HNSW), > 1M with quantization | performance-quality 1.1 | Collection stats |
| NFR-C03 | Qdrant sharding | 4 shards for 10M-50M, 8 shards > 50M vectors | performance-quality 6.2 | Collection config |
| NFR-C04 | ETL parallel extraction | 3 Confluence workers, 5 Jira workers, 3 GitLab workers | performance-quality 6.3 | Thread count monitoring |
| NFR-C05 | Cold storage | Keep current + 1 prior version in Qdrant, older in Parquet | performance-quality 6.4 | Version manifest |

---

## Constraints (CON)

| ID | Description | Source | Rationale |
|----|------------|--------|-----------|
| CON-01 | **Air-gapped first.** All models must be pre-downloaded. No external API calls at runtime. System must function fully offline. | AGENTS.md, README, ADR-001, ADR-008 | Corporate security policy; offline deployment requirement |
| CON-02 | **Graceful degradation.** Every component can fail independently. Neo4j unavailable → skip graph expansion. Reranker OOM → use raw hybrid scores. Redis down → in-memory cache. Proxy never crashes on component failure. | AGENTS.md, ADR-011 | Resilience requirement; system must operate in degraded environments |
| CON-03 | **Single worker proxy.** `WORKERS=1` to protect shared embedder/cache state. | AGENTS.md, ADR-004, ADR-008 | Prevents race conditions on in-process singleton models |
| CON-04 | **Python/FastAPI for proxy.** Java/Quarkus migration formally rejected (ADR-008). All ML components require Python ecosystem (sentence-transformers, HuggingFace, torch). | ADR-008 | ML ecosystem dominance; Python optimization path addresses concerns |
| CON-05 | **BAAI/bge-m3 as sole embedding model.** Dense (1024-dim) + sparse (lexical) + ColBERT multi-vectors; 8192 token context; 100+ languages. | ADR-001 | Single model for both indexing and retrieval; no synchronization needed |
| CON-06 | **Qdrant as primary vector store.** Hybrid search via RRF. No separate BM25 index. On-disk sparse index. | ADR-002 | Single deployment for dense+sparse; REST API; incremental upsert |
| CON-07 | **OpenAI-compatible API.** All endpoints follow OpenAI protocol. RAG extensions silently ignored by standard clients. | ADR-004 | Drop-in replacement for any OpenAI client; zero client changes |
| CON-08 | **Content-addressable chunks.** SHA-256 hashing for deduplication and versioning. Hash as Qdrant point ID. | ADR-005 | Eliminates duplicates; enables incremental updates |
| CON-09 | **WAL-based incremental ETL.** Checkpointing per pipeline stage. Resume after failure without data loss. | ADR-005, ADR-011 | Incremental by default; only changed documents reindexed |
| CON-10 | **Optional complexity.** LangGraph, Neo4j, Redis all optional. System runs in simple RAG mode by default. All advanced features default to `false`. | AGENTS.md, ADR-011 | Low barrier to entry; progressive adoption |
| CON-11 | **Dual-model routing.** SLM for fast preprocessing (< 100ms), LLM for generation. Heuristic fallback when SLM unavailable. | ADR-003 | Balances latency and quality; efficient GPU utilization |
| CON-12 | **Multi-provider LLM backend.** Pluggable adapters for vLLM, llama.cpp, Anthropic, Ollama, generic OpenAI-compatible. | AGENTS.md, ADR-004 | Deployment flexibility; no vendor lock-in |
| CON-13 | **Token economy.** BPE-aware counting, 4 compression strategies, smart budget allocation. Every token counts. | AGENTS.md | Cost optimization; context window efficiency |
| CON-14 | **Python 3.11+.** Minimum Python version for the entire project. | pyproject.toml, README | Language version constraint |
| CON-15 | **Ruff for linting/formatting.** line-length=120, double quotes, select rules: E, F, I, N, W, UP, B, C4, SIM | pyproject.toml | Code style enforcement |
| CON-16 | **mypy strict mode** for proxy/app/. ETL modules have relaxed strictness. | pyproject.toml | Type safety requirement |
| CON-17 | **Coverage ≥ 80%.** fail_under=80 with exclusions for streaming pipeline, FLARE, RAGAS, query router, RAPTOR, community detection. | pyproject.toml | Testing quality gate |
| CON-18 | **granian ASGI server** (not uvicorn) for production. Rust-based, ~5× faster startup. | ADR-008, Makefile | Performance optimization |
| CON-19 | **MinIO for object storage.** S3-compatible, air-gapped, three buckets (rag-documents, rag-artifacts, open-webui). | ADR-014, ADR-010 ADR-ME-005 | Centralized artifact and file storage |
| CON-20 | **MLflow for experiment tracking.** Self-hosted, S3-compatible (MinIO) artifact store, built-in model registry. | ADR-010 ADR-ME-001 | Experiment reproducibility; model lifecycle management |
| CON-21 | **LoRA/QLoRA for fine-tuning.** Not full fine-tune. LoRA rank=8 (SLM), QLoRA rank=16 4-bit NF4 (LLM), LoRA rank=4 (Reranker). | ADR-010 ADR-ME-002 | Small swappable adapters; single GPU inference compatibility |
| CON-22 | **Application-layer canary** (not load balancer). Weighted random traffic split with Prometheus-driven rollback. | ADR-010 ADR-ME-004 | Single-worker proxy design; instantaneous rollback |
| CON-23 | **Hot-reload via file watcher + SIGHUP** (not gRPC service mesh). Adapter lifecycle: UNLOADED→LOADING→ACTIVE→DRAINING→RETIRING. | ADR-010 ADR-ME-003 | Process-local swap; zero request loss; simple Unix pattern |
| CON-24 | **HITL feedback → fine-tuning closed loop.** Export training datasets from HITL logs. Expert corrections drive SLM/LLM/Reranker improvement. | ADR-007, ADR-010 | Continuous quality improvement; domain adaptation |
| CON-25 | **English for code and comments.** Documentation bilingual (RU + EN). | AGENTS.md | Team language policy |
| CON-26 | **FastMCP for MCP server.** Three tools (rag_search, rag_chat, rag_feedback), dual transport (STDIO + HTTP), standalone deployment. | ADR-013 | Standard MCP protocol; IDE integration |
| CON-27 | **Streamlit for HITL dashboard.** Expert review, feedback submission, training dataset export. | ADR-007 | Lightweight; Python-native; no additional infrastructure |
| CON-28 | **SQLite for user database and KB metadata** (not PostgreSQL by default). PostgreSQL in Helm chart as optional upgrade. | AGENTS.md, requirements-and-sprint-plan FR-20 | Simplicity for single-node; upgrade path for production |

---

## Decision Records (DEC)

Architectural decisions from ADRs that MUST be respected in all future development:

| ID | Decision | ADR | Key Mandate |
|----|----------|-----|-------------|
| DEC-01 | Use BAAI/bge-m3 as the sole embedding model for both indexing and retrieval | ADR-001 | No alternative embedder may be introduced without a new ADR |
| DEC-02 | Qdrant is the primary vector store; hybrid search via RRF with k=60 | ADR-002 | No separate BM25 index, no alternative vector DB |
| DEC-03 | Dual-model architecture: SLM for routing + LLM for generation | ADR-003 | Both models served from same inference endpoint, distinguished by model name |
| DEC-04 | OpenAI-compatible proxy pattern; RAG extensions are additive, silently ignored by standard clients | ADR-004 | No breaking changes to `/v1/chat/completions` contract |
| DEC-05 | Version-aware indexing via SHA-256 content-addressable chunks with hot/cold storage stratification | ADR-005 | Always hash-based; always incremental |
| DEC-06 | LangGraph for agentic orchestration (10-node graph), optional, fallback to linear pipeline | ADR-006 | LangGraph is opt-in; linear pipeline must always work |
| DEC-07 | HITL feedback via async JSONL logging + Streamlit dashboard + training dataset export | ADR-007 | Feedback logging is always non-blocking; JSONL format |
| DEC-08 | Python/FastAPI for proxy (Java/Quarkus rejected) | ADR-008 | No JVM components in the proxy layer; Python-native optimization |
| DEC-09 | Agentic tools expansion: unified ToolDefinition, @tool SDK, declarative YAML/JSON, OpenAPI discovery, parallel execution | ADR-009 | No monolithic tools.py; subpackage structure; backward-compat shim |
| DEC-10 | Model evolution: LoRA/QLoRA fine-tuning, MLflow tracking, MinIO artifacts, EvalGate CI/CD, AdapterManager hot-reload, CanaryController traffic split | ADR-010 | All gated behind MODEL_EVOLUTION_ENABLED=false by default |
| DEC-11 | Incremental/progressive architecture: 3 tiers (Minimal Core → Enhanced Retrieval → Advanced Orchestration), all optional features default off | ADR-011 | Every feature toggle must have an `if enabled:` guard; fallback path always tested |
| DEC-12 | OpenWebUI integration as first-class frontend with shared Qdrant, MinIO file storage, OpenAI-compatible API | ADR-012 | Consistent search results via shared Qdrant |
| DEC-13 | Standalone MCP server with dual transport (STDIO + HTTP) for IDE integration | ADR-013 | Must run independently of proxy; must support OpenCode and Claude Desktop |
| DEC-14 | MinIO as S3-compatible object storage for documents, artifacts, and file uploads | ADR-014 | Three buckets; presigned URL support; air-gapped deployment |
| DEC-15 | MLflow for experiment tracking (ADR-ME-001); LoRA/QLoRA for fine-tuning (ADR-ME-002); File watcher + SIGHUP hot-reload (ADR-ME-003); Application-layer canary (ADR-ME-004); MinIO for artifacts (ADR-ME-005) | ADR-010 | All sub-decisions binding |

---

## Traceability Summary

| Source | FR Coverage | NFR Coverage | DEC Coverage |
|--------|-------------|--------------|--------------|
| ADR-001 (bge-m3) | FR-09, FR-13 | CON-05 | DEC-01 |
| ADR-002 (Qdrant) | FR-09, FR-10 | CON-06 | DEC-02 |
| ADR-003 (Dual LLM) | FR-64, FR-65, FR-66 | CON-11 | DEC-03 |
| ADR-004 (OpenAI Proxy) | FR-01-08 | CON-07 | DEC-04 |
| ADR-005 (Versioning) | FR-12, FR-44-47 | CON-08, CON-09 | DEC-05 |
| ADR-006 (LangGraph) | FR-19, FR-21, FR-26-29 | CON-10 | DEC-06 |
| ADR-007 (HITL) | FR-73-78 | CON-24, CON-27 | DEC-07 |
| ADR-008 (Java rejected) | — | CON-04, CON-18, CON-03 | DEC-08 |
| ADR-009 (Tools) | FR-111-120 | NFR-S13, NFR-S14 | DEC-09 |
| ADR-010 (Model Evolution) | FR-95-102, FR-126-136 | NFR-Q11, CON-19-23 | DEC-10, DEC-15 |
| ADR-011 (Incremental) | FR-24, FR-29 | CON-10 | DEC-11 |
| ADR-012 (OpenWebUI) | FR-159 | — | DEC-12 |
| ADR-013 (MCP) | FR-121-125 | CON-26 | DEC-13 |
| ADR-014 (MinIO) | FR-110, FR-157 | CON-19 | DEC-14 |
| AGENTS.md | All core FRs | CON-01-03, CON-25 | — |
| README | FR-40, FR-149 | — | — |
| Requirements & Sprint Plan S5 | FR-61, FR-62, FR-79-83, FR-104-109, FR-137-145, FR-149-155, FR-168-171 | NFR-P02, NFR-P04-09, NFR-S01-12, NFR-D01-06, NFR-M01-05 | — |
| RAG Maturity Assessment | FR-09-18, FR-26-39, FR-146-147 | NFR-Q01-10 | — |
| Best Practices Checklist | FR-73-78, FR-84-94, FR-160-164, FR-172-173 | NFR-P01-13, NFR-A01-06, NFR-S01-14, NFR-D01-06, NFR-M06-08 | — |
| SLI/SLO | — | NFR-A01-03, NFR-Q09 | — |
| Performance & Quality | FR-40-42, FR-64-72, FR-168-173 | NFR-P01-13, NFR-Q06-08 | — |
| Disaster Recovery Runbook | FR-165-167 | NFR-A04-05 | — |
| Deployment Guide | FR-149-156 | NFR-D01-03, NFR-D06 | — |
| ETL Operations | FR-40-63 | — | — |
| Knowledge Graph Strategy | FR-19-25 | — | — |
| Access Control & RBAC | FR-84-94 | NFR-S01-05 | — |
| Model Evolution Guide | FR-126-136 | NFR-Q11 | — |
| Roadmap | FR-14-18, FR-20-23, FR-32-39, FR-146-147, FR-174-175 | NFR-C01-05 | — |

---

**Total Requirements:** 175 FR + 50 NFR + 28 CON + 15 DEC = **268 traceable items**
