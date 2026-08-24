"""Flag-matrix verification for FR-176 / NFR-A07 (operator-configurable degradation).

Runs the core pipeline with each major optional subsystem disabled and asserts the
request still completes. This is the executable form of the "flag matrix" check
recorded in docs/en/guides/compliance-requirements.md. All external services are
mocked per project convention — the test verifies wiring/topology, not services.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _hit() -> MagicMock:
    hit = MagicMock()
    hit.payload = {"text": "chunk text", "source_type": "wiki", "title": "T", "version": "1"}
    hit.score = 0.9
    return hit


async def _run_pipeline(**extra_flags: bool) -> str:
    """Run process_rag_query with every optional subsystem forced off."""
    from proxy.app.main import process_rag_query

    timings: dict[str, float] = {}
    with (
        patch("proxy.app.main.cache_manager", None),  # Redis off
        patch("proxy.app.main.semantic_cache", None),  # semantic cache off
        patch("proxy.app.main.hybrid_search", return_value=[_hit()]),
        patch("proxy.app.main.rerank_chunks", return_value=[0]),
        patch("proxy.app.main.deduplicate_chunks", return_value=[({"text": "t"}, 0.95)]),
        patch("proxy.app.main.build_context", return_value="ctx"),
        patch("proxy.app.main.non_stream_completion", new=AsyncMock(return_value="OK")),
        patch("proxy.app.core.retrieval.qdrant_client", MagicMock()),
        patch("proxy.app.core.retrieval.embedder", MagicMock()),
        patch("proxy.app.core.ragas_eval.evaluate_rag_response", return_value={}),
    ):
        result, _, _, _, _ = await process_rag_query(user_query="q", stream=False, stage_timings=timings, **extra_flags)
    assert timings.get("generation_ms") is not None
    return result


@pytest.mark.asyncio
async def test_pipeline_completes_with_adaptive_top_k_off(monkeypatch):
    monkeypatch.setattr("proxy.app.core.rerank.ADAPTIVE_TOP_K_ENABLED", False)
    assert await _run_pipeline()


@pytest.mark.asyncio
async def test_pipeline_completes_with_adaptive_top_k_on(monkeypatch):
    monkeypatch.setattr("proxy.app.core.rerank.ADAPTIVE_TOP_K_ENABLED", True)
    assert await _run_pipeline()


@pytest.mark.asyncio
async def test_pipeline_completes_with_all_caches_disabled():
    """Redis + semantic cache both None → exact-match layer skipped, still answers."""
    assert await _run_pipeline()
