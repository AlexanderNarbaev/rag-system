"""Opt-in Docker chaos tests for NFR-A05 graceful degradation.

Run against a live Docker deployment with CHAOS_TEST_ENABLED=1. The default
suite skips so ordinary unit-test runs never stop a developer's containers.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator

import httpx
import pytest

PROXY_URL = os.getenv("RAG_PROXY_URL", "http://localhost:8080")
CONTAINERS = {"qdrant": "rag-qdrant", "redis": "rag-redis", "neo4j": "rag-neo4j", "llm": "rag-vllm"}


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=60)


def _container_running(name: str) -> bool:
    result = _docker("inspect", "-f", "{{.State.Running}}", name, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


@pytest.fixture(scope="module", autouse=True)
def chaos_environment() -> Iterator[None]:
    """Require explicit opt-in and restore every stopped container afterward."""
    if os.getenv("CHAOS_TEST_ENABLED") != "1":
        pytest.skip("Set CHAOS_TEST_ENABLED=1 to run Docker chaos tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker is not installed")
    missing = [name for name in CONTAINERS.values() if not _container_running(name)]
    if missing:
        pytest.skip(f"Required running containers are unavailable: {', '.join(missing)}")
    yield


@pytest.fixture
def stopped_service(request: pytest.FixtureRequest) -> Iterator[str]:
    service = request.param
    container = CONTAINERS[service]
    _docker("stop", container)
    try:
        yield container
    finally:
        _docker("start", container, check=False)


def _chat() -> httpx.Response:
    return httpx.post(
        f"{PROXY_URL}/v1/chat/completions",
        json={"model": "test-model+RAG", "messages": [{"role": "user", "content": "Chaos test query"}]},
        timeout=30,
    )


def _response_text(response: httpx.Response) -> str:
    try:
        return json.dumps(response.json()).lower()
    except (ValueError, TypeError):
        return response.text.lower()


@pytest.mark.chaos
@pytest.mark.parametrize("stopped_service", ["qdrant"], indirect=True)
def test_qdrant_failure_returns_ungrounded_response(stopped_service: str) -> None:
    """Qdrant failure must not prevent a 200 response from the proxy."""
    response = _chat()
    assert response.status_code == 200
    body = _response_text(response)
    assert any(term in body for term in ("ungrounded", "without context", "no context", "degraded"))


@pytest.mark.chaos
@pytest.mark.parametrize("stopped_service", ["redis"], indirect=True)
def test_redis_failure_uses_in_memory_cache(stopped_service: str) -> None:
    """Redis failure must fall back to the in-memory cache path."""
    response = _chat()
    assert response.status_code == 200


@pytest.mark.chaos
@pytest.mark.parametrize("stopped_service", ["llm"], indirect=True)
def test_llm_failure_returns_service_unavailable(stopped_service: str) -> None:
    """LLM failure is fatal to generation and must be reported as 503."""
    response = _chat()
    assert response.status_code == 503
    assert any(term in _response_text(response) for term in ("llm", "unavailable", "generation", "error"))


@pytest.mark.chaos
@pytest.mark.parametrize("stopped_service", ["neo4j"], indirect=True)
def test_neo4j_failure_skips_graph_expansion(stopped_service: str) -> None:
    """Neo4j failure must skip graph expansion while serving the answer."""
    response = _chat()
    assert response.status_code == 200
