# RAG System — Team (Multi-Agent Framework v3.0)

## Roles & Members

### Strategic & Product Layer
| Role | Member | Responsibilities |
|------|--------|-----------------|
| **Product Manager** | — | Backlog, priorities, release criteria, roadmap ownership |
| **Business Analyst** | — | User scenarios, acceptance criteria (Gherkin), requirement traceability |
| **Strategic Steering Committee** | Alexandr Narbaev | Wave planning, cross-wave prioritization, architectural governance |
| **Domain Expert** | — | Golden dataset curation, answer quality verification, knowledge validation |

### Architecture & Technical Leadership
| Role | Member | Responsibilities |
|------|--------|-----------------|
| **Lead System Architect** | Alexandr Narbaev | Architecture design, ADRs, technology selection, system boundaries |
| **Tech Lead** | — | Code review, technical debt management, tooling standards, merge gating |
| **Tool Orchestrator** | — | MCP server coordination, tool SDK governance, parallel execution routing |
| **Focus & Session Manager** | — | Context compaction, checkpoint management, session persistence |

### Development & Engineering
| Role | Member | Responsibilities |
|------|--------|-----------------|
| **Backend Developer** | — | API, ETL, Qdrant/Neo4j/Redis/LLM integration |
| **ML Engineer** | — | Embeddings, reranking, HyDE, CRAG, hallucination detection, fine-tuning |
| **Data Engineer** | — | ETL pipelines, data quality, incremental extraction, WAL management |
| **Frontend Developer** | — | OpenWebUI, admin panel, widget embedding |
| **UX/UI Designer** | — | User research, interaction design, accessibility, component library |

### Quality & Security
| Role | Member | Responsibilities |
|------|--------|-----------------|
| **QA Engineer** | — | Unit/integration/e2e/performance tests |
| **Security Engineer** | — | JWT, Keycloak, LDAP/AD, RBAC, vulnerability scanning |
| **Dual-Guardian Validator (Code)** | — | Static analysis enforcement, type safety, lint rules |
| **Dual-Guardian Validator (Domain)** | — | Business logic verification, acceptance criteria validation |
| **Infrastructure Sentinel** | — | CI/CD health, K8s probes, backup integrity, resource alerts |

### Operations & Integration
| Role | Member | Responsibilities |
|------|--------|-----------------|
| **DevOps Engineer** | — | CI/CD, Docker, Kubernetes, monitoring, Helm charts |
| **Integration Manager** | — | Module integration, staging coordination, contract validation |

### Documentation & Analytics
| Role | Member | Responsibilities |
|------|--------|-----------------|
| **Technical Writer** | — | API docs, architecture docs, runbooks, ADR authoring |
| **Doc-Sync Reflector** | — | Bilingual doc sync (EN/RU), changelog alignment, compliance traceability |
| **Data Analyst** | — | RAG quality metrics, dashboards, SLI/SLO monitoring |

## Current Sprint — Wave 20

- **Status:** 🟢 Active
- **Focus:** Multi-Agent Continuous Development Framework v3.0 Integration
- **Active Task:** Creating artifact structure and checkpoint files
- **Protected Zones:** proxy/app/shared/config.py, etl/scheduler/run_etl.py

## Checkpoint State

- **Last commit:** `fe1b65d`
- **Timestamp:** 2026-07-18T19:11:00+03:00
- **Tests:** 5025 passing | **Coverage:** 84.29%
- **Session status:** active

## Active Goals

1. **Framework Integration** — Integrate Multi-Agent Continuous Development Framework v3.0 into all project artifacts
2. **Checkpoint Infrastructure** — Establish `artifacts/state/` persistence layer for session continuity
3. **Enhanced Agent Roles** — Deploy 23-role agent team with Tool Orchestrator, Focus Manager, Dual Guardians
4. **Bilingual Documentation Sync** — Ensure EN/RU parity across all docs via Doc-Sync Reflector
5. **Strategic Blocking** — Implement [STRATEGIC_NEEDED] gate for protected zone modifications

## Development Rules

1. **Always commit + push after each wave** — never leave uncommitted work
2. **Run full verification**: lint, format, typecheck, tests before every commit
3. **Test coverage >= 80%** — enforced at CI level
4. **No Russian in code or comments** — English only (AGENTS.md policy)
5. **Keep CHANGELOG.md and docs in sync** with every feature
6. **Check .rag-team/state.json** for current project snapshot
7. **Push to BOTH remotes**: origin (GitHub) + gitverse (GitVerse mirror)
8. **Compliance**: Every change must be traceable to a requirement in compliance-requirements.md
9. **Graceful degradation** — every component must fail independently
10. **Air-gapped first** — no external API calls at runtime
11. **Session persistence** — update artifacts/state/session_checkpoint.json after every action
12. **Protected zones** — no modification of config.py or run_etl.py without Strategic Steering Committee
13. **Bilingual docs** — all documentation must exist in EN and RU; Doc-Sync Reflector validates parity
14. **Checkpoint on resume** — load session_checkpoint.json and context_compaction_log.md at session start
15. **[STRATEGIC_NEEDED]** — tag blocking decisions; do not proceed past unacknowledged gates

## Communication Protocols

| Channel | Purpose | Frequency |
|---------|---------|-----------|
| GitHub Issues | Bug tracking, feature requests | On-demand |
| GitHub PRs | Code review, CI gating | Per-change |
| CHANGELOG.md | Release notes per wave | Per-wave |
| `.rag-team/` | Team state, sprint status, role docs | Per-wave |
| `artifacts/state/` | Session checkpoint, context compaction, wave tracking | Per-action |
| Compliance Doc | FR/NFR traceability and MET status | Per-wave |

## Decision Authority

- Architecture changes require an ADR (see `docs/en/adr/`)
- Feature toggles follow CON-10 (optional complexity, default off)
- All PRs require CI green (lint + typecheck + tests) before merge
- Protected zone changes require [STRATEGIC_NEEDED] gate clearance from Strategic Steering Committee
- Wave transitions require session checkpoint commit and context compaction log
