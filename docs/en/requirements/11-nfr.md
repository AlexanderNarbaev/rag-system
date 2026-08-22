# Part 2. Non-Functional Requirements (NFR)

---

## NFR-P: Performance

### NFR-P01. End-to-end latency p95 < 5s

**Description:**
Total time from request to response (p95) < 5 seconds for a regular request,
< 2 seconds for a simple one, < 8 seconds for an agentic one (with tool calls).

**Acceptance criteria:**

1. Prometheus histogram `rag_request_duration_seconds` p95 < 5s
2. Load test: 50 concurrent users, p95 < 5s

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** SLI/SLO

---

### NFR-P02. Retrieval latency p95 < 200ms

**Description:**
Hybrid search time in Qdrant (p95) < 200ms over HTTP, < 130ms over gRPC.

**Acceptance criteria:**

1. Prometheus `retrieval_duration_seconds` p95 < 0.2s
2. With gRPC — p95 < 0.13s

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P02

---

### NFR-P03. TTFT p50 < 1s (cached)

**Description:**
Time To First Token (p50) < 1s for cached responses, < 2s for uncached.

**Acceptance criteria:**

1. Prometheus `rag_ttft_seconds` p50 < 1s (cached)
2. Prometheus `rag_ttft_seconds` p50 < 2s (uncached)

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** SLI/SLO

---

### NFR-P04. Embedding cache hit ratio ≥ 60%

**Description:**
≥ 60% of requests must hit the embedding cache.

**Acceptance criteria:**

1. Prometheus `rag_cache_hit_ratio{cache_type="embedding"}` ≥ 0.6

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P04

---

### NFR-P05. Response cache hit ratio ≥ 30%

**Description:**
≥ 30% of requests must hit the response cache.

**Acceptance criteria:**

1. Prometheus counter ≥ 30% hit ratio

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P05

---

### NFR-P06. Reranker latency p95 < 200ms

**Description:**
Reranking top-50 → top-20 (p95) < 200ms.

**Acceptance criteria:**

1. Prometheus `rag_rerank_duration_seconds` p95 < 0.2s

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P06

---

### NFR-P07. Qdrant memory (quantized) ≤ 50%

**Description:**
With INT8 quantization, memory consumption ≤ 50% of the non-quantized one.

**Acceptance criteria:**

1. Qdrant /metrics shows ≤ 50% memory usage

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P07

---

### NFR-P08. vLLM prefix cache hit ≥ 40%

**Description:**
≥ 40% of system prompt tokens must hit the prefix cache.

**Acceptance criteria:**

1. The vLLM metrics endpoint shows ≥ 40% hit rate

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P08

---

### NFR-P09. ETL OCR throughput ≤ 5min/100 pages

**Description:**
OCR of a 100-page PDF ≤ 5 minutes.

**Acceptance criteria:**

1. A 100-page PDF — processing ≤ 5 min

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P09

---

### NFR-P10. ETL streaming latency < 5s

**Description:**
From webhook event to searchable chunk — < 5 seconds.

**Acceptance criteria:**

1. Prometheus `rag_etl_stream_processing_duration_seconds` < 5s

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P10

---

### NFR-P11. Response compression ≥ 60% ✅

**Description:**
Gzip/Brotli compresses JSON responses by ≥ 60%.

**Acceptance criteria:**

1. Content-Length comparison: compressed ≤ 40% of original

**Status:** ✅ Confirmed
**Reference:** NFR-P11

---

### NFR-P12. Warm-up duration < 30s

**Description:**
Warming up all models (embedder + reranker + SLM) < 30 seconds.

**Acceptance criteria:**

1. Prometheus `rag_warmup_duration_seconds` < 30s

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P12

---

### NFR-P13. Retrieval quality under quantization — MRR drop ≤ 2%

**Description:**
INT8 quantization must not reduce MRR by more than 2%.

**Acceptance criteria:**

1. MRR(quantized) ≥ MRR(full) - 0.02

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-P13

---

## NFR-A: Availability

### NFR-A01. Service availability 99.5%

**Description:**
The system is available 99.5% of the time (~3.6 hours of downtime/month).

**Acceptance criteria:**

1. Prometheus `up{job="rag-proxy"}` ≥ 99.5%

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** SLI/SLO

---

### NFR-A02. Error rate 5xx < 1%

**Description:**
< 1% of requests return 5xx.

**Acceptance criteria:**

1. Prometheus `rag_requests_total{status=~"5.."}` / total < 0.01

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** SLI/SLO

---

### NFR-A03. Backup RPO < 1 hour

**Description:**
Maximum data loss on failure — 1 hour.

**Acceptance criteria:**

1. Backup schedule: Qdrant 6h, Neo4j 6h, Redis 1h, WAL 30min
2. Redis backup — RPO < 1h

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** SLI/SLO

---

### NFR-A04. Backup RTO < 30 min

**Description:**
Restore from backup — < 30 minutes.

**Acceptance criteria:**

1. DR drill: restore_all.sh — completes in < 30 min

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** SLI/SLO

---

### NFR-A05. Graceful degradation

**Description:**
The proxy does NOT crash when any component is unavailable. Neo4j down → skip graph.
Reranker OOM → use raw scores. Redis down → in-memory cache.

**Acceptance criteria:**

1. Chaos test: each component down — the proxy responds 200

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** CON-02

---

### NFR-A06. ETL WAL survival

**Description:**
ETL resumes from the last checkpoint after a failure.

**Acceptance criteria:**

1. Kill ETL at the embedding stage — restart begins from embedding

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** CON-09

---

## NFR-S: Security

### NFR-S01. 4 auth methods

**Description:**
The system supports: JWT, Keycloak OIDC, LDAP/AD, API keys.

**Acceptance criteria:**

1. Each method — successful authentication

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** access-control-rbac

---

### NFR-S02. RBAC enforcement

**Description:**
4 roles, 5 access levels. Unauthorized → 403.

**Acceptance criteria:**

1. Unauthorized request → 403

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** access-control-rbac

---

### NFR-S03. ACL in Qdrant queries

**Description:**
Every Qdrant query includes an ACL filter.

**Acceptance criteria:**

1. A restricted user — does not see restricted chunks

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-S03

---

### NFR-S04. RBAC by default

**Description:**
All endpoints require auth unless explicitly public.

**Acceptance criteria:**

1. Without a token → 401 on protected endpoints

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-S04

---

### NFR-S05. Secret masking in logs

**Description:**
All credentials are masked in logs (replaced with `***`).

**Acceptance criteria:**

1. grep logs — no secrets in plain text

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** best-practices-checklist 3.1

---

### NFR-S09. HTTPS/TLS

**Description:**
TLS 1.3 on the reverse proxy, HSTS header, HTTP → HTTPS redirect.

**Acceptance criteria:**

1. HSTS header present
2. HTTP redirect → HTTPS

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** best-practices-checklist 3.7

---

### NFR-S10. Audit logging

**Description:**
All auth events, admin actions, and config changes are logged.

**Acceptance criteria:**

1. audit.jsonl contains records

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** best-practices-checklist 3.10

---

### NFR-S11. K8s Secrets

**Description:**
Credentials in K8s Secrets, not in ConfigMaps.

**Acceptance criteria:**

1. Helm template: secret refs, not literals

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-S11

---

### NFR-S12. Feedback abuse prevention

**Description:**
100 feedback submissions/user/hour.

**Acceptance criteria:**

1. 101st submission → 429

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-S12

---

### NFR-S13. Shell tool safety

**Description:**
Shell tools — whitelist-based validation.

**Acceptance criteria:**

1. Unsafe command → rejected at validation

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-S13

---

### NFR-S14. Tool handlers hidden

**Description:**
Raw tool callables are not exposed via the API.

**Acceptance criteria:**

1. `/v1/tools/{name}` — no handler field in the response

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-S14

---

## NFR-D: Deployment

### NFR-D01. Docker Compose — one command

**Description:**
`docker compose up -d` starts all services.

**Acceptance criteria:**

1. All health checks pass

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-D01

---

### NFR-D02. Helm chart completeness

**Description:**
The Helm chart covers: proxy, ETL, Qdrant, Redis, Neo4j, MinIO, PostgreSQL, vLLM.

**Acceptance criteria:**

1. `helm template` renders all components

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-D02

---

### NFR-D03. Distributed Compose

**Description:**
A single `docker-compose.distributed.yml` for multi-machine.

**Acceptance criteria:**

1. `docker-compose config` validates

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-D03

---

### NFR-D04. Zero-downtime K8s deployment

**Description:**
Rolling update: start new, wait healthy, drain old.

**Acceptance criteria:**

1. ab test: 0 failures during deploy

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-D04

---

### NFR-D05. Env-based configuration

**Description:**
All settings via env vars, no hardcoded hostnames/ports.

**Acceptance criteria:**

1. grep: no hardcoded localhost in config

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-D05

---

### NFR-D06. Air-gapped compatibility

**Description:**
All models and dependencies are pre-downloadable.

**Acceptance criteria:**

1. `download_models_offline.py` — all models are downloaded

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** CON-01

---

## NFR-M: Maintainability

### NFR-M01. Runtime configuration hot-reload

**Description:**
Non-secret settings can be changed without a restart.

**Acceptance criteria:**

1. PATCH config → effect without restart

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-M01

---

### NFR-M02. Stale document monitoring

**Description:**
Automatic detection of stale documents every 24 hours.

**Acceptance criteria:**

1. Cron job runs every 24h
2. Stale documents flagged

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-M02

---

### NFR-M03. Reindexing resilience

**Description:**
3 retries with exponential backoff on reindexing errors.

**Acceptance criteria:**

1. Error → 3 retries → DLQ

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-M03

---

### NFR-M04. Cache key namespacing ✅

**Description:**
The proxy and OpenWebUI use different namespace prefixes for Redis keys.

**Acceptance criteria:**

1. Proxy keys: `proxy:*`
2. OpenWebUI keys: `openwebui:*`
3. No collisions

**Status:** ✅ Confirmed
**Reference:** NFR-M04

---

### NFR-M05. Feedback preservation through reindex

**Description:**
Feedback is preserved when documents are reindexed.

**Acceptance criteria:**

1. Reindex → feedback is tied to the new chunk_id

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-M05

---

### NFR-M06. Code quality ✅

**Description:**
ruff lint 0 warnings, ruff format clean, mypy strict 0 errors, 80% coverage.

**Acceptance criteria:**

1. `make lint && make typecheck && make test` — all green

**Status:** ✅ Confirmed
**Reference:** NFR-M06

---

### NFR-M07. Test suite — 80% coverage ✅

**Description:**
≥ 5000 tests, ≥ 80% coverage, CI green.

**Acceptance criteria:**

1. `make test` exits 0
2. Coverage ≥ 80%

**Status:** ✅ Confirmed
**Reference:** NFR-M07

---

### NFR-M08. Log rotation

**Description:**
100MB per file, keep 10 files, compress old ones.

**Acceptance criteria:**

1. LOG_DIR files under limits

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** NFR-M08

---

## NFR-Q: RAG Quality

### NFR-Q01. Retrieval MRR > 0.80

**Description:**
Mean Reciprocal Rank > 0.80 on the evaluation dataset.

**Acceptance criteria:**

1. `evaluate_retrieval.py` — MRR > 0.80

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** rag-maturity-assessment

---

### NFR-Q02. Recall@20 > 0.90

**Description:**
Recall at top-20 > 0.90.

**Acceptance criteria:**

1. `evaluate_retrieval.py` — Recall@20 > 0.90

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** rag-maturity-assessment

---

### NFR-Q03. nDCG@10 > 0.85

**Description:**
Normalized Discounted Cumulative Gain at top-10 > 0.85.

**Acceptance criteria:**

1. `evaluate_retrieval.py` — nDCG@10 > 0.85

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** rag-maturity-assessment

---

### NFR-Q04. Precision@5 > 0.70

**Description:**
Precision at top-5 > 0.70.

**Acceptance criteria:**

1. `evaluate_retrieval.py` — Precision@5 > 0.70

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** rag-maturity-assessment

---

### NFR-Q05. Context grounding score > 0.70

**Description:**
Cosine similarity between the answer and the context > 0.70 for well-grounded answers.

**Acceptance criteria:**

1. Cosine similarity(embed(answer), embed(context)) > 0.70

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** rag-maturity-assessment

---

### NFR-Q06. Hallucination rate < 5%

**Description:**
< 5% of answers contain hallucinations (unsupported claims).

**Acceptance criteria:**

1. NLI entailment check — hallucination rate < 5%

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** rag-maturity-assessment

---

### NFR-Q07. Chunker semantic coherence > 0.75

**Description:**
Intra-chunk cosine similarity > 0.75.

**Acceptance criteria:**

1. Chunker evaluation — coherence > 0.75

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** performance-quality

---

### NFR-Q08. Chunker boundary precision > 0.85

**Description:**
Chunk boundaries match section/heading breaks in > 85% of cases.

**Acceptance criteria:**

1. Chunker evaluation — boundary precision > 0.85

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** performance-quality

---

### NFR-Q09. Confidence > 0.5 rate > 70%

**Description:**
> 70% of answers have confidence > 0.5.

**Acceptance criteria:**

1. Prometheus `rag_confidence_score_high_ratio` > 0.7

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** SLI/SLO

---

### NFR-Q10. Self-reflection correlation with expert feedback

**Description:**
The self-reflection score correlates with expert feedback (statistically significant).

**Acceptance criteria:**

1. A/B comparison — correlation significant

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** rag-maturity-assessment

---

### NFR-Q11. Eval gate thresholds

**Description:**

- SLM: F1 ≥ 0.85
- LLM: BertScore ≥ 0.70, hallucination ≤ 0.05
- Reranker: MRR ≥ baseline + 0.02, Rouge-L ≥ 0.35

**Acceptance criteria:**

1. EvalGate run — thresholds enforced

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** ADR-010

---

## NFR-C: Capacity and Scalability

### NFR-C01. 50 concurrent users (p95 < 5s)

**Description:**
The system handles 50 concurrent users with p95 < 5s.

**Acceptance criteria:**

1. Load test: 50 concurrent — p95 < 5s

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** roadmap Phase 7.2

---

### NFR-C02. Qdrant collection size < 1M vectors

**Description:**
Default HNSW for < 1M vectors. Quantization for > 1M.

**Acceptance criteria:**

1. Collection stats — correct config for size

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** performance-quality

---

### NFR-C03. Qdrant sharding

**Description:**
4 shards for 10M-50M, 8 shards for > 50M vectors.

**Acceptance criteria:**

1. Collection config — correct shards

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** performance-quality

---

### NFR-C04. ETL parallel extraction

**Description:**
3 Confluence workers, 5 Jira workers, 3 GitLab workers.

**Acceptance criteria:**

1. Thread count monitoring — correct workers

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** performance-quality

---

### NFR-C05. Cold storage

**Description:**
Current + 1 prior version in Qdrant, older in Parquet.

**Acceptance criteria:**

1. Version manifest — correct stratification

**Status:** ✅ Infrastructure confirmed (benchmark on minikube)
**Reference:** performance-quality

---

# Part 3. Constraints

| ID     | Description                                                                                                                                         | Rationale                  |
|--------|-----------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------|
| CON-01 | **Air-gapped first.** All models pre-downloaded. No external API calls.                                                                              | Corporate security         |
| CON-02 | **Graceful degradation.** Each component can fail independently.                                                                                     | Resilience                 |
| CON-03 | **Single worker proxy.** `WORKERS=1` to protect shared state.                                                                                        | Race condition prevention  |
| CON-04 | **Python/FastAPI for proxy.** Java/Quarkus rejected.                                                                                                 | ML ecosystem               |
| CON-05 | **BAAI/bge-m3 as sole embedder.** 1024-dim, 100+ languages.                                                                                          | Single model               |
| CON-06 | **Qdrant as primary vector store.** RRF fusion.                                                                                                      | Single deployment          |
| CON-07 | **OpenAI-compatible API.** RAG extensions additive.                                                                                                  | Drop-in replacement        |
| CON-08 | **Content-addressable chunks.** SHA-256 hashing.                                                                                                     | Dedup + versioning         |
| CON-09 | **WAL-based incremental ETL.** Checkpointing per stage.                                                                                              | Resume after failure       |
| CON-10 | **Optional complexity.** LangGraph/Neo4j/Redis optional.                                                                                             | Low barrier                |
| CON-11 | **Dual-model routing.** SLM for routing, LLM for generation.                                                                                         | Latency + quality          |
| CON-12 | **Multi-provider LLM backend.** Pluggable adapters.                                                                                                  | No vendor lock-in          |
| CON-13 | **Token economy.** BPE-aware counting, 4 strategies.                                                                                                 | Cost optimization          |
| CON-14 | **Python 3.11+.** Minimum version.                                                                                                                   | Language constraint        |
| CON-15 | **Ruff for linting.** line-length=120.                                                                                                               | Code style                 |
| CON-16 | **mypy strict mode** for proxy/app/.                                                                                                                 | Type safety                |
| CON-17 | **Coverage ≥ 80%.**                                                                                                                                  | Testing quality            |
| CON-18 | **granian ASGI server** (not uvicorn).                                                                                                               | Performance                |
| CON-19 | **MinIO for object storage.** S3-compatible.                                                                                                         | Air-gapped                 |
| CON-20 | **MLflow for experiment tracking.** Self-hosted.                                                                                                     | Reproducibility            |
| CON-21 | **LoRA/QLoRA for fine-tuning.** Not full fine-tune.                                                                                                  | Small adapters             |
| CON-22 | **Application-layer canary.** Weighted random split.                                                                                                 | Simple rollback            |
| CON-23 | **Hot-reload via file watcher + SIGHUP.**                                                                                                            | Process-local swap         |
| CON-24 | **HITL feedback → fine-tuning closed loop.**                                                                                                         | Continuous improvement     |
| CON-25 | **English for code.** Docs bilingual (RU + EN).                                                                                                      | Team policy                |
| CON-26 | **FastMCP for MCP server.** Dual transport.                                                                                                          | Standard protocol          |
| CON-27 | **Streamlit for HITL dashboard.**                                                                                                                    | Lightweight                |
| CON-28 | **SQLite for user DB.** PostgreSQL optional.                                                                                                         | Simplicity                 |
| CON-29 | **Standard OpenAI protocol first.** All RAG extensions are implemented through standard mechanisms: the `model` field (+RAG suffix), HTTP headers (X-User-ID, X-Forwarded-User), the request `user` field. Extensions unused by standard clients are allowed in the response (rag_sources, rag_confidence) but not in the request. | Drop-in compatibility      |
