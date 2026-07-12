# RAG System — Comprehensive Project Checklist

**Last Updated:** 2026-07-12
**Version:** v2.0.0
**RAG Maturity Level:** 5 (Self-Correcting RAG) — Score 4.5/5.0
**Production Readiness:** 71.5/80 (89%)

---

This document is the **single source of truth** for the current state of the RAG system project. It consolidates architecture, testing, documentation, deployment, and operational status into one actionable checklist.

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
11. [Observability & Monitoring](#11-observability--monitoring)
12. [Open Gaps & Action Items](#12-open-gaps--action-items)
13. [Roadmap Status](#13-roadmap-status)

---

## 1. Project Overview

| Property | Value |
|----------|-------|
| **Name** | RAG System — Corporate Knowledge Assistant |
| **Version** | v2.0.0 |
| **Python** | ≥ 3.11 |
| **Architecture** | 3-layer (ETL + Proxy + HITL) + MCP Server + Model Evolution + Agentic Tools |
| **Git Remotes** | GitHub: `AlexanderNarbaev/rag-system`, GitVerse: `AlexandrNarbaev/rag-system` |
| **Latest Commit** | `f9d0413` — fix: orchestrator test patches for restructured modules |
| **Total Python Files** | ~200+ |
| **Total Test Files** | 106 |
| **Total Documentation Files** | 118 (EN + RU) |

---

## 2. Architecture Inventory

### 2.1 Proxy Layer (`proxy/app/`) — 65 Python modules

| Package | Modules | Purpose |
|---------|---------|---------|
| `api/` | 9 | Endpoint handlers: chat, auth, health, admin, feedback, files, tools, widget, metrics |
| `auth/` | 5 | JWT, RBAC, LDAP, API keys, user DB |
| `core/` | 13 + 5 sub | RAG pipeline: retrieval, rerank, confidence, grounding, evaluation, HyDE, query enhancer, token optimizer, context builder, orchestrator |
| `llm/` | 5 + 3 sub | LLM routing, SLM routing, remote services, provider adapters (base, openai, utils) |
| `tools/` | 12 + 2 sub | Agentic tools: SDK, registry, declarative, OpenAPI discovery, orchestrator, security, audit, metrics |
| `shared/` | 20 | Utilities: config, cache, middleware, logging, metrics, rate limiter, sanitizer, circuit breaker, tracing, i18n, MinIO, etc. |
| `model_evolution/` | 16 | Fine-tuning: trainers (SLM/LLM/reranker), adapter manager, canary controller, eval gate, model registry, experiment tracker |

### 2.2 ETL Layer (`etl/`) — 22 Python modules

| Package | Modules | Purpose |
|---------|---------|---------|
| `extractors/` | 9 | Confluence, Jira, GitLab, books, docs, chats, images, tables, base |
| `chunker/` | 4 | Semantic chunker, code chunker, table extractor, hash versioning |
| `graph_builder/` | 2 + yaml | Entity extractor, Neo4j loader, schema |
| `indexer/` | 3 | Qdrant hybrid, live vector lake, WAL manager |
| `scheduler/` | 6 | ETL orchestrator, streaming pipeline, webhook server, cold storage cleanup |

### 2.3 Supporting Components

| Component | Location | Status |
|-----------|----------|--------|
| MCP Server | `mcp_server/` | ✅ Implemented (STDIO + HTTP transports) |
| HITL Dashboard | `dashboard/` | ✅ Implemented (Streamlit) |
| TUI | `tui/` | ✅ Implemented (Terminal UI) |
| Monitoring | `config/monitoring/` | ✅ Prometheus + Grafana (3 dashboards, alert rules) |
| Helm Chart | `deploy/k8s/helm/rag-system/` | ✅ 14 files, HPA, probes, secrets |
| Ops Scripts | `scripts/ops/` | ✅ Backup/restore for Qdrant, Neo4j, Redis |

---

## 3. Component Status Matrix

| Component | Implemented | Tested | Documented | Deployed |
|-----------|:-----------:|:------:|:----------:|:--------:|
| Hybrid Retrieval (dense+sparse RRF) | ✅ | ✅ | ✅ | ✅ |
| Cross-Encoder Reranking | ✅ | ✅ | ✅ | ✅ |
| Dual-LLM Architecture (SLM+LLM) | ✅ | ✅ | ✅ | ✅ |
| OpenAI-Compatible Proxy API | ✅ | ✅ | ✅ | ✅ |
| LangGraph Agentic Orchestrator | ✅ | ✅ | ✅ | ✅ |
| GraphRAG (Neo4j) | ✅ | ✅ | ✅ | ✅ |
| Redis Multi-Tier Cache | ✅ | ✅ | ✅ | ✅ |
| JWT Authentication | ✅ | ✅ | ✅ | ✅ |
| RBAC (4 roles) | ✅ | ✅ | ✅ | ✅ |
| LDAP/AD Integration | ✅ | ✅ | ✅ | ✅ |
| Input Sanitization | ✅ | ✅ | ✅ | ✅ |
| Rate Limiting | ✅ | ✅ | ✅ | ✅ |
| Prometheus Metrics | ✅ | ✅ | ✅ | ✅ |
| Structured Logging | ✅ | ✅ | ✅ | ✅ |
| Health/Liveness/Readiness Probes | ✅ | ✅ | ✅ | ✅ |
| Confidence Scoring | ✅ | ✅ | ✅ | ✅ |
| HyDE Query Expansion | ✅ | ✅ | ✅ | ✅ |
| Hallucination Detection (NLI) | ✅ | ✅ | ✅ | ✅ |
| Self-Reflection Loops | ✅ | ✅ | ✅ | ✅ |
| Corrective Re-generation | ✅ | ✅ | ✅ | ✅ |
| Token Optimizer (BPE) | ✅ | ✅ | ✅ | ✅ |
| HITL Feedback System | ✅ | ✅ | ✅ | ✅ |
| Self-Enrichment (feedback → Qdrant) | ✅ | ✅ | ✅ | ✅ |
| WAL-Based Incremental ETL | ✅ | ✅ | ✅ | ✅ |
| Streaming ETL (Redis Streams) | ✅ | ✅ | ✅ | ✅ |
| Webhook-Driven Ingestion | ✅ | ✅ | ✅ | ✅ |
| Agentic Tools SDK (`@tool`) | ✅ | ✅ | ✅ | ✅ |
| YAML/JSON Declarative Tools | ✅ | ✅ | ✅ | ✅ |
| OpenAPI Auto-Discovery | ✅ | ✅ | ✅ | ✅ |
| Tool Orchestrator (parallel+deps) | ✅ | ✅ | ✅ | ✅ |
| Federated RAG (fan-out + RRF) | ✅ | ✅ | ✅ | ✅ |
| Model Evolution (LoRA/QLoRA) | ✅ | ❌ | ✅ | ✅ |
| Canary Controller | ✅ | ❌ | ✅ | ✅ |
| Adapter Manager (hot-reload) | ✅ | ❌ | ✅ | ✅ |
| EvalGate CI/CD Gating | ✅ | ❌ | ✅ | ✅ |
| MLflow Experiment Tracking | ✅ | ❌ | ✅ | ✅ |
| MinIO Object Storage | ✅ | ✅ | ✅ | ✅ |
| MCP Server | ✅ | ❌ | ✅ | ✅ |
| OpenWebUI Integration | ✅ | ❌ | ✅ | ✅ |
| Multi-Language i18n | ✅ | ✅ | ✅ | ✅ |
| A/B Test Harness | ✅ | ✅ | ✅ | ✅ |
| Circuit Breaker | ✅ | ✅ | ✅ | ✅ |
| Response Compression (gzip/brotli) | ✅ | ✅ | ✅ | ✅ |
| Model Warm-up | ✅ | ✅ | ✅ | ✅ |
| Kubernetes Helm Chart | ✅ | ❌ | ✅ | ✅ |
| Backup Automation | ✅ | ❌ | ✅ | ✅ |
| DR Runbook | ✅ | N/A | ✅ | N/A |

---

## 4. ADR Status

| # | Title | Status | Date |
|---|-------|--------|------|
| ADR-001 | BAAI/bge-m3 Embedding Model | ✅ Accepted | 2026-06-22 |
| ADR-002 | Qdrant Hybrid Search | ✅ Accepted | 2026-06-22 |
| ADR-003 | Dual-LLM Architecture (SLM+LLM) | ✅ Accepted | 2026-06-22 |
| ADR-004 | OpenAI-Compatible Proxy | ✅ Accepted | 2026-06-22 |
| ADR-005 | Version-Aware Indexing | ✅ Accepted | 2026-06-22 |
| ADR-006 | Agentic RAG (LangGraph) | ✅ Accepted | 2026-06-22 |
| ADR-007 | HITL Feedback System | ✅ Accepted | 2026-06-22 |
| ADR-008 | Java/Quarkus Hybrid Migration | 🟡 Proposed | 2026-07-03 |
| ADR-009 | Agentic Tools Expansion | ✅ Accepted | 2026-07-05 |
| ADR-010 | Model Evolution (Fine-Tuning) | ✅ Accepted | 2026-07-05 |
| ADR-011 | Incremental Architecture | ✅ Accepted | 2026-07-10 |
| ADR-012 | OpenWebUI Integration | ✅ Accepted | 2026-07-10 |
| ADR-013 | MCP Server Architecture | ✅ Accepted | 2026-07-10 |
| ADR-014 | MinIO Object Storage | ✅ Accepted | 2026-07-10 |

**Summary:** 13 Accepted, 1 Proposed (ADR-008), 0 Deprecated

---

## 5. Documentation Inventory

### 5.1 Guides (29 per language × 2 = 58 files)

| Category | Guides |
|----------|--------|
| **Getting Started** | quickstart, user-guide, api-examples |
| **Configuration** | configuration-reference, development-guide |
| **Deployment** | deployment-guide, operations-guide, runbook |
| **Security** | security-guide, access-control-rbac |
| **Observability** | monitoring-guide, troubleshooting |
| **Architecture** | rag-maturity-assessment, best-practices-checklist, performance-quality, disaster-recovery-runbook, roadmap |
| **Data Pipeline** | etl-guide, extensibility-data-sources, knowledge-graph-strategy, knowledge-graph-guide |
| **Advanced Features** | federated-rag, agentic-tools-sdk, agentic-tools-declarative, agentic-tools-openapi, model-evolution |
| **Integration** | integration-guide, integration-opencode, mcp-server-guide |

### 5.2 Reference Documents (EN + RU = 18 files)

| Document | Lines | Content |
|----------|-------|---------|
| `architecture.md` | Full | 6-layer architecture, C4 diagrams, component descriptions |
| `api_reference.md` | 968 | 25 endpoints, schemas, auth, RBAC, examples |
| `sli_slo.md` | Full | 8 SLIs, SLO targets, PromQL queries, error budgets |
| `deploy_proxy.md` | 588 | Docker Compose, K8s, air-gapped, scaling |
| `deploy_etl.md` | 477 | Pipeline config, scheduling, source setup |

### 5.3 Diagrams (9 files)

- C4 Level 1 — System Context (11 nodes)
- C4 Level 2 — Containers (10 nodes)
- C4 Level 3 — Proxy Components (13 nodes)
- C4 Level 3 — ETL Components (14 nodes)
- Full architecture (Excalidraw)

### 5.4 Documentation Gaps

| Gap | Priority |
|-----|----------|
| No CHANGELOG.md found (mentioned in checklist as existing) | Medium |
| AGENTS.md references `hitl_dashboard/` but actual dir is `dashboard/` | Low |
| No C4 diagram for MCP Server component | Low |
| No component diagram for Model Evolution pipeline | Low |

---

## 6. Test Suite Status

### 6.1 Test File Distribution

| Directory | Test Files | Coverage |
|-----------|-----------|----------|
| `tests/proxy/` | 60 | Core proxy modules |
| `tests/proxy/tools/` | 12 | Agentic tools subsystem |
| `tests/etl/` | 22 | ETL extractors, chunkers, indexers |
| `tests/integration/` | 5 | Cross-component flows |
| `tests/e2e/` | 3 | Full-stack end-to-end |
| `tests/performance/` | 2 | Load testing & benchmarks |
| `tests/resilience/` | 2 | Chaos engineering |
| **Total** | **106** | |

### 6.2 Test Configuration

| Setting | Value |
|---------|-------|
| Coverage target | 80% minimum (`fail_under = 80`) |
| Coverage sources | `proxy/`, `etl/` |
| Coverage exclusions | `model_evolution/*`, `streaming_pipeline.py`, `static/*` |
| Pytest markers | `e2e`, `benchmark`, `chaos`, `asyncio`, `slow`, `integration` |
| Conftest files | 5 (root, proxy, e2e, resilience, performance) |

### 6.3 Test Gaps

| Gap | Severity | Details |
|-----|----------|---------|
| **No `tests/model_evolution/`** | 🔴 High | 13 modules (trainer, adapter_manager, canary_controller, eval_gate, etc.) have zero test coverage |
| **No `tests/mcp_server/`** | 🟡 Medium | MCP server (server.py) has no tests at all |
| **No `tests/etl/conftest.py`** | 🟡 Medium | ETL tests lack shared fixtures |
| **No `tests/integration/conftest.py`** | 🟡 Medium | Integration tests lack shared service fixtures |
| **`model_evolution` excluded from coverage** | 🔴 High | Major subsystem masked from coverage tracking |
| **Marker inconsistency** | 🟡 Low | `integration` marker defined but not used in Makefile target; `slow` marker unused |
| **Naming inconsistency** | 🟡 Low | `_enhanced` suffix files unclear if additive or replacement |

### 6.4 Makefile Test Targets

| Target | Scope |
|--------|-------|
| `make test` | All tests |
| `make test-proxy` | Proxy unit tests |
| `make test-etl` | ETL unit tests |
| `make test-integration` | Integration tests |
| `make test-performance` | Performance/benchmark tests |
| `make test-e2e` | End-to-end tests |
| `make test-resilience` | Chaos/resilience tests |
| `make benchmark` | Benchmark suite |

---

## 7. Production Readiness Scorecard

| # | Dimension | Score | % | Trend | Key Gaps |
|---|-----------|-------|---|-------|----------|
| 1 | Code Quality | 9.0/10 | 90% | ↑ | Type hints partial, mypy partial |
| 2 | Testing | 8.5/10 | 85% | ↑ | Retrieval eval dataset, model_evolution tests |
| 3 | Security | 9.0/10 | 90% | → | HTTPS partial, API key rotation |
| 4 | Observability | 8.5/10 | 85% | ↑ | Distributed tracing partial |
| 5 | Reliability | 9.0/10 | 90% | ↑ | Circuit breaker refinement |
| 6 | Performance | 9.5/10 | 95% | → | — |
| 7 | Operations | 8.0/10 | 80% | ↑ | IaC partial, secrets mgmt, DB migrations |
| 8 | Documentation | 10/10 | 100% | → | — |
| **Total** | | **71.5/80** | **89%** | | |

---

## 8. Deployment & Infrastructure

### 8.1 Docker Compose Variants

| File | Purpose | Services |
|------|---------|----------|
| `proxy/docker-compose.yml` | Development | Qdrant, Neo4j, Redis, MinIO, rag-proxy |
| `proxy/docker-compose.override.yml` | Local overrides | — |
| `proxy/docker-compose.standalone.yml` | Proxy-only | rag-proxy |
| `proxy/docker-compose.ha.yml` | High availability | Clustered setup |
| `deploy/docker/docker-compose.prod.yml` | Production | + vLLM, resource limits, logging rotation |
| `deploy/docker/docker-compose.openwebui.yml` | OpenWebUI | + OpenWebUI frontend |
| `config/monitoring/docker-compose.monitoring.yml` | Monitoring | Grafana + Prometheus |

### 8.2 Kubernetes / Helm

| Resource | Kind | Replicas | Storage |
|----------|------|----------|---------|
| Proxy | Deployment | 2 (HPA: 2-10) | EmptyDir |
| Qdrant | StatefulSet | 1 | 50Gi PVC |
| Neo4j | StatefulSet | 1 | 20Gi PVC |
| Redis | Deployment | 1 | 10Gi PVC |

### 8.3 Makefile Targets (36 total)

| Category | Targets |
|----------|---------|
| Setup | `install`, `install-dev`, `install-one-line`, `wizard`, `setup` |
| Run | `run` |
| ETL | `etl`, `etl-confluence`, `etl-jira`, `etl-gitlab` |
| Testing | `test`, `test-proxy`, `test-etl`, `test-integration`, `test-performance`, `test-e2e`, `test-resilience`, `benchmark` |
| Quality | `lint`, `format`, `format-check`, `typecheck` |
| Docker | `docker-build`, `docker-up`, `docker-down`, `docker-logs` |
| Backup | `backup`, `restore`, `verify-backups` |
| Deploy | `deploy`, `deploy-prod` |
| UI | `dashboard`, `tui`, `mcp-server` |
| CI | `all` |

---

## 9. Configuration & Environment

### 9.1 Required Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `EMBEDDER_MODEL` | Embedding model name | REQUIRED |
| `RERANKER_MODEL` | Reranker model name | REQUIRED |
| `LLM_MODEL_NAME` | LLM model name | REQUIRED |
| `LLM_ENDPOINT` | LLM backend URL | REQUIRED |

### 9.2 Optional Feature Flags

| Flag | Default | Feature |
|------|---------|---------|
| `USE_REDIS` | `false` | Redis caching layer |
| `GRAPH_ENABLED` | `false` | Neo4j knowledge graph |
| `USE_LANGGRAPH` | `false` | Agentic orchestration |
| `AUTH_ENABLED` | `false` | JWT authentication |
| `RBAC_ENABLED` | `false` | Role-based access control |
| `RATE_LIMIT_ENABLED` | `false` | Token bucket rate limiting |
| `METRICS_ENABLED` | `false` | Prometheus metrics |
| `TOOLS_ENABLED` | `false` | Agentic tool calling |
| `LIVE_SOURCES_ENABLED` | `false` | Live Confluence/Jira/GitLab |
| `ENRICHMENT_ENABLED` | `false` | Self-enrichment feedback loop |

### 9.3 ETL Configuration (`etl/config/etl_config.yaml`)

| Section | Key Settings |
|---------|-------------|
| Global | timeout=120s, retries=5, retry_delay=5s |
| WAL | checkpoint at `./wal/etl_wal.json`, file locking |
| Confluence | Bearer token auth, space filters, incremental, attachments |
| Jira | Bearer token auth, JQL filter, incremental, changelog |
| GitLab | PAT auth, project filter, file extensions (py, md, Dockerfile, yaml, sql) |
| Chunking | max 8000 tokens, 200 overlap, 100 min |
| Indexing | Qdrant host/port, embedder model, batch size, hot/cold/lake dirs |
| Streaming | Redis Streams, webhook server on port 9000 |
| Schedule | Cron `0 2 * * *` (daily 02:00 UTC) |
| Graph | spaCy NER or SLM entity extraction |

---

## 10. Security Checklist

| # | Item | Status |
|---|------|--------|
| 10.1 | JWT authentication (access + refresh tokens) | ✅ |
| 10.2 | RBAC with 4 roles (admin/expert/user/read-only) | ✅ |
| 10.3 | LDAP/AD integration | ✅ |
| 10.4 | Keycloak OIDC SSO | ✅ |
| 10.5 | API key authentication | ✅ |
| 10.6 | Input sanitization (SQL/XSS/length) | ✅ |
| 10.7 | Rate limiting (token bucket per IP) | ✅ |
| 10.8 | Sensitive data masking in logs | ✅ |
| 10.9 | Audit logging (auth events, admin actions) | ✅ |
| 10.10 | No hardcoded secrets | ✅ |
| 10.11 | HTTPS/TLS termination | 🟡 Partial (nginx documented) |
| 10.12 | Dependency vulnerability scanning | ✅ (pip-audit) |
| 10.13 | Tool sandboxing & permission checks | ✅ |
| 10.14 | CORS configuration | ✅ |
| 10.15 | Secret rotation automation | ❌ Not implemented |

---

## 11. Observability & Monitoring

### 11.1 Prometheus Metrics

- 12+ custom metrics (`rag_*` prefix)
- Counters: requests, cache hits/misses, errors
- Histograms: request duration, retrieval duration, rerank duration, LLM duration
- Gauges: warmup status, active connections, circuit breaker state

### 11.2 Grafana Dashboards (3)

| Dashboard | Panels |
|-----------|--------|
| `rag-overview.json` | Request rate, latency, errors, cache, tokens, confidence, feedback |
| `rag-infrastructure.json` | CPU, memory, disk, network per service |
| `rag-retrieval-quality.json` | MRR, Recall@k, nDCG, precision over time |

### 11.3 Alert Rules

| Severity | Condition |
|----------|-----------|
| Critical | LLM unavailable > 2 min |
| Critical | Qdrant unavailable > 1 min |
| Warning | p95 latency > 5s |
| Warning | Error rate > 5% |
| Warning | Cache hit ratio < 20% |
| Info | Disk usage > 80% |

### 11.4 SLI/SLO Definitions

| SLI | SLO Target |
|-----|-----------|
| Availability | 99.5% |
| p95 Latency | < 5s |
| Error Rate | < 1% |
| Cache Hit Ratio | > 30% |

---

## 12. Open Gaps & Action Items

### 🔴 Critical (Blocking)

| # | Gap | Impact | Effort |
|---|-----|--------|--------|
| 1 | No tests for `model_evolution/` (13 modules) | Untested fine-tuning pipeline | High |
| 2 | `model_evolution` excluded from coverage tracking | Risk masked | Low |
| 3 | No tests for MCP Server | Untested IDE integration | Medium |

### 🟡 Important (Non-blocking)

| # | Gap | Impact | Effort |
|---|-----|--------|--------|
| 4 | Retrieval evaluation dataset (200+ labeled pairs) | No automated quality regression | High |
| 5 | Mypy strict mode not passing | Type safety gaps | Medium |
| 6 | HTTPS/TLS not fully automated | Manual cert setup | Medium |
| 7 | Secrets rotation automation | Manual rotation only | Medium |
| 8 | Database migration framework | Ad-hoc migrations | Medium |
| 9 | No CHANGELOG.md | Release tracking incomplete | Low |
| 10 | `tests/etl/conftest.py` missing | ETL test isolation | Low |
| 11 | `tests/integration/conftest.py` missing | Integration test fixtures | Low |
| 12 | ADR-008 (Java migration) still "Proposed" | Decision pending | Low |
| 13 | AGENTS.md `hitl_dashboard/` → actual `dashboard/` | Doc inconsistency | Low |

### 🟢 Nice to Have

| # | Gap | Impact | Effort |
|---|-----|--------|--------|
| 14 | OpenAPI/Swagger export for API | Developer experience | Low |
| 15 | C4 diagram for MCP Server | Documentation completeness | Low |
| 16 | Component diagram for Model Evolution | Documentation completeness | Low |
| 17 | Quarterly RAG maturity review cadence | Process | Low |

---

## 13. Roadmap Status

### Completed Phases

| Phase | Theme | Status |
|-------|-------|--------|
| Phase 1 | Core Infrastructure | ✅ Complete |
| Phase 2 | Self-Improving RAG | ✅ Complete |
| Phase 3 | Token Optimization & Quality | ✅ Complete |
| Phase 4 | Security & Multi-Tenancy | ✅ Complete |
| Phase 5 | Multi-Modal RAG | ✅ Complete |
| Phase 6 | Real-Time Indexing & Streaming | ✅ Complete |
| Phase 7 | Production Hardening | ✅ Complete |
| Phase 8 | Self-Correcting RAG | ✅ Complete |

### Beyond Phases (v2.0)

| Feature | Status |
|---------|--------|
| Federated RAG | ✅ Complete |
| Agentic Tools Expansion | ✅ Complete |
| Model Evolution (LoRA/QLoRA) | ✅ Complete |
| MCP Server | ✅ Complete |
| OpenWebUI Integration | ✅ Complete |
| MinIO Object Storage | ✅ Complete |
| Incremental Architecture | ✅ Complete |

### Future Horizons

| Horizon | Theme | Status |
|---------|-------|--------|
| Near-term | Java/Quarkus Hybrid Migration (ADR-008) | 🟡 Proposed |
| Mid-term | Advanced Multi-Modal (video/audio, OCR) | 📋 Planned |
| Mid-term | Autonomous Knowledge Curation | 📋 Planned |
| Long-term | Federated Learning across instances | 📋 Planned |

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

*This document is auto-generated from project analysis and should be updated with each significant change.*
