"""Tests for dynamic top-k retrieval in orchestrator.py."""

from unittest.mock import patch

from proxy.app.core import orchestrator
from proxy.app.core.orchestrator import _dynamic_top_k


class TestDynamicTopK:
    """Tests for the _dynamic_top_k function.

    Uses orchestrator.IntentType because orchestrator imports from proxy.app.llm.slm
    which is a separate module from proxy.app.llm.slm, so IntentType values
    from proxy.app.llm.slm are different objects than those used in the
    orchestrator's comparison logic.
    """

    def test_factual_query_returns_small_topk(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.FACTUAL, 0.9)
            result = _dynamic_top_k("What is Kubernetes?", max_default=50)
            assert result == 15

    def test_procedural_query_returns_medium_topk(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.PROCEDURAL, 0.85)
            result = _dynamic_top_k("How do I configure CI/CD?", max_default=50)
            assert result == 25

    def test_comparison_query_returns_max_topk(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.COMPARISON, 0.9)
            result = _dynamic_top_k("Compare Kubernetes vs Docker Swarm", max_default=50)
            assert result == 50

    def test_summarization_query_returns_max_topk(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.SUMMARIZATION, 0.9)
            result = _dynamic_top_k("Summarize the deployment guide", max_default=50)
            assert result == 30  # min(30, 50)

    def test_greeting_returns_zero(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.GREETING, 0.95)
            result = _dynamic_top_k("Hello!", max_default=50)
            assert result == 0

    def test_unknown_falls_back_to_default(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.UNKNOWN, 0.5)
            result = _dynamic_top_k("some unusual query", max_default=50)
            assert result == 50

    def test_slm_unavailable_falls_back_to_default(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.side_effect = RuntimeError("SLM not available")
            result = _dynamic_top_k("any query", max_default=50)
            assert result == 50

    def test_max_default_caps_factual(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.FACTUAL, 0.9)
            result = _dynamic_top_k("factual query", max_default=10)
            assert result == 10  # min(15, 10) = 10

    def test_max_default_caps_procedural(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.PROCEDURAL, 0.9)
            result = _dynamic_top_k("procedural query", max_default=20)
            assert result == 20  # min(25, 20) = 20

    def test_returns_int_type(self):
        with patch("proxy.app.core.orchestrator.classify_intent") as mock_classify:
            mock_classify.return_value = (orchestrator.IntentType.COMPARISON, 0.9)
            result = _dynamic_top_k("test", max_default=30)
            assert isinstance(result, int)
