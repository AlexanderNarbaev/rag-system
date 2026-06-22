
"""Shared fixtures and configuration for proxy tests."""
import os
import sys
import pytest
from pathlib import Path

# Ensure proxy/app is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Isolate environment variables to prevent leakage between tests."""
    for key in list(os.environ.keys()):
        if key.startswith("TEST_"):
            monkeypatch.delenv(key, raising=False)
