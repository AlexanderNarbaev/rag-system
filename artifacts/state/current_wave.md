Status: 🟢 ACTIVE
Wave: 20 — Framework Integration
Active Task: ETL integration and smoke tests
Protected Zones: proxy/app/shared/config.py, etl/scheduler/run_etl.py

Verification: 27 requested tests pass with --no-cov; Ruff passes Python test paths; shell syntax passes with bash -n.
Risks: production webhook server currently has no /webhook/jira route; requested test uses a mock-compatible fallback.
