# Contributing to RAG System

Thank you for your interest in contributing! This guide covers everything you need to get started.

---

## Development Setup

### Prerequisites

| Tool   | Version | Purpose                 |
|--------|---------|-------------------------|
| Python | 3.11+   | Runtime                 |
| Docker | 24.0+   | Infrastructure services |
| Git    | 2.30+   | Version control         |
| Make   | 4.0+    | Build automation        |

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system

# Install with dev dependencies
make install-dev

# Start infrastructure (Qdrant + Redis + Neo4j)
cd proxy && docker compose up -d qdrant redis neo4j

# Run tests to verify setup
make test
```

### Environment Configuration

```bash
# Copy environment template
cp proxy/.env.example proxy/.env

# Edit with your local settings
nano proxy/.env
```

---

## Code Style Guidelines

### Python

- **Formatter & Linter:** [Ruff](https://github.com/astral-sh/ruff) (replaces black, isort, flake8)
- **Type Checker:** mypy with strict mode
- **Docstrings:** Google style
- **Line Length:** 100 characters

```bash
# Format code
make format

# Check formatting without changes
make format-check

# Lint
make lint

# Type check
make typecheck
```

### Ruff Configuration (pyproject.toml)

The project uses Ruff for all Python linting and formatting. Key rules:

- `E` — pycodestyle errors
- `F` — pyflakes
- `I` — isort (import sorting)
- `N` — pep8-naming
- `UP` — pyupgrade
- `B` — flake8-bugbear
- `SIM` — flake8-simplify
- `TCH` — flake8-type-checking

### Naming Conventions

| Type     | Convention         | Example              |
|----------|--------------------|----------------------|
| Module   | snake_case         | `retrieval.py`       |
| Class    | PascalCase         | `HybridRetriever`    |
| Function | snake_case         | `search_documents()` |
| Constant | UPPER_SNAKE        | `MAX_CHUNK_SIZE`     |
| Private  | Leading underscore | `_internal_method()` |

### Type Annotations

All public functions must have type annotations:

```python
from typing import Optional

async def retrieve_documents(
    query: str,
    top_k: int = 10,
    collection: str = "default",
) -> list[dict[str, Any]]:
    """Retrieve relevant documents for a query.

    Args:
        query: The search query text.
        top_k: Maximum number of results.
        collection: Qdrant collection name.

    Returns:
        List of document dicts with 'content' and 'score' keys.
    """
    ...
```

---

## Testing Requirements

### Test Structure

```
tests/
├── proxy/              # Proxy unit tests
│   ├── test_retrieval.py
│   ├── test_rerank.py
│   └── test_auth.py
├── etl/                # ETL unit tests
├── model_evolution/    # Model evolution tests
├── integration/        # Integration tests
├── e2e/                # End-to-end tests
├── mcp_server/         # MCP server tests
└── conftest.py         # Shared fixtures
```

### Running Tests

```bash
# All tests
make test

# Proxy tests only
make test-proxy

# ETL tests only
make test-etl

# Integration tests (requires running services)
make test-integration

# Single test with verbose output
python -m pytest tests/proxy/test_retrieval.py::TestHybridSearch::test_rrf_fusion -v

# Coverage report
python -m pytest tests/ --cov=proxy --cov=etl --cov-report=html
# Open htmlcov/index.html in browser
```

### Writing Tests

- Use `pytest` fixtures from `conftest.py`
- Mock external services (Qdrant, Redis, Neo4j, LLM)
- Test both success and failure paths
- Use descriptive test names: `test_<what>_<condition>_<expected>`

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_retrieve_returns_empty_when_qdrant_down(mock_qdrant):
    """Retrieval returns empty list when Qdrant is unavailable."""
    mock_qdrant.search.side_effect = ConnectionError("Qdrant unavailable")

    results = await retrieve_documents(query="test", top_k=5)

    assert results == []
```

### Test Coverage

- Minimum coverage target: **80%**
- Critical paths (auth, retrieval, generation): **90%+**
- New features must include tests

---

## Commit Guidelines

### Commit Message Format

```
<type>(<scope>): <subject>

[optional body]

[optional footer]
```

### Types

| Type       | Description                |
|------------|----------------------------|
| `feat`     | New feature                |
| `fix`      | Bug fix                    |
| `docs`     | Documentation only         |
| `style`    | Formatting, no code change |
| `refactor` | Code restructuring         |
| `test`     | Adding/fixing tests        |
| `chore`    | Build, CI, tooling         |
| `perf`     | Performance improvement    |

### Examples

```
feat(retrieval): add ColBERT multi-vector support

Add ColBERT late-interaction scoring alongside dense and sparse vectors.
Improves retrieval precision for long documents by 12%.

Closes #142
```

```
fix(auth): handle expired refresh tokens gracefully

Return 401 instead of 500 when refresh token has expired.
```

---

## Pull Request Process

### Before Submitting

1. **Run the full CI pipeline:**

    ```bash
    make all  # install → lint → test
    ```

2. **Update documentation** if adding/changing features
3. **Add tests** for new functionality
4. **Update CHANGELOG.md** (if applicable)

### PR Template

```markdown
## Description
Brief description of changes.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests pass (`make test`)
- [ ] Integration tests pass (`make test-integration`)
- [ ] Manual testing performed

## Checklist
- [ ] Code follows project style (`make lint`)
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new warnings
```

### Review Process

1. **Automated checks** must pass (lint, typecheck, tests)
2. **At least one approval** from a maintainer
3. **No unresolved conversations**
4. **Branch is up to date** with `main`

### Merge Strategy

- **Squash and merge** for feature branches
- **Rebase** for single-commit PRs
- **Merge commit** for complex multi-commit PRs

---

## Issue Templates

### Bug Report

```markdown
**Describe the bug**
A clear description of what the bug is.

**To reproduce**
1. Start services with '...'
2. Send request '...'
3. See error

**Expected behavior**
What you expected to happen.

**Logs / Screenshots**
Include relevant logs from `docker compose logs rag-proxy`.

**Environment**
- OS: [e.g., Ubuntu 22.04]
- Docker: [e.g., 27.0]
- Python: [e.g., 3.12]
- GPU: [e.g., RTX 4090, none]
```

### Feature Request

```markdown
**Problem**
What problem does this solve?

**Proposed solution**
How should it work?

**Alternatives considered**
Other approaches you've thought about.

**Additional context**
Screenshots, references, examples.
```

---

## Project Architecture

Before contributing, familiarize yourself with the architecture:

| Layer          | Directory         | Purpose                                    |
|----------------|-------------------|--------------------------------------------|
| **Proxy**      | `proxy/app/`      | FastAPI application, retrieval, generation |
| **ETL**        | `etl/`            | Data extraction, chunking, embedding       |
| **Federation** | `federation/app/` | Multi-silo RAG proxy                       |
| **MCP**        | `mcp_server/`     | Model Context Protocol server              |
| **Dashboard**  | `hitl_dashboard/` | Streamlit expert review                    |
| **Tests**      | `tests/`          | All test suites                            |
| **Docs**       | `docs/`           | Documentation (EN + RU)                    |

See [Architecture Decision Records](docs/en/adr/) for design rationale.

---

## Getting Help

- **Issues:** [GitHub Issues](https://github.com/AlexanderNarbaev/rag-system/issues)
- **Discussions:** [GitHub Discussions](https://github.com/AlexanderNarbaev/rag-system/discussions)
- **Documentation:** [docs/en/](docs/en/)

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
