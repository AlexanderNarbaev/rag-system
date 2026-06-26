#!/bin/bash
# scripts/run_chaos.sh
# Chaos/resilience test runner
# These tests use mocked dependencies — no actual services needed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Running chaos/resilience tests ==="
cd "$PROJECT_DIR"
source .venv/bin/activate 2>/dev/null || true
python -m pytest tests/resilience/ -v -m chaos --tb=short
