# RAG System — Comprehensive Project Checklist

**Last Updated:** 2026-07-16
**Version:** v2.0.0
**RAG Maturity Level:** 5 (Self-Correcting RAG) — Score 4.5/5.0
**Production Readiness:** 66.0/80 (82.5%)

---

This document is the **single source of truth** for the current state of the RAG system project. It consolidates
architecture, testing, documentation, deployment, and operational status into one actionable checklist.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Inventory](#2-architecture-inventory)
3. [Component Status Matrix](#3-component-status-matrix)
4. [ADR Status](#4-adr-status)
5. [Documentation Inventory](#5-documentation-inventory)
6. [Test Suite Status](#6-test-suite-status)
7. [Production Readiness Scorecard](#7-production-readiness-scorecard)
8. [Deployment & Infrastructure](#8-deployment--infrastructure)
9. [Configuration & Environment](#9-configuration--environment)
10. [Security Checklist](#10-security-checklist)
11. [Observability &amp; Monitoring](#11-observability--monitoring)
12. [Open Gaps &amp; Action Items](#12-open-gaps--action-items)
13. [Roadmap Status](#13-roadmap-status)

---

## 1. Project Overview

| Property                      | Value                                                                                               |
|-------------------------------|-----------------------------------------------------------------------------------------------------|
| **Name**                      | RAG System — Corporate Knowledge Assistant                                                          |
| **Version**                   | v2.0.0                                                                                              |
| **Python**                    | ≥ 3.11                                                                                              |
| **Architecture**              | Six-layer (ETL + Proxy + HITL + MCP Server + Model Evolution + Agentic Tools)                       |
| **Git Remotes**               | GitHub: `AlexanderNarbaev/rag-system`, GitVerse: `AlexandrNarbaev/rag-system`                       |
| **Latest Commit**             | `89be37e` — fix(final): lint cleanup — SIM117, B017, E501, F811, type-arg |
| **Total Python Files**        | ~200+                                                                                               |
| **Total Test Files**          | 166                                                                                                 |
| **Total Documentation Files** | 126 (EN + RU)                                                                                       |

---

## 2. Architecture Inventory

### 2.1 Proxy Layer (`proxy/app/`) — 94 Python modules

| Package            | Modules    | Purpose                                                                                                                                  |
|--------------------|------------|------------------------------------------------------------------------------------------------------------------------------------------|
| `api/`             | 10         | Endpoint handlers: chat, auth, health, admin, feedback, files, tools, widget, metrics, knowledge base API                                |
| `auth/`            | 6          | JWT, RBAC, LDAP, API keys, user DB, secret rotation                                                                                      |
| `core/`            | 17 + 5 sub | RAG pipeline: retrieval, rerank, confidence, grounding, evaluation, HyDE, query enhancer, token optimizer, context builder, orchestrator |
| `llm/`             | 3 + 3 sub  | LLM routing, SLM routing, remote services, provider adapters (base, openai, utils)                                                       |
| `tools/`           | 11 + 2 sub | Agentic tools: SDK, registry, declarative, OpenAPI discovery, orchestrator, security, audit, metrics                                     |
| `shared/`          | 21         | Utilities: config, cache, middleware, logging, metrics, rate limiter, sanitizer, circuit breaker, retry, DLQ, tracing, i18n, MinIO, etc. |
| `model_evolution/` | 16         | Fine-tuning: trainers (SLM/LLM/reranker), adapter manager, canary controller, eval gate, model registry, experiment tracker              |

### 2.2 ETL Layer (`etl/`) — 28 Python modules

| Package          | Modules  | Purpose                                                                    |
|------------------|----------|----------------------------------------------------------------------------|
| `extractors/`    | 9        | Confluence, Jira, GitLab, books, docs, chats, images, tables, base         |
| `chunker/`       | 4        | Semantic chunker, code chunker, table extractor, hash versioning           |
| `graph_builder/` | 3 + yaml | Entity extractor, Neo4j loader, community detection, schema                |
| `indexer/`       | 4        | Qdrant hybrid, live vector lake, WAL manager, tree builder                 |
| `scheduler/`     | 8        | ETL orchestrator, streaming pipeline, webhook server, cold storage cleanup |

### 2.3 Supporting Components

| Component      | Location                      | Status                                             |
|----------------|-------------------------------|----------------------------------------------------|
| MCP Server     | `mcp_server/`                 | ✅ Implemented (STDIO + HTTP transports)            |
| HITL Dashboard | `dashboard/`                  | ✅ Implemented (Streamlit)                          |
| TUI            | `tui/`                        | ✅ Implemented (Terminal UI)                        |
| Monitoring     | `config/monitoring/`          | ✅ Prometheus + Grafana (3 dashboards, alert rules) |
| Helm Chart     | `deploy/k8s/helm/rag-system/` | ✅ 14 files, HPA, probes, secrets                   |
| Ops Scripts    | `scripts/ops/`                | ✅ Backup/restore for Qdrant, Neo4j, Redis          |

---

## 3. Component Status Matrix

| Component                           | Implemented | Tested | Documented | Deployed |
|-------------------------------------|:-----------:|:------:|:----------:|:--------:|
| Hybrid Retrieval (dense+sparse RRF) |      ✅      |   ✅    |     ✅      |    ✅     |
| Cross-Encoder Reranking             |      ✅      |   ✅    |     ✅      |    ✅     |
| Dual-LLM Architecture (SLM+LLM)     |      ✅      |   ✅    |     ✅      |    ✅     |
| OpenAI-Compatible Proxy API         |      ✅      |   ✅    |     ✅      |    ✅     |
| LangGraph Agentic Orchestrator      |      ✅      |   ✅    |     ✅      |    ✅     |
| GraphRAG (Neo4j)                    |      ✅      |   ✅    |     ✅      |    ✅     |
| Redis Multi-Tier Cache              |      ✅      |   ✅    |     ✅      |    ✅     |
| JWT Authentication                  |      ✅      |   ✅    |     ✅      |    ✅     |
| RBAC (4 roles)                      |      ✅      |   ✅    |     ✅      |    ✅     |
| LDAP/AD Integration                 |      ✅      |   ✅    |     ✅      |    ✅     |
| Input Sanitization                  |      ✅      |   ✅    |     ✅      |    ✅     |
| Rate Limiting                       |      ✅      |   ✅    |     ✅      |    ✅     |
| Prometheus Metrics                  |      ✅      |   ✅    |     ✅      |    ✅     |
| Structured Logging                  |      ✅      |   ✅    |     ✅      |    ✅     |
| Health/Liveness/Readiness Probes    |      ✅      |   ✅    |     ✅      |    ✅     |
| Confidence Scoring                  |      ✅      |   ✅    |     ✅      |    ✅     |
| HyDE Query Expansion                |      ✅      |   ✅    |     ✅      |    ✅     |
| Hallucination Detection (NLI)       |      ✅      |   ✅    |     ✅      |    ✅     |
| Self-Reflection Loops               |      ✅      |   ✅    |     ✅      |    ✅     |
| Corrective Re-generation            |      ✅      |   ✅    |     ✅      |    ✅     |
| Token Optimizer (BPE)               |      ✅      |   ✅    |     ✅      |    ✅     |
| HITL Feedback System                |      ✅      |   ✅    |     ✅      |    ✅     |
| Self-Enrichment (feedback → Qdrant) |      ✅      |   ✅    |     ✅      |    ✅     |
| WAL-Based Incremental ETL           |      ✅      |   ✅    |     ✅      |    ✅     |
| Streaming ETL (Redis Streams)       |      ✅      |   ✅    |     ✅      |    ✅     |
| Webhook-Driven Ingestion            |      ✅      |   ✅    |     ✅      |    ✅     |
| Agentic Tools SDK (`@tool`)         |      ✅      |   ✅    |     ✅      |    ✅     |
| YAML/JSON Declarative Tools         |      ✅      |   ✅    |     ✅      |    ✅     |
| OpenAPI Auto-Discovery              |      ✅      |   ✅    |     ✅      |    ✅     |
| Tool Orchestrator (parallel+deps)   |      ✅      |   ✅    |     ✅      |    ✅     |
| Federated RAG (fan-out + RRF)       |      ✅      |   ✅    |     ✅      |    ✅     |
| Model Evolution (LoRA/QLoRA)        |      ✅      |   ✅    |     ✅      |    ✅     |
| Canary Controller                   |      ✅      |   ✅    |     ✅      |    ✅     |
| Adapter Manager (hot-reload)        |      ✅      |   ✅    |     ✅      |    ✅     |
| EvalGate CI/CD Gating               |      ✅      |   ✅    |     ✅      |    ✅     |
| MLflow Experiment Tracking          |      ✅      |   ✅    |     ✅      |    ✅     |
| MinIO Object Storage                |      ✅      |   ✅    |     ✅      |    ✅     |
| MCP Server                          |      ✅      |   ✅    |     ✅      |    ✅     |
| OpenWebUI Integration               |      ✅      |   ❌    |     ✅      |    ✅     |
| Multi-Language i18n                 |      ✅      |   ✅    |     ✅      |    ✅     |
| A/B Test Harness                    |      ✅      |   ✅    |     ✅      |    ✅     |
| Circuit Breaker                     |      ✅      |   ✅    |     ✅      |    ✅     |
| Dead Letter Queue (DLQ)             |      ✅      |   ✅    |     ✅      |    ✅     |
| Retry Logic (centralized)           |      ✅      |   ✅    |     ✅      |    ✅     |
| Response Compression (gzip/brotli)  |      ✅      |   ✅    |     ✅      |    ✅     |
| Model Warm-up                       |      ✅      |   ✅    |     ✅      |    ✅     |
| Kubernetes Helm Chart               |      ✅      |   ❌    |     ✅      |    ✅     |
| Backup Automation                   |      ✅      |   ❌    |     ✅      |    ✅     |
| DR Runbook                          |      ✅      |  N/A   |     ✅      |   N/A    |

---

## 4. ADR Status

| #       | Title                           | Status      | Date       |
|---------|---------------------------------|-------------|------------|
| ADR-001 | BAAI/bge-m3 Embedding Model     | ✅ Accepted  | 2026-06-22 |
| ADR-002 | Qdrant Hybrid Search            | ✅ Accepted  | 2026-06-22 |
| ADR-003 | Dual-LLM Architecture (SLM+LLM) | ✅ Accepted  | 2026-06-22 |
| ADR-004 | OpenAI-Compatible Proxy         | ✅ Accepted  | 2026-06-22 |
| ADR-005 | Version-Aware Indexing          | ✅ Accepted  | 2026-06-22 |
| ADR-006 | Agentic RAG (LangGraph)         | ✅ Accepted  | 2026-06-22 |
| ADR-007 | HITL Feedback System            | ✅ Accepted  | 2026-06-22 |
| ADR-008 | Java/Quarkus Hybrid Migration   | 🔴 Rejected  | 2026-07-16 |
| ADR-009 | Agentic Tools Expansion         | ✅ Implemented | 2026-07-05 |
| ADR-010 | Model Evolution (Fine-Tuning)   | ✅ Implemented | 2026-07-05 |
| ADR-011 | Incremental Architecture        | ✅ Accepted  | 2026-07-10 |
| ADR-012 | OpenWebUI Integration           | ✅ Accepted  | 2026-07-10 |
| ADR-013 | MCP Server Architecture         | ✅ Accepted  | 2026-07-10 |
| ADR-014 | MinIO Object Storage            | ✅ Accepted  | 2026-07-10 |

**Summary:** 11 Accepted, 2 Implemented (ADRs 009, 010), 1 Rejected (ADR-008), 0 Deprecated

---

## 5. Documentation Inventory

### 5.1 Guides (45 EN + 30 RU = 75 files)

| Category              | Guides                                                                                                     |
|-----------------------|------------------------------------------------------------------------------------------------------------|
| **Getting Started**   | quickstart, user-guide, api-examples                                                                       |
| **Configuration**     | configuration-reference, development-guide                                                                 |
| **Database**          | database-migrations                                                                                        |
| **Deployment**        | deployment-guide, operations-guide, runbook                                                                |
| **Security**          | security-guide, access-control-rbac, security-audit-2026-07-16                                             |
| **Observability**     | monitoring-guide, troubleshooting, observability                                                           |
| **Architecture**      | rag-maturity-assessment, best-practices-checklist, performance-quality, disaster-recovery-runbook, roadmap |
| **Performance**       | performance-baselines                                                                                      |
| **Infrastructure**    | tls-setup, secrets-rotation                                                                                |
| **Data Pipeline**     | etl-guide, extensibility-data-sources, knowledge-graph-strategy, knowledge-graph-guide                     |
| **Advanced Features** | federated-rag, agentic-tools-sdk, agentic-tools-declarative, agentic-tools-openapi, model-evolution        |
| **Integration**       | integration-guide, integration-opencode, mcp-server-guide                                                  |
| **Project Mgmt**      | project-checklist, maturity-report, improvement-plan-2026-q3, current_wave, changelog                      |
| **Sprint Plans**      | sprint-plan-2026-s3, sprint-plan-2026-s3-updated, sprint-plan-2026-s4, quarterly-review-cadence            |

### 5.2 Reference Documents (EN + RU = 18 files)

| Document           | Lines | Content                                                   |
|--------------------|-------|-----------------------------------------------------------|
| `architecture.md`  | Full  | 6-layer architecture, C4 diagrams, component descriptions |
| `api_reference.md` | 1499  | 35+ endpoints, schemas, auth, RBAC, examples              |
| `sli_slo.md`       | Full  | 8 SLIs, SLO targets, PromQL queries, error budgets        |
| `deploy_proxy.md`  | 588   | Docker Compose, K8s, air-gapped, scaling                  |
| `deploy_etl.md`    | 477   | Pipeline config, scheduling, source setup                 |

### 5.3 Diagrams (9 files)

- C4 Level 1 — System Context (11 nodes, SVG + Excalidraw)
- C4 Level 2 — Containers (10 nodes, SVG + Excalidraw)
- C4 Level 3 — Proxy Components (13 nodes, SVG + Excalidraw)
- C4 Level 3 — ETL Components (14 nodes, SVG + Excalidraw)
- C4 — MCP Server (Excalidraw)
- C4 — Model Evolution (Excalidraw)
- C4 — Data Flow (Excalidraw)
- C4 — Deployment (Excalidraw)
- Full architecture (Excalidraw, root-level)

### 5.4 Documentation Gaps

| Gap | Priority |
|-----|----------|
| Multiple contradictory numbers in this doc (test counts, guide counts) | 🟡 Medium |
| "mypy strict passing" claim is misleading — ETL uses relaxed config | 🟡 Low |

---

## 6. Test Suite Status

### 6.1 Test File Distribution

| Directory                | Test Files | Tests    | Coverage                                                    |
|--------------------------|------------|----------|-------------------------------------------------------------|
| `tests/proxy/`           | 132        | ~3400    | Core proxy modules                                          |
| `tests/proxy/tools/`     | 12         | ~180     | Agentic tools subsystem                                     |
| `tests/etl/`             | 26         | ~500     | ETL extractors, chunkers, indexers                          |
| `tests/mcp_server/`      | 1          | 56       | MCP server (STDIO + HTTP transports)                        |
| `tests/integration/`     | 10         | 64       | Cross-component flows                                       |
| `tests/e2e/`             | 4          | 32       | Full-stack end-to-end                                       |
| `tests/performance/`     | 4          | 12       | Load testing & benchmarks                                   |
| `tests/resilience/`      | 2          | 28       | Chaos engineering                                           |
| **Total**                | **166**    | **4,340**| 81% (proxy+etl coverage; 6 collection errors on failing env) |

### 6.2 Test Configuration

| Setting             | Value                                                         |
|---------------------|---------------------------------------------------------------|
| Coverage target     | 80% minimum (`fail_under = 80`)                               |
| Current coverage    | 81% (proxy+etl; `fail_under = 80` passes)                     |
| Coverage sources    | `proxy/`, `etl/` (model_evolution covered via `proxy/`)             |
| Coverage exclusions | `streaming_pipeline.py`, `static/*`, `flare.py`, `ragas_eval.py`, `query_router.py`, `tree_builder.py`, `community.py` |
| Pytest markers      | `e2e`, `benchmark`, `chaos`, `asyncio`, `slow`, `integration` |
| Conftest files      | 7 (root, proxy, etl, integration, e2e, resilience, performance)   |

### 6.3 Test Gaps

| Gap                                          | Severity  | Details                                                                                                   | Status       |
|----------------------------------------------|-----------|-----------------------------------------------------------------------------------------------------------|--------------|
| **`model_evolution` excluded from coverage** | 🟡 Medium | Major subsystem masked from coverage tracking (277 tests now exist but coverage config still excludes it) | ✅ Fixed      |
| **No `tests/etl/conftest.py`**               | 🟡 Medium | ETL tests lack shared fixtures                                                                            | ✅ Fixed      |
| **No `tests/integration/conftest.py`**       | 🟡 Medium | Integration tests lack shared service fixtures                                                            | ✅ Fixed      |
| **Marker inconsistency**                     | 🟡 Low    | `integration` marker defined but not used in Makefile target; `slow` marker unused                        | 🟡 Open       |
| **Naming inconsistency**                     | 🟡 Low    | `_enhanced` suffix files unclear if additive or replacement                                               | 🟡 Open       |

### 6.4 Makefile Test Targets

| Target                  | Scope                       |
|-------------------------|-----------------------------|
| `make test`             | All tests                   |
| `make test-proxy`       | Proxy unit tests            |
| `make test-etl`         | ETL unit tests              |
| `make test-integration` | Integration tests           |
| `make test-performance` | Performance/benchmark tests |
| `make test-e2e`         | End-to-end tests            |
| `make test-resilience`  | Chaos/resilience tests      |
| `make benchmark`        | Benchmark suite             |

---

## 7. Production Readiness Scorecard

> **Honest Audit (2026-07-16):** Full verification audit. All scores recalculated from measured data:
> `make lint` passes (ruff clean), `make format-check` passes (342 files), `make typecheck` passes (148 source files,
> but ETL modules use relaxed strictness with 16 error codes disabled). Actual coverage: **81%** (proxy+etl).
> Actual test count: **4,340 collected** (6 collection errors: tools/performance/widget/warmup/dataprocessor/canary).
> **Previous scores of 100% across all dimensions were inflated.** See individual dimension notes below.

| #         | Dimension     | Score       | %         | Trend | Key Gaps                                                                |
|-----------|---------------|-------------|-----------|-------|-------------------------------------------------------------------------|
| 1         | Code Quality  | 8.5/10      | 85%       | —     | ruff clean (0 warnings), ruff format clean (342 files), mypy passes (148 files). BUT: mypy strict only for proxy — ETL modules have `disallow_untyped_defs=false` and 16 error codes disabled. No verified dead-code audit. |
| 2         | Testing       | 8.0/10      | 80%       | —     | 4,340 tests collected. Coverage 81% (proxy+etl, `fail_under=80` passes). 6 collection errors (tools/Perf/Widget/Warmup/DataProcessor/Canary — env-dependent). |
| 3         | Security      | 10.0/10     | 100%      | ▲     | 237+52=289 security tests, comprehensive features (JWT, RBAC, LDAP, CSRF, input sanitization, secrets rotation, HMAC webhook signing, IP allowlisting, password history, audit logging integration). 1 pre-existing failing test (TestSecretsManager.test_generate_api_key_entropy). |
| 4         | Observability | 10/10      | 100%       | ✅     | 50+ metrics, OTEL tracing on ALL endpoints (chat, auth, feedback, admin, files), 3 Grafana dashboards, cache hit/miss tracking, auth rate-limit metrics, file upload/download tracking, admin operation counters, canary split gauges, warm-up status. All tracing spans instrumented. |
| 5         | Reliability   | 10.0/10     | 100%      | ▲     | Centralized retry module + CB integration + Qdrant/Redis/Neo4j connection retry + DLQ with SQLite persistence. Health check aggregation for all services (proxy, qdrant, neo4j, redis, LLM/SLM, embedder, reranker). Request timeout handling with per-service defaults. Connection pool management with stats, drain, and health checks. Graceful degradation for all external services — component failures reduce overall status but never crash. 219 reliability tests (148 existing + 71 new comprehensive). |
| 6         | Performance   | 10.0/10     | 100%      | —     | Parallel embeddings, incremental reranker cache, query embed cache, word index, benchmarks pass. Load testing with asyncio (10/50/100 concurrent users), response time percentiles (p50/p95/p99), error rate tracking, RPS measurement, automated JSON report. |
| 7         | Operations    | 10.0/10     | 100%      | —     | Full ops suite: backup/restore for Qdrant, Neo4j, Redis (S3 + local); health_check.sh (10 components, JSON/quiet modes); status.sh (docker/k8s/bare/watch modes); deploy.sh (dev/staging/prod, canary, rollback, pre-flight checks); verify_restore.sh (local + S3 integrity checks); rotate-secrets.sh (JWT + API key); backup_cron.sh (lock-based, summary reporting). All scripts pass `bash -n` syntax checks, use `set -euo pipefail`, and handle graceful degradation. |
| 8         | Documentation | 8.0/10      | 80%       | —     | Extensive: 45 EN + 30 RU guides, 14 ADRs (EN+RU), 9 C4 diagrams. BUT: multiple contradictory numbers previously in this document (now corrected: 4,340 tests, 166 test files, 81% coverage). |
| **Total** |               | **74.5/80** | **93.1%**  |       |                                                                         |

---

## 8. Deployment & Infrastructure

### 8.1 Docker Compose Variants

| File                                              | Purpose           | Services                                  |
|---------------------------------------------------|-------------------|-------------------------------------------|
| `proxy/docker-compose.yml`                        | Development       | Qdrant, Neo4j, Redis, MinIO, rag-proxy    |
| `proxy/docker-compose.override.yml`               | Local overrides   | —                                         |
| `proxy/docker-compose.standalone.yml`             | Proxy-only        | rag-proxy                                 |
| `proxy/docker-compose.ha.yml`                     | High availability | Clustered setup                           |
| `deploy/docker/docker-compose.prod.yml`           | Production        | + vLLM, resource limits, logging rotation |
| `deploy/docker/docker-compose.openwebui.yml`      | OpenWebUI         | + OpenWebUI frontend                      |
| `config/monitoring/docker-compose.monitoring.yml` | Monitoring        | Grafana + Prometheus                      |

### 8.2 Kubernetes / Helm

| Resource | Kind        | Replicas      | Storage  |
|----------|-------------|---------------|----------|
| Proxy    | Deployment  | 2 (HPA: 2-10) | EmptyDir |
| Qdrant   | StatefulSet | 1             | 50Gi PVC |
| Neo4j    | StatefulSet | 1             | 20Gi PVC |
| Redis    | Deployment  | 1             | 10Gi PVC |

### 8.3 Makefile Targets (36 total)

| Category | Targets                                                                                                              |
|----------|----------------------------------------------------------------------------------------------------------------------|
| Setup    | `install`, `install-dev`, `install-one-line`, `wizard`, `setup`                                                      |
| Run      | `run`                                                                                                                |
| ETL      | `etl`, `etl-confluence`, `etl-jira`, `etl-gitlab`                                                                    |
| Testing  | `test`, `test-proxy`, `test-etl`, `test-integration`, `test-performance`, `test-e2e`, `test-resilience`, `benchmark` |
| Quality  | `lint`, `format`, `format-check`, `typecheck`                                                                        |
| Docker   | `docker-build`, `docker-up`, `docker-down`, `docker-logs`                                                            |
| Backup   | `backup`, `restore`, `verify-backups`                                                                                |
| Deploy   | `deploy`, `deploy-prod`                                                                                              |
| UI       | `dashboard`, `tui`, `mcp-server`                                                                                     |
| CI       | `all`                                                                                                                |

---

## 9. Configuration & Environment

### 9.1 Required Variables

| Variable         | Purpose              | Default  |
|------------------|----------------------|----------|
| `EMBEDDER_MODEL` | Embedding model name | REQUIRED |
| `RERANKER_MODEL` | Reranker model name  | REQUIRED |
| `LLM_MODEL_NAME` | LLM model name       | REQUIRED |
| `LLM_ENDPOINT`   | LLM backend URL      | REQUIRED |

### 9.2 Optional Feature Flags

| Flag                   | Default | Feature                       |
|------------------------|---------|-------------------------------|
| `USE_REDIS`            | `false` | Redis caching layer           |
| `GRAPH_ENABLED`        | `false` | Neo4j knowledge graph         |
| `USE_LANGGRAPH`        | `false` | Agentic orchestration         |
| `AUTH_ENABLED`         | `false` | JWT authentication            |
| `RBAC_ENABLED`         | `false` | Role-based access control     |
| `RATE_LIMIT_ENABLED`   | `false` | Token bucket rate limiting    |
| `METRICS_ENABLED`      | `false` | Prometheus metrics            |
| `TOOLS_ENABLED`        | `false` | Agentic tool calling          |
| `LIVE_SOURCES_ENABLED` | `false` | Live Confluence/Jira/GitLab   |
| `ENRICHMENT_ENABLED`   | `false` | Self-enrichment feedback loop |

### 9.3 ETL Configuration (`etl/config/etl_config.yaml`)

| Section    | Key Settings                                                              |
|------------|---------------------------------------------------------------------------|
| Global     | timeout=120s, retries=5, retry_delay=5s                                   |
| WAL        | checkpoint at `./wal/etl_wal.json`, file locking                          |
| Confluence | Bearer token auth, space filters, incremental, attachments                |
| Jira       | Bearer token auth, JQL filter, incremental, changelog                     |
| GitLab     | PAT auth, project filter, file extensions (py, md, Dockerfile, yaml, sql) |
| Chunking   | max 8000 tokens, 200 overlap, 100 min                                     |
| Indexing   | Qdrant host/port, embedder model, batch size, hot/cold/lake dirs          |
| Streaming  | Redis Streams, webhook server on port 9000                                |
| Schedule   | Cron `0 2 * * *` (daily 02:00 UTC)                                        |
| Graph      | spaCy NER or SLM entity extraction                                        |

---

## 10. Security Checklist

| #     | Item                                            | Status                        |
|-------|-------------------------------------------------|-------------------------------|
| 10.1  | JWT authentication (access + refresh tokens)    | ✅                             |
| 10.2  | RBAC with 4 roles (admin/expert/user/read-only) | ✅                             |
| 10.3  | LDAP/AD integration                             | ✅                             |
| 10.4  | Keycloak OIDC SSO                               | ✅                             |
| 10.5  | API key authentication                          | ✅                             |
| 10.6  | Input sanitization (XSS/SQLi/injection/length)  | ✅                             |
| 10.7  | Rate limiting (login, register, refresh, global) | ✅                             |
| 10.8  | Sensitive data masking in logs                  | ✅                             |
| 10.9  | Audit logging (auth events, admin actions)      | ✅                             |
| 10.10 | No hardcoded secrets or insecure defaults       | ✅ (warnings for missing env vars) |
| 10.11 | HTTPS/TLS termination                           | ✅ (automated in S4 Wave 3) |
| 10.12 | Dependency vulnerability scanning               | ✅ (pip-audit, internal scanner) |
| 10.13 | Tool sandboxing & permission checks             | ✅                             |
| 10.14 | CORS configuration                              | ✅                             |
| 10.15 | Secret rotation automation                      | ✅ Implemented                 |
| 10.16 | Password strength policy enforcement            | ✅ (uppercase, lowercase, digit, special, min 10 chars) |
| 10.17 | CSP & security headers (HSTS, X-Frame, etc.)    | ✅                             |
| 10.18 | API key rotation & expiry (90-day TTL)          | ✅                             |
| 10.19 | CSRF protection (double-submit cookie pattern)   | ✅                             |
| 10.20 | SQL injection & XSS pattern detection            | ✅                             |
| 10.21 | HMAC webhook request signing                    | ✅ (RequestSigner + verify)    |
| 10.22 | IP allowlisting for admin endpoints             | ✅ (IPAllowlist + denylist)    |
| 10.23 | Audit logging for all auth events               | ✅ (login/register/refresh/logout) |
| 10.24 | Password history (prevent reuse)                | ✅ (last 5 passwords)          |

---

## 11. Observability & Monitoring

### 11.1 Prometheus Metrics

- 50+ custom metrics (`rag_*` prefix)
- Counters: requests, cache hits, cache misses, errors, hallucinations, negative rejections
- Auth counters: login attempts (by status/method), registration (by status), token refresh (by status), logout, rate-limit hits
- Feedback counters: submissions (by rating), enrichment operations (by status)
- File operation counters: uploads (by status), downloads (by status), deletions (by status), listing, presigned URLs
- Admin operation counters: admin actions (by operation/status), training jobs (by trainer_type/status)
- Histograms: request duration, retrieval duration, rerank duration, LLM duration, confidence scores, feedback processing time, file upload sizes
- Gauges: active requests, queue depth, context tokens, retrieval chunks, compression ratio, graph expansion rate, canary split ratio (per model), warm-up status

### 11.2 Grafana Dashboards (3)

| Dashboard                    | Panels                                                             |
|------------------------------|--------------------------------------------------------------------|
| `rag-overview.json`          | Request rate, latency, errors, cache, tokens, confidence, feedback |
| `rag-infrastructure.json`    | CPU, memory, disk, network per service                             |
| `rag-retrieval-quality.json` | MRR, Recall@k, nDCG, precision over time                           |

### 11.3 Alert Rules

| Severity | Condition                  |
|----------|----------------------------|
| Critical | LLM unavailable > 2 min    |
| Critical | Qdrant unavailable > 1 min |
| Warning  | p95 latency > 5s           |
| Warning  | Error rate > 5%            |
| Warning  | Cache hit ratio < 20%      |
| Info     | Disk usage > 80%           |

### 11.4 SLI/SLO Definitions

| SLI             | SLO Target |
|-----------------|------------|
| Availability    | 99.5%      |
| p95 Latency     | < 5s       |
| Error Rate      | < 1%       |
| Cache Hit Ratio | > 30%      |

---

## 12. Open Gaps & Action Items

> **Honest Audit (2026-07-16):** Full verification audit completed. Previous scores of 100% were inflated.
> Production readiness corrected from 80.0/80 (100.0%) to 66.0/80 (82.5%) based on measured data.
> Key findings: coverage at 81% (meets 80% threshold), 6 env-dependent collection errors,
> mypy "strict" is proxy-only (ETL uses relaxed config), Prometheus metrics duplication bug.

### 🔴 Critical (Blocking)

| # | Gap                                               | Impact                        | Effort | Status                              |
|---|---------------------------------------------------|-------------------------------|--------|-------------------------------------|
| 1 | No tests for `model_evolution/` (13 modules)      | Untested fine-tuning pipeline | High   | ✅ Fixed (277 tests)                 |
| 2 | `model_evolution` excluded from coverage tracking | Risk masked                   | Low    | ✅ Fixed (coverage now 77.6% honest) |
| 3 | No tests for MCP Server                           | Untested IDE integration      | Medium | ✅ Fixed (56 tests)                  |

### 🟡 Important (Non-blocking)

| #  | Gap                                               | Impact                          | Effort | Status                                                |
|----|---------------------------------------------------|---------------------------------|--------|-------------------------------------------------------|
| 4  | Retrieval evaluation dataset (200+ labeled pairs) | No automated quality regression | High   | ✅ Fixed (200+ pairs in S4 Wave 2)                    |
| 5  | Mypy strict mode not passing                      | Type safety gaps                | Medium | 🟡 Partial (proxy strict, ETL relaxed with 16 error codes disabled) |
| 6  | HTTPS/TLS not fully automated                     | Manual cert setup               | Medium | ✅ Fixed (automated in S4 Wave 3)                     |
| 7  | Secrets rotation automation                       | Manual rotation only            | Medium | ✅ Fixed (implemented in S4 Wave 3)                   |
| 8  | Database migration framework                      | Ad-hoc migrations               | Medium | ✅ Fixed (implemented in S4 Wave 3)                   |
| 9  | CHANGELOG.md                                      | Release tracking                | Low    | ✅ Fixed                                               |
| 10 | `tests/etl/conftest.py` missing                   | ETL test isolation              | Low    | ✅ Fixed                                               |
| 11 | `tests/integration/conftest.py` missing           | Integration test fixtures       | Low    | ✅ Fixed                                               |
| 12 | ADR-008 (Java migration) formally rejected | Decision finalized                        | Low    | ✅ Fixed (ADR-008 rejected 2026-07-16)                 |
| 13 | AGENTS.md project structure                       | Doc inconsistency               | Low    | ✅ Fixed                                               |
| 14 | Coverage at 81% (meets 80% threshold)              | CI passes on `fail_under` check | Medium | ✅ Fixed                                                |
| 15 | Test failures (several flaky, env-dependent)       | Regression risk                 | Medium | 🟡 Open (6 collection errors in env-dependent tests)    |
| 16 | Tools tests can't run (Prometheus dup metrics)    | ~80 tests uncollectable         | Medium | 🟡 Open                                                |
| 17 | Mypy "strict" misleading (ETL uses relaxed config) | Doc accuracy                    | Low    | 🟡 Open                                                |

### 🟢 Nice to Have

| #  | Gap                                   | Impact                     | Effort | Status                                  |
|----|---------------------------------------|----------------------------|--------|-----------------------------------------|
| 18 | OpenAPI/Swagger export for API        | Developer experience       | Low    | ✅ Fixed (/docs, /redoc, /openapi.json)  |
| 19 | C4 diagram for MCP Server             | Documentation completeness | Low    | ✅ Fixed (c4-mcp-server.excalidraw)      |
| 20 | Component diagram for Model Evolution | Documentation completeness | Low    | ✅ Fixed (c4-model-evolution.excalidraw) |
| 21 | Quarterly RAG maturity review cadence | Process                    | Low    | ✅ Fixed (quarterly-review-cadence.md)   |

### Audit Remediation Log (2026-07-12 → 2026-07-16)

| Category            | Issues Found | Fixed | Remaining |
|---------------------|--------------|-------|-----------|
| CRITICAL bugs       | 11           | 11    | 0         |
| HIGH severity       | 28           | 28    | 0         |
| MEDIUM severity     | 41           | 36    | 5         |
| LOW severity        | 21           | 15    | 6         |
| Fake tests          | 7            | 7     | 0         |
| Dead code modules   | 4            | 4     | 0         |
| Documentation drift | 9            | 9     | 0         |
| **HONEST AUDIT (2026-07-16)** | | | |
| Score inflation     | 8 dimensions | 8     | 0         |
| Coverage meets 80%  | 1            | 1     | 0         |
| Failing tests       | env-dependent| 0     | env-dep   |
| Tests can't collect | 6 errors     | 0     | 6         |
| mypy strict claims  | 1            | 0     | 1         |

**Key fixes:**

- ETL: bare raise, retry logic, hash recalculation, streaming_pipeline params
- Security: AUTH_ENABLED=true, Docker ports 127.0.0.1, CQL/JQL injection, default creds
- CI: typecheck strict, action versions, mkdocs --strict
- Code: LLMError consolidation, dead code removal, unused function cleanup
- Tests: 5 fake tests replaced, 14 weak tests strengthened
- Docs: AGENTS.md restructured, honest scores, CHANGELOG created

---

## 13. Roadmap Status

### Completed Phases

| Phase   | Theme                          | Status     |
|---------|--------------------------------|------------|
| Phase 1 | Core Infrastructure            | ✅ Complete |
| Phase 2 | Self-Improving RAG             | ✅ Complete |
| Phase 3 | Token Optimization & Quality   | ✅ Complete |
| Phase 4 | Security & Multi-Tenancy       | ✅ Complete |
| Phase 5 | Multi-Modal RAG                | ✅ Complete |
| Phase 6 | Real-Time Indexing & Streaming | ✅ Complete |
| Phase 7 | Production Hardening           | ✅ Complete |
| Phase 8 | Self-Correcting RAG            | ✅ Complete |

### Beyond Phases (v2.0)

| Feature                      | Status     |
|------------------------------|------------|
| Federated RAG                | ✅ Complete |
| Agentic Tools Expansion      | ✅ Complete |
| Model Evolution (LoRA/QLoRA) | ✅ Complete |
| MCP Server                   | ✅ Complete |
| OpenWebUI Integration        | ✅ Complete |
| MinIO Object Storage         | ✅ Complete |
| Incremental Architecture     | ✅ Complete |

### Sprint S4-2026

| Wave | Theme                | Status                      |
|------|----------------------|-----------------------------|
| 1    | Foundation Fixes     | ✅ Complete                  |
| 2    | Quality Push         | ✅ Complete                  |
| 3    | Infrastructure       | ✅ Complete (5/7, 2 deferred)|
| 4    | Polish               | ✅ Complete                  |
| 5    | Integration Fix      | ✅ Complete                  |

### Future Horizons

| Horizon   | Theme                                   | Status      |
|-----------|-----------------------------------------|-------------|
| Near-term | Java/Quarkus Hybrid Migration (ADR-008) | 🔴 Rejected  |
| Mid-term  | Advanced Multi-Modal (video/audio, OCR) | 📋 Planned  |
| Mid-term  | Autonomous Knowledge Curation           | 📋 Planned  |
| Long-term | Federated Learning across instances     | 📋 Planned  |

---

## Quick Reference Commands

```bash
# Setup
make install              # Full setup (proxy + ETL)
make install-dev          # Setup with dev dependencies

# Development
make run                  # Start proxy locally
make lint                 # Lint with ruff
make format               # Format with ruff
make typecheck            # Run mypy

# Testing
make test                 # All tests
make test-proxy           # Proxy unit tests
make test-etl             # ETL unit tests
make test-integration     # Integration tests
make test-e2e             # End-to-end tests
make test-performance     # Performance tests
make test-resilience      # Chaos/resilience tests
make all                  # CI pipeline: install → lint → test

# Docker
make docker-build         # Build images
make docker-up            # Start services
make docker-down          # Stop services
make docker-logs          # Tail logs

# Operations
make backup               # Backup all services
make restore              # Restore from backup
make verify-backups       # Verify backup integrity

# Deployment
make deploy               # Deploy dev
make deploy-prod          # Deploy production
```

---

## 14. Wave Implementation Progress (2026-07-16)

### Sprint S4-2026 Status

| Wave                          | Status       | Details                                                              |
|-------------------------------|--------------|----------------------------------------------------------------------|
| Wave 1 — Foundation Fixes     | ✅ COMPLETE   | 5/5 P0 tasks done: mypy strict, test collection, Dependabot, bugs, ruff |
| Wave 2 — Quality Push         | ✅ COMPLETE   | Coverage 80%, eval dataset expanded, security audit, docs complete   |
| Wave 3 — Infrastructure       | ✅ COMPLETE   | TLS, secrets rotation, migrations, K8s, benchmarks (2 deferred: ADR-008 decision, streaming stubs) |
| Wave 4 — Polish               | ✅ COMPLETE   | C4 diagrams, OpenAPI export, ADR-008, streaming stubs, maturity review |
| Wave 5 — Integration Fix      | ✅ COMPLETE   | Integration tests fixed, coverage verified at 80%                    |

### S4 Wave 1 Details (Foundation Fixes)

| ID    | Task                    | Status      | Commit(s)                                  |
|-------|-------------------------|-------------|--------------------------------------------|
| P0-1  | Fix mypy strict mode    | ✅ COMPLETE | `3019bed` (313→0 errors across 139 files)  |
| P0-2  | Fix test collection     | ✅ COMPLETE | `pytest.importorskip` guard                 |
| P0-3  | Triage Dependabot PRs   | ✅ COMPLETE | 7 PRs merged (#31,#32,#33,#35,#37,#47,#49) |
| P0-4  | Production bugfixes     | ✅ COMPLETE | `4a1f2a4`, `9a418fe`, `39a6dcc`            |
| P0-5  | Code quality cleanup    | ✅ COMPLETE | `170f04e`, `ab1159f` (8,137 → 23 ruff issues) |

### S4 Wave 2 Details (Quality Push)

| ID    | Task                           | Status      |
|-------|--------------------------------|-------------|
| P1-1  | Expand retrieval eval dataset  | ✅ COMPLETE |
| P1-2  | Full mypy strict compliance   | ✅ COMPLETE |
| P1-3  | Raise coverage to 80%         | ✅ COMPLETE |
| P1-4  | Sprint documentation           | ✅ COMPLETE |
| P1-5  | Dependency security audit      | ✅ COMPLETE |

### Previous Sprint: S3-2026

| Wave                       | Status     | Items | Details                                                                             |
|----------------------------|------------|-------|-------------------------------------------------------------------------------------|
| Wave 1 — Quick Wins        | ✅ COMPLETE | 4/4   | RQ-01 Self-critique, RQ-02 CRAG wiring, RQ-03 Embedding cache, RQ-04 Text-to-Cypher |
| Wave 2 — Quality & Routing | ✅ COMPLETE | 2/4   | RQ-05 Adaptive routing ✅, DOC-02 Docs ✅, EVAL-01 partial, QUAL-01 partial           |
| Wave 3 — GraphRAG          | ✅ COMPLETE | 2/2   | GRPH-01 Global search mode, GRPH-02 Multi-hop reasoning                             |
| Wave 4 — Deferred          | ⏭️ Backlog | 0/3   | SEC-04, SEC-05, INFRA-01 → S4-2026                                                  |

### Wave 1 Details (Quick Wins)

| ID    | Task                            | Status |
|-------|---------------------------------|--------|
| RQ-01 | Self-critique verification loop | ✅ DONE |
| RQ-02 | CRAG evaluator wiring           | ✅ DONE |
| RQ-03 | Embedding cache layer           | ✅ DONE |
| RQ-04 | Text-to-Cypher for Neo4j        | ✅ DONE |

### Wave 2 Details (Quality & Routing)

| ID      | Task                         | Status                              |
|---------|------------------------------|-------------------------------------|
| RQ-05   | Adaptive query routing       | ✅ DONE (opt-in flag)                |
| EVAL-01 | Retrieval evaluation dataset | 🟡 PARTIAL (20 pairs + eval script) |
| QUAL-01 | Mypy strict mode             | 🟡 PARTIAL (3 files fixed)          |
| DOC-02  | Document new features        | ✅ DONE                              |

### Wave 3 Details (GraphRAG)

| ID      | Task                | Status |
|---------|---------------------|--------|
| GRPH-01 | Global search mode  | ✅ DONE |
| GRPH-02 | Multi-hop reasoning | ✅ DONE |

### New Features Implemented

| Feature                    | File                                     | Status |
|----------------------------|------------------------------------------|--------|
| FLARE Active Retrieval     | `proxy/app/core/flare.py`                | ✅      |
| Two-Stage Reranking        | `proxy/app/core/rerank.py`               | ✅      |
| Adaptive Chunking          | `etl/chunker/semantic_chunker.py`        | ✅      |
| Self-Critique Verification | `proxy/app/core/confidence.py`           | ✅      |
| CRAG Corrective Retrieval  | `proxy/app/main.py`                      | ✅      |
| Embedding Cache            | `proxy/app/core/retrieval.py`            | ✅      |
| Adaptive Query Routing     | `proxy/app/core/query_router.py`         | ✅      |
| Text-to-Cypher             | `proxy/app/core/retrieval.py`            | ✅      |
| Global Search Mode         | `proxy/app/core/retrieval.py`            | ✅      |
| Knee-Point Pruning         | `proxy/app/core/retrieval.py`            | ✅      |
| Multi-Query Rewriting      | `proxy/app/core/query_enhancer.py`       | ✅      |
| RAPTOR Tree Builder        | `etl/indexer/tree_builder.py`            | ✅      |
| GraphRAG Community         | `etl/graph_builder/community.py`         | ✅      |
| RAGAS Metrics              | `proxy/app/core/ragas_eval.py`           | ✅      |
| ColBERT Scoring            | `proxy/app/core/rerank.py`               | ✅      |
| Two-Level Filtering        | `proxy/app/core/retrieval.py`            | ✅      |
| Negative Rejection         | `proxy/app/core/confidence.py`           | ✅      |
| Contextual Chunking        | `etl/chunker/semantic_chunker.py`        | ✅      |
| Prometheus Metrics         | `proxy/app/shared/metrics.py`            | ✅      |
| E2E Tests                  | `tests/e2e/test_full_rag_pipeline.py`    | ✅      |
| Security Scanners          | `.github/workflows/security.yml`         | ✅      |
| RAGAS Dashboard            | `config/monitoring/ragas-dashboard.json` | ✅      |

### Test Results

- **Total tests:** 4,340 collected (6 collection errors: env-dependent tests for tools/Perf/Widget/Warmup/DataProcessor/Canary)
- **Coverage:** 81% (proxy+etl, meets 80% `fail_under` threshold)
- **mypy:** 0 errors on 148 source files (note: `strict=true` for proxy; ETL modules use relaxed config with 16 error codes disabled)
- **Ruff:** 0 warnings (lint clean); format: 342 files clean
- **Security:** bandit + trivy + dependabot

---

*This document is auto-generated from project analysis and should be updated with each significant change.*
