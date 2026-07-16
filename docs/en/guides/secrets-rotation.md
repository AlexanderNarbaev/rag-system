# Secrets Rotation Guide

This guide covers the automated secrets rotation system for the RAG proxy — JWT signing keys, API keys, and database
credentials. It includes rotation schedules, emergency procedures, vault integration, and operational runbooks.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Rotation Schedule](#rotation-schedule)
4. [Automated Rotation](#automated-rotation)
5. [Manual Rotation](#manual-rotation)
6. [Emergency Rotation](#emergency-rotation)
7. [Health Monitoring](#health-monitoring)
8. [Vault / K8s Integration](#vault--k8s-integration)
9. [Rollback Procedures](#rollback-procedures)
10. [Troubleshooting](#troubleshooting)

---

## Overview

### Why Rotate Secrets?

| Threat                          | Mitigation                        |
|---------------------------------|-----------------------------------|
| Credential leakage              | Short-lived keys limit exposure   |
| Insider threats                 | Regular rotation limits window    |
| Compliance (SOC2, ISO 27001)    | Demonstrable rotation policy      |
| Key compromise detection        | Emergency rotation capability     |
| Stale credentials in backups    | Grace period for old keys         |

### Design Principles

- **Zero-downtime**: old keys remain valid during a grace period after rotation.
- **Backward compatibility**: in-flight tokens are verified against both old and new keys.
- **Audit trail**: every rotation is logged with timestamps, fingerprints, and initiator.
- **Air-gapped compatible**: no external API calls — all key generation is local.
- **Graceful degradation**: rotation failures don't crash the proxy.

---

## Architecture

### Components

| Component                       | File                                         | Purpose                              |
|---------------------------------|----------------------------------------------|--------------------------------------|
| **SecretRotationManager**       | `proxy/app/auth/secret_rotation.py`          | Core rotation logic, key generation  |
| **rotate-secrets.sh**           | `scripts/ops/rotate-secrets.sh`              | Shell-based rotation (cron, manual)  |
| **Health endpoint**             | `proxy/app/api/health.py`                    | Rotation status in `/v1/health`      |
| **Audit logger**                | `proxy/app/shared/audit.py`                  | Rotation event audit trail           |
| **Rotation state**              | `data/rotation/rotation_state.json`          | Persisted rotation metadata          |

### Rotation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Secrets Rotation Flow                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Backup current .env                                         │
│     └── proxy/.env.backups/.env.20260716_030000                 │
│                                                                 │
│  2. Generate new keys                                           │
│     ├── JWT: RSA-2048 / EC P-256 / HS256                       │
│     └── API: sk-{random} per user                              │
│                                                                 │
│  3. Update .env file                                            │
│     ├── JWT_SECRET=<new_private_key>                            │
│     ├── JWT_PUBLIC_KEY=<new_public_key>                         │
│     └── JWT_ALGORITHM=RS256                                     │
│                                                                 │
│  4. Signal service reload                                       │
│     ├── /tmp/rag-secrets-rotated (file signal)                  │
│     └── SIGHUP to Docker container                              │
│                                                                 │
│  5. Grace period begins                                         │
│     └── Old tokens remain valid for JWT_GRACE_PERIOD_SECONDS    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Rotation Schedule

### Recommended Intervals

| Secret Type           | Production         | Development        | After Incident     |
|-----------------------|--------------------|--------------------|--------------------|
| **JWT signing keys**  | 90 days            | 180 days           | Immediately        |
| **API keys**          | 180 days           | 365 days           | Immediately        |
| **Database passwords**| 90 days            | 365 days           | Immediately        |
| **Embedder API keys** | Per vendor policy  | Per vendor policy  | Immediately        |
| **LLM API keys**      | Per vendor policy  | Per vendor policy  | Immediately        |

### Cron Configuration

```bash
# Monthly JWT rotation (1st of month at 03:00 UTC)
0 3 1 * * FORCE=true SKIP_API_KEYS=true /scripts/ops/rotate-secrets.sh

# Quarterly full rotation (1st of Jan/Apr/Jul/Oct at 03:00 UTC)
0 3 1 1,4,7,10 * FORCE=true /scripts/ops/rotate-secrets.sh

# Weekly health check (Monday at 09:00 UTC)
0 9 * * 1 curl -sf http://localhost:8080/v1/health | jq '.components.secret_rotation'
```

### Scheduling in Kubernetes

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: secrets-rotation
spec:
  schedule: "0 3 1 * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: rotate
              image: rag-system:latest
              command: ["/scripts/ops/rotate-secrets.sh", "--force"]
              volumeMounts:
                - name: env-file
                  mountPath: /app/proxy/.env
                  subPath: .env
                - name: rotation-data
                  mountPath: /app/data/rotation
          volumes:
            - name: env-file
              secret:
                secretName: rag-proxy-env
            - name: rotation-data
              persistentVolumeClaim:
                claimName: rotation-data
          restartPolicy: OnFailure
```

---

## Automated Rotation

### Using the Shell Script

```bash
# Full interactive rotation
./scripts/ops/rotate-secrets.sh

# Dry-run (preview changes)
DRY_RUN=true ./scripts/ops/rotate-secrets.sh

# JWT-only rotation (automated)
FORCE=true SKIP_API_KEYS=true ./scripts/ops/rotate-secrets.sh

# EC key rotation
JWT_KEY_TYPE=ec ./scripts/ops/rotate-secrets.sh

# With custom .env path
ROTATE_ENV_FILE=/etc/rag/proxy.env ./scripts/ops/rotate-secrets.sh
```

### Using the Python API

```python
from proxy.app.auth.secret_rotation import get_rotation_manager

manager = get_rotation_manager()

# Rotate JWT keys (RSA-2048, 1-hour grace)
record = await manager.rotate_jwt_keys(
    algorithm="RS256",
    initiated_by="admin",
    grace_seconds=3600
)
print(f"Rotation {record.rotation_id}: {record.status}")

# Rotate API keys for specific users
record = await manager.rotate_api_keys(
    user_ids=["user-1", "user-2"],
    initiated_by="cron",
    overlap_seconds=86400
)

# Check rotation status
status = manager.get_rotation_status()
print(f"Last rotation: {status['last_rotation']}")
print(f"JWT key age: {status['jwt_key_age_seconds']}s")
```

### Key Types

| Algorithm | Key Type    | Size       | Use Case                     |
|-----------|-------------|------------|------------------------------|
| RS256     | RSA-2048    | 2048-bit   | Production (default)         |
| ES256     | EC P-256    | 256-bit    | High-performance production  |
| HS256     | Symmetric   | 512-bit    | Development, air-gapped      |

---

## Manual Rotation

### Step-by-Step Procedure

1. **Verify current health**
   ```bash
   curl -s http://localhost:8080/v1/health | jq '.components.secret_rotation'
   ```

2. **Create backup**
   ```bash
   cp proxy/.env proxy/.env.manual-backup-$(date +%Y%m%d)
   ```

3. **Run rotation**
   ```bash
   ./scripts/ops/rotate-secrets.sh --jwt-only
   ```

4. **Verify new health**
   ```bash
   curl -s http://localhost:8080/v1/health | jq '.components'
   ```

5. **Test authentication**
   ```bash
   # Generate a test token
   curl -X POST http://localhost:8080/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"username": "admin", "password": "your-password"}'

   # Verify the token works
   curl -H 'Authorization: Bearer <token>' http://localhost:8080/v1/models
   ```

6. **Monitor for 15 minutes**
   ```bash
   tail -f /var/log/rag-system/rotation_*.log
   ```

---

## Emergency Rotation

### When to Rotate Immediately

- JWT secret leaked or exposed in logs
- API keys found in public repositories
- Suspected unauthorized access
- Security audit finding
- Employee offboarding (compromised accounts)

### Emergency Procedure

```bash
# 1. Rotate immediately (skip confirmation, zero grace period)
FORCE=true ./scripts/ops/rotate-secrets.sh

# 2. Verify health
curl -s http://localhost:8080/v1/health | jq .

# 3. Check audit log for unauthorized access
tail -100 /var/log/rag-system/audit.jsonl | jq 'select(.event_type == "login")'

# 4. Force-logout all users (revoke all refresh tokens)
python3 -c "
import asyncio
from proxy.app.auth.user_db import get_user_db
db = get_user_db()
# This would need admin endpoint implementation
"
```

### Incident Response Checklist

- [ ] Rotate all affected secrets immediately
- [ ] Review audit logs for unauthorized access
- [ ] Revoke all active sessions for affected users
- [ ] Notify security team
- [ ] Document incident timeline
- [ ] Update rotation schedule if needed
- [ ] Verify no secrets remain in version control

---

## Health Monitoring

### Health Endpoint Response

```json
{
  "status": "ok",
  "timestamp": "2026-07-16T10:30:00Z",
  "components": {
    "qdrant": "ok",
    "llm": "ok",
    "kb_manager": "ok",
    "secret_rotation": "ok",
    "secret_rotation_info": {
      "last_rotation": "2026-07-01T03:00:00Z",
      "total_rotations": 12,
      "failed_rotations": 0,
      "active_rotations": 0,
      "jwt_key_age_seconds": 1296000,
      "last_error": null,
      "grace_period_seconds": 3600
    }
  }
}
```

### Status Values

| Status      | Meaning                              | Action Required         |
|-------------|--------------------------------------|-------------------------|
| `ok`        | Rotation healthy, key is fresh       | None                    |
| `degraded`  | Last rotation had errors             | Check `last_error`      |
| `stale_key` | JWT key older than 30 days           | Schedule rotation       |
| `rotating`  | Rotation currently in progress       | Wait for completion     |
| `error`     | Rotation module failure              | Check logs, restart     |

### Prometheus Metrics

```yaml
# Add to config/monitoring/prometheus.yml
- alert: StaleJWTKey
  expr: rag_secret_rotation_jwt_key_age_seconds > 2592000  # 30 days
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "JWT signing key is older than 30 days"

- alert: RotationFailed
  expr: rag_secret_rotation_failed_rotations > 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Secret rotation has failed"
```

---

## Vault / K8s Integration

### HashiCorp Vault Integration

```bash
# Store secrets in Vault
vault kv put secret/rag-proxy/jwt \
  secret="$(cat data/rotation/jwt_private_key.pem)" \
  public_key="$(cat data/rotation/jwt_public_key.pem)" \
  algorithm="RS256"

# Retrieve in application
export JWT_SECRET=$(vault kv get -field=secret secret/rag-proxy/jwt)
export JWT_PUBLIC_KEY=$(vault kv get -field=public_key secret/rag-proxy/jwt)
```

### Vault Agent Auto-Rotation

```hcl
# vault-agent-config.hcl
template {
  source      = "/etc/vault-agent/jwt-secret.tpl"
  destination = "/etc/rag-proxy/jwt-secret"
  perms       = "0600"
}

template {
  source      = "/etc/vault-agent/env.tpl"
  destination = "/etc/rag-proxy/.env"
  perms       = "0644"

  command = "docker kill -s HUP rag-proxy"
}
```

### Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rag-proxy-secrets
  namespace: rag-system
type: Opaque
data:
  JWT_SECRET: <base64-encoded>
  JWT_PUBLIC_KEY: <base64-encoded>
  API_KEY_EMBEDDER: <base64-encoded>
  API_KEY_RERANKER: <base64-encoded>
  API_KEY_LLM: <base64-encoded>
```

### External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rag-proxy-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: rag-proxy-secrets
    creationPolicy: Owner
  data:
    - secretKey: JWT_SECRET
      remoteRef:
        key: secret/rag-proxy/jwt
        property: secret
```

### Sealed Secrets (Bitnami)

```bash
# Create sealed secret for air-gapped environments
kubeseal --format yaml < rag-proxy-secrets.yaml > rag-proxy-sealed.yaml
```

---

## Rollback Procedures

### Automatic Rollback

The rotation script automatically creates backups before making changes:

```bash
# List available backups
ls -la proxy/.env.backups/

# Rollback to latest backup
./scripts/ops/rotate-secrets.sh --rollback

# Rollback to specific backup
cp proxy/.env.backups/.env.20260716_030000 proxy/.env
docker restart rag-proxy
```

### Manual Rollback

```bash
# 1. Stop the proxy
docker-compose -f proxy/docker-compose.yml stop proxy

# 2. Restore .env
cp proxy/.env.backups/.env.20260701_030000 proxy/.env

# 3. Restart
docker-compose -f proxy/docker-compose.yml start proxy

# 4. Verify
curl -s http://localhost:8080/v1/health | jq .
```

### Rollback Validation

```bash
# After rollback, verify:
# 1. Health endpoint returns 200
curl -sf http://localhost:8080/v1/health

# 2. Authentication still works
curl -X POST http://localhost:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "your-password"}'

# 3. No errors in logs
docker logs rag-proxy --tail 50 | grep -i error
```

---

## Troubleshooting

### Common Issues

#### Rotation Script Fails

```bash
# Check prerequisites
openssl version
python3 --version
jq --version

# Check permissions
ls -la proxy/.env
ls -la scripts/ops/rotate-secrets.sh

# Check disk space
df -h proxy/.env.backups/
```

#### Health Shows `stale_key`

```bash
# Check key age
curl -s http://localhost:8080/v1/health | jq '.components.secret_rotation_info.jwt_key_age_seconds'

# Rotate immediately
FORCE=true ./scripts/ops/rotate-secrets.sh --jwt-only
```

#### Health Shows `degraded`

```bash
# Check last error
curl -s http://localhost:8080/v1/health | jq '.components.secret_rotation_info.last_error'

# Check rotation logs
ls -la /var/log/rag-system/rotation_*.log
tail -50 /var/log/rag-system/rotation_*.log
```

#### Auth Failures After Rotation

```bash
# Check if .env was updated correctly
grep JWT_ALGORITHM proxy/.env

# Verify the proxy picked up new config
docker logs rag-proxy | grep -i "jwt\|secret\|rotation"

# Check grace period
curl -s http://localhost:8080/v1/health | jq '.components.secret_rotation_info.grace_period_seconds'
```

### Debug Mode

```bash
# Run rotation with verbose logging
DEBUG=true DRY_RUN=true ./scripts/ops/rotate-secrets.sh

# Check Python module directly
python3 -c "
from proxy.app.auth.secret_rotation import get_rotation_manager
import asyncio

async def check():
    manager = get_rotation_manager()
    print(manager.get_rotation_status())

asyncio.run(check())
"
```

---

## See Also

- [Security Guide](security-guide.md) — overall security model
- [Access Control / RBAC](access-control-rbac.md) — role-based access control
- [Deployment Guide](deployment-guide.md) — deployment and operations
- [Disaster Recovery Runbook](disaster-recovery-runbook.md) — DR procedures
- [Troubleshooting Guide](troubleshooting.md) — common issues and fixes
