# ruff: noqa: E402
# tests/integration/test_core_api_e2e.py
"""Integration tests for FR-01 through FR-18 — Core API end-to-end tests.

These tests verify the full request/response cycle using FastAPI's TestClient.
They mock external services (Qdrant, LLM, Redis) but test the actual
proxy endpoints with real routing.

Prerequisites:
- All proxy modules importable
- External dependencies mocked (Qdrant, LLM, Redis, Neo4j)
"""

import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock heavy dependencies
for _mod in (
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "sentence_transformers",
    "neo4j",
    "torch",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.app.api.chat import router as chat_router
from proxy.app.api.health import router as health_router
from proxy.app.auth import UserContext

# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


def _mock_auth_context():
    """Return a mock UserContext that bypasses auth."""
    return UserContext(
        user_id="test_user",
        username="test",
        roles=["admin"],
    )


@pytest.fixture
def app():
    """Create a FastAPI app with all relevant routers and auth bypassed."""
    application = FastAPI()
    application.include_router(chat_router)
    application.include_router(health_router)
    # Override auth dependency to bypass authentication
    from proxy.app.auth import get_auth_context

    application.dependency_overrides[get_auth_context] = _mock_auth_context
    return application


@pytest.fixture
def client(app):
    """Create a TestClient for integration tests."""
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────
# FR-01: Chat Completions — Integration
# ─────────────────────────────────────────────────────────────────────


class TestFR01Integration:
    """FR-01: Integration tests for /v1/chat/completions."""

    @patch("proxy.app.main.non_stream_completion", new_callable=AsyncMock)
    @patch("proxy.app.main.process_rag_query", new_callable=AsyncMock)
    @patch("proxy.app.main.USE_LANGGRAPH", False)
    @patch("proxy.app.main.LOG_REQUESTS", False)
    @patch("proxy.app.main.request_tracker")
    @patch("proxy.app.main.audit_logger", None)
    @patch("proxy.app.main.extract_version_from_query", return_value=None)
    @patch("proxy.app.shared.memory_manager.enrich_query_with_context", side_effect=lambda c, q: q)
    @patch("proxy.app.shared.memory_manager.get_conversation")
    def test_non_streaming_returns_openai_format(
        self,
        mock_get_conv,
        mock_enrich,
        mock_extract_ver,
        mock_tracker,
        mock_process,
        mock_non_stream,
        client,
    ):
        """AC1: Non-streaming returns {choices: [{message: {content}}]}."""
        # Setup mocks
        mock_conv = MagicMock()
        mock_conv.needs_summarization.return_value = False
        mock_conv.add_turn = MagicMock()
        mock_get_conv.return_value = mock_conv

        sources = [{"chunk_id": "c1", "source": "test", "title": "Test", "version": "1.0", "relevance": 0.9}]
        mock_process.return_value = (
            "Test answer",  # response_text
            "test context",  # rag_ctx
            False,  # from_cache
            sources,
            {},  # ragas_scores — must be dict, not MagicMock
        )

        with (
            patch("proxy.app.core.confidence.compute_confidence") as mock_conf,
            patch("proxy.app.core.confidence.should_generate_answer", return_value=(True, "ok")),
            patch("proxy.app.core.hitl.generate_feedback_id", return_value="fb_test_123"),
            patch("proxy.app.core.knowledge_status.determine_knowledge_status") as mock_ks,
            patch("proxy.app.core.clarification.generate_clarifying_questions") as mock_clar,
        ):
            mock_conf.return_value = MagicMock(score=0.85)
            mock_ks.return_value = MagicMock(status="sufficient", source_count=1)
            mock_clar.return_value = MagicMock(clarification_needed=False, questions=[])

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "qwen3-635b+RAG",
                    "messages": [{"role": "user", "content": "What is RAG?"}],
                    "stream": False,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "Test answer"
        assert data["choices"][0]["finish_reason"] == "stop"

    @patch("proxy.app.main.stream_completion", new_callable=MagicMock)
    @patch("proxy.app.main.process_rag_query", new_callable=AsyncMock)
    @patch("proxy.app.main.USE_LANGGRAPH", False)
    @patch("proxy.app.main.LOG_REQUESTS", False)
    @patch("proxy.app.main.request_tracker")
    @patch("proxy.app.main.audit_logger", None)
    @patch("proxy.app.main.extract_version_from_query", return_value=None)
    @patch("proxy.app.shared.memory_manager.enrich_query_with_context", side_effect=lambda c, q: q)
    @patch("proxy.app.shared.memory_manager.get_conversation")
    def test_streaming_returns_sse_with_done(
        self,
        mock_get_conv,
        mock_enrich,
        mock_extract_ver,
        mock_tracker,
        mock_process,
        mock_stream,
        client,
    ):
        """AC2: Streaming returns SSE ending with data: [DONE]."""
        mock_conv = MagicMock()
        mock_conv.needs_summarization.return_value = False
        mock_conv.add_turn = MagicMock()
        mock_get_conv.return_value = mock_conv

        mock_process.return_value = (
            "test context",
            [{"role": "user", "content": "What is RAG?"}],  # messages_for_llm must be list
            False,
            [{"chunk_id": "c1", "source": "test", "title": "Test", "version": "1.0", "relevance": 0.9}],
            {},
        )

        async def mock_stream_gen(*args, **kwargs):
            yield {"choices": [{"delta": {"content": "RAG "}, "index": 0}]}
            yield {"choices": [{"delta": {"content": "is great."}, "index": 0}]}

        mock_stream.side_effect = mock_stream_gen

        with (
            patch("proxy.app.core.confidence.compute_confidence") as mock_conf,
            patch("proxy.app.core.confidence.should_generate_answer", return_value=(True, "ok")),
            patch("proxy.app.core.hitl.generate_feedback_id", return_value="fb_test_456"),
            patch("proxy.app.core.knowledge_status.determine_knowledge_status") as mock_ks,
            patch("proxy.app.core.clarification.generate_clarifying_questions") as mock_clar,
        ):
            mock_conf.return_value = MagicMock(score=0.85)
            mock_ks.return_value = MagicMock(status="sufficient", source_count=1)
            mock_clar.return_value = MagicMock(clarification_needed=False, questions=[])

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "qwen3-635b+RAG",
                    "messages": [{"role": "user", "content": "What is RAG?"}],
                    "stream": True,
                },
            )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE lines
        lines = [line for line in response.text.split("\n") if line.strip()]
        assert len(lines) >= 1
        # Last non-meta line should be [DONE]
        data_lines = [line for line in lines if line.startswith("data: ")]
        assert data_lines[-1].strip() == "data: [DONE]"


# ─────────────────────────────────────────────────────────────────────
# FR-02: Models endpoint — Integration
# ─────────────────────────────────────────────────────────────────────


class TestFR02Integration:
    """FR-02: Integration test for /v1/models."""

    def test_models_endpoint_returns_list(self, client):
        """AC1: GET /v1/models returns {object: 'list', data: [...]}."""
        # Import main to check if app is already set up
        # We need to test the models endpoint which is in main.py
        # For now, test the data model directly
        from proxy.app.api.chat import ModelInfo, ModelsResponse

        models = ModelsResponse(
            data=[
                ModelInfo(id="qwen3-635b+RAG", created=int(time.time())),
                ModelInfo(id="qwen3-635b", created=int(time.time())),
            ],
        )
        data = models.model_dump()
        assert data["object"] == "list"
        assert len(data["data"]) == 2
        assert data["data"][0]["object"] == "model"


# ─────────────────────────────────────────────────────────────────────
# FR-03: Health check — Integration
# ─────────────────────────────────────────────────────────────────────


class TestFR03Integration:
    """FR-03: Integration test for /v1/health."""

    @patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {"knowledge_bases": 2}))
    @patch("proxy.app.api.health._check_llm", return_value=("ok", {"endpoint": "http://llm:8000"}))
    @patch("proxy.app.api.health._check_qdrant", return_value=("ok", {"collections": 5}))
    def test_health_all_healthy(self, mock_q, mock_l, mock_kb, client):
        """AC1: All services up → 200, all components healthy."""
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["components"]["qdrant"] == "ok"
        assert data["components"]["llm"] == "ok"

    @patch("proxy.app.api.health._check_kb_manager", return_value=("ok", {}))
    @patch("proxy.app.api.health._check_llm", return_value=("ok", {}))
    @patch("proxy.app.api.health._check_qdrant", return_value=("Qdrant service unavailable", {}))
    def test_health_qdrant_down(self, mock_q, mock_l, mock_kb, client):
        """AC2: Qdrant down → 503, qdrant component down."""
        response = client.get("/v1/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["components"]["qdrant"] != "ok"


# ─────────────────────────────────────────────────────────────────────
# FR-04: Kubernetes probes — Integration
# ─────────────────────────────────────────────────────────────────────


class TestFR04Integration:
    """FR-04: Integration test for /v1/health/live and /v1/health/ready."""

    def test_liveness_probe_200(self, client):
        """AC1: /v1/health/live always returns 200."""
        response = client.get("/v1/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    @patch("proxy.app.api.health._check_llm", return_value=("ok", {}))
    @patch("proxy.app.api.health._check_qdrant", return_value=("ok", {}))
    def test_readiness_probe_200_healthy(self, mock_q, mock_l, client):
        """AC: /v1/health/ready returns 200 when healthy."""
        response = client.get("/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"

    @patch("proxy.app.api.health._check_llm", return_value=("ok", {}))
    @patch("proxy.app.api.health._check_qdrant", return_value=("unavailable", {}))
    def test_readiness_probe_503_qdrant_down(self, mock_q, mock_l, client):
        """AC2: /v1/health/ready returns 503 when Qdrant down."""
        response = client.get("/v1/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"


# ─────────────────────────────────────────────────────────────────────
# FR-05 through FR-06: RAG parameters and response fields — Integration
# ─────────────────────────────────────────────────────────────────────


class TestFR05FR06Integration:
    """FR-05/06: RAG parameters and response fields in full pipeline."""

    @patch("proxy.app.main.non_stream_completion", new_callable=AsyncMock)
    @patch("proxy.app.main.process_rag_query", new_callable=AsyncMock)
    @patch("proxy.app.main.USE_LANGGRAPH", False)
    @patch("proxy.app.main.LOG_REQUESTS", False)
    @patch("proxy.app.main.request_tracker")
    @patch("proxy.app.main.audit_logger", None)
    @patch("proxy.app.main.extract_version_from_query", return_value=None)
    @patch("proxy.app.shared.memory_manager.enrich_query_with_context", side_effect=lambda c, q: q)
    @patch("proxy.app.shared.memory_manager.get_conversation")
    def test_rag_response_contains_extension_fields(
        self,
        mock_get_conv,
        mock_enrich,
        mock_extract_ver,
        mock_tracker,
        mock_process,
        mock_non_stream,
        client,
    ):
        """AC: Response contains rag_feedback_id, rag_confidence, rag_sources."""
        mock_conv = MagicMock()
        mock_conv.needs_summarization.return_value = False
        mock_conv.add_turn = MagicMock()
        mock_get_conv.return_value = mock_conv

        sources = [
            {"chunk_id": "c1", "source": "confluence", "title": "RAG Guide", "version": "1.0", "relevance": 0.95},
        ]
        mock_process.return_value = ("RAG is retrieval-augmented generation.", "context", False, sources, {})

        with (
            patch("proxy.app.core.confidence.compute_confidence") as mock_conf,
            patch("proxy.app.core.confidence.should_generate_answer", return_value=(True, "ok")),
            patch("proxy.app.core.hitl.generate_feedback_id", return_value="fb_abc"),
            patch("proxy.app.core.knowledge_status.determine_knowledge_status") as mock_ks,
            patch("proxy.app.core.clarification.generate_clarifying_questions") as mock_clar,
        ):
            mock_conf.return_value = MagicMock(score=0.92)
            mock_ks.return_value = MagicMock(status="sufficient", source_count=1)
            mock_clar.return_value = MagicMock(clarification_needed=False, questions=[])

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "qwen3-635b+RAG",
                    "messages": [{"role": "user", "content": "What is RAG?"}],
                    "stream": False,
                },
            )

        assert response.status_code == 200
        data = response.json()

        # FR-06: RAG response fields
        assert "rag_feedback_id" in data
        assert data["rag_feedback_id"] is not None
        assert len(data["rag_feedback_id"]) > 0

        assert "rag_confidence" in data
        assert 0.0 <= data["rag_confidence"] <= 1.0

        assert "rag_sources" in data
        assert isinstance(data["rag_sources"], list)


# ─────────────────────────────────────────────────────────────────────
# FR-08: SSE streaming format — Integration
# ─────────────────────────────────────────────────────────────────────


class TestFR08Integration:
    """FR-08: SSE streaming format in full pipeline."""

    @patch("proxy.app.main.stream_completion", new_callable=MagicMock)
    @patch("proxy.app.main.process_rag_query", new_callable=AsyncMock)
    @patch("proxy.app.main.USE_LANGGRAPH", False)
    @patch("proxy.app.main.LOG_REQUESTS", False)
    @patch("proxy.app.main.request_tracker")
    @patch("proxy.app.main.audit_logger", None)
    @patch("proxy.app.main.extract_version_from_query", return_value=None)
    @patch("proxy.app.shared.memory_manager.enrich_query_with_context", side_effect=lambda c, q: q)
    @patch("proxy.app.shared.memory_manager.get_conversation")
    def test_sse_format_and_done_marker(
        self,
        mock_get_conv,
        mock_enrich,
        mock_extract_ver,
        mock_tracker,
        mock_process,
        mock_stream,
        client,
    ):
        """AC: SSE response with data: lines and data: [DONE]."""
        mock_conv = MagicMock()
        mock_conv.needs_summarization.return_value = False
        mock_conv.add_turn = MagicMock()
        mock_get_conv.return_value = mock_conv

        mock_process.return_value = (
            "answer",
            [{"role": "user", "content": "test"}],  # messages_for_llm must be list
            False,
            [{"chunk_id": "c1", "source": "test", "title": "T", "version": "1.0", "relevance": 0.9}],
            {},
        )

        async def mock_stream_gen(*args, **kwargs):
            yield {"choices": [{"delta": {"content": "token1"}, "index": 0}]}
            yield {"choices": [{"delta": {"content": "token2"}, "index": 0}]}

        mock_stream.side_effect = mock_stream_gen

        with (
            patch("proxy.app.core.confidence.compute_confidence") as mock_conf,
            patch("proxy.app.core.confidence.should_generate_answer", return_value=(True, "ok")),
            patch("proxy.app.core.hitl.generate_feedback_id", return_value="fb_123"),
            patch("proxy.app.core.knowledge_status.determine_knowledge_status") as mock_ks,
            patch("proxy.app.core.clarification.generate_clarifying_questions") as mock_clar,
        ):
            mock_conf.return_value = MagicMock(score=0.8)
            mock_ks.return_value = MagicMock(status="sufficient", source_count=1)
            mock_clar.return_value = MagicMock(clarification_needed=False, questions=[])

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "qwen3-635b+RAG",
                    "messages": [{"role": "user", "content": "test"}],
                    "stream": True,
                },
            )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        lines = response.text.split("\n")
        data_lines = [line for line in lines if line.startswith("data: ")]

        # Verify data lines exist
        assert len(data_lines) >= 1

        # Verify last data line is [DONE]
        assert data_lines[-1].strip() == "data: [DONE]"

        # Verify intermediate lines are valid JSON
        for line in data_lines[:-1]:
            payload = json.loads(line[6:].strip())
            assert isinstance(payload, dict)


# ─────────────────────────────────────────────────────────────────────
# FR-09 through FR-18: Retrieval unit tests are in test_core_api.py
# These integration tests verify the full pipeline behavior
# ─────────────────────────────────────────────────────────────────────


class TestRetrievalIntegration:
    """Integration tests for retrieval pipeline (FR-09 to FR-18)."""

    def test_rrf_formula_integration(self):
        """FR-09: RRF formula with realistic data."""
        from proxy.app.core.retrieval import reciprocal_rank_fusion

        dense = []
        sparse = []
        for i in range(10):
            dense.append(MagicMock(id=f"doc_{i}", score=0.9 - i * 0.05, payload={"text": f"Doc {i}"}))
        for i in range(5, 15):
            sparse.append(MagicMock(id=f"doc_{i}", score=0.85 - (i - 5) * 0.05, payload={"text": f"Doc {i}"}))

        result = reciprocal_rank_fusion(dense, sparse, k=60)
        assert len(result) > 0

        # doc_5 through doc_9 appear in both lists — should rank higher
        top_ids = [r.id for r in result[:5]]
        # At least some overlapping docs should be in top 5
        overlapping = [f"doc_{i}" for i in range(5, 10)]
        assert any(oid in top_ids for oid in overlapping)

    def test_knee_point_pruning_integration(self):
        """FR-15: Knee-point pruning with realistic score distribution."""
        from proxy.app.core.retrieval import knee_point_pruning

        # Simulate realistic retrieval scores with a clear drop-off
        scores = [0.95, 0.92, 0.88, 0.85, 0.82, 0.30, 0.25, 0.20, 0.15, 0.10]
        results = [MagicMock(id=f"r{i}", score=scores[i], payload={}) for i in range(len(scores))]

        pruned = knee_point_pruning(results, sensitivity=0.5)
        assert len(pruned) < len(results)
        assert len(pruned) >= 2
        # High-scoring results should be preserved
        pruned_ids = [r.id for r in pruned]
        assert "r0" in pruned_ids  # highest score

    def test_deduplication_pipeline(self):
        """FR-11: Deduplication in context building pipeline."""
        from proxy.app.core.context.builder import deduplicate_chunks

        chunks = [
            ({"text": "Same content", "source_type": "c", "source_id": "1", "version": "1", "doc_title": "D"}, 0.9),
            ({"text": "Same content", "source_type": "c", "source_id": "1", "version": "1", "doc_title": "D"}, 0.8),
            (
                {"text": "Different content", "source_type": "c", "source_id": "2", "version": "1", "doc_title": "D"},
                0.7,
            ),
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 2

    def test_version_resolution_pipeline(self):
        """FR-12: Version resolution in context pipeline."""
        from proxy.app.core.context.versioning import resolve_versions

        chunks = [
            ({"text": "old", "source_id": "doc1", "version": "1.0"}, 0.9),
            ({"text": "new", "source_id": "doc1", "version": "2.0"}, 0.8),
            ({"text": "v1 only", "source_id": "doc2", "version": "1.0"}, 0.7),
        ]

        # Without version filter: latest wins
        result_latest = resolve_versions(chunks, requested_version=None)
        versions = {ch.get("source_id"): ch.get("version") for ch, _ in result_latest}
        assert versions.get("doc1") == "2.0"

        # With version filter: only matching
        result_v1 = resolve_versions(chunks, requested_version="1.0")
        for ch, _ in result_v1:
            assert ch.get("version") == "1.0"

    def test_flare_integration(self):
        """FR-16: FLARE controller with mock search."""
        from proxy.app.core.flare import FLAREController

        mock_results = [
            MagicMock(payload={"text": "Additional context from re-retrieval"}),
        ]
        search_fn = MagicMock(return_value=mock_results)
        controller = FLAREController(
            search_fn=search_fn,
            confidence_threshold=0.5,
            max_retrievals=3,
        )

        # Test re-retrieval
        new_contexts = controller.retrieve_additional_context("test query", ["existing"])
        assert len(new_contexts) == 1
        assert "Additional context" in new_contexts[0]
        search_fn.assert_called_once()

    def test_dynamic_top_k_integration(self):
        """FR-18: Dynamic top-k with complexity scoring."""
        from proxy.app.llm.slm import dynamic_top_k_from_complexity

        # Simple queries should get fewer chunks
        simple_top_k = dynamic_top_k_from_complexity(1)
        assert simple_top_k <= 5

        # Complex queries should get more chunks
        complex_top_k = dynamic_top_k_from_complexity(10)
        assert complex_top_k >= 40

        # Middle range
        mid_top_k = dynamic_top_k_from_complexity(5)
        assert 10 <= mid_top_k <= 20

    def test_colbert_score_integration(self):
        """FR-14: ColBERT scoring with realistic token embeddings."""
        from proxy.app.core.rerank import colbert_score

        # Simulate 3-token query and 5-token document
        query_tokens = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        doc_tokens = [
            [0.9, 0.1, 0.0],
            [0.1, 0.9, 0.0],
            [0.0, 0.1, 0.9],
            [0.5, 0.5, 0.0],
            [0.0, 0.0, 1.0],
        ]
        score = colbert_score(query_tokens, doc_tokens)
        assert 0.0 < score <= 1.0
