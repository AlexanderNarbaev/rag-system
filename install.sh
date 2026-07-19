#!/bin/bash
# RAG System Installer
# Usage: curl -sSL https://raw.githubusercontent.com/AlexanderNarbaev/rag-system/main/install.sh | bash
# Or:    bash install.sh
#
# This script:
#   1. Checks prerequisites (Docker, Docker Compose, Git)
#   2. Clones the RAG System repository
#   3. Creates configuration from template
#   4. Starts all services via Docker Compose
#   5. Verifies installation

set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ── Functions ───────────────────────────────────────────────────────────────
log()   { echo -e "${GREEN}[RAG]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
info()  { echo -e "${BLUE}[INFO]${NC} $1"; }

# ── Check prerequisites ────────────────────────────────────────────────────
check_prerequisites() {
    log "Checking prerequisites..."

    # Docker
    if ! command -v docker >/dev/null 2>&1; then
        error "Docker is required. Install: https://docs.docker.com/get-docker/"
    fi

    # Docker Compose (v2 plugin or standalone)
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD="docker-compose"
    else
        error "Docker Compose is required. Install: https://docs.docker.com/compose/install/"
    fi

    # Git
    if ! command -v git >/dev/null 2>&1; then
        error "Git is required. Install: https://git-scm.com/downloads"
    fi

    # curl (needed for health checks)
    if ! command -v curl >/dev/null 2>&1; then
        error "curl is required. Install: apt install curl / brew install curl"
    fi

    # Check Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        error "Docker daemon is not running. Start Docker and try again."
    fi

    log "Prerequisites OK (docker, compose, git, curl)"
}

# ── Clone or update repository ─────────────────────────────────────────────
clone_repo() {
    # Check if we're already inside the rag-system repo
    if [ -f "proxy/docker-compose.yml" ] && [ -f "install.sh" ]; then
        log "Already inside rag-system repository"
        return 0
    fi

    INSTALL_DIR="${INSTALL_DIR:-$(pwd)/rag-system}"

    if [ -d "$INSTALL_DIR" ]; then
        warn "Directory '$INSTALL_DIR' exists, pulling latest..."
        cd "$INSTALL_DIR"
        git pull --ff-only 2>/dev/null || warn "Git pull failed, continuing with existing code"
    else
        log "Cloning repository into $INSTALL_DIR ..."
        git clone https://github.com/AlexanderNarbaev/rag-system.git "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi

    # Verify we're in the right directory
    if [ ! -f "proxy/docker-compose.yml" ]; then
        error "proxy/docker-compose.yml not found. Are you in the correct directory?"
    fi

    log "Repository ready at $(pwd)"
}

# ── Setup configuration ────────────────────────────────────────────────────
setup_config() {
    log "Setting up configuration..."

    # Create proxy/.env from .env.example
    if [ ! -f proxy/.env ]; then
        if [ -f .env.example ]; then
            cp .env.example proxy/.env
            log "Created proxy/.env from .env.example"
            warn "Please edit proxy/.env with your settings before starting:"
            warn "  - EMBEDDER_MODEL (embedding model name)"
            warn "  - RERANKER_MODEL (reranker model name)"
            warn "  - LLM_MODEL_NAME (LLM model name)"
            warn "  - LLM_ENDPOINT (LLM API endpoint)"
        else
            warn ".env.example not found, skipping proxy/.env creation"
        fi
    else
        log "proxy/.env already exists"
    fi

    # Create data directories
    mkdir -p data logs
    log "Created data/ and logs/ directories"
}

# ── Start services ──────────────────────────────────────────────────────────
start_services() {
    log "Starting services with ${COMPOSE_CMD}..."

    # Pull images first (for better error messages)
    ${COMPOSE_CMD} -f proxy/docker-compose.yml pull --ignore-buildable 2>/dev/null || true

    # Start services
    ${COMPOSE_CMD} -f proxy/docker-compose.yml up -d

    echo ""
    log "Services starting..."
    info "  Proxy:   http://localhost:8080"
    info "  Qdrant:  http://localhost:6333"
    info "  Neo4j:   http://localhost:7474"
    info "  Redis:   http://localhost:6379"
    echo ""
}

# ── Verify installation ────────────────────────────────────────────────────
verify_install() {
    log "Verifying installation..."

    # Wait for services to initialize
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if curl -sf http://localhost:8080/v1/health/live >/dev/null 2>&1; then
            echo ""
            log "✅ Installation successful!"
            echo ""
            info "Quick test:"
            info "  curl http://localhost:8080/v1/health"
            echo ""
            info "Configuration wizard:"
            info "  make wizard"
            echo ""
            info "View logs:"
            info "  ${COMPOSE_CMD} -f proxy/docker-compose.yml logs -f"
            echo ""
            return 0
        fi
        attempt=$((attempt + 1))
        if [ $((attempt % 5)) -eq 0 ]; then
            info "  Waiting for services... ($attempt/$max_attempts)"
        fi
        sleep 2
    done

    echo ""
    warn "Health check timed out after ${max_attempts} attempts."
    warn "Services may still be starting. Check logs:"
    warn "  ${COMPOSE_CMD} -f proxy/docker-compose.yml logs"
    warn ""
    warn "Common issues:"
    warn "  1. LLM endpoint not configured (edit proxy/.env → LLM_ENDPOINT)"
    warn "  2. Embedding model not set (edit proxy/.env → EMBEDDER_MODEL)"
    warn "  3. Port already in use (check: lsof -i :8080)"
}

# ── Main ────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║          RAG System — Installation Script                ║"
    echo "║                                                          ║"
    echo "║  This will install:                                      ║"
    echo "║    • RAG Proxy (FastAPI)                                 ║"
    echo "║    • Qdrant (vector database)                            ║"
    echo "║    • Neo4j (graph database)                              ║"
    echo "║    • Redis (cache)                                       ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""

    check_prerequisites
    clone_repo
    setup_config
    start_services
    verify_install
}

main "$@"
