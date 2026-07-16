#!/usr/bin/env bash
#
# scripts/ops/health_check.sh
# Comprehensive health check for all RAG System infrastructure components.
#
# Checks connectivity, resource usage, and data integrity for:
#   - RAG Proxy
#   - Qdrant (HTTP API + collection status)
#   - Neo4j (Bolt connectivity + node count)
#   - Redis (PING + memory usage)
#   - LLM Backend (vLLM/llama.cpp health)
#   - MinIO (if configured)
#   - Disk space
#   - Memory usage
#   - Docker containers (if applicable)
#
# Exit codes:
#   0 — All healthy
#   1 — One or more warnings (degraded)
#   2 — One or more critical failures
#
# Usage:
#   ./health_check.sh
#   ./health_check.sh --json          # JSON output for automation
#   ./health_check.sh --quiet         # Only errors, exit code indicates health
#
# Cron example (every 5 minutes):
#   */5 * * * * /scripts/ops/health_check.sh --quiet || /scripts/ops/notify_on_failure.sh

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────────────────
QDRANT_HOST="${QDRANT_HOST:-localhost}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
COLLECTION_NAME="${COLLECTION_NAME:-knowledge_base}"
NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"
REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
LLM_ENDPOINT="${LLM_ENDPOINT:-http://localhost:8000/v1}"
PROXY_URL="${PROXY_URL:-http://localhost:8080}"
MINIO_URL="${MINIO_URL:-}"
DISK_THRESHOLD_PCT="${DISK_THRESHOLD_PCT:-85}"
MEMORY_THRESHOLD_PCT="${MEMORY_THRESHOLD_PCT:-90}"
LOG_DIR="${LOG_DIR:-/var/log/rag-system}"
RUN_ID="$(date -u +%Y%m%d_%H%M%S)"

mkdir -p "${LOG_DIR}"
HEALTH_LOG="${LOG_DIR}/health_check_$(date -u +%Y-%m-%d).log"

# ── Colors ──────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' CYAN='' BOLD='' NC=''
fi

# ── State ───────────────────────────────────────────────────────────────────
OUTPUT_JSON=false
QUIET=false
CRITICAL_COUNT=0
WARNING_COUNT=0
OK_COUNT=0
declare -A CHECK_RESULTS
declare -A CHECK_MESSAGES

# ── Helpers ─────────────────────────────────────────────────────────────────
log() {
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >> "$HEALTH_LOG"
}

ok()       { local msg="$1"; OK_COUNT=$((OK_COUNT + 1));           log "[OK]    $msg"; $QUIET || echo -e "  ${GREEN}✓${NC} $msg"; }
warn()     { local msg="$1"; WARNING_COUNT=$((WARNING_COUNT + 1));  log "[WARN]  $msg"; $QUIET || echo -e "  ${YELLOW}⚠${NC} $msg"; }
critical() { local msg="$1"; CRITICAL_COUNT=$((CRITICAL_COUNT + 1)); log "[CRIT]  $msg"; $QUIET || echo -e "  ${RED}✗${NC} $msg"; }

record() {
    local check="$1"
    local status="$2"
    local message="$3"
    CHECK_RESULTS["$check"]="$status"
    CHECK_MESSAGES["$check"]="$message"
}

http_get() {
    local url="$1"
    local timeout="${2:-5}"
    local code
    code=$(curl -s --max-time "$timeout" -o /dev/null -w "%{http_code}" "$url" 2>/dev/null) || true
    echo "${code:-000}"
}

http_get_body() {
    local url="$1"
    local timeout="${2:-5}"
    curl -s --max-time "$timeout" "$url" 2>/dev/null || true
}

# ── Parse arguments ─────────────────────────────────────────────────────────
parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --json)  OUTPUT_JSON=true ;;
            --quiet) QUIET=true ;;
            --help|-h)
                echo "Usage: $(basename "$0") [--json] [--quiet]"
                echo ""
                echo "Options:"
                echo "  --json    Output results as JSON"
                echo "  --quiet   Only output on failure, exit code indicates health"
                echo "  --help    Show this help"
                exit 0
                ;;
        esac
        shift
    done
}

# ── Check: Disk Space ───────────────────────────────────────────────────────
check_disk() {
    local mount="${1:-/}"
    local usage
    usage=$(df -h "$mount" 2>/dev/null | awk 'NR==2 {print $5}' | tr -d '%')
    local avail
    avail=$(df -h "$mount" 2>/dev/null | awk 'NR==2 {print $4}')

    if [ -z "$usage" ]; then
        warn "Disk: Cannot check $mount"
        record "disk" "warning" "Cannot determine disk usage for $mount"
        return
    fi

    if [ "$usage" -ge "${DISK_THRESHOLD_PCT}" ]; then
        warn "Disk: ${usage}% used on $mount (${avail} free) — threshold: ${DISK_THRESHOLD_PCT}%"
        record "disk" "warning" "${usage}% used on $mount, ${avail} free"
    else
        ok "Disk: ${usage}% used on $mount (${avail} free)"
        record "disk" "ok" "${usage}% used, ${avail} free"
    fi
}

# ── Check: Memory ───────────────────────────────────────────────────────────
check_memory() {
    local mem_total mem_used mem_avail mem_pct

    if [ -f /proc/meminfo ]; then
        mem_total=$(awk '/MemTotal/  {print $2}' /proc/meminfo)
        mem_avail=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
        mem_used=$((mem_total - mem_avail))
        mem_pct=$((mem_used * 100 / mem_total))
    elif command -v free &>/dev/null; then
        mem_total=$(free -b | awk '/Mem:/ {print $2}')
        mem_avail=$(free -b | awk '/Mem:/ {print $7}')
        mem_used=$((mem_total - mem_avail))
        mem_pct=$((mem_used * 100 / mem_total))
    else
        warn "Memory: Cannot determine usage"
        record "memory" "warning" "Cannot determine memory usage"
        return
    fi

    if [ "$mem_pct" -ge "${MEMORY_THRESHOLD_PCT}" ]; then
        warn "Memory: ${mem_pct}% used — threshold: ${MEMORY_THRESHOLD_PCT}%"
        record "memory" "warning" "${mem_pct}% used"
    else
        ok "Memory: ${mem_pct}% used"
        record "memory" "ok" "${mem_pct}% used"
    fi
}

# ── Check: RAG Proxy ────────────────────────────────────────────────────────
check_proxy() {
    local status_code
    status_code=$(http_get "${PROXY_URL}/v1/health/live" 5)

    if [ "$status_code" == "200" ]; then
        local health_body
        health_body=$(http_get_body "${PROXY_URL}/v1/health" 5)
        local health_status
        health_status=$(echo "$health_body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

        if [ "$health_status" == "ok" ]; then
            ok "Proxy: healthy (${PROXY_URL})"
            record "proxy" "ok" "healthy at ${PROXY_URL}"
        else
            warn "Proxy: degraded — status=${health_status}"
            record "proxy" "warning" "degraded: status=${health_status}"
        fi
    else
        critical "Proxy: unreachable (HTTP ${status_code})"
        record "proxy" "critical" "unreachable: HTTP ${status_code}"
    fi
}

# ── Check: Qdrant ───────────────────────────────────────────────────────────
check_qdrant() {
    local base_url="http://${QDRANT_HOST}:${QDRANT_PORT}"

    local health_code
    health_code=$(http_get "${base_url}/health" 5)

    if [ "$health_code" != "200" ]; then
        critical "Qdrant: unreachable (HTTP ${health_code})"
        record "qdrant" "critical" "unreachable: HTTP ${health_code}"
        return
    fi

    local coll_body
    coll_body=$(http_get_body "${base_url}/collections/${COLLECTION_NAME}" 5)
    local coll_status
    coll_status=$(echo "$coll_body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('status','unknown'))" 2>/dev/null || echo "unknown")

    local vectors_count
    vectors_count=$(echo "$coll_body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('vectors_count',0))" 2>/dev/null || echo "0")

    if [ "$coll_status" == "green" ]; then
        ok "Qdrant: healthy — ${COLLECTION_NAME}: ${vectors_count} vectors (${coll_status})"
        record "qdrant" "ok" "${vectors_count} vectors, status=${coll_status}"
    elif [ "$coll_status" == "yellow" ]; then
        warn "Qdrant: degraded — ${COLLECTION_NAME}: ${vectors_count} vectors (${coll_status})"
        record "qdrant" "warning" "${vectors_count} vectors, status=${coll_status}"
    else
        critical "Qdrant: unhealthy — ${COLLECTION_NAME} status=${coll_status}"
        record "qdrant" "critical" "status=${coll_status}"
    fi
}

# ── Check: Neo4j ────────────────────────────────────────────────────────────
check_neo4j() {
    if [ -z "${NEO4J_PASSWORD}" ]; then
        warn "Neo4j: skipped (NEO4J_PASSWORD not set)"
        record "neo4j" "skipped" "NEO4J_PASSWORD not set"
        return
    fi

    local bolt_host
    local bolt_port
    if [[ "$NEO4J_URI" =~ bolt://([^:]+):?([0-9]*)$ ]] || [[ "$NEO4J_URI" =~ bolt://([^/]+)/?$ ]]; then
        bolt_host="${BASH_REMATCH[1]}"
        bolt_port="${BASH_REMATCH[2]:-7687}"
    else
        bolt_host="localhost"
        bolt_port="7687"
    fi

    if ! timeout 5 bash -c "echo > /dev/tcp/${bolt_host}/${bolt_port}" 2>/dev/null; then
        warn "Neo4j: unreachable on bolt://${bolt_host}:${bolt_port}"
        record "neo4j" "warning" "unreachable: bolt://${bolt_host}:${bolt_port}"
        return
    fi

    local node_count=""
    if command -v cypher-shell &>/dev/null; then
        node_count=$(echo "MATCH (n) RETURN count(n) AS cnt;" | \
            cypher-shell -a "${NEO4J_URI}" -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" 2>/dev/null | \
            grep -E '^[0-9]+$' | head -1)
    fi

    if [ -n "$node_count" ]; then
        ok "Neo4j: healthy — ${node_count} nodes"
        record "neo4j" "ok" "${node_count} nodes"
    else
        ok "Neo4j: reachable on bolt://${bolt_host}:${bolt_port}"
        record "neo4j" "ok" "reachable: bolt://${bolt_host}:${bolt_port}"
    fi
}

# ── Check: Redis ────────────────────────────────────────────────────────────
check_redis() {
    local redis_args=()
    local redis_host redis_port

    if [[ "$REDIS_URL" =~ redis://([^@]+@)?([^:/]+):?([0-9]*) ]]; then
        redis_host="${BASH_REMATCH[2]}"
        redis_port="${BASH_REMATCH[3]:-6379}"

        local userinfo="${BASH_REMATCH[1]}"
        if [ -n "$userinfo" ]; then
            local password="${userinfo%@}"
            redis_args+=(-a "${password//:/}" --no-auth-warning)
        fi
    else
        redis_host="localhost"
        redis_port="6379"
    fi

    redis_args+=(-h "$redis_host" -p "$redis_port")

    if ! command -v redis-cli &>/dev/null; then
        if timeout 3 bash -c "echo > /dev/tcp/${redis_host}/${redis_port}" 2>/dev/null; then
            ok "Redis: reachable on ${redis_host}:${redis_port} (TCP check only, redis-cli not found)"
            record "redis" "ok" "reachable: TCP ${redis_host}:${redis_port}"
        else
            warn "Redis: unreachable on ${redis_host}:${redis_port}"
            record "redis" "warning" "unreachable: ${redis_host}:${redis_port}"
        fi
        return
    fi

    local ping_result
    ping_result=$(redis-cli "${redis_args[@]}" PING 2>/dev/null)

    if [ "$ping_result" == "PONG" ]; then
        local used_memory
        used_memory=$(redis-cli "${redis_args[@]}" INFO memory 2>/dev/null | grep "used_memory_human" | cut -d: -f2 | tr -d '\r')
        local keys_count
        keys_count=$(redis-cli "${redis_args[@]}" DBSIZE 2>/dev/null | tr -d '\r')

        ok "Redis: healthy — ${keys_count} keys, ${used_memory:-N/A}"
        record "redis" "ok" "${keys_count} keys, ${used_memory:-N/A}"
    else
        critical "Redis: PING failed — ${ping_result}"
        record "redis" "critical" "PING failed: ${ping_result}"
    fi
}

# ── Check: LLM Backend ──────────────────────────────────────────────────────
check_llm() {
    local llm_health_url="${LLM_ENDPOINT%/v1}/health"

    local status_code
    status_code=$(http_get "$llm_health_url" 10)

    if [ "$status_code" == "200" ]; then
        ok "LLM: healthy (${LLM_ENDPOINT})"
        record "llm" "ok" "healthy at ${LLM_ENDPOINT}"
    elif [ "$status_code" == "000" ]; then
        warn "LLM: unreachable — timeout or connection refused (${LLM_ENDPOINT})"
        record "llm" "warning" "unreachable: ${LLM_ENDPOINT}"
    else
        warn "LLM: degraded — HTTP ${status_code} (${LLM_ENDPOINT})"
        record "llm" "warning" "degraded: HTTP ${status_code}"
    fi
}

# ── Check: MinIO ────────────────────────────────────────────────────────────
check_minio() {
    if [ -z "${MINIO_URL}" ]; then
        record "minio" "skipped" "MINIO_URL not set"
        return
    fi

    local status_code
    status_code=$(http_get "${MINIO_URL}/minio/health/live" 5)

    if [ "$status_code" == "200" ]; then
        ok "MinIO: healthy (${MINIO_URL})"
        record "minio" "ok" "healthy at ${MINIO_URL}"
    else
        warn "MinIO: unreachable — HTTP ${status_code} (${MINIO_URL})"
        record "minio" "warning" "unreachable: HTTP ${status_code}"
    fi
}

# ── Check: Docker Containers ────────────────────────────────────────────────
check_docker() {
    if ! command -v docker &>/dev/null; then
        return
    fi

    local expected_containers=("rag-proxy" "qdrant" "neo4j" "redis" "vllm")
    for name in "${expected_containers[@]}"; do
        local container_id
        container_id=$(docker ps --filter "name=${name}" --format "{{.ID}}" 2>/dev/null | head -1)
        if [ -z "$container_id" ]; then
            continue
        fi

        local status
        status=$(docker inspect -f '{{.State.Status}}' "$container_id" 2>/dev/null)
        local health
        health=$(docker inspect -f '{{.State.Health.Status}}' "$container_id" 2>/dev/null || echo "N/A")

        if [ "$status" == "running" ] && [ "$health" == "healthy" ]; then
            ok "Docker: ${name} running (healthy)"
            record "docker_${name}" "ok" "running, healthy"
        elif [ "$status" == "running" ] && [ "$health" == "N/A" ]; then
            ok "Docker: ${name} running (no healthcheck)"
            record "docker_${name}" "ok" "running, no healthcheck"
        elif [ "$status" == "running" ]; then
            warn "Docker: ${name} running (${health})"
            record "docker_${name}" "warning" "running, ${health}"
        else
            critical "Docker: ${name} ${status}"
            record "docker_${name}" "critical" "${status}"
        fi
    done
}

# ── JSON Output ─────────────────────────────────────────────────────────────
output_json() {
    local overall
    if [ "$CRITICAL_COUNT" -gt 0 ]; then
        overall="unhealthy"
    elif [ "$WARNING_COUNT" -gt 0 ]; then
        overall="degraded"
    else
        overall="healthy"
    fi

    local json
    json=$(python3 -c "
import json, sys

results = {
    'timestamp': '$(date -u '+%Y-%m-%dT%H:%M:%SZ')',
    'run_id': '${RUN_ID}',
    'overall': '${overall}',
    'summary': {
        'ok': ${OK_COUNT},
        'warnings': ${WARNING_COUNT},
        'critical': ${CRITICAL_COUNT},
        'total': $((OK_COUNT + WARNING_COUNT + CRITICAL_COUNT))
    },
    'checks': {}
}

# Build checks dict from bash associative arrays
import os
" 2>/dev/null)

    python3 -c "
import json
checks = {}
$(
    for check in "${!CHECK_RESULTS[@]}"; do
        echo "checks['${check}'] = {'status': '${CHECK_RESULTS[$check]}', 'message': '${CHECK_MESSAGES[$check]}'}"
    done
)
results = {
    'timestamp': '$(date -u '+%Y-%m-%dT%H:%M:%SZ')',
    'run_id': '${RUN_ID}',
    'overall': '${overall}',
    'summary': {'ok': ${OK_COUNT}, 'warnings': ${WARNING_COUNT}, 'critical': ${CRITICAL_COUNT}},
    'checks': checks
}
print(json.dumps(results, indent=2))
"
}

# ── Summary ─────────────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"

    if [ $CRITICAL_COUNT -gt 0 ]; then
        echo -e "  ${RED}Status: UNHEALTHY${NC} — ${CRITICAL_COUNT} critical, ${WARNING_COUNT} warnings, ${OK_COUNT} ok"
    elif [ $WARNING_COUNT -gt 0 ]; then
        echo -e "  ${YELLOW}Status: DEGRADED${NC} — ${WARNING_COUNT} warnings, ${OK_COUNT} ok"
    else
        echo -e "  ${GREEN}Status: HEALTHY${NC} — all ${OK_COUNT} checks passed"
    fi

    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "Log: ${HEALTH_LOG}"
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    parse_args "$@"

    if ! $QUIET; then
        echo -e "${BOLD}${CYAN}RAG System Health Check${NC} — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
        echo ""
    fi

    log "=== Health check started (run: ${RUN_ID}) ==="

    check_disk "/"
    check_memory
    check_proxy
    check_qdrant
    check_neo4j
    check_redis
    check_llm
    check_minio
    check_docker

    log "=== Health check completed — ok=${OK_COUNT} warn=${WARNING_COUNT} crit=${CRITICAL_COUNT} ==="

    if $OUTPUT_JSON; then
        output_json
    elif ! $QUIET; then
        print_summary
    fi

    if [ $CRITICAL_COUNT -gt 0 ]; then
        exit 2
    elif [ $WARNING_COUNT -gt 0 ]; then
        exit 1
    fi
    exit 0
}

main "$@"
