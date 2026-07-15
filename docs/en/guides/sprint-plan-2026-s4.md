# Sprint Plan — S4-2026

**Status:** IN PROGRESS (Wave 1 active)  
**Date:** 2026-07-15  
**Previous sprint:** [S3-2026](sprint-plan-2026-s3-updated.md) — ✅ Complete  

---

## S4 Wave 1 — Foundation Fixes (Jul 15–18)

### P0-1: Fix mypy strict mode ✅/🟡
- **Status:** 🟡 PARTIAL — numpy stub `Type statement is only supported in Python 3.12` error
- **Effort:** XS (1h)
- **Role:** Backend Developer
- **DoD:** `make typecheck` returns 0 errors

### P0-2: Fix test collection error  
- **Status:** 🔴 NOT STARTED — `tests/mcp_server/test_server.py` fails to collect
- **Effort:** S (2h)
- **Role:** QA Engineer
- **DoD:** Full suite collects cleanly (0 errors)

### P0-3: Triage Dependabot PRs
- **Status:** 🔴 NOT STARTED — 11 open PRs
- **Effort:** M (4h)
- **Role:** DevOps Engineer
- **DoD:** Non-breaking PRs merged, breaking ones triaged with issues

### P0-4: Production bugfixes (Qdrant + LLM)
- **Status:** ✅ COMPLETE — 3 critical bugs fixed
- **Commits:** `4a1f2a4`, `9a418fe`, `39a6dcc`
- **Effort:** M (6h)
- **Role:** Backend Developer

### P0-5: Code quality cleanup
- **Status:** ✅ COMPLETE — ruff auto-fix: 8,137 issues → 23
- **Commit:** `170f04e`, `ab1159f`
- **Role:** Backend Developer

---

## S4 Wave 2 — Quality Push (Jul 19–Aug 2)

### P1-1 (EVAL-01): Expand retrieval eval dataset
- **Target:** 20 → 200+ labeled pairs
- **Effort:** HIGH (24h)
- **Role:** Data Analyst + ML Engineer
- **DoD:** MRR regression gate (≥0.75) in CI

### P1-2 (QUAL-01): Full mypy strict compliance
- **Target:** 0 errors across entire codebase
- **Effort:** HIGH (20h)
- **Role:** Backend Developer
- **DoD:** `strict = true` in CI, all modules passing

### P1-3 (COV-01): Raise coverage to 80%
- **Current:** 75.70% (threshold 74%)
- **Target:** 80% with `fail_under = 80`
- **Effort:** HIGH (24h)
- **Role:** QA Engineer + Backend Developer

### P1-4 (DOC-04): Sprint documentation
- **Status:** 🟡 IN PROGRESS — `current_wave.md` created, S4 plan drafted
- **Effort:** S (3h)
- **Role:** PM + Tech Writer
- **DoD:** S3 archived, S4 plan published, ADR indices updated

### P1-5 (SEC-06): Dependency security audit
- **Effort:** S (3h)
- **Role:** Security Engineer
- **DoD:** No HIGH/CRITICAL CVEs remaining

---

## S4 Wave 3 — Infrastructure (Aug 3–16)

| ID | Description | Effort | Role |
|----|-------------|--------|------|
| P2-1 | HTTPS/TLS automation | M (12h) | DevOps |
| P2-2 | Secrets rotation automation | M (16h) | DevOps + Backend |
| P2-3 | DB migration framework | M (16h) | Backend |
| P2-4 | ADR-008 Java/Quarkus decision | M (8h) | Architect |
| P2-5 | Validate K8s Helm chart | M (12h) | DevOps |
| P2-6 | Streaming pipeline stubs | M (8h) | Backend |
| P2-7 | Baseline latency benchmarks | M (8h) | Backend + DevOps |

---

## S4 Wave 4 — Polish (Aug 17–24, stretch)

| ID | Description | Effort | Role |
|----|-------------|--------|------|
| P3-1 | C4 diagram gaps | S (4h) | Architect |
| P3-2 | OpenAPI export automation | S (2h) | Backend |
| P3-3 | ADR-008 POC | HIGH (40h) | Architect + Backend |
| P3-4 | OCR/audio/video RAG | VERY HIGH (80h+) | ML + Backend |
| P3-5 | Automated maturity review | S (4h) | PM + DevOps |

---

## Risk Matrix

| Risk | Prob | Impact | Mitigation |
|------|------|--------|------------|
| mypy 2.3 breaks annotations | HIGH | MED | Merge P0-1 first, test in branch |
| EVAL-01 labeling > 24h | MED | HIGH | Use HITL logs + SLM bootstrapping |
| mypy strict reveals 100+ errors | MED | MED | Fix module-by-module |
| K8s validation finds blockers | LOW | HIGH | Test in isolated namespace |

---

## Human Decisions Required

1. **ADR-008:** Accept Java/Quarkus migration or deprecate?
2. **EVAL-01:** Analyst available for labeling, or use SLM-assisted?
3. **Sprint cadence:** Single 8-week sprint or 2×4-week sprints?
4. **Coverage target:** 78% intermediate or straight to 80%?

---

## Effort Summary

| Wave | Items | Hours |
|------|-------|-------|
| Wave 1 (P0) | 3 | ~7h |
| Wave 2 (P1) | 5 | ~74h |
| Wave 3 (P2) | 7 | ~80h |
| Wave 4 (P3, stretch) | 5 | ~130h |
| **Total** | **20** | **~291h** |
