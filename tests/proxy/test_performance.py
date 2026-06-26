"""Tests for proxy performance features (SSE streaming + compression)."""
import json
import sys
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

_modules_to_mock = [
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "sentence_transformers",
    "langgraph",
    "langgraph.graph",
    "langgraph.checkpoint",
    "neo4j",
    "redis",
    "redis.asyncio",
    "tiktoken",
]

for mod in _modules_to_mock:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from proxy.app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class TestCompressionConfig:
    """Tests for response compression configuration."""

    def test_compression_config_defaults(self):
        """Verify default compression configuration values."""
        from proxy.app.config import COMPRESSION_ENABLED, COMPRESSION_MIN_SIZE, COMPRESSION_LEVEL
        assert isinstance(COMPRESSION_ENABLED, bool)
        assert isinstance(COMPRESSION_MIN_SIZE, int)
        assert isinstance(COMPRESSION_LEVEL, int)

    def test_compression_env_overrides(self):
        """Verify compression config reads from environment variables."""
        import os
        from importlib import reload

        os.environ["COMPRESSION_ENABLED"] = "true"
        os.environ["COMPRESSION_MIN_SIZE"] = "1024"
        os.environ["COMPRESSION_LEVEL"] = "9"

        import proxy.app.config
        reload(proxy.app.config)

        assert proxy.app.config.COMPRESSION_ENABLED is True
        assert proxy.app.config.COMPRESSION_MIN_SIZE == 1024
        assert proxy.app.config.COMPRESSION_LEVEL == 9

    def test_gzip_middleware_registered(self, client):
        """Verify GZipMiddleware is present when compression is enabled."""
        from proxy.app.main import app as main_app
        middleware_names = [str(m.cls) for m in main_app.user_middleware]
        assert "GZipMiddleware" in str(middleware_names)


class TestSSEStreamingConfig:
    """Tests for SSE streaming optimization configuration."""

    def test_sse_chunk_size_default(self):
        from proxy.app.config import SSE_CHUNK_SIZE, STREAM_BUFFER_SIZE
        assert isinstance(SSE_CHUNK_SIZE, int)
        assert SSE_CHUNK_SIZE > 0
        assert isinstance(STREAM_BUFFER_SIZE, int)
        assert STREAM_BUFFER_SIZE > 0

    def test_sse_chunk_size_env_override(self):
        import os
        from importlib import reload

        os.environ["SSE_CHUNK_SIZE"] = "8"
        os.environ["STREAM_BUFFER_SIZE"] = "2"

        import proxy.app.config
        reload(proxy.app.config)

        assert proxy.app.config.SSE_CHUNK_SIZE == 8
        assert proxy.app.config.STREAM_BUFFER_SIZE == 2


class TestStreamingTTFT:
    """Tests for SSE streaming time-to-first-token optimization."""

    def test_initial_chunk_sent_only_once(self):
        """Verify initial_chunk returns data only on first call."""
        from proxy.app.main import StreamOptimizer
        optimizer = StreamOptimizer()
        first = optimizer.initial_chunk()
        second = optimizer.initial_chunk()
        assert first != ""
        assert "initial_chunk" in first
        assert second == ""

    def test_stream_optimizer_initial_chunk(self):
        """Verify StreamOptimizer class sends initial empty chunk before content."""
        from proxy.app.main import StreamOptimizer
        optimizer = StreamOptimizer()
        assert optimizer.initial_chunk_sent is False
        assert optimizer.sse_chunk_size > 0
        assert optimizer.stream_buffer_size > 0

    def test_stream_optimizer_config_chunk_size(self):
        """Verify StreamOptimizer respects configured SSE_CHUNK_SIZE."""
        from proxy.app.main import StreamOptimizer
        optimizer = StreamOptimizer(chunk_size=6)
        assert optimizer.sse_chunk_size == 6

    def test_stream_optimizer_config_buffer_size(self):
        """Verify StreamOptimizer respects configured STREAM_BUFFER_SIZE."""
        from proxy.app.main import StreamOptimizer
        optimizer = StreamOptimizer(buffer_size=2)
        assert optimizer.stream_buffer_size == 2

    def test_format_chunk_produces_valid_sse(self):
        """Verify format_chunk outputs valid SSE data format."""
        from proxy.app.main import StreamOptimizer
        optimizer = StreamOptimizer()
        chunk = {"choices": [{"delta": {"content": "hello"}}]}
        formatted = optimizer.format_chunk(chunk)
        assert formatted.startswith("data: ")
        assert formatted.endswith("\n\n")
        assert "hello" in formatted
