#!/bin/bash
# Distributed deployment verification
# Usage: MACHINE_A_IP=10.0.1.10 GPUSTACK_TOKEN=sk-xxx bash scripts/verify_distributed.sh

set -e

MACHINE_A_IP="${MACHINE_A_IP:-10.0.1.10}"
MACHINE_B_IP="${MACHINE_B_IP:-localhost}"
GPUSTACK_TOKEN="${GPUSTACK_TOKEN:-dummy}"
PROXY_PORT="${PROXY_PORT:-8080}"
OPENWEBUI_PORT="${OPENWEBUI_PORT:-3000}"

echo "=== Distributed RAG Verification ==="
echo "Machine A (GPUStack): $MACHINE_A_IP"
echo "Machine B (Proxy):    $MACHINE_B_IP"
echo ""

# Test 1: GPUStack connectivity
echo "[1/7] GPUStack (Machine A) — LLM/SLM/Embedder/Reranker..."
curl -sf -H "Authorization: Bearer $GPUSTACK_TOKEN" \
  http://$MACHINE_A_IP:8080/v1/models 2>/dev/null | python3 -m json.tool 2>/dev/null | head -20 || echo "  FAIL: Cannot reach GPUStack"

# Test 2: Qdrant
echo ""
echo "[2/7] Qdrant (Machine B)..."
curl -sf http://$MACHINE_B_IP:6333/collections 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  FAIL: Cannot reach Qdrant"

# Test 3: Redis
echo ""
echo "[3/7] Redis (Machine B)..."
if command -v redis-cli &> /dev/null; then
    redis-cli -h $MACHINE_B_IP -p 6379 ping 2>/dev/null || echo "  FAIL: Redis not responding"
else
    echo "  SKIP: no redis-cli"
fi

# Test 4: Proxy liveness
echo ""
echo "[4/7] Proxy liveness (Machine B)..."
curl -sf http://$MACHINE_B_IP:$PROXY_PORT/v1/health/live 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  FAIL: Proxy not responding"

# Test 5: Proxy readiness (checks all deps)
echo ""
echo "[5/7] Proxy readiness (Machine B)..."
curl -sf http://$MACHINE_B_IP:$PROXY_PORT/v1/health/ready 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  FAIL: Proxy not ready"

# Test 6: Model listing
echo ""
echo "[6/7] Models (Machine B)..."
curl -sf http://$MACHINE_B_IP:$PROXY_PORT/v1/models 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  FAIL: Cannot list models"

# Test 7: RAG chat
echo ""
echo "[7/7] RAG chat test..."
curl -sf -X POST http://$MACHINE_B_IP:$PROXY_PORT/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-6b+RAG",
    "messages": [{"role": "user", "content": "test"}]
  }' 2>/dev/null | python3 -m json.tool 2>/dev/null | head -20 || echo "  FAIL: Chat not working"

echo ""
echo "=== Verification complete ==="
