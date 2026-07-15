"""Shared fixtures and configuration for proxy tests."""

import os
import sys
from pathlib import Path

import pytest

# Ensure proxy/app is importable
sys.path.insert (0, str (Path (__file__).parent.parent.parent / "proxy"))


@pytest.fixture (autouse = True)
def _isolate_env (monkeypatch):
  """Isolate environment variables to prevent leakage between tests."""
  for key in list (os.environ.keys ()):
    if key.startswith ("TEST_"):
      monkeypatch.delenv (key, raising = False)

  # Default: disable auth for tests that don't test auth specifically.
  # Tests that need auth should monkeypatch AUTH_ENABLED back to True.
  monkeypatch.setenv ("AUTH_ENABLED", "false")
  try:
    import proxy.app.auth.jwt as _jwt
    import proxy.app.shared.config as _cfg

    monkeypatch.setattr (_cfg, "AUTH_ENABLED", False)
    monkeypatch.setattr (_jwt, "AUTH_ENABLED", False)
  except ImportError:
    pass
