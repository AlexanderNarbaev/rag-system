"""Shared fixtures for integration tests.

Provides common FastAPI TestClient setup, mock configurations,
and helper functions used across all integration test modules.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure proxy module is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))


# ---------------------------------------------------------------------------
# FastAPI TestClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client():
    """Create a FastAPI TestClient with all external dependencies mocked.

    Disables auth, langgraph, logging, and sets a test model name.
    Returns a ready-to-use TestClient for integration testing.
    """
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.USE_LANGGRAPH", False),
        patch("proxy.app.main.LOG_REQUESTS", False),
        patch("proxy.app.main.LLM_MODEL_NAME", "test-model"),
        patch("proxy.app.auth.jwt.AUTH_ENABLED", False),
    ):
        from fastapi.testclient import TestClient

        from proxy.app.main import app

        client = TestClient(app)
        yield client


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def make_scored_points(texts_with_meta):
    """Build fake Qdrant ScoredPoint objects for testing.

    Args:
        texts_with_meta: List of (text, score, metadata) tuples.

    Returns:
        List of mock ScoredPoint objects.
    """
    points = []
    for i, (text, score, meta) in enumerate(texts_with_meta):
        point = MagicMock()
        point.id = f"point_{i}"
        point.score = score
        point.payload = {"text": text, **meta}
        points.append(point)
    return points


def mock_qdrant_ok():
    """Return a mock qdrant_client that responds to get_collections."""
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[])
    return client


def mock_llm_response(content="Test response"):
    """Return a mock LLM response dict."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
