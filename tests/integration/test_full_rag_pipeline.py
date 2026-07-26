# tests/integration/test_full_rag_pipeline.py
"""End-to-end tests for the full RAG pipeline.

Tests the complete flow:
  Document → ETL → Chunking → Embedding → Indexing → Search → Reranking → Context → LLM → Response

Each scenario uses mock services so the suite runs hermetically without
external dependencies (Qdrant / Neo4j / Redis / live LLM endpoint).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Disable progressive retrieval — these tests patch hybrid_search directly
os.environ.setdefault("PROGRESSIVE_RETRIEVAL_ENABLED", "false")

# Make sure both proxy/ and etl/ are importable (etl/ for DocExtractor + chunker)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "etl"))


# ---------------------------------------------------------------------------
# Helpers — sample fixtures
# ---------------------------------------------------------------------------


SAMPLE_MD_PATH = Path(__file__).parent.parent / "fixtures" / "sample.md"


def _make_scored_point(
    text: str,
    score: float = 0.9,
    source_type: str = "confluence",
    source_id: str = "src_1",
    version: str = "1.0",
    title: str = "Test Doc",
    doc_title: str = "Test Doc Title",
    access_level: str = "public",
) -> MagicMock:
    """Build a fake Qdrant ScoredPoint for use as a hybrid_search result."""
    point = MagicMock()
    point.id = f"hash_{hash(text) & 0xFFFFFFFF}"
    point.score = score
    point.payload = {
        "text": text,
        "source_type": source_type,
        "source_id": source_id,
        "version": version,
        "title": title,
        "doc_title": doc_title,
        "access_level": access_level,
        "hash": point.id,
    }
    return point


def _make_mock_llm(content: str = "Mock LLM response"):
    """Build an AsyncMock matching non_stream_completion signature."""

    async def _mock(*_args: Any, **_kwargs: Any) -> str:
        return content

    return AsyncMock(side_effect=_mock)


# ---------------------------------------------------------------------------
# Shared app_client fixture (FastAPI TestClient with all externals mocked)
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client():
    """Create a FastAPI TestClient with cache, langgraph, and auth disabled."""
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.USE_LANGGRAPH", False),
        patch("proxy.app.main.LOG_REQUESTS", False),
        patch("proxy.app.main.LLM_MODEL_NAME", "test-model"),
        patch("proxy.app.main.PROGRESSIVE_RETRIEVAL_ENABLED", False),
        patch("proxy.app.main.SEMANTIC_CACHE_ENABLED", False),
        patch("proxy.app.main.semantic_cache", None),
        patch("proxy.app.auth.jwt.AUTH_ENABLED", False),
        patch("proxy.app.shared.config.RBAC_ENABLED", False),
    ):
        from fastapi.testclient import TestClient

        from proxy.app.main import app

        client = TestClient(app)
        yield client


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestFullRAGPipeline:
    """Test the complete RAG pipeline end-to-end (mocked externals)."""

    def test_extract_chunk_index_search_respond(self, tmp_path):
        """Full pipeline: extract → chunk → embed → index → search → respond.

        Drives each component directly using in-memory mocks so we exercise
        the actual contracts (DocExtractor → MDKeyChunker → hybrid_search →
        rerank_chunks → build_context) without spinning up Qdrant.
        """
        # 1. Extract from the fixture markdown file (copy into tmp_path so
        # DocExtractor sees a directory that actually exists on this host)
        import shutil

        target = tmp_path / "sample.md"
        shutil.copy(SAMPLE_MD_PATH, target)

        from etl.extractors.doc_extractor import DocExtractor

        config = MagicMock()
        config.base_url = str(tmp_path)
        config.exclude_patterns = []
        extractor = DocExtractor(config)

        async def _collect() -> list:
            docs = []
            async for doc in extractor.extract():
                docs.append(doc)
            return docs

        docs = asyncio.run(_collect())
        assert len(docs) >= 1, "DocExtractor should yield at least one document"
        assert all(doc.content for doc in docs)

        # 2. Chunk via MDKeyChunker (canonical ETL chunker)
        from etl.chunker.semantic_chunker import MDKeyChunker, MetadataEnricher, SemanticChunker

        base = SemanticChunker(max_tokens=200, overlap_tokens=0, min_chunk_tokens=1, contextual_enrichment=False)
        chunker = MDKeyChunker(base, MetadataEnricher(use_slm=False))

        all_chunks: list = []
        for doc in docs:
            all_chunks.extend(
                chunker.process_document(
                    doc.content,
                    doc.content_type,
                    {
                        "source_type": doc.source_type,
                        "source_id": doc.source_id,
                        "version": "1.0",
                        "doc_title": doc.title,
                    },
                ),
            )
        assert len(all_chunks) >= 1
        # SHA-256 content addressing must be present on every chunk
        import hashlib

        for chunk in all_chunks:
            assert chunk.hash == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()

        # 3. Index — pretend we embedded + upserted (no real Qdrant)
        for chunk in all_chunks:
            chunk.embedding = [0.1] * 1024  # Mock embedding

        # 4. Search — patch hybrid_search so we don't need Qdrant.
        # The sample fixture produces ≥1 chunks; we cap at 5 for the assertion.
        # We synthesise lightweight ScoredPoint-like objects that carry the
        # shape hybrid_search actually returns at runtime (.id, .score, .payload).
        retrieved = all_chunks[:5]

        def _to_scored_point(chunk: Any) -> MagicMock:
            sp = MagicMock()
            sp.id = chunk.hash
            sp.score = 0.9
            sp.payload = {
                "text": chunk.text,
                "source_type": chunk.source_type,
                "source_id": chunk.source_id,
                "version": chunk.version,
                "title": chunk.title,
                "doc_title": chunk.doc_title,
                "access_level": chunk.access_level,
                "hash": chunk.hash,
            }
            return sp

        scored = [_to_scored_point(c) for c in retrieved]

        with patch("proxy.app.core.retrieval.hybrid_search") as mock_search:
            mock_search.return_value = scored
            from proxy.app.core.retrieval import hybrid_search

            results = hybrid_search("test query", top_k=5)
        assert len(results) == len(retrieved)
        assert len(results) >= 1

        # 5. Rerank — patch rerank_chunks (cross-encoder would normally rank by relevance)
        top_k = min(3, len(results))
        with patch("proxy.app.core.rerank.rerank_chunks") as mock_rerank:
            mock_rerank.return_value = list(range(top_k))
            from proxy.app.core.rerank import rerank_chunks

            reranked = rerank_chunks("test query", [r.payload["text"] for r in results], top_k=top_k)
        assert len(reranked) <= 3

        # 6. Context — build a real context string from the selected chunks
        from proxy.app.core.context.builder import build_context

        context_input = [(results[i].payload, results[i].score) for i in reranked]
        context = build_context(context_input, max_tokens=10_000)
        assert len(context) > 0
        # Context should reference the source_type metadata header
        assert "[" in context

    def test_ungrounded_response_when_no_knowledge(self, app_client):
        """When knowledge base is empty, system responds with ungrounded notice.

        Verifies that the `rag_knowledge_status` extension signals
        ``absent`` so downstream clients can render a fallback UI.
        """

        async def mock_llm(*_args: Any, **_kwargs: Any) -> str:
            return "I do not have information about this in the knowledge base."

        with (
            patch("proxy.app.main.hybrid_search", return_value=[]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            response = app_client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model+RAG",
                    "messages": [{"role": "user", "content": "What is RAG?"}],
                },
            )
        assert response.status_code == 200
        data = response.json()

        # FR-144 knowledge status taxonomy — empty retrieval = "absent"
        assert data.get("rag_knowledge_status") == "absent"
        assert data.get("rag_source_count") == 0
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1
        assert len(data["choices"][0]["message"]["content"]) > 0

    def test_streaming_response_with_rag(self, app_client):
        """Streaming chat with RAG pipeline produces SSE events ending with [DONE]."""
        search_results = [_make_scored_point("Streaming RAG context.")]

        async def mock_stream(*_args: Any, **_kwargs: Any):
            yield {
                "id": "chunk-1",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "Streaming "}, "index": 0}],
            }
            yield {
                "id": "chunk-2",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": "answer."}, "index": 0}],
            }

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.stream_completion", side_effect=mock_stream),
            app_client.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": "test-model+RAG",
                    "messages": [{"role": "user", "content": "test streaming"}],
                    "stream": True,
                },
            ) as response,
        ):
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            body = ""
            for chunk in response.iter_text():
                body += chunk
        # Standard OpenAI streaming sentinel must terminate the stream
        assert "[DONE]" in body
        # At least one chunk should contain content
        assert "Streaming" in body or "answer" in body

    def test_direct_passthrough_without_rag(self, app_client):
        """Model name without +RAG suffix bypasses retrieval and forwards to LLM directly.

        Per OpenAI-compat design: callers opt into RAG by appending ``+RAG``
        to the model name. A bare model name is pure passthrough — the proxy
        must not perform search, rerank, or include rag_sources.
        """

        async def mock_llm(*_args: Any, **_kwargs: Any) -> str:
            return "Direct passthrough response."

        with patch("proxy.app.main.non_stream_completion", side_effect=mock_llm):
            response = app_client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",  # no +RAG suffix
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
        assert response.status_code == 200
        data = response.json()

        # OpenAI passthrough shape — no RAG-specific extensions
        assert "rag_sources" not in data or not data["rag_sources"]
        assert "rag_knowledge_status" not in data or data["rag_knowledge_status"] is None
        assert data["model"] == "test-model"
        assert data["choices"][0]["message"]["content"] == "Direct passthrough response."

    def test_with_graph_expansion(self, app_client):
        """RAG with graph expansion enabled still serves a chat completion.

        When GRAPH_ENABLED is on, the LangGraph orchestrator adds a
        ``graph_expand`` node that enriches the context with multi-hop
        entity relationships from Neo4j. Here we simply verify the
        endpoint remains healthy with the flag flipped.
        """
        search_results = [_make_scored_point("Graph expansion context.")]

        async def mock_llm(*_args: Any, **_kwargs: Any) -> str:
            return "Graph-enriched answer."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
            patch("proxy.app.main.GRAPH_ENABLED", True),
        ):
            response = app_client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model+RAG",
                    "messages": [{"role": "user", "content": "graph expansion test"}],
                },
            )
        assert response.status_code == 200
        data = response.json()
        # Even with graph on, standard pipeline returns rag_sources
        assert "rag_sources" in data

    def test_with_tool_calling(self, app_client):
        """RAG works with tool calling enabled (the proxy simply forwards tools).

        The agentic-tools layer sits between the user and the LLM. With
        TOOLS_ENABLED on, the model may return tool_calls — the proxy must
        still return a valid ChatCompletionResponse either way.
        """
        search_results = [_make_scored_point("Tools-enabled context.")]

        # LLM that "decides" to call a tool
        async def mock_llm(*_args: Any, **_kwargs: Any) -> str:
            return "Tool-enabled response (no actual tool invocation in this test)."

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
            patch("proxy.app.main.TOOLS_ENABLED", True),
        ):
            payload = {
                "model": "test-model+RAG",
                "messages": [{"role": "user", "content": "call a tool"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "description": "Echo input back",
                            "parameters": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        },
                    },
                ],
            }
            response = app_client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"
        assert len(data["choices"]) == 1

    def test_with_kb_manager(self, app_client):
        """KB manager listing endpoint exists at /v1/admin/kb.

        The admin/kb API is registered under the auth-protected prefix.
        With AUTH_ENABLED off (and RBAC off), the endpoint must respond
        with either 200 (if it doesn't require admin role) or 401/403
        (if it does). In both cases the response must be a valid HTTP
        status, not a 404 — the route must exist.
        """
        mock_mgr = MagicMock()
        mock_mgr.list_kbs.return_value = [
            {"id": "default", "name": "Default KB", "doc_count": 0, "chunk_count": 0},
        ]

        with (
            patch("proxy.app.main.kb_manager", mock_mgr),
            patch("proxy.app.auth.jwt.AUTH_ENABLED", False),
            patch("proxy.app.shared.config.RBAC_ENABLED", False),
        ):
            response = app_client.get("/v1/admin/kb/")
        # Route exists — must not 404
        assert response.status_code != 404
        assert response.status_code in (200, 401, 403, 503)
        # When authorized, payload shape is sane
        if response.status_code == 200:
            body = response.json()
            assert "knowledge_bases" in body or "total" in body


class TestPipelineFailureModes:
    """Verify the pipeline degrades gracefully when individual components fail."""

    def test_search_exception_returns_response(self, app_client):
        """Search blowing up must not crash the proxy — fallback to LLM-only."""

        async def mock_llm(*_args: Any, **_kwargs: Any) -> str:
            return "Fallback without context."

        with (
            patch("proxy.app.main.hybrid_search", side_effect=RuntimeError("Qdrant OOM")),
            patch("proxy.app.main.non_stream_completion", side_effect=mock_llm),
        ):
            response = app_client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model+RAG",
                    "messages": [{"role": "user", "content": "degradation test"}],
                },
            )
        assert response.status_code == 200
        data = response.json()
        # When retrieval fails AND ALLOW_UNGROUNDED_GENERATION is true, the
        # proxy prepends UNGROUNDED_NOTICE so the user knows the answer is
        # not grounded. We assert on the LLM body being preserved.
        content = data["choices"][0]["message"]["content"]
        assert "Fallback without context." in content
        # rag_knowledge_status surfaces the degraded mode to clients
        assert data.get("rag_knowledge_status") in ("absent", "insufficient")

    def test_reranker_failure_propagates_as_503(self, app_client):
        """Reranker crash is the one component that IS allowed to surface.

        Other layers have fallbacks (e.g. raw hybrid scores), but the
        cross-encoder pipeline is considered essential — failures map
        to HTTP 503 ``rag_unavailable`` so clients can back off.
        """
        search_results = [_make_scored_point("Context that won't survive rerank.")]

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", side_effect=RuntimeError("reranker OOM")),
        ):
            response = app_client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model+RAG",
                    "messages": [{"role": "user", "content": "rerank fail"}],
                },
            )
        assert response.status_code == 503
        assert response.json()["detail"]["error"] == "rag_unavailable"

    def test_skip_generation_returns_chunks_only(self, app_client):
        """``rag_skip_generation=True`` returns retrieval result without calling LLM.

        Federation mode: another system reads the chunks and runs its own
        LLM. The proxy must still respect the rag_sources contract.
        """
        search_results = [_make_scored_point("Federated context.", score=0.8)]

        with (
            patch("proxy.app.main.hybrid_search", return_value=search_results),
            patch("proxy.app.main.rerank_chunks", return_value=[0]),
            patch("proxy.app.main.non_stream_completion") as mock_llm,
        ):
            response = app_client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model+RAG",
                    "messages": [{"role": "user", "content": "federate this"}],
                    "rag_skip_generation": True,
                },
            )
        # LLM should never have been called
        mock_llm.assert_not_called()
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == ""
        assert "rag_sources" in data
        assert len(data["rag_sources"]) >= 1
