#!/usr/bin/env bash
#
# scripts/backup_qdrant.sh
# Create Qdrant snapshot and upload to S3/MinIO with retention policy.
#
# Required environment variables:
#   QDRANT_HOST     — Qdrant HTTP API endpoint (default: localhost)
#   QDRANT_PORT     — Qdrant HTTP API port (default: 6333)
#   BACKUP_BUCKET   — S3/MinIO bucket name
#   S3_ENDPOINT     — S3/MinIO endpoint URL
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
# Optional environment variables:
#   COLLECTION_NAME — Qdrant collection name (default: knowledge_base)
#   RETENTION_DAYS  — Snapshot retention in days (default: 7)
#
# Usage:
#   ./backup_qdrant.sh

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
QDRANT_HOST="${QDRANT_HOST:-localhost}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
COLLECTION_NAME="${COLLECTION_NAME:-knowledge_base}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
BACKUP_DATE="$(date -u +%Y-%m-%d)"
SNAPSHOT_NAME="snapshot-${BACKUP_DATE}-$(date -u +%H%M%S)"

LOG_FILE="${LOG_DIR:-/var/log/rag-system}/backup_qdrant_${BACKUP_DATE}.log"
: "${BACKUP_BUCKET:?BACKUP_BUCKET must be set}"
: "${S3_ENDPOINT:?S3_ENDPOINT must be set}"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG_FILE"
}

check_prereqs() {
    for cmd in curl python3 jq; do
        if ! command -v "$cmd" &>/dev/null; then
            log "ERROR: Required command '$cmd' not found in PATH"
            exit 1
        fi
    done
}

# ── Verify S3 credentials ──────────────────────────────────────────────────
verify_s3() {
    if [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
        log "ERROR: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set"
        exit 1
    fi

    if ! python3 -c "import boto3; boto3.client('s3', endpoint_url='${S3_ENDPOINT}').head_bucket(Bucket='${BACKUP_BUCKET}')" 2>/dev/null; then
        log "WARNING: Could not verify bucket '${BACKUP_BUCKET}' — will attempt upload anyway"
    fi
}

# ── Create Qdrant snapshot via REST API ────────────────────────────────────
create_snapshot() {
    log "Creating Qdrant snapshot '${SNAPSHOT_NAME}' for collection '${COLLECTION_NAME}'..."

    local base_url="http://${QDRANT_HOST}:${QDRANT_PORT}"

    local response
    response=$(curl -s -w "\n%{http_code}" \
        -X POST "${base_url}/collections/${COLLECTION_NAME}/snapshots" \
        -H "Content-Type: application/json" \
        -d '{}' 2>&1)

    local http_code
    http_code=$(echo "$response" | tail -1)
    local body
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" != "200" ] && [ "$http_code" != "202" ]; then
        log "ERROR: Failed to create snapshot. HTTP ${http_code}: ${body}"
        exit 1
    fi

    log "Snapshot creation initiated successfully (HTTP ${http_code})"

    local snapshot_file
    snapshot_file=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('name',''))" 2>/dev/null || echo "")

    if [ -z "$snapshot_file" ]; then
        log "WARNING: Could not parse snapshot name from response. Using fallback name."
        snapshot_file="${SNAPSHOT_NAME}"
    fi

    log "Waiting for snapshot '${snapshot_file}' to be ready..."

    local max_wait=300
    local waited=0
    while [ $waited -lt $max_wait ]; do
        local status_response
        status_response=$(curl -s -o /dev/null -w "%{http_code}" \
            "${base_url}/collections/${COLLECTION_NAME}/snapshots/${snapshot_file}")

        if [ "$status_response" == "200" ]; then
            log "Snapshot '${snapshot_file}' is ready"
            break
        fi

        sleep 5
        waited=$((waited + 5))
    done

    if [ $waited -ge $max_wait ]; then
        log "ERROR: Timed out waiting for snapshot to be ready (${max_wait}s)"
        exit 1
    fi

    echo "$snapshot_file"
}

# ── Download snapshot from Qdrant ──────────────────────────────────────────
download_snapshot() {
    local snapshot_file="$1"
    local base_url="http://${QDRANT_HOST}:${QDRANT_PORT}"
    local local_path="/tmp/${snapshot_file}"

    log "Downloading snapshot to ${local_path}..."

    curl -s -o "${local_path}" \
        "${base_url}/collections/${COLLECTION_NAME}/snapshots/${snapshot_file}"

    if [ ! -s "${local_path}" ]; then
        log "ERROR: Downloaded snapshot file is empty or missing"
        exit 1
    fi

    log "Snapshot downloaded: $(du -h "${local_path}" | cut -f1)"

    echo "${local_path}"
}

# ── Upload to S3/MinIO ─────────────────────────────────────────────────────
upload_to_s3() {
    local local_path="$1"
    local snapshot_file="$2"
    local s3_key="qdrant/${BACKUP_DATE}/${snapshot_file}"

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

# ── Cleanup old snapshots (S3 side) ────────────────────────────────────────
cleanup_old_snapshots_s3() {
    log "Cleaning up S3 snapshots older than ${RETENTION_DAYS} days..."

    python3 -c "
import boto3
from datetime import datetime, timedelta, timezone

s3 = boto3.client('s3', endpoint_url='${S3_ENDPOINT}')
cutoff = datetime.now(timezone.utc) - timedelta(days=${RETENTION_DAYS})

paginator = s3.get_paginator('list_objects_v2')
pages = paginator.paginate(Bucket='${BACKUP_BUCKET}', Prefix='qdrant/')

deleted = 0
for page in pages:
    if 'Contents' not in page:
        continue
    for obj in page['Contents']:
        if obj['LastModified'] < cutoff:
            s3.delete_object(Bucket='${BACKUP_BUCKET}', Key=obj['Key'])
            deleted += 1
            print(f'Deleted: {obj[\"Key\"]} (last modified: {obj[\"LastModified\"]})')

print(f'Total old snapshots deleted from S3: {deleted}')
"

    log "S3 cleanup completed"
}

# ── Cleanup old snapshots (Qdrant side) ────────────────────────────────────
cleanup_old_snapshots_qdrant() {
    log "Cleaning up Qdrant-side snapshots older than ${RETENTION_DAYS} days..."

    local base_url="http://${QDRANT_HOST}:${QDRANT_PORT}"
    local cutoff_date
    cutoff_date=$(date -u -d "${RETENTION_DAYS} days ago" +%Y-%m-%d)

    local response
    response=$(curl -s "${base_url}/collections/${COLLECTION_NAME}/snapshots" 2>/dev/null)

    if [ $? -ne 0 ]; then
        log "WARNING: Could not list Qdrant snapshots"
        return
    fi

    echo "$response" | python3 -c "
import sys, json
from datetime import datetime

data = json.load(sys.stdin)
snapshots = data.get('result', [])
cutoff = datetime.strptime('${cutoff_date}', '%Y-%m-%d')

deleted = 0
for snap in snapshots:
    try:
        created = datetime.fromisoformat(snap['creation_time'].replace('Z', '+00:00'))
        if created.replace(tzinfo=None) < cutoff:
            snap_name = snap['name']
            import subprocess
            url = f'http://${QDRANT_HOST}:${QDRANT_PORT}/collections/${COLLECTION_NAME}/snapshots/{snap_name}'
            result = subprocess.run(['curl', '-s', '-X', 'DELETE', url], capture_output=True, text=True)
            if 'ok' in result.stdout.lower():
                print(f'Deleted Qdrant snapshot: {snap_name}')
                deleted += 1
    except Exception as e:
        print(f'Skipping snapshot: {e}', file=sys.stderr)

print(f'Total old Qdrant snapshots deleted: {deleted}')
"

    log "Qdrant-side cleanup completed"
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    log "=== Qdrant backup started ==="

    check_prereqs
    verify_s3

    local snapshot_file
    snapshot_file=$(create_snapshot)

    local local_path
    local_path=$(download_snapshot "${snapshot_file}")

    upload_to_s3 "${local_path}" "${snapshot_file}"

    cleanup_old_snapshots_s3
    cleanup_old_snapshots_qdrant

    log "=== Qdrant backup completed successfully ==="
}

main "$@"
