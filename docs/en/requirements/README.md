# RAG System — Complete Requirements Map

**Version:** 1.1 | **Date:** 2026-07-26 | **Status:** Approved

> **Purpose of this document:** A complete description of every system requirement with
> acceptance criteria, current status, and concrete verification steps. Once approved, each
> requirement will be confirmed by a test, then implemented (if necessary),
> then the documentation will be updated.

---

## How to read this document

| Field                  | Description                                                             |
|------------------------|-------------------------------------------------------------------------|
| **ID**                 | Unique requirement identifier                                           |
| **Description**        | What the system must do                                                 |
| **Acceptance criteria**| The concrete check after which the requirement is considered fulfilled  |
| **Status**             | ✅ Confirmed / ⚠️ Code exists, integration needed / ❌ Implementation needed |
| **Priority**           | CRITICAL / HIGH / MEDIUM / LOW                                          |
| **Reference**          | ADR, guide, or module this requirement relates to                       |

> **Status markers for different categories:**
> - FR with tests → ✅ Confirmed (tests/.../test_class)
> - FR without tests but with code → ⚠️ Code exists, integration needed (with Neo4j / LangGraph / smoke)
> - NFR → ✅ Infrastructure confirmed (benchmark on minikube)
> - Model Evolution → ✅ Confirmed (extracted into `model_evolution_service/`)

---

## Structure

| File                                           | Contents                                                      |
|------------------------------------------------|---------------------------------------------------------------|
| [01-core-api.md](01-core-api.md)               | FR-01 — FR-08: OpenAI-compatible API                          |
| [02-retrieval.md](02-retrieval.md)             | FR-09 — FR-18: Hybrid search and ranking                      |
| [03-knowledge-graph.md](03-knowledge-graph.md) | FR-19 — FR-25: Knowledge graph (Neo4j)                        |
| [04-agentic.md](04-agentic.md)                 | FR-26 — FR-31: Agentic orchestration (LangGraph)              |
| [05-quality.md](05-quality.md)                 | FR-32 — FR-39: HyDE, CRAG, Self-Reflection, Grounding         |
| [06-etl.md](06-etl.md)                         | FR-40 — FR-57: ETL Pipeline                                   |
| [07-auth.md](07-auth.md)                       | FR-73 — FR-94 (+FR-87b): HITL, Auth, RBAC                     |
| [08-model-evolution.md](08-model-evolution.md) | FR-95 — FR-102: Model Evolution                               |
| [09-tools.md](09-tools.md)                     | FR-104 — FR-120: KB Management, Agentic Tools                 |
| [10-mcp-deploy-obs.md](10-mcp-deploy-obs.md)   | FR-121 — FR-175: MCP, Deployment, Observability, Performance  |
| [11-nfr.md](11-nfr.md)                         | NFR-P, NFR-A, NFR-S, NFR-D, NFR-M, NFR-Q, NFR-C               |

---

## Additional documents

| File                                                  | Purpose                                                  |
|--------------------------------------------------------|----------------------------------------------------------|
| [TRACEABILITY.md](TRACEABILITY.md)                     | FR/NFR → implementation → tests mapping (full matrix)    |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)   | Implementation status report and production recommendations |

---

## Summary statistics

> **Snapshot as of 2026-07-26:** based on actual test coverage analysis (5823 passing tests).

| Category             | Total   | ✅ Confirmed | ⚠️ Code exists | ❌ Implementation needed |
|----------------------|---------|--------------|----------------|--------------------------|
| FR (Functional)      | 176     | 108          | 16             | 2 (+50 in reserve)       |
| NFR (Non-Functional) | 63      | 60           | 0              | 3 (reserve)              |
| CON (Constraints)    | 29      | 29           | 0              | 0                        |
| DEC (Decisions)      | 15      | 15           | 0              | 0                        |
| **TOTAL**            | **283** | **212**      | **16**         | **5**                    |

### Status breakdown

- **✅ 212 Confirmed** — implementation + tests (`tests/proxy/test_*.py`,
  `tests/etl/test_*.py`, `tests/integration/test_*.py`, `tests/performance/test_*.py`,
  `tests/deploy/test_*.py`, `tests/mcp_server/test_*.py`).
- **⚠️ 16 Code exists, integration needed** — 12 Graph/LangGraph requirements (FR-19–FR-31,
  except FR-25 and FR-30) + 4 Performance tuning requirements (FR-168–FR-171).
- **❌ 5 Implementation needed** — FR-25 (graph retention), FR-87b (OpenWebUI headers),
  NFR-A04 (DR drill — operational, not code), NFR-D04 (zero-downtime deploy validation),
  NFR-S09 (HTTPS/TLS — infra).

### Test coverage (5823 passing tests)

| Test file                                          | Count  | Covers              |
|----------------------------------------------------|--------|---------------------|
| `tests/proxy/test_core_api.py`                     | 85     | FR-01 — FR-18       |
| `tests/proxy/test_quality_pipeline.py`             | 53     | FR-32 — FR-39       |
| `tests/proxy/test_auth_rbac.py`                    | 70     | FR-73 — FR-94       |
| `tests/proxy/test_tools_kb.py`                     | 111    | FR-104 — FR-120     |
| `tests/proxy/test_observability.py`                | 30     | NFR observability   |
| `tests/proxy/test_nfr_*.py`                       | 27     | NFR-M, NFR-S        |
| `tests/etl/test_etl_requirements.py`               | 89     | FR-40 — FR-57       |
| `tests/etl/test_*.py` (others)                     | ~280   | ETL components      |
| `tests/integration/test_*.py`                      | ~150   | e2e scenarios       |
| `tests/mcp_server/test_mcp_requirements.py`        | 44     | FR-121 — FR-125     |
| `tests/deploy/test_helm_chart.py`                  | 50     | FR-149 — FR-167     |
| `tests/performance/test_nfr_benchmarks.py`         | 36     | NFR-P, NFR-Q        |
| `tests/resilience/` + `tests/e2e/` + `tests/performance/` (other) | ~4800  | Full suite          |

---

## Related documents

- [docs/en/guides/rag-maturity-assessment.md](../../en/guides/rag-maturity-assessment.md) — RAG maturity model
- [docs/en/guides/best-practices-checklist.md](../../en/guides/best-practices-checklist.md) — Production readiness
- [docs/en/guides/roadmap.md](../../en/guides/roadmap.md) — Roadmap
- [Architecture Decision Records](../adr/index.md)
