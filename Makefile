# RAG System Makefile
# Primary entry point for development, testing, and deployment workflows.

.PHONY: help install install-dev test test-proxy test-etl test-integration \
        lint format typecheck clean docker-build docker-up docker-down docs all

SHELL := /bin/bash
ROOT  := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

# ── Setup ──────────────────────────────────────────────────────────────────
install: ## Run full setup (proxy + ETL)
	@bash $(ROOT)/setup.sh --full

install-dev: ## Run setup with dev dependencies (lint, test, typecheck)
	@bash $(ROOT)/setup.sh --dev

# ── Testing ────────────────────────────────────────────────────────────────
test: ## Run all tests
	@cd $(ROOT) && python -m pytest tests/ -v

test-proxy: ## Run proxy unit tests
	@cd $(ROOT) && python -m pytest tests/proxy/ -v

test-etl: ## Run ETL unit tests
	@cd $(ROOT) && python -m pytest tests/etl/ -v

test-integration: ## Run integration tests
	@cd $(ROOT) && python -m pytest tests/integration/ -v

# ── Code quality ───────────────────────────────────────────────────────────
lint: ## Lint with ruff
	@cd $(ROOT) && ruff check .

format: ## Format with ruff
	@cd $(ROOT) && ruff format .

format-check: ## Check formatting without changes
	@cd $(ROOT) && ruff format --check .

typecheck: ## Run mypy static type checker
	@cd $(ROOT) && mypy proxy/ etl/ --exclude '.venv|__pycache__'

# ── Cleanup ────────────────────────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	@find $(ROOT) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	@find $(ROOT) -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
	@find $(ROOT) -type d -name '.mypy_cache' -exec rm -rf {} + 2>/dev/null || true
	@find $(ROOT) -type d -name '.ruff_cache' -exec rm -rf {} + 2>/dev/null || true
	@find $(ROOT) -type f -name '*.pyc' -delete
	@find $(ROOT) -type f -name '*.pyo' -delete
	@find $(ROOT) -type f -name '.DS_Store' -delete
	@echo "Cleaned build artifacts and caches"

# ── Docker ─────────────────────────────────────────────────────────────────
docker-build: ## Build Docker images
	@cd $(ROOT)/proxy && docker-compose build

docker-up: ## Start docker-compose services (detached)
	@cd $(ROOT)/proxy && docker-compose up -d

docker-down: ## Stop docker-compose services
	@cd $(ROOT)/proxy && docker-compose down

docker-logs: ## Tail docker-compose logs
	@cd $(ROOT)/proxy && docker-compose logs -f

# ── Documentation ──────────────────────────────────────────────────────────
docs: ## Show documentation locations
	@echo "Documentation:"
	@echo "  Architecture: docs/"
	@echo "  AGENTS.md:    project structure and conventions"
	@echo "  README.md:    project overview"

# ── CI pipeline (all-in-one) ───────────────────────────────────────────────
all: install lint test ## Install deps, lint, then run all tests

# ── Help ───────────────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
