#!/usr/bin/env bash
#
# scripts/restore_all.sh
# Download latest backups from S3/MinIO and restore all services.
#
# Required environment variables:
#   BACKUP_BUCKET    — S3/MinIO bucket name
#   S3_ENDPOINT      — S3/MinIO endpoint URL
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
# Service-specific (as needed for the services to restore):
#   QDRANT_HOST, QDRANT_PORT, COLLECTION_NAME
#   NEO4J_USER, NEO4J_PASSWORD, NEO4J_URI
#   REDIS_URL or REDIS_DATA_DIR
#
# Optional environment variables:
#   RESTORE_DATE       — Restore from specific date YYYY-MM-DD (default: latest)
#   SKIP_QDRANT        — Set to 'true' to skip Qdrant restore
#   SKIP_NEO4J         — Set to 'true' to skip Neo4j restore
#   SKIP_REDIS         — Set to 'true' to skip Redis restore
#   DRY_RUN            — Set to 'true' to list available backups without restoring
#
# Usage:
#   ./restore_all.sh

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
RESTORE_DATE="${RESTORE_DATE:-}"
LOG_FILE="${LOG_DIR:-/var/log/rag-system}/restore_$(date -u +%Y-%m-%d_%H%M%S).log"
: "${BACKUP_BUCKET:?BACKUP_BUCKET must be set}"
: "${S3_ENDPOINT:?S3_ENDPOINT must be set}"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG_FILE"
}

# ── S3 list helper ─────────────────────────────────────────────────────────
list_s3_backups() {
    local prefix="$1"
    local limit="${2:-}"

    local jq_limit=""
    if [ -n "$limit" ]; then
        jq_limit="-${limit}"
    fi

    python3 -c "
import boto3, sys, json

s3 = boto3.client('s3', endpoint_url='${S3_ENDPOINT}')
paginator = s3.get_paginator('list_objects_v2')
pages = paginator.paginate(Bucket='${BACKUP_BUCKET}', Prefix='${prefix}')

objects = []
for page in pages:
    if 'Contents' not in page:
        continue
    for obj in page['Contents']:
        objects.append({
            'key': obj['Key'],
            'size': obj['Size'],
            'last_modified': obj['LastModified'].isoformat()
        })

objects.sort(key=lambda x: x['last_modified'], reverse=True)
print(json.dumps(objects[:${limit:-20}], indent=2))
"
}

# ── Find latest backup for a prefix ────────────────────────────────────────
find_latest() {
    local prefix="$1"

    python3 -c "
import boto3

s3 = boto3.client('s3', endpoint_url='${S3_ENDPOINT}')
paginator = s3.get_paginator('list_objects_v2')
pages = paginator.paginate(Bucket='${BACKUP_BUCKET}', Prefix='${prefix}')

latest = None
for page in pages:
    if 'Contents' not in page:
        continue
    for obj in page['Contents']:
        if latest is None or obj['LastModified'] > latest['LastModified']:
            latest = obj

if latest:
    print(latest['Key'])
"
}

# ── Download from S3 ───────────────────────────────────────────────────────
download_from_s3() {
    local s3_key="$1"
    local local_path="$2"

    log "Downloading s3://${BACKUP_BUCKET}/${s3_key} -> ${local_path}"

    python3 -c "
import boto3, sys
s3 = boto3.client('s3', endpoint_url='${S3_ENDPOINT}')
try:
    s3.download_file('${BACKUP_BUCKET}', '${s3_key}', '${local_path}')
    print(f'Downloaded: ${local_path}')
except Exception as e:
    print(f'Download failed: {e}', file=sys.stderr)
    sys.exit(1)
"

    if [ ! -f "${local_path}" ]; then
        log "ERROR: Download failed — file not found at ${local_path}"
        return 1
    fi

    log "Downloaded: $(du -h "${local_path}" | cut -f1)"
}

# ── Restore Qdrant ─────────────────────────────────────────────────────────
restore_qdrant() {
    log "=== Restoring Qdrant ==="

    local qdrant_host="${QDRANT_HOST:-localhost}"
    local qdrant_port="${QDRANT_PORT:-6333}"
    local collection="${COLLECTION_NAME:-knowledge_base}"

    local key
    key=$(find_latest "qdrant/")
    if [ -z "$key" ]; then
        log "WARNING: No Qdrant backup found in S3. Skipping restore."
        return 0
    fi

    log "Found latest Qdrant backup: ${key}"

    local filename
    filename=$(basename "$key")
    local local_path="/tmp/${filename}"

    download_from_s3 "$key" "$local_path"

    local base_url="http://${qdrant_host}:${qdrant_port}"

    log "Restoring snapshot to collection '${collection}'..."

    local response
    response=$(curl -s -w "\n%{http_code}" \
        -X PUT "${base_url}/collections/${collection}/snapshots/recover" \
        -F "snapshot=@${local_path}" 2>&1)

    local http_code
    http_code=$(echo "$response" | tail -1)

    if [ "$http_code" != "200" ] && [ "$http_code" != "202" ]; then
        log "ERROR: Qdrant snapshot restore failed. HTTP ${http_code}"
        rm -f "$local_path"
        return 1
    fi

    log "Qdrant snapshot restore initiated (HTTP ${http_code})"

    # Wait for recovery to complete
    log "Waiting for Qdrant recovery to complete..."
    local max_wait=600
    local waited=0
    while [ $waited -lt $max_wait ]; do
        local status
        status=$(curl -s "${base_url}/collections/${collection}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',{}).get('status',''))" 2>/dev/null || echo "")
        if [ "$status" == "green" ] || [ "$status" == "yellow" ]; then
            log "Qdrant collection status: ${status}"
            break
        fi
        sleep 10
        waited=$((waited + 10))
    done

    rm -f "$local_path"
    log "Qdrant restore completed"
}

# ── Restore Neo4j ──────────────────────────────────────────────────────────
restore_neo4j() {
    log "=== Restoring Neo4j ==="

    local key
    key=$(find_latest "neo4j/")
    if [ -z "$key" ]; then
        log "WARNING: No Neo4j backup found in S3. Skipping restore."
        return 0
    fi

    log "Found latest Neo4j backup: ${key}"

    local filename
    filename=$(basename "$key")
    local local_dir="/tmp/neo4j_restore"
    mkdir -p "${local_dir}"
    local local_path="${local_dir}/${filename}"

    download_from_s3 "$key" "$local_path"

    # Try to find neo4j-admin
    local neo4j_admin
    if command -v neo4j-admin &>/dev/null; then
        neo4j_admin="neo4j-admin"
    elif [ -x /var/lib/neo4j/bin/neo4j-admin ]; then
        neo4j_admin="/var/lib/neo4j/bin/neo4j-admin"
    else
        log "WARNING: neo4j-admin not found. Cannot restore .dump file. Backup saved to ${local_path}"
        log "To restore manually, copy to Neo4j server and run:"
        log "  neo4j-admin database load neo4j --from-path=${local_dir} --overwrite-destination=true"
        return 0
    fi

    log "Restoring Neo4j database from dump..."

    # Stop Neo4j if running (required for restore)
    log "NOTE: Neo4j must be stopped before restore. Waking 10s for manual intervention..."
    sleep 10

    if ! "$neo4j_admin" database load neo4j --from-path="${local_dir}" --overwrite-destination=true 2>&1 | tee -a "$LOG_FILE"; then
        log "ERROR: Neo4j restore failed"
        return 1
    fi

    rm -rf "${local_dir}"
    log "Neo4j restore completed"
}

# ── Restore Redis ──────────────────────────────────────────────────────────
restore_redis() {
    log "=== Restoring Redis ==="

    local key
    key=$(find_latest "redis/")
    if [ -z "$key" ]; then
        log "WARNING: No Redis backup found in S3. Skipping restore."
        return 0
    fi

    log "Found latest Redis backup: ${key}"

    local filename
    filename=$(basename "$key")
    local local_path="/tmp/${filename}"

    download_from_s3 "$key" "$local_path"

    # Determine Redis data directory
    local data_dir="${REDIS_DATA_DIR:-/data}"

    if [ ! -d "$data_dir" ]; then
        log "ERROR: Redis data directory not found: ${data_dir}"
        rm -f "$local_path"
        return 1
    fi

    log "Restoring Redis RDB to ${data_dir}/dump.rdb..."

    cp "$local_path" "${data_dir}/dump.rdb"
    rm -f "$local_path"

    log "Redis RDB restored to ${data_dir}/dump.rdb"
    log "Restart Redis for changes to take effect"
}

# ── Verify health ──────────────────────────────────────────────────────────
verify_health() {
    log "=== Verifying service health ==="

    local all_healthy=true

    # Check Qdrant
    if [ "${SKIP_QDRANT:-}" != "true" ]; then
        local qdrant_host="${QDRANT_HOST:-localhost}"
        local qdrant_port="${QDRANT_PORT:-6333}"
        if curl -s -o /dev/null -w "%{http_code}" "http://${qdrant_host}:${qdrant_port}/health" | grep -q "200"; then
            log "[OK] Qdrant is healthy"
        else
            log "[FAIL] Qdrant health check failed"
            all_healthy=false
        fi
    fi

    # Check Neo4j
    if [ "${SKIP_NEO4J:-}" != "true" ]; then
        local neo4j_uri="${NEO4J_URI:-bolt://localhost:7687}"
        local neo4j_host
        local neo4j_port
        neo4j_host=$(echo "$neo4j_uri" | sed -E 's|bolt://([^:]+).*|\1|')
        neo4j_port=7687

        if timeout 5 bash -c "echo > /dev/tcp/${neo4j_host}/${neo4j_port}" 2>/dev/null; then
            log "[OK] Neo4j is reachable on bolt://${neo4j_host}:${neo4j_port}"
        else
            log "[FAIL] Neo4j bolt port not reachable"
            all_healthy=false
        fi
    fi

    # Check Redis
    if [ "${SKIP_REDIS:-}" != "true" ]; then
        local redis_url="${REDIS_URL:-redis://localhost:6379}"
        local redis_host
        local redis_port
        if [[ "$redis_url" =~ redis://([^:/]+):?([0-9]*)$ ]] || [[ "$redis_url" =~ redis://([^:/]+)/?$ ]]; then
            redis_host="${BASH_REMATCH[1]}"
            redis_port="${BASH_REMATCH[2]:-6379}"
        else
            redis_host=localhost
            redis_port=6379
        fi

        if timeout 5 bash -c "echo > /dev/tcp/${redis_host}/${redis_port}" 2>/dev/null; then
            log "[OK] Redis is reachable on redis://${redis_host}:${redis_port}"
        else
            log "[FAIL] Redis port not reachable"
            all_healthy=false
        fi
    fi

    if [ "$all_healthy" == "true" ]; then
        log "All restored services are healthy"
    else
        log "WARNING: Some services failed health checks"
    fi
}

# ── Dry run — list available backups ───────────────────────────────────────
dry_run() {
    log "=== Dry Run: Listing available backups ==="

    log "--- Qdrant backups ---"
    list_s3_backups "qdrant/" 5

    echo ""
    log "--- Neo4j backups ---"
    list_s3_backups "neo4j/" 5

    echo ""
    log "--- Redis backups ---"
    list_s3_backups "redis/" 5
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    log "=== Restore process started ==="

    if [ "${DRY_RUN:-}" == "true" ]; then
        dry_run
        log "=== Dry run complete ==="
        exit 0
    fi

    if [ "${SKIP_QDRANT:-}" != "true" ]; then
        restore_qdrant || log "WARNING: Qdrant restore had issues"
    else
        log "Skipping Qdrant restore (SKIP_QDRANT=true)"
    fi

    if [ "${SKIP_NEO4J:-}" != "true" ]; then
        restore_neo4j || log "WARNING: Neo4j restore had issues"
    else
        log "Skipping Neo4j restore (SKIP_NEO4J=true)"
    fi

    if [ "${SKIP_REDIS:-}" != "true" ]; then
        restore_redis || log "WARNING: Redis restore had issues"
    else
        log "Skipping Redis restore (SKIP_REDIS=true)"
    fi

    verify_health

    log "=== Restore process completed ==="
}

main "$@"
