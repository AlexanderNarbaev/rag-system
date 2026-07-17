#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# init-openwebui.sh — Инициализация и запуск OpenWebUI для RAG-системы
# ═══════════════════════════════════════════════════════════════════════════════
# Назначение: Подготовка окружения, генерация секретов, создание ресурсов,
#              запуск автономного OpenWebUI с PostgreSQL + Redis + Tika.
#
# Использование:
#   chmod +x scripts/init-openwebui.sh
#   ./scripts/init-openwebui.sh              # Интерактивный режим
#   ./scripts/init-openwebui.sh --auto       # Автоматический режим (без вопросов)
#   ./scripts/init-openwebui.sh --recreate   # Полная переустановка (удалить все данные)
#
# Требования:
#   - Docker 24+ и Docker Compose v2
#   - Запущенный RAG Proxy в сети rag-network
#   - Доступ к MinIO (minio:9000 в rag-network)
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Цвета для вывода ──────────────────────────────────────────────────────────
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly BOLD='\033[1m'
readonly NC='\033[0m' # No Color

# ── Пути ──────────────────────────────────────────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
readonly COMPOSE_DIR="$PROJECT_ROOT/deploy/docker"
readonly COMPOSE_FILE="$COMPOSE_DIR/docker-compose.openwebui.yml"
readonly ENV_FILE="$COMPOSE_DIR/.env.openwebui"
readonly MINIO_ENDPOINT="http://minio:9000"
readonly MINIO_BUCKET="openwebui-files"
readonly POSTGRES_PASSWORD_LENGTH=24
readonly SECRET_KEY_LENGTH=32

# ── Флаги ─────────────────────────────────────────────────────────────────────
AUTO_MODE=false
RECREATE_MODE=false
SKIP_CHECKS=false

# ── Функции ───────────────────────────────────────────────────────────────────

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

# ── Проверка аргументов командной строки ─────────────────────────────────────
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
                echo "Использование: $0 [--auto] [--recreate] [--skip-checks]"
                echo ""
                echo "  --auto, -a       Автоматический режим (без интерактивных вопросов)"
                echo "  --recreate, -r   Полная переустановка (удалить все тома и данные)"
                echo "  --skip-checks, -s Пропустить проверки зависимостей"
                echo "  --help, -h       Показать эту справку"
                exit 0
                ;;
            *)
                log_error "Неизвестный аргумент: $arg"
                echo "Используйте --help для справки"
                exit 1
                ;;
        esac
    done
}

# ── Проверка зависимостей ────────────────────────────────────────────────────
check_prerequisites() {
    log_section "Проверка зависимостей"

    if [ "$SKIP_CHECKS" = true ]; then
        log_warning "Проверки пропущены (--skip-checks)"
        return 0
    fi

    # Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker не установлен. Установите Docker 24.0+"
        exit 1
    fi
    local docker_version
    docker_version=$(docker --version 2>/dev/null | grep -oP '\d+\.\d+' | head -1 || echo "0.0")
    log_success "Docker: $(docker --version)"

    # Docker Compose v2
    if docker compose version &> /dev/null; then
        log_success "Docker Compose: $(docker compose version --short)"
    elif docker-compose version &> /dev/null; then
        log_warning "Найден старый docker-compose v1. Рекомендуется Docker Compose v2 (плагин)"
    else
        log_error "Docker Compose не найден. Установите Docker Compose v2"
        exit 1
    fi

    # openssl (для генерации секретов)
    if ! command -v openssl &> /dev/null; then
        log_warning "openssl не найден — секреты будут сгенерированы через /dev/urandom"
    fi

    # xxd (fallback для генерации секретов)
    if ! command -v xxd &> /dev/null; then
        log_warning "xxd не найден — убедитесь что openssl доступен для генерации секретов"
    fi

    # curl (для health-check и создания бакета)
    if ! command -v curl &> /dev/null; then
        log_warning "curl не найден — проверка health-check будет недоступна"
    fi

    # Проверка доступности docker socket
    if ! docker info &> /dev/null; then
        log_error "Docker не запущен или недостаточно прав. Запустите Docker daemon"
        exit 1
    fi

    log_success "Все зависимости удовлетворены"
}

# ── Проверка сети rag-network ─────────────────────────────────────────────────
check_rag_network() {
    log_section "Проверка сети rag-network"

    if docker network inspect rag-network &> /dev/null; then
        log_success "Сеть rag-network существует"
    else
        log_warning "Сеть rag-network не найдена. Она будет создана при запуске proxy."
        log_info "Убедитесь, что RAG Proxy запущен с сетью rag-network:"
        echo "       cd $PROJECT_ROOT/proxy && docker compose up -d"
        if ! confirm "Продолжить без rag-network?"; then
            exit 0
        fi
    fi
}

# ── Проверка доступности MinIO ────────────────────────────────────────────────
check_minio() {
    log_section "Проверка доступности MinIO"

    # Проверяем, запущен ли контейнер MinIO
    if docker ps --format '{{.Names}}' | grep -q 'rag-minio'; then
        log_success "Контейнер MinIO (rag-minio) запущен"
    else
        log_warning "Контейнер MinIO не найден. Убедитесь, что MinIO запущен в rag-network"
        if ! confirm "Продолжить без MinIO? (загрузка файлов будет недоступна)"; then
            exit 0
        fi
        return 0
    fi

    # Проверяем API MinIO
    if docker exec rag-minio curl -sf "$MINIO_ENDPOINT/minio/health/live" &> /dev/null; then
        log_success "MinIO API доступен"
    else
        log_warning "MinIO API недоступен. Проверьте состояние контейнера"
    fi
}

# ── Создание бакета MinIO ─────────────────────────────────────────────────────
create_minio_bucket() {
    log_section "Создание бакета MinIO: $MINIO_BUCKET"

    # Используем mc (MinIO Client) внутри контейнера MinIO
    if docker exec rag-minio mc alias list 2>/dev/null | grep -q 'local'; then
        log_info "Alias 'local' уже настроен в MinIO"
    else
        log_step "Настройка MinIO client alias..."
        docker exec rag-minio mc alias set local "$MINIO_ENDPOINT" minioadmin minioadmin &> /dev/null || true
    fi

    # Создаем бакет, если не существует
    if docker exec rag-minio mc ls local/$MINIO_BUCKET &> /dev/null; then
        log_success "Бакет '$MINIO_BUCKET' уже существует"
    else
        log_step "Создание бакета '$MINIO_BUCKET'..."
        if docker exec rag-minio mc mb local/$MINIO_BUCKET &> /dev/null; then
            log_success "Бакет '$MINIO_BUCKET' создан"
        else
            log_warning "Не удалось создать бакет. Возможно, он будет создан автоматически"
        fi
    fi
}

# ── Генерация секретов ────────────────────────────────────────────────────────
generate_secrets() {
    log_section "Генерация секретов"

    # WEBUI_SECRET_KEY
    local current_key
    current_key=$(grep -E '^WEBUI_SECRET_KEY=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || echo "")

    if [ -z "$current_key" ]; then
        local new_key
        new_key=$(generate_secret "$SECRET_KEY_LENGTH")
        log_step "Генерация WEBUI_SECRET_KEY..."

        # Обновление .env.openwebui
        if [ -f "$ENV_FILE" ]; then
            sed -i "s/^WEBUI_SECRET_KEY=.*/WEBUI_SECRET_KEY=$new_key/" "$ENV_FILE"
        fi
        log_success "WEBUI_SECRET_KEY сгенерирован"
        echo -e "       ${YELLOW}Секретный ключ:${NC} $new_key"
        echo -e "       ${YELLOW}СОХРАНИТЕ этот ключ в надежном месте!${NC} Он нужен для:"
        echo "       - Валидации JWT токенов при перезапуске"
        echo "       - Восстановления доступа к сессиям пользователей"
    else
        log_success "WEBUI_SECRET_KEY уже задан"
    fi

    # POSTGRES_PASSWORD
    local current_pg_pass
    current_pg_pass=$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || echo "")

    if [ -z "$current_pg_pass" ]; then
        local new_pg_pass
        new_pg_pass=$(generate_secret "$POSTGRES_PASSWORD_LENGTH")
        log_step "Генерация POSTGRES_PASSWORD..."

        if [ -f "$ENV_FILE" ]; then
            sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$new_pg_pass/" "$ENV_FILE"
        fi
        log_success "POSTGRES_PASSWORD сгенерирован"
        echo -e "       ${YELLOW}Пароль БД:${NC} $new_pg_pass"
    else
        log_success "POSTGRES_PASSWORD уже задан"
    fi
}

# ── Полная переустановка ──────────────────────────────────────────────────────
recreate_deployment() {
    log_section "Переустановка (удаление всех данных)"

    if [ "$RECREATE_MODE" = false ]; then
        return 0
    fi

    log_warning "ВНИМАНИЕ: Это удалит ВСЕ данные OpenWebUI — пользователей, чаты, файлы!"
    if ! confirm "Вы уверены? Введите 'yes' для подтверждения:"; then
        log_info "Переустановка отменена"
        RECREATE_MODE=false
        return 0
    fi

    local confirm_text
    read -r -p "Введите 'yes' для подтверждения: " confirm_text
    if [ "$confirm_text" != "yes" ]; then
        log_info "Переустановка отменена"
        RECREATE_MODE=false
        return 0
    fi

    log_step "Остановка контейнеров..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" down -v --timeout 30 2>/dev/null || true

    log_step "Удаление томов..."
    docker volume rm rag-openwebui-data rag-openwebui-tmp rag-openwebui-postgres rag-openwebui-redis 2>/dev/null || true

    log_step "Удаление сети openwebui-network..."
    docker network rm rag-openwebui-network 2>/dev/null || true

    log_success "Переустановка завершена. Все данные удалены."
}

# ── Запуск развертывания ──────────────────────────────────────────────────────
deploy_services() {
    log_section "Запуск сервисов OpenWebUI"

    log_step "Загрузка образов (это может занять время)..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" pull 2>&1 | grep -v "Pulling from\|Digest:\|Status:" || true

    log_step "Запуск контейнеров..."
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --wait --wait-timeout 120 2>&1 || {
        log_error "Не удалось запустить сервисы. Проверьте логи:"
        echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs"
        exit 1
    }

    log_success "Сервисы запущены"
}

# ── Проверка работоспособности ────────────────────────────────────────────────
health_check() {
    log_section "Проверка работоспособности"

    local openwebui_url="http://localhost:${OPENWEBUI_HOST_PORT:-3000}"

    if ! command -v curl &> /dev/null; then
        log_warning "curl не найден — пропускаем health-check"
        return 0
    fi

    # Ожидаем запуск OpenWebUI
    log_step "Ожидание готовности OpenWebUI..."
    local retries=12
    local delay=5

    for i in $(seq 1 $retries); do
        if curl -sf "$openwebui_url/health" &> /dev/null; then
            log_success "OpenWebUI отвечает ($openwebui_url)"
            break
        fi
        if [ "$i" -eq "$retries" ]; then
            log_warning "OpenWebUI не отвечает после $((retries * delay)) секунд."
            log_info "Проверьте логи: docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs openwebui"
            return 1
        fi
        echo -n "."
        sleep "$delay"
    done
    echo ""

    # Проверка PostgreSQL
    if docker exec rag-openwebui-postgres pg_isready -U openwebui &> /dev/null; then
        log_success "PostgreSQL: готов"
    else
        log_warning "PostgreSQL: не отвечает"
    fi

    # Проверка Redis
    if docker exec rag-openwebui-redis redis-cli ping &> /dev/null; then
        log_success "Redis: готов"
    else
        log_warning "Redis: не отвечает"
    fi

    # Проверка Tika
    if docker exec rag-openwebui-tika curl -sf http://localhost:9998/tika &> /dev/null; then
        log_success "Apache Tika: готов"
    else
        log_warning "Apache Tika: не отвечает"
    fi
}

# ── Инструкции по созданию администратора ─────────────────────────────────────
print_admin_instructions() {
    log_section "Создание учетной записи администратора"

    local openwebui_url="http://localhost:${OPENWEBUI_HOST_PORT:-3000}"

    echo ""
    echo -e "  ${BOLD}${GREEN}OpenWebUI развернут и готов к настройке!${NC}"
    echo ""
    echo -e "  ${BOLD}1. Откройте в браузере:${NC}"
    echo -e "     ${BLUE}$openwebui_url${NC}"
    echo ""
    echo -e "  ${BOLD}2. Создайте учетную запись администратора:${NC}"
    echo "     • Нажмите \"Sign up\" на странице входа"
    echo "     • Введите имя, email и пароль"
    echo "     • Эта учетная запись будет единственной с правами администратора"
    echo "     • После создания администратора регистрация будет отключена"
    echo ""
    echo -e "  ${BOLD}3. Настройте подключение к RAG Proxy:${NC}"
    echo "     • Перейдите: Admin Panel → Settings → Connections"
    echo "     • Проверьте OpenAI API: $OPENAI_API_BASE_URLS"
    echo "     • Убедитесь что модель 'rag' видна в списке моделей"
    echo ""
    echo -e "  ${BOLD}4. Управление пользователями:${NC}"
    echo "     • Admin Panel → Users — создание и активация учетных записей"
    echo "     • Самостоятельная регистрация отключена (корпоративное требование)"
    echo "     • Для Keycloak OIDC: Admin Panel → Settings → General → OAuth"
    echo ""
    echo -e "  ${BOLD}5. Полезные команды управления:${NC}"
    echo "     • Просмотр логов:"
    echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE logs -f openwebui"
    echo "     • Статус сервисов:"
    echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE ps"
    echo "     • Перезапуск:"
    echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE restart"
    echo "     • Остановка:"
    echo "       docker compose -f $COMPOSE_FILE --env-file $ENV_FILE down"
    echo ""
    echo -e "  ${BOLD}Сохраненные секреты:${NC}"
    echo "  WEBUI_SECRET_KEY:   из файла $ENV_FILE"
    echo "  POSTGRES_PASSWORD:  из файла $ENV_FILE"
    echo ""
    echo -e "  ${YELLOW}${BOLD}⚠ Сохраните эти секреты в корпоративном хранилище секретов!${NC}"
    echo ""
}

# ── Сводка развертывания ──────────────────────────────────────────────────────
print_summary() {
    log_section "Сводка развертывания"

    echo ""
    echo -e "  ${BOLD}Сервисы:${NC}"
    echo "  ├── OpenWebUI       → http://localhost:${OPENWEBUI_HOST_PORT:-3000}"
    echo "  ├── PostgreSQL      → postgres:5432 (внутренняя сеть)"
    echo "  ├── Redis           → redis:6379 (внутренняя сеть)"
    echo "  └── Apache Tika     → tika:9998 (внутренняя сеть)"
    echo ""
    echo -e "  ${BOLD}Внешние зависимости (сеть rag-network):${NC}"
    echo "  ├── RAG Proxy       → http://rag-proxy:8080/v1"
    echo "  └── MinIO           → http://minio:9000"
    echo ""
    echo -e "  ${BOLD}Файлы конфигурации:${NC}"
    echo "  ├── Compose:        $COMPOSE_FILE"
    echo "  └── Переменные:     $ENV_FILE"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# Главный процесс
# ═══════════════════════════════════════════════════════════════════════════════

main() {
    parse_args "$@"

    echo -e "${BLUE}${BOLD}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║   Инициализация OpenWebUI для корпоративной RAG-системы  ║"
    echo "║   Версия 2.0.0                                           ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    # Проверка compose файла
    if [ ! -f "$COMPOSE_FILE" ]; then
        log_error "Compose-файл не найден: $COMPOSE_FILE"
        exit 1
    fi

    # Проверка .env файла
    if [ ! -f "$ENV_FILE" ]; then
        log_error ".env файл не найден: $ENV_FILE"
        exit 1
    fi

    # 1. Проверка зависимостей
    check_prerequisites

    # 2. Проверка сети
    check_rag_network

    # 3. Проверка MinIO
    check_minio

    # 4. Генерация секретов
    generate_secrets

    # 5. Переустановка (если запрошена)
    recreate_deployment

    # 6. Создание бакета MinIO
    create_minio_bucket

    # 7. Запуск сервисов
    deploy_services

    # 8. Health-check
    health_check

    # 9. Сводка и инструкции
    print_summary
    print_admin_instructions

    log_success "Инициализация OpenWebUI завершена!"
}

main "$@"
