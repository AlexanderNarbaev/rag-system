#!/usr/bin/env bash
#
# scripts/backup_neo4j.sh
# Create Neo4j database dump and upload to S3/MinIO with retention policy.
#
# Required environment variables:
#   NEO4J_URI       — Neo4j bolt URI (e.g., bolt://localhost:7687)
#   NEO4J_USER      — Neo4j username
#   NEO4J_PASSWORD  — Neo4j password
#   BACKUP_BUCKET   — S3/MinIO bucket name
#   S3_ENDPOINT     — S3/MinIO endpoint URL
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
# Optional environment variables:
#   NEO4J_DATA_DIR  — Neo4j data directory (default: /data)
#   RETENTION_DAYS  — Backup retention in days (default: 7)
#
# Note: Uses neo4j-admin dump for consistency. Requires neo4j-admin to be
#       available in the Neo4j container or accessible on the host.
#
# Usage:
#   ./backup_neo4j.sh

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
NEO4J_USER="${NEO4J_USER:-neo4j}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
BACKUP_DATE="$(date -u +%Y-%m-%d)"
BACKUP_NAME="neo4j-dump-${BACKUP_DATE}-$(date -u +%H%M%S)"
BACKUP_DIR="/tmp/neo4j_backups"
DUMP_FILE="${BACKUP_DIR}/${BACKUP_NAME}.dump"

LOG_FILE="${LOG_DIR:-/var/log/rag-system}/backup_neo4j_${BACKUP_DATE}.log"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be set}"
: "${BACKUP_BUCKET:?BACKUP_BUCKET must be set}"
: "${S3_ENDPOINT:?S3_ENDPOINT must be set}"

mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "${BACKUP_DIR}"

log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG_FILE"
}

check_prereqs() {
    for cmd in python3; do
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

# ── Find neo4j-admin ───────────────────────────────────────────────────────
find_neo4j_admin() {
    # Check if neo4j-admin is available directly
    if command -v neo4j-admin &>/dev/null; then
        echo "neo4j-admin"
        return
    fi

    # Check common locations
    for path in \
        /var/lib/neo4j/bin/neo4j-admin \
        /usr/bin/neo4j-admin \
        /usr/local/bin/neo4j-admin; do
        if [ -x "$path" ]; then
            echo "$path"
            return
        fi
    done

    log "ERROR: neo4j-admin not found. Ensure Neo4j is installed or specify NEO4J_DATA_DIR"
    exit 1
}

# ── Run neo4j-admin dump ───────────────────────────────────────────────────
create_dump() {
    local neo4j_admin
    neo4j_admin=$(find_neo4j_admin)

    log "Creating Neo4j dump using $neo4j_admin..."

    if [ -n "${NEO4J_DATA_DIR:-}" ]; then
        log "Using data directory: ${NEO4J_DATA_DIR}"
        if ! "$neo4j_admin" database dump neo4j --to-path="${BACKUP_DIR}" --overwrite-destination=true 2>&1 | tee -a "$LOG_FILE"; then
            log "ERROR: neo4j-admin dump failed"
            exit 1
        fi
    else
        log "No NEO4J_DATA_DIR set — attempting online backup via cypher-shell"

        if ! command -v cypher-shell &>/dev/null; then
            log "ERROR: Cannot perform online backup without cypher-shell or NEO4J_DATA_DIR"
            exit 1
        fi

        local uri="${NEO4J_URI:-bolt://localhost:7687}"

        log "Running APOC export via cypher-shell (requires APOC plugin)..."

        local cypher_cmd="CALL apoc.export.cypher.all('${DUMP_FILE}', {format: 'plain', useOptimizations: {type: 'UNWIND_BATCH', unwindBatchSize: 20}})"
        echo "$cypher_cmd" | cypher-shell -a "$uri" -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" 2>&1 | tee -a "$LOG_FILE"

        if [ "${PIPESTATUS[0]}" -ne 0 ]; then
            log "WARNING: cypher-shell export may have failed. Attempting fallback..."

            local apoc_json="${BACKUP_DIR}/${BACKUP_NAME}.json"
            cypher-shell -a "$uri" -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" \
                --format plain \
                "CALL apoc.export.json.all('${apoc_json}', {useTypes: true})" 2>&1 | tee -a "$LOG_FILE"

            if [ -f "${apoc_json}" ]; then
                log "JSON export created: ${apoc_json}"
                EXTRA_FILES="${EXTRA_FILES:-} ${apoc_json}"
            fi
        fi
    fi

    # If neo4j-admin dump ran, rename the output to our naming convention
    if [ -f "${BACKUP_DIR}/neo4j.dump" ] && [ ! -f "${DUMP_FILE}" ]; then
        mv "${BACKUP_DIR}/neo4j.dump" "${DUMP_FILE}"
        log "Renamed dump to ${DUMP_FILE}"
    fi

    if [ ! -f "${DUMP_FILE}" ]; then
        log "WARNING: No .dump file created at ${DUMP_FILE}"
    else
        log "Dump created: $(du -h "${DUMP_FILE}" | cut -f1)"
    fi
}

# ── Upload to S3/MinIO ─────────────────────────────────────────────────────
upload_to_s3() {
    local s3_prefix="neo4j/${BACKUP_DATE}"

    log "Uploading to s3://${BACKUP_BUCKET}/${s3_prefix}/..."

    python3 -c "
import boto3, os, glob, sys
s3 = boto3.client('s3', endpoint_url='${S3_ENDPOINT}')
prefix = '${s3_prefix}'
backup_dir = '${BACKUP_DIR}'
bucket = '${BACKUP_BUCKET}'

for f in os.listdir(backup_dir):
    fpath = os.path.join(backup_dir, f)
    if not os.path.isfile(fpath):
        continue
    key = f'{prefix}/{f}'
    try:
        s3.upload_file(fpath, bucket, key)
        print(f'Uploaded: {key}')
    except Exception as e:
        print(f'Failed to upload {fpath}: {e}', file=sys.stderr)
        sys.exit(1)
"

    log "Upload completed"
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
pages = paginator.paginate(Bucket='${BACKUP_BUCKET}', Prefix='neo4j/')

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

# ── Clean local temp files ─────────────────────────────────────────────────
cleanup_local() {
    log "Cleaning up local backup files..."
    rm -rf "${BACKUP_DIR:?}"
    log "Local cleanup done"
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    log "=== Neo4j backup started ==="

    check_prereqs
    verify_s3

    create_dump
    upload_to_s3
    cleanup_old_backups
    cleanup_local

    log "=== Neo4j backup completed successfully ==="
}

main "$@"
