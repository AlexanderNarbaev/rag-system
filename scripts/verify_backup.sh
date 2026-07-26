#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/backup}"
echo "=== Backup Verification ==="

latest_file() {
    local directory="$1" pattern="$2"
    ls -t "$BACKUP_ROOT/$directory"/$pattern 2>/dev/null | head -1 || true
}

check_backup() {
    local label="$1" directory="$2" pattern="$3"
    echo "[$label]"
    local latest
    latest=$(latest_file "$directory" "$pattern")
    if [[ -z "$latest" ]]; then
        echo "  FAIL: No $label backup found in $BACKUP_ROOT/$directory"
        return 1
    fi
    local size
    size=$(stat -c%s "$latest")
    if [[ "$size" -le 0 ]]; then
        echo "  FAIL: $latest is empty"
        return 1
    fi
    echo "  OK: $latest ($size bytes)"
}

check_backup "Qdrant snapshot" qdrant '*.tar.gz'
check_backup "Neo4j dump" neo4j '*.dump'
check_backup "Redis RDB" redis '*.rdb'

echo "=== Backup Verification PASSED ==="
