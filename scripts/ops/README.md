# Operational Scripts

Backup and restore scripts for RAG System infrastructure components.

## Scripts

| Script              | Purpose                                                        |
|---------------------|----------------------------------------------------------------|
| `backup_qdrant.sh`  | Create Qdrant snapshot and upload to S3/MinIO                  |
| `backup_neo4j.sh`   | Create Neo4j database dump and upload to S3/MinIO              |
| `backup_redis.sh`   | Trigger Redis BGSAVE and upload RDB to S3/MinIO                |
| `backup_cron.sh`    | Cron wrapper that runs all backup scripts in sequence          |
| `restore_all.sh`    | Download latest backups from S3/MinIO and restore all services |
| `verify_restore.sh` | Verify backup file integrity (archive, size, presence)         |
| `health_check.sh`   | Comprehensive health check for all infrastructure components   |
| `status.sh`         | Show real-time status of all services (table/json/watch modes) |
| `rotate-secrets.sh` | Automated JWT key and API key rotation with rollback support   |

## Prerequisites

All scripts require:

```bash
# Required environment variables
export BACKUP_BUCKET=rag-backups          # S3/MinIO bucket name
export S3_ENDPOINT=https://s3.amazonaws.com  # S3/MinIO endpoint
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key

# Optional
export RETENTION_DAYS=7                   # Backup retention (default: 7)
export LOG_DIR=/var/log/rag-system        # Log directory
```

## Quick Start

### Run All Backups

```bash
# Using Makefile (recommended)
make backup

# Or directly
./scripts/ops/backup_cron.sh
```

### Run Individual Backups

```bash
# Qdrant only
./scripts/ops/backup_qdrant.sh

# Neo4j only
./scripts/ops/backup_neo4j.sh

# Redis only
./scripts/ops/backup_redis.sh
```

### Restore All Services

```bash
# Using Makefile (recommended)
make restore

# Or directly
./scripts/ops/restore_all.sh

# Dry run (list available backups without restoring)
DRY_RUN=true ./scripts/ops/restore_all.sh

# Restore from specific date
RESTORE_DATE=2026-07-01 ./scripts/ops/restore_all.sh

# Skip specific services
SKIP_QDRANT=true ./scripts/ops/restore_all.sh
```

## Cron Schedule

Add to crontab for automated backups:

```bash
# Edit crontab
crontab -e

# Add entry (every hour, RPO < 1h)
0 * * * * /opt/rag-system/scripts/ops/backup_cron.sh >> /var/log/rag-system/backup_cron.log 2>&1
```

## Service-Specific Configuration

### Qdrant

```bash
export QDRANT_HOST=localhost      # Qdrant HTTP API endpoint
export QDRANT_PORT=6333           # Qdrant HTTP API port
export COLLECTION_NAME=knowledge_base  # Collection to backup
```

### Neo4j

```bash
export NEO4J_URI=bolt://localhost:7687  # Neo4j bolt URI
export NEO4J_USER=neo4j                 # Neo4j username
export NEO4J_PASSWORD=your-password     # Neo4j password
export NEO4J_DATA_DIR=/data             # Neo4j data directory (optional)
```

### Redis

```bash
export REDIS_URL=redis://localhost:6379  # Redis connection URL
export REDIS_PASSWORD=your-password      # Redis password (if required)
export REDIS_DATA_DIR=/data              # Redis data directory
```

## Backup Retention

All scripts implement automatic cleanup:

- **S3/MinIO**: Deletes backups older than `RETENTION_DAYS` (default: 7 days)
- **Qdrant**: Cleans up local snapshots older than `RETENTION_DAYS`

## Logs

Logs are written to `${LOG_DIR}/` (default: `/var/log/rag-system/`):

- `backup_qdrant_YYYY-MM-DD.log`
- `backup_neo4j_YYYY-MM-DD.log`
- `backup_redis_YYYY-MM-DD.log`
- `backup_cron_YYYY-MM-DD.log`
- `restore_YYYY-MM-DD_HHMMSS.log`

## Health Check

```bash
# Run comprehensive health check
./scripts/ops/health_check.sh

# JSON output for automation
./scripts/ops/health_check.sh --json

# Silent mode (only exit code)
./scripts/ops/health_check.sh --quiet || echo "Health check failed"
```

Exit codes: `0` = all healthy, `1` = warnings (degraded), `2` = critical failures.

## Service Status

```bash
# Show status table
./scripts/ops/status.sh

# Watch mode (refresh every 5s)
./scripts/ops/status.sh --watch

# JSON output
./scripts/ops/status.sh --json

# Environment-specific modes
./scripts/ops/status.sh --docker
./scripts/ops/status.sh --k8s
```

## Secrets Rotation

```bash
# Interactive rotation
./scripts/ops/rotate-secrets.sh

# Dry-run (preview without changes)
./scripts/ops/rotate-secrets.sh --dry-run

# Automated JWT-only rotation
./scripts/ops/rotate-secrets.sh --jwt-only --force

# Rollback to previous .env
./scripts/ops/rotate-secrets.sh --rollback
```

## Error Handling

- All scripts use `set -euo pipefail` for strict error handling
- `backup_cron.sh` uses a lock file to prevent concurrent runs
- Individual backup failures are logged but don't stop other backups
- Summary report is generated at the end of each `backup_cron.sh` run
