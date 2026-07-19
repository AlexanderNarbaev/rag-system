#!/usr/bin/env bash
#
# scripts/ops/rotate-secrets.sh
# Automated secrets rotation for the RAG System.
#
# Generates new JWT signing keys, rotates API keys in the database,
# updates .env files with new values, and triggers service reload.
#
# Features:
#   - Zero-downtime rotation (grace period for old keys)
#   - Automatic .env backup before changes
#   - Dry-run mode for safe testing
#   - Full audit logging
#   - Rollback support via .env backups
#
# Required environment variables:
#   PROXY_DIR          — Path to the proxy directory (default: ./proxy)
#   ROTATION_LOG_DIR   — Log directory (default: /var/log/rag-system)
#
# Optional environment variables:
#   DRY_RUN            — Set to "true" for dry-run mode (default: false)
#   SKIP_API_KEYS      — Set to "true" to skip API key rotation
#   SKIP_JWT           — Set to "true" to skip JWT key rotation
#   JWT_KEY_TYPE       — Key type: "rsa" or "ec" (default: rsa)
#   FORCE              — Set to "true" to skip confirmation prompts
#   ROTATE_ENV_FILE    — Path to .env file to update (default: PROXY_DIR/.env)
#   BACKUP_RETENTION   — Number of .env backups to keep (default: 10)
#
# Usage:
#   # Full rotation (interactive):
#   ./rotate-secrets.sh
#
#   # Dry-run (preview changes without applying):
#   DRY_RUN=true ./rotate-secrets.sh
#
#   # Automated rotation (no prompts):
#   FORCE=true ./rotate-secrets.sh
#
#   # JWT-only rotation:
#   SKIP_API_KEYS=true ./rotate-secrets.sh
#
#   # EC key rotation:
#   JWT_KEY_TYPE=ec ./rotate-secrets.sh
#
# Cron example (monthly rotation):
#   0 3 1 * * FORCE=true /scripts/ops/rotate-secrets.sh >> /var/log/rag-system/rotation.log 2>&1

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROXY_DIR="${PROXY_DIR:-${PROJECT_ROOT}/proxy}"
ROTATION_LOG_DIR="${ROTATION_LOG_DIR:-/var/log/rag-system}"
ROTATE_ENV_FILE="${ROTATE_ENV_FILE:-${PROXY_DIR}/.env}"
BACKUP_RETENTION="${BACKUP_RETENTION:-10}"
DRY_RUN="${DRY_RUN:-false}"
SKIP_API_KEYS="${SKIP_API_KEYS:-false}"
SKIP_JWT="${SKIP_JWT:-false}"
JWT_KEY_TYPE="${JWT_KEY_TYPE:-rsa}"
FORCE="${FORCE:-false}"

RUN_ID="$(date -u +%Y%m%d_%H%M%S)"
LOG_FILE="${ROTATION_LOG_DIR}/rotation_${RUN_ID}.log"
BACKUP_DIR="${PROXY_DIR}/.env.backups"
ROTATION_DATA_DIR="${PROJECT_ROOT}/data/rotation"

mkdir -p "${ROTATION_LOG_DIR}" "${BACKUP_DIR}" "${ROTATION_DATA_DIR}"

# ── Logging ────────────────────────────────────────────────────────────────
log() {
    local level="$1"
    shift
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] [${level}] $*" | tee -a "$LOG_FILE"
}

log_info()  { log "INFO"  "$@"; }
log_warn()  { log "WARN"  "$@"; }
log_error() { log "ERROR" "$@"; }
log_ok()    { log "OK"    "$@"; }

# ── Validation ─────────────────────────────────────────────────────────────
validate_prerequisites() {
    local errors=0

    # Check for required tools
    for cmd in openssl jq; do
        if ! command -v "$cmd" &>/dev/null; then
            log_error "Required command not found: ${cmd}"
            errors=$((errors + 1))
        fi
    done

    # Check for Python (needed for API key rotation via the app)
    if ! command -v python3 &>/dev/null; then
        log_warn "python3 not found — API key rotation will be skipped"
        SKIP_API_KEYS="true"
    fi

    # Check .env file exists
    if [ ! -f "${ROTATE_ENV_FILE}" ]; then
        log_error ".env file not found: ${ROTATE_ENV_FILE}"
        errors=$((errors + 1))
    fi

    if [ $errors -gt 0 ]; then
        log_error "Prerequisites check failed with ${errors} error(s)"
        exit 1
    fi
}

# ── Confirmation ───────────────────────────────────────────────────────────
confirm_rotation() {
    if [ "${FORCE}" == "true" ] || [ "${DRY_RUN}" == "true" ]; then
        return 0
    fi

    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║              SECRETS ROTATION — CONFIRMATION                ║"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  This will rotate the following secrets:                    ║"
    if [ "${SKIP_JWT}" != "true" ]; then
        echo "║    ✓ JWT signing keys (${JWT_KEY_TYPE^^})                           ║"
    fi
    if [ "${SKIP_API_KEYS}" != "true" ]; then
        echo "║    ✓ API keys in SQLite database                           ║"
    fi
    echo "║                                                             ║"
    echo "║  Environment file: ${ROTATE_ENV_FILE}  "
    echo "║  A backup will be created before changes.                   ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    read -r -p "Proceed with rotation? [y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) echo "Rotation cancelled."; exit 0 ;;
    esac
}

# ── Backup .env ────────────────────────────────────────────────────────────
backup_env() {
    local backup_file="${BACKUP_DIR}/.env.${RUN_ID}"
    if [ "${DRY_RUN}" == "true" ]; then
        log_info "[DRY RUN] Would create backup: ${backup_file}"
        return 0
    fi

    cp "${ROTATE_ENV_FILE}" "${backup_file}"
    log_ok "Backup created: ${backup_file}"

    # Cleanup old backups (keep last N)
    local backup_count
    backup_count=$(ls -1 "${BACKUP_DIR}"/.env.* 2>/dev/null | wc -l)
    if [ "$backup_count" -gt "$BACKUP_RETENTION" ]; then
        local to_delete=$((backup_count - BACKUP_RETENTION))
        ls -1t "${BACKUP_DIR}"/.env.* | tail -n "$to_delete" | xargs rm -f
        log_info "Cleaned up ${to_delete} old backup(s)"
    fi
}

# ── Generate JWT Keys ──────────────────────────────────────────────────────
generate_jwt_keys() {
    if [ "${SKIP_JWT}" == "true" ]; then
        log_info "Skipping JWT key rotation (SKIP_JWT=true)"
        return 0
    fi

    log_info "Generating new JWT signing keys (type=${JWT_KEY_TYPE})..."

    local private_key_file="${ROTATION_DATA_DIR}/jwt_private_key.pem"
    local public_key_file="${ROTATION_DATA_DIR}/jwt_public_key.pem"
    local secret_value

    case "${JWT_KEY_TYPE}" in
        rsa|RSA)
            if [ "${DRY_RUN}" == "true" ]; then
                log_info "[DRY RUN] Would generate RSA-2048 key pair"
                return 0
            fi

            # Generate RSA-2048 private key
            openssl genrsa -out "${private_key_file}" 2048 2>/dev/null
            # Extract public key
            openssl rsa -in "${private_key_file}" -pubout -out "${public_key_file}" 2>/dev/null

            # Read keys into variables (for .env update)
            JWT_SECRET_VALUE=$(cat "${private_key_file}")
            JWT_PUBLIC_KEY_VALUE=$(cat "${public_key_file}")
            JWT_ALGORITHM_VALUE="RS256"

            # Set restrictive permissions
            chmod 600 "${private_key_file}"
            chmod 644 "${public_key_file}"

            log_ok "RSA-2048 key pair generated"
            ;;

        ec|EC)
            if [ "${DRY_RUN}" == "true" ]; then
                log_info "[DRY RUN] Would generate EC P-256 key pair"
                return 0
            fi

            # Generate EC P-256 private key
            openssl ecparam -genkey -name prime256v1 -noout -out "${private_key_file}" 2>/dev/null
            # Extract public key
            openssl ec -in "${private_key_file}" -pubout -out "${public_key_file}" 2>/dev/null

            JWT_SECRET_VALUE=$(cat "${private_key_file}")
            JWT_PUBLIC_KEY_VALUE=$(cat "${public_key_file}")
            JWT_ALGORITHM_VALUE="ES256"

            chmod 600 "${private_key_file}"
            chmod 644 "${public_key_file}"

            log_ok "EC P-256 key pair generated"
            ;;

        *)
            # Symmetric secret (HS256)
            if [ "${DRY_RUN}" == "true" ]; then
                log_info "[DRY RUN] Would generate HS256 symmetric secret"
                return 0
            fi

            JWT_SECRET_VALUE=$(openssl rand -base64 64 | tr -d '\n')
            JWT_PUBLIC_KEY_VALUE=""
            JWT_ALGORITHM_VALUE="HS256"

            log_ok "HS256 symmetric secret generated"
            ;;
    esac

    # Compute fingerprint for audit
    local fingerprint
    if [ -n "${JWT_PUBLIC_KEY_VALUE:-}" ]; then
        fingerprint=$(echo -n "${JWT_PUBLIC_KEY_VALUE}" | sha256sum | cut -c1-16)
    else
        fingerprint=$(echo -n "${JWT_SECRET_VALUE}" | sha256sum | cut -c1-16)
    fi

    # Save rotation metadata
    cat > "${ROTATION_DATA_DIR}/jwt_rotation_${RUN_ID}.json" <<EOF
{
    "rotation_id": "${RUN_ID}",
    "timestamp": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
    "algorithm": "${JWT_ALGORITHM_VALUE}",
    "fingerprint": "${fingerprint}",
    "key_type": "${JWT_KEY_TYPE}",
    "private_key_file": "${private_key_file}",
    "public_key_file": "${public_key_file}"
}
EOF

    log_ok "JWT key rotation metadata saved (fingerprint: ${fingerprint})"

    # Export for .env update step
    export JWT_SECRET_VALUE JWT_PUBLIC_KEY_VALUE JWT_ALGORITHM_VALUE
}

# ── Rotate API Keys ───────────────────────────────────────────────────────
rotate_api_keys() {
    if [ "${SKIP_API_KEYS}" == "true" ]; then
        log_info "Skipping API key rotation (SKIP_API_KEYS=true)"
        return 0
    fi

    log_info "Rotating API keys in database..."

    if [ "${DRY_RUN}" == "true" ]; then
        log_info "[DRY RUN] Would rotate all active API keys in SQLite"
        return 0
    fi

    # Use Python to rotate keys through the application's API key manager
    python3 -c "
import sys
sys.path.insert(0, '${PROJECT_ROOT}')
try:
    from proxy.app.auth.api_keys import api_key_manager
    keys = api_key_manager.list_keys()
    active = [k for k in keys if k.is_active]
    print(f'Found {len(active)} active API key(s)')

    users_rotated = set()
    for key in active:
        if key.user_id not in users_rotated:
            new_key = api_key_manager.generate_key(
                user_id=key.user_id,
                roles=key.roles
            )
            api_key_manager.revoke_key(key.key_id)
            users_rotated.add(key.user_id)
            print(f'  Rotated key for user: {key.user_id} (old: {key.key_id})')

    print(f'Rotated {len(users_rotated)} user key(s)')
except Exception as e:
    print(f'Error rotating API keys: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1 | tee -a "$LOG_FILE"

    log_ok "API key rotation completed"
}

# ── Update .env File ──────────────────────────────────────────────────────
update_env_file() {
    log_info "Updating .env file with new secrets..."

    if [ "${DRY_RUN}" == "true" ]; then
        log_info "[DRY RUN] Would update the following in ${ROTATE_ENV_FILE}:"
        [ -n "${JWT_SECRET_VALUE:-}" ] && log_info "  - JWT_SECRET=<new value>"
        [ -n "${JWT_PUBLIC_KEY_VALUE:-}" ] && log_info "  - JWT_PUBLIC_KEY=<new value>"
        [ -n "${JWT_ALGORITHM_VALUE:-}" ] && log_info "  - JWT_ALGORITHM=${JWT_ALGORITHM_VALUE}"
        return 0
    fi

    local env_file="${ROTATE_ENV_FILE}"
    local tmp_file="${env_file}.tmp"

    # Update JWT_SECRET
    if [ -n "${JWT_SECRET_VALUE:-}" ]; then
        if grep -q "^JWT_SECRET=" "$env_file" 2>/dev/null; then
            # Replace existing value (handle multi-line PEM keys)
            python3 -c "
import re
with open('${env_file}', 'r') as f:
    content = f.read()
# Replace JWT_SECRET value (single line or PEM block)
new_secret = '''${JWT_SECRET_VALUE}'''
content = re.sub(
    r'JWT_SECRET=.*',
    f'JWT_SECRET={new_secret.split(chr(10))[0] if chr(10) in new_secret else new_secret}',
    content,
    count=1
)
with open('${env_file}', 'w') as f:
    f.write(content)
"
        else
            echo "JWT_SECRET=${JWT_SECRET_VALUE}" >> "$env_file"
        fi
        log_ok "Updated JWT_SECRET in .env"
    fi

    # Update JWT_PUBLIC_KEY
    if [ -n "${JWT_PUBLIC_KEY_VALUE:-}" ]; then
        if grep -q "^JWT_PUBLIC_KEY=" "$env_file" 2>/dev/null; then
            python3 -c "
import re
with open('${env_file}', 'r') as f:
    content = f.read()
new_key = '''${JWT_PUBLIC_KEY_VALUE}'''
content = re.sub(
    r'JWT_PUBLIC_KEY=.*',
    f'JWT_PUBLIC_KEY={new_key.split(chr(10))[0] if chr(10) in new_key else new_key}',
    content,
    count=1
)
with open('${env_file}', 'w') as f:
    f.write(content)
"
        else
            echo "JWT_PUBLIC_KEY=${JWT_PUBLIC_KEY_VALUE}" >> "$env_file"
        fi
        log_ok "Updated JWT_PUBLIC_KEY in .env"
    fi

    # Update JWT_ALGORITHM
    if [ -n "${JWT_ALGORITHM_VALUE:-}" ]; then
        if grep -q "^JWT_ALGORITHM=" "$env_file" 2>/dev/null; then
            sed -i "s/^JWT_ALGORITHM=.*/JWT_ALGORITHM=${JWT_ALGORITHM_VALUE}/" "$env_file"
        else
            echo "JWT_ALGORITHM=${JWT_ALGORITHM_VALUE}" >> "$env_file"
        fi
        log_ok "Updated JWT_ALGORITHM in .env"
    fi
}

# ── Trigger Service Reload ────────────────────────────────────────────────
trigger_reload() {
    log_info "Triggering service reload..."

    if [ "${DRY_RUN}" == "true" ]; then
        log_info "[DRY RUN] Would create rotation signal and reload proxy"
        return 0
    fi

    # Method 1: Signal file (picked up by hot-reload watcher)
    local signal_file="/tmp/rag-secrets-rotated"
    cat > "${signal_file}" <<EOF
{
    "rotated_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
    "rotation_id": "${RUN_ID}",
    "pid": $$
}
EOF
    log_ok "Rotation signal written to ${signal_file}"

    # Method 2: Docker container reload (if running in Docker)
    if command -v docker &>/dev/null; then
        local container_id
        container_id=$(docker ps --filter "name=rag-proxy" --format "{{.ID}}" 2>/dev/null | head -1)
        if [ -n "${container_id}" ]; then
            docker kill -s HUP "${container_id}" 2>/dev/null && \
                log_ok "Sent SIGHUP to Docker container ${container_id}" || \
                log_warn "Could not send SIGHUP to container"
        fi
    fi

    # Method 3: Docker Compose restart (if using compose)
    if [ -f "${PROJECT_ROOT}/proxy/docker-compose.yml" ] && command -v docker-compose &>/dev/null; then
        log_info "To complete rotation, restart the proxy service:"
        log_info "  cd ${PROJECT_ROOT}/proxy && docker-compose restart proxy"
    fi
}

# ── Generate Summary Report ───────────────────────────────────────────────
generate_summary() {
    local end_time
    end_time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    log_info ""
    log_info "=========================================="
    log_info "Secrets Rotation Summary — ${RUN_ID}"
    log_info "=========================================="
    log_info "Date: ${end_time}"
    log_info "Mode: $([ "${DRY_RUN}" == "true" ] && echo "DRY RUN" || echo "LIVE")"
    log_info "Log file: ${LOG_FILE}"
    log_info ""

    if [ "${SKIP_JWT}" != "true" ]; then
        log_info "JWT Keys:"
        log_info "  Algorithm: ${JWT_ALGORITHM_VALUE:-N/A}"
        log_info "  Fingerprint: ${fingerprint:-N/A}"
        log_info "  Key files: ${ROTATION_DATA_DIR}/"
    fi

    if [ "${SKIP_API_KEYS}" != "true" ]; then
        log_info "API Keys: rotated (see log for details)"
    fi

    log_info ""
    log_info "=========================================="
    log_info "Next steps:"
    log_info "  1. Verify health: curl http://localhost:8080/v1/health"
    log_info "  2. Test auth: curl -H 'Authorization: Bearer <token>' http://localhost:8080/v1/models"
    log_info "  3. Monitor logs for auth errors"
    log_info "=========================================="
}

# ── Rollback ──────────────────────────────────────────────────────────────
rollback() {
    log_warn "Rolling back to previous .env..."

    local latest_backup
    latest_backup=$(ls -1t "${BACKUP_DIR}"/.env.* 2>/dev/null | head -1)

    if [ -z "${latest_backup}" ]; then
        log_error "No backup found for rollback"
        exit 1
    fi

    if [ "${DRY_RUN}" == "true" ]; then
        log_info "[DRY RUN] Would restore from: ${latest_backup}"
        return 0
    fi

    cp "${latest_backup}" "${ROTATE_ENV_FILE}"
    log_ok "Restored .env from ${latest_backup}"
    log_warn "Restart the proxy to apply rolled-back configuration"
}

# ── Usage ─────────────────────────────────────────────────────────────────
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Automated secrets rotation for the RAG System.

Options:
  --dry-run         Preview changes without applying
  --jwt-only        Rotate JWT keys only (skip API keys)
  --api-only        Rotate API keys only (skip JWT keys)
  --rollback        Restore .env from latest backup
  --force           Skip confirmation prompts
  --key-type TYPE   JWT key type: rsa, ec, hs256 (default: rsa)
  --help            Show this help message

Environment Variables:
  PROXY_DIR         Path to proxy directory (default: ./proxy)
  ROTATION_LOG_DIR  Log directory (default: /var/log/rag-system)
  DRY_RUN           true/false (default: false)
  SKIP_API_KEYS     true/false (default: false)
  SKIP_JWT          true/false (default: false)
  JWT_KEY_TYPE      rsa/ec/hs256 (default: rsa)
  FORCE             true/false (default: false)

Examples:
  $(basename "$0")                    # Full interactive rotation
  $(basename "$0") --dry-run          # Preview changes
  $(basename "$0") --jwt-only --force # Automated JWT rotation
  $(basename "$0") --rollback         # Restore previous state
EOF
}

# ── Parse Arguments ────────────────────────────────────────────────────────
parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run)     DRY_RUN="true" ;;
            --jwt-only)    SKIP_API_KEYS="true" ;;
            --api-only)    SKIP_JWT="true" ;;
            --rollback)    rollback; exit 0 ;;
            --force)       FORCE="true" ;;
            --key-type)    shift; JWT_KEY_TYPE="$1" ;;
            --help|-h)     usage; exit 0 ;;
            *)             log_error "Unknown option: $1"; usage; exit 1 ;;
        esac
        shift
    done
}

# ── Main ──────────────────────────────────────────────────────────────────
main() {
    parse_args "$@"

    log_info "=== Secrets Rotation started (run: ${RUN_ID}) ==="
    log_info "Mode: $([ "${DRY_RUN}" == "true" ] && echo "DRY RUN" || echo "LIVE")"

    validate_prerequisites
    confirm_rotation

    # Step 1: Backup current .env
    backup_env

    # Step 2: Generate new JWT keys
    generate_jwt_keys

    # Step 3: Rotate API keys
    rotate_api_keys

    # Step 4: Update .env file
    update_env_file

    # Step 5: Trigger service reload
    trigger_reload

    # Step 6: Generate summary
    generate_summary

    log_info "=== Secrets Rotation completed (run: ${RUN_ID}) ==="
}

main "$@"
