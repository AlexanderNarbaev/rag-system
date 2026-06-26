#!/usr/bin/env bash
#
# Dependency vulnerability scanner for CI/CD pipelines.
#
# Uses pip-audit to scan installed packages for known vulnerabilities.
# Falls back to safety check if pip-audit is unavailable.
#
# Usage:
#     ./scripts/run_dependency_scan.sh            # Scan installed packages
#     ./scripts/run_dependency_scan.sh --strict   # Exit with error on any finding
#     DEPENDENCY_SCAN_ENABLED=true ./scripts/run_dependency_scan.sh
#
# Environment:
#     DEPENDENCY_SCAN_ENABLED — if "false", prints a message and exits 0.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ENABLED="${DEPENDENCY_SCAN_ENABLED:-false}"
STRICT_MODE=false

for arg in "$@"; do
    case "$arg" in
        --strict) STRICT_MODE=true ;;
        --help|-h)
            echo "Usage: $0 [--strict]"
            echo "  --strict   Exit with error code on any vulnerability finding"
            exit 0
            ;;
    esac
done

if [ "$ENABLED" != "true" ] && [ "$ENABLED" != "1" ]; then
    echo "[dependency-scan] Dependency scanning is disabled (DEPENDENCY_SCAN_ENABLED=$ENABLED). Skipping."
    exit 0
fi

echo "[dependency-scan] Starting dependency vulnerability scan..."

# Activate virtual environment if present
if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    source "$ROOT_DIR/.venv/bin/activate"
fi

# Try pip-audit first (preferred)
if command -v pip-audit &>/dev/null; then
    echo "[dependency-scan] Using pip-audit..."
    if pip-audit --requirement "$ROOT_DIR/requirements.txt" 2>/dev/null || \
       pip-audit 2>/dev/null; then
        echo "[dependency-scan] pip-audit: PASSED — no known vulnerabilities."
        exit 0
    else
        EXIT_CODE=$?
        if [ "$STRICT_MODE" = true ]; then
            echo "[dependency-scan] pip-audit: FAILED — vulnerabilities found!"
            exit $EXIT_CODE
        else
            echo "[dependency-scan] pip-audit: WARNING — vulnerabilities found (non-strict mode)."
            exit 0
        fi
    fi
fi

# Fall back to safety
if command -v safety &>/dev/null; then
    echo "[dependency-scan] Using safety..."
    if safety check --json 2>/dev/null | python -c "
import sys, json
data = json.load(sys.stdin)
vulns = data.get('vulnerabilities', [])
if vulns:
    for v in vulns:
        print(f\"  - {v.get('package_name', 'unknown')}: {v.get('advisory', 'N/A')}\")
    sys.exit(1)
print('No vulnerabilities found.')
"; then
        echo "[dependency-scan] safety: PASSED — no known vulnerabilities."
        exit 0
    else
        EXIT_CODE=$?
        if [ "$STRICT_MODE" = true ]; then
            echo "[dependency-scan] safety: FAILED — vulnerabilities found!"
            exit $EXIT_CODE
        else
            echo "[dependency-scan] safety: WARNING — vulnerabilities found (non-strict mode)."
            exit 0
        fi
    fi
fi

# Neither pip-audit nor safety available
echo "[dependency-scan] WARNING: Neither pip-audit nor safety is installed. Install with:"
echo "    pip install pip-audit"
echo "    # or"
echo "    pip install safety"
echo "[dependency-scan] Scan skipped — tools unavailable."
exit 0
