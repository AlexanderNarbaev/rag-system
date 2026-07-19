#!/bin/bash
set -e

echo "=== Starting minikube test environment ==="

# Check minikube is running
if ! minikube status | grep -q "Running"; then
    echo "ERROR: minikube is not running. Run: minikube start"
    exit 1
fi

# Start port-forward in background
echo "Starting port-forward..."
kubectl port-forward svc/rag-system-proxy 9080:8080 -n rag-system &
PORTFWD_PID=$!
sleep 3

# Start mock LLM in background
echo "Starting mock LLM..."
python3 scripts/mock_llm_server.py &
MOCK_PID=$!
sleep 2

# Run tests
echo "Running integration tests..."
RAG_PROXY_URL=http://localhost:9080 MOCK_LLM_URL=http://localhost:8010 \
    python -m pytest tests/integration/test_minikube_e2e.py -v --tb=short

TEST_EXIT=$?

# Cleanup
kill $PORTFWD_PID $MOCK_PID 2>/dev/null
exit $TEST_EXIT
