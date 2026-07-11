#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# RAG System — Interactive Setup Wizard v2
# Usage: ./setup.sh [command]
#
# Commands:
#   (none)     — interactive menu
#   install    — fresh install
#   configure  — modify existing config
#   expand     — add components
#   status     — show current status
#   test       — run tests and checks
#   docker     — manage containers
#   build      — build proxy image
#   etl        — run ETL pipeline
#   openwebui  — setup OpenWebUI
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# ── Logging ──────────────────────────────────────────────────────────────────
log()     { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; }
info()    { echo -e "${BLUE}[i]${NC} $1"; }
header()  { echo -e "\n${BOLD}${CYAN}━━━ $1 ━━━${NC}\n"; }

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$PROJECT_ROOT/proxy/.env"
ETL_CONFIG="$PROJECT_ROOT/etl/config/etl_config.yaml"
COMPOSE_FILE="$PROJECT_ROOT/proxy/docker-compose.yml"
OPENWEBUI_COMPOSE="$PROJECT_ROOT/deploy/docker/docker-compose.openwebui.yml"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

# ── Helpers ──────────────────────────────────────────────────────────────────
get_env() {
    local key="$1" default="${2:-}"
    if [ -f "$ENV_FILE" ]; then
        local val
        val=$(grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | sed 's/#.*//' | xargs)
        echo "${val:-$default}"
    else
        echo "$default"
    fi
}

set_env() {
    local key="$1" value="$2"
    [ ! -f "$ENV_FILE" ] && cp "$ENV_EXAMPLE" "$ENV_FILE" 2>/dev/null || touch "$ENV_FILE"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

get_yaml() {
    local key="$1" default="${2:-}"
    if [ -f "$ETL_CONFIG" ]; then
        local val
        val=$(grep "^  ${key}:" "$ETL_CONFIG" 2>/dev/null | head -1 | cut -d':' -f2- | sed 's/#.*//' | xargs | sed 's/"//g')
        echo "${val:-$default}"
    else
        echo "$default"
    fi
}

set_yaml() {
    local key="$1" value="$2"
    if [ -f "$ETL_CONFIG" ]; then
        if grep -q "^  ${key}:" "$ETL_CONFIG"; then
            sed -i "s|^  ${key}:.*|  ${key}: ${value}|" "$ETL_CONFIG"
        fi
    fi
}

ask() {
    local prompt="$1" default="${2:-}" answer
    if [ -n "$default" ]; then
        read -rp "$(echo -e "${MAGENTA}[?]${NC} ${prompt} [${default}]: ")" answer
        echo "${answer:-$default}"
    else
        read -rp "$(echo -e "${MAGENTA}[?]${NC} ${prompt}: ")" answer
        echo "$answer"
    fi
}

confirm() {
    local prompt="$1" default="${2:-y}" answer
    read -rp "$(echo -e "${MAGENTA}[?]${NC} ${prompt} [y/n, default=${default}]: ")" answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Yy] ]]
}

# ── Compose command ──────────────────────────────────────────────────────────
get_compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
    else
        echo ""
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# MENU
# ═══════════════════════════════════════════════════════════════════════════════
show_menu() {
    echo ""
    echo -e "${BOLD}${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║          RAG System — Setup Wizard v2                    ║${NC}"
    echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "  1)  Fresh Install      — полная установка с нуля"
    echo "  2)  Configure          — настроить существующую установку"
    echo "  3)  Expand             — добавить компоненты"
    echo "  4)  ETL Setup          — настроить и запустить ETL"
    echo "  5)  Proxy Build        — собрать образ прокси"
    echo "  6)  Docker             — управление контейнерами"
    echo "  7)  OpenWebUI          — настройка веб-интерфейса"
    echo "  8)  Status             — показать текущий статус"
    echo "  9)  Test               — запустить проверку"
    echo "  0)  Exit"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# 1. FRESH INSTALL
# ═══════════════════════════════════════════════════════════════════════════════
do_install() {
    header "Fresh Install"

    # Profile
    echo "Выберите профиль установки:"
    echo ""
    echo "  1) Minimal   — Proxy + Qdrant (без графа, без кэша)"
    echo "  2) Standard  — Proxy + Qdrant + Redis + Neo4j"
    echo "  3) Full      — Standard + MinIO + Monitoring"
    echo ""
    local profile
    read -rp "$(echo -e "${MAGENTA}[?]${NC} Профиль [1/2/3, default=2]: ")" profile
    profile="${profile:-2}"

    # Create .env
    header "Configuration"
    if [ -f "$ENV_FILE" ]; then
        warn "Файл $ENV_FILE уже существует"
        if confirm "Перезаписать?" "n"; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            log "Создан $ENV_FILE"
        fi
    else
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        log "Создан $ENV_FILE"
    fi

    # LLM
    header "LLM / Language Model"
    info "Основная языковая модель для генерации ответов"
    echo ""
    set_env "LLM_ENDPOINT" "$(ask 'LLM Endpoint (OpenAI-compatible)' "$(get_env LLM_ENDPOINT 'http://localhost:8000/v1')")"
    set_env "LLM_MODEL_NAME" "$(ask 'LLM Model Name' "$(get_env LLM_MODEL_NAME '')")"
    local api_key
    api_key=$(ask 'LLM API Key (пусто = без ключа)' "$(get_env LLM_API_KEY '')")
    [ -n "$api_key" ] && set_env "LLM_API_KEY" "$api_key"

    # Embedder
    header "Embedding Model"
    echo "  1) Remote  — использовать удалённый сервис (GPUStack, OpenAI-compatible)"
    echo "  2) Local   — загрузить модель локально (SentenceTransformer)"
    echo ""
    local embed_choice
    read -rp "$(echo -e "${MAGENTA}[?]${NC} Выбор [1/2, default=1]: ")" embed_choice
    embed_choice="${embed_choice:-1}"

    if [ "$embed_choice" = "1" ]; then
        set_env "EMBEDDER_ENDPOINT" "$(ask 'Embedder Endpoint' "$(get_env EMBEDDER_ENDPOINT '')")"
        set_env "EMBEDDER_API_KEY" "$(ask 'Embedder API Key' "$(get_env EMBEDDER_API_KEY '')")"
        set_env "EMBEDDER_MODEL" "$(ask 'Embedder Model Name (e.g. bge-m3)' "$(get_env EMBEDDER_MODEL 'bge-m3')")"
        set_env "EMBEDDER_FALLBACK_LOCAL" "false"
    else
        set_env "EMBEDDER_MODEL" "$(ask 'Embedder Model Name (e.g. BAAI/bge-m3)' "$(get_env EMBEDDER_MODEL 'BAAI/bge-m3')")"
        set_env "EMBEDDER_DEVICE" "$(ask 'Device (cpu/cuda)' "$(get_env EMBEDDER_DEVICE 'cpu')")"
        set_env "EMBEDDER_ENDPOINT" ""
        set_env "EMBEDDER_FALLBACK_LOCAL" "true"
    fi

    # Reranker
    header "Reranker Model"
    echo "  1) Remote  — использовать удалённый сервис"
    echo "  2) Local   — загрузить модель локально (CrossEncoder)"
    echo "  3) None    — не использовать реранкер"
    echo ""
    local rerank_choice
    read -rp "$(echo -e "${MAGENTA}[?]${NC} Выбор [1/2/3, default=1]: ")" rerank_choice
    rerank_choice="${rerank_choice:-1}"

    if [ "$rerank_choice" = "1" ]; then
        set_env "RERANKER_ENDPOINT" "$(ask 'Reranker Endpoint' "$(get_env RERANKER_ENDPOINT '')")"
        set_env "RERANKER_API_KEY" "$(ask 'Reranker API Key' "$(get_env RERANKER_API_KEY '')")"
        set_env "RERANKER_MODEL" "$(ask 'Reranker Model Name' "$(get_env RERANKER_MODEL 'bge-reranker-v2-m3')")"
        set_env "RERANKER_FALLBACK_LOCAL" "false"
    elif [ "$rerank_choice" = "2" ]; then
        set_env "RERANKER_MODEL" "$(ask 'Reranker Model Name' "$(get_env RERANKER_MODEL 'cross-encoder/ms-marco-MiniLM-L-6-v2')")"
        set_env "RERANKER_ENDPOINT" ""
        set_env "RERANKER_FALLBACK_LOCAL" "true"
    else
        set_env "RERANKER_MODEL" ""
        set_env "RERANKER_ENDPOINT" ""
    fi

    # SSL
    header "SSL / TLS"
    if confirm "Корпоративная среда с самоподписанными сертификатами?" "n"; then
        set_env "SSL_VERIFY" "false"
        set_env "SSL_CERT_PATH" "$(ask 'Путь к CA bundle (пусто = отключить проверку)' "$(get_env SSL_CERT_PATH '')")"
    else
        set_env "SSL_VERIFY" "true"
    fi

    # Optional components
    if [ "$profile" = "2" ] || [ "$profile" = "3" ]; then
        header "Optional Components"
        if confirm "Включить Redis кэш?" "y"; then
            set_env "USE_REDIS" "true"
            set_env "REDIS_URL" "$(ask 'Redis URL' "$(get_env REDIS_URL 'redis://localhost:6379')")"
        fi
        if confirm "Включить Knowledge Graph (Neo4j)?" "y"; then
            set_env "GRAPH_ENABLED" "true"
            set_env "NEO4J_URI" "$(ask 'Neo4j URI' "$(get_env NEO4J_URI 'bolt://localhost:7687')")"
            set_env "NEO4J_USER" "$(ask 'Neo4j User' "$(get_env NEO4J_USER 'neo4j')")"
            set_env "NEO4J_PASSWORD" "$(ask 'Neo4j Password' "$(get_env NEO4J_PASSWORD '')")"
        fi
        if confirm "Включить LangGraph агентный оркестратор?" "n"; then
            set_env "USE_LANGGRAPH" "true"
        fi
    fi

    if [ "$profile" = "3" ]; then
        header "MinIO Object Storage"
        if confirm "Включить MinIO для файлов?" "y"; then
            set_env "MINIO_ENDPOINT" "$(ask 'MinIO Endpoint' "$(get_env MINIO_ENDPOINT 'localhost:9000')")"
            set_env "MINIO_ACCESS_KEY" "$(ask 'MinIO Access Key' "$(get_env MINIO_ACCESS_KEY '')")"
            set_env "MINIO_SECRET_KEY" "$(ask 'MinIO Secret Key' "$(get_env MINIO_SECRET_KEY '')")"
        fi
        header "Monitoring"
        if confirm "Включить Prometheus метрики?" "y"; then
            set_env "METRICS_ENABLED" "true"
        fi
    fi

    # Auth
    header "Authentication"
    if confirm "Включить JWT аутентификацию?" "n"; then
        set_env "AUTH_ENABLED" "true"
        local jwt_secret
        jwt_secret=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p)
        set_env "JWT_SECRET" "$jwt_secret"
        log "JWT_SECRET сгенерирован"
        if confirm "Включить RBAC (ролевой доступ)?" "n"; then
            set_env "RBAC_ENABLED" "true"
        fi
    fi

    # Build proxy
    header "Build Proxy Image"
    if confirm "Собрать образ прокси сейчас?" "y"; then
        do_build_proxy
    fi

    # Start services
    header "Start Services"
    if confirm "Запустить сервисы?" "y"; then
        do_start_services
    fi

    # ETL setup
    if [ "$profile" = "2" ] || [ "$profile" = "3" ]; then
        header "ETL Setup"
        if confirm "Настроить ETL пайплайн?" "y"; then
            do_etl_setup
        fi
    fi

    # OpenWebUI (optional for all profiles)
    header "OpenWebUI (optional)"
    if confirm "Установить OpenWebUI веб-интерфейс?" "n"; then
        do_openwebui_setup
    fi

    # Summary
    do_status
}

# ═══════════════════════════════════════════════════════════════════════════════
# 2. CONFIGURE
# ═══════════════════════════════════════════════════════════════════════════════
do_configure() {
    header "Configure Existing Installation"

    if [ ! -f "$ENV_FILE" ]; then
        error "Файл $ENV_FILE не найден. Запустите сначала Install."
        return 1
    fi

    echo "Что настроить?"
    echo ""
    echo "  1)  LLM Endpoint"
    echo "  2)  Embedding Model"
    echo "  3)  Reranker Model"
    echo "  4)  SSL / TLS"
    echo "  5)  Authentication"
    echo "  6)  Redis / Cache"
    echo "  7)  Neo4j / Knowledge Graph"
    echo "  8)  MinIO / File Storage"
    echo "  9)  Rate Limiting"
    echo "  10) Logging"
    echo "  11) ETL Configuration"
    echo "  12) Показать текущую конфигурацию"
    echo "  0)  Назад"
    echo ""

    local choice
    read -rp "$(echo -e "${MAGENTA}[?]${NC} Выбор: ")" choice

    case "$choice" in
        1)
            header "LLM Endpoint"
            set_env "LLM_ENDPOINT" "$(ask 'LLM Endpoint' "$(get_env LLM_ENDPOINT)")"
            set_env "LLM_MODEL_NAME" "$(ask 'Model Name' "$(get_env LLM_MODEL_NAME)")"
            set_env "LLM_API_KEY" "$(ask 'API Key' "$(get_env LLM_API_KEY)")"
            log "LLM настроен"
            ;;
        2)
            header "Embedding Model"
            echo "  1) Remote"
            echo "  2) Local"
            local ec
            read -rp "$(echo -e "${MAGENTA}[?]${NC} Выбор [1/2]: ")" ec
            if [ "$ec" = "1" ]; then
                set_env "EMBEDDER_ENDPOINT" "$(ask 'Endpoint' "$(get_env EMBEDDER_ENDPOINT)")"
                set_env "EMBEDDER_API_KEY" "$(ask 'API Key' "$(get_env EMBEDDER_API_KEY)")"
                set_env "EMBEDDER_MODEL" "$(ask 'Model Name' "$(get_env EMBEDDER_MODEL)")"
                set_env "EMBEDDER_FALLBACK_LOCAL" "false"
            else
                set_env "EMBEDDER_MODEL" "$(ask 'Model Name' "$(get_env EMBEDDER_MODEL)")"
                set_env "EMBEDDER_DEVICE" "$(ask 'Device' "$(get_env EMBEDDER_DEVICE)")"
                set_env "EMBEDDER_ENDPOINT" ""
                set_env "EMBEDDER_FALLBACK_LOCAL" "true"
            fi
            log "Embedder настроен"
            ;;
        3)
            header "Reranker Model"
            echo "  1) Remote"
            echo "  2) Local"
            echo "  3) None"
            local rc
            read -rp "$(echo -e "${MAGENTA}[?]${NC} Выбор [1/2/3]: ")" rc
            if [ "$rc" = "1" ]; then
                set_env "RERANKER_ENDPOINT" "$(ask 'Endpoint' "$(get_env RERANKER_ENDPOINT)")"
                set_env "RERANKER_API_KEY" "$(ask 'API Key' "$(get_env RERANKER_API_KEY)")"
                set_env "RERANKER_MODEL" "$(ask 'Model Name' "$(get_env RERANKER_MODEL)")"
                set_env "RERANKER_FALLBACK_LOCAL" "false"
            elif [ "$rc" = "2" ]; then
                set_env "RERANKER_MODEL" "$(ask 'Model Name' "$(get_env RERANKER_MODEL)")"
                set_env "RERANKER_ENDPOINT" ""
                set_env "RERANKER_FALLBACK_LOCAL" "true"
            else
                set_env "RERANKER_MODEL" ""
                set_env "RERANKER_ENDPOINT" ""
            fi
            log "Reranker настроен"
            ;;
        4)
            header "SSL / TLS"
            local sv
            sv=$(ask 'Verify SSL (true/false)' "$(get_env SSL_VERIFY 'true')")
            set_env "SSL_VERIFY" "$sv"
            if [ "$sv" = "false" ]; then
                set_env "SSL_CERT_PATH" "$(ask 'CA Bundle Path' "$(get_env SSL_CERT_PATH)")"
            fi
            log "SSL настроен"
            ;;
        5)
            header "Authentication"
            local av
            av=$(ask 'Enable Auth (true/false)' "$(get_env AUTH_ENABLED 'false')")
            set_env "AUTH_ENABLED" "$av"
            if [ "$av" = "true" ]; then
                set_env "JWT_SECRET" "$(ask 'JWT Secret' "$(get_env JWT_SECRET)")"
                local rv
                rv=$(ask 'Enable RBAC (true/false)' "$(get_env RBAC_ENABLED 'false')")
                set_env "RBAC_ENABLED" "$rv"
            fi
            log "Auth настроен"
            ;;
        6)
            header "Redis / Cache"
            local rdis
            rdis=$(ask 'Enable Redis (true/false)' "$(get_env USE_REDIS 'false')")
            set_env "USE_REDIS" "$rdis"
            if [ "$rdis" = "true" ]; then
                set_env "REDIS_URL" "$(ask 'Redis URL' "$(get_env REDIS_URL 'redis://localhost:6379')")"
            fi
            log "Redis настроен"
            ;;
        7)
            header "Neo4j / Knowledge Graph"
            local gv
            gv=$(ask 'Enable Graph (true/false)' "$(get_env GRAPH_ENABLED 'false')")
            set_env "GRAPH_ENABLED" "$gv"
            if [ "$gv" = "true" ]; then
                set_env "NEO4J_URI" "$(ask 'Neo4j URI' "$(get_env NEO4J_URI)")"
                set_env "NEO4J_USER" "$(ask 'Neo4j User' "$(get_env NEO4J_USER)")"
                set_env "NEO4J_PASSWORD" "$(ask 'Neo4j Password' "$(get_env NEO4J_PASSWORD)")"
            fi
            log "Neo4j настроен"
            ;;
        8)
            header "MinIO / File Storage"
            set_env "MINIO_ENDPOINT" "$(ask 'MinIO Endpoint' "$(get_env MINIO_ENDPOINT)")"
            set_env "MINIO_ACCESS_KEY" "$(ask 'Access Key' "$(get_env MINIO_ACCESS_KEY)")"
            set_env "MINIO_SECRET_KEY" "$(ask 'Secret Key' "$(get_env MINIO_SECRET_KEY)")"
            log "MinIO настроен"
            ;;
        9)
            header "Rate Limiting"
            local rl
            rl=$(ask 'Enable Rate Limiting (true/false)' "$(get_env RATE_LIMIT_ENABLED 'false')")
            set_env "RATE_LIMIT_ENABLED" "$rl"
            if [ "$rl" = "true" ]; then
                set_env "RATE_LIMIT_PER_MINUTE" "$(ask 'Requests per minute' "$(get_env RATE_LIMIT_PER_MINUTE '60')")"
                set_env "RATE_LIMIT_BURST" "$(ask 'Burst limit' "$(get_env RATE_LIMIT_BURST '10')")"
            fi
            log "Rate Limiting настроен"
            ;;
        10)
            header "Logging"
            set_env "LOG_LEVEL" "$(ask 'Log Level (DEBUG/INFO/WARNING/ERROR)' "$(get_env LOG_LEVEL 'INFO')")"
            set_env "LOG_FORMAT" "$(ask 'Log Format (text/json)' "$(get_env LOG_FORMAT 'text')")"
            local lr
            lr=$(ask 'Log Requests (true/false)' "$(get_env LOG_REQUESTS 'false')")
            set_env "LOG_REQUESTS" "$lr"
            log "Logging настроен"
            ;;
        11)
            do_etl_configure
            ;;
        12)
            do_status
            ;;
        0)
            return 0
            ;;
        *)
            error "Неверный выбор"
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════════
# 3. EXPAND
# ═══════════════════════════════════════════════════════════════════════════════
do_expand() {
    header "Expand System"

    echo "Добавить компонент:"
    echo ""
    echo "  1)  MinIO           — объектное хранилище для файлов"
    echo "  2)  Monitoring      — Prometheus + Grafana"
    echo "  3)  OpenWebUI       — веб-интерфейс для чата"
    echo "  4)  MCP Server      — для OpenCode / Claude Desktop"
    echo "  5)  Auth            — JWT аутентификация"
    echo "  6)  Rate Limiting   — ограничение запросов"
    echo "  7)  Tools           — система инструментов"
    echo "  8)  ETL Sources     — добавить источники данных"
    echo "  9)  Knowledge Graph — Neo4j граф знаний"
    echo "  10) LangGraph       — агентный оркестратор"
    echo "  0)  Назад"
    echo ""

    local choice
    read -rp "$(echo -e "${MAGENTA}[?]${NC} Выбор: ")" choice

    case "$choice" in
        1)
            header "Adding MinIO"
            set_env "MINIO_ENDPOINT" "$(ask 'MinIO Endpoint' 'localhost:9000')"
            set_env "MINIO_ACCESS_KEY" "$(ask 'Access Key' 'minioadmin')"
            set_env "MINIO_SECRET_KEY" "$(ask 'Secret Key' 'minioadmin')"
            set_env "MINIO_BUCKET" "$(ask 'Bucket Name' 'rag-documents')"
            log "MinIO добавлен"
            ;;
        2)
            header "Adding Monitoring"
            set_env "METRICS_ENABLED" "true"
            log "Мониторинг включён"
            info "Используйте: docker compose -f config/monitoring/docker-compose.monitoring.yml up -d"
            ;;
        3)
            do_openwebui_setup
            ;;
        4)
            header "Adding MCP Server"
            echo ""
            echo "Добавьте в opencode.json:"
            echo ""
            echo '  {'
            echo '    "mcp": {'
            echo '      "rag-system": {'
            echo '        "type": "local",'
            echo "        \"command\": [\"python\", \"$PROJECT_ROOT/mcp_server/server.py\"],"
            echo '        "env": {"RAG_PROXY_URL": "http://localhost:8080"}'
            echo '      }'
            echo '    }'
            echo '  }'
            echo ""
            log "MCP Server готов"
            ;;
        5)
            header "Adding Authentication"
            set_env "AUTH_ENABLED" "true"
            local jwt_secret
            jwt_secret=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p)
            set_env "JWT_SECRET" "$jwt_secret"
            log "JWT_SECRET сгенерирован"
            if confirm "Включить RBAC?" "n"; then
                set_env "RBAC_ENABLED" "true"
            fi
            ;;
        6)
            header "Adding Rate Limiting"
            set_env "RATE_LIMIT_ENABLED" "true"
            set_env "RATE_LIMIT_PER_MINUTE" "$(ask 'Requests per minute' '60')"
            set_env "RATE_LIMIT_BURST" "$(ask 'Burst limit' '10')"
            log "Rate Limiting включён"
            ;;
        7)
            header "Adding Tools"
            set_env "TOOLS_ENABLED" "true"
            if confirm "Включить Live Source Tools?" "n"; then
                set_env "LIVE_SOURCES_ENABLED" "true"
                set_env "CONFLUENCE_API_URL" "$(ask 'Confluence URL' '')"
                set_env "CONFLUENCE_API_TOKEN" "$(ask 'Confluence Token' '')"
                set_env "JIRA_API_URL" "$(ask 'Jira URL' '')"
                set_env "JIRA_API_TOKEN" "$(ask 'Jira Token' '')"
                set_env "GITLAB_API_URL" "$(ask 'GitLab URL' '')"
                set_env "GITLAB_API_TOKEN" "$(ask 'GitLab Token' '')"
            fi
            log "Tools включены"
            ;;
        8)
            do_etl_setup
            ;;
        9)
            header "Adding Knowledge Graph"
            set_env "GRAPH_ENABLED" "true"
            set_env "NEO4J_URI" "$(ask 'Neo4j URI' 'bolt://localhost:7687')"
            set_env "NEO4J_USER" "$(ask 'Neo4j User' 'neo4j')"
            set_env "NEO4J_PASSWORD" "$(ask 'Neo4j Password' '')"
            set_env "USE_GRAPH_EXPANSION" "true"
            log "Knowledge Graph включён"
            ;;
        10)
            header "Adding LangGraph"
            set_env "USE_LANGGRAPH" "true"
            set_env "MAX_RETRIEVAL_LOOPS" "$(ask 'Max retrieval loops' '3')"
            log "LangGraph включён"
            ;;
        0)
            return 0
            ;;
        *)
            error "Неверный выбор"
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════════════
# 4. ETL SETUP
# ═══════════════════════════════════════════════════════════════════════════════
do_etl_setup() {
    header "ETL Pipeline Setup"

    if [ ! -f "$ETL_CONFIG" ]; then
        error "Файл $ETL_CONFIG не найден"
        return 1
    fi

    echo "Настройка ETL пайплайна для загрузки данных из корпоративных систем"
    echo ""

    # Global timeout
    header "Global Settings"
    local timeout
    timeout=$(ask 'Request timeout (seconds)' "$(get_yaml timeout '30')")
    set_yaml timeout "$timeout"

    local connect_timeout
    connect_timeout=$(ask 'Connect timeout (seconds)' "$(get_yaml connect_timeout '10')")
    set_yaml connect_timeout "$connect_timeout"

    # Confluence
    header "Confluence"
    if confirm "Настроить Confluence?" "y"; then
        local url
        url=$(ask 'Confluence URL' "$(get_yaml url 'https://confluence.internal.company.com')")
        set_yaml url "\"$url\""

        local token
        token=$(ask 'Confluence Token (Bearer)' "$(get_yaml token '')")
        set_yaml token "\"$token\""

        local verify_ssl
        verify_ssl=$(ask 'Verify SSL (true/false)' "$(get_yaml verify_ssl 'false')")
        set_yaml verify_ssl "$verify_ssl"

        log "Confluence настроен"
    fi

    # Jira
    header "Jira"
    if confirm "Настроить Jira?" "y"; then
        local url
        url=$(ask 'Jira URL' "$(get_yaml url 'https://jira.internal.company.com')")
        set_yaml url "\"$url\""

        local token
        token=$(ask 'Jira Token' "$(get_yaml token '')")
        set_yaml token "\"$token\""

        local verify_ssl
        verify_ssl=$(ask 'Verify SSL (true/false)' "$(get_yaml verify_ssl 'false')")
        set_yaml verify_ssl "$verify_ssl"

        log "Jira настроен"
    fi

    # GitLab
    header "GitLab"
    if confirm "Настроить GitLab?" "y"; then
        local url
        url=$(ask 'GitLab URL' "$(get_yaml url 'https://gitlab.internal.company.com')")
        set_yaml url "\"$url\""

        local token
        token=$(ask 'GitLab Token' "$(get_yaml token '')")
        set_yaml token "\"$token\""

        local verify_ssl
        verify_ssl=$(ask 'Verify SSL (true/false)' "$(get_yaml verify_ssl 'false')")
        set_yaml verify_ssl "$verify_ssl"

        log "GitLab настроен"
    fi

    # Test connection
    if confirm "Проверить подключение?" "y"; then
        do_etl_test_connection
    fi
}

do_etl_configure() {
    header "ETL Configuration"
    do_etl_setup
}

do_etl_test_connection() {
    header "Testing ETL Connections"

    if [ ! -f "$ETL_CONFIG" ]; then
        error "Файл $ETL_CONFIG не найден"
        return 1
    fi

    info "Запускаю проверку подключения..."
    python -m etl.scheduler.run_etl --config "$ETL_CONFIG" --test-connection
}

do_etl_run() {
    header "Running ETL Pipeline"

    if [ ! -f "$ETL_CONFIG" ]; then
        error "Файл $ETL_CONFIG не найден"
        return 1
    fi

    local timeout
    timeout=$(ask 'Timeout (seconds, empty = from config)' "")
    local timeout_arg=""
    if [ -n "$timeout" ]; then
        timeout_arg="--timeout $timeout"
    fi

    info "Запускаю ETL пайплайн..."
    python -m etl.scheduler.run_etl --config "$ETL_CONFIG" $timeout_arg
}

# ═══════════════════════════════════════════════════════════════════════════════
# 5. PROXY BUILD
# ═══════════════════════════════════════════════════════════════════════════════
do_build_proxy() {
    header "Building Proxy Image"

    if [ ! -f "$PROJECT_ROOT/Dockerfile.proxy" ]; then
        error "Dockerfile.proxy не найден"
        return 1
    fi

    info "Собираю образ rag-proxy:latest..."
    docker build -f "$PROJECT_ROOT/Dockerfile.proxy" -t rag-proxy:latest "$PROJECT_ROOT"

    log "Образ собран: rag-proxy:latest"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 6. DOCKER
# ═══════════════════════════════════════════════════════════════════════════════
do_docker() {
    header "Docker Management"

    echo "Действие:"
    echo ""
    echo "  1) Start          — запустить все сервисы"
    echo "  2) Stop           — остановить все сервисы"
    echo "  3) Restart        — перезапустить все сервисы"
    echo "  4) Logs           — показать логи"
    echo "  5) Status         — показать статус"
    echo "  6) Clean          — удалить контейнеры и volumes"
    echo "  7) Build & Start  — собрать образ и запустить"
    echo "  0) Назад"
    echo ""

    local choice
    read -rp "$(echo -e "${MAGENTA}[?]${NC} Выбор: ")" choice

    local compose_cmd
    compose_cmd=$(get_compose_cmd)

    case "$choice" in
        1) $compose_cmd -f "$COMPOSE_FILE" up -d ;;
        2) $compose_cmd -f "$COMPOSE_FILE" down ;;
        3) $compose_cmd -f "$COMPOSE_FILE" restart ;;
        4) $compose_cmd -f "$COMPOSE_FILE" logs -f ;;
        5) $compose_cmd -f "$COMPOSE_FILE" ps ;;
        6)
            if confirm "Удалить все контейнеры и volumes?" "n"; then
                $compose_cmd -f "$COMPOSE_FILE" down -v
            fi
            ;;
        7)
            do_build_proxy
            $compose_cmd -f "$COMPOSE_FILE" up -d
            ;;
        0) return 0 ;;
        *) error "Неверный выбор" ;;
    esac
}

do_start_services() {
    header "Starting Services"

    if [ ! -f "$COMPOSE_FILE" ]; then
        error "Файл $COMPOSE_FILE не найден"
        return 1
    fi

    local compose_cmd
    compose_cmd=$(get_compose_cmd)

    if [ -z "$compose_cmd" ]; then
        error "Docker Compose не найден"
        return 1
    fi

    info "Запускаю сервисы..."
    $compose_cmd -f "$COMPOSE_FILE" up -d

    echo ""
    info "Ожидание запуска сервисов..."
    sleep 5

    local max_attempts=30 attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if curl -sf http://localhost:8080/v1/health/live >/dev/null 2>&1; then
            log "Proxy запущен: http://localhost:8080"
            break
        fi
        attempt=$((attempt + 1))
        sleep 2
    done

    if [ $attempt -ge $max_attempts ]; then
        warn "Proxy не отвечает. Проверьте логи: $compose_cmd -f $COMPOSE_FILE logs"
    fi

    echo ""
    log "Сервисы запущены"
    info "  Proxy:   http://localhost:8080"
    info "  Qdrant:  http://localhost:6333"
    info "  Neo4j:   http://localhost:7474"
    info "  Redis:   http://localhost:6379"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 7. OPENWEBUI
# ═══════════════════════════════════════════════════════════════════════════════
do_openwebui_setup() {
    header "OpenWebUI Setup"

    info "OpenWebUI — веб-интерфейс для чата с RAG системой"
    echo ""

    # Check if compose file exists
    if [ ! -f "$OPENWEBUI_COMPOSE" ]; then
        error "Файл $OPENWEBUI_COMPOSE не найден"
        return 1
    fi

    # Configure
    local api_key
    api_key=$(ask 'OpenWebUI API Key (для подключения к прокси)' "sk-rag-proxy")
    set_env "OPENWEBUI_API_KEY" "$api_key"

    # Build proxy image if not exists
    if ! docker image inspect rag-proxy:latest >/dev/null 2>&1; then
        warn "Образ rag-proxy:latest не найден"
        if confirm "Собрать образ сейчас?" "y"; then
            do_build_proxy
        fi
    fi

    # Start
    if confirm "Запустить OpenWebUI?" "y"; then
        local compose_cmd
        compose_cmd=$(get_compose_cmd)

        info "Запускаю OpenWebUI..."
        $compose_cmd -f "$OPENWEBUI_COMPOSE" up -d

        echo ""
        log "OpenWebUI запущен"
        info "  OpenWebUI: http://localhost:3000"
        info "  Proxy:     http://localhost:8080"
        echo ""
        info "Первый пользователь = админ"
        info "В Settings → Connections укажите:"
        info "  OpenAI API: http://rag-proxy:8080/v1"
        info "  API Key: $api_key"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# 8. STATUS
# ═══════════════════════════════════════════════════════════════════════════════
do_status() {
    header "System Status"

    # Docker containers
    echo "Docker Containers:"
    if command -v docker >/dev/null 2>&1; then
        docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -20 || echo "  Нет запущенных контейнеров"
    else
        echo "  Docker не установлен"
    fi
    echo ""

    # Health checks
    echo "Health Checks:"
    if curl -sf http://localhost:8080/v1/health/live >/dev/null 2>&1; then
        log "Proxy: OK (http://localhost:8080)"
    else
        warn "Proxy: не отвечает"
    fi
    echo ""

    # Config
    show_config
}

show_config() {
    header "Current Configuration"

    if [ ! -f "$ENV_FILE" ]; then
        warn "Файл $ENV_FILE не найден"
        return 1
    fi

    echo "Proxy:"
    echo "  LLM Endpoint:      $(get_env LLM_ENDPOINT)"
    echo "  LLM Model:         $(get_env LLM_MODEL_NAME)"
    echo "  Embedder Model:    $(get_env EMBEDDER_MODEL)"
    echo "  Embedder Endpoint: $(get_env EMBEDDER_ENDPOINT '—')"
    echo "  Reranker Model:    $(get_env RERANKER_MODEL)"
    echo "  Reranker Endpoint: $(get_env RERANKER_ENDPOINT '—')"
    echo ""
    echo "Components:"
    echo "  Redis:             $(get_env USE_REDIS 'false')"
    echo "  Neo4j:             $(get_env GRAPH_ENABLED 'false')"
    echo "  LangGraph:         $(get_env USE_LANGGRAPH 'false')"
    echo "  MinIO:             $(get_env MINIO_ENDPOINT '—')"
    echo "  Auth:              $(get_env AUTH_ENABLED 'false')"
    echo "  RBAC:              $(get_env RBAC_ENABLED 'false')"
    echo "  Rate Limiting:     $(get_env RATE_LIMIT_ENABLED 'false')"
    echo "  Metrics:           $(get_env METRICS_ENABLED 'false')"
    echo "  Tools:             $(get_env TOOLS_ENABLED 'false')"
    echo ""
    echo "SSL:"
    echo "  Verify:            $(get_env SSL_VERIFY 'true')"
    echo "  CA Bundle:         $(get_env SSL_CERT_PATH '—')"

    if [ -f "$ETL_CONFIG" ]; then
        echo ""
        echo "ETL:"
        echo "  Timeout:           $(get_yaml timeout '30')s"
        echo "  Connect Timeout:   $(get_yaml connect_timeout '10')s"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# 9. TEST
# ═══════════════════════════════════════════════════════════════════════════════
do_test() {
    header "Running Tests"

    if confirm "Запустить pytest?" "y"; then
        python -m pytest tests/proxy/ tests/etl/ tests/integration/ -q --tb=short --ignore=tests/performance --ignore=tests/e2e --ignore=tests/resilience
    fi

    if confirm "Проверить Ruff lint?" "y"; then
        python -m ruff check proxy/ etl/ tests/
    fi

    if confirm "Проверить ETL подключение?" "y"; then
        do_etl_test_connection
    fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
main() {
    case "${1:-}" in
        install)    do_install; exit 0 ;;
        configure)  do_configure; exit 0 ;;
        expand)     do_expand; exit 0 ;;
        etl)        do_etl_run; exit 0 ;;
        build)      do_build_proxy; exit 0 ;;
        openwebui)  do_openwebui_setup; exit 0 ;;
        status)     do_status; exit 0 ;;
        test)       do_test; exit 0 ;;
        docker)     do_docker; exit 0 ;;
    esac

    while true; do
        show_menu
        local choice
        read -rp "$(echo -e "${MAGENTA}[?]${NC} Выбор: ")" choice

        case "$choice" in
            1) do_install ;;
            2) do_configure ;;
            3) do_expand ;;
            4) do_etl_setup ;;
            5) do_build_proxy ;;
            6) do_docker ;;
            7) do_openwebui_setup ;;
            8) do_status ;;
            9) do_test ;;
            0)
                echo -e "\n${GREEN}До свидания!${NC}\n"
                exit 0
                ;;
            *)
                error "Неверный выбор"
                ;;
        esac
    done
}

main "$@"
