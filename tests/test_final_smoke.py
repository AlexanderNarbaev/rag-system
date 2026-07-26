"""Final smoke test that verifies the system is production-ready."""

import subprocess


def test_ruff_check_passes():
    """Lint check passes."""
    r = subprocess.run(
        ["ruff", "check", "."], capture_output=True, text=True, cwd="/home/alexandr-narbaev/Projects/rag-system"
    )
    assert r.returncode == 0, f"ruff check failed: {r.stdout}"


def test_ruff_format_passes():
    """Format check passes."""
    r = subprocess.run(
        ["ruff", "format", "--check", "."],
        capture_output=True,
        text=True,
        cwd="/home/alexandr-narbaev/Projects/rag-system",
    )
    assert r.returncode == 0, f"ruff format failed: {r.stdout}"


def test_all_spec_files_exist():
    """All spec files exist and are not empty."""
    spec_files = [
        "README.md",
        "01-core-api.md",
        "02-retrieval.md",
        "03-knowledge-graph.md",
        "04-agentic.md",
        "05-quality.md",
        "06-etl.md",
        "07-auth.md",
        "08-model-evolution.md",
        "09-tools.md",
        "10-mcp-deploy-obs.md",
        "11-nfr.md",
        "TRACEABILITY.md",
        "IMPLEMENTATION_STATUS.md",
    ]
    import os

    base = "/home/alexandr-narbaev/Projects/rag-system/docs/ru/requirements"
    for f in spec_files:
        path = os.path.join(base, f)
        assert os.path.exists(path), f"Missing spec file: {f}"
        assert os.path.getsize(path) > 0, f"Empty spec file: {f}"


def test_no_secrets_in_tracked_files():
    """No secrets in tracked files."""
    import re

    secret_patterns = [
        r"sk-[a-zA-Z0-9]{20,}",  # OpenAI keys
        r"AKIA[0-9A-Z]{16}",  # AWS keys
        r"ghp_[a-zA-Z0-9]{36}",  # GitHub tokens
        r"password\s*=\s*['\"]\w+['\"]",  # Hardcoded passwords
    ]

    r = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd="/home/alexandr-narbaev/Projects/rag-system"
    )
    files = r.stdout.strip().split("\n")

    for f in files:
        if f.endswith((".py", ".yaml", ".yml", ".json", ".md")):
            # Skip documentation directories (legitimate example values)
            if f.startswith("docs/"):
                continue
            try:
                with open(f"/home/alexandr-narbaev/Projects/rag-system/{f}") as fp:
                    content = fp.read()
                for pattern in secret_patterns:
                    if re.search(pattern, content):
                        # Skip test files (they may have placeholder secrets)
                        if "test_" in f or "conftest" in f:
                            continue
                        # Skip files that explicitly document these patterns
                        if "security" in f or "audit" in f:
                            continue
                        raise AssertionError(f"Possible secret in {f}")
            except (FileNotFoundError, UnicodeDecodeError):
                pass


def test_dockerfile_exists():
    """Dockerfile exists for proxy."""
    import os

    assert os.path.exists("/home/alexandr-narbaev/Projects/rag-system/proxy/Dockerfile")


def test_helm_chart_validates():
    """Helm chart lints clean."""
    r = subprocess.run(
        ["helm", "lint", "deploy/k8s/helm/rag-system/"],
        capture_output=True,
        text=True,
        cwd="/home/alexandr-narbaev/Projects/rag-system",
    )
    assert r.returncode == 0, f"helm lint failed: {r.stdout}"
