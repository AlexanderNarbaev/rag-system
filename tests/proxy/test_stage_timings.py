"""Unit tests for per-stage latency breakdown (rag_stage_timings_ms).

Verifies that ``process_rag_query`` fills the optional ``stage_timings`` dict
with retrieval / rerank / generation measurements and observes the corresponding
Prometheus histograms — including on the degraded-retrieval path (graceful
behavior requirement). External services are fully mocked per project convention.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_hit() -> MagicMock:
    hit = MagicMock()
    hit.payload = {"text": "chunk text", "source_type": "wiki", "title": "T", "version": "1"}
    hit.score = 0.9
    return hit


@pytest.mark.asyncio
async def test_stage_timings_populated_on_full_pipeline():
    """All three stages are measured when retrieval succeeds."""
    timings: dict[str, float] = {}
    mock_chunk = {"text": "chunk text", "source_type": "wiki", "title": "T", "version": "1"}
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.semantic_cache", None),
        patch("proxy.app.main.hybrid_search", return_value=[_mock_hit()]),
        patch("proxy.app.main.rerank_chunks", return_value=[0]),
        patch("proxy.app.main.deduplicate_chunks", return_value=[(mock_chunk, 0.95)]),
        patch("proxy.app.main.build_context", return_value="Built context"),
        patch("proxy.app.main.non_stream_completion", new=AsyncMock(return_value="Answer")),
        patch("proxy.app.core.retrieval.qdrant_client", MagicMock()),
        patch("proxy.app.core.retrieval.embedder", MagicMock()),
        patch("proxy.app.core.ragas_eval.evaluate_rag_response", return_value={}),
    ):
        from proxy.app.main import process_rag_query

        await process_rag_query(user_query="test", stream=False, stage_timings=timings)

    for stage in ("retrieval_ms", "rerank_ms", "generation_ms"):
        assert stage in timings, f"missing {stage} in {timings}"
        assert isinstance(timings[stage], float)
        assert timings[stage] >= 0.0


@pytest.mark.asyncio
async def test_stage_timings_recorded_when_retrieval_degraded():
    """Degraded retrieval must still record timing — graceful degradation."""
    timings: dict[str, float] = {}
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.semantic_cache", None),
        patch("proxy.app.core.retrieval.embedder", None),  # forces degraded path
        patch("proxy.app.main.non_stream_completion", new=AsyncMock(return_value="Fallback answer")),
    ):
        from proxy.app.main import process_rag_query

        await process_rag_query(user_query="test", stream=False, stage_timings=timings)

    assert "retrieval_ms" in timings
    assert "rerank_ms" not in timings  # never reached — correctly absent
    assert "generation_ms" in timings


@pytest.mark.asyncio
async def test_stage_histograms_observed():
    """Existing Prometheus stage histograms get at least one observation."""
    hist_retrieval = MagicMock()
    hist_llm = MagicMock()
    mock_chunk = {"text": "chunk text", "source_type": "wiki", "title": "T", "version": "1"}
    with (
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.semantic_cache", None),
        patch("proxy.app.main.hybrid_search", return_value=[_mock_hit()]),
        patch("proxy.app.main.rerank_chunks", return_value=[0]),
        patch("proxy.app.main.deduplicate_chunks", return_value=[(mock_chunk, 0.95)]),
        patch("proxy.app.main.build_context", return_value="ctx"),
        patch("proxy.app.main.non_stream_completion", new=AsyncMock(return_value="Answer")),
        patch("proxy.app.core.retrieval.qdrant_client", MagicMock()),
        patch("proxy.app.core.retrieval.embedder", MagicMock()),
        patch("proxy.app.core.ragas_eval.evaluate_rag_response", return_value={}),
        patch("proxy.app.shared.metrics.rag_retrieval_duration_seconds", hist_retrieval),
        patch("proxy.app.shared.metrics.rag_llm_duration_seconds", hist_llm),
    ):
        from proxy.app.main import process_rag_query

        await process_rag_query(user_query="test", stream=False, stage_timings={})

    hist_retrieval.observe.assert_called_once()
    hist_llm.observe.assert_called_once()


@pytest.mark.asyncio
async def test_no_stage_timings_param_is_backward_compatible():
    """Omitting stage_timings must not break the call (existing callers unchanged)."""
    with (
        patch("proxy.app.main.cache_manager", MagicMock(get=AsyncMock(return_value="Cached"))),
        patch("proxy.app.main.semantic_cache", None),
    ):
        from proxy.app.main import process_rag_query

        result, _, from_cache, _, _ = await process_rag_query(user_query="q", stream=False)
    assert from_cache is True
    assert result == "Cached"
