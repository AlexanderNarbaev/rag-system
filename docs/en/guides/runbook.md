# RAG System Operational Runbook

This runbook provides operational procedures for maintaining the RAG System in production.

## Table of Contents

- [Daily Operations](#daily-operations)
- [Weekly Maintenance](#weekly-maintenance)
- [Monthly Review](#monthly-review)
- [Incident Response](#incident-response)
- [Escalation Paths](#escalation-paths)
- [Common Issues](#common-issues)
- [Useful Commands](#useful-commands)

---

## Daily Operations

### Morning Checklist (09:00)

- [ ] **Check service health**
  ```bash
  curl -s http://localhost:8080/v1/health | jq .
  ```

- [ ] **Verify all containers are running**
  ```bash
  docker-compose -f proxy/docker-compose.yml ps
  ```

- [ ] **Check error logs for anomalies**
  ```bash
  docker-compose -f proxy/docker-compose.yml logs --since 24h | grep -i error
  ```

- [ ] **Monitor resource usage**
  ```bash
  docker stats --no-stream
  ```

- [ ] **Verify backup completion**
  ```bash
  make verify-backups
  ```

### During Business Hours

- **Monitor response times** via Prometheus metrics at `/metrics`
- **Check HITL dashboard** for expert feedback (http://localhost:8501)
- **Review rate limiting** metrics for unusual patterns

### End of Day (18:00)

- [ ] **Trigger nightly backup** (if not automated)
  ```bash
  make backup
  ```

- [ ] **Review daily metrics summary**

---

## Weekly Maintenance

### Monday Morning

- [ ] **Run ETL pipeline for data freshness**
  ```bash
  make etl
  ```

- [ ] **Verify Qdrant collection health**
  ```bash
  curl -s http://localhost:6333/collections | jq .
  ```

- [ ] **Check Neo4j graph consistency**
  ```bash
  docker exec neo4j cypher-shell "MATCH (n) RETURN count(n);"
  ```

- [ ] **Review and rotate logs**
  ```bash
  docker-compose -f proxy/docker-compose.yml logs --since 7d > logs/weekly-$(date +%Y%m%d).log
  ```

### Wednesday Afternoon

- [ ] **Run integration tests**
  ```bash
  make test-integration
  ```

- [ ] **Verify backup restoration** (on staging)
  ```bash
  ./scripts/ops/restore_all.sh
  ```

- [ ] **Check disk space usage**
  ```bash
  df -h | grep -E "(/$|/data)"
  ```

### Friday Before EOD

- [ ] **Update dependencies** (if needed)
  ```bash
  pip list --outdated
  ```

- [ ] **Review security alerts**
  ```bash
  pip audit
  ```

- [ ] **Document any incidents from the week**

---

## Monthly Review

### First Monday of Month

- [ ] **Performance baseline review**
    - Compare current metrics with previous month
    - Identify trends in latency, throughput, error rates

- [ ] **Capacity planning**
    - Review storage growth (Qdrant, Neo4j, Redis)
    - Estimate when scaling will be needed
    - Check model storage requirements

- [ ] **Security audit**
  ```bash
  # Check for vulnerable dependencies
  pip audit
  # Review access logs
  grep "401\|403" logs/proxy-*.log
  ```

- [ ] **Backup strategy review**
    - Verify backup retention policy (7 daily, 4 weekly, 3 monthly)
    - Test full restoration procedure
    - Update backup scripts if needed

- [ ] **Documentation updates**
    - Update runbook with new procedures
    - Review and update escalation contacts
    - Update architecture diagrams if changes were made

### Quarterly

- [ ] **Disaster recovery drill**
    - Simulate full system failure
    - Practice restoration from backups
    - Document recovery time actuals vs. targets

- [ ] **Model performance evaluation**
    - Run evaluation pipeline on held-out test set
    - Compare with previous quarter metrics
    - Decide if retraining is needed

---

## Incident Response

### Severity Levels

| Level             | Description            | Response Time | Example                                     |
|-------------------|------------------------|---------------|---------------------------------------------|
| **P1 - Critical** | System down, data loss | 15 minutes    | All services unresponsive, data corruption  |
| **P2 - High**     | Major feature broken   | 1 hour        | LLM not responding, search returning errors |
| **P3 - Medium**   | Degraded performance   | 4 hours       | High latency, intermittent failures         |
| **P4 - Low**      | Minor issue            | 24 hours      | UI glitch, non-critical log errors          |

### Incident Response Procedure

#### 1. Detect & Alert (0-5 minutes)

```bash
# Quick health check
curl -s http://localhost:8080/v1/health

# Check all services
docker-compose -f proxy/docker-compose.yml ps

# Check resource usage
docker stats --no-stream
```

#### 2. Assess & Communicate (5-15 minutes)

- Determine severity level
- Notify stakeholders via appropriate channel
- Create incident ticket

#### 3. Mitigate (15-60 minutes)

**If LLM backend is down:**

```bash
# Check LLM endpoint
curl -s http://localhost:8000/v1/models

# Restart LLM service
docker-compose -f proxy/docker-compose.yml restart llm
```

**If Qdrant is unresponsive:**

```bash
# Check Qdrant status
curl -s http://localhost:6333/healthz

# Restart Qdrant
docker-compose -f proxy/docker-compose.yml restart qdrant
```

**If Redis is down:**

```bash
# Check Redis
docker exec redis redis-cli ping

# Restart Redis
docker-compose -f proxy/docker-compose.yml restart redis
```

**If Neo4j is down:**

```bash
# Check Neo4j
docker exec neo4j cypher-shell "RETURN 1;"

# Restart Neo4j
docker-compose -f proxy/docker-compose.yml restart neo4j
```

#### 4. Resolve & Document (1-4 hours)

- Identify root cause
- Implement permanent fix
- Update monitoring/alerting if needed
- Document incident in post-mortem template

#### 5. Post-Incident Review (24-48 hours)

- Conduct blameless post-mortem
- Identify preventive measures
- Update runbook with lessons learned
- Share findings with team

### Common Incident Scenarios

#### Scenario: High Latency (>5s response time)

```bash
# 1. Check resource usage
docker stats --no-stream

# 2. Check Qdrant load
curl -s http://localhost:6333/metrics | grep qdrant_

# 3. Check LLM backend
time curl -s http://localhost:8000/v1/models

# 4. Restart services if needed
docker-compose -f proxy/docker-compose.yml restart
```

#### Scenario: Memory Leak (OOM kills)

```bash
# 1. Check container memory limits
docker inspect <container> | grep -A 5 "Memory"

# 2. Check for OOM kills
dmesg | grep -i "out of memory"

# 3. Restart affected service
docker-compose -f proxy/docker-compose.yml restart <service>

# 4. Monitor memory usage
watch -n 1 'docker stats --no-stream'
```

#### Scenario: Data Corruption

```bash
# 1. Stop write operations
docker-compose -f proxy/docker-compose.yml stop proxy

# 2. Assess damage
curl -s http://localhost:6333/collections | jq '.result.collections | length'

# 3. Restore from backup
./scripts/ops/restore_all.sh

# 4. Verify restoration
make verify-backups

# 5. Resume operations
docker-compose -f proxy/docker-compose.yml start proxy
```

---

## Escalation Paths

### Internal Escalation

| Level               | Contact                  | When to Escalate                        |
|---------------------|--------------------------|-----------------------------------------|
| **L1 - On-call**    | Current on-call engineer | Initial response, basic troubleshooting |
| **L2 - Senior**     | Senior backend engineer  | Complex issues, service failures        |
| **L3 - Lead**       | Tech lead / Architect    | Architecture decisions, data loss       |
| **L4 - Management** | Engineering manager      | Extended outages, customer impact       |

### External Escalation

| Service             | Contact            | When to Escalate                        |
|---------------------|--------------------|-----------------------------------------|
| **Cloud Provider**  | Support ticket     | Infrastructure issues, network problems |
| **LLM Provider**    | API support        | Model availability, rate limiting       |
| **Database Vendor** | Enterprise support | Data corruption, performance issues     |

### Communication Channels

- **Slack**: #rag-system-alerts (automated alerts)
- **Slack**: #rag-system-oncall (manual coordination)
- **Email**: rag-support@company.com
- **Phone**: On-call rotation (PagerDuty)

---

## Common Issues

### Issue: Proxy returns 502 Bad Gateway

**Symptoms**: Nginx/reverse proxy returns 502

**Diagnosis**:

```bash
# Check if proxy is running
docker-compose -f proxy/docker-compose.yml ps proxy

# Check proxy logs
docker-compose -f proxy/docker-compose.yml logs proxy --tail=50

# Check port binding
netstat -tlnp | grep 8080
```

**Resolution**:

```bash
# Restart proxy
docker-compose -f proxy/docker-compose.yml restart proxy

# If persistent, check .env configuration
cat proxy/.env | grep -E "^(HOST|PORT|WORKERS)"
```

### Issue: Embedding service timeout

**Symptoms**: Slow or failed embedding requests

**Diagnosis**:

```bash
# Check embedding service health
curl -s http://localhost:8080/v1/health | jq '.embedding_service'

# Check GPU utilization (if applicable)
nvidia-smi
```

**Resolution**:

```bash
# Restart embedding service
docker-compose -f proxy/docker-compose.yml restart embedder

# If GPU OOM, reduce batch size in config
# Edit proxy/.env: EMBEDDING_BATCH_SIZE=16
```

### Issue: Qdrant collection not found

**Symptoms**: Search returns empty results

**Diagnosis**:

```bash
# List collections
curl -s http://localhost:6333/collections | jq .

# Check collection details
curl -s http://localhost:6333/collections/{collection_name} | jq .
```

**Resolution**:

```bash
# Reinitialize collections
python scripts/init_collections.py

# Re-run ETL if data is missing
make etl
```

---

## Useful Commands

### Service Management

```bash
# Start all services
docker-compose -f proxy/docker-compose.yml up -d

# Stop all services
docker-compose -f proxy/docker-compose.yml down

# Restart specific service
docker-compose -f proxy/docker-compose.yml restart <service>

# View logs (follow)
docker-compose -f proxy/docker-compose.yml logs -f <service>

# View logs (last 100 lines)
docker-compose -f proxy/docker-compose.yml logs --tail=100 <service>
```

### Health Checks

```bash
# Full health check
curl -s http://localhost:8080/v1/health | jq .

# Liveness probe (K8s)
curl -s http://localhost:8080/v1/health/live

# Readiness probe (K8s)
curl -s http://localhost:8080/v1/health/ready
```

### Database Operations

```bash
# Qdrant - List collections
curl -s http://localhost:6333/collections | jq .

# Qdrant - Collection info
curl -s http://localhost:6333/collections/{name} | jq .

# Neo4j - Node count
docker exec neo4j cypher-shell "MATCH (n) RETURN count(n);"

# Redis - Check keys
docker exec redis redis-cli keys "*"
```

### Backup & Restore

```bash
# Run all backups
make backup

# Verify backups
make verify-backups

# Restore from backup
make restore
```

### Deployment

```bash
# Deploy dev environment
make deploy

# Deploy production
make deploy-prod

# Pull latest images
docker-compose -f proxy/docker-compose.yml pull
```

### Monitoring

```bash
# View Prometheus metrics
curl -s http://localhost:8080/metrics

# Container resource usage
docker stats --no-stream

# Disk usage
df -h

# Memory usage
free -h
```

---

## Maintenance Windows

### Scheduled Maintenance

- **Weekly**: Sunday 02:00-06:00 UTC (ETL updates, backups)
- **Monthly**: First Sunday 00:00-08:00 UTC (system updates, patches)
- **Quarterly**: Scheduled per team (major upgrades, DR drills)

### Unscheduled Maintenance

- Communicate via #rag-system-alerts
- Minimum 1 hour notice for non-emergency
- Document in maintenance log

---

## Contact Information

| Role                    | Name   | Contact       |
|-------------------------|--------|---------------|
| **Primary On-call**     | [Name] | [Phone/Slack] |
| **Secondary On-call**   | [Name] | [Phone/Slack] |
| **Tech Lead**           | [Name] | [Phone/Slack] |
| **Engineering Manager** | [Name] | [Phone/Slack] |
| **DevOps/SRE**          | [Name] | [Phone/Slack] |

---

## Appendix

### Log Locations

- **Proxy logs**: `docker-compose logs proxy`
- **ETL logs**: `logs/etl-*.log`
- **System logs**: `/var/log/syslog`
- **Application logs**: `logs/proxy-*.log`

### Configuration Files

- **Main config**: `proxy/.env`
- **Docker compose**: `proxy/docker-compose.yml`
- **ETL config**: `etl/config/etl_config.yaml`
- **Nginx config**: `deploy/nginx/nginx.conf`

### Monitoring URLs

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000
- **HITL Dashboard**: http://localhost:8501
- **API Health**: http://localhost:8080/v1/health

### Key Metrics to Watch

| Metric              | Warning Threshold | Critical Threshold |
|---------------------|-------------------|--------------------|
| Response time (p95) | >2s               | >5s                |
| Error rate          | >1%               | >5%                |
| CPU usage           | >70%              | >90%               |
| Memory usage        | >80%              | >95%               |
| Disk usage          | >75%              | >90%               |
| Qdrant load         | >70%              | >90%               |

---

**Last Updated**: 2026-07-10

**Version**: 1.0.0

**Maintainer**: RAG System Team
