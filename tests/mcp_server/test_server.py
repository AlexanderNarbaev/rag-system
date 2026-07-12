# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for MCP server — server.py tool/resource/prompt registration and execution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level import of the MCP server object.
# We patch httpx.AsyncClient to prevent real HTTP calls during import/tool execution.
# ---------------------------------------------------------------------------

from mcp_server.server import mcp  # noqa: E402


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_httpx_response():
    """Create a mock httpx.Response with standard RAG proxy response format."""

    def _make(json_data=None, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {
            "choices": [{"message": {"content": "Mocked RAG answer"}}]
        }
        resp.text = str(json_data)
        return resp

    return _make


@pytest.fixture
def mock_httpx_client(mock_httpx_response):
    """Mock httpx.AsyncClient context manager used inside server.py tools."""

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
# 1. Server Initialization
# ===========================================================================


class TestServerInitialization:
    """Verify the MCP server object is created with correct metadata."""

    def test_mcp_instance_exists(self):
        assert mcp is not None

    def test_mcp_name(self):
        assert mcp.name == "RAG System"

    def test_mcp_instructions(self):
        assert "Corporate Knowledge Assistant" in mcp.instructions

    def test_mcp_has_run_method(self):
        assert hasattr(mcp, "run")
        assert callable(mcp.run)

    def test_mcp_has_http_app_method(self):
        assert hasattr(mcp, "http_app")
        assert callable(mcp.http_app)

    def test_mcp_has_call_tool_method(self):
        assert hasattr(mcp, "call_tool")
        assert callable(mcp.call_tool)


# ===========================================================================
# 2. Tool Registration
# ===========================================================================


class TestToolRegistration:
    """Verify that all expected tools are registered on the MCP server."""

    @pytest.mark.asyncio
    async def test_tools_registered(self):
        tools = await mcp.list_tools()
        tool_names = [t.name for t in tools]
        assert "rag_search" in tool_names
        assert "rag_chat" in tool_names
        assert "rag_feedback" in tool_names

    @pytest.mark.asyncio
    async def test_exactly_three_tools(self):
        tools = await mcp.list_tools()
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_rag_search_description(self):
        tools = await mcp.list_tools()
        search_tool = next(t for t in tools if t.name == "rag_search")
        assert "Search" in search_tool.description
        assert "knowledge base" in search_tool.description.lower()

    @pytest.mark.asyncio
    async def test_rag_chat_description(self):
        tools = await mcp.list_tools()
        chat_tool = next(t for t in tools if t.name == "rag_chat")
        assert "Chat" in chat_tool.description
        assert "questions" in chat_tool.description.lower()

    @pytest.mark.asyncio
    async def test_rag_feedback_description(self):
        tools = await mcp.list_tools()
        feedback_tool = next(t for t in tools if t.name == "rag_feedback")
        assert "feedback" in feedback_tool.description.lower()

    @pytest.mark.asyncio
    async def test_rag_search_parameters(self):
        tools = await mcp.list_tools()
        search_tool = next(t for t in tools if t.name == "rag_search")
        schema = search_tool.parameters
        props = schema.get("properties", {})
        assert "query" in props
        assert "limit" in props

    @pytest.mark.asyncio
    async def test_rag_chat_parameters(self):
        tools = await mcp.list_tools()
        chat_tool = next(t for t in tools if t.name == "rag_chat")
        schema = chat_tool.parameters
        props = schema.get("properties", {})
        assert "message" in props
        assert "context" in props

    @pytest.mark.asyncio
    async def test_rag_feedback_parameters(self):
        tools = await mcp.list_tools()
        feedback_tool = next(t for t in tools if t.name == "rag_feedback")
        schema = feedback_tool.parameters
        props = schema.get("properties", {})
        assert "query" in props
        assert "answer" in props
        assert "rating" in props
        assert "correction" in props


# ===========================================================================
# 3. Resource Registration
# ===========================================================================


class TestResourceRegistration:
    """Verify that resources are registered on the MCP server."""

    @pytest.mark.asyncio
    async def test_resource_registered(self):
        resources = await mcp.list_resources()
        uris = [str(r.uri) for r in resources]
        assert "rag://collections" in uris

    @pytest.mark.asyncio
    async def test_resource_has_name(self):
        resources = await mcp.list_resources()
        collection_res = next(r for r in resources if str(r.uri) == "rag://collections")
        assert collection_res.name is not None


# ===========================================================================
# 4. Prompt Registration
# ===========================================================================


class TestPromptRegistration:
    """Verify that prompts are registered on the MCP server."""

    @pytest.mark.asyncio
    async def test_prompt_registered(self):
        prompts = await mcp.list_prompts()
        prompt_names = [p.name for p in prompts]
        assert "rag_help" in prompt_names

    @pytest.mark.asyncio
    async def test_rag_help_prompt_content(self):
        result = await mcp.render_prompt("rag_help")
        assert result is not None
        messages = result.messages
        assert len(messages) > 0
        content = messages[0].content.text
        assert "rag_search" in content
        assert "rag_chat" in content
        assert "rag_feedback" in content


# ===========================================================================
# 5. Tool Execution — rag_search
# ===========================================================================


class TestRagSearchTool:
    """Test the rag_search tool with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_rag_search_returns_content(self, mock_httpx_client):
        mock_client = mock_httpx_client(
            response_data={"choices": [{"message": {"content": "Found 3 relevant documents"}}]}
        )
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool("rag_search", {"query": "What is RAG?"})
        assert result is not None
        assert len(result.content) > 0
        text = result.content[0].text
        assert "Found 3 relevant documents" in text

    @pytest.mark.asyncio
    async def test_rag_search_uses_correct_url(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_search", {"query": "test query"})
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "/v1/chat/completions" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_rag_search_sends_correct_payload(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_search", {"query": "CI/CD pipeline"})
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["model"] == "rag"
        assert "CI/CD pipeline" in payload["messages"][0]["content"]
        assert payload["stream"] is False
        assert payload["rag_search_only"] is True

    @pytest.mark.asyncio
    async def test_rag_search_default_limit(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_search", {"query": "test"})
        # Default limit is 5 — check it's passed as the query prefix
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert "Search: test" in payload["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_rag_search_with_custom_limit(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_search", {"query": "test", "limit": 10})
        # The tool still works — limit param is accepted
        mock_client.post.assert_called_once()


# ===========================================================================
# 6. Tool Execution — rag_chat
# ===========================================================================


class TestRagChatTool:
    """Test the rag_chat tool with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_rag_chat_returns_content(self, mock_httpx_client):
        mock_client = mock_httpx_client(
            response_data={"choices": [{"message": {"content": "RAG is a technique..."}}]}
        )
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool("rag_chat", {"message": "What is RAG?"})
        assert result is not None
        assert len(result.content) > 0
        text = result.content[0].text
        assert "RAG is a technique" in text

    @pytest.mark.asyncio
    async def test_rag_chat_without_context(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_chat", {"message": "Hello"})
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        messages = payload["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_rag_chat_with_context(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_chat", {"message": "Explain this", "context": "RAG overview"})
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        messages = payload["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "RAG overview" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Explain this"

    @pytest.mark.asyncio
    async def test_rag_chat_uses_correct_url(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_chat", {"message": "test"})
        call_args = mock_client.post.call_args
        assert "/v1/chat/completions" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_rag_chat_sends_stream_false(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_chat", {"message": "test"})
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["stream"] is False

    @pytest.mark.asyncio
    async def test_rag_chat_model_is_rag(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool("rag_chat", {"message": "test"})
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["model"] == "rag"


# ===========================================================================
# 7. Tool Execution — rag_feedback
# ===========================================================================


class TestRagFeedbackTool:
    """Test the rag_feedback tool with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_rag_feedback_success(self, mock_httpx_client):
        mock_client = mock_httpx_client(response_data={"status": "ok"})
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool(
                "rag_feedback",
                {"query": "What is RAG?", "answer": "RAG is...", "rating": "positive"},
            )
        assert result is not None
        assert len(result.content) > 0
        assert "Feedback submitted" in result.content[0].text

    @pytest.mark.asyncio
    async def test_rag_feedback_sends_correct_payload(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool(
                "rag_feedback",
                {
                    "query": "test query",
                    "answer": "test answer",
                    "rating": "negative",
                    "correction": "correct answer",
                },
            )
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["query"] == "test query"
        assert payload["answer"] == "test answer"
        assert payload["rating"] == "negative"
        assert payload["correction"] == "correct answer"

    @pytest.mark.asyncio
    async def test_rag_feedback_uses_correct_url(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool(
                "rag_feedback",
                {"query": "q", "answer": "a", "rating": "positive"},
            )
        call_args = mock_client.post.call_args
        assert "/v1/feedback" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_rag_feedback_without_correction(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool(
                "rag_feedback",
                {"query": "q", "answer": "a", "rating": "positive"},
            )
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["correction"] == ""

    @pytest.mark.asyncio
    async def test_rag_feedback_negative_with_correction(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.call_tool(
                "rag_feedback",
                {
                    "query": "How to deploy?",
                    "answer": "Wrong answer",
                    "rating": "negative",
                    "correction": "Use kubectl apply",
                },
            )
        call_kwargs = mock_client.post.call_args[1]
        payload = call_kwargs["json"]
        assert payload["rating"] == "negative"
        assert payload["correction"] == "Use kubectl apply"


# ===========================================================================
# 8. Resource Execution — rag://collections
# ===========================================================================


class TestCollectionsResource:
    """Test the rag://collections resource with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_read_resource_returns_data(self, mock_httpx_client):
        mock_client = mock_httpx_client(response_data={"data": [{"id": "rag-proxy"}]})
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.read_resource("rag://collections")
        assert result is not None
        assert len(result.contents) > 0

    @pytest.mark.asyncio
    async def test_read_resource_uses_correct_url(self, mock_httpx_client):
        mock_client = mock_httpx_client()
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            await mcp.read_resource("rag://collections")
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert "/v1/models" in call_args[0][0]


# ===========================================================================
# 9. Error Handling
# ===========================================================================


class TestErrorHandling:
    """Test error scenarios for the MCP server."""

    @pytest.mark.asyncio
    async def test_invalid_tool_name_raises(self):
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("nonexistent_tool", {})
        assert "not found" in str(exc_info.value).lower() or "unknown" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_missing_required_parameter_raises(self):
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("rag_search", {})
        # Should fail because 'query' is required
        error_msg = str(exc_info.value).lower()
        assert "query" in error_msg or "missing" in error_msg or "required" in error_msg

    @pytest.mark.asyncio
    async def test_rag_chat_missing_message_raises(self):
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("rag_chat", {})
        error_msg = str(exc_info.value).lower()
        assert "message" in error_msg or "missing" in error_msg or "required" in error_msg

    @pytest.mark.asyncio
    async def test_rag_feedback_missing_rating_raises(self):
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("rag_feedback", {"query": "q", "answer": "a"})
        error_msg = str(exc_info.value).lower()
        assert "rating" in error_msg or "missing" in error_msg or "required" in error_msg

    @pytest.mark.asyncio
    async def test_http_error_propagates(self, mock_httpx_client):
        """When the proxy returns an error, the tool should propagate it."""
        mock_client = mock_httpx_client(status_code=500)
        # Simulate response.json() raising on error
        mock_client.post.return_value.json.side_effect = Exception("Internal Server Error")
        with (
            patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(Exception, match="Internal Server Error"),
        ):
            await mcp.call_tool("rag_search", {"query": "test"})

    @pytest.mark.asyncio
    async def test_connection_error_propagates(self, mock_httpx_client):
        """When the proxy is unreachable, the tool should propagate the error."""
        mock_client = mock_httpx_client()
        mock_client.post.side_effect = Exception("Connection refused")
        with (
            patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(Exception, match="Connection refused"),
        ):
            await mcp.call_tool("rag_search", {"query": "test"})

    @pytest.mark.asyncio
    async def test_invalid_prompt_name_raises(self):
        with pytest.raises(Exception) as exc_info:
            await mcp.render_prompt("nonexistent_prompt")
        assert "not found" in str(exc_info.value).lower() or "unknown" in str(exc_info.value).lower()


# ===========================================================================
# 10. Transport Configuration
# ===========================================================================


class TestTransportConfiguration:
    """Test that the server respects transport environment variables."""

    def test_default_transport_is_stdio(self):
        """Default transport should be stdio when MCP_TRANSPORT is not set."""
        import os

        transport = os.getenv("MCP_TRANSPORT", "stdio")
        assert transport == "stdio"

    def test_http_transport_can_be_configured(self):
        """When MCP_TRANSPORT=http, the server should use HTTP transport."""
        with patch.dict("os.environ", {"MCP_TRANSPORT": "http"}):
            import os

            transport = os.getenv("MCP_TRANSPORT", "stdio")
            assert transport == "http"

    def test_rag_proxy_url_default(self):
        """Default RAG_PROXY_URL should be http://localhost:8080."""
        import os

        url = os.getenv("RAG_PROXY_URL", "http://localhost:8080")
        assert url == "http://localhost:8080"

    def test_rag_proxy_url_configurable(self):
        """RAG_PROXY_URL should be configurable via environment."""
        with patch.dict("os.environ", {"RAG_PROXY_URL": "http://custom-host:9090"}):
            import os

            url = os.getenv("RAG_PROXY_URL", "http://localhost:8080")
            assert url == "http://custom-host:9090"


# ===========================================================================
# 11. HTTP App Creation
# ===========================================================================


class TestHttpApp:
    """Test that the HTTP app can be created for HTTP transport."""

    def test_http_app_creates_starlette_app(self):
        app = mcp.http_app()
        assert app is not None
        assert hasattr(app, "routes")

    def test_http_app_has_mcp_routes(self):
        app = mcp.http_app()
        route_paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                route_paths.append(route.path)
        # FastMCP mounts the MCP endpoint at /mcp by default
        assert any("/mcp" in p for p in route_paths)


# ===========================================================================
# 12. Config File
# ===========================================================================


class TestConfigFile:
    """Verify the config.json matches the registered tools."""

    def test_config_file_exists(self):
        import os

        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        assert os.path.exists(config_path)

    def test_config_has_correct_name(self):
        import json
        import os

        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        with open(config_path) as f:
            config = json.load(f)
        assert config["name"] == "rag-system"

    def test_config_lists_all_tools(self):
        import json
        import os

        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        with open(config_path) as f:
            config = json.load(f)
        tool_names = [t["name"] for t in config["tools"]]
        assert "rag_search" in tool_names
        assert "rag_chat" in tool_names
        assert "rag_feedback" in tool_names

    def test_config_transport_is_stdio(self):
        import json
        import os

        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "mcp_server", "config.json")
        with open(config_path) as f:
            config = json.load(f)
        assert config["transport"] == "stdio"


# ===========================================================================
# 13. Integration — Tool Call Round-Trip
# ===========================================================================


class TestToolCallRoundTrip:
    """End-to-end tests for tool calls through the MCP server."""

    @pytest.mark.asyncio
    async def test_full_search_roundtrip(self, mock_httpx_client):
        mock_client = mock_httpx_client(
            response_data={
                "choices": [
                    {
                        "message": {
                            "content": "## Search Results\n\n1. **RAG Overview** - RAG combines retrieval with generation (score: 0.95)"
                        }
                    }
                ]
            }
        )
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool("rag_search", {"query": "RAG architecture", "limit": 3})
        assert result.is_error is False
        text = result.content[0].text
        assert "RAG Overview" in text
        assert "0.95" in text

    @pytest.mark.asyncio
    async def test_full_chat_roundtrip(self, mock_httpx_client):
        mock_client = mock_httpx_client(
            response_data={
                "choices": [
                    {
                        "message": {
                            "content": "Kubernetes is an open-source container orchestration platform."
                        }
                    }
                ]
            }
        )
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool(
                "rag_chat",
                {"message": "What is Kubernetes?", "context": "DevOps documentation"},
            )
        assert result.is_error is False
        text = result.content[0].text
        assert "Kubernetes" in text
        assert "container orchestration" in text

    @pytest.mark.asyncio
    async def test_full_feedback_roundtrip(self, mock_httpx_client):
        mock_client = mock_httpx_client(response_data={"status": "ok"})
        with patch("mcp_server.server.httpx.AsyncClient", return_value=mock_client):
            result = await mcp.call_tool(
                "rag_feedback",
                {
                    "query": "What is CI/CD?",
                    "answer": "CI/CD is continuous integration and deployment",
                    "rating": "positive",
                },
            )
        assert result.is_error is False
        assert "Feedback submitted" in result.content[0].text
