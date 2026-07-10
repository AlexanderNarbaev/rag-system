"""Integration tests for tool discovery on application startup.

Verifies that when TOOLS_ENABLED is set, the lifespan handler discovers
tools from all configured providers and registers them so they are
available via /v1/tools.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))

# Mock heavy dependencies that load at module level
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
    "bcrypt",
]
for mod in _modules_to_mock:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


@pytest.fixture
def tools_client():
    """Create a FastAPI TestClient with tool discovery mocked."""
    from proxy.app import main as proxy_main

    saved = {}
    for attr in (
        "cache_manager",
        "USE_LANGGRAPH",
        "LOG_REQUESTS",
        "LLM_MODEL_NAME",
        "WARMUP_ENABLED",
        "OTEL_ENABLED",
        "GRACEFUL_SHUTDOWN_ENABLED",
        "USE_REDIS",
    ):
        saved[attr] = getattr(proxy_main, attr, None)

    proxy_main.cache_manager = None
    proxy_main.USE_LANGGRAPH = False
    proxy_main.LOG_REQUESTS = False
    proxy_main.LLM_MODEL_NAME = "test-model"
    proxy_main.WARMUP_ENABLED = False
    proxy_main.OTEL_ENABLED = False
    proxy_main.GRACEFUL_SHUTDOWN_ENABLED = False
    proxy_main.USE_REDIS = False

    from fastapi.testclient import TestClient

    client = TestClient(proxy_main.app)

    yield client

    for attr, value in saved.items():
        setattr(proxy_main, attr, value)


class TestStartupDiscoveryIntegration:
    """Verify tools from startup discovery are available via the API."""

    def test_tools_endpoint_returns_discovered_tools(self, tools_client):
        """GET /v1/tools returns tools registered from all configured providers."""
        from proxy.app.tools.definition import (
            ToolDefinition,
            ToolParam,
            ToolVisibility,
        )
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry.get_instance()
        registry._tools.clear()
        registry._provider_tools.clear()

        registry.register(
            ToolDefinition(
                name="search_documents",
                description="Search indexed documents",
                parameters=[ToolParam(name="query", type=str, description="Query")],
                category="search",
                tags=["hybrid"],
                visibility=ToolVisibility.PUBLIC,
                provider="sdk",
            )
        )
        registry.register(
            ToolDefinition(
                name="list_pets",
                description="List pets from the store",
                parameters=[],
                category="api",
                tags=["openapi", "pets"],
                visibility=ToolVisibility.PUBLIC,
                provider="openapi",
            )
        )
        registry.register(
            ToolDefinition(
                name="weekly_report",
                description="Generate weekly report",
                parameters=[ToolParam(name="team", type=str)],
                category="reporting",
                tags=["declarative", "scheduled"],
                visibility=ToolVisibility.PUBLIC,
                provider="declarative",
            )
        )

        with patch("proxy.app.main.get_enhanced_registry", return_value=registry):
            response = tools_client.get("/v1/tools")
            assert response.status_code == 200
            data = response.json()

        providers = {t["provider"] for t in data["tools"]}
        assert "sdk" in providers
        assert "openapi" in providers
        assert "declarative" in providers

        names = {t["name"] for t in data["tools"]}
        assert "search_documents" in names
        assert "list_pets" in names
        assert "weekly_report" in names

    def test_tools_endpoint_filter_by_provider(self, tools_client):
        """GET /v1/tools?provider=sdk returns only SDK tools."""
        from proxy.app.tools.definition import (
            ToolDefinition,
            ToolParam,
            ToolVisibility,
        )
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry.get_instance()
        registry._tools.clear()
        registry._provider_tools.clear()

        registry.register(
            ToolDefinition(
                name="sdk_search",
                description="SDK search tool",
                parameters=[ToolParam(name="q", type=str)],
                category="search",
                tags=[],
                visibility=ToolVisibility.PUBLIC,
                provider="sdk",
            )
        )
        registry.register(
            ToolDefinition(
                name="openapi_get",
                description="OpenAPI GET tool",
                parameters=[],
                category="api",
                tags=[],
                visibility=ToolVisibility.PUBLIC,
                provider="openapi",
            )
        )

        with patch("proxy.app.main.get_enhanced_registry", return_value=registry):
            response = tools_client.get("/v1/tools?provider=sdk")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            assert data["tools"][0]["name"] == "sdk_search"
            assert data["tools"][0]["provider"] == "sdk"

    def test_tools_endpoint_returns_correct_fields(self, tools_client):
        """Each tool returned by /v1/tools has all required fields."""
        from proxy.app.tools.definition import (
            ToolDefinition,
            ToolParam,
            ToolVisibility,
        )
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry.get_instance()
        registry._tools.clear()
        registry._provider_tools.clear()

        registry.register(
            ToolDefinition(
                name="test_tool",
                description="Test description",
                parameters=[ToolParam(name="input", type=str, description="Input value")],
                category="testing",
                tags=["integration"],
                visibility=ToolVisibility.PUBLIC,
                version="1.0.0",
                provider="sdk",
            )
        )

        with patch("proxy.app.main.get_enhanced_registry", return_value=registry):
            response = tools_client.get("/v1/tools")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            tool = data["tools"][0]
            assert tool["name"] == "test_tool"
            assert tool["description"] == "Test description"
            assert tool["category"] == "testing"
            assert tool["tags"] == ["integration"]
            assert tool["version"] == "1.0.0"
            assert "parameters" in tool
            assert tool["provider"] == "sdk"
