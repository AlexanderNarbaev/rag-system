# Ранбук развёртывания RAG-системы

## Предварительные требования

- Docker Compose или Kubernetes 1.24+
- Helm 3.x
- Minikube (для локальной разработки) или кластер K8s
- 8 ГБ RAM, 4 CPU, 50 ГБ дискового пространства

## Локальная разработка (Minikube)

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

## Продакшн (Kubernetes)

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

## После развёртывания

### Мониторинг

- Импортируйте `config/monitoring/grafana-rag-dashboard.json` в Grafana
- Импортируйте правила алертов `config/monitoring/alerts.yml`
- Настройте AlertManager

### Резервные копии

```bash
# Verify backup schedule
kubectl get cronjobs -n rag-system

# Manual backup
bash scripts/ops/backup_cron.sh

# Verify
bash scripts/verify_backup.sh
```

## Устранение неполадок

### Компонент недоступен

1. `kubectl get pods -n rag-system`
2. `kubectl logs -n rag-system <pod>`
3. Проверьте эндпоинты сервисов

### Медленные ответы

1. Проверьте панель латентности в Grafana
2. Запустите `python scripts/benchmark.py`
3. Рассмотрите масштабирование реплик

### Проблемы с памятью

1. Проверьте память Qdrant: `curl http://qdrant:6333/metrics`
2. Включите квантизацию INT8 (FR-168)
3. Уменьшите параметры HNSW (FR-171)
