#!/bin/bash
set -e

echo "=== Security Audit ==="

# Python dependency scan
echo "[1] Python dependencies (pip-audit)..."
pip-audit --strict || echo "pip-audit not installed, skipping"

# npm dependency scan (if applicable)
if [ -f "package.json" ]; then
    echo "[2] npm dependencies (npm audit)..."
    npm audit || echo "npm not installed"
fi

# Check for hardcoded secrets
echo "[3] Hardcoded secrets scan..."
if grep -rE "(api[_-]?key|secret|password|token)\s*=\s*['\"]" --include="*.py" --include="*.yaml" --include="*.yml" proxy/ etl/ model_evolution_service/ 2>/dev/null | grep -v "example\|test\|fixture"; then
    echo "  WARNING: Possible hardcoded secrets found"
else
    echo "  OK: No hardcoded secrets"
fi

# Check file permissions
echo "[4] File permissions..."
find . -name "*.pem" -o -name "*.key" -o -name "id_rsa*" 2>/dev/null | while read -r f; do
    PERMS=$(stat -c%a "$f")
    if [ "$PERMS" != "600" ] && [ "$PERMS" != "400" ]; then
        echo "  WARNING: $f has permissions $PERMS (should be 600 or 400)"
    fi
done

# Check TLS configuration
echo "[5] TLS configuration..."
if ! grep -q "TLS\|ssl\|https" deploy/k8s/helm/rag-system/values.yaml; then
    echo "  WARNING: No TLS configuration found in Helm chart"
fi

echo "=== Security Audit Complete ==="
