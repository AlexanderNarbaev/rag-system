"""Shared fixtures for chaos/resilience tests."""
import sys
from pathlib import Path

# Ensure proxy/app is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))
