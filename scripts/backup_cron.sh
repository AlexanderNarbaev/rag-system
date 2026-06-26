#!/usr/bin/env bash
#
# scripts/backup_cron.sh
# Cron wrapper that runs all backup scripts in sequence with logging.
# Designed to be called from cron: 0 * * * * /scripts/backup_cron.sh (RPO < 1h)
#
# Required environment variables (same as individual backup scripts):
#   BACKUP_BUCKET     — S3/MinIO bucket name
#   S3_ENDPOINT       — S3/MinIO endpoint URL
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#   QDRANT_HOST, QDRANT_PORT, COLLECTION_NAME
#   NEO4J_USER, NEO4J_PASSWORD, NEO4J_URI
#   REDIS_URL
#
# Optional environment variables:
#   BACKUP_SCRIPTS_DIR  — Directory containing backup scripts (default: /scripts)
#   LOG_DIR             — Log directory (default: /var/log/rag-system)
#   RETENTION_DAYS      — Backup retention in days (default: 7)
#   LOCK_FILE           — Path to lock file (default: /tmp/backup_cron.lock)
#   LOCK_TIMEOUT        — Lock timeout in seconds (default: 3540 = 59 min)
#   SKIP_QDRANT         — Skip Qdrant backup
#   SKIP_NEO4J          — Skip Neo4j backup
#   SKIP_REDIS          — Skip Redis backup
#
# Usage:
#   # Run as cron (every hour, RPO < 1h):
#   0 * * * * /scripts/backup_cron.sh >> /var/log/rag-system/backup_cron.log 2>&1
#
#   # Run manually:
#   ./backup_cron.sh

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPTS_DIR="${BACKUP_SCRIPTS_DIR:-${SCRIPT_DIR}}"
LOG_DIR="${LOG_DIR:-/var/log/rag-system}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
LOCK_FILE="${LOCK_FILE:-/tmp/backup_cron.lock}"
LOCK_TIMEOUT="${LOCK_TIMEOUT:-3540}"

RUN_ID="$(date -u +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/backup_cron_$(date -u +%Y-%m-%d).log"
SUMMARY_FILE="${LOG_DIR}/backup_summary_${RUN_ID}.log"

mkdir -p "${LOG_DIR}"

# ── Logging ────────────────────────────────────────────────────────────────
log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] [${RUN_ID}] $*" | tee -a "$LOG_FILE"
}

log_summary() {
    echo "$*" | tee -a "$SUMMARY_FILE"
}

# ── Lock management ────────────────────────────────────────────────────────
acquire_lock() {
    if [ -f "$LOCK_FILE" ]; then
        local lock_age
        lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || stat -f %m "$LOCK_FILE" 2>/dev/null) ))

        if [ "$lock_age" -lt "${LOCK_TIMEOUT}" ]; then
            log "ERROR: Another backup process is running (lock age: ${lock_age}s). Aborting."
            exit 0
        else
            log "WARNING: Stale lock file found (${lock_age}s). Removing and continuing."
            rm -f "$LOCK_FILE"
        fi
    fi

    echo "${RUN_ID}" > "$LOCK_FILE"
    log "Lock acquired: ${LOCK_FILE}"
}

release_lock() {
    if [ -f "$LOCK_FILE" ] && [ "$(cat "$LOCK_FILE")" == "${RUN_ID}" ]; then
        rm -f "$LOCK_FILE"
        log "Lock released"
    fi
}

# ── Run a single backup script with error handling ─────────────────────────
run_backup() {
    local service="$1"
    local script="$2"

    log_summary ""
    log_summary "=== ${service} Backup ==="

    local start_time
    start_time=$(date +%s)

    if [ ! -x "$script" ]; then
        log "ERROR: Backup script not found or not executable: ${script}"
        log_summary "  Status: FAILED (script not found)"
        return 1
    fi

    log "Running: ${script}"
    local exit_code=0

    # Run with timeout (55 minutes) to ensure completion within the hour
    if timeout 3300 bash "$script" 2>&1 | tee -a "$LOG_FILE"; then
        exit_code=0
    else
        exit_code=${PIPESTATUS[0]}
    fi

    local elapsed
    elapsed=$(( $(date +%s) - start_time ))

    if [ "$exit_code" -eq 0 ]; then
        log "[OK] ${service} backup completed successfully (${elapsed}s)"
        log_summary "  Status: SUCCESS (${elapsed}s)"
        return 0
    else
        log "[FAIL] ${service} backup failed with exit code ${exit_code} (${elapsed}s)"
        log_summary "  Status: FAILED (exit=${exit_code}, ${elapsed}s)"
        return 1
    fi
}

# ── Validate prerequisites ─────────────────────────────────────────────────
validate_env() {
    local errors=0

    for var in BACKUP_BUCKET S3_ENDPOINT AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
        if [ -z "${!var:-}" ]; then
            log "ERROR: Required environment variable ${var} is not set"
            errors=$((errors + 1))
        fi
    done

    if [ $errors -gt 0 ]; then
        log "ERROR: ${errors} required environment variable(s) missing"
        exit 1
    fi
}

# ── Generate summary report ────────────────────────────────────────────────
generate_summary() {
    log_summary ""
    log_summary "=========================================="
    log_summary "Backup Summary — ${RUN_ID}"
    log_summary "=========================================="
    log_summary "Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    log_summary "Log file: ${LOG_FILE}"
    log_summary ""

    local total=0
    local passed=0
    local failed=0

    for service in "Qdrant" "Neo4j" "Redis"; do
        local status_var="BACKUP_STATUS_${service^^}"
        if [ "${!status_var:-}" == "success" ]; then
            passed=$((passed + 1))
        else
            failed=$((failed + 1))
        fi
        total=$((total + 1))
    done

    log_summary "Results: ${passed}/${total} succeeded, ${failed}/${total} failed"
    log_summary ""

    if [ $failed -gt 0 ]; then
        log_summary "WARNING: ${failed} backup(s) failed. Check ${LOG_FILE} for details."
    else
        log_summary "All backups completed successfully."
    fi

    log_summary "=========================================="

    # Copy summary to main log
    cat "$SUMMARY_FILE" >> "$LOG_FILE"
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    log "=== Backup Cron started (run: ${RUN_ID}) ==="

    acquire_lock
    trap release_lock EXIT INT TERM

    validate_env

    # Export shared env vars for child scripts
    export BACKUP_BUCKET S3_ENDPOINT AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
    export RETENTION_DAYS LOG_DIR

    BACKUP_STATUS_QDRANT="skipped"
    BACKUP_STATUS_NEO4J="skipped"
    BACKUP_STATUS_REDIS="skipped"

    # ── Qdrant ─────────────────────────────────────────────────────────────
    if [ "${SKIP_QDRANT:-}" != "true" ]; then
        if run_backup "Qdrant" "${BACKUP_SCRIPTS_DIR}/backup_qdrant.sh"; then
            BACKUP_STATUS_QDRANT="success"
        else
            BACKUP_STATUS_QDRANT="failed"
        fi
    else
        log "Skipping Qdrant backup (SKIP_QDRANT=true)"
        log_summary "  Status: SKIPPED"
    fi

    # ── Neo4j ──────────────────────────────────────────────────────────────
    if [ "${SKIP_NEO4J:-}" != "true" ]; then
        if run_backup "Neo4j" "${BACKUP_SCRIPTS_DIR}/backup_neo4j.sh"; then
            BACKUP_STATUS_NEO4J="success"
        else
            BACKUP_STATUS_NEO4J="failed"
        fi
    else
        log "Skipping Neo4j backup (SKIP_NEO4J=true)"
        log_summary "  Status: SKIPPED"
    fi

    # ── Redis ──────────────────────────────────────────────────────────────
    if [ "${SKIP_REDIS:-}" != "true" ]; then
        if run_backup "Redis" "${BACKUP_SCRIPTS_DIR}/backup_redis.sh"; then
            BACKUP_STATUS_REDIS="success"
        else
            BACKUP_STATUS_REDIS="failed"
        fi
    else
        log "Skipping Redis backup (SKIP_REDIS=true)"
        log_summary "  Status: SKIPPED"
    fi

    generate_summary

    log "=== Backup Cron completed (run: ${RUN_ID}) ==="
}

main "$@"
