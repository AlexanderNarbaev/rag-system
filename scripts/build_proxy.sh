#!/bin/bash
# build-proxy.sh — Build RAG proxy Docker image
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Building RAG proxy image..."
echo "Context: $PROJECT_ROOT"
echo "Dockerfile: $PROJECT_ROOT/Dockerfile.proxy"

docker build \
    -f "$PROJECT_ROOT/Dockerfile.proxy" \
    -t rag-proxy:latest \
    "$PROJECT_ROOT"

echo ""
echo "✅ Image built: rag-proxy:latest"
echo ""
echo "Run with:"
echo "  docker compose -f proxy/docker-compose.yml up -d"
