#!/usr/bin/env bash
#
# scripts/ops/verify_restore.sh
# Verify backup integrity — local files or S3/MinIO.
#
# Modes:
#   local  — verify backups in a local directory (default)
#   s3     — verify backups in S3/MinIO bucket
#
# Required environment variables (S3 mode):
#   BACKUP_BUCKET    — S3/MinIO bucket name
#   S3_ENDPOINT      — S3/MinIO endpoint URL
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#
# Optional environment variables:
#   RETENTION_DAYS   — warn if newest backup older than this (default: 2)
#   MIN_SIZE_BYTES   — minimum expected file size in bytes (default: 1024)
#
# Usage:
#   ./verify_restore.sh                          # local mode, ./backups/
#   ./verify_restore.sh /path/to/backups         # local mode, custom path
#   ./verify_restore.sh --s3                     # S3 mode
#   ./verify_restore.sh --quiet                  # error-only output

set -euo pipefail

BACKUP_DIR="${1:-./backups}"
MODE="local"
QUIET=false
MIN_SIZE_BYTES="${MIN_SIZE_BYTES:-1024}"
RETENTION_DAYS="${RETENTION_DAYS:-2}"
ERRORS=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_ok()   { $QUIET || echo -e "   ${GREEN}OK${NC}   $*"; }
log_warn() { $QUIET || echo -e "   ${YELLOW}WARN${NC}  $*"; }
log_err()  { echo -e "   ${RED}FAIL${NC} $*"; ERRORS=$((ERRORS + 1)); }

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --s3)    MODE="s3" ;;
            --quiet) QUIET=true ;;
            --help|-h)
                echo "Usage: $(basename "$0") [DIR] [--s3] [--quiet]"
                exit 0
                ;;
            *) BACKUP_DIR="$1" ;;
        esac
        shift
    done
}

verify_s3_backups() {
    : "${BACKUP_BUCKET:?BACKUP_BUCKET must be set}"
    : "${S3_ENDPOINT:?S3_ENDPOINT must be set}"

    python3 -c "
import sys
from datetime import datetime, timedelta, timezone

try:
    import boto3
except ImportError:
    print('FAIL: boto3 not installed', file=sys.stderr)
    sys.exit(1)

s3 = boto3.client('s3', endpoint_url='${S3_ENDPOINT}')

services = {
    'Qdrant':  'qdrant/',
    'Neo4j':   'neo4j/',
    'Redis':   'redis/',
}

min_size = ${MIN_SIZE_BYTES}
cutoff = datetime.now(timezone.utc) - timedelta(days=${RETENTION_DAYS})
overall_ok = True

for service, prefix in services.items():
    try:
        paginator = s3.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket='${BACKUP_BUCKET}', Prefix=prefix)

        objects = []
        for page in pages:
            if 'Contents' in page:
                objects.extend(page['Contents'])

        if not objects:
            print(f'WARN: {service} — no backups found in s3://${BACKUP_BUCKET}/{prefix}')
            continue

        objects.sort(key=lambda x: x['LastModified'], reverse=True)
        latest = objects[0]

        issues = []

        if latest['Size'] < min_size:
            issues.append(f'size={latest[\"Size\"]}B < {min_size}B')

        if latest['LastModified'] < cutoff:
            age_days = (datetime.now(timezone.utc) - latest['LastModified']).days
            issues.append(f'age={age_days}d > {${RETENTION_DAYS}}d')

        if issues:
            print(f'WARN: {service} — latest backup has issues: {\" \".join(issues)} — key={latest[\"Key\"]}')
        else:
            size_mb = latest['Size'] / (1024 * 1024)
            age_hours = (datetime.now(timezone.utc) - latest['LastModified']).total_seconds() / 3600
            print(f'OK:   {service} — latest: {latest[\"Key\"]} ({size_mb:.1f}MB, {age_hours:.1f}h ago)')

        total = sum(o['Size'] for o in objects)
        print(f'      total backups: {len(objects)}, combined size: {total / (1024 * 1024):.1f}MB')

    except Exception as e:
        print(f'FAIL: {service} — error: {e}')
        overall_ok = False

exit(0 if overall_ok else 1)
" 2>/dev/null

    local s3_status=$?
    if [ $s3_status -ne 0 ]; then
        ERRORS=$((ERRORS + 1))
    fi
}

verify_local_backups() {
    if [ ! -d "$BACKUP_DIR" ]; then
        log_err "Backup directory not found: $BACKUP_DIR"
        return
    fi

    local service_patterns=(
        "Qdrant:snapshot-*"
        "Neo4j:neo4j-dump-*.dump"
        "Redis:redis-rdb-*.rdb"
    )

    for entry in "${service_patterns[@]}"; do
        local service="${entry%%:*}"
        local pattern="${entry##*:}"

        local latest
        latest=$(find "$BACKUP_DIR" -maxdepth 1 -name "$pattern" -type f 2>/dev/null | sort -r | head -1)

        if [ -z "$latest" ]; then
            log_warn "$service — no backups found matching: $pattern"
            continue
        fi

        local fname size
        fname=$(basename "$latest")
        size=$(stat -c%s "$latest" 2>/dev/null || stat -f%z "$latest" 2>/dev/null)

        if [ "$size" -lt "$MIN_SIZE_BYTES" ]; then
            log_err "$service — $fname: size=${size}B < ${MIN_SIZE_BYTES}B"
        else
            local size_mb
            size_mb=$(echo "scale=1; $size / 1048576" | bc 2>/dev/null || echo "?")
            log_ok "$service — $fname (${size_mb}MB)"
        fi

        if ! file "$latest" 2>/dev/null | grep -qE '(gzip|data|ASCII|UTF-8)'; then
            log_warn "$service — $fname: unrecognized file type"
        fi
    done

    local total_count
    total_count=$(find "$BACKUP_DIR" -maxdepth 1 -type f \( \
        -name "snapshot-*" -o \
        -name "neo4j-dump-*.dump" -o \
        -name "redis-rdb-*.rdb" \) 2>/dev/null | wc -l)
    log_ok "Total backup files found: $total_count"
}

print_summary() {
    $QUIET || echo ""
    $QUIET || echo -e "${YELLOW}========================================${NC}"
    if [ $ERRORS -eq 0 ]; then
        $QUIET || echo -e "${GREEN}All backup integrity checks passed${NC}"
    else
        echo -e "${RED}$ERRORS backup integrity issue(s) found${NC}"
    fi
    $QUIET || echo -e "${YELLOW}========================================${NC}"
}

main() {
    parse_args "$@"

    if [ "$MODE" = "local" ]; then
        $QUIET || echo -e "${GREEN}Verifying local backups in $BACKUP_DIR...${NC}"
        verify_local_backups
    elif [ "$MODE" = "s3" ]; then
        $QUIET || echo -e "${GREEN}Verifying S3 backups in s3://${BACKUP_BUCKET:-?}/...${NC}"
        verify_s3_backups
    fi

    print_summary
    exit $((ERRORS > 0 ? 1 : 0))
}

main "$@"
