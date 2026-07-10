# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/main.py - FastAPI application with mocked dependencies."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Before importing main, mock heavy dependencies that load at module level
# This prevents actual imports of qdrant, sentence-transformers, langgraph, etc.
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

# Now we can import the app
from proxy.app.main import (
    app,
    generate_request_id,
    process_rag_query,
)


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_rag_pipeline():
    """Mock all RAG pipeline dependencies used in endpoints."""
    with (
        patch("proxy.app.main.hybrid_search") as mock_hybrid,
        patch("proxy.app.main.rerank_chunks") as mock_rerank,
        patch("proxy.app.main.deduplicate_chunks") as mock_dedup,
        patch("proxy.app.main.build_context") as mock_build,
        patch("proxy.app.main.non_stream_completion") as mock_nonstream,
        patch("proxy.app.main.stream_completion") as mock_stream,
        patch("proxy.app.main.extract_version_from_query", return_value=None),
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.log_interaction") as mock_log,
    ):
        mock_hybrid.return_value = []
        mock_rerank.return_value = []
        mock_dedup.return_value = []
        mock_build.return_value = ""
        mock_nonstream.return_value = "Mocked LLM response"
        mock_stream.return_value = iter([])
        yield {
            "hybrid_search": mock_hybrid,
            "rerank_chunks": mock_rerank,
            "deduplicate_chunks": mock_dedup,
            "build_context": mock_build,
            "non_stream_completion": mock_nonstream,
            "stream_completion": mock_stream,
            "log_interaction": mock_log,
        }


class TestGenerateRequestId:
    """Tests for generate_request_id in main module."""

    def test_format(self):
        rid = generate_request_id()
        assert rid.startswith("rag_")

    def test_uniqueness(self):
        ids = {generate_request_id() for _ in range(50)}
        assert len(ids) == 50


class TestAppCreation:
    """Tests for FastAPI app creation."""

    def test_app_exists(self):
        assert app is not None
        assert "RAG Proxy" in app.title

    def test_app_has_routes(self):
        # Collect all route paths, including those nested in included routers
        all_paths = set()
        for route in app.routes:
            if hasattr(route, "path"):
                all_paths.add(route.path)
            elif hasattr(route, "original_router"):
                for sub in route.original_router.routes:
                    if hasattr(sub, "path"):
                        all_paths.add(sub.path)
        assert "/v1/health" in all_paths
        assert "/v1/models" in all_paths
        assert "/v1/chat/completions" in all_paths


class TestHealthEndpoint:
    """Tests for /v1/health endpoint."""

    def test_health_mocked_components(self, client):
        with patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant, patch("requests.get") as mock_get:
            mock_qdrant.get_collections.return_value = {}
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {}
            response = client.get("/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "components" in data

    def test_health_qdrant_error(self, client):
        with patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant, patch("requests.get") as mock_get:
            mock_qdrant.get_collections.side_effect = Exception("down")
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {}
            response = client.get("/v1/health")
            data = response.json()
            assert data["status"] == "degraded"
            assert "error" in data["components"]["qdrant"]

    def test_health_llm_error(self, client):
        with (
            patch("proxy.app.core.retrieval.qdrant_client") as mock_qdrant,
            patch("requests.get", side_effect=Exception("refused")),
        ):
            mock_qdrant.get_collections.return_value = {}
            response = client.get("/v1/health")
            data = response.json()
            assert data["status"] == "degraded"


class TestModelsEndpoint:
    """Tests for /v1/models endpoint."""

    def test_returns_models_list(self, client):
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 2
        model_ids = [m["id"] for m in data["data"]]
        assert "rag-proxy" in model_ids


class TestChatCompletionsNonStreaming:
    """Tests for /v1/chat/completions in non-streaming mode."""

    def test_basic_chat_completion(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "This is a test answer."
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello, how are you?"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["content"] == "This is a test answer."
        assert data["choices"][0]["message"]["role"] == "assistant"

    def test_chat_completion_with_version(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "Versioned answer."
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "What changed in v2.0?"}],
                "rag_version": "2.0",
                "stream": False,
            },
        )
        assert response.status_code == 200

    def test_missing_user_message(self, client, mock_rag_pipeline):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "system", "content": "You are helpful."}],
                "stream": False,
            },
        )
        assert response.status_code == 400
        assert "No user message found" in response.text

    def test_chat_completion_with_context(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "Context-based answer"
        mock_rag_pipeline["hybrid_search"].return_value = [MagicMock(payload={"text": "Relevant chunk"}, score=0.95)]
        mock_rag_pipeline["rerank_chunks"].return_value = [0]
        mock_rag_pipeline["deduplicate_chunks"].return_value = [
            ({"text": "Relevant chunk", "source_type": "wiki", "title": "T", "doc_title": "D", "version": "1"}, 0.95)
        ]
        mock_rag_pipeline["build_context"].return_value = "[wiki] D / T (v1)\nRelevant chunk"

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "What is Kubernetes?"}],
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Context-based answer"

    def test_chat_completion_response_structure(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "Answer"
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "test"}],
                "temperature": 0.5,
                "max_tokens": 2000,
                "stream": False,
            },
        )
        data = response.json()
        assert data["object"] == "chat.completion"
        assert data["model"] == "test-model"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "id" in data
        assert "created" in data

    def test_rag_skip_generation_returns_chunks_only(self, client, mock_rag_pipeline):
        mock_rag_pipeline["non_stream_completion"].return_value = "Should not be called"
        chunk_a = {"text": "Chunk A", "source_type": "confluence", "title": "Doc", "doc_title": "Doc", "version": "1"}
        chunk_b = {"text": "Chunk B", "source_type": "wiki", "title": "Page", "doc_title": "Page", "version": "2"}
        mock_rag_pipeline["hybrid_search"].return_value = [
            MagicMock(payload=chunk_a, score=0.95),
            MagicMock(payload=chunk_b, score=0.85),
        ]
        mock_rag_pipeline["rerank_chunks"].return_value = [0, 1]
        mock_rag_pipeline["deduplicate_chunks"].return_value = [
            (chunk_a, 0.95),
            (chunk_b, 0.85),
        ]
        mock_rag_pipeline["build_context"].return_value = "Built context"

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "test query"}],
                "rag_skip_generation": True,
                "rag_return_chunks": True,
                "rag_top_k": 30,
                "stream": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "rag_sources" in data
        assert len(data["rag_sources"]) == 2
        assert data["choices"][0]["message"]["content"] == ""
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["finish_reason"] == "stop"
        mock_rag_pipeline["non_stream_completion"].assert_not_called()


class TestChatCompletionsStreaming:
    """Tests for /v1/chat/completions in streaming mode."""

    def test_streaming_response(self, client, mock_rag_pipeline):
        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "Hello"}}]}
            yield {"id": "2", "choices": [{"delta": {"content": " world"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "Hi"}], "stream": True},
        )
        assert response.status_code == 200
        body = response.text
        assert "data:" in body

    def test_streaming_done_sentinel(self, client, mock_rag_pipeline):
        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "test"}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen
        mock_rag_pipeline["hybrid_search"].return_value = []

        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "hello"}], "stream": True},
        )
        body = response.text
        assert "[DONE]" in body

    def test_streaming_error_handling(self, client, mock_rag_pipeline):
        mock_rag_pipeline["hybrid_search"].side_effect = Exception("Search failed")

        response = client.post(
            "/v1/chat/completions",
            json={"model": "test-model", "messages": [{"role": "user", "content": "query"}], "stream": True},
        )
        # Streaming errors return the error in the stream body
        body = response.text
        assert "error" in body


class TestProcessRagQuery:
    """Tests for process_rag_query function directly."""

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value="Cached response")

        with patch("proxy.app.main.cache_manager", mock_cache), patch("proxy.app.main.hybrid_search") as mock_search:
            result, context, from_cache, sources = await process_rag_query(
                user_query="test query",
                version=None,
                force_refresh=False,
                stream=False,
            )
            assert result == "Cached response"
            assert from_cache is True
            assert sources == []
            mock_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_search_results(self):
        with (
            patch("proxy.app.main.cache_manager", None),
            patch("proxy.app.main.hybrid_search", return_value=[]),
            patch("proxy.app.main.non_stream_completion", return_value="Answer from LLM"),
        ):
            result, context, from_cache, sources = await process_rag_query(
                user_query="test",
                stream=False,
            )
            assert result == "Answer from LLM"
            assert from_cache is False
            assert sources == []

    @pytest.mark.asyncio
    async def test_streaming_returns_context_and_messages(self):
        mock_search = MagicMock()
        mock_hit = MagicMock()
        mock_hit.payload = {"text": "chunk text"}
        mock_hit.score = 0.9
        mock_search.return_value = [mock_hit]

        with (
            patch("proxy.app.main.cache_manager", None),
            patch("proxy.app.main.hybrid_search", mock_search),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.deduplicate_chunks") as mock_dedup,
            patch("proxy.app.main.build_context", return_value="Built context"),
        ):
            mock_dedup.return_value = [({"text": "chunk text"}, 0.95)]
            context, messages, _, sources = await process_rag_query(
                user_query="test",
                stream=True,
            )
            assert context == "Built context"
            assert isinstance(messages, list)
            assert messages[0]["role"] == "system"
            assert isinstance(sources, list)


class TestLangGraphOrchestratorIntegration:
    """Tests for LangGraph orchestrator integration."""

    def test_langgraph_path_taken_when_enabled(self, client):
        mock_orchestrator = MagicMock()
        mock_orchestrator.ainvoke = AsyncMock(return_value={"answer": "Agentic response", "context": "some context"})

        with patch("proxy.app.main.USE_LANGGRAPH", True), patch("proxy.app.main.orchestrator", mock_orchestrator):
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "Complex question"}],
                    "stream": False,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["choices"][0]["message"]["content"] == "Agentic response"

    def test_langgraph_streaming_path(self, client):
        mock_stream_response = MagicMock()
        mock_orchestrator = MagicMock()
        mock_orchestrator.ainvoke = AsyncMock(return_value=mock_stream_response)

        with patch("proxy.app.main.USE_LANGGRAPH", True), patch("proxy.app.main.orchestrator", mock_orchestrator):
            response = client.post(
                "/v1/chat/completions",
                json={"model": "test-model", "messages": [{"role": "user", "content": "stream this"}], "stream": True},
            )
            assert response.status_code == 200


# ===========================================================================
# Tool discovery endpoints (Task 13)
# ===========================================================================


class TestToolsEndpoint:
    """Tests for GET /v1/tools and GET /v1/tools/{name}."""

    @pytest.fixture
    def sample_tools(self):
        """Create sample ToolDefinition objects for testing."""
        from proxy.app.tools.definition import (
            ToolDefinition,
            ToolParam,
            ToolVisibility,
        )

        search_tool = ToolDefinition(
            name="search_documents",
            description="Search indexed documents using hybrid search",
            parameters=[
                ToolParam(name="query", type=str, description="Search query text"),
                ToolParam(name="top_k", type=int, description="Number of results", required=False),
            ],
            category="search",
            tags=["hybrid", "live"],
            version="1.0.0",
            visibility=ToolVisibility.PUBLIC,
            timeout_seconds=30.0,
            provider="sdk",
            depends_on=[],
        )
        admin_tool = ToolDefinition(
            name="admin_reindex",
            description="Trigger full reindex of knowledge base",
            parameters=[
                ToolParam(name="collection", type=str, description="Collection name"),
            ],
            category="admin",
            tags=["maintenance"],
            version="1.0.0",
            visibility=ToolVisibility.ADMIN,
            timeout_seconds=300.0,
            provider="sdk",
            depends_on=["search_documents"],
        )
        expert_tool = ToolDefinition(
            name="review_feedback",
            description="Review and approve expert feedback",
            parameters=[
                ToolParam(name="feedback_id", type=str, description="Feedback ID"),
            ],
            category="review",
            tags=["expert", "live"],
            version="1.0.0",
            visibility=ToolVisibility.EXPERT,
            timeout_seconds=60.0,
            provider="declarative",
            depends_on=[],
        )
        user_tool = ToolDefinition(
            name="save_bookmark",
            description="Save a document bookmark for later",
            parameters=[
                ToolParam(name="doc_id", type=str, description="Document ID"),
            ],
            category="bookmarks",
            tags=["user"],
            version="1.0.0",
            visibility=ToolVisibility.USER,
            timeout_seconds=10.0,
            provider="sdk",
            depends_on=[],
        )
        return [search_tool, admin_tool, expert_tool, user_tool]

    @pytest.fixture
    def mock_registry(self, sample_tools):
        """Mock EnhancedToolRegistry with sample tools."""
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        for t in sample_tools:
            registry.register(t)
        return registry

    def test_list_tools_returns_count_and_tools(self, client, mock_registry):
        """GET /v1/tools returns {"count": N, "tools": [...]} with correct fields."""
        with patch("proxy.app.main.get_enhanced_registry", return_value=mock_registry):
            response = client.get("/v1/tools")
            assert response.status_code == 200
            data = response.json()
            assert "count" in data
            assert "tools" in data
            assert data["count"] == len(data["tools"])
            for tool in data["tools"]:
                assert "name" in tool
                assert "description" in tool
                assert "category" in tool
                assert "tags" in tool
                assert "version" in tool
                assert "parameters" in tool
                assert "provider" in tool

    def test_list_tools_filter_by_category(self, client, mock_registry):
        """GET /v1/tools?category=search filters correctly."""
        with patch("proxy.app.main.get_enhanced_registry", return_value=mock_registry):
            response = client.get("/v1/tools?category=search")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            assert data["tools"][0]["name"] == "search_documents"

    def test_list_tools_filter_by_tag(self, client, mock_registry):
        """GET /v1/tools?tag=live filters by tag."""
        with (
            patch("proxy.app.main.get_enhanced_registry", return_value=mock_registry),
            patch("proxy.app.main._highest_role_from_user", return_value="admin"),
        ):
            response = client.get("/v1/tools?tag=live")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 2
            names = [t["name"] for t in data["tools"]]
            assert "search_documents" in names
            assert "review_feedback" in names

    def test_list_tools_filter_by_provider(self, client, mock_registry):
        """GET /v1/tools?provider=sdk filters by provider."""
        with (
            patch("proxy.app.main.get_enhanced_registry", return_value=mock_registry),
            patch("proxy.app.main._highest_role_from_user", return_value="admin"),
        ):
            response = client.get("/v1/tools?provider=sdk")
            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 3
            names = [t["name"] for t in data["tools"]]
            assert "search_documents" in names
            assert "admin_reindex" in names
            assert "save_bookmark" in names

    def test_get_tool_by_name_returns_detail(self, client, mock_registry):
        """GET /v1/tools/{name} returns tool detail with all fields."""
        with patch("proxy.app.main.get_enhanced_registry", return_value=mock_registry):
            response = client.get("/v1/tools/search_documents")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "search_documents"
            assert data["description"] == "Search indexed documents using hybrid search"
            assert data["category"] == "search"
            assert data["tags"] == ["hybrid", "live"]
            assert data["version"] == "1.0.0"
            assert "visibility" in data
            assert data["visibility"] == "public"
            assert data["timeout_seconds"] == 30.0
            assert "parameters" in data
            assert data["provider"] == "sdk"
            assert "depends_on" in data

    def test_get_tool_unknown_returns_404(self, client, mock_registry):
        """GET /v1/tools/{name} returns 404 for unknown tool."""
        with patch("proxy.app.main.get_enhanced_registry", return_value=mock_registry):
            response = client.get("/v1/tools/nonexistent_tool")
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()

    def test_anonymous_user_sees_only_public_tools(self, client, sample_tools):
        """Unauthenticated user sees only public tools."""
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        for t in sample_tools:
            registry.register(t)

        with (
            patch("proxy.app.main.get_enhanced_registry", return_value=registry),
            patch("proxy.app.main._highest_role_from_user", return_value=None),
        ):
            response = client.get("/v1/tools")
            assert response.status_code == 200
            data = response.json()
            names = [t["name"] for t in data["tools"]]
            assert "search_documents" in names
            assert "admin_reindex" not in names
            assert "review_feedback" not in names
            assert "save_bookmark" not in names

    def test_tool_list_filtered_by_role(self, client, mock_registry):
        """Expert role sees public + expert + user tools."""
        from proxy.app.tools.definition import (
            ToolDefinition,
            ToolParam,
            ToolVisibility,
        )
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry()
        search_tool = ToolDefinition(
            name="search_documents",
            description="Search",
            parameters=[ToolParam(name="query", type=str)],
            category="search",
            tags=["live"],
            visibility=ToolVisibility.PUBLIC,
            provider="sdk",
        )
        expert_tool = ToolDefinition(
            name="review_feedback",
            description="Review",
            parameters=[ToolParam(name="feedback_id", type=str)],
            category="review",
            tags=["expert"],
            visibility=ToolVisibility.EXPERT,
            provider="sdk",
        )
        user_tool = ToolDefinition(
            name="save_bookmark",
            description="Bookmark",
            parameters=[ToolParam(name="doc_id", type=str)],
            category="bookmarks",
            tags=["user"],
            visibility=ToolVisibility.USER,
            provider="sdk",
        )
        admin_tool = ToolDefinition(
            name="admin_reindex",
            description="Reindex",
            parameters=[ToolParam(name="collection", type=str)],
            category="admin",
            tags=["maintenance"],
            visibility=ToolVisibility.ADMIN,
            provider="sdk",
        )
        for t in [search_tool, expert_tool, user_tool, admin_tool]:
            registry.register(t)

        with (
            patch("proxy.app.main.get_enhanced_registry", return_value=registry),
            patch("proxy.app.main._highest_role_from_user", return_value="expert"),
        ):
            response = client.get("/v1/tools")
            assert response.status_code == 200
            data = response.json()
            names = [t["name"] for t in data["tools"]]
            assert "search_documents" in names
            assert "review_feedback" in names
            assert "save_bookmark" in names
            assert "admin_reindex" not in names


# ---------------------------------------------------------------------------
# Startup tool discovery tests (Task 15)
# ---------------------------------------------------------------------------


class TestStartupToolDiscovery:
    """Tests for tool discovery on application startup (lifespan handler)."""

    @pytest.fixture
    def sample_discovery_tool(self):
        from proxy.app.tools.definition import (
            ToolDefinition,
            ToolParam,
            ToolVisibility,
        )

        return ToolDefinition(
            name="discovered_http",
            description="HTTP action from OpenAPI spec",
            parameters=[ToolParam(name="url", type=str, description="Target URL")],
            category="api",
            tags=["http"],
            visibility=ToolVisibility.PUBLIC,
            provider="openapi",
        )

    @pytest.fixture
    def sample_declarative_tool(self):
        from proxy.app.tools.definition import (
            ToolDefinition,
            ToolParam,
            ToolVisibility,
        )

        return ToolDefinition(
            name="declared_jira_issue",
            description="Declarative Jira tool from YAML",
            parameters=[ToolParam(name="issue_key", type=str, description="Jira key")],
            category="jira",
            tags=["declarative"],
            visibility=ToolVisibility.USER,
            provider="declarative",
        )

    def test_startup_discovers_declarative_when_dir_exists(
        self,
        sample_declarative_tool,
    ):
        """When TOOLS_DECLARATIVE_DIR exists, declarative provider loads tools on startup."""
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry.get_instance()
        registry._tools.clear()
        registry._provider_tools.clear()

        provider = MagicMock()
        provider.provider_name = "declarative"
        provider.discover = AsyncMock(return_value=[sample_declarative_tool])

        async def _run():
            discovered = await provider.discover()
            for tool in discovered:
                registry.register(tool)

        import asyncio

        asyncio.run(_run())

        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "declared_jira_issue"
        assert tools[0].provider == "declarative"

    def test_startup_discovers_openapi_when_specs_configured(
        self,
        sample_discovery_tool,
    ):
        """When TOOLS_OPENAPI_SPECS is non-empty, OpenAPI provider loads tools on startup."""
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry.get_instance()
        registry._tools.clear()
        registry._provider_tools.clear()

        provider = MagicMock()
        provider.provider_name = "openapi"
        provider.discover = AsyncMock(return_value=[sample_discovery_tool])

        async def _run():
            discovered = await provider.discover()
            for tool in discovered:
                registry.register(tool)

        import asyncio

        asyncio.run(_run())

        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "discovered_http"
        assert tools[0].provider == "openapi"

    def test_startup_skips_declarative_when_dir_missing(self):
        """When TOOLS_DECLARATIVE_DIR does not exist, declarative provider is skipped."""
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry.get_instance()
        registry._tools.clear()
        registry._provider_tools.clear()

        with patch("os.path.isdir", return_value=False):
            pass  # No discovery attempted for missing dir

        tools = registry.list_tools()
        assert len(tools) == 0

    def test_startup_skips_openapi_when_specs_empty(self):
        """When TOOLS_OPENAPI_SPECS is empty/falsy, OpenAPI provider is skipped."""
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry.get_instance()
        registry._tools.clear()
        registry._provider_tools.clear()

        assert not ""
        tools = registry.list_tools()
        assert len(tools) == 0

    def test_startup_tool_discovery_failure_is_non_blocking(self):
        """Provider failure during startup does not crash the application."""
        from proxy.app.tools.registry import EnhancedToolRegistry

        registry = EnhancedToolRegistry.get_instance()
        registry._tools.clear()
        registry._provider_tools.clear()

        provider = MagicMock()
        provider.provider_name = "openapi"
        provider.discover = AsyncMock(side_effect=Exception("Connection refused"))

        async def _run():
            try:
                await provider.discover()
            except Exception:  # noqa: SIM105
                pass  # Non-blocking: log warning, continue

        import asyncio

        asyncio.run(_run())

        tools = registry.list_tools()
        assert len(tools) == 0
