"""Tests for mcp_server/server.py — MCP server tools, resources, and prompts."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

# Pre-mock external deps so the module can be imported without them installed
for _mod in (
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "sentence_transformers",
    "neo4j",
    "mcp",
    "mcp.server",
    "mcp.server.fastmcp",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


class _PreservingFastMCP:
    """Mock FastMCP whose decorators return the original function unchanged."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def tool(self, *args: object, **kwargs: object):
        def decorator(fn):
            return fn
        return decorator

    def resource(self, *args: object, **kwargs: object):
        def decorator(fn):
            return fn
        return decorator

    def prompt(self, *args: object, **kwargs: object):
        def decorator(fn):
            return fn
        return decorator

    def run(self, *args: object, **kwargs: object) -> None:
        pass


# Replace FastMCP with a preserving mock so that @mcp.tool(),
# @mcp.resource(), @mcp.prompt() pass the original functions through.
sys.modules["mcp.server.fastmcp"].FastMCP = _PreservingFastMCP

from mcp_server.server import (  # noqa: E402
    _hit_to_dict,
    _estimate_tokens,
    rag_search,
    rag_get_context,
    rag_list_sources,
    rag_get_document,
    rag_get_entities,
    rag_search_graph,
    rag_search_prompt,
    rag_code_review_prompt,
    resource_list_sources,
    resource_get_document,
    resource_get_entity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_scored_point(id_, score, payload=None):
    """Create a mock Qdrant ScoredPoint."""
    mock = MagicMock()
    mock.id = id_
    mock.score = score
    mock.payload = payload or {}
    return mock


def _make_mock_graph_record(entity_name, etype, rel_names, *, graph_search=False):
    """Create a mock Neo4j record.

    graph_search=True: returns strings in ``related`` (for rag_search_graph).
    graph_search=False: returns dicts (for rag_get_entities).
    """
    related = (
        rel_names
        if graph_search
        else [{"name": r, "type": "", "relation": "RELATED_TO"} for r in rel_names]
    )
    record = MagicMock()
    record.__getitem__ = lambda self, key, _r=record: {
        "name": entity_name,
        "type": etype,
        "entity": entity_name,  # rag_search_graph uses RETURN ... AS entity
        "etype": etype,  # rag_search_graph uses RETURN ... AS etype
        "labels": ["Entity"],
        "related": related,
    }[key]
    return record


# ---------------------------------------------------------------------------
# Unit tests: utilities
# ---------------------------------------------------------------------------


class TestHitToDict:
    def test_full_payload(self):
        hit = _make_mock_scored_point("abc-123", 0.95, {
            "text": "Some text content",
            "source_type": "confluence",
            "source_id": "doc-42",
            "title": "Chapter 1",
            "doc_title": "Architecture Guide",
            "version": "2.0",
            "url": "https://wiki.example.com/page",
        })
        result = _hit_to_dict(hit)
        assert result["id"] == "abc-123"
        assert result["score"] == 0.95
        assert result["text"] == "Some text content"
        assert result["source_type"] == "confluence"
        assert result["source_id"] == "doc-42"
        assert result["title"] == "Chapter 1"
        assert result["doc_title"] == "Architecture Guide"
        assert result["version"] == "2.0"

    def test_empty_payload(self):
        hit = _make_mock_scored_point(42, 0.8, None)
        result = _hit_to_dict(hit)
        assert result["id"] == 42
        assert result["text"] == ""
        assert result["source_type"] == "unknown"

    def test_missing_score_uses_default(self):
        hit = MagicMock()
        hit.id = "x"
        hit.score = None
        hit.payload = {}
        result = _hit_to_dict(hit, score=0.75)
        assert result["score"] == 0.75


class TestEstimateTokens:
    def test_typical_text(self):
        assert _estimate_tokens("Hello world") == 2  # 11 chars // 4 = 2

    def test_empty_text(self):
        assert _estimate_tokens("") == 1  # max(1, 0)

    def test_short_text(self):
        assert _estimate_tokens("hi") == 1


# ---------------------------------------------------------------------------
# Tool tests: rag_search
# ---------------------------------------------------------------------------


class TestRagSearch:
    def test_qdrant_unavailable(self):
        with patch("mcp_server.server._get_qdrant_client", return_value=None):
            result = json.loads(rag_search("test"))
            assert result["error"] == "Qdrant is unavailable"
            assert result["results"] == []

    def test_returns_results(self):
        mock_client = MagicMock()
        mock_client.search.return_value = [
            _make_mock_scored_point("a", 0.9, {"text": "Result A", "source_type": "wiki"}),
            _make_mock_scored_point("b", 0.7, {"text": "Result B", "source_type": "jira"}),
        ]
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder):
            result = json.loads(rag_search("test query", top_k=5))
            assert result["count"] == 2
            assert len(result["results"]) == 2
            assert result["results"][0]["text"] == "Result A"

    def test_clamps_top_k(self):
        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder):
            rag_search("q", top_k=0)
            mock_client.search.assert_called_once()
            limit = mock_client.search.call_args[1]["limit"]
            assert limit == 1  # clamped up

    def test_search_exception_handled(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("connection refused")
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder):
            result = json.loads(rag_search("test"))
            assert "error" in result
            assert "connection refused" in result["error"]

    def test_embedder_unavailable_fallback(self):
        mock_client = MagicMock()
        mock_client.scroll.return_value = (
            [
                _make_mock_scored_point("c", 0.0, {"text": "Fallback", "source_type": "gitlab"}),
            ],
            None,
        )

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=None):
            result = json.loads(rag_search("test"))
            assert result["count"] == 1
            assert result["results"][0]["text"] == "Fallback"


# ---------------------------------------------------------------------------
# Tool tests: rag_get_context
# ---------------------------------------------------------------------------


class TestRagGetContext:
    def test_qdrant_unavailable(self):
        with patch("mcp_server.server._get_qdrant_client", return_value=None):
            result = rag_get_context("test")
            assert "Qdrant unavailable" in result

    def test_embedder_unavailable(self):
        mock_client = MagicMock()
        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=None):
            result = rag_get_context("test")
            assert "Embedder unavailable" in result

    def test_no_results(self):
        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder):
            result = rag_get_context("test")
            assert "No relevant documents" in result

    def test_assembles_context(self):
        mock_client = MagicMock()
        mock_client.search.return_value = [
            _make_mock_scored_point("a", 0.95, {
                "text": "Architecture overview content.",
                "source_type": "confluence",
                "doc_title": "Arch Doc",
                "title": "Overview",
                "version": "1.0",
            }),
            _make_mock_scored_point("b", 0.80, {
                "text": "Deployment guide content.",
                "source_type": "confluence",
                "doc_title": "Deploy Doc",
                "title": "Deployment",
                "version": "2.1",
            }),
        ]
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder):
            result = rag_get_context("architecture", max_tokens=1000)
            assert "[confluence]" in result
            assert "Architecture overview content" in result
            assert "Deployment guide content" in result

    def test_deduplicates_by_hash(self):
        mock_client = MagicMock()
        mock_client.search.return_value = [
            _make_mock_scored_point("a", 0.9, {
                "text": "Same content",
                "source_type": "wiki",
                "doc_title": "D",
                "title": "T",
                "version": "1",
            }),
            _make_mock_scored_point("b", 0.8, {
                "text": "Same content",
                "source_type": "wiki",
                "doc_title": "D",
                "title": "T",
                "version": "1",
            }),
        ]
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder):
            result = rag_get_context("test")
            # Should appear only once
            assert result.count("Same content") == 1

    def test_token_limit_truncation(self):
        mock_client = MagicMock()
        # Create a very long chunk
        long_text = "x" * 5000
        mock_client.search.return_value = [
            _make_mock_scored_point("a", 0.9, {
                "text": long_text,
                "source_type": "wiki",
                "doc_title": "D",
                "title": "T",
                "version": "1",
            }),
        ]
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder):
            result = rag_get_context("test", max_tokens=300)
            # Should be truncated (not the full 5000 chars)
            assert len(result) < 3000
            assert "..." in result


# ---------------------------------------------------------------------------
# Tool tests: rag_list_sources
# ---------------------------------------------------------------------------


class TestRagListSources:
    def test_qdrant_unavailable(self):
        with patch("mcp_server.server._get_qdrant_client", return_value=None):
            result = json.loads(rag_list_sources())
            assert result["error"] == "Qdrant is unavailable"

    def test_lists_sources(self):
        mock_client = MagicMock()
        mock_client.scroll.side_effect = [
            (
                [
                    _make_mock_scored_point("a", 0, {"source_type": "confluence", "source_id": "doc1"}),
                    _make_mock_scored_point("b", 0, {"source_type": "confluence", "source_id": "doc2"}),
                    _make_mock_scored_point("c", 0, {"source_type": "jira", "source_id": "issue-1"}),
                ],
                None,
            ),
        ]

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client):
            result = json.loads(rag_list_sources())
            sources = {s["source_type"]: s["document_count"] for s in result["sources"]}
            assert sources["confluence"] == 2
            assert sources["jira"] == 1

    def test_exception_handled(self):
        mock_client = MagicMock()
        mock_client.scroll.side_effect = RuntimeError("timeout")

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client):
            result = json.loads(rag_list_sources())
            assert "error" in result


# ---------------------------------------------------------------------------
# Tool tests: rag_get_document
# ---------------------------------------------------------------------------


class TestRagGetDocument:
    def test_qdrant_unavailable(self):
        with patch("mcp_server.server._get_qdrant_client", return_value=None):
            result = json.loads(rag_get_document("abc"))
            assert result["error"] == "Qdrant is unavailable"

    def test_not_found(self):
        mock_client = MagicMock()
        mock_client.retrieve.return_value = []

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client):
            result = json.loads(rag_get_document("missing-id"))
            assert "not found" in result["error"]

    def test_returns_document(self):
        mock_client = MagicMock()
        mock_client.retrieve.return_value = [
            _make_mock_scored_point("doc-1", 1.0, {
                "text": "Full document text",
                "source_type": "confluence",
                "source_id": "page-42",
                "title": "Guide",
                "doc_title": "User Guide",
                "version": "3.0",
            }),
        ]

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client):
            result = json.loads(rag_get_document("doc-1"))
            assert result["document"]["text"] == "Full document text"
            assert result["document"]["source_type"] == "confluence"

    def test_exception_handled(self):
        mock_client = MagicMock()
        mock_client.retrieve.side_effect = ValueError("bad id format")

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client):
            result = json.loads(rag_get_document("bad"))
            assert "error" in result


# ---------------------------------------------------------------------------
# Tool tests: rag_get_entities
# ---------------------------------------------------------------------------


class TestRagGetEntities:
    def test_neo4j_unavailable(self):
        with patch("mcp_server.server._get_neo4j_driver", return_value=None):
            result = json.loads(rag_get_entities("ServiceX"))
            assert "Neo4j is unavailable" in result["error"]

    def test_returns_entities(self):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.run.return_value = [
            _make_mock_graph_record("ServiceX", "Microservice", ["ServiceY", "DatabaseZ"]),
        ]

        with patch("mcp_server.server._get_neo4j_driver", return_value=mock_driver):
            result = json.loads(rag_get_entities("ServiceX"))
            assert result["count"] == 1
            assert result["entities"][0]["name"] == "ServiceX"
            assert result["entities"][0]["type"] == "Microservice"

    def test_exception_handled(self):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.run.side_effect = RuntimeError("neo4j down")

        with patch("mcp_server.server._get_neo4j_driver", return_value=mock_driver):
            result = json.loads(rag_get_entities("ServiceX"))
            assert "error" in result


# ---------------------------------------------------------------------------
# Tool tests: rag_search_graph
# ---------------------------------------------------------------------------


class TestRagSearchGraph:
    def test_qdrant_unavailable(self):
        with patch("mcp_server.server._get_qdrant_client", return_value=None):
            result = json.loads(rag_search_graph("test"))
            assert result["error"] == "Qdrant is unavailable"

    def test_embedder_unavailable(self):
        mock_client = MagicMock()
        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=None):
            result = json.loads(rag_search_graph("test"))
            assert "Embedder unavailable" in result["error"]

    def test_vector_search_results(self):
        mock_client = MagicMock()
        mock_client.search.return_value = [
            _make_mock_scored_point("a", 0.9, {
                "text": "Content A", "title": "Service Registry", "source_type": "wiki",
            }),
        ]
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder), \
             patch("mcp_server.server._get_neo4j_driver", return_value=None):
            result = json.loads(rag_search_graph("test"))
            assert result["count"] == 1
            assert result["graph_context"] == ""

    def test_with_graph_context(self):
        mock_client = MagicMock()
        mock_client.search.return_value = [
            _make_mock_scored_point("a", 0.9, {
                "text": "Content A", "title": "Service Registry", "source_type": "wiki",
            }),
        ]
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.run.return_value = [
            _make_mock_graph_record("ServiceRegistry", "Microservice", ["AuthService"], graph_search=True),
        ]

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder), \
             patch("mcp_server.server._get_neo4j_driver", return_value=mock_driver):
            result = json.loads(rag_search_graph("Service Registry"))
            assert "Knowledge graph relationships" in result["graph_context"]

    def test_exception_handled(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = RuntimeError("qdrant timeout")
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value.tolist.return_value = [0.1] * 1024

        with patch("mcp_server.server._get_qdrant_client", return_value=mock_client), \
             patch("mcp_server.server._get_embedder", return_value=mock_embedder):
            result = json.loads(rag_search_graph("test"))
            assert "error" in result


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------


class TestPrompts:
    def test_rag_search_prompt_contains_query(self):
        prompt = rag_search_prompt("How do I deploy?")
        assert "How do I deploy?" in prompt
        assert "{context}" in prompt
        assert "corporate knowledge assistant" in prompt.lower()

    def test_rag_code_review_prompt_contains_code(self):
        prompt = rag_code_review_prompt(
            code="def foo(): pass",
            context="Use snake_case.",
        )
        assert "def foo(): pass" in prompt
        assert "Use snake_case." in prompt
        assert "Correctness" in prompt
        assert "Security" in prompt


# ---------------------------------------------------------------------------
# Tool existence / registration tests
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify that all 6 required tools are callable."""

    def test_rag_search_exists(self):
        assert callable(rag_search)

    def test_rag_get_context_exists(self):
        assert callable(rag_get_context)

    def test_rag_list_sources_exists(self):
        assert callable(rag_list_sources)

    def test_rag_get_document_exists(self):
        assert callable(rag_get_document)

    def test_rag_get_entities_exists(self):
        assert callable(rag_get_entities)

    def test_rag_search_graph_exists(self):
        assert callable(rag_search_graph)


class TestResourceRegistration:
    """Verify that all 3 resources are callable."""

    def test_resource_list_sources_exists(self):
        assert callable(resource_list_sources)

    def test_resource_get_document_exists(self):
        assert callable(resource_get_document)

    def test_resource_get_entity_exists(self):
        assert callable(resource_get_entity)

    def test_resources_delegate_to_tools(self):
        """Resources should return same results as their corresponding tools."""
        with patch("mcp_server.server._get_qdrant_client", return_value=None):
            result = resource_list_sources()
            assert "Qdrant is unavailable" in result


class TestPromptRegistration:
    """Verify that all 2 prompts are callable and return strings."""

    def test_rag_search_prompt_exists(self):
        assert callable(rag_search_prompt)
        assert isinstance(rag_search_prompt("test"), str)

    def test_rag_code_review_prompt_exists(self):
        assert callable(rag_code_review_prompt)
        assert isinstance(
            rag_code_review_prompt("code", "context"), str
        )
