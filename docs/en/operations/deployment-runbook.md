# RAG System Deployment Runbook

## Prerequisites

- Docker Compose or Kubernetes 1.24+
- Helm 3.x
- Minikube (for local dev) or K8s cluster
- 8 GB RAM, 4 CPU, 50 GB disk

## Local Development (Minikube)

```bash
# Start minikube
minikube start --cpus=4 --memory=8192

# Build and load image
docker build -t rag-proxy:latest -f proxy/Dockerfile .
minikube image load rag-proxy:latest

# Deploy
helm install rag-system deploy/k8s/helm/rag-system/ \
  -n rag-system --create-namespace \
  -f deploy/k8s/helm/rag-system/values-minikube.yaml

# Verify
kubectl get pods -n rag-system
kubectl port-forward svc/rag-system-proxy 9080:8080 -n rag-system &
curl http://localhost:9080/v1/health/live
```

## Production (Kubernetes)

```bash
# Install
helm install rag-system deploy/k8s/helm/rag-system/ \
  --namespace rag-system \
  --create-namespace \
  --values values-production.yaml

# Verify
kubectl get all -n rag-system
curl https://rag.example.com/v1/health/ready
```

## Post-Deployment

### Monitoring

- Import `config/monitoring/grafana-rag-dashboard.json` to Grafana
- Import `config/monitoring/alerts.yml` alert rules
- Configure AlertManager

### Backups

```bash
# Verify backup schedule
kubectl get cronjobs -n rag-system

# Manual backup
bash scripts/ops/backup_cron.sh

# Verify
bash scripts/verify_backup.sh
```

## Troubleshooting

### Component Down

1. `kubectl get pods -n rag-system`
2. `kubectl logs -n rag-system <pod>`
3. Check service endpoints

### Slow Responses

1. Check Grafana latency panel
2. Run `python scripts/benchmark.py`
3. Consider scaling replicas

### Memory Issues

1. Check Qdrant memory: `curl http://qdrant:6333/metrics`
2. Enable INT8 quantization (FR-168)
3. Reduce HNSW parameters (FR-171)
