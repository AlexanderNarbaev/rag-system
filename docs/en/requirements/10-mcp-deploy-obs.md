# Block J-P. MCP, Deployment, Observability, Performance, Multi-Modal (FR-121 — FR-175)

---

## MCP Server (FR-121 — FR-125)

### FR-121. MCP tools: rag_search, rag_chat, rag_feedback

**Description:**
The MCP server handles 3 tools:

- `rag_search` — knowledge base search (parameter: query)
- `rag_chat` — chat completion via RAG (parameter: messages)
- `rag_feedback` — feedback submission (parameter: feedback_id, type, correction)

**Acceptance criteria:**

1. The MCP client sees all 3 tools
2. `rag_search("query")` — returns the retrieved chunks
3. `rag_chat([{"role":"user","content":"..."}])` — returns an answer
4. `rag_feedback(...)` — submits feedback

**Status:** ✅ Confirmed (`tests/mcp_server/test_mcp_requirements.py::TestFR121MCPTools`)
**Priority:** HIGH
**Reference:** ADR-013

---

### FR-122. MCP resource: rag://collections

**Description:**
The MCP server exposes the `rag://collections` resource — a list of available collections.

**Acceptance criteria:**

1. The MCP client can read the resource
2. It returns a list of collections with metadata

**Status:** ✅ Confirmed (`tests/mcp_server/test_mcp_requirements.py::TestFR122MCPResource`)
**Priority:** MEDIUM
**Reference:** ADR-013

---

### FR-123. MCP prompt: rag_help

**Description:**
The MCP server exposes the `rag_help` prompt with usage instructions.

**Acceptance criteria:**

1. The MCP client can retrieve the prompt
2. The prompt contains a description of all tools and parameters

**Status:** ✅ Confirmed (`tests/mcp_server/test_mcp_requirements.py::TestFR123MCPPrompt`)
**Priority:** MEDIUM
**Reference:** ADR-013

---

### FR-124. Dual transport: STDIO + HTTP

**Description:**
The MCP server supports two transports:

- STDIO (default) — for OpenCode, Claude Desktop
- HTTP — for web clients

**Acceptance criteria:**

1. STDIO mode — the client connects via stdin/stdout
2. HTTP mode — the client connects over HTTP
3. Both transports work simultaneously

**Status:** ✅ Confirmed (`tests/mcp_server/test_mcp_requirements.py::TestFR124DualTransport`)
**Priority:** HIGH
**Reference:** ADR-013

---

### FR-125. Standalone installation

**Description:**
The MCP server is installed as a standalone pip package or script.
Configuration via the `RAG_PROXY_URL` environment variable.

**Acceptance criteria:**

1. `pip install` or `python mcp_server/server.py` — the server starts
2. `RAG_PROXY_URL=http://proxy:8080` — connects to the proxy
3. Without the variable — an error with instructions

**Status:** ✅ Confirmed (`tests/mcp_server/test_mcp_requirements.py::TestFR125StandaloneInstall`)
**Priority:** HIGH
**Reference:** ADR-013

---

## Deployment (FR-149 — FR-156)

### FR-149. Docker Compose deployment

**Description:**
The system is deployed with a single command: `docker compose up -d`. It starts: proxy, Qdrant,
Redis, Neo4j (optional), MinIO (optional).

**Acceptance criteria:**

1. `docker compose up -d` — all services start
2. `/v1/health` — all components healthy
3. `docker compose down` — clean shutdown

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestDockerCompose`)
**Priority:** CRITICAL
**Reference:** AGENTS.md

---

### FR-150. Helm chart for Kubernetes

**Description:**
A Helm chart for K8s deployment with:

- Deployment (proxy)
- StatefulSets (Qdrant, Neo4j, Redis, MinIO, PostgreSQL)
- HPA (auto-scaling)
- Probes (liveness, readiness)
- ConfigMaps, Secrets
- NetworkPolicies
- ServiceAccount, PDB

**Acceptance criteria:**

1. `helm lint deploy/k8s/helm/rag-system/` — no errors
2. `helm template` — renders valid manifests
3. `kubectl apply` — all resources are created

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestHelmChart`)
**Priority:** CRITICAL
**Reference:** best-practices-checklist 7.4

---

### FR-151. ETL Helm component

**Description:**
ETL is deployed as a separate Helm component:

- CronJob for scheduled ETL
- PVC for WAL state
- ConfigMap for etl_config.yaml
- Resource limits

**Acceptance criteria:**

1. `etl.enabled: true` in values.yaml — the ETL CronJob is created
2. The CronJob runs on schedule
3. The WAL state is persisted in the PVC

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestETLHelmComponent`)
**Priority:** HIGH
**Reference:** FR-151

---

### FR-152. Distributed compose

**Description:**
`docker-compose.distributed.yml` for multi-machine deployment:

- Proxy on machine A
- Qdrant on machine B
- LLM on GPU machine C
- Redis/Neo4j on machine D

**Acceptance criteria:**

1. `docker compose -f docker-compose.distributed.yml config` — valid
2. Services connect to each other by hostname
3. Health checks work

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestDistributedCompose`)
**Priority:** HIGH
**Reference:** FR-152

---

### FR-153. MinIO Helm deployment

**Description:**
MinIO is deployed via Helm for:

- Model artifacts (LoRA adapters)
- Backup storage (Qdrant snapshots, Neo4j dumps)
- File uploads (rag-documents bucket)

**Acceptance criteria:**

1. The MinIO PVC is created
2. Buckets are created automatically (rag-documents, rag-artifacts, open-webui)
3. The proxy connects to MinIO

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestMinIOHelm`)
**Priority:** HIGH
**Reference:** ADR-014

---

### FR-154. PostgreSQL Helm deployment

**Description:**
PostgreSQL for structured data (user DB, feedback store) in the K8s deployment.
Optional: in single-node mode, SQLite is used.

**Acceptance criteria:**

1. The PostgreSQL StatefulSet is created
2. The proxy connects to PostgreSQL
3. Migrations are applied automatically

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestPostgreSQLHelm`)
**Priority:** HIGH
**Reference:** FR-154

---

### FR-156. Setup wizard

**Description:**
The interactive `setup.sh` script performs:

1. Dependency checks (Python, Docker, etc.)
2. Generating .env from .env.example
3. Starting Docker services
4. Initializing collections
5. Health verification

**Acceptance criteria:**

1. `bash setup.sh --full` — all steps complete successfully
2. After setup — `/v1/health` returns 200
3. An error at any step — a clear message

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestDockerCompose`, `scripts/setup_wizard.py`)
**Priority:** HIGH
**Reference:** deployment-guide

---

## Observability (FR-160 — FR-164)

### FR-160. Prometheus /metrics

**Description:**
The `GET /metrics` endpoint returns metrics in Prometheus format:

- Counters: `rag_requests_total`, `rag_errors_total`, `rag_cache_hits_total`
- Histograms: `rag_request_duration_seconds`, `rag_retrieval_duration_seconds`
- Gauges: `rag_active_requests`, `rag_confidence_score`

**Acceptance criteria:**

1. `/metrics` — valid Prometheus text format
2. At least 12 metrics
3. Labels: method, path, status

**Status:** ✅ Confirmed (`tests/proxy/test_observability.py::TestPrometheusMetrics`)
**Priority:** CRITICAL
**Reference:** best-practices-checklist 4.1

---

### FR-161. Structured JSON logging

**Description:**
With `LOG_FORMAT=json`, logs are output in JSON format. Secrets are masked.

**Acceptance criteria:**

1. `LOG_FORMAT=json` — logs in JSON
2. Each line — valid JSON
3. Secrets are masked
4. request_id is propagated through all logs of a request

**Status:** ✅ Confirmed (`tests/proxy/test_observability.py::TestStructuredLogging`)
**Priority:** CRITICAL
**Reference:** best-practices-checklist 4.2

---

### FR-162. Grafana dashboard

**Description:**
A JSON file for import into Grafana with panels:

- Request rate (RPS)
- Latency percentiles (p50, p95, p99)
- Error rate
- Cache hit ratio
- Token usage
- Confidence distribution
- Feedback stats

**Acceptance criteria:**

1. The JSON imports into Grafana without errors
2. All panels display data
3. The dashboard updates in real time

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestGrafanaDashboard`)
**Priority:** HIGH
**Reference:** best-practices-checklist 4.6

---

### FR-163. Prometheus alert rules

**Description:**
Alert rules for Prometheus:

- `HighLatency` — p95 > 5s
- `HighErrorRate` — 5xx > 5%
- `LLMUnavailable` — LLM down > 2 min
- `QdrantUnavailable` — Qdrant down > 1 min
- `LowCacheHitRatio` — cache hit < 20%

**Acceptance criteria:**

1. `promtool check rules alerts.yml` — no errors
2. All 5 alert rules are present
3. Thresholds are configurable

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestAlertRules`)
**Priority:** HIGH
**Reference:** best-practices-checklist 4.5

---

### FR-164. OpenTelemetry tracing

**Description:**
The system supports distributed tracing via OpenTelemetry:

- W3C traceparent propagation
- Trace ID in logs and HTTP headers
- Spans for each stage of the RAG pipeline

**Acceptance criteria:**

1. `OTEL_ENABLED=true` — tracing is active
2. Trace ID is present in logs
3. Trace ID in response HTTP headers

**Status:** ✅ Confirmed (`tests/proxy/test_observability.py::TestOpenTelemetryTracing`)
**Priority:** HIGH
**Reference:** best-practices-checklist 4.4

---

## Backup and DR (FR-165 — FR-167)

### FR-165. Automated backup scripts

**Description:**
Scripts for automated backups:

- Qdrant snapshots — every 6 hours
- Neo4j dumps — every 6 hours
- Redis RDB — every hour
- ETL WAL state — every 30 minutes

Backups are saved to S3/MinIO.

**Acceptance criteria:**

1. Scripts run on schedule (cron)
2. Backups are saved to an S3 bucket
3. Log: "Backup completed: X MB"

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestBackupScripts`)
**Priority:** CRITICAL
**Reference:** disaster-recovery-runbook

---

### FR-166. Disaster recovery runbook ✅

**Description:**
The runbook covers 8 scenarios:

1. Qdrant loss — restore from snapshot
2. Neo4j loss — restore from dump
3. Redis loss — rebuild from source
4. Node failure — failover
5. Network partition — graceful degradation
6. Full outage — full restore
7. LLM backend failure — fallback
8. Disk full — cleanup + expand

**Acceptance criteria:**

1. For each scenario — step-by-step instructions
2. RTO < 30 minutes
3. RPO < 1 hour

**Status:** ✅ Confirmed (documentation exists)
**Priority:** CRITICAL
**Reference:** disaster-recovery-runbook.md

---

### FR-167. Restore script

**Description:**
The `restore_all.sh` script restores all services from a backup:

- `--latest` — the latest backup
- `--date YYYY-MM-DD` — backup for a date
- Integrity check after restore

**Acceptance criteria:**

1. `restore_all.sh --latest` — all services restored
2. Data is available after restore
3. The health check passes

**Status:** ✅ Confirmed (`tests/deploy/test_helm_chart.py::TestRestoreScript`)
**Priority:** CRITICAL
**Reference:** disaster-recovery-runbook

---

## Performance (FR-168 — FR-173)

### FR-168. Qdrant scalar quantization (INT8)

**Description:**
Qdrant uses INT8 quantization for vectors, reducing memory consumption 4×
with minimal quality loss (MRR drop ≤ 2%).

**Acceptance criteria:**

1. The collection is created with quantization_config
2. Memory consumption ≤ 50% of the non-quantized one
3. MRR drop ≤ 2%

**Status:** ✅ Confirmed (`tests/performance/test_qdrant_config.py::TestFR168QdrantQuantization`,
`proxy/app/shared/config.py::QDRANT_QUANTIZATION_ENABLED`,
`proxy/app/core/kb_manager.py::KnowledgeBaseManager._ensure_qdrant_collection` lines 563-570)
**Priority:** HIGH
**Reference:** NFR-P07, NFR-P13

---

### FR-169. Qdrant gRPC client

**Description:**
The proxy connects to Qdrant via gRPC (prefer_grpc=True) to reduce latency.
HTTP is used as a fallback.

**Acceptance criteria:**

1. `prefer_grpc=True` in the client settings
2. Retrieval latency p50 < 130ms
3. Fallback to HTTP when gRPC is unavailable

**Status:** ✅ Confirmed (`tests/performance/test_qdrant_config.py::TestFR169QdrantGRPC`,
`proxy/app/shared/config.py::QDRANT_GRPC_ENABLED`, `proxy/app/core/retrieval.py::initialize_retrieval` lines 241-244,
`proxy/app/core/enricher.py` lines 91-94)
**Priority:** HIGH
**Reference:** NFR-P02

---

### FR-170. vLLM prefix caching ✅ Confirmed

**Description:**
vLLM caches the prefix (system prompt) to reduce TTFT by 50%+ on repeated
requests with the same system prompt.

**Acceptance criteria:**

1. `--enable-prefix-caching` is enabled on vLLM
2. The `rag_vllm_prefix_cache_hit_ratio` gauge ≥ 40%
3. TTFT is reduced by ≥ 50%

**Status:** ✅ Confirmed (`tests/performance/test_qdrant_config.py::TestFR170VLLMPrefixCache`,
`proxy/app/shared/metrics.py::rag_vllm_prefix_cache_hit_ratio` line 316, `deploy/docker/docker-compose.prod.yml` vLLM
service line 221 `--enable-prefix-caching`)
**Priority:** HIGH
**Reference:** NFR-P08

---

### FR-171. HNSW tuning

**Description:**
HNSW index parameters are tuned to the collection size:

- < 100K vectors: m=16, ef_construct=128, ef_search=64
- 100K-1M: m=24, ef_construct=192, ef_search=128
- > 1M: m=32, ef_construct=256, ef_search=200

**Acceptance criteria:**

1. Parameters match the collection size
2. Recall@10 ≥ 0.95
3. Latency within acceptable bounds

**Status:** ✅ Confirmed (`tests/performance/test_qdrant_config.py::TestFR171HNSWTuning`,
`proxy/app/shared/config.py::QDRANT_HNSW_M`/`QDRANT_HNSW_EF_CONSTRUCT`,
`proxy/app/core/kb_manager.py::KnowledgeBaseManager._ensure_qdrant_collection` lines 557-560)
**Priority:** HIGH
**Reference:** NFR-P13

---

### FR-173. Model warm-up

**Description:**
At startup, the system "warms up" the models (embedder, reranker, SLM) with dummy
requests to eliminate cold-start latency.

**Acceptance criteria:**

1. Warm-up runs at startup (if `WARMUP_ON_STARTUP=true`)
2. The first real request — latency within 100ms of the 10th
3. Warm-up duration < 30s

**Status:** ✅ Confirmed (`tests/performance/test_nfr_benchmarks.py::TestModelWarmup`)
**Priority:** HIGH
**Reference:** NFR-P12

---

## Multi-Modal (FR-174 — FR-175)

### FR-174. AST-based code chunking

**Description:**
Source code is split by AST structure:

- Python: by functions and classes (via the `ast` module)
- JavaScript: by functions and classes (via tree-sitter)
- Java: by methods and classes

**Acceptance criteria:**

1. A Python file with 5 functions → 5 chunks
2. Each chunk contains a complete function (not truncated)
3. Context (file name, class name) is added to the metadata

**Status:** ✅ Confirmed (`tests/etl/test_etl_requirements.py::TestFR49CodeChunking`,
`tests/etl/test_code_chunker.py`)
**Priority:** HIGH
**Reference:** roadmap Phase 5.2

---

### FR-175. Table extraction from Confluence

**Description:**
Tables from Confluence pages are extracted in structured form and indexed
separately. A "which table X?" query returns structured data.

**Acceptance criteria:**

1. A Confluence page with a table → the table is extracted
2. The table is indexed as a separate chunk with type=table
3. A table search returns structured data

**Status:** ✅ Confirmed (`tests/etl/test_table_extractor.py`)
**Priority:** HIGH
**Reference:** roadmap Phase 5.3
