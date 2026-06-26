#!/bin/bash
# scripts/run_benchmarks.sh
# Performance benchmark runner
# Requires the proxy service to be already running.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_URL="${E2E_SERVICE_URL:-http://localhost:8080}"

echo "=== Checking service availability at $SERVICE_URL ==="
if ! curl -sf "$SERVICE_URL/v1/health/live" > /dev/null 2>&1; then
    echo "ERROR: Service not available at $SERVICE_URL"
    echo "Start the service first, then run this script."
    exit 1
fi

echo "=== Running benchmark tests ==="
cd "$PROJECT_DIR"
source .venv/bin/activate 2>/dev/null || true
python -m pytest tests/benchmark/ -v -m benchmark --tb=short

echo "=== Benchmark results ==="
if [ -f tests/benchmark/benchmark_results.json ]; then
    python -m json.tool tests/benchmark/benchmark_results.json
fi
