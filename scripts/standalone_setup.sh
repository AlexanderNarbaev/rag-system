#!/usr/bin/env bash
# standalone_setup.sh — Complete standalone deployment for RAG System
# Usage: sudo bash standalone_setup.sh [--install-dir /opt/rag-system]
#
# This script:
#   - Installs all dependencies (Docker, NVIDIA Container Toolkit)
#   - Downloads LLM and embedding models offline
#   - Initializes Qdrant collections
#   - Generates self-signed SSL certificates
#   - Configures firewall rules
#   - Creates systemd service
#   - Sets up logrotate and backup cron
#   - Runs health checks

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
INSTALL_DIR="${INSTALL_DIR:-/opt/rag-system}"
DATA_DIR="${DATA_DIR:-${INSTALL_DIR}/data}"
MODELS_DIR="${MODELS_DIR:-${DATA_DIR}/models}"
LOGS_DIR="${LOGS_DIR:-${INSTALL_DIR}/logs}"
CERT_DIR="${CERT_DIR:-${INSTALL_DIR}/certs}"
BACKUP_DIR="${BACKUP_DIR:-${DATA_DIR}/backups}"
COMPOSE_FILE="${INSTALL_DIR}/docker-compose.standalone.yml"
MODEL_NAME_LLM="${MODEL_NAME_LLM:-gemma-4-26b-it}"
MODEL_NAME_EMBEDDER="${MODEL_NAME_EMBEDDER:-BAAI/bge-m3}"
RAG_PORT="${RAG_PORT:-8080}"
DOMAIN="${DOMAIN:-rag.internal}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --data-dir)    DATA_DIR="$2";    shift 2 ;;
        --models-dir)  MODELS_DIR="$2";  shift 2 ;;
        --port)        RAG_PORT="$2";    shift 2 ;;
        --domain)      DOMAIN="$2";      shift 2 ;;
        *) err "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Pre-flight checks ─────────────────────────────────────────────────────────
log "== RAG System Standalone Setup =="
log "Install dir:  ${INSTALL_DIR}"
log "Data dir:     ${DATA_DIR}"
log "Models dir:   ${MODELS_DIR}"
log "Port:         ${RAG_PORT}"

if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (sudo)."
    exit 1
fi

# ── 1. Create directory structure ─────────────────────────────────────────────
log "Creating directory structure..."
mkdir -p "${INSTALL_DIR}" "${DATA_DIR}" "${MODELS_DIR}" "${LOGS_DIR}" "${CERT_DIR}" "${BACKUP_DIR}"
mkdir -p "${DATA_DIR}/qdrant" "${DATA_DIR}/neo4j" "${DATA_DIR}/redis" "${DATA_DIR}/etl-raw" "${DATA_DIR}/chunks"

# ── 2. Install system dependencies ────────────────────────────────────────────
log "Installing system dependencies..."

if command -v apt-get &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq \
        curl wget git python3 python3-pip python3-venv \
        jq zip unzip nginx certbot logrotate ufw \
        nvidia-container-toolkit 2>/dev/null || true
elif command -v yum &>/dev/null; then
    yum install -y -q \
        curl wget git python3 python3-pip \
        jq zip unzip nginx certbot logrotate firewalld \
        nvidia-container-toolkit 2>/dev/null || true
elif command -v dnf &>/dev/null; then
    dnf install -y -q \
        curl wget git python3 python3-pip \
        jq zip unzip nginx certbot logrotate firewalld \
        nvidia-container-toolkit 2>/dev/null || true
fi

# ── 3. Install Docker if missing ──────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# Install Docker Compose plugin
if ! docker compose version &>/dev/null 2>&1; then
    log "Installing Docker Compose plugin..."
    DOCKER_COMPOSE_VERSION="v2.24.0"
    ARCH=$(uname -m)
    if [[ "$ARCH" == "x86_64" ]]; then
        curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64" \
            -o /usr/local/lib/docker/cli-plugins/docker-compose
    else
        curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-aarch64" \
            -o /usr/local/lib/docker/cli-plugins/docker-compose
    fi
    mkdir -p /usr/local/lib/docker/cli-plugins
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# ── 4. Configure NVIDIA GPU support ───────────────────────────────────────────
if command -v nvidia-smi &>/dev/null; then
    log "NVIDIA GPU detected, configuring container toolkit..."
    nvidia-ctk runtime configure --runtime=docker 2>/dev/null || true
    systemctl restart docker 2>/dev/null || true
    export HAS_GPU=true
else
    warn "No NVIDIA GPU detected — running in CPU-only mode."
    export HAS_GPU=false
fi

# ── 5. Download models (offline cache) ────────────────────────────────────────
log "Downloading models to ${MODELS_DIR}..."

download_model() {
    local name="$1"
    local url="$2"
    local dest="${MODELS_DIR}/${name}"
    if [[ -d "${dest}" ]] && [[ -n "$(ls -A "${dest}" 2>/dev/null)" ]]; then
        log "Model ${name} already exists, skipping."
    else
        mkdir -p "${dest}"
        log "Downloading ${name} from ${url}..."
        if [[ "${url}" == *.gguf || "${url}" == *.bin ]]; then
            wget -q --show-progress -O "${dest}/$(basename "${url}")" "${url}" || {
                warn "Failed to download ${name}. Install manually to ${dest}"
            }
        else
            # HuggingFace model — use snapshot_download if available
            if python3 -c "import huggingface_hub" 2>/dev/null; then
                python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('${url}', local_dir='${dest}', local_dir_use_symlinks=False)
" 2>/dev/null || warn "HF download failed for ${name}"
            else
                pip3 install -q huggingface_hub 2>/dev/null && \
                python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('${url}', local_dir='${dest}', local_dir_use_symlinks=False)
" 2>/dev/null || warn "HF download failed for ${name}"
            fi
        fi
    fi
}

# Gemma LLM
download_model "gemma-4-26b-it-GGUF" \
    "https://huggingface.co/bartowski/gemma-4-26b-it-GGUF/resolve/main/gemma-4-26b-it-Q4_K_M.gguf" &

# Embedding model
download_model "bge-m3" "BAAI/bge-m3" &

# Reranker model
download_model "reranker-MiniLM-L6-v2" "cross-encoder/ms-marco-MiniLM-L-6-v2" &

wait
log "Model downloads completed."

# ── 6. Generate self-signed SSL certificates ──────────────────────────────────
log "Generating self-signed SSL certificates..."

if [[ ! -f "${CERT_DIR}/cert.pem" ]]; then
    openssl req -x509 -nodes -days 365 -newkey rsa:4096 \
        -keyout "${CERT_DIR}/privkey.pem" \
        -out "${CERT_DIR}/cert.pem" \
        -subj "/C=RU/ST=Moscow/L=Moscow/O=RAG System/CN=${DOMAIN}" \
        -addext "subjectAltName=DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1" 2>/dev/null
    chmod 600 "${CERT_DIR}/privkey.pem"
    chmod 644 "${CERT_DIR}/cert.pem"
    log "SSL certificates generated in ${CERT_DIR}"
else
    log "SSL certificates already exist."
fi

# ── 7. Create .env file ───────────────────────────────────────────────────────
log "Creating environment configuration..."

cat > "${INSTALL_DIR}/.env" <<EOF
# RAG System — Standalone Deployment
QDRANT_HOST=qdrant
QDRANT_PORT=6333
QDRANT_COLLECTION=knowledge_base
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=$(openssl rand -hex 16)
REDIS_URL=redis://redis:6379
REDIS_DB=0
LLM_ENDPOINT=http://vllm:8000/v1
LLM_MODEL_NAME=${MODEL_NAME_LLM}
SLM_MODEL_NAME=gemma-2b-it
EMBEDDER_MODEL=${MODEL_NAME_EMBEDDER}
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
USE_REDIS=true
USE_LANGGRAPH=true
GRAPH_ENABLED=true
USE_GRAPH_EXPANSION=true
RATE_LIMIT_ENABLED=true
METRICS_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
MODEL_CACHE_DIR=/models
DATA_DIR=/data
MAX_CONTEXT_TOKENS=8000
RERANK_TOP_K=20
WORKERS=1
API_KEY=${RAG_API_KEY:-}
EOF
chmod 600 "${INSTALL_DIR}/.env"
log ".env file created."

# ── 8. Create docker-compose.standalone.yml ───────────────────────────────────
log "Creating Docker Compose configuration..."

cat > "${COMPOSE_FILE}" <<'COMPOSE_EOF'
version: "3.8"

services:
  qdrant:
    image: qdrant/qdrant:v1.10.0
    container_name: rag-qdrant
    volumes:
      - ${DATA_DIR:-./data}/qdrant:/qdrant/storage
    ports:
      - "127.0.0.1:6333:6333"
    environment:
      QDRANT__SERVICE__HTTP_PORT: 6333
      QDRANT__STORAGE__SNAPSHOT_PATH: /qdrant/storage/snapshots
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4g
          cpus: "4"
    networks:
      - rag-net

  neo4j:
    image: neo4j:5.25-community
    container_name: rag-neo4j
    volumes:
      - ${DATA_DIR:-./data}/neo4j:/data
      - ${DATA_DIR:-./data}/neo4j-logs:/logs
      - ${DATA_DIR:-./data}/neo4j-import:/import
    ports:
      - "127.0.0.1:7474:7474"
      - "127.0.0.1:7687:7687"
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:-password}
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_memory_pagecache_size: 512M
      NEO4J_dbms_memory_heap_initial__size: 512M
      NEO4J_dbms_memory_heap_max__size: 1G
      NEO4J_dbms_security_procedures_unrestricted: apoc.*
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "${NEO4J_PASSWORD:-password}", "RETURN 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 30s
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2g
          cpus: "2"
    networks:
      - rag-net

  redis:
    image: redis:7.4-alpine
    container_name: rag-redis
    volumes:
      - ${DATA_DIR:-./data}/redis:/data
    ports:
      - "127.0.0.1:6379:6379"
    command: >
      redis-server
      --appendonly yes
      --maxmemory 2gb
      --maxmemory-policy allkeys-lru
      --save 900 1
      --save 300 10
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2g
          cpus: "1"
    networks:
      - rag-net

  vllm:
    image: vllm/vllm-openai:v0.6.4
    container_name: rag-vllm
    volumes:
      - ${MODELS_DIR:-./data/models}:/models:ro
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      VLLM_API_KEY: "${API_KEY:-}"
    command: >
      --model /models/gemma-4-26b-it-GGUF/gemma-4-26b-it-Q4_K_M.gguf
      --port 8000
      --host 0.0.0.0
      --max-model-len 65536
      --gpu-memory-utilization 0.90
      --dtype auto
      --enforce-eager
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 60s
      timeout: 30s
      retries: 5
      start_period: 120s
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 32g
          cpus: "8"
    runtime: nvidia
    networks:
      - rag-net
    profiles:
      - gpu

  vllm-cpu:
    image: ghcr.io/ggerganov/llama.cpp:server
    container_name: rag-vllm-cpu
    volumes:
      - ${MODELS_DIR:-./data/models}:/models:ro
    ports:
      - "127.0.0.1:8000:8000"
    command: >
      --model /models/gemma-4-26b-it-GGUF/gemma-4-26b-it-Q4_K_M.gguf
      --host 0.0.0.0
      --port 8000
      --ctx-size 65536
      --n-gpu-layers 0
      --threads ${CPU_THREADS:-4}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 60s
      timeout: 30s
      retries: 5
      start_period: 120s
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 32g
          cpus: "8"
    networks:
      - rag-net
    profiles:
      - cpu

  rag-proxy:
    build:
      context: ..
      dockerfile: proxy/Dockerfile
    container_name: rag-proxy
    volumes:
      - ${MODELS_DIR:-./data/models}:/models:ro
      - ${LOGS_DIR:-./logs}:/app/logs
      - ${INSTALL_DIR:-.}/.env:/app/.env:ro
    ports:
      - "127.0.0.1:${RAG_PORT:-8080}:8080"
    environment:
      QDRANT_HOST: qdrant
      QDRANT_PORT: 6333
      NEO4J_URI: bolt://neo4j:7687
      REDIS_URL: redis://redis:6379
      LLM_ENDPOINT: http://vllm:8000/v1
    depends_on:
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 8g
          cpus: "4"
    networks:
      - rag-net

  nginx:
    image: nginx:1.27-alpine
    container_name: rag-nginx
    volumes:
      - ${CERT_DIR:-./certs}:/etc/nginx/certs:ro
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      rag-proxy:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - rag-net

networks:
  rag-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16

volumes:
  qdrant_data:
  neo4j_data:
  neo4j_logs:
  neo4j_import:
  redis_data:
COMPOSE_EOF

log "Docker Compose file created at ${COMPOSE_FILE}"

# ── 9. Create NGINX reverse proxy config ──────────────────────────────────────
cat > "${INSTALL_DIR}/nginx.conf" <<EOF
events { worker_connections 1024; }

http {
    upstream rag_backend {
        server rag-proxy:8080;
    }

    server {
        listen 80;
        server_name ${DOMAIN} localhost;
        return 301 https://\$host\$request_uri;
    }

    server {
        listen 443 ssl;
        server_name ${DOMAIN} localhost;

        ssl_certificate     /etc/nginx/certs/cert.pem;
        ssl_certificate_key /etc/nginx/certs/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        client_max_body_size 100M;
        proxy_read_timeout 300s;

        location / {
            proxy_pass http://rag_backend;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }

        location /v1/chat/completions {
            proxy_pass http://rag_backend/v1/chat/completions;
            proxy_set_header Host \$host;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_read_timeout 600s;
            proxy_buffering off;
        }
    }
}
EOF

# ── 10. Configure firewall ────────────────────────────────────────────────────
log "Configuring firewall..."

if command -v ufw &>/dev/null; then
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow "${RAG_PORT}"/tcp
    ufw --force enable 2>/dev/null || true
elif command -v firewall-cmd &>/dev/null; then
    firewall-cmd --permanent --add-service=http
    firewall-cmd --permanent --add-service=https
    firewall-cmd --permanent --add-port="${RAG_PORT}"/tcp
    firewall-cmd --reload
fi

# ── 11. Create systemd service ────────────────────────────────────────────────
log "Creating systemd service..."

cat > /etc/systemd/system/rag-system.service <<EOF
[Unit]
Description=RAG Knowledge System (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${INSTALL_DIR}
ExecStartPre=/usr/bin/docker compose -f ${COMPOSE_FILE} --env-file ${INSTALL_DIR}/.env pull
ExecStart=/usr/bin/docker compose -f ${COMPOSE_FILE} --env-file ${INSTALL_DIR}/.env up -d
ExecStop=/usr/bin/docker compose -f ${COMPOSE_FILE} --env-file ${INSTALL_DIR}/.env down
ExecReload=/usr/bin/docker compose -f ${COMPOSE_FILE} --env-file ${INSTALL_DIR}/.env restart rag-proxy
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable rag-system.service

# ── 12. Create logrotate configuration ────────────────────────────────────────
log "Configuring logrotate..."

cat > /etc/logrotate.d/rag-system <<EOF
${LOGS_DIR}/*.log ${LOGS_DIR}/*.jsonl {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 100M
    create 0640 root root
    postrotate
        docker exec rag-proxy kill -HUP 1 2>/dev/null || true
    endscript
}
EOF

# ── 13. Create backup script ──────────────────────────────────────────────────
log "Creating backup script..."

cat > "${INSTALL_DIR}/backup.sh" <<'BACKUP_EOF'
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/rag-system/data/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/rag-backup-${TIMESTAMP}.tar.gz"
RETAIN_DAYS="${RETAIN_DAYS:-14}"

mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Starting RAG system backup..."

docker stop rag-qdrant 2>/dev/null || true

tar -czf "${BACKUP_FILE}" \
    -C /opt/rag-system/data \
    qdrant/ neo4j/ redis/ \
    2>/dev/null || true

docker start rag-qdrant 2>/dev/null || true

echo "[$(date)] Backup saved to ${BACKUP_FILE}"
echo "[$(date)] Size: $(du -h "${BACKUP_FILE}" | cut -f1)"

# Cleanup old backups
find "${BACKUP_DIR}" -name "rag-backup-*.tar.gz" -mtime "+${RETAIN_DAYS}" -delete 2>/dev/null || true
echo "[$(date)] Cleaned up backups older than ${RETAIN_DAYS} days"
echo "[$(date)] Backup completed."
BACKUP_EOF

chmod +x "${INSTALL_DIR}/backup.sh"

# Add backup cron job
(crontab -l 2>/dev/null; echo "0 3 * * * ${INSTALL_DIR}/backup.sh >> ${LOGS_DIR}/backup.log 2>&1") | crontab -

# ── 14. Initialize Qdrant collections ─────────────────────────────────────────
log "Initializing Qdrant collections..."

if [[ -f "${INSTALL_DIR}/../scripts/init_collections.py" ]]; then
    python3 "${INSTALL_DIR}/../scripts/init_collections.py" \
        --qdrant-host localhost --qdrant-port 6333 \
        2>/dev/null || warn "Qdrant collection init skipped (Qdrant not running yet)."
else
    warn "init_collections.py not found — run manually after services start."
fi

# ── 15. Start services ────────────────────────────────────────────────────────
log "Starting RAG system services..."

cd "${INSTALL_DIR}"

# Determine GPU profile
if [[ "${HAS_GPU:-false}" == "true" ]]; then
    PROFILE="gpu"
    log "Using GPU profile for LLM inference."
else
    PROFILE="cpu"
    log "Using CPU profile for LLM inference."
fi

COMPOSE_PROFILES="${PROFILE}" docker compose -f "${COMPOSE_FILE}" --env-file "${INSTALL_DIR}/.env" pull
COMPOSE_PROFILES="${PROFILE}" docker compose -f "${COMPOSE_FILE}" --env-file "${INSTALL_DIR}/.env" up -d

# ── 16. Health check verification ─────────────────────────────────────────────
log "Waiting for services to become healthy..."

max_wait=300
elapsed=0
interval=10
all_healthy=false

while [[ ${elapsed} -lt ${max_wait} ]]; do
    if health_output=$(docker compose -f "${COMPOSE_FILE}" ps 2>/dev/null); then
        unhealthy_count=$(echo "${health_output}" | grep -c "unhealthy" || true)
        starting_count=$(echo "${health_output}" | grep -c "starting" || true)

        if [[ ${unhealthy_count} -eq 0 ]] && [[ ${starting_count} -eq 0 ]]; then
            all_healthy=true
            break
        fi
    fi
    sleep "${interval}"
    elapsed=$((elapsed + interval))
    echo "  Waiting... (${elapsed}s / ${max_wait}s)"
done

if [[ "${all_healthy}" == "true" ]]; then
    log "All services are healthy!"
else
    warn "Some services may still be starting. Check 'docker compose -f ${COMPOSE_FILE} ps'."
fi

# ── 17. Verify API endpoint ───────────────────────────────────────────────────
log "Verifying API endpoint..."
sleep 5

if curl -sf http://localhost:8080/v1/health >/dev/null 2>&1; then
    log "RAG API is responding at http://localhost:8080/v1/health"
elif curl -sfk https://localhost/v1/health >/dev/null 2>&1; then
    log "RAG API is responding at https://localhost/v1/health"
else
    warn "RAG API not yet responding. Check logs: docker compose -f ${COMPOSE_FILE} logs rag-proxy"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
log ""
log "==============================================="
log "   RAG System Standalone Deployment Complete"
log "==============================================="
log "Install dir:     ${INSTALL_DIR}"
log "API endpoint:    http://localhost:${RAG_PORT}/v1/chat/completions"
log "HTTPS endpoint:  https://${DOMAIN}/v1/chat/completions"
log "Health check:    http://localhost:${RAG_PORT}/v1/health"
log "Models endpoint: http://localhost:${RAG_PORT}/v1/models"
log "Metrics:         http://localhost:${RAG_PORT}/metrics"
log ""
log "Manage with:"
log "  systemctl start|stop|restart|status rag-system"
log "  docker compose -f ${COMPOSE_FILE} logs -f"
log "  ${INSTALL_DIR}/backup.sh"
log ""
log "Logs:    ${LOGS_DIR}"
log "Backups: ${BACKUP_DIR}"
log "Certs:   ${CERT_DIR}"
log "==============================================="
