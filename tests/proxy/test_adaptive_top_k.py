"""Unit tests for knee-based adaptive top-k selection in the reranker.

Covers the pure ``adaptive_top_k`` function (success, edge, and degradation paths)
and verifies that ``rerank_chunks`` honors the feature flag with a safe fallback
to the statically requested top_k when the flag is disabled.
"""

from unittest.mock import MagicMock

import pytest

from proxy.app.core import rerank as rerank_mod


class TestAdaptiveTopK:
    """Pure-function behavior of adaptive_top_k."""

    def test_empty_scores_returns_zero(self):
        assert rerank_mod.adaptive_top_k([], 10) == 0

    def test_non_positive_request_returns_zero(self):
        assert rerank_mod.adaptive_top_k([0.9, 0.8], 0) == 0

    def test_short_list_returns_full_length(self):
        assert rerank_mod.adaptive_top_k([0.9, 0.5], 10) == 2

    def test_sharp_drop_cuts_at_knee(self):
        scores = [0.9, 0.85, 0.8, 0.2, 0.19, 0.18]
        k = rerank_mod.adaptive_top_k(scores, requested_k=6, sensitivity=1.0)
        # Knee sits at the drop after index 2 -> keep 3 chunks.
        assert k == 3

    def test_flat_curve_degrades_to_requested_k(self):
        scores = [0.5] * 20
        assert rerank_mod.adaptive_top_k(scores, requested_k=20) == 20

    def test_gradual_curve_keeps_most_results(self):
        scores = [float(100 - i) for i in range(50)]  # linear decline, no knee
        k = rerank_mod.adaptive_top_k(scores, requested_k=50, sensitivity=0.5)
        assert k >= 45  # conservative on smooth curves

    def test_sensitivity_zero_returns_requested(self):
        scores = [0.9, 0.85, 0.1, 0.09]
        assert rerank_mod.adaptive_top_k(scores, requested_k=4, sensitivity=0.0) == 4

    def test_result_always_within_bounds(self):
        scores = [0.9, 0.89, 0.2, 0.19, 0.18, 0.17]
        for sens in (-1.0, 0.0, 0.25, 0.5, 1.0, 7.0):
            k = rerank_mod.adaptive_top_k(scores, requested_k=6, sensitivity=sens)
            assert rerank_mod.ADAPTIVE_TOP_K_MIN <= k <= 6


class TestRerankChunksFlagWiring:
    """rerank_chunks must honor the ADAPTIVE_TOP_K_ENABLED flag."""

    @pytest.fixture()
    def _mock_reranker_env(self, monkeypatch):
        monkeypatch.setattr(rerank_mod, "reranker", MagicMock(), raising=False)
        monkeypatch.setattr(rerank_mod, "cache_manager", None, raising=False)
        monkeypatch.setattr(
            rerank_mod,
            "_call_reranker_safe",
            lambda pairs: [0.9 - 0.01 * i if i < 3 else 0.1 for i in range(len(pairs))],
        )

    @pytest.mark.usefixtures("_mock_reranker_env")
    def test_flag_disabled_returns_static_top_k(self, monkeypatch):
        monkeypatch.setattr(rerank_mod, "ADAPTIVE_TOP_K_ENABLED", False)
        chunks = [f"chunk {i}" for i in range(10)]
        result = rerank_mod.rerank_chunks("q", chunks, top_k=10)
        assert len(result) == 10

    @pytest.mark.usefixtures("_mock_reranker_env")
    def test_flag_enabled_prunes_flat_tail(self, monkeypatch):
        monkeypatch.setattr(rerank_mod, "ADAPTIVE_TOP_K_ENABLED", True)
        chunks = [f"chunk {i}" for i in range(10)]
        result = rerank_mod.rerank_chunks("q", chunks, top_k=10)
        assert len(result) < 10
        assert len(result) >= rerank_mod.ADAPTIVE_TOP_K_MIN

    @pytest.mark.usefixtures("_mock_reranker_env")
    def test_no_chunks_returns_empty(self):
        assert rerank_mod.rerank_chunks("q", [], top_k=5) == []
