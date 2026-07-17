# Development Guide

**Version:** v2.0.0 | **Last Updated:** 2026-07-10

This guide covers setting up a development environment, running tests, code style conventions, and contributing to the
RAG System.

---

## 1. Project Structure

```
rag-system/
├── proxy/                         # RAG proxy (FastAPI + LangGraph)
│   ├── app/
│   │   ├── main.py                # FastAPI entry point (25+ endpoints)
│   │   ├── core/                  # Core RAG logic
│   │   │   ├── retrieval.py       # Qdrant hybrid search
│   │   │   ├── rerank.py          # Cross-encoder reranker
│   │   │   ├── context.py         # Context assembly
│   │   │   ├── confidence.py      # Confidence scoring
│   │   │   ├── token_optimizer.py # Token budgeting
│   │   │   ├── orchestrator.py    # LangGraph agentic pipeline
│   │   │   ├── enricher.py        # Self-enrichment from feedback
│   │   │   └── hitl.py            # Interaction logging
│   │   ├── auth/                  # Authentication & authorization
│   │   │   ├── jwt.py             # JWT token management
│   │   │   ├── rbac.py            # Role-based access control
│   │   │   ├── user_db.py         # SQLite user database
│   │   │   └── ldap.py            # LDAP/AD integration
│   │   ├── llm/                   # LLM provider adapters
│   │   │   └── provider.py        # Multi-provider completion
│   │   ├── tools/                 # Agentic tool system
│   │   │   ├── registry.py        # Tool registry
│   │   │   ├── declarative.py     # YAML/JSON tool definitions
│   │   │   └── openapi_discovery.py # OpenAPI auto-discovery
│   │   ├── model_evolution/       # Fine-tuning pipeline (13 modules)
│   │   │   ├── trainer.py         # Base trainer + TrainingJob
│   │   │   ├── slm_trainer.py     # SLM LoRA fine-tuning
│   │   │   ├── llm_trainer.py     # LLM QLoRA fine-tuning
│   │   │   ├── reranker_trainer.py # Reranker training
│   │   │   ├── adapter_manager.py # Hot-reload adapters
│   │   │   ├── canary_controller.py # Canary deployment
│   │   │   ├── model_registry.py  # Model artifact registry
│   │   │   ├── eval_gate.py       # CI/CD quality gating
│   │   │   └── env_profile.py     # Dev/Prod/CI profiles
│   │   ├── shared/                # Shared utilities
│   │   │   ├── config.py          # Environment-based configuration
│   │   │   ├── cache.py           # Redis + in-memory cache
│   │   │   ├── metrics.py         # Prometheus metrics
│   │   │   ├── middleware.py       # Request middleware
│   │   │   ├── rate_limiter.py    # Token bucket rate limiter
│   │   │   ├── security.py        # Input sanitization
│   │   │   └── logging.py         # Structured logging
│   │   └── static/                # Widget HTML/JS
│   ├── Dockerfile.proxy
│   └── docker-compose.yml
├── etl/                           # ETL pipeline (standalone)
│   ├── extractors/                # Data source extractors
│   │   ├── confluence.py
│   │   ├── jira.py
│   │   ├── gitlab.py
│   │   ├── doc_extractor.py
│   │   ├── book_extractor.py
│   │   └── chat_extractor.py
│   ├── chunker/                   # Document chunking
│   │   ├── semantic_chunker.py
│   │   ├── hash_versioning.py
│   │   ├── code_chunker.py
│   │   └── table_extractor.py
│   ├── graph_builder/             # Neo4j graph construction
│   │   ├── entity_extractor.py
│   │   ├── neo4j_loader.py
│   │   └── schema.yaml
│   ├── indexer/                   # Vector indexing
│   │   ├── qdrant_hybrid.py
│   │   ├── live_vector_lake.py
│   │   └── wal_manager.py
│   ├── scheduler/                 # Pipeline orchestration
│   │   ├── run_etl.py
│   │   ├── stream_producer.py
│   │   ├── stream_consumer.py
│   │   └── webhook_server.py
│   ├── config/
│   │   └── etl_config.yaml
│   ├── Dockerfile.etl
│   └── requirements_etl.txt
├── mcp_server/                    # MCP server for IDE integration
│   └── server.py
├── hitl_dashboard/                # Streamlit expert dashboard
│   ├── dashboard.py
│   └── feedback_logger.py
├── scripts/                       # Utility scripts
│   ├── init_collections.py
│   └── download_models_offline.py
├── tests/                         # Test suite
│   ├── proxy/                     # Proxy unit tests
│   ├── etl/                       # ETL unit tests
│   ├── model_evolution/           # Model evolution tests
│   ├── integration/               # Integration tests
│   ├── e2e/                       # End-to-end tests
│   ├── benchmark/                 # Performance tests
│   ├── mcp_server/                # MCP server tests
│   └── conftest.py                # Shared fixtures
├── docs/                          # Documentation (EN + RU)
│   ├── en/                        # English docs
│   └── ru/                        # Russian docs
├── k8s/helm/rag-system/           # Kubernetes Helm chart
├── Makefile                       # Primary dev entry point
├── pyproject.toml                 # Python project config
├── setup.sh                       # Installation script
└── README.md
```

---

## 2. Setting Up Development Environment

### Prerequisites

- Python 3.11+
- Docker 24+ and Docker Compose v2.20+
- Git
- 16 GB RAM minimum (for local model testing)
- uv (recommended) or pip

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system

# Full setup (creates venvs, installs dependencies)
make install-dev

# Or manually:
bash setup.sh --dev
```

### Manual Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install proxy dependencies
pip install -r requirements-proxy.txt

# Install ETL dependencies
pip install -r requirements-etl.txt

# Install dev dependencies
pip install -r requirements-dev.txt

# Create .env from template
cp .env.example proxy/.env
# Edit proxy/.env with your settings
```

### Configuration

All configuration is via environment variables or `proxy/.env`. Key settings for development:

```bash
# Minimal local setup
QDRANT_HOST=localhost
LLM_ENDPOINT=http://localhost:8000/v1
LLM_MODEL_NAME=your-model-name

# Enable features for testing
USE_LANGGRAPH=false        # Start simple, enable later
USE_REDIS=false            # Use in-memory cache
GRAPH_ENABLED=false        # Skip Neo4j for quick start
AUTH_ENABLED=false         # Skip auth for local dev
METRICS_ENABLED=true
```

### Starting Services Locally

```bash
# Option 1: Docker Compose (all services)
cd proxy && docker compose up -d

# Option 2: Start only infrastructure
docker run -d -p 6333:6333 qdrant/qdrant:v1.12.1
docker run -d -p 6379:6379 redis:7-alpine

# Then run proxy locally
make run
# Or: granian --interface asgi --host 0.0.0.0 --port 8080 --workers 1 proxy.app.main:app
```

---

## 3. Running Tests

### Test Commands

```bash
# Run all tests
make test

# Run specific test suites
make test-proxy           # Proxy unit tests only
make test-etl             # ETL unit tests only
make test-integration     # Integration tests (requires services)

# Run with verbose output
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/proxy/test_retrieval.py -v

# Run specific test
python -m pytest tests/proxy/test_retrieval.py::TestHybridSearch::test_rrf_fusion -v

# Run with coverage
python -m pytest tests/ --cov=proxy --cov=etl --cov-report=html

# Run only fast tests (exclude slow/e2e/benchmark)
python -m pytest tests/ -m "not slow and not e2e and not benchmark"
```

### Test Markers

| Marker        | Description                            | Requires             |
|---------------|----------------------------------------|----------------------|
| `e2e`         | End-to-end tests                       | Running services     |
| `benchmark`   | Performance and load tests             | Running services     |
| `chaos`       | Resilience and chaos engineering tests | Running services     |
| `asyncio`     | Tests using asyncio                    | Nothing extra        |
| `slow`        | Tests taking >5 seconds                | Nothing extra        |
| `integration` | Tests requiring external services      | Qdrant, Neo4j, Redis |

### Writing Tests

```python
# tests/proxy/test_example.py
import pytest
from unittest.mock import AsyncMock, patch


class TestExample:
    """Example test class following project conventions."""

    def test_basic_retrieval(self):
        """Test hybrid search returns results."""
        # Arrange
        query = "test query"
        # Act
        # ...
        # Assert
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_async_endpoint(self):
        """Test async endpoint."""
        # Use AsyncMock for async dependencies
        with patch("proxy.app.core.retrieval.hybrid_search") as mock:
            mock.return_value = []
            # ...

    @pytest.mark.slow
    def test_expensive_operation(self):
        """Mark slow tests to exclude from fast runs."""
        # ...
```

---

## 4. Code Style

### Ruff (Linting + Formatting)

The project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
# Lint
make lint                 # Check for issues
ruff check .              # Same as above

# Format
make format               # Auto-format code
ruff format .             # Same as above

# Check formatting without changes
make format-check
ruff format --check .
```

**Configuration** (from `pyproject.toml`):

```toml
[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM"]

[tool.ruff.format]
quote-style = "double"
```

### Mypy (Type Checking)

```bash
make typecheck            # Run mypy
mypy proxy/ etl/ --exclude '.venv|__pycache__'
```

**Configuration** (from `pyproject.toml`):

```toml
[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

### Code Conventions

1. **Type hints**: Use modern Python 3.11+ syntax (`list[str]` not `List[str]`, `X | None` not `Optional[X]`).
2. **Docstrings**: Use Google-style docstrings for public functions.
3. **Imports**: Sorted by Ruff (stdlib → third-party → local).
4. **Line length**: 120 characters maximum.
5. **Naming**: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE` for constants.
6. **Error handling**: Graceful degradation — log and continue, never crash the proxy.

---

## 5. Adding New Features

### Adding a New ETL Extractor

1. Create `etl/extractors/my_source.py`:

```python
# etl/extractors/my_source.py
from etl.extractors.base_extractor import BaseExtractor


class MySourceExtractor(BaseExtractor):
    """Extract data from MySource."""

    def extract(self, config: dict) -> list[dict]:
        """Extract documents from MySource."""
        documents = []
        # ... extraction logic ...
        return documents
```

2. Register in `etl/scheduler/run_etl.py`.
3. Add configuration to `etl/config/etl_config.yaml`.
4. Write tests in `tests/etl/test_my_source.py`.

### Adding a New API Endpoint

1. Add endpoint to `proxy/app/main.py`:

```python
@app.get("/v1/my-endpoint")
async def my_endpoint(
    user: UserContext = Depends(get_optional_auth_context),
):
    """My new endpoint."""
    return {"status": "ok"}
```

2. Add Pydantic models for request/response if needed.
3. Write tests in `tests/proxy/test_my_endpoint.py`.
4. Update API reference documentation.

### Adding a New Tool

See [Agentic Tools SDK](agentic-tools-sdk.md) for the `@tool` decorator:

```python
from proxy.app.tools.registry import tool


@tool(
    name="my_tool",
    description="Does something useful",
    category="custom",
)
async def my_tool(query: str) -> str:
    """Execute my custom tool."""
    return f"Result for: {query}"
```

### Adding a New LLM Provider

1. Add adapter to `proxy/app/llm/provider.py`:

```python
async def my_provider_completion(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    """Completion via MyProvider API."""
    # ... implementation ...
```

2. Add provider type to config (`LLM_PROVIDER_TYPE`).
3. Write tests.

---

## 6. Git Workflow

### Branches

| Branch      | Purpose               |
|-------------|-----------------------|
| `main`      | Production-ready code |
| `develop`   | Integration branch    |
| `feature/*` | Feature development   |
| `fix/*`     | Bug fixes             |
| `release/*` | Release preparation   |

### Commit Messages

Follow conventional commits:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

Examples:

```
feat(proxy): add federated search endpoint
fix(etl): handle empty Confluence pages gracefully
docs(api): update chat completions documentation
test(retrieval): add RRF fusion edge case tests
```

### Pull Requests

1. Create feature branch from `develop`
2. Make changes with proper commits
3. Run full CI: `make all` (install → lint → test)
4. Create PR with description of changes
5. Request review
6. Squash-merge into `develop`

### CI Pipeline

```bash
make all    # Runs: install → lint → test
```

Individual steps:

```bash
make install    # Install dependencies
make lint       # Ruff linting
make format     # Ruff formatting
make typecheck  # Mypy type checking
make test       # All tests
```

---

## 7. Useful Commands Reference

```bash
# ── Setup ──────────────────────────────────
make install          # Full setup (proxy + ETL)
make install-dev      # Setup with dev dependencies
make setup            # Create .env from .env.example

# ── Run ────────────────────────────────────
make run              # Start proxy locally

# ── Testing ────────────────────────────────
make test             # All tests
make test-proxy       # Proxy unit tests
make test-etl         # ETL unit tests
make test-integration # Integration tests

# ── Code Quality ───────────────────────────
make lint             # Ruff linting
make format           # Ruff formatting
make format-check     # Check formatting
make typecheck        # Mypy type checking

# ── Docker ─────────────────────────────────
make docker-build     # Build Docker images
make docker-up        # Start docker-compose
make docker-down      # Stop docker-compose
make docker-logs      # Tail logs

# ── Cleanup ────────────────────────────────
make clean            # Remove build artifacts and caches

# ── CI ─────────────────────────────────────
make all              # Install → lint → test
```
