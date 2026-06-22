# Disaster Recovery Runbook

**Version:** v1.0.0
**Last Updated:** 2026-06-26
**RTO:** < 30 min | **RPO:** < 1 hour

---

## Overview

This runbook covers step-by-step recovery procedures for all failure scenarios in the RAG System production deployment. Each scenario includes detection methods, impact assessment, recovery steps, and verification criteria.

### Prerequisites

- Access to the S3/MinIO backup bucket (credentials in `BACKUP_S3_*` env vars)
- SSH access to all nodes (or `kubectl` access to the K8s cluster)
- `scripts/backup.sh` and `scripts/restore_all.sh` available on the admin machine
- Monitoring dashboard access (Grafana) for verification

### Backup Schedule Reference

| Component | Frequency | Retention | Location |
|-----------|-----------|-----------|----------|
| Qdrant snapshots | Every 6 hours | 7 daily, 4 weekly, 3 monthly | `s3://backup-rag/qdrant/` |
| Neo4j dumps | Every 6 hours | 7 daily, 4 weekly, 3 monthly | `s3://backup-rag/neo4j/` |
| Redis RDB | Every 1 hour | 24 hourly, 7 daily | `s3://backup-rag/redis/` |
| ETL WAL state | Every 30 min | 7 daily | `s3://backup-rag/etl/` |

---

## Recovery Scenarios

### 1. Qdrant Data Loss

**Detection:**
- Qdrant collections report 0 vectors (`curl localhost:6333/collections/<name>`)
- Proxy health check shows `qdrant: "degraded"` or `"unhealthy"`
- All retrieval fails, proxy returns empty contexts
- Prometheus alert: `QdrantUnhealthy` (critical)

**Impact:** All retrieval fails. Proxy returns empty contexts with `rag_confidence: 0`. Users receive "I don't have enough information" responses.

**Recovery Steps:**

```bash
# 1. Stop ETL pipeline to prevent writing incomplete data
systemctl stop rag-etl
# K8s: kubectl scale deployment rag-etl --replicas=0

# 2. Restore from latest Qdrant snapshot
bash scripts/restore_all.sh qdrant --latest
# This downloads the latest snapshot from S3 and restores to Qdrant

# 3. Verify restoration
curl -s localhost:6333/collections | jq '.result.collections[].vectors_count'

# 4. Identify last backup timestamp
BACKUP_TS=$(aws s3 ls s3://backup-rag/qdrant/ --recursive | sort | tail -1 | awk '{print $1" "$2}')
echo "Last backup: $BACKUP_TS"

# 5. Re-run ETL for delta since last backup
python scheduler/run_etl.py --since "$BACKUP_TS" --config config/etl_config.yaml

# 6. Verify retrieval works
curl -X POST localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"rag","messages":[{"role":"user","content":"test query"}]}' | jq '.rag_confidence'

# 7. Restart ETL in normal mode
systemctl start rag-etl
```

**RTO:** < 30 min | **RPO:** < 1 hour

---

### 2. Neo4j Data Loss

**Detection:**
- Neo4j returns 0 nodes (`MATCH (n) RETURN count(n)` → 0)
- Proxy health check shows `neo4j: "degraded"` or `"unhealthy"`
- Graph expansion produces empty results
- Prometheus alert: `Neo4jUnhealthy` (warning — proxy degrades gracefully)

**Impact:** Graph expansion skipped. Agentic queries lose entity context (~500 tokens). Non-agentic queries unaffected. Proxy automatically skips graph enrichment per graceful degradation design.

**Recovery Steps:**

```bash
# 1. Stop ETL pipeline
systemctl stop rag-etl

# 2. Restore from latest Neo4j dump
bash scripts/restore_all.sh neo4j --latest

# 3. Verify restoration
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "MATCH (n) RETURN count(n) AS node_count;"

# 4. Re-run ETL for delta since last backup
python scheduler/run_etl.py --since "$BACKUP_TS" --config config/etl_config.yaml

# 5. Restart ETL
systemctl start rag-etl
```

**RTO:** < 30 min | **RPO:** < 1 hour

---

### 3. Redis Data Loss

**Detection:**
- `redis-cli DBSIZE` → 0
- Proxy health check shows `redis: "degraded"`
- Cache hit ratio drops to 0 (`rag_cache_hit_ratio{cache_type="response"} == 0`)
- Prometheus alert: `RedisDown` (warning)

**Impact:** Cache miss only. No data loss — all data is recomputable. Latency increases temporarily (embedding re-computation, re-retrieval from Qdrant). No user-facing errors. Proxy automatically falls back to in-memory cache.

**Recovery:**
- **No recovery needed.** Redis is a cache-only component. The proxy automatically falls back to in-memory LRU cache.
- Cache will self-repopulate from normal traffic.
- To speed up recovery: run warm-up endpoint `curl -X POST localhost:8080/v1/admin/warmup`

```bash
# Verify cache is recovering
curl -s localhost:8080/metrics | grep rag_cache_hit_ratio
```

**RTO:** 0 min (auto-recovery) | **RPO:** N/A (cache only)

---

### 4. Node Failure (Compute)

**Detection:**
- Node unreachable via SSH/kubectl
- Kubernetes: Pod status `Pending` or `CrashLoopBackOff`
- Prometheus alert: `NodeDown` (critical)
- Grafana: node CPU/memory metrics flatline

**Impact (K8s):** Minimal. Pods automatically rescheduled to healthy nodes by Kubernetes scheduler. Brief interruption during reschedule (< 30s).

**Impact (Docker Compose):** Full outage of services on the failed node. Manual restart required.

**Recovery (Kubernetes):**

```bash
# 1. Verify pods rescheduled
kubectl get pods -n rag-system -o wide

# 2. Check for any stuck pods
kubectl get pods -n rag-system --field-selector=status.phase=Pending

# 3. If pods stuck in Terminating (node lost without draining):
kubectl delete pod <pod-name> -n rag-system --force --grace-period=0

# 4. Verify all services healthy
kubectl exec -it deploy/rag-proxy -n rag-system -- curl -s localhost:8080/v1/health

# 5. Check HPA status for auto-scaling
kubectl get hpa -n rag-system
```

**Recovery (Docker Compose):**

```bash
# 1. SSH to replacement node
# 2. Start services
cd rag-system/proxy && docker-compose up -d

# 3. Verify health
curl localhost:8080/v1/health
```

**RTO:** < 1 min (K8s) / < 5 min (Docker Compose)

---

### 5. Network Partition

**Detection:**
- Proxy cannot reach Qdrant/Neo4j/Redis (connection refused or timeout)
- Health check shows components as `"unhealthy"`
- Prometheus alert: `QdrantUnhealthy` (critical), `Neo4jUnhealthy` (warning)
- Logs show `ConnectionError` or `TimeoutError` for internal services

**Impact:** Graceful degradation kicks in:
- Qdrant unreachable → 503 on `/v1/chat/completions`
- Neo4j unreachable → skip graph expansion
- Redis unreachable → fall back to in-memory cache

**Recovery Steps:**

```bash
# 1. Verify network connectivity between components
ping <qdrant-host>
nc -zv <qdrant-host> 6333
nc -zv <neo4j-host> 7687
nc -zv <redis-host> 6379

# 2. Check for firewall rules blocking internal traffic
iptables -L -n | grep -E "6333|7687|6379"
# K8s: kubectl describe networkpolicy -n rag-system

# 3. Check DNS resolution
nslookup qdrant.<namespace>.svc.cluster.local
# K8s: kubectl run -it --rm debug --image=busybox -- nslookup qdrant

# 4. Restart affected components if needed
# K8s: kubectl rollout restart deployment/<component> -n rag-system
# Docker: docker-compose restart <service>

# 5. Verify recovery
curl localhost:8080/v1/health | jq '.components'
```

**RTO:** < 10 min | **RPO:** N/A

---

### 6. Complete Outage (All Services Down)

**Detection:**
- All services unreachable
- `/v1/health` returns 503 or connection refused
- All Prometheus alerts firing simultaneously
- Grafana shows 0 requests, 0 metrics

**Impact:** Complete service unavailability. All API endpoints return errors.

**Recovery Steps (Full Restore from S3):**

```bash
# === PHASE 1: Restore Data (15-20 min) ===

# 1. Restore Qdrant from latest snapshot
bash scripts/restore_all.sh qdrant --latest

# 2. Restore Neo4j from latest dump
bash scripts/restore_all.sh neo4j --latest

# 3. Verify data integrity
curl -s localhost:6333/collections | jq '.result.collections[].vectors_count'
cypher-shell -u neo4j -p "$NEO4J_PASSWORD" "MATCH (n) RETURN count(n);"

# === PHASE 2: Start Services (5 min) ===

# 4. Start infrastructure services first
docker-compose up -d qdrant neo4j redis
# K8s: kubectl apply -f infra/

# 5. Wait for services to be healthy
until curl -s localhost:6333/health | grep -q ok; do sleep 2; done
until curl -s localhost:7474 | grep -q neo4j; do sleep 2; done
until redis-cli ping | grep -q PONG; do sleep 2; done

# 6. Start proxy
docker-compose up -d proxy
# K8s: kubectl apply -f proxy/

# === PHASE 3: Verify (5 min) ===

# 7. Verify all components
curl localhost:8080/v1/health | jq '.'
# Expected: {"status":"ok","qdrant":"healthy","neo4j":"healthy","redis":"healthy","llm":"healthy"}

# 8. Test retrieval
curl -X POST localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "rag",
    "messages": [{"role": "user", "content": "What is the deployment process?"}]
  }' | jq '{confidence: .rag_confidence, sources: .rag_sources | length}'

# 9. Start ETL (runs delta since last backup)
systemctl start rag-etl

# 10. Verify backup schedule is active
systemctl status rag-backup.timer
kubectl get cronjob -n rag-system | grep backup
```

**RTO:** < 30 min | **RPO:** < 1 hour

---

### 7. LLM Backend Failure

**Detection:**
- LLM inference server unreachable (connection refused / timeout)
- Proxy health check shows `llm: "unhealthy"`
- `/v1/chat/completions` returns 503
- Prometheus alert: `LLMDown` (critical)

**Impact:** No generation possible. All chat completion requests return 503. Health and metrics endpoints remain available. `/v1/models` still works if cached.

**Recovery Steps:**

```bash
# 1. Check LLM backend status
curl $LLM_ENDPOINT/health  # vLLM
curl $LLM_ENDPOINT/health  # llama.cpp
# OpenAI-compatible: curl $LLM_ENDPOINT/models

# 2. Restart LLM backend
# vLLM:
systemctl restart vllm
# K8s: kubectl rollout restart deployment/vllm -n rag-system

# llama.cpp:
systemctl restart llama-cpp
# Docker: docker restart llama-cpp

# 3. Wait for model to load (may take 1-5 min)
until curl -s $LLM_ENDPOINT/models | grep -q "$LLM_MODEL_NAME"; do
  echo "Waiting for LLM to load..."
  sleep 10
done

# 4. Run model warm-up
curl -X POST localhost:8080/v1/admin/warmup -d '{"warmup_llm": true}'

# 5. Verify
curl localhost:8080/v1/health | jq '.llm'
```

**RTO:** < 5 min (if model cached in memory) / < 10 min (cold start)

---

### 8. Disk Full

**Detection:**
- Prometheus alert: `DiskNearFull` (warning at 85%, critical at 95%)
- Grafana dashboard shows disk usage trending up
- Qdrant write errors: "No space left on device"
- Proxy logs show `OSError: [Errno 28] No space left on device`

**Impact:** Services stop writing. Qdrant upserts fail. ETL stalls. Read operations may continue if enough space for temporary files.

**Recovery Steps:**

```bash
# 1. Identify disk usage
df -h
du -sh /data/* | sort -rh | head -10

# 2. Clean up old data
# Prune old Qdrant snapshots (>7 days)
find /data/qdrant/snapshots -name "*.snapshot" -mtime +7 -delete

# Prune old Neo4j backups
find /data/neo4j/backups -name "*.dump" -mtime +7 -delete

# Prune old Redis RDB backups
find /data/redis/backups -name "*.rdb" -mtime +3 -delete

# Clean up Docker artifacts (if using Docker)
docker system prune -af --volumes

# 3. Run cold storage cleanup
python scripts/cleanup_cold_storage.py --keep-versions 3

# 4. Rotate logs
logrotate -f /etc/logrotate.d/rag-system

# 5. Verify free space recovered
df -h /data/

# 6. Restart affected services if needed
systemctl restart rag-etl
```

**RTO:** < 15 min

---

## Verification Checklist

After any recovery procedure, run this verification checklist:

- [ ] Qdrant collection has expected vector count: `curl localhost:6333/collections | jq '.result.collections[].vectors_count'`
- [ ] Neo4j has expected node count: `cypher-shell "MATCH (n) RETURN count(n)"`
- [ ] Redis is accepting connections: `redis-cli PING` → `PONG`
- [ ] Proxy health check returns 200: `curl -s -o /dev/null -w "%{http_code}" localhost:8080/v1/health`
- [ ] All components healthy: `curl localhost:8080/v1/health | jq '.components | to_entries | map(select(.value != "healthy"))'` → `[]`
- [ ] Test query returns confidence > 0.5: `curl -X POST localhost:8080/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"rag","messages":[{"role":"user","content":"What is the RAG system?"}]}' | jq '.rag_confidence'`
- [ ] Prometheus metrics accessible: `curl -s localhost:8080/metrics | grep rag_cache_hit_ratio`
- [ ] Grafana dashboard shows healthy metrics (no gaps, values in normal range)
- [ ] Backup schedule active: `systemctl status rag-backup.timer` or `kubectl get cronjob rag-backup`
- [ ] ETL pipeline running: `systemctl status rag-etl` or `kubectl get pods -l app=rag-etl`

---

## Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Primary on-call | See PagerDuty schedule | After 15 min: secondary |
| DevOps lead | See team roster | After 30 min: engineering manager |
| Infrastructure | See team roster | After 45 min: CTO |

---

## DR Drill Schedule

| Frequency | Scope | Duration Target |
|-----------|-------|-----------------|
| Monthly | Single component failure (Qdrant or Neo4j restore) | < 1 hour |
| Quarterly | Full stack restore from S3 backups | < 2 hours |
| Annually | Complete datacenter failure simulation | < 4 hours |
