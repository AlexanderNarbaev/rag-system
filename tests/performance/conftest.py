"""Shared fixtures for performance benchmark tests."""

import json
import os
from pathlib import Path

import pytest

BENCHMARK_RESULTS_PATH = Path (__file__).parent / "benchmark_results.json"


@pytest.fixture (scope = "session")
def service_url () -> str:
  """Return the base URL of the running proxy service."""
  url = os.getenv ("E2E_SERVICE_URL", "http://localhost:8080")
  import requests

  try:
    resp = requests.get (f"{url}/v1/health/live", timeout = 3)
    if resp.status_code != 200:
      pytest.skip (f"Service not ready at {url}")
  except requests.exceptions.ConnectionError:
    pytest.skip (f"Service not reachable at {url}")
  return url


@pytest.fixture (scope = "session")
def benchmark_report ():
  """Accumulates benchmark results and writes JSON report at session end."""
  results = []

  yield results

  if results:
    BENCHMARK_RESULTS_PATH.parent.mkdir (parents = True, exist_ok = True)
    with open (BENCHMARK_RESULTS_PATH, "w") as f:
      json.dump (results, f, indent = 2, default = str)
