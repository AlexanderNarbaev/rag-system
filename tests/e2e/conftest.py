"""Shared fixtures for E2E tests.

These tests require running services (proxy, Qdrant, Redis, Neo4j).
Run with: pytest tests/e2e/ -v -m e2e
Skip with:  pytest -m "not e2e"
"""

import os
import time

import pytest
import requests

SERVICE_URL = os.getenv("E2E_SERVICE_URL", "http://localhost:8080")


def _check_service_ready(url: str, timeout: int = 30) -> bool:
    """Wait for a service to become healthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/v1/health/live", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="session")
def service_url() -> str:
    """Return the base URL of the running proxy service.

    Skips the entire session if the service is not available.
    """
    if not _check_service_ready(SERVICE_URL):
        pytest.skip(f"E2E service not available at {SERVICE_URL}")
    return SERVICE_URL


@pytest.fixture(scope="session")
def auth_headers(service_url: str) -> dict:
    """Login and return JWT auth headers for authenticated requests."""
    try:
        resp = requests.post(
            f"{service_url}/v1/auth/login",
            json={"username": "testuser", "password": "testpass"},
            timeout=5,
        )
        if resp.status_code == 200:
            token = resp.json()["access_token"]
            return {"Authorization": f"Bearer {token}"}
    except requests.exceptions.ConnectionError:
        pass
    # Auth may not be enabled in E2E setup
    return {}
