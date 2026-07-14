# Kubernetes Deployment

Helm chart for deploying the RAG System to Kubernetes.

## Prerequisites

- Kubernetes 1.28+
- Helm 3.14+
- kubectl configured for your cluster

## Quick Start

```bash
# 1. Create namespace
kubectl create namespace rag-system

# 2. Install Helm chart
cd deploy/k8s/helm
helm upgrade --install rag-system ./rag-system \
  -n rag-system \
  -f values.yaml \
  --set proxy.env.llmEndpoint=http://your-llm-endpoint:8000/v1 \
  --set proxy.env.llmModelName=your-model-name \
  --set secrets.neo4jPassword=$(openssl rand -hex 16) \
  --set secrets.jwtSecret=$(openssl rand -hex 32) \
  --wait \
  --timeout 10m

# 3. Verify deployment
kubectl get pods,svc,hpa -n rag-system

# 4. Check health
kubectl exec -it deploy/rag-system-proxy -n rag-system -- curl -s localhost:8080/v1/health
```

## Configuration

All configuration is in `values.yaml`. Key settings:

| Parameter                 | Description              | Default |
|---------------------------|--------------------------|---------|
| `proxy.replicaCount`      | Number of proxy replicas | `2`     |
| `proxy.env.llmEndpoint`   | LLM backend URL          | `""`    |
| `proxy.env.llmModelName`  | LLM model name           | `""`    |
| `proxy.env.useRedis`      | Enable Redis cache       | `false` |
| `proxy.env.graphEnabled`  | Enable Neo4j graph       | `false` |
| `qdrant.persistence.size` | Qdrant storage size      | `50Gi`  |
| `neo4j.persistence.size`  | Neo4j storage size       | `20Gi`  |
| `redis.persistence.size`  | Redis storage size       | `10Gi`  |

## Production Overrides

Create a `values-prod.yaml`:

```yaml
proxy:
  replicaCount: 3
  resources:
    limits:
      cpu: "4"
      memory: 8Gi
    requests:
      cpu: "2"
      memory: 4Gi
  env:
    useRedis: "true"
    graphEnabled: "true"
    useLangGraph: "true"
    metricsEnabled: "true"
    logFormat: "json"
    rateLimitEnabled: "true"

qdrant:
  replicaCount: 3
  persistence:
    size: 100Gi

ingress:
  enabled: true
  className: "nginx"
  tls:
    enabled: true
    secretName: rag-system-tls
  hosts:
    - host: rag.example.com
      paths:
        - path: /v1/
          pathType: Prefix
          serviceName: proxy
          servicePort: 8080
```

Then install with:

```bash
helm upgrade --install rag-system ./rag-system \
  -n rag-system \
  -f values.yaml \
  -f values-prod.yaml
```

## Secrets Management

Never store secrets in `values.yaml`. Use one of:

### Option A: Kubernetes Secrets (simple)

```bash
kubectl create secret generic rag-secrets -n rag-system \
  --from-literal=jwt-secret=$(openssl rand -hex 32) \
  --from-literal=neo4j-password=$(openssl rand -hex 16) \
  --from-literal=llm-api-key=your-llm-api-key
```

### Option B: Helm --set flags

```bash
helm upgrade --install rag-system ./rag-system \
  --set secrets.jwtSecret=$(openssl rand -hex 32) \
  --set secrets.neo4jPassword=$(openssl rand -hex 16)
```

## Scaling

### Horizontal Pod Autoscaler

The proxy has HPA enabled by default (2-10 replicas, CPU target 70%).

```bash
# Check HPA status
kubectl get hpa -n rag-system

# Manually scale
kubectl scale deployment rag-system-proxy --replicas=5 -n rag-system
```

### Vertical Scaling

Adjust resource limits in `values.yaml`:

```yaml
proxy:
  resources:
    limits:
      cpu: "8"
      memory: 16Gi
```

## Upgrades

```bash
# Update image tag
helm upgrade --install rag-system ./rag-system \
  -n rag-system \
  --reuse-values \
  --set proxy.image.tag=v1.1.0

# Monitor rollout
kubectl rollout status deployment/rag-system-proxy -n rag-system

# Rollback if needed
kubectl rollout undo deployment/rag-system-proxy -n rag-system
```

## Uninstall

```bash
helm uninstall rag-system -n rag-system
kubectl delete namespace rag-system
```

## Directory Structure

```
deploy/k8s/helm/rag-system/
├── Chart.yaml                     # Chart metadata
├── values.yaml                    # Default configuration
├── .helmignore                    # Patterns to ignore
└── templates/
    ├── _helpers.tpl               # Name, label helpers
    ├── proxy-deployment.yaml      # RAG Proxy Deployment
    ├── proxy-service.yaml         # Proxy ClusterIP Service
    ├── proxy-hpa.yaml             # Horizontal Pod Autoscaler
    ├── proxy-configmap.yaml       # Non-sensitive config
    ├── proxy-secrets.yaml         # Kubernetes Secret
    ├── ingress.yaml               # Ingress with TLS
    ├── qdrant-statefulset.yaml    # Qdrant StatefulSet
    ├── qdrant-pvc.yaml            # Qdrant headless Service
    ├── neo4j-statefulset.yaml     # Neo4j StatefulSet + Service
    └── redis-deployment.yaml      # Redis Deployment + Service + PVC
```
