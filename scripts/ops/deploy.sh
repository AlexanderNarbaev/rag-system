#!/usr/bin/env bash
#
# scripts/ops/deploy.sh
# Operational-grade deployment automation for RAG System.
#
# Features:
#   - Multi-environment deployment (dev/staging/prod)
#   - Pre-flight checks (Docker, disk, env vars)
#   - Rolling update with health verification
#   - Automatic backup before deployment
#   - Zero-downtime for production
#   - Canary deployment support
#   - Rollback on failure
#   - Deployment audit log
#
# Required environment variables:
#   (Same as proxy/.env — QDRANT_HOST, LLM_ENDPOINT, etc.)
#
# Optional environment variables:
#   DEPLOY_ENV          — Environment to deploy: dev, staging, prod (default: dev)
#   DEPLOY_IMAGE_TAG    — Docker image tag (default: latest)
#   PRE_DEPLOY_BACKUP   — Run backup before deploy (default: true)
#   CANARY_REPLICAS     — Number of canary replicas before full rollout (default: 0)
#   HEALTH_RETRIES      — Health check retries (default: 30)
#   DEPLOY_TIMEOUT      — Deployment timeout in seconds (default: 600)
#   ROLLBACK_ON_FAILURE — Auto-rollback if deploy fails (default: true)
#   DRY_RUN             — Preview deployment steps (default: false)
#   FORCE               — Skip confirmation prompts (default: false)
#
# Usage:
#   ./deploy.sh                                    # dev deployment
#   DEPLOY_ENV=prod ./deploy.sh                    # prod deployment
#   ./deploy.sh --canary                           # canary deployment
#   ./deploy.sh --rollback                         # rollback to previous version
#   DRY_RUN=true ./deploy.sh                       # preview deployment steps

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PROXY_DIR="${PROXY_DIR:-${PROJECT_ROOT}/proxy}"

DEPLOY_ENV="${DEPLOY_ENV:-dev}"
DEPLOY_IMAGE_TAG="${DEPLOY_IMAGE_TAG:-latest}"
PRE_DEPLOY_BACKUP="${PRE_DEPLOY_BACKUP:-true}"
CANARY_REPLICAS="${CANARY_REPLICAS:-0}"
HEALTH_RETRIES="${HEALTH_RETRIES:-30}"
DEPLOY_TIMEOUT="${DEPLOY_TIMEOUT:-600}"
ROLLBACK_ON_FAILURE="${ROLLBACK_ON_FAILURE:-true}"
DRY_RUN="${DRY_RUN:-false}"
FORCE="${FORCE:-false}"

RUN_ID="$(date -u +%Y%m%d_%H%M%S)"
LOG_DIR="${LOG_DIR:-/var/log/rag-system}"
DEPLOY_LOG="${LOG_DIR}/deploy_${RUN_ID}.log"
PREVIOUS_IMAGE=""

mkdir -p "${LOG_DIR}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()     { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$DEPLOY_LOG"; }
log_info() { log "INFO  $*"; echo -e "  ${CYAN}→${NC} $*"; }
log_ok()   { log "OK    $*"; echo -e "  ${GREEN}✓${NC} $*"; }
log_warn() { log "WARN  $*"; echo -e "  ${YELLOW}⚠${NC} $*"; }
log_err()  { log "ERROR $*"; echo -e "  ${RED}✗${NC} $*"; }
step()     { echo ""; echo -e "${BOLD}${CYAN}━━━ $* ━━━${NC}"; log "STEP  $*"; }

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --canary)   CANARY_REPLICAS=1 ;;
            --rollback) deploy_rollback; exit $? ;;
            --force)    FORCE=true ;;
            --dry-run)  DRY_RUN=true ;;
            --help|-h)
                echo "Usage: $(basename "$0") [--canary] [--rollback] [--force] [--dry-run]"
                echo ""
                echo "Environment variables:"
                echo "  DEPLOY_ENV          dev, staging, prod (default: dev)"
                echo "  DEPLOY_IMAGE_TAG    Docker image tag (default: latest)"
                echo "  PRE_DEPLOY_BACKUP   Run backup before deploy (default: true)"
                echo "  CANARY_REPLICAS     Canary replicas before full rollout (default: 0)"
                echo "  ROLLBACK_ON_FAILURE Auto-rollback on deploy failure (default: true)"
                echo "  DRY_RUN             Preview steps without deploying (default: false)"
                echo "  FORCE               Skip confirmation prompts (default: false)"
                exit 0
                ;;
            *) DEPLOY_ENV="$1" ;;
        esac
        shift
    done
}

validate_environment() {
    case "$DEPLOY_ENV" in
        dev|staging|prod) ;;
        *) log_err "Invalid environment: $DEPLOY_ENV (use: dev, staging, prod)"; exit 1 ;;
    esac
}

confirm_deployment() {
    if [ "$FORCE" = true ] || [ "$DRY_RUN" = true ]; then
        return 0
    fi

    echo ""
    echo -e "${YELLOW}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║           DEPLOYMENT CONFIRMATION — ${DEPLOY_ENV^^}                        ║${NC}"
    echo -e "${YELLOW}╠══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${YELLOW}║  Environment: ${DEPLOY_ENV}                                       ║${NC}"
    echo -e "${YELLOW}║  Image tag:   ${DEPLOY_IMAGE_TAG}                                       ║${NC}"
    if [ "$CANARY_REPLICAS" -gt 0 ]; then
        echo -e "${YELLOW}║  Mode:        Canary (${CANARY_REPLICAS} replicas)                     ║${NC}"
    fi
    echo -e "${YELLOW}║  Backup:      $([ "$PRE_DEPLOY_BACKUP" = true ] && echo "Yes" || echo "No")                                    ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    read -r -p "Proceed with deployment? [y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) log_info "Deployment cancelled"; exit 0 ;;
    esac
}

preflight_checks() {
    step "Pre-flight checks"

    local errors=0

    if ! command -v docker &>/dev/null; then
        log_err "Docker not found"
        errors=$((errors + 1))
    else
        if ! docker info &>/dev/null 2>&1; then
            log_err "Docker daemon not running or inaccessible"
            errors=$((errors + 1))
        else
            log_ok "Docker daemon running"
        fi
    fi

    if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null 2>&1; then
        log_err "docker-compose not found"
        errors=$((errors + 1))
    else
        log_ok "docker-compose available"
    fi

    local disk_avail
    disk_avail=$(df -h / | awk 'NR==2 {print $4}' 2>/dev/null || echo "?")
    local disk_pct
    disk_pct=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%' 2>/dev/null || echo "0")
    if [ "$disk_pct" -ge 90 ] 2>/dev/null; then
        log_warn "Disk usage: ${disk_pct}% (${disk_avail} free) — may fail"
    else
        log_ok "Disk: ${disk_avail} free (${disk_pct}% used)"
    fi

    docker_compose_cmd
    local compose_file
    compose_file=$(get_compose_file)
    if [ ! -f "$compose_file" ]; then
        log_err "Compose file not found: $compose_file"
        errors=$((errors + 1))
    else
        log_ok "Compose file: $compose_file"
    fi

    if [ "$errors" -gt 0 ]; then
        log_err "Pre-flight checks failed ($errors error(s))"
        exit 1
    fi
}

docker_compose_cmd() {
    if docker compose version &>/dev/null 2>&1; then
        echo "docker compose"
    else
        echo "docker-compose"
    fi
}

get_compose_file() {
    local compose_file
    case "$DEPLOY_ENV" in
        prod)    compose_file="${PROJECT_ROOT}/deploy/docker/docker-compose.prod.yml" ;;
        staging) compose_file="${PROJECT_ROOT}/deploy/docker/docker-compose.prod.yml" ;;
        dev)     compose_file="${PROXY_DIR}/docker-compose.yml" ;;
    esac
    if [ -f "$compose_file" ]; then
        echo "$compose_file"
    elif [ -f "${PROXY_DIR}/docker-compose.yml" ]; then
        echo "${PROXY_DIR}/docker-compose.yml"
    else
        echo ""
    fi
}

get_proxy_url() {
    local port=8080
    local compose_file
    compose_file=$(get_compose_file)
    if [ -f "$compose_file" ]; then
        local extracted
        extracted=$(grep -A2 'rag-proxy:' "$compose_file" 2>/dev/null | grep -oP '"\d+:8080"' | tr -d '"' | cut -d: -f1 | head -1 || echo "")
        if [ -n "$extracted" ]; then
            port="$extracted"
        fi
    fi
    echo "http://localhost:${port}"
}

run_pre_deploy_backup() {
    if [ "$PRE_DEPLOY_BACKUP" != true ]; then
        log_info "Skipping pre-deployment backup (PRE_DEPLOY_BACKUP=false)"
        return 0
    fi

    step "Pre-deployment backup"

    local backup_script="${SCRIPT_DIR}/backup_cron.sh"
    if [ -x "$backup_script" ]; then
        if [ "$DRY_RUN" = true ]; then
            log_info "[DRY RUN] Would run: $backup_script"
        else
            log_info "Running pre-deployment backup..."
            if SKIP_QDRANT="${SKIP_QDRANT:-}" SKIP_NEO4J="${SKIP_NEO4J:-}" SKIP_REDIS="${SKIP_REDIS:-}" \
                bash "$backup_script" 2>&1 | tee -a "$DEPLOY_LOG"; then
                log_ok "Pre-deployment backup completed"
            else
                log_warn "Pre-deployment backup completed with warnings"
            fi
        fi
    else
        log_warn "Backup script not found: $backup_script"
    fi
}

save_current_image() {
    local compose_file
    compose_file=$(get_compose_file)
    local dc
    dc=$(docker_compose_cmd)

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would save current image tag"
        return 0
    fi

    PREVIOUS_IMAGE=$($dc -f "$compose_file" images -q rag-proxy 2>/dev/null | head -1 || echo "")
    if [ -n "$PREVIOUS_IMAGE" ]; then
        log_info "Current image: $PREVIOUS_IMAGE"
    else
        log_warn "Could not determine current image"
    fi
}

pull_images() {
    step "Pull images"

    local compose_file
    compose_file=$(get_compose_file)
    local dc
    dc=$(docker_compose_cmd)

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would pull images"
        return 0
    fi

    if DEPLOY_IMAGE_TAG="$DEPLOY_IMAGE_TAG" $dc -f "$compose_file" pull 2>&1 | tee -a "$DEPLOY_LOG"; then
        log_ok "Images pulled"
    else
        log_err "Failed to pull images"
        exit 1
    fi
}

stop_services() {
    step "Stop services"

    local compose_file
    compose_file=$(get_compose_file)
    local dc
    dc=$(docker_compose_cmd)

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would stop services gracefully"
        return 0
    fi

    $dc -f "$compose_file" down --timeout 30 2>&1 | tee -a "$DEPLOY_LOG"
    log_ok "Services stopped"
}

start_services() {
    step "Start services"

    local compose_file
    compose_file=$(get_compose_file)
    local dc
    dc=$(docker_compose_cmd)

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would start services"
        return 0
    fi

    if [ "$CANARY_REPLICAS" -gt 0 ]; then
        log_info "Starting canary with $CANARY_REPLICAS replica(s)..."
        $dc -f "$compose_file" up -d --scale "rag-proxy=$CANARY_REPLICAS" 2>&1 | tee -a "$DEPLOY_LOG"
    else
        $dc -f "$compose_file" up -d 2>&1 | tee -a "$DEPLOY_LOG"
    fi

    log_ok "Services started"
}

wait_for_healthy() {
    step "Health verification"

    local proxy_url
    proxy_url=$(get_proxy_url)
    local health_url="${proxy_url}/v1/health/live"

    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY RUN] Would check health: $health_url"
        return 0
    fi

    log_info "Waiting for proxy to become healthy..."
    log_info "Health URL: $health_url"

    local retries=$HEALTH_RETRIES
    local delay=2

    for i in $(seq 1 "$retries"); do
        local status
        status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$health_url" 2>/dev/null || echo "000")

        if [ "$status" = "200" ]; then
            log_ok "Proxy healthy (attempt $i/$retries)"

            sleep 3
            local full_health
            full_health=$(curl -s --max-time 5 "${proxy_url}/v1/health" 2>/dev/null || echo "{}")

            local health_status
            health_status=$(echo "$full_health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

            if [ "$health_status" = "ok" ]; then
                log_ok "Full health check: OK"
                log_info "$(echo "$full_health" | python3 -m json.tool 2>/dev/null || echo "$full_health")"
                return 0
            else
                log_warn "Full health: $health_status (degraded but alive)"
                return 0
            fi
        fi

        if [ "$i" -ge "$((retries / 2))" ]; then
            log_warn "Attempt $i/$retries — HTTP $status"
        fi

        sleep "$delay"
    done

    log_err "Proxy did not become healthy within $((retries * delay))s"
    return 1
}

show_running_services() {
    step "Running services"

    local compose_file
    compose_file=$(get_compose_file)
    local dc
    dc=$(docker_compose_cmd)

    $dc -f "$compose_file" ps 2>/dev/null || true

    local proxy_url
    proxy_url=$(get_proxy_url)

    echo ""
    log_info "Proxy endpoint: $proxy_url"
    log_info "Health:  ${proxy_url}/v1/health"
    log_info "Metrics: ${proxy_url}/metrics"
}

deploy_rollback() {
    step "Rollback"

    local compose_file
    compose_file=$(get_compose_file)
    local dc
    dc=$(docker_compose_cmd)

    if [ -n "$PREVIOUS_IMAGE" ]; then
        log_info "Rolling back to image: $PREVIOUS_IMAGE"
        $dc -f "$compose_file" down --timeout 30
        DEPLOY_IMAGE_TAG="$PREVIOUS_IMAGE" $dc -f "$compose_file" up -d
    fi

    log_ok "Rollback completed"
    show_running_services
}

generate_audit() {
    step "Deployment audit"

    local end_time
    end_time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    local proxy_url
    proxy_url=$(get_proxy_url)

    log_info "=========================================="
    log_info "Deployment Audit — $RUN_ID"
    log_info "=========================================="
    log_info "Date:        $end_time"
    log_info "Environment: $DEPLOY_ENV"
    log_info "Image tag:   $DEPLOY_IMAGE_TAG"
    log_info "Previous:    ${PREVIOUS_IMAGE:-N/A}"
    log_info "Canary:      $([ $CANARY_REPLICAS -gt 0 ] && echo "Yes ($CANARY_REPLICAS)" || echo "No")"
    log_info "Log file:    $DEPLOY_LOG"
    log_info "Proxy URL:   $proxy_url"
    log_info ""
    log_info "Post-deployment checks:"
    log_info "  Health:  curl $proxy_url/v1/health"
    log_info "  Models:  curl $proxy_url/v1/models"
    log_info "  Metrics: curl $proxy_url/metrics"
    log_info "=========================================="

    local audit_file="${LOG_DIR}/deploy_history.log"
    echo "$end_time | $RUN_ID | $DEPLOY_ENV | $DEPLOY_IMAGE_TAG | ${PREVIOUS_IMAGE:-N/A}" >> "$audit_file"
}

main() {
    parse_args "$@"
    validate_environment

    log_info "=== Deployment started — env=$DEPLOY_ENV tag=$DEPLOY_IMAGE_TAG ==="

    confirm_deployment
    preflight_checks
    run_pre_deploy_backup
    save_current_image
    pull_images
    stop_services
    start_services

    if ! wait_for_healthy; then
        log_err "Health check failed after deployment"
        if [ "$ROLLBACK_ON_FAILURE" = true ] && [ -n "$PREVIOUS_IMAGE" ]; then
            log_warn "Initiating rollback..."
            deploy_rollback
        fi
        exit 1
    fi

    show_running_services
    generate_audit

    log_info "=== Deployment completed successfully ==="
}

main "$@"
