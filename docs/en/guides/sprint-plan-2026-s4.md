# Sprint Plan — S4-2026

**Status:** IN PROGRESS (Wave 3 complete)  
**Date:** 2026-07-16  
**Previous sprint:** [S3-2026](sprint-plan-2026-s3-updated.md) — ✅ Complete  

---

## S4 Wave 1 — Foundation Fixes (Jul 15–18) ✅ COMPLETE

### P0-1: Fix mypy strict mode
- **Status:** ✅ COMPLETE — 313→0 errors across 139 source files
- **Commit:** `3019bed`
- **Effort:** XS (1h)
- **Role:** Backend Developer
- **DoD:** `make typecheck` returns 0 errors ✅

### P0-2: Fix test collection error  
- **Status:** ✅ COMPLETE — `tests/mcp_server/test_server.py` uses `pytest.importorskip`, collects cleanly
- **Effort:** S (2h)
- **Role:** QA Engineer
- **DoD:** Full suite collects cleanly (0 errors) ✅

### P0-3: Triage Dependabot PRs
- **Status:** ✅ COMPLETE — 7 PRs merged, rest triaged
- **Commits:** `72f776a` (#31), `33f16c5` (#32), `58d66bc` (#33), `089c661` (#35), `2c8b900` (#37), `7461804` (#47), `2c704b0` (#49)
- **Effort:** M (4h)
- **Role:** DevOps Engineer
- **DoD:** Non-breaking PRs merged, breaking ones triaged with issues ✅

### P0-4: Production bugfixes (Qdrant + LLM)
- **Status:** ✅ COMPLETE — 3 critical bugs fixed
- **Commits:** `4a1f2a4`, `9a418fe`, `39a6dcc`
- **Effort:** M (6h)
- **Role:** Backend Developer

### P0-5: Code quality cleanup
- **Status:** ✅ COMPLETE — ruff auto-fix: 8,137 issues → 23
- **Commits:** `170f04e`, `ab1159f`
- **Role:** Backend Developer

---

## S4 Wave 2 — Quality Push (Jul 19–Aug 2) ✅ COMPLETE

### P1-1 (EVAL-01): Expand retrieval eval dataset
- **Status:** ✅ COMPLETE — 20 → 452 pairs (+2160%)
- **Commit:** `9094b8d`
- **Effort:** HIGH (24h)
- **Role:** Data Analyst + ML Engineer
- **DoD:** MRR regression gate (≥0.75) in CI ✅

### P1-2 (QUAL-01): Full mypy strict compliance
- **Status:** ✅ COMPLETE — Done in Wave 1 (P0-1)
- **Commit:** `3019bed`
- **Effort:** HIGH (20h)
- **Role:** Backend Developer
- **DoD:** `strict = true` in CI, all modules passing ✅

### P1-3 (COV-01): Raise coverage to 80%
- **Status:** ✅ COMPLETE — 74.73% → 80.02%
- **Commit:** `9094b8d`
- **Effort:** HIGH (24h)
- **Role:** QA Engineer + Backend Developer

### P1-4 (DOC-04): Sprint documentation
- **Status:** ✅ COMPLETE — All docs updated
- **Commit:** `9094b8d`
- **Effort:** S (3h)
- **Role:** PM + Tech Writer
- **DoD:** S3 archived, S4 plan published, ADR indices updated ✅

### P1-5 (SEC-06): Dependency security audit
- **Status:** ✅ COMPLETE — 6 packages fixed, 0 HIGH/CRITICAL CVEs
- **Commit:** `9094b8d`
- **Effort:** S (3h)
- **Role:** Security Engineer
- **DoD:** No HIGH/CRITICAL CVEs remaining ✅

---

## S4 Wave 3 — Infrastructure (Aug 3–16) ✅ COMPLETE (5/7)

| ID | Description | Status | Commit | Effort | Role |
|----|-------------|--------|--------|--------|------|
| P2-1 | HTTPS/TLS automation | ✅ COMPLETE | `7638c8c` | M (12h) | DevOps |
| P2-2 | Secrets rotation automation | ✅ COMPLETE | `7638c8c` | M (16h) | DevOps + Backend |
| P2-3 | DB migration framework | ✅ COMPLETE | `7638c8c` | M (16h) | Backend |
| P2-4 | ADR-008 Java/Quarkus decision | ⏳ DEFERRED | — | M (8h) | Architect |
| P2-5 | Validate K8s Helm chart | ✅ COMPLETE | `7638c8c` | M (12h) | DevOps |
| P2-6 | Streaming pipeline stubs | ⏳ DEFERRED | — | M (8h) | Backend |
| P2-7 | Baseline latency benchmarks | ✅ COMPLETE | `7638c8c` | M (8h) | Backend + DevOps |

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

| Wave | Items | Hours | Status |
|------|-------|-------|--------|
| Wave 1 (P0) | 5 | ~13h | ✅ COMPLETE |
| Wave 2 (P1) | 5 | ~74h | ✅ COMPLETE |
| Wave 3 (P2) | 7 (5 done) | ~80h | ✅ COMPLETE (5/7) |
| Wave 4 (P3, stretch) | 5 | ~130h | ⏳ Planned |
| **Total** | **22** | **~297h** | **Waves 1-3 COMPLETE** |
