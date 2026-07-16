#!/usr/bin/env python3
"""
Automated RAG System Maturity Review.

Scans the project structure, documentation, tests, CI/CD, and security posture
to produce a comprehensive maturity report aligned with the 5-level RAG
Maturity Model defined in docs/en/guides/rag-maturity-assessment.md.

Usage:
    python scripts/maturity_review.py                   # Print to stdout
    python scripts/maturity_review.py --output report.md  # Write to file
    python scripts/maturity_review.py --json             # JSON output
    python scripts/maturity_review.py --quiet            # Only final scores

Sprint: S4-2026 Wave 4, Task P3-5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Configuration ────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent

# Scoring weights per dimension (must sum to 1.0)
WEIGHTS: dict[str, float] = {
    "project_structure": 0.10,
    "documentation": 0.15,
    "testing": 0.25,
    "ci_cd": 0.15,
    "security": 0.15,
    "rag_capabilities": 0.20,
}

# RAG maturity level weights (for composite score)
RAG_LEVEL_WEIGHTS: dict[int, float] = {
    1: 1.0,
    2: 1.5,
    3: 2.0,
    4: 2.5,
    5: 3.0,
}


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    """Result of a single maturity check."""

    name: str
    passed: bool
    score: float  # 0.0 – 1.0
    detail: str = ""
    evidence: str = ""
    remediation: str = ""


@dataclass
class DimensionResult:
    """Aggregated result for a maturity dimension."""

    name: str
    weight: float
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        return sum(c.score for c in self.checks) / len(self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total_count(self) -> int:
        return len(self.checks)


@dataclass
class MaturityReport:
    """Full maturity report."""

    project_name: str
    version: str
    timestamp: str
    dimensions: list[DimensionResult] = field(default_factory=list)
    rag_level: int = 0
    rag_composite: float = 0.0
    recommendations: list[str] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        return sum(d.score * d.weight for d in self.dimensions)

    @property
    def overall_grade(self) -> str:
        score = self.overall_score
        if score >= 0.90:
            return "A"
        if score >= 0.80:
            return "B"
        if score >= 0.70:
            return "C"
        if score >= 0.60:
            return "D"
        return "F"

    @property
    def maturity_label(self) -> str:
        labels = {
            1: "Naive RAG",
            2: "Advanced RAG",
            3: "GraphRAG",
            4: "Agentic RAG",
            5: "Self-Correcting RAG",
        }
        return labels.get(self.rag_level, "Unknown")


# ── Utility Functions ────────────────────────────────────────────────────────


def file_exists(*parts: str) -> bool:
    """Check if a file exists relative to project root."""
    return (ROOT / Path(*parts)).is_file()


def dir_exists(*parts: str) -> bool:
    """Check if a directory exists relative to project root."""
    return (ROOT / Path(*parts)).is_dir()


def count_files(*parts: str, pattern: str = "*.py") -> int:
    """Count files matching pattern in a directory."""
    target = ROOT / Path(*parts)
    if not target.is_dir():
        return 0
    return len(list(target.rglob(pattern)))


def count_lines(*parts: str) -> int:
    """Count lines in a file."""
    target = ROOT / Path(*parts)
    if not target.is_file():
        return 0
    return len(target.read_text(encoding="utf-8", errors="ignore").splitlines())


def grep_count(pattern: str, *path_parts: str, include: str = "*.py") -> int:
    """Count regex matches in files."""
    target = ROOT / Path(*path_parts) if path_parts else ROOT
    if not target.is_dir():
        return 0
    count = 0
    regex = re.compile(pattern)
    for f in target.rglob(include):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            count += len(regex.findall(content))
        except (OSError, UnicodeDecodeError):
            continue
    return count


def run_cmd(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    """Run a command and return (returncode, stdout)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
        return result.returncode, result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return -1, ""


def read_pyproject_version() -> str:
    """Read version from pyproject.toml."""
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.is_file():
        return "unknown"
    for line in pyproject.read_text().splitlines():
        if line.strip().startswith("version"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                return parts[1].strip().strip('"').strip("'")
    return "unknown"


# ── Dimension Checkers ───────────────────────────────────────────────────────


def check_project_structure() -> DimensionResult:
    """Check project structure completeness."""
    dim = DimensionResult(name="Project Structure", weight=WEIGHTS["project_structure"])

    # Core directories
    core_dirs = [
        ("proxy", "Proxy layer (FastAPI RAG application)"),
        ("etl", "ETL pipeline (extraction, chunking, indexing)"),
        ("tests", "Test suite"),
        ("docs", "Documentation"),
        ("scripts", "Utility scripts"),
        ("config", "Configuration (monitoring, alerts)"),
        ("deploy", "Deployment manifests"),
    ]
    for dir_name, desc in core_dirs:
        exists = dir_exists(dir_name)
        dim.checks.append(CheckResult(
            name=f"Core directory: {dir_name}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=desc,
            remediation=f"Create {dir_name}/ directory with appropriate structure" if not exists else "",
        ))

    # Optional but valuable directories
    optional_dirs = [
        ("mcp_server", "MCP server for IDE integration"),
        ("dashboard", "Streamlit expert dashboard"),
        ("tui", "Terminal UI"),
        ("eval", "Evaluation scripts"),
    ]
    for dir_name, desc in optional_dirs:
        exists = dir_exists(dir_name)
        dim.checks.append(CheckResult(
            name=f"Optional directory: {dir_name}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=desc,
            remediation=f"Consider creating {dir_name}/ for {desc.lower()}" if not exists else "",
        ))

    # Key config files
    key_files = [
        ("pyproject.toml", "Python project configuration"),
        ("Makefile", "Build/dev task automation"),
        (".gitignore", "Git ignore rules"),
        (".pre-commit-config.yaml", "Pre-commit hooks"),
        ("AGENTS.md", "Agent coding conventions"),
    ]
    for fname, desc in key_files:
        exists = file_exists(fname)
        dim.checks.append(CheckResult(
            name=f"Config file: {fname}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=desc,
            remediation=f"Create {fname}" if not exists else "",
        ))

    return dim


def check_documentation() -> DimensionResult:
    """Check documentation completeness."""
    dim = DimensionResult(name="Documentation", weight=WEIGHTS["documentation"])

    # Essential docs
    essential_docs = [
        ("README.md", "Project README"),
        ("CHANGELOG.md", "Change log"),
        ("CONTRIBUTING.md", "Contributing guide"),
        ("LICENSE", "License file"),
        ("AGENTS.md", "Agent conventions"),
    ]
    for fname, desc in essential_docs:
        exists = file_exists(fname)
        dim.checks.append(CheckResult(
            name=f"Essential doc: {fname}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=desc,
        ))

    # ADRs
    adr_dir = ROOT / "docs" / "en" / "adr"
    adr_count = len(list(adr_dir.glob("*.md"))) if adr_dir.is_dir() else 0
    adr_score = min(1.0, adr_count / 10)  # 10+ ADRs = full score
    dim.checks.append(CheckResult(
        name="Architecture Decision Records",
        passed=adr_count >= 5,
        score=adr_score,
        detail=f"{adr_count} ADRs found",
        evidence=f"docs/en/adr/ contains {adr_count} files",
        remediation="Create ADRs for key architectural decisions" if adr_count < 5 else "",
    ))

    # Guides
    guides_dir = ROOT / "docs" / "en" / "guides"
    guide_count = len(list(guides_dir.glob("*.md"))) if guides_dir.is_dir() else 0
    guide_score = min(1.0, guide_count / 15)  # 15+ guides = full score
    dim.checks.append(CheckResult(
        name="Implementation guides",
        passed=guide_count >= 10,
        score=guide_score,
        detail=f"{guide_count} guides found",
        evidence=f"docs/en/guides/ contains {guide_count} files",
        remediation="Write guides for deployment, operations, troubleshooting" if guide_count < 10 else "",
    ))

    # i18n docs
    ru_docs = dir_exists("docs", "ru")
    dim.checks.append(CheckResult(
        name="Multi-language documentation (RU)",
        passed=ru_docs,
        score=1.0 if ru_docs else 0.0,
        detail="Russian translations available" if ru_docs else "No Russian translations",
        remediation="Create docs/ru/ with translated guides" if not ru_docs else "",
    ))

    # MkDocs config
    mkdocs = file_exists("mkdocs.yml")
    dim.checks.append(CheckResult(
        name="Documentation site config (MkDocs)",
        passed=mkdocs,
        score=1.0 if mkdocs else 0.0,
        detail="MkDocs configuration present" if mkdocs else "No MkDocs config",
        remediation="Add mkdocs.yml for documentation site generation" if not mkdocs else "",
    ))

    # Diagrams
    diagrams_dir = ROOT / "docs" / "en" / "diagrams"
    has_diagrams = diagrams_dir.is_dir() and any(diagrams_dir.iterdir())
    dim.checks.append(CheckResult(
        name="Architecture diagrams",
        passed=has_diagrams,
        score=1.0 if has_diagrams else 0.3,
        detail="C4/SVG diagrams available" if has_diagrams else "No architecture diagrams found",
        remediation="Create C4 diagrams in docs/en/diagrams/" if not has_diagrams else "",
    ))

    return dim


def check_testing() -> DimensionResult:
    """Check test coverage and quality."""
    dim = DimensionResult(name="Testing", weight=WEIGHTS["testing"])

    # Test directories
    test_dirs: list[tuple[tuple[str, ...], str]] = [
        (("tests", "proxy"), "Proxy unit tests"),
        (("tests", "etl"), "ETL unit tests"),
        (("tests", "integration"), "Integration tests"),
        (("tests", "e2e"), "End-to-end tests"),
        (("tests", "performance"), "Performance tests"),
        (("tests", "resilience"), "Resilience/chaos tests"),
    ]
    for dir_path, desc in test_dirs:
        exists = dir_exists(*dir_path)
        test_count = count_files(*dir_path, pattern="test_*.py") if exists else 0
        score = min(1.0, test_count / 3) if exists else 0.0
        dim.checks.append(CheckResult(
            name=f"Test suite: {desc}",
            passed=exists and test_count > 0,
            score=score,
            detail=f"{test_count} test files" if exists else "Missing",
            evidence=f"{'/'.join(dir_path)}/ contains {test_count} test files" if exists else "",
            remediation=f"Create test files in {'/'.join(dir_path)}/" if not exists else "",
        ))

    # Coverage configuration
    pyproject = ROOT / "pyproject.toml"
    has_cov_config = False
    if pyproject.is_file():
        content = pyproject.read_text()
        has_cov_config = "[tool.coverage" in content
    dim.checks.append(CheckResult(
        name="Coverage configuration",
        passed=has_cov_config,
        score=1.0 if has_cov_config else 0.0,
        detail="Coverage config in pyproject.toml" if has_cov_config else "No coverage config",
        remediation="Add [tool.coverage.*] sections to pyproject.toml" if not has_cov_config else "",
    ))

    # Coverage threshold
    cov_threshold = 0
    if pyproject.is_file():
        content = pyproject.read_text()
        match = re.search(r"fail_under\s*=\s*(\d+)", content)
        if match:
            cov_threshold = int(match.group(1))
    threshold_score = min(1.0, cov_threshold / 80)  # 80% = full score
    dim.checks.append(CheckResult(
        name="Coverage threshold",
        passed=cov_threshold >= 70,
        score=threshold_score,
        detail=f"fail_under={cov_threshold}%",
        remediation="Set fail_under >= 70 in pyproject.toml" if cov_threshold < 70 else "",
    ))

    # Test conftest fixtures
    conftest = file_exists("tests", "conftest.py")
    dim.checks.append(CheckResult(
        name="Shared test fixtures (conftest.py)",
        passed=conftest,
        score=1.0 if conftest else 0.0,
        detail="conftest.py present" if conftest else "No shared fixtures",
        remediation="Create tests/conftest.py with shared fixtures" if not conftest else "",
    ))

    # Pytest markers configured
    markers_configured = False
    if pyproject.is_file():
        content = pyproject.read_text()
        markers_configured = "markers" in content and "e2e" in content
    dim.checks.append(CheckResult(
        name="Pytest markers configured",
        passed=markers_configured,
        score=1.0 if markers_configured else 0.3,
        detail="Markers for e2e, benchmark, chaos, etc." if markers_configured else "No custom markers",
        remediation="Add markers to [tool.pytest.ini_options]" if not markers_configured else "",
    ))

    # Total test file count
    total_tests = count_files("tests", pattern="test_*.py")
    test_score = min(1.0, total_tests / 50)  # 50+ test files = full score
    dim.checks.append(CheckResult(
        name="Total test file count",
        passed=total_tests >= 30,
        score=test_score,
        detail=f"{total_tests} test files total",
        remediation="Write more tests to cover all modules" if total_tests < 30 else "",
    ))

    return dim


def check_ci_cd() -> DimensionResult:
    """Check CI/CD configuration."""
    dim = DimensionResult(name="CI/CD", weight=WEIGHTS["ci_cd"])

    # GitHub workflows
    workflows = [
        ("ci.yml", "CI pipeline (lint, test, typecheck)"),
        ("security.yml", "Security audit (pip-audit, safety)"),
        ("docs.yml", "Documentation build"),
        ("model-evolution.yml", "Model training pipeline"),
    ]
    for fname, desc in workflows:
        exists = file_exists(".github", "workflows", fname)
        dim.checks.append(CheckResult(
            name=f"Workflow: {fname}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=desc,
            remediation=f"Create .github/workflows/{fname}" if not exists else "",
        ))

    # Dependabot
    dependabot = file_exists(".github", "dependabot.yml")
    dim.checks.append(CheckResult(
        name="Dependabot configuration",
        passed=dependabot,
        score=1.0 if dependabot else 0.0,
        detail="Automated dependency updates" if dependabot else "No Dependabot config",
        remediation="Create .github/dependabot.yml" if not dependabot else "",
    ))

    # Dockerfiles
    dockerfiles = [
        ("Dockerfile.proxy", "Proxy Dockerfile"),
        ("Dockerfile.etl", "ETL Dockerfile"),
    ]
    for fname, desc in dockerfiles:
        exists = file_exists(fname)
        dim.checks.append(CheckResult(
            name=f"Dockerfile: {fname}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=desc,
            remediation=f"Create {fname}" if not exists else "",
        ))

    # Docker Compose
    compose_files: list[tuple[tuple[str, ...], str]] = [
        (("proxy", "docker-compose.yml"), "Main compose file"),
        (("deploy", "docker", "docker-compose.prod.yml"), "Production compose"),
    ]
    for path_parts, desc in compose_files:
        exists = file_exists(*path_parts)
        dim.checks.append(CheckResult(
            name=f"Docker Compose: {path_parts[-1]}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=desc,
            remediation=f"Create {'/'.join(path_parts)}" if not exists else "",
        ))

    # Makefile targets
    makefile = ROOT / "Makefile"
    important_targets = ["test", "lint", "format", "typecheck", "docker-build", "docker-up"]
    if makefile.is_file():
        content = makefile.read_text()
        found_targets = [t for t in important_targets if f"{t}:" in content]
        target_score = len(found_targets) / len(important_targets)
        dim.checks.append(CheckResult(
            name="Makefile dev targets",
            passed=len(found_targets) >= 5,
            score=target_score,
            detail=f"{len(found_targets)}/{len(important_targets)} targets: {', '.join(found_targets)}",
            remediation=f"Add missing targets: {', '.join(set(important_targets) - set(found_targets))}" if len(found_targets) < 5 else "",
        ))
    else:
        dim.checks.append(CheckResult(
            name="Makefile dev targets",
            passed=False,
            score=0.0,
            detail="No Makefile found",
        ))

    # K8s/Helm
    k8s = dir_exists("deploy", "k8s", "helm")
    dim.checks.append(CheckResult(
        name="Kubernetes Helm chart",
        passed=k8s,
        score=1.0 if k8s else 0.0,
        detail="Helm chart present" if k8s else "No Helm chart",
        remediation="Create deploy/k8s/helm/rag-system/ chart" if not k8s else "",
    ))

    # Nginx/HAProxy
    has_reverse_proxy = dir_exists("deploy", "nginx") or dir_exists("deploy", "haproxy")
    dim.checks.append(CheckResult(
        name="Reverse proxy config",
        passed=has_reverse_proxy,
        score=1.0 if has_reverse_proxy else 0.0,
        detail="Nginx/HAProxy config present" if has_reverse_proxy else "No reverse proxy config",
        remediation="Add nginx or haproxy config in deploy/" if not has_reverse_proxy else "",
    ))

    return dim


def check_security() -> DimensionResult:
    """Check security measures."""
    dim = DimensionResult(name="Security", weight=WEIGHTS["security"])

    # Auth module
    auth_files: list[tuple[tuple[str, ...], str]] = [
        (("proxy", "app", "auth", "jwt.py"), "JWT authentication"),
        (("proxy", "app", "auth", "rbac.py"), "Role-based access control"),
        (("proxy", "app", "auth", "user_db.py"), "User database"),
        (("proxy", "app", "auth", "api_keys.py"), "API key management"),
        (("proxy", "app", "auth", "ldap.py"), "LDAP integration"),
        (("proxy", "app", "auth", "secret_rotation.py"), "Secret rotation"),
    ]
    for path_parts, desc in auth_files:
        exists = file_exists(*path_parts)
        dim.checks.append(CheckResult(
            name=f"Auth: {desc}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=f"{'/'.join(path_parts)}",
            remediation=f"Implement {desc}" if not exists else "",
        ))

    # Input validation
    has_input_validation = file_exists("proxy", "app", "shared", "security.py")
    dim.checks.append(CheckResult(
        name="Input validation (InputValidator)",
        passed=has_input_validation,
        score=1.0 if has_input_validation else 0.0,
        detail="proxy/app/shared/security.py" if has_input_validation else "No input validator",
        remediation="Create InputValidator class for query/message sanitization" if not has_input_validation else "",
    ))

    # Rate limiting
    has_rate_limiter = file_exists("proxy", "app", "shared", "rate_limiter.py")
    dim.checks.append(CheckResult(
        name="Rate limiting middleware",
        passed=has_rate_limiter,
        score=1.0 if has_rate_limiter else 0.0,
        detail="Token bucket rate limiter" if has_rate_limiter else "No rate limiter",
        remediation="Implement token bucket rate limiter middleware" if not has_rate_limiter else "",
    ))

    # Circuit breaker
    has_circuit_breaker = file_exists("proxy", "app", "shared", "circuit_breaker.py")
    dim.checks.append(CheckResult(
        name="Circuit breaker",
        passed=has_circuit_breaker,
        score=1.0 if has_circuit_breaker else 0.0,
        detail="Circuit breaker for downstream calls" if has_circuit_breaker else "No circuit breaker",
        remediation="Implement circuit breaker pattern" if not has_circuit_breaker else "",
    ))

    # Pre-commit hooks
    has_precommit = file_exists(".pre-commit-config.yaml")
    dim.checks.append(CheckResult(
        name="Pre-commit hooks",
        passed=has_precommit,
        score=1.0 if has_precommit else 0.0,
        detail="Ruff lint + format + trailing whitespace" if has_precommit else "No pre-commit config",
        remediation="Create .pre-commit-config.yaml" if not has_precommit else "",
    ))

    # Security workflow
    has_security_wf = file_exists(".github", "workflows", "security.yml")
    dim.checks.append(CheckResult(
        name="Security audit workflow",
        passed=has_security_wf,
        score=1.0 if has_security_wf else 0.0,
        detail="pip-audit + safety + SBOM generation" if has_security_wf else "No security workflow",
        remediation="Create .github/workflows/security.yml" if not has_security_wf else "",
    ))

    # Secret masking
    has_secret_masking = False
    security_file = ROOT / "proxy" / "app" / "shared" / "security.py"
    if security_file.is_file():
        content = security_file.read_text()
        has_secret_masking = "sanitize_for_log" in content or "mask" in content.lower()
    dim.checks.append(CheckResult(
        name="Secret masking in logs",
        passed=has_secret_masking,
        score=1.0 if has_secret_masking else 0.0,
        detail="PII/secret sanitization in security.py" if has_secret_masking else "No secret masking",
        remediation="Implement sanitize_for_log() to mask PII and secrets" if not has_secret_masking else "",
    ))

    # CORS configuration
    has_cors = False
    middleware_file = ROOT / "proxy" / "app" / "shared" / "middleware.py"
    if middleware_file.is_file():
        content = middleware_file.read_text()
        has_cors = "CORS" in content or "cors" in content.lower()
    dim.checks.append(CheckResult(
        name="CORS configuration",
        passed=has_cors,
        score=1.0 if has_cors else 0.0,
        detail="CORS middleware configured" if has_cors else "No CORS config",
        remediation="Add CORS middleware with configurable origins" if not has_cors else "",
    ))

    # Audit logging
    has_audit = file_exists("proxy", "app", "shared", "audit.py")
    dim.checks.append(CheckResult(
        name="Audit logging",
        passed=has_audit,
        score=1.0 if has_audit else 0.0,
        detail="Request/feedback audit trail" if has_audit else "No audit logging",
        remediation="Implement audit.py for request tracing" if not has_audit else "",
    ))

    return dim


def check_rag_capabilities() -> DimensionResult:
    """Check RAG-specific capabilities across the 5 maturity levels."""
    dim = DimensionResult(name="RAG Capabilities", weight=WEIGHTS["rag_capabilities"])

    # Level 1: Naive RAG
    l1_checks: list[tuple[tuple[str, ...], str]] = [
        (("proxy", "app", "core", "retrieval.py"), "Dense vector retrieval"),
        (("proxy", "app", "core", "rerank.py"), "Cross-encoder reranking"),
    ]
    for path_parts, desc in l1_checks:
        exists = file_exists(*path_parts)
        dim.checks.append(CheckResult(
            name=f"L1 — {desc}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=f"{'/'.join(path_parts)}",
        ))

    # Level 2: Advanced RAG
    l2_checks: list[tuple[tuple[str, ...], str, str | None]] = [
        (("proxy", "app", "core", "retrieval.py"), "Hybrid search (dense+sparse RRF)", "rrf|reciprocal_rank"),
        (("proxy", "app", "core", "context", "builder.py"), "Context assembly", None),
        (("proxy", "app", "core", "token_optimizer.py"), "Token budget management", None),
        (("proxy", "app", "shared", "cache.py"), "Multi-tier caching", None),
    ]
    for path_parts, desc, search_term in l2_checks:
        exists = file_exists(*path_parts)
        if exists and search_term:
            content = (ROOT / Path(*path_parts)).read_text(encoding="utf-8", errors="ignore")
            exists = bool(re.search(search_term, content, re.IGNORECASE))
        dim.checks.append(CheckResult(
            name=f"L2 — {desc}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=f"{'/'.join(path_parts)}",
        ))

    # Level 3: GraphRAG
    l3_checks: list[tuple[tuple[str, ...], str]] = [
        (("etl", "graph_builder", "entity_extractor.py"), "Entity extraction"),
        (("etl", "graph_builder", "neo4j_loader.py"), "Neo4j graph loader"),
        (("etl", "graph_builder", "schema.yaml"), "Graph schema"),
    ]
    for path_parts, desc in l3_checks:
        exists = file_exists(*path_parts)
        dim.checks.append(CheckResult(
            name=f"L3 — {desc}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=f"{'/'.join(path_parts)}",
        ))

    # Level 4: Agentic RAG
    l4_checks: list[tuple[tuple[str, ...], str]] = [
        (("proxy", "app", "core", "orchestrator", "graph.py"), "LangGraph state graph"),
        (("proxy", "app", "core", "orchestrator", "nodes.py"), "Graph node implementations"),
        (("proxy", "app", "llm", "slm.py"), "SLM intent classification"),
    ]
    for path_parts, desc in l4_checks:
        exists = file_exists(*path_parts)
        dim.checks.append(CheckResult(
            name=f"L4 — {desc}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=f"{'/'.join(path_parts)}",
        ))

    # Level 5: Self-Correcting RAG
    l5_checks: list[tuple[tuple[str, ...], str]] = [
        (("proxy", "app", "core", "retrieval_evaluator.py"), "CRAG retrieval evaluator"),
        (("proxy", "app", "core", "confidence.py"), "Confidence scoring"),
        (("proxy", "app", "core", "grounding.py"), "NLI grounding check"),
        (("proxy", "app", "core", "hallucination.py"), "Hallucination detection"),
        (("proxy", "app", "core", "query_enhancer.py"), "HyDE query expansion"),
        (("proxy", "app", "core", "evaluation.py"), "Retrieval evaluation pipeline"),
        (("proxy", "app", "core", "enricher.py"), "Self-enrichment (feedback to chunks)"),
        (("proxy", "app", "core", "hitl.py"), "HITL interaction logging"),
    ]
    for path_parts, desc in l5_checks:
        exists = file_exists(*path_parts)
        dim.checks.append(CheckResult(
            name=f"L5 — {desc}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=f"{'/'.join(path_parts)}",
        ))

    # Observability
    obs_checks: list[tuple[tuple[str, ...], str]] = [
        (("proxy", "app", "shared", "metrics.py"), "Prometheus metrics"),
        (("proxy", "app", "api", "metrics.py"), "Metrics endpoint"),
        (("proxy", "app", "api", "health.py"), "Health check endpoints"),
        (("proxy", "app", "shared", "logging.py"), "Structured logging"),
        (("proxy", "app", "shared", "tracing.py"), "Distributed tracing"),
    ]
    for path_parts, desc in obs_checks:
        exists = file_exists(*path_parts)
        dim.checks.append(CheckResult(
            name=f"Observability — {desc}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=f"{'/'.join(path_parts)}",
        ))

    # Monitoring stack
    monitoring_checks: list[tuple[tuple[str, ...], str]] = [
        (("config", "monitoring", "alerts.yml"), "Prometheus alert rules"),
        (("config", "monitoring", "grafana"), "Grafana dashboards"),
        (("config", "monitoring", "prometheus"), "Prometheus config"),
    ]
    for path_parts, desc in monitoring_checks:
        exists = file_exists(*path_parts) or dir_exists(*path_parts)
        dim.checks.append(CheckResult(
            name=f"Monitoring — {desc}",
            passed=exists,
            score=1.0 if exists else 0.0,
            detail=f"{'/'.join(path_parts)}",
        ))

    # Agentic tools
    has_tools = dir_exists("proxy", "app", "tools")
    dim.checks.append(CheckResult(
        name="Agentic Tools SDK",
        passed=has_tools,
        score=1.0 if has_tools else 0.0,
        detail="proxy/app/tools/ directory" if has_tools else "No tools SDK",
    ))

    # MCP server
    has_mcp = file_exists("mcp_server", "server.py")
    dim.checks.append(CheckResult(
        name="MCP server",
        passed=has_mcp,
        score=1.0 if has_mcp else 0.0,
        detail="mcp_server/server.py" if has_mcp else "No MCP server",
    ))

    # Model evolution
    has_model_evo = dir_exists("proxy", "app", "model_evolution")
    dim.checks.append(CheckResult(
        name="Model evolution pipeline",
        passed=has_model_evo,
        score=1.0 if has_model_evo else 0.0,
        detail="LoRA/QLoRA fine-tuning pipeline" if has_model_evo else "No model evolution",
    ))

    # Multi-provider LLM
    has_providers = dir_exists("proxy", "app", "llm", "provider")
    dim.checks.append(CheckResult(
        name="Multi-provider LLM routing",
        passed=has_providers,
        score=1.0 if has_providers else 0.0,
        detail="Pluggable provider adapters" if has_providers else "No provider adapters",
    ))

    # Backup scripts
    has_backups = dir_exists("scripts", "ops")
    dim.checks.append(CheckResult(
        name="Backup & restore scripts",
        passed=has_backups,
        score=1.0 if has_backups else 0.0,
        detail="scripts/ops/ with backup_cron.sh, restore_all.sh" if has_backups else "No backup scripts",
    ))

    return dim


# ── RAG Level Assessment ─────────────────────────────────────────────────────


def assess_rag_level(dimensions: list[DimensionResult]) -> tuple[int, float]:
    """Compute RAG maturity level from capability checks."""
    rag_dim = next((d for d in dimensions if d.name == "RAG Capabilities"), None)
    if not rag_dim:
        return 0, 0.0

    # Group checks by level
    level_scores: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    for check in rag_dim.checks:
        for level in range(1, 6):
            if check.name.startswith(f"L{level} —"):
                level_scores[level].append(check.score)
                break

    # Compute per-level scores
    level_avgs: dict[int, float] = {}
    for level, scores in level_scores.items():
        if scores:
            level_avgs[level] = sum(scores) / len(scores)
        else:
            level_avgs[level] = 0.0

    # Determine highest level with >= 80% score
    rag_level = 0
    for level in range(5, 0, -1):
        if level_avgs.get(level, 0) >= 0.8:
            rag_level = level
            break

    # Composite score (weighted)
    total_weight = 0.0
    weighted_sum = 0.0
    for level in range(1, 6):
        weight = RAG_LEVEL_WEIGHTS[level]
        total_weight += weight
        weighted_sum += level_avgs.get(level, 0.0) * weight

    composite = (weighted_sum / total_weight) * 5.0 if total_weight > 0 else 0.0

    return rag_level, round(composite, 2)


# ── Recommendations Generator ────────────────────────────────────────────────


def generate_recommendations(report: MaturityReport) -> list[str]:
    """Generate prioritized recommendations from failed/weak checks."""
    recommendations: list[tuple[float, str]] = []

    for dim in report.dimensions:
        for check in dim.checks:
            if not check.passed and check.remediation:
                # Priority: weight * (1 - score) — higher weight gaps get priority
                priority = dim.weight * (1.0 - check.score)
                recommendations.append((priority, check.remediation))

    # Sort by priority (descending)
    recommendations.sort(key=lambda x: x[0], reverse=True)

    # Deduplicate and limit
    seen: set[str] = set()
    unique: list[str] = []
    for _, rec in recommendations:
        if rec not in seen:
            seen.add(rec)
            unique.append(rec)
    return unique[:15]


# ── Report Renderers ─────────────────────────────────────────────────────────


def render_markdown(report: MaturityReport) -> str:
    """Render the report as Markdown."""
    lines: list[str] = []
    a = lines.append

    a(f"# RAG System Maturity Review")
    a("")
    a(f"**Project:** {report.project_name}")
    a(f"**Version:** {report.version}")
    a(f"**Date:** {report.timestamp}")
    a(f"**Overall Score:** {report.overall_score:.1%} (Grade: {report.overall_grade})")
    a(f"**RAG Maturity:** Level {report.rag_level} — {report.maturity_label} (composite: {report.rag_composite}/5.0)")
    a("")
    a("---")
    a("")

    # Summary table
    a("## Summary")
    a("")
    a("| Dimension | Score | Passed | Weight |")
    a("|-----------|-------|--------|--------|")
    for dim in report.dimensions:
        bar = "█" * int(dim.score * 10) + "░" * (10 - int(dim.score * 10))
        a(f"| {dim.name} | {bar} {dim.score:.0%} | {dim.passed_count}/{dim.total_count} | {dim.weight:.0%} |")
    a(f"| **Overall** | **{report.overall_score:.0%}** | — | **100%** |")
    a("")

    # RAG Level breakdown
    a("## RAG Maturity Level Breakdown")
    a("")
    rag_dim = next((d for d in report.dimensions if d.name == "RAG Capabilities"), None)
    if rag_dim:
        current_level = 0
        for check in rag_dim.checks:
            for level in range(1, 6):
                if check.name.startswith(f"L{level} —"):
                    if level != current_level:
                        if current_level > 0:
                            a("")
                        a(f"### Level {level}")
                        current_level = level
                    status = "✅" if check.passed else "❌"
                    a(f"- {status} {check.name.split(' — ', 1)[1]}")
                    break
    a("")

    # Detailed results per dimension
    a("## Detailed Results")
    a("")
    for dim in report.dimensions:
        a(f"### {dim.name} (weight: {dim.weight:.0%}, score: {dim.score:.0%})")
        a("")
        a("| Check | Status | Score | Detail |")
        a("|-------|--------|-------|--------|")
        for check in dim.checks:
            status = "✅" if check.passed else "❌"
            a(f"| {check.name} | {status} | {check.score:.0%} | {check.detail} |")
        a("")

    # Recommendations
    if report.recommendations:
        a("## Recommendations (Priority Order)")
        a("")
        for i, rec in enumerate(report.recommendations, 1):
            a(f"{i}. {rec}")
        a("")

    # Footer
    a("---")
    a("")
    a(f"*Generated by `scripts/maturity_review.py` on {report.timestamp}*")

    return "\n".join(lines)


def render_json(report: MaturityReport) -> str:
    """Render the report as JSON."""
    data: dict[str, Any] = {
        "project": report.project_name,
        "version": report.version,
        "timestamp": report.timestamp,
        "overall_score": round(report.overall_score, 4),
        "overall_grade": report.overall_grade,
        "rag_level": report.rag_level,
        "rag_composite": report.rag_composite,
        "rag_label": report.maturity_label,
        "dimensions": [],
        "recommendations": report.recommendations,
    }
    for dim in report.dimensions:
        dim_data: dict[str, Any] = {
            "name": dim.name,
            "weight": dim.weight,
            "score": round(dim.score, 4),
            "passed": dim.passed_count,
            "total": dim.total_count,
            "checks": [],
        }
        for check in dim.checks:
            dim_data["checks"].append({
                "name": check.name,
                "passed": check.passed,
                "score": round(check.score, 4),
                "detail": check.detail,
                "evidence": check.evidence,
                "remediation": check.remediation,
            })
        data["dimensions"].append(dim_data)
    return json.dumps(data, indent=2)


def render_quiet(report: MaturityReport) -> str:
    """Render minimal output — scores only."""
    lines = [
        f"RAG Maturity Review — {report.project_name} v{report.version}",
        f"Date: {report.timestamp}",
        "",
    ]
    for dim in report.dimensions:
        lines.append(f"  {dim.name:.<30s} {dim.score:.0%} ({dim.passed_count}/{dim.total_count})")
    lines.append("")
    lines.append(f"  {'Overall':.<30s} {report.overall_score:.0%} (Grade: {report.overall_grade})")
    lines.append(f"  {'RAG Level':.<30s} Level {report.rag_level} — {report.maturity_label}")
    lines.append(f"  {'RAG Composite':.<30s} {report.rag_composite}/5.0")
    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────


def run_review() -> MaturityReport:
    """Execute all maturity checks and produce a report."""
    report = MaturityReport(
        project_name="rag-system",
        version=read_pyproject_version(),
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )

    # Run all dimension checks
    report.dimensions = [
        check_project_structure(),
        check_documentation(),
        check_testing(),
        check_ci_cd(),
        check_security(),
        check_rag_capabilities(),
    ]

    # Compute RAG level
    report.rag_level, report.rag_composite = assess_rag_level(report.dimensions)

    # Generate recommendations
    report.recommendations = generate_recommendations(report)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated RAG System Maturity Review",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Write report to file (default: stdout)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output in JSON format",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output (scores only)",
    )
    args = parser.parse_args()

    report = run_review()

    if args.json:
        output = render_json(report)
    elif args.quiet:
        output = render_quiet(report)
    else:
        output = render_markdown(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"Report written to {output_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
