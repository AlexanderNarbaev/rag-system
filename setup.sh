#!/usr/bin/env bash
# setup.sh — RAG System environment bootstrap
# Run from repo root: ./setup.sh [--proxy-only|--etl-only|--dev|--full]
# Idempotent: safe to run multiple times.

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()  { echo -e "${GREEN}[OK]${NC}    $*"; }
fail(){ echo -e "${RED}[FAIL]${NC}  $*"; }
warn(){ echo -e "${YELLOW}[WARN]${NC}  $*"; }
info(){ echo -e "${CYAN}[INFO]${NC}  $*"; }
step(){ echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

# ── Flags ─────────────────────────────────────────────────────────────────
PROXY=true; ETL=true; DEV=false
case "${1:-}" in
  --proxy-only) ETL=false ;;
  --etl-only)   PROXY=false ;;
  --dev)        DEV=true ;;
  --full)       ;;  # both components, no dev extras
  "")           ;;  # default: both components
  *) echo "Usage: $0 [--proxy-only|--etl-only|--dev|--full]"; exit 1 ;;
esac

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PROXY="$ROOT/proxy/.venv"
VENV_ETL="$ROOT/etl/.venv"

# ── Helper functions ──────────────────────────────────────────────────────
require_cmd() {
  command -v "$1" &>/dev/null && ok "Found: $1 ($(command -v "$1"))" || {
    fail "Missing required command: $1 — please install it first"
    MISSING_CMDS+=("$1")
  }
}

ensure_dir() { mkdir -p "$1" && ok "Directory: $1"; }

copy_if_missing() {
  local src="$1" dst="$2"
  if [ ! -f "$dst" ]; then
    cp "$src" "$dst" && ok "Created: $dst (from $src)"
  else
    ok "Exists: $dst"
  fi
}

venv_create() {
  local venv_path="$1" label="$2"
  if [ ! -d "$venv_path" ]; then
    python3 -m venv "$venv_path" && ok "Virtualenv created: $label"
  else
    ok "Virtualenv exists: $label"
  fi
}

venv_pip_install() {
  local venv_path="$1" req_file="$2" label="$3"
  source "$venv_path/bin/activate"
  pip install --upgrade pip -q
  pip install -r "$req_file" -q && ok "Dependencies installed: $label" || fail "Dependency install failed: $label"
  if [ "$DEV" = true ]; then
    pip install pytest pytest-asyncio pytest-cov pytest-mock ruff mypy -q && ok "Dev deps installed: $label" || fail "Dev deps failed: $label"
  fi
  deactivate 2>/dev/null || true
}

# ── Step 1: System checks ─────────────────────────────────────────────────
step "System prerequisites"
MISSING_CMDS=()
require_cmd python3
require_cmd pip
require_cmd curl
require_cmd git
if [ ${#MISSING_CMDS[@]} -gt 0 ]; then
  fail "Install missing commands and re-run."
  exit 1
fi

PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$(printf '%s\n' "3.11" "$PYTHON_VER" | sort -V | head -1)" != "3.11" ]; then
  fail "Python >= 3.11 required, found $PYTHON_VER"
  exit 1
fi
ok "Python version: $PYTHON_VER"

# ── Step 2: Directories ───────────────────────────────────────────────────
step "Creating directories"
ensure_dir "$ROOT/logs"
ensure_dir "$ROOT/cache"
ensure_dir "$ROOT/data"

# ── Step 3: Proxy setup ───────────────────────────────────────────────────
if [ "$PROXY" = true ]; then
  step "Proxy environment"
  venv_create "$VENV_PROXY" "proxy"
  venv_pip_install "$VENV_PROXY" "$ROOT/requirements-proxy.txt" "proxy"
  copy_if_missing "$ROOT/.env.example" "$ROOT/proxy/.env"
fi

# ── Step 4: ETL setup ─────────────────────────────────────────────────────
if [ "$ETL" = true ]; then
  step "ETL environment"
  venv_create "$VENV_ETL" "etl"
  venv_pip_install "$VENV_ETL" "$ROOT/requirements-etl.txt" "etl"
  copy_if_missing "$ROOT/etl/.env.example" "$ROOT/etl/.env"

  info "SpaCy models may need manual download:"
  info "  source $VENV_ETL/bin/activate"
  info "  python -m spacy download ru_core_news_sm"
  info "  python -m spacy download en_core_web_sm"
fi

# ── Step 5: Pre-commit hooks (dev only) ───────────────────────────────────
if [ "$DEV" = true ]; then
  step "Pre-commit hooks"
  require_cmd pre-commit
  if [ ${#MISSING_CMDS[@]} -eq 0 ]; then
    (cd "$ROOT" && pre-commit install) && ok "Pre-commit hooks installed"
  else
    warn "pre-commit not found, skipping hook install"
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   RAG System setup complete          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo "Proxy venv:  source $VENV_PROXY/bin/activate"
echo "ETL venv:    source $VENV_ETL/bin/activate"
echo "Next steps:"
echo "  make docker-up        # Start services"
echo "  make test             # Run tests"
echo "  make all              # Install, lint, test"
