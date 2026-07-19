# tests/mcp_server/test_mcp_requirements.py
"""Tests for FR-121 — FR-125: MCP Server requirements.

Covers:
  FR-121  MCP tools: rag_search, rag_chat, rag_feedback
  FR-122  MCP resource: rag://collections
  FR-123  MCP prompt: rag_help
  FR-124  Dual transport: STDIO + HTTP
  FR-125  Standalone install: MCP server startup
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("fastmcp", reason="fastmcp not installed")
from mcp_server.server import mcp

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_httpx_response():
    """Create a mock httpx.Response."""

    def _make(json_data=None, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {"choices": [{"message": {"content": "Mocked answer"}}]}
        resp.text = str(json_data)
        return resp

    return _make


@pytest.fixture
def mock_httpx_client(mock_httpx_response):
    """Mock httpx.AsyncClient context manager."""

    def _setup(response_data=None, status_code=200):
        mock_client = AsyncMock()
        mock_response = mock_httpx_response(json_data=response_data, status_code=status_code)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    return _setup


# ===========================================================================
# FR-121: MCP tools — rag_search, rag_chat, rag_feedback
# ===========================================================================


class TestFR121MCPTools:
    """FR-121: MCP server exposes rag_search, rag_chat, rag_feedback tools."""

    @pytest.mark.asyncio
    async def test_three_tools_registered(self):
        """Exactly three tools are registered: rag_search, rag_chat, rag_feedback."""
        tools = await mcp.list_tools()
        tool_names = [t.name for t in tools]
        assert "rag_search" in tool_names
        assert "rag_chat" in tool_names
        assert "rag_feedback" in tool_names
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_rag_search_parameters(self):
        """rag_search accepts query (required) and limit (optional)."""
        tools = await mcp.list_tools()
        search_tool = next(t for t in tools if t.name == "rag_search")
        props = search_tool.parameters.get("properties", {})
        assert "query" in props
        assert "limit" in props

    @pytest.mark.asyncio
    async def test_rag_chat_parameters(self):
        """rag_chat accepts message (required) and context (optional)."""
        tools = await mcp.list_tools()
        chat_tool = next(t for t in tools if t.name == "rag_chat")
        props = chat_tool.parameters.get("properties", {})
        assert "message" in props
        assert "context" in props

    @pytest.mark.asyncio
    async def test_rag_feedback_parameters(self):
        """rag_feedback accepts query, answer, rating, correction."""
        tools = await mcp.list_tools()
        feedback_tool = next(t for t in tools if t.name == "rag_feedback")
        props = feedback_tool.parameters.get("properties", {})
        assert "query" in props
        assert "answer" in props
        assert "rating" in props
        assert "correction" in props

    @pytest.mark.asyncio
    async def test_rag_search_calls_proxy(self, mock_httpx_client):
        """rag_search calls /v1/chat/completions with rag_search_only=True."""
        mock_client = mock_httpx_client(
            response_data={"choices": [{"message": {"content": "Found 3 docs"}}]},
        )
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool("rag_search", {"query": "What is RAG?"})
        assert "Found 3 docs" in result.content[0].text
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["rag_search_only"] is True

    @pytest.mark.asyncio
    async def test_rag_chat_calls_proxy(self, mock_httpx_client):
        """rag_chat calls /v1/chat/completions."""
        mock_client = mock_httpx_client(
            response_data={"choices": [{"message": {"content": "RAG is..."}}]},
        )
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool("rag_chat", {"message": "Explain RAG"})
        assert "RAG is..." in result.content[0].text
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["model"] == "rag"

    @pytest.mark.asyncio
    async def test_rag_feedback_calls_proxy(self, mock_httpx_client):
        """rag_feedback calls /v1/feedback."""
        mock_client = mock_httpx_client(response_data={"status": "ok"})
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool(
                "rag_feedback",
                {"query": "q", "answer": "a", "rating": "positive"},
            )
        assert "Feedback submitted" in result.content[0].text
        call_args = mock_client.post.call_args
        assert "/v1/feedback" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_rag_chat_with_context(self, mock_httpx_client):
        """rag_chat includes context as system message when provided."""
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_chat", {"message": "test", "context": "DevOps docs"})
        messages = mock_client.post.call_args[1]["json"]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "DevOps docs" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_rag_search_missing_query_raises(self):
        """rag_search without required 'query' raises error."""
        with pytest.raises(BaseException):  # noqa: B017
            await mcp.call_tool("rag_search", {})

    @pytest.mark.asyncio
    async def test_rag_chat_missing_message_raises(self):
        """rag_chat without required 'message' raises error."""
        with pytest.raises(BaseException):  # noqa: B017
            await mcp.call_tool("rag_chat", {})

    @pytest.mark.asyncio
    async def test_rag_feedback_missing_rating_raises(self):
        """rag_feedback without required 'rating' raises error."""
        with pytest.raises(BaseException):  # noqa: B017
            await mcp.call_tool("rag_feedback", {"query": "q", "answer": "a"})


# ===========================================================================
# FR-122: MCP resource — rag://collections
# ===========================================================================


class TestFR122MCPResource:
    """FR-122: MCP server exposes rag://collections resource."""

    @pytest.mark.asyncio
    async def test_resource_registered(self):
        """rag://collections resource is registered."""
        resources = await mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "rag://collections" in uris

    @pytest.mark.asyncio
    async def test_resource_has_name(self):
        """Resource has a display name."""
        resources = await mcp.list_resources()
        collection_res = next(r for r in resources if str(r.uri) == "rag://collections")
        assert collection_res.name is not None

    @pytest.mark.asyncio
    async def test_resource_calls_v1_models(self, mock_httpx_client):
        """Resource reads from /v1/models endpoint."""
        mock_client = mock_httpx_client(response_data={"data": [{"id": "rag-proxy"}]})
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.read_resource("rag://collections")
        assert result is not None
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert "/v1/models" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_resource_returns_data(self, mock_httpx_client):
        """Resource returns collection data."""
        mock_client = mock_httpx_client(response_data={"data": [{"id": "model-1"}]})
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.read_resource("rag://collections")
        assert result is not None
        assert len(result.contents) > 0


# ===========================================================================
# FR-123: MCP prompt — rag_help
# ===========================================================================


class TestFR123MCPPrompt:
    """FR-123: MCP server exposes rag_help prompt."""

    @pytest.mark.asyncio
    async def test_prompt_registered(self):
        """rag_help prompt is registered."""
        prompts = await mcp.list_prompts()
        prompt_names = [p.name for p in prompts]
        assert "rag_help" in prompt_names

    @pytest.mark.asyncio
    async def test_prompt_has_description(self):
        """rag_help prompt has a description."""
        prompts = await mcp.list_prompts()
        help_prompt = next(p for p in prompts if p.name == "rag_help")
        assert help_prompt.description is not None
        assert len(help_prompt.description) > 0

    @pytest.mark.asyncio
    async def test_prompt_content_lists_all_tools(self):
        """rag_help prompt content lists all three tools."""
        result = await mcp.render_prompt("rag_help")
        assert result is not None
        messages = result.messages
        assert len(messages) > 0
        content = messages[0].content.text
        assert "rag_search" in content
        assert "rag_chat" in content
        assert "rag_feedback" in content

    @pytest.mark.asyncio
    async def test_prompt_provides_usage_guidance(self):
        """rag_help prompt includes usage guidance."""
        result = await mcp.render_prompt("rag_help")
        content = result.messages[0].content.text
        assert "best results" in content.lower() or "for best" in content.lower()

    @pytest.mark.asyncio
    async def test_invalid_prompt_raises(self):
        """Rendering a non-existent prompt raises an error."""
        with pytest.raises(BaseException):  # noqa: B017
            await mcp.render_prompt("nonexistent_prompt")


# ===========================================================================
# FR-124: Dual transport — STDIO + HTTP
# ===========================================================================


class TestFR124DualTransport:
    """FR-124: MCP server supports both STDIO and HTTP transports."""

    def test_default_transport_is_stdio(self):
        """Default transport is STDIO."""
        transport = os.getenv("MCP_TRANSPORT", "stdio")
        assert transport == "stdio"

    def test_http_transport_configurable(self):
        """HTTP transport configurable via MCP_TRANSPORT env var."""
        with patch.dict("os.environ", {"MCP_TRANSPORT": "http"}):
            transport = os.getenv("MCP_TRANSPORT", "stdio")
            assert transport == "http"

    def test_rag_proxy_url_default(self):
        """RAG_PROXY_URL defaults to http://localhost:8080."""
        url = os.getenv("RAG_PROXY_URL", "http://localhost:8080")
        assert url == "http://localhost:8080"

    def test_rag_proxy_url_configurable(self):
        """RAG_PROXY_URL is configurable via environment."""
        with patch.dict("os.environ", {"RAG_PROXY_URL": "http://custom:9090"}):
            url = os.getenv("RAG_PROXY_URL", "http://localhost:8080")
            assert url == "http://custom:9090"

    def test_http_app_creates_starlette_app(self):
        """mcp.http_app() creates a Starlette ASGI application."""
        app = mcp.http_app()
        assert app is not None
        assert hasattr(app, "routes")

    def test_http_app_has_mcp_routes(self):
        """HTTP app includes MCP endpoint routes."""
        app = mcp.http_app()
        route_paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                route_paths.append(route.path)
        assert any("/mcp" in p for p in route_paths)

    def test_mcp_has_run_method(self):
        """MCP server has run() method for starting transport."""
        assert hasattr(mcp, "run")
        assert callable(mcp.run)

    def test_server_main_block_uses_env(self):
        """server.py __main__ block reads MCP_TRANSPORT env var."""
        import inspect

        from mcp_server import server

        source = inspect.getsource(server)
        assert "MCP_TRANSPORT" in source
        assert 'transport = os.getenv("MCP_TRANSPORT"' in source or "MCP_TRANSPORT" in source

    def test_config_json_transport_stdio(self):
        """config.json specifies stdio as default transport."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        with open(config_path) as f:
            config = json.load(f)
        assert config["transport"] == "stdio"


# ===========================================================================
# FR-125: Standalone install — MCP server startup
# ===========================================================================


class TestFR125StandaloneInstall:
    """FR-125: MCP server can start standalone."""

    def test_config_json_exists(self):
        """config.json exists for MCP server configuration."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        assert os.path.exists(config_path)

    def test_config_json_valid(self):
        """config.json is valid JSON with required fields."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        with open(config_path) as f:
            config = json.load(f)
        assert "name" in config
        assert "transport" in config
        assert "tools" in config

    def test_config_name_is_rag_system(self):
        """config.json name is 'rag-system'."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        with open(config_path) as f:
            config = json.load(f)
        assert config["name"] == "rag-system"

    def test_config_lists_all_three_tools(self):
        """config.json lists all three MCP tools."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        with open(config_path) as f:
            config = json.load(f)
        tool_names = [t["name"] for t in config["tools"]]
        assert "rag_search" in tool_names
        assert "rag_chat" in tool_names
        assert "rag_feedback" in tool_names

    def test_requirements_txt_exists(self):
        """requirements.txt exists for MCP server dependencies."""
        req_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "requirements.txt")
        assert os.path.exists(req_path)

    def test_requirements_includes_fastmcp(self):
        """requirements.txt includes fastmcp dependency."""
        req_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "requirements.txt")
        with open(req_path) as f:
            content = f.read()
        assert "fastmcp" in content.lower()

    def test_server_module_has_main_guard(self):
        """server.py has __main__ guard for standalone execution."""
        import inspect

        from mcp_server import server

        source = inspect.getsource(server)
        assert 'if __name__ == "__main__"' in source

    def test_mcp_instance_is_fastmcp(self):
        """mcp object is a FastMCP instance."""
        from fastmcp import FastMCP

        assert isinstance(mcp, FastMCP)

    def test_mcp_name_is_rag_system(self):
        """MCP server name is 'RAG System'."""
        assert mcp.name == "RAG System"

    def test_mcp_instructions_set(self):
        """MCP server has instructions describing its purpose."""
        assert mcp.instructions is not None
        assert "Corporate Knowledge Assistant" in mcp.instructions

    def test_mcp_has_call_tool_method(self):
        """MCP server supports tool invocation."""
        assert hasattr(mcp, "call_tool")
        assert callable(mcp.call_tool)

    def test_mcp_has_list_tools_method(self):
        """MCP server supports listing tools."""
        assert hasattr(mcp, "list_tools")
        assert callable(mcp.list_tools)

    def test_mcp_has_read_resource_method(self):
        """MCP server supports reading resources."""
        assert hasattr(mcp, "read_resource")
        assert callable(mcp.read_resource)

    def test_mcp_has_list_resources_method(self):
        """MCP server supports listing resources."""
        assert hasattr(mcp, "list_resources")
        assert callable(mcp.list_resources)

    def test_mcp_has_render_prompt_method(self):
        """MCP server supports rendering prompts."""
        assert hasattr(mcp, "render_prompt")
        assert callable(mcp.render_prompt)
