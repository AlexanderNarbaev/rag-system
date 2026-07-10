#!/bin/bash
# RAG System Installer
# Usage: curl -sSL https://raw.githubusercontent.com/AlexanderNarbaev/rag-system/main/install.sh | bash
# Or:    bash install.sh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Functions
log() { echo -e "${GREEN}[RAG]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."

    # Docker
    if ! command -v docker >/dev/null 2>&1; then
        error "Docker is required. Install: https://docs.docker.com/get-docker/"
    fi

    # Docker Compose (v2 plugin or standalone)
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
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

    # Check Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        error "Docker daemon is not running. Start Docker and try again."
    fi

    log "Prerequisites OK (docker, compose, git)"
}

# Clone or update repository
clone_repo() {
    if [ -d "rag-system" ]; then
        warn "Directory 'rag-system' exists, pulling latest..."
        cd rag-system && git pull --ff-only || warn "Git pull failed, continuing with existing code"
    else
        log "Cloning repository..."
        git clone https://github.com/AlexanderNarbaev/rag-system.git
        cd rag-system
    fi
}

# Setup configuration
setup_config() {
    log "Setting up configuration..."

    # Proxy .env
    if [ ! -f proxy/.env ]; then
        if [ -f .env.example ]; then
            cp .env.example proxy/.env
            log "Created proxy/.env from .env.example"
            warn "Please edit proxy/.env with your settings before starting"
        else
            warn ".env.example not found, skipping proxy/.env creation"
        fi
    else
        log "proxy/.env already exists"
    fi

    # ETL .env (optional)
    if [ ! -f etl/.env ] && [ -f etl/.env.example ]; then
        cp etl/.env.example etl/.env
        log "Created etl/.env from etl/.env.example"
    fi
}

# Start services
start_services() {
    log "Starting services with ${COMPOSE_CMD}..."
    ${COMPOSE_CMD} -f proxy/docker-compose.yml up -d

    echo ""
    log "Services starting..."
    info "  Proxy:   http://localhost:8080"
    info "  Qdrant:  http://localhost:6333"
    info "  Neo4j:   http://localhost:7474"
    info "  Redis:   http://localhost:6379"
    echo ""
}

# Verify installation
verify_install() {
    log "Verifying installation..."

    # Wait for services to initialize
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if curl -sf http://localhost:8080/v1/health/live >/dev/null 2>&1; then
            log "✅ Installation successful!"
            echo ""
            info "Quick test:"
            info "  curl http://localhost:8080/v1/health"
            info ""
            info "Configuration wizard:"
            info "  make wizard"
            info ""
            info "View logs:"
            info "  ${COMPOSE_CMD} -f proxy/docker-compose.yml logs -f"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 2
    done

    warn "Health check timed out after ${max_attempts} attempts."
    warn "Services may still be starting. Check logs:"
    warn "  ${COMPOSE_CMD} -f proxy/docker-compose.yml logs"
}

# Main
main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║          RAG System — Installation Script           ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""

    check_prerequisites
    clone_repo
    setup_config
    start_services
    verify_install
}

main "$@"
