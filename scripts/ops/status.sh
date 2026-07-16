#!/usr/bin/env bash
#
# scripts/ops/status.sh
# Show status of all RAG System services in a compact table format.
#
# Displays:
#   - Service name and status (running/stopped/unreachable)
#   - Port and endpoint
#   - Version info (where available)
#   - Key metrics (vectors, nodes, keys, etc.)
#   - Uptime (Docker containers)
#
# Usage:
#   ./status.sh
#   ./status.sh --docker      # Docker Compose-specific output
#   ./status.sh --k8s         # Kubernetes-specific output
#   ./status.sh --json        # JSON output
#   ./status.sh --watch       # Watch mode (refresh every 5s)
#
# Required environment variables (optional — uses defaults):
#   QDRANT_HOST, QDRANT_PORT, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
#   REDIS_URL, LLM_ENDPOINT, PROXY_URL

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

# ── Colors (terminal only) ──────────────────────────────────────────────────
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    DIM='\033[2m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' CYAN='' BOLD='' DIM='' NC=''
fi

# ── State ───────────────────────────────────────────────────────────────────
MODE="auto"
OUTPUT_JSON=false
WATCH=false
STATUS_DATA=()

# ── Helpers ─────────────────────────────────────────────────────────────────
http_code() {
    curl -s --max-time 5 -o /dev/null -w "%{http_code}" "$1" 2>/dev/null || echo "000"
}

http_body() {
    curl -s --max-time 5 "$1" 2>/dev/null || echo ""
}

redis_cmd() {
    if ! command -v redis-cli &>/dev/null; then
        return 1
    fi

    local args=()

    if [[ "$REDIS_URL" =~ redis://([^@]+@)?([^:/]+):?([0-9]*) ]]; then
        local userinfo="${BASH_REMATCH[1]}"
        local host="${BASH_REMATCH[2]}"
        local port="${BASH_REMATCH[3]:-6379}"
        args+=(-h "$host" -p "$port")
        if [ -n "$userinfo" ]; then
            local password="${userinfo%@}"
            args+=(-a "${password//:/}" --no-auth-warning)
        fi
    fi

    redis-cli "${args[@]}" "$@" 2>/dev/null
}

status_icon() {
    case "$1" in
        running|healthy|ok|green)  echo -e "${GREEN}●${NC}" ;;
        degraded|warning|yellow)   echo -e "${YELLOW}●${NC}" ;;
        stopped|unreachable|failed|error|red) echo -e "${RED}●${NC}" ;;
        unknown|skipped)           echo -e "${DIM}○${NC}" ;;
        *)                         echo -e "${DIM}○${NC}" ;;
    esac
}

# ── Parse arguments ─────────────────────────────────────────────────────────
parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --docker) MODE="docker" ;;
            --k8s)    MODE="k8s" ;;
            --json)   OUTPUT_JSON=true ;;
            --watch)  WATCH=true ;;
            --help|-h)
                echo "Usage: $(basename "$0") [--docker|--k8s] [--json] [--watch]"
                echo ""
                echo "Options:"
                echo "  --docker   Show Docker Compose service status"
                echo "  --k8s      Show Kubernetes pod status"
                echo "  --json     Output as JSON"
                echo "  --watch    Refresh every 5 seconds"
                echo "  --help     Show this help"
                exit 0
                ;;
        esac
        shift
    done
}

# ── Detect environment ──────────────────────────────────────────────────────
detect_env() {
    if [ "$MODE" != "auto" ]; then
        return
    fi
    if command -v kubectl &>/dev/null && kubectl cluster-info &>/dev/null 2>&1; then
        MODE="k8s"
    elif command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
        MODE="docker"
    else
        MODE="bare"
    fi
}

# ── Collect service status ──────────────────────────────────────────────────
collect_proxy() {
    local status="unreachable"
    local detail=""
    local version=""

    local code
    code=$(http_code "${PROXY_URL}/v1/health/live")
    if [ "$code" == "200" ]; then
        status="healthy"
        detail="port 8080"

        local health
        health=$(http_body "${PROXY_URL}/v1/health")
        local health_status
        health_status=$(echo "$health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
        if [ "$health_status" != "ok" ] && [ -n "$health_status" ]; then
            status="degraded"
            detail="status=${health_status}"
        fi
    elif [ "$code" != "000" ]; then
        status="degraded"
        detail="HTTP ${code}"
    fi

    echo "proxy|${status}|RAG Proxy|${PROXY_URL}|${detail}"
}

collect_qdrant() {
    local status="unreachable"
    local detail=""

    local code
    code=$(http_code "http://${QDRANT_HOST}:${QDRANT_PORT}/health")
    if [ "$code" == "200" ]; then
        local coll
        coll=$(http_body "http://${QDRANT_HOST}:${QDRANT_PORT}/collections/${COLLECTION_NAME}")

        local vcount
        vcount=$(echo "$coll" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('vectors_count',0))" 2>/dev/null || echo "0")

        local cstatus
        cstatus=$(echo "$coll" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('status',''))" 2>/dev/null || echo "")

        status="${cstatus:-healthy}"
        detail="${vcount} vectors"
    elif [ "$code" != "000" ]; then
        status="degraded"
        detail="HTTP ${code}"
    fi

    echo "qdrant|${status}|Qdrant|http://${QDRANT_HOST}:${QDRANT_PORT}|${detail}"
}

collect_neo4j() {
    local status="unreachable"
    local detail=""

    if [ -z "${NEO4J_PASSWORD}" ]; then
        echo "neo4j|skipped|Neo4j|${NEO4J_URI}|NEO4J_PASSWORD not set"
        return
    fi

    local bolt_host bolt_port
    if [[ "$NEO4J_URI" =~ bolt://([^:]+):?([0-9]*)$ ]] || [[ "$NEO4J_URI" =~ bolt://([^/]+)/?$ ]]; then
        bolt_host="${BASH_REMATCH[1]}"
        bolt_port="${BASH_REMATCH[2]:-7687}"
    else
        bolt_host="localhost"
        bolt_port="7687"
    fi

    if timeout 5 bash -c "echo > /dev/tcp/${bolt_host}/${bolt_port}" 2>/dev/null; then
        status="healthy"

        if command -v cypher-shell &>/dev/null; then
            local node_count
            node_count=$(echo "MATCH (n) RETURN count(n) AS cnt;" | \
                cypher-shell -a "${NEO4J_URI}" -u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}" 2>/dev/null | \
                grep -E '^[0-9]+$' | head -1)
            if [ -n "$node_count" ]; then
                detail="${node_count} nodes"
            fi
        fi
        detail="${detail:-reachable}"
    fi

    echo "neo4j|${status}|Neo4j|${NEO4J_URI}|${detail}"
}

collect_redis() {
    local status="unreachable"
    local detail=""

    if command -v redis-cli &>/dev/null; then
        local ping_result
        ping_result=$(redis_cmd PING 2>/dev/null)
        if [ "$ping_result" == "PONG" ]; then
            status="healthy"
            local keys
            keys=$(redis_cmd DBSIZE 2>/dev/null | tr -d '\r')
            local mem
            mem=$(redis_cmd INFO memory 2>/dev/null | grep "used_memory_human" | cut -d: -f2 | tr -d '\r')
            detail="${keys} keys, ${mem:-N/A}"
        fi
    else
        local redis_host redis_port
        if [[ "$REDIS_URL" =~ redis://([^@]+@)?([^:/]+):?([0-9]*) ]]; then
            redis_host="${BASH_REMATCH[2]}"
            redis_port="${BASH_REMATCH[3]:-6379}"
        else
            redis_host="localhost"
            redis_port="6379"
        fi
        if timeout 3 bash -c "echo > /dev/tcp/${redis_host}/${redis_port}" 2>/dev/null; then
            status="healthy"
            detail="TCP reachable (no redis-cli)"
        fi
    fi

    echo "redis|${status}|Redis|${REDIS_URL}|${detail}"
}

collect_llm() {
    local status="unreachable"
    local detail=""

    local llm_health="${LLM_ENDPOINT%/v1}/health"
    local code
    code=$(http_code "$llm_health")
    if [ "$code" == "200" ]; then
        status="healthy"
        detail="${LLM_ENDPOINT}"

        local models
        models=$(http_body "${LLM_ENDPOINT}/models")
        local model_count
        model_count=$(echo "$models" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null || echo "?")
        detail="${model_count} model(s)"

    elif [ "$code" == "000" ]; then
        detail="timeout"
    else
        detail="HTTP ${code}"
    fi

    echo "llm|${status}|LLM Backend|${LLM_ENDPOINT}|${detail}"
}

collect_minio() {
    if [ -z "${MINIO_URL}" ]; then
        echo "minio|skipped|MinIO|—|MINIO_URL not set"
        return
    fi

    local code
    code=$(http_code "${MINIO_URL}/minio/health/live")
    local status="unreachable"
    local detail=""

    if [ "$code" == "200" ]; then
        status="healthy"
        detail="${MINIO_URL}"
    else
        detail="HTTP ${code}"
    fi

    echo "minio|${status}|MinIO|${MINIO_URL}|${detail}"
}

collect_etl() {
    local status="unknown"
    local detail=""

    if command -v systemctl &>/dev/null; then
        if systemctl is-active --quiet rag-etl 2>/dev/null; then
            status="healthy"
            detail="systemd service active"
        elif systemctl is-enabled --quiet rag-etl 2>/dev/null; then
            status="stopped"
            detail="systemd service inactive"
        fi
    fi

    echo "etl|${status}|ETL Pipeline|—|${detail:-cannot determine status}"
}

# ── Docker mode ─────────────────────────────────────────────────────────────
collect_docker() {
    local containers=("rag-proxy" "qdrant" "neo4j" "redis" "vllm" "minio")
    for name in "${containers[@]}"; do
        local cid
        cid=$(docker ps -a --filter "name=${name}" --format "{{.ID}}" 2>/dev/null | head -1)
        if [ -z "$cid" ]; then
            continue
        fi

        local state
        state=$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)
        local health
        health=$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "N/A")
        local uptime
        uptime=$(docker inspect -f '{{.State.StartedAt}}' "$cid" 2>/dev/null | cut -d'T' -f2 | cut -d'.' -f1)

        local status="$state"
        if [ "$health" != "N/A" ] && [ "$health" != "healthy" ]; then
            status="degraded"
        elif [ "$state" != "running" ]; then
            status="stopped"
        fi

        local detail="started ${uptime:-?}"
        if [ "$health" != "N/A" ]; then
            detail="${detail}, ${health}"
        fi

        echo "docker_${name}|${status}|${name}|—|${detail}"
    done
}

# ── K8s mode ────────────────────────────────────────────────────────────────
collect_k8s() {
    if ! command -v kubectl &>/dev/null; then
        echo "k8s|error|Kubernetes|—|kubectl not found"
        return
    fi

    local namespace="${K8S_NAMESPACE:-rag-system}"
    local pods
    pods=$(kubectl get pods -n "$namespace" --no-headers -o wide 2>/dev/null || echo "")

    if [ -z "$pods" ]; then
        echo "k8s|warning|Kubernetes|—|no pods in ${namespace}"
        return
    fi

    while IFS= read -r line; do
        [ -z "$line" ] && continue
        local name
        name=$(echo "$line" | awk '{print $1}')
        local ready
        ready=$(echo "$line" | awk '{print $2}')
        local state
        state=$(echo "$line" | awk '{print $3}')
        local status="healthy"

        if [[ "$state" == "Running" ]]; then
            status="healthy"
        elif [[ "$state" == "Pending" ]] || [[ "$state" == "ContainerCreating" ]]; then
            status="degraded"
        elif [[ "$state" == *"Error"* ]] || [[ "$state" == *"Crash"* ]]; then
            status="failed"
        else
            status="unknown"
        fi

        local node
        node=$(echo "$line" | awk '{print $7}')
        echo "k8s_${name%%-*}|${status}|${name}|${node:-?}|${ready} ready, ${state}"
    done <<< "$pods"
}

# ── Collect all status ──────────────────────────────────────────────────────
collect_all() {
    STATUS_DATA=()

    if [ "$MODE" == "docker" ]; then
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_docker)
    elif [ "$MODE" == "k8s" ]; then
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_k8s)
    else
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_proxy)
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_qdrant)
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_neo4j)
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_redis)
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_llm)
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_minio)
        while IFS= read -r line; do STATUS_DATA+=("$line"); done < <(collect_etl)
    fi
}

# ── Print table ─────────────────────────────────────────────────────────────
print_table() {
    echo -e "${BOLD}${CYAN}RAG System Status${NC} — $(date -u '+%Y-%m-%d %H:%M:%S UTC') — ${MODE} mode"
    echo ""

    printf "  %-2s %-20s %-12s %-13s %s\n" "" "SERVICE" "STATUS" "ENDPOINT" "DETAILS"
    echo "  ───────────────────────────────────────────────────────────────────────────────"

    for entry in "${STATUS_DATA[@]}"; do
        local id status_raw label endpoint detail
        IFS='|' read -r id status_raw label endpoint detail <<< "$entry"

        local icon
        icon=$(status_icon "$status_raw")

        local display_status="$status_raw"
        case "$status_raw" in
            healthy|running|ok|green)  display_status="${GREEN}${status_raw}${NC}" ;;
            degraded|warning|yellow)   display_status="${YELLOW}${status_raw}${NC}" ;;
            stopped|unreachable|failed|error|red) display_status="${RED}${status_raw}${NC}" ;;
            *)                         display_status="${DIM}${status_raw}${NC}" ;;
        esac

        printf "  %b %-20s %b %-13s %s\n" \
            "$icon" \
            "$label" \
            "$display_status" \
            "${endpoint:0:25}" \
            "${detail:0:45}"

    done

    echo ""
}

# ── JSON output ─────────────────────────────────────────────────────────────
print_json() {
    local entries_json="["
    local first=true
    for entry in "${STATUS_DATA[@]}"; do
        local id status_raw label endpoint detail
        IFS='|' read -r id status_raw label endpoint detail <<< "$entry"
        if [ "$first" = true ]; then first=false; else entries_json+=","; fi
        entries_json+="{\"id\":\"$id\",\"status\":\"$status_raw\",\"label\":\"$label\",\"endpoint\":\"$endpoint\",\"detail\":\"$detail\"}"
    done
    entries_json+="]"

    echo "{\"timestamp\":\"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\",\"mode\":\"$MODE\",\"services\":$entries_json}"
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    parse_args "$@"
    detect_env

    collect_all

    if $OUTPUT_JSON; then
        print_json
    else
        print_table
    fi

    if $WATCH; then
        trap 'echo ""; exit 0' INT
        while true; do
            sleep 5
            clear 2>/dev/null || true
            collect_all
            if $OUTPUT_JSON; then
                print_json
            else
                print_table
            fi
        done
    fi
}

main "$@"
