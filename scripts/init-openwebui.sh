#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# init-openwebui.sh — OpenWebUI initialization and startup for RAG System
# ═══════════════════════════════════════════════════════════════════════════════
# Purpose: Environment preparation, secret generation, resource creation,
#          launching standalone OpenWebUI with PostgreSQL + Redis + Tika.
#
# Usage:
#   chmod +x scripts/init-openwebui.sh
#   ./scripts/init-openwebui.sh              # Interactive mode
#   ./scripts/init-openwebui.sh --auto       # Automatic mode (no prompts)
#   ./scripts/init-openwebui.sh --recreate   # Full reinstall (delete all data)
#
# Requirements:
#   - Docker 24+ and Docker Compose v2
#   - Running RAG Proxy in rag-network
#   - Access to MinIO (minio:9000 in rag-network)
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Output colors ──────────────────────────────────────────────────────────────
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly BOLD='\033[1m'
readonly NC='\033[0m' # No Color

# ── Paths ──────────────────────────────────────────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly COMPOSE_DIR="$PROJECT_ROOT/deploy/docker"
readonly COMPOSE_FILE="$COMPOSE_DIR/docker-compose.openwebui.yml"
readonly ENV_FILE="$COMPOSE_DIR/.env.openwebui"
readonly MINIO_ENDPOINT="http://minio:9000"
readonly MINIO_BUCKET="openwebui-files"
readonly POSTGRES_PASSWORD_LENGTH=24
readonly SECRET_KEY_LENGTH=32

# ── Flags ─────────────────────────────────────────────────────────────────────
AUTO_MODE=false
RECREATE_MODE=false
SKIP_CHECKS=false

# ── Functions ──────────────────────────────────────────────────────────────────

log_section() {
    echo ""
    echo -e "${BLUE}${BOLD}═══ $1 ═══${NC}"
}

log_info() {
    echo -e "${BLUE}ℹ${NC}  $1"
}

log_success() {
    echo -e "${GREEN}✅${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC}  $1"
}

log_error() {
    echo -e "${RED}❌${NC} $1"
}

log_step() {
    echo -e "${BOLD}▶${NC}  $1"
}

confirm() {
    local prompt="$1"
    local default="${2:-n}"

    if [ "$AUTO_MODE" = true ]; then
        return 0
    fi

    local yn="$default"
    read -r -p "$prompt [y/N]: " yn
    case "${yn:-$default}" in
        [Yy]*) return 0 ;;
        *) return 1 ;;
    esac
}

generate_secret() {
    local length="${1:-32}"
    openssl rand -hex "$length" 2>/dev/null || {
        # Fallback: /dev/urandom
        dd if=/dev/urandom bs=1 count=$((length * 2)) 2>/dev/null | xxd -p | tr -d '\n' | head -c $((length * 2))
    }
}

# ── Command-line argument parsing ──────────────────────────────────────────────
parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --auto|-a)
                AUTO_MODE=true
                ;;
            --recreate|-r)
                RECREATE_MODE=true
                ;;
            --skip-checks|-s)
                SKIP_CHECKS=true
                ;;
            --help|-h)
                echo "Usage: $0 [--auto] [--recreate] [--skip-checks]"
                echo ""
                echo "  --auto, -a        Automatic mode (no interactive prompts)"
                echo "  --recreate, -r    Full reinstall (delete all volumes and data)"
                echo "  --skip-checks, -s Skip dependency checks"
                echo "  --help, -h        Show this help"
                exit 0
                ;;
            *)
                log_error "Unknown argument: $arg"
                echo "Use --help for usage"
                exit 1
                ;;
        esac
    done
}

# ── Dependency check ──────────────────────────────────────────────────────────
check_prerequisites() {
    log_section "Dependency Check"

    if [ "$SKIP_CHECKS" = true ]; then
        log_warning "Checks skipped (--skip-checks)"
        return 0
    fi

    # Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker not found. Install Docker 24.0+"
        exit 1
    fi
    local docker_version
    docker_version=$(docker --version 2>/dev/null | grep -oP '\d+\.\d+' | head -1 || echo "0.0")
    log_success "Docker: $(docker --version)"

    # Docker Compose v2
    if docker compose version &> /dev/null; then
        log_success "Docker Compose: $(docker compose version --short)"
    elif docker-compose version &> /dev/null; then
        log_warning "Found legacy docker-compose v1. Docker Compose v2 (plugin) is recommended"
    else
        log_error "Docker Compose not found. Install Docker Compose v2"
        exit 1
    fi

    # openssl (for secret generation)
    if ! command -v openssl &> /dev/null; then
        log_warning "openssl not found — secrets will be generated via /dev/urandom"
    fi

    # xxd (fallback for secret generation)
    if ! command -v xxd &> /dev/null; then
        log_warning "xxd not found — ensure openssl is available for secret generation"
    fi

    # curl (for health-check and bucket creation)
    if ! command -v curl &> /dev/null; then
        log_warning "curl not found — health-check will be unavailable"
    fi

    # Check docker socket availability
    if ! docker info &> /dev/null; then
        log_error "Docker is not running or insufficient permissions. Start Docker daemon"
        exit 1
    fi

    log_success "All prerequisites satisfied"
}

# ── rag-network check ─────────────────────────────────────────────────────────
check_rag_network() {
    log_section "rag-network Check"

    if docker network inspect rag-network &> /dev/null; then
        log_success "rag-network exists"
    else
        log_warning "rag-network not found. It will be created when proxy starts."
        log_info "Ensure RAG Proxy is running with rag-network:"
        echo "       cd $PROJECT_ROOT/proxy && docker compose up -d"
        if ! confirm "Continue without rag-network?"; then
            exit 0
        fi
    fi
}

# ── MinIO availability check ──────────────────────────────────────────────────
check_minio() {
    log_section "MinIO Availability Check"

    # Check if MinIO container is running
    if docker ps --format '{{.Names}}' | grep -q 'rag-minio'; then
        log_success "MinIO container (rag-minio) is running"
    else
        log_warning "MinIO container not found. Ensure MinIO is running in rag-network"
        if ! confirm "Continue without MinIO? (file uploads will be unavailable)"; then
            exit 0
        fi
        return 0
    fi

    # Check MinIO API
    if docker exec rag-minio curl -sf "$MINIO_ENDPOINT/minio/health/live" &> /dev/null; then
        log_success "MinIO API is available"
    else
        log_warning "MinIO API is unavailable. Check container state"
    fi
}

# ── Create MinIO bucket ───────────────────────────────────────────────────────
create_minio_bucket() {
    log_section "Create MinIO Bucket: $MINIO_BUCKET"

    # Use mc (MinIO Client) inside MinIO container
    if docker exec rag-minio mc alias list 2>/dev/null | grep -q 'local'; then
        log_info "Alias 'local' already configured in MinIO"
    else
        log_step "Configuring MinIO client alias..."
        docker exec rag-minio mc alias set local "$MINIO_ENDPOINT" minioadmin minioadmin &> /dev/null || true
    fi

    # Create bucket if it doesn't exist
    if docker exec rag-minio mc ls local/$MINIO_BUCKET &> /dev/null; then
        log_success "Bucket '$MINIO_BUCKET' already exists"
    else
        log_step "Creating bucket '$MINIO_BUCKET'..."
        if docker exec rag-minio mc mb local/$MINIO_BUCKET &> /dev/null; then
            log_success "Bucket '$MINIO_BUCKET' created"
        else
            log_warning "Failed to create bucket. It may be created automatically"
        fi
    fi
}

# ── Generate secrets ──────────────────────────────────────────────────────────
generate_secrets() {
    log_section "Generate Secrets"

    # WEBUI_SECRET_KEY
    local current_key
    current_key=$(grep -E '^WEBUI_SECRET_KEY=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || echo "")

    if [ -z "$current_key" ]; then
        local new_key
        new_key=$(generate_secret "$SECRET_KEY_LENGTH")
        log_step "Generating WEBUI_SECRET_KEY..."

        # Update .env.openwebui
        if [ -f "$ENV_FILE" ]; then
            sed -i "s/^WEBUI_SECRET_KEY=.*/WEBUI_SECRET_KEY=$new_key/" "$ENV_FILE"
        fi
        log_success "WEBUI_SECRET_KEY generated"
        echo -e "       ${YELLOW}Secret key:${NC} $new_key"
        echo -e "       ${YELLOW}SAVE this key in a secure location!${NC} It is needed for:"
        echo "       - JWT token validation across restarts"
        echo "       - Restoring access to user sessions"
    else
        log_success "WEBUI_SECRET_KEY already set"
    fi

    # POSTGRES_PASSWORD
    local current_pg_pass
    current_pg_pass=$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || echo "")

    if [ -z "$current_pg_pass" ]; then
        local new_pg_pass
        new_pg_pass=$(generate_secret "$POSTGRES_PASSWORD_LENGTH")
        log_step "Generating POSTGRES_PASSWORD..."

        if [ -f "$ENV_FILE" ]; then
            sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$new_pg_pass/" "$ENV_FILE"
        fi
        log_success "POSTGRES_PASSWORD generated"
        echo -e "       ${YELLOW}DB password:${NC} $new_pg_pass"
    else
        log_success "POSTGRES_PASSWORD already set"
    fi
}

# ── Full reinstall ────────────────────────────────────────────────────────────
recreate_deployment() {
    log_section "Reinstall (delete all data)"

    if [ "$RECREATE_MODE" = false ]; then
        return 0
    fi

    log_warning "WARNING: This will delete ALL OpenWebUI data — users, chats, files!"
    if ! confirm "Are you sure?"; then
        log_info "Reinstall cancelled"
        RECREATE_MODE=false
        return 0
    fi

    if [ "$AUTO_MODE" = false ]; then
        local confirm_text
        read -r -p "Type 'yes' to confirm: " confirm_text
        if [ "$confirm_text" != "yes" ]; then
            log_info "Reinstall cancelled"
            RECREATE_MODE=false
            return 0
        fi
    fi

    log_step "Stopping containers..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down -v --timeout 30 2>/dev/null || true

    log_step "Removing volumes..."
    docker volume rm rag-openwebui-data rag-openwebui-tmp rag-openwebui-postgres rag-openwebui-redis 2>/dev/null || true

    log_step "Removing openwebui-network..."
    docker network rm rag-openwebui-network 2>/dev/null || true

    log_success "Reinstall complete. All data deleted."
}

# ── Deploy services ───────────────────────────────────────────────────────────
deploy_services() {
    log_section "Deploy OpenWebUI Services"

    log_step "Pulling images (this may take a while)..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" pull 2>&1 | grep -v "Pulling from\|Digest:\|Status:" || true

    log_step "Starting containers..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --wait --wait-timeout 120 2>&1 || {
        log_error "Failed to start services. Check logs:"
        echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs"
        exit 1
    }

    log_success "Services started"
}

# ── Health check ──────────────────────────────────────────────────────────────
health_check() {
    log_section "Health Check"

    local openwebui_url="http://localhost:${OPENWEBUI_HOST_PORT:-3000}"

    if ! command -v curl &> /dev/null; then
        log_warning "curl not found — skipping health-check"
        return 0
    fi

    # Wait for OpenWebUI startup
    log_step "Waiting for OpenWebUI to be ready..."
    local retries=12
    local delay=5

    for i in $(seq 1 $retries); do
        if curl -sf "$openwebui_url/health" &> /dev/null; then
            log_success "OpenWebUI is responding ($openwebui_url)"
            break
        fi
        if [ "$i" -eq "$retries" ]; then
            log_warning "OpenWebUI did not respond after $((retries * delay)) seconds."
            log_info "Check logs: docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs openwebui"
            return 1
        fi
        echo -n "."
        sleep "$delay"
    done
    echo ""

    # Check PostgreSQL
    if docker exec rag-openwebui-postgres pg_isready -U openwebui &> /dev/null; then
        log_success "PostgreSQL: ready"
    else
        log_warning "PostgreSQL: not responding"
    fi

    # Check Redis
    if docker exec rag-openwebui-redis redis-cli ping &> /dev/null; then
        log_success "Redis: ready"
    else
        log_warning "Redis: not responding"
    fi

    # Check Tika
    if docker exec rag-openwebui-tika curl -sf http://localhost:9998/tika &> /dev/null; then
        log_success "Apache Tika: ready"
    else
        log_warning "Apache Tika: not responding"
    fi
}

# ── Admin setup instructions ──────────────────────────────────────────────────
print_admin_instructions() {
    log_section "Admin Account Setup"

    local openwebui_url="http://localhost:${OPENWEBUI_HOST_PORT:-3000}"

    echo ""
    echo -e "  ${BOLD}${GREEN}OpenWebUI is deployed and ready to configure!${NC}"
    echo ""
    echo -e "  ${BOLD}1. Open in browser:${NC}"
    echo -e "     ${BLUE}$openwebui_url${NC}"
    echo ""
    echo -e "  ${BOLD}2. Create admin account:${NC}"
    echo "     • Click \"Sign up\" on the login page"
    echo "     • Enter name, email, and password"
    echo "     • This will be the only account with admin privileges"
    echo "     • After admin creation, self-registration will be disabled"
    echo ""
    echo -e "  ${BOLD}3. Configure RAG Proxy connection:${NC}"
    echo "     • Go to: Admin Panel → Settings → Connections"
    echo "     • Verify OpenAI API: $OPENAI_API_BASE_URLS"
    echo "     • Ensure the 'rag' model appears in the model list"
    echo ""
    echo -e "  ${BOLD}4. User management:${NC}"
    echo "     • Admin Panel → Users — create and activate accounts"
    echo "     • Self-registration is disabled (corporate requirement)"
    echo "     • For Keycloak OIDC: Admin Panel → Settings → General → OAuth"
    echo ""
    echo -e "  ${BOLD}5. Useful management commands:${NC}"
    echo "     • View logs:"
    echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs -f openwebui"
    echo "     • Service status:"
    echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE ps"
    echo "     • Restart:"
    echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE restart"
    echo "     • Stop:"
    echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE down"
    echo ""
    echo -e "  ${BOLD}Saved secrets:${NC}"
    echo "  WEBUI_SECRET_KEY:   from file $ENV_FILE"
    echo "  POSTGRES_PASSWORD:  from file $ENV_FILE"
    echo ""
    echo -e "  ${YELLOW}${BOLD}⚠ Save these secrets in your corporate secret store!${NC}"
    echo ""
}

# ── Deployment summary ────────────────────────────────────────────────────────
print_summary() {
    log_section "Deployment Summary"

    echo ""
    echo -e "  ${BOLD}Services:${NC}"
    echo "  ├── OpenWebUI       → http://localhost:${OPENWEBUI_HOST_PORT:-3000}"
    echo "  ├── PostgreSQL      → postgres:5432 (internal network)"
    echo "  ├── Redis           → redis:6379 (internal network)"
    echo "  └── Apache Tika     → tika:9998 (internal network)"
    echo ""
    echo -e "  ${BOLD}External dependencies (rag-network):${NC}"
    echo "  ├── RAG Proxy       → http://rag-proxy:8080/v1"
    echo "  └── MinIO           → http://minio:9000"
    echo ""
    echo -e "  ${BOLD}Configuration files:${NC}"
    echo "  ├── Compose:        $COMPOSE_FILE"
    echo "  └── Env vars:       $ENV_FILE"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# Main process
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    parse_args "$@"

    echo -e "${BLUE}${BOLD}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║   OpenWebUI Initialization for Corporate RAG System      ║"
    echo "║   Version 2.1.0                                           ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    # Check compose file
    if [ ! -f "$COMPOSE_FILE" ]; then
        log_error "Compose file not found: $COMPOSE_FILE"
        exit 1
    fi

    # Check .env file
    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env file not found: $ENV_FILE"
        exit 1
    fi

    # 1. Dependency check
    check_prerequisites

    # 2. Network check
    check_rag_network

    # 3. MinIO check
    check_minio

    # 4. Generate secrets
    generate_secrets

    # 5. Reinstall (if requested)
    recreate_deployment

    # 6. Create MinIO bucket
    create_minio_bucket

    # 7. Deploy services
    deploy_services

    # 8. Health-check
    health_check

    # 9. Summary and instructions
    print_summary
    print_admin_instructions

    log_success "OpenWebUI initialization complete!"
}

main "$@"
