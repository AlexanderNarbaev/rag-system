# RAG System Makefile
# Primary entry point for development, testing, and deployment workflows.

.PHONY: help install install-dev install-one-line setup wizard \
        test test-proxy test-etl test-integration test-minikube \
        test-performance test-e2e test-resilience benchmark \
        benchmark-baselines benchmark-compare \
        lint helm-lint format format-check typecheck clean \
        docker-build docker-up docker-down docker-logs run run-dev docs all \
        etl etl-run-streaming etl-run-batch etl-test-connection etl-cleanup \
        etl-confluence etl-jira etl-gitlab \
        backup restore dashboard tui mcp-server \
        deploy deploy-prod verify-backups \
        health-check status \
        maturity-review maturity-review-json maturity-review-save \
        export-openapi audit \
        openwebui-up openwebui-down openwebui-logs openwebui-dev

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
	@cd $(ROOT) && granian --interface asgi --host 0.0.0.0 --port 8080 --workers 1 proxy.app.main:app

run-dev: ## Start proxy with hot reload for development
	@cd $(ROOT) && granian --interface asgi --host 0.0.0.0 --port 8080 --workers 1 --reload proxy.app.main:app

# ── ETL ───────────────────────────────────────────────────────────────────────
etl: ## Run full ETL pipeline
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml

etl-run-streaming: ## Run ETL in streaming mode with remote embedder
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode streaming

etl-run-batch: ## Run ETL in batch mode
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --mode batch

etl-test-connection: ## Test connections to all sources
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --test-connection

etl-cleanup: ## Clean raw data after indexing
	@cd $(ROOT) && python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --cleanup-after-index

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

test-minikube: ## Run integration tests against minikube deployment
	@echo "Ensure minikube is running and port-forward is active:"
	@echo "  kubectl port-forward svc/rag-system-proxy 9080:8080 -n rag-system &"
	@echo "  python3 scripts/mock_llm_server.py &"
	@echo ""
	RAG_PROXY_URL=http://localhost:9080 MOCK_LLM_URL=http://localhost:8010 \
		python -m pytest tests/integration/test_minikube_e2e.py -v

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
audit: ## Run pip-audit on all requirements files
	@echo "Auditing proxy dependencies..."
	@pip-audit --requirement requirements-proxy.txt --desc --format columns --vulnerability-service osv
	@echo ""
	@echo "Auditing ETL dependencies..."
	@pip-audit --requirement requirements-etl.txt --desc --format columns --vulnerability-service osv
	@echo ""
	@echo "Auditing dev dependencies..."
	@pip-audit --requirement requirements-dev.txt --desc --format columns --vulnerability-service osv

lint: ## Lint with ruff
	@cd $(ROOT) && ruff check .

helm-lint: ## Lint Helm chart (requires helm CLI)
	@if ! command -v helm >/dev/null 2>&1; then echo "helm not found - skipping Helm lint"; exit 0; fi && cd $(ROOT) && helm lint deploy/k8s/helm/rag-system/

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

# ── OpenWebUI ─────────────────────────────────────────────────────────────────
openwebui-up: ## Start OpenWebUI with production config
	@bash $(ROOT)/scripts/init-openwebui.sh --auto

openwebui-down: ## Stop OpenWebUI
	@docker compose -f $(ROOT)/deploy/docker/docker-compose.openwebui.yml --env-file $(ROOT)/deploy/docker/.env.openwebui down --timeout 30

openwebui-logs: ## Tail OpenWebUI logs
	@docker compose -f $(ROOT)/deploy/docker/docker-compose.openwebui.yml --env-file $(ROOT)/deploy/docker/.env.openwebui logs -f

openwebui-dev: ## Start OpenWebUI with dev override (SQLite, no Tika, signup enabled)
	@bash $(ROOT)/scripts/init-openwebui.sh --auto --dev

# ── Backup & Restore ─────────────────────────────────────────────────────────
backup: ## Run all backups (Qdrant, Neo4j, Redis)
	@bash $(ROOT)/scripts/ops/backup_cron.sh

restore: ## Run restore from latest backups
	@bash $(ROOT)/scripts/ops/restore_all.sh

verify-backups: ## Verify backup integrity
	@bash $(ROOT)/scripts/ops/verify_restore.sh

health-check: ## Run comprehensive health check on all services
	@bash $(ROOT)/scripts/ops/health_check.sh

status: ## Show real-time status of all services
	@bash $(ROOT)/scripts/ops/status.sh

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
