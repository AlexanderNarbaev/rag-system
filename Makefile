# RAG System Makefile
# Primary entry point for development, testing, and deployment workflows.

.PHONY: help install install-dev install-one-line setup wizard \
        test test-proxy test-etl test-integration \
        test-performance test-e2e test-resilience benchmark \
        benchmark-baselines benchmark-compare \
        lint format format-check typecheck clean \
        docker-build docker-up docker-down docker-logs run docs all \
        etl etl-confluence etl-jira etl-gitlab \
        backup restore dashboard tui mcp-server \
        deploy deploy-prod verify-backups \
        maturity-review maturity-review-json maturity-review-save \
        export-openapi

SHELL := /bin/bash
ROOT  := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

# ── Setup ─────────────────────────────────────────────────────────────────────
install: ## Run full setup (proxy + ETL)
	@bash $(ROOT)/setup.sh --full

install-dev: ## Run setup with dev dependencies (lint, test, typecheck)
	@bash $(ROOT)/setup.sh --dev

install-one-line: ## One-line install (clone + setup + start)
	@bash $(ROOT)/install.sh

wizard: ## Run configuration wizard
	@python $(ROOT)/scripts/setup_wizard.py

setup: ## Create .env from .env.example if missing
	@test -f $(ROOT)/proxy/.env || (cp $(ROOT)/.env.example $(ROOT)/proxy/.env && echo "Created proxy/.env from .env.example")
	@test -f $(ROOT)/etl/.env || (cp $(ROOT)/etl/.env.example $(ROOT)/etl/.env 2>/dev/null && echo "Created etl/.env" || true)

# ── Run ───────────────────────────────────────────────────────────────────────
run: ## Start proxy locally (requires .env and venv)
	@cd $(ROOT) && uvicorn proxy.app.main:app --host 0.0.0.0 --port 8080 --workers 1

# ── ETL ───────────────────────────────────────────────────────────────────────
etl: ## Run full ETL pipeline
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml

etl-confluence: ## Run Confluence extractor only
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --skip-graph --skip-index

etl-jira: ## Run Jira extractor only
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --skip-graph --skip-index

etl-gitlab: ## Run GitLab extractor only
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --skip-graph --skip-index

# ── Testing ───────────────────────────────────────────────────────────────────
test: ## Run all tests
	@cd $(ROOT) && python -m pytest tests/ -v

test-proxy: ## Run proxy unit tests
	@cd $(ROOT) && python -m pytest tests/proxy/ -v

test-etl: ## Run ETL unit tests
	@cd $(ROOT) && python -m pytest tests/etl/ -v

test-integration: ## Run integration tests
	@cd $(ROOT) && python -m pytest tests/integration/ -v

test-performance: ## Run performance and benchmark tests
	@cd $(ROOT) && python -m pytest tests/performance/ -v -m benchmark

test-e2e: ## Run end-to-end tests (requires running services)
	@cd $(ROOT) && python -m pytest tests/e2e/ -v -m e2e

test-resilience: ## Run chaos and resilience tests
	@cd $(ROOT) && python -m pytest tests/resilience/ -v -m chaos

benchmark: ## Run performance benchmarks (pytest-benchmark micro-benchmarks)
	@cd $(ROOT) && python -m pytest tests/performance/test_benchmarks.py -v --benchmark-only

benchmark-baselines: ## Run latency baseline benchmarks and generate reports
	@cd $(ROOT) && python scripts/run_benchmarks.py

benchmark-compare: ## Run benchmarks and compare against saved baseline
	@cd $(ROOT) && python scripts/run_benchmarks.py --compare tests/performance/latency_benchmarks.json

# ── Code quality ──────────────────────────────────────────────────────────────
lint: ## Lint with ruff
	@cd $(ROOT) && ruff check .

format: ## Format with ruff
	@cd $(ROOT) && ruff format .

format-check: ## Check formatting without changes
	@cd $(ROOT) && ruff format --check .

typecheck: ## Run mypy static type checker
	@cd $(ROOT) && mypy proxy/ etl/ --exclude '\.venv|__pycache__'

# ── Cleanup ───────────────────────────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	@find $(ROOT) -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
	@find $(ROOT) -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
	@find $(ROOT) -type d -name '.mypy_cache' -exec rm -rf {} + 2>/dev/null || true
	@find $(ROOT) -type d -name '.ruff_cache' -exec rm -rf {} + 2>/dev/null || true
	@find $(ROOT) -type f -name '*.pyc' -delete
	@find $(ROOT) -type f -name '*.pyo' -delete
	@find $(ROOT) -type f -name '.DS_Store' -delete
	@echo "Cleaned build artifacts and caches"

# ── Docker ────────────────────────────────────────────────────────────────────
docker-build: ## Build Docker images
	@cd $(ROOT)/proxy && docker-compose build

docker-up: ## Start docker-compose services (detached)
	@cd $(ROOT)/proxy && docker-compose up -d

docker-down: ## Stop docker-compose services
	@cd $(ROOT)/proxy && docker-compose down

docker-logs: ## Tail docker-compose logs
	@cd $(ROOT)/proxy && docker-compose logs -f

# ── Backup & Restore ─────────────────────────────────────────────────────────
backup: ## Run all backups (Qdrant, Neo4j, Redis)
	@bash $(ROOT)/scripts/ops/backup_cron.sh

restore: ## Run restore from latest backups
	@bash $(ROOT)/scripts/ops/restore_all.sh

verify-backups: ## Verify backup integrity
	@bash $(ROOT)/scripts/ops/verify_restore.sh

# ── Deployment ───────────────────────────────────────────────────────────────
deploy: ## Deploy services (dev)
	@bash $(ROOT)/scripts/deploy.sh dev

deploy-prod: ## Deploy services (prod)
	@bash $(ROOT)/scripts/deploy.sh prod

# ── Documentation ─────────────────────────────────────────────────────────────
docs: ## Show documentation locations
	@echo "Documentation:"
	@echo "  Architecture: docs/"
	@echo "  AGENTS.md:    project structure and conventions"
	@echo "  README.md:    project overview"

export-openapi: ## Export OpenAPI spec + generate API docs
	@cd $(ROOT) && python scripts/export_openapi.py

# ── UI ────────────────────────────────────────────────────────────────────────
dashboard: ## Start Streamlit dashboard
	streamlit run dashboard/app.py --server.port 8501

tui: ## Start terminal UI
	python tui/app.py

# ── MCP Server ────────────────────────────────────────────────────────────────
mcp-server: ## Start MCP server
	python mcp_server/server.py

# ── CI pipeline ───────────────────────────────────────────────────────────────
all: install lint test ## Install deps, lint, then run all tests

# ── Maturity Review ───────────────────────────────────────────────────────────
maturity-review: ## Run automated RAG maturity assessment
	@python $(ROOT)/scripts/maturity_review.py

maturity-review-json: ## Run maturity assessment (JSON output)
	@python $(ROOT)/scripts/maturity_review.py --json

maturity-review-save: ## Run maturity assessment and save report
	@python $(ROOT)/scripts/maturity_review.py --output $(ROOT)/docs/en/guides/maturity-report.md
	@echo "Report saved to docs/en/guides/maturity-report.md"

# ── Help ──────────────────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
