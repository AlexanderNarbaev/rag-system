#!/bin/bash
# scripts/run_e2e.sh
# Docker Compose E2E test runner
# Starts full stack (proxy + Qdrant + Redis + Neo4j), waits for health, runs E2E tests, tears down.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.e2e.yml"

echo "=== Starting E2E environment ==="
docker-compose -f "$COMPOSE_FILE" up -d --build

echo "=== Waiting for services to be healthy ==="
TIMEOUT=120
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    HEALTHY=$(docker-compose -f "$COMPOSE_FILE" ps -q proxy | xargs docker inspect -f '{{.State.Health.Status}}' 2>/dev/null || echo "starting")
    if [ "$HEALTHY" = "healthy" ]; then
        echo "Proxy is healthy after ${ELAPSED}s"
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

if [ "$HEALTHY" != "healthy" ]; then
    echo "ERROR: Proxy failed to become healthy within ${TIMEOUT}s"
    docker-compose -f "$COMPOSE_FILE" logs proxy
    docker-compose -f "$COMPOSE_FILE" down -v
    exit 1
fi

echo "=== Running E2E tests ==="
cd "$PROJECT_DIR"
source .venv/bin/activate 2>/dev/null || true
python -m pytest tests/e2e/ -v -m e2e --tb=short

EXIT_CODE=$?

echo "=== Tearing down E2E environment ==="
docker-compose -f "$COMPOSE_FILE" down -v

exit $EXIT_CODE
