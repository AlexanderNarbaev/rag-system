#!/usr/bin/env bash
#
# scripts/backup_redis.sh
# Trigger Redis BGSAVE and upload RDB file to S3/MinIO with retention policy.
#
# Required environment variables:
#   REDIS_URL      — Redis connection URL (e.g., redis://localhost:6379)
#   BACKUP_BUCKET  — S3/MinIO bucket name
#   S3_ENDPOINT    — S3/MinIO endpoint URL
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
# Optional environment variables:
#   REDIS_DATA_DIR    — Redis data directory for locating RDB (default: /data)
#   REDIS_PASSWORD    — Redis password (if auth is required)
#   RETENTION_DAYS    — Backup retention in days (default: 7)
#
# Usage:
#   ./backup_redis.sh

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
BACKUP_DATE="$(date -u +%Y-%m-%d)"
BACKUP_NAME="redis-rdb-${BACKUP_DATE}-$(date -u +%H%M%S)"

LOG_FILE="${LOG_DIR:-/var/log/rag-system}/backup_redis_${BACKUP_DATE}.log"
: "${BACKUP_BUCKET:?BACKUP_BUCKET must be set}"
: "${S3_ENDPOINT:?S3_ENDPOINT must be set}"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG_FILE"
}

check_prereqs() {
    for cmd in redis-cli python3; do
        if ! command -v "$cmd" &>/dev/null; then
            log "ERROR: Required command '$cmd' not found in PATH"
            exit 1
        fi
    done
}

verify_s3() {
    if ! python3 -c "import boto3; boto3.client('s3', endpoint_url='${S3_ENDPOINT}').head_bucket(Bucket='${BACKUP_BUCKET}')" 2>/dev/null; then
        log "WARNING: Could not verify bucket '${BACKUP_BUCKET}' — will attempt upload anyway"
    fi
}

# ── Build redis-cli connection arguments ───────────────────────────────────
build_redis_args() {
    local args=()

    if [[ "$REDIS_URL" =~ ^redis://([^@]+@)?([^:/]+)(:([0-9]+))?(/([0-9]+))?$ ]]; then
        local userinfo="${BASH_REMATCH[1]}"
        local host="${BASH_REMATCH[2]}"
        local port="${BASH_REMATCH[4]:-6379}"

        args+=("-h" "$host" "-p" "$port")

        if [ -n "$userinfo" ]; then
            local password="${userinfo%@}"
            password="${password//:/}"
            args+=("-a" "$password" "--no-auth-warning")
        fi
    elif [ -n "${REDIS_PASSWORD:-}" ]; then
        args+=("-a" "${REDIS_PASSWORD}" "--no-auth-warning")
    fi

    echo "${args[@]}"
}

# ── Trigger BGSAVE ─────────────────────────────────────────────────────────
trigger_bgsave() {
    log "Triggering Redis BGSAVE..."

    local redis_args
    redis_args=$(build_redis_args)

    local response
    response=$(redis-cli $redis_args BGSAVE 2>&1)

    log "BGSAVE response: ${response}"

    if [[ "$response" != *"Background saving started"* ]] && [[ "$response" != *"OK"* ]]; then
        log "ERROR: BGSAVE failed: ${response}"
        exit 1
    fi

    # Wait for BGSAVE to complete
    log "Waiting for BGSAVE to finish..."
    local max_wait=300
    local waited=0
    while [ $waited -lt $max_wait ]; do
        local info
        info=$(redis-cli $redis_args INFO persistence 2>&1)
        local bgsave_status
        bgsave_status=$(echo "$info" | grep "rdb_bgsave_in_progress" | cut -d: -f2 | tr -d '\r')
        if [ "$bgsave_status" == "0" ]; then
            log "BGSAVE completed successfully"
            break
        fi
        sleep 3
        waited=$((waited + 3))
    done

    if [ $waited -ge $max_wait ]; then
        log "ERROR: Timed out waiting for BGSAVE to complete (${max_wait}s)"
        exit 1
    fi
}

# ── Locate and copy RDB file ───────────────────────────────────────────────
copy_rdb() {
    local redis_args
    redis_args=$(build_redis_args)

    # Get the RDB file path from Redis CONFIG GET
    local dir
    dir=$(redis-cli $redis_args CONFIG GET dir 2>/dev/null | tail -1 | tr -d '\r')
    local dbfilename
    dbfilename=$(redis-cli $redis_args CONFIG GET dbfilename 2>/dev/null | tail -1 | tr -d '\r')

    local rdb_path="${dir}/${dbfilename}"

    if [ ! -f "$rdb_path" ]; then
        # Try default locations
        for candidate in /data/dump.rdb /var/lib/redis/dump.rdb /tmp/dump.rdb; do
            if [ -f "$candidate" ]; then
                rdb_path="$candidate"
                break
            fi
        done
    fi

    if [ ! -f "$rdb_path" ]; then
        log "ERROR: Cannot locate RDB file. dir=${dir:-unknown}, dbfilename=${dbfilename:-unknown}"
        exit 1
    fi

    local local_path="/tmp/${BACKUP_NAME}.rdb"
    cp "$rdb_path" "$local_path"

    log "RDB copied: ${local_path} ($(du -h "$local_path" | cut -f1))"

    echo "$local_path"
}

# ── Upload to S3/MinIO ─────────────────────────────────────────────────────
upload_to_s3() {
    local local_path="$1"
    local s3_key="redis/${BACKUP_DATE}/${BACKUP_NAME}.rdb"

    log "Uploading to s3://${BACKUP_BUCKET}/${s3_key}..."

    python3 -c "
import boto3, sys
try:
    s3 = boto3.client('s3', endpoint_url='${S3_ENDPOINT}')
    s3.upload_file('${local_path}', '${BACKUP_BUCKET}', '${s3_key}')
    print('Upload completed successfully')
except Exception as e:
    print(f'Upload failed: {e}', file=sys.stderr)
    sys.exit(1)
"

    log "Uploaded to s3://${BACKUP_BUCKET}/${s3_key}"

    rm -f "${local_path}"
}

# ── Cleanup old backups ────────────────────────────────────────────────────
cleanup_old_backups() {
    log "Cleaning up backups older than ${RETENTION_DAYS} days..."

    python3 -c "
import boto3
from datetime import datetime, timedelta, timezone

s3 = boto3.client('s3', endpoint_url='${S3_ENDPOINT}')
cutoff = datetime.now(timezone.utc) - timedelta(days=${RETENTION_DAYS})

paginator = s3.get_paginator('list_objects_v2')
pages = paginator.paginate(Bucket='${BACKUP_BUCKET}', Prefix='redis/')

deleted = 0
for page in pages:
    if 'Contents' not in page:
        continue
    for obj in page['Contents']:
        if obj['LastModified'] < cutoff:
            s3.delete_object(Bucket='${BACKUP_BUCKET}', Key=obj['Key'])
            deleted += 1
            print(f'Deleted: {obj[\"Key\"]}')

print(f'Total old backups deleted: {deleted}')
"

    log "Cleanup completed"
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    log "=== Redis backup started ==="

    check_prereqs
    verify_s3

    trigger_bgsave

    local local_path
    local_path=$(copy_rdb)

    upload_to_s3 "$local_path"

    cleanup_old_backups

    log "=== Redis backup completed successfully ==="
}

main "$@"
