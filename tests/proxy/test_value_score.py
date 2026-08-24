"""Unit tests for the EvalGate value_score helper (quality-vs-cost comparison).

The helper must behave identically in both eval_gate trees (proxy and standalone
service); ``tests/proxy/test_model_evolution_eval_gate_sync.py`` guards tree parity.
"""

import math

import pytest

from proxy.app.model_evolution.eval_gate import (
    VALUE_SCORE_COST_WEIGHT,
    VALUE_SCORE_QUALITY_WEIGHT,
    value_score,
)


class TestValueScore:
    def test_perfect_quality_zero_cost_scores_one(self):
        assert value_score(quality=1.0, cost_per_1k_tokens=0.0) == pytest.approx(1.0)

    def test_quality_dominates_cost(self):
        high_q = value_score(quality=1.0, cost_per_1k_tokens=10.0)
        low_q = value_score(quality=0.2, cost_per_1k_tokens=0.0)
        assert high_q > low_q

    def test_higher_cost_lowers_score_monotonically(self):
        cheap = value_score(quality=0.8, cost_per_1k_tokens=1.0)
        mid = value_score(quality=0.8, cost_per_1k_tokens=5.0)
        expensive = value_score(quality=0.8, cost_per_1k_tokens=25.0)
        assert cheap > mid > expensive

    def test_cost_never_pushes_score_below_quality_share(self):
        # Even an absurd cost keeps at least W_Q * norm_quality contribution.
        floor = VALUE_SCORE_QUALITY_WEIGHT * 0.9
        assert value_score(quality=0.9, cost_per_1k_tokens=1e9) >= floor

    def test_negative_cost_clamped_to_free(self):
        assert value_score(0.5, -100.0) == value_score(0.5, 0.0)

    def test_quality_clamped_to_unit_range(self):
        above = value_score(quality=7.0, quality_min=0.0, quality_max=1.0, cost_per_1k_tokens=0.0)
        below = value_score(quality=-3.0, quality_min=0.0, quality_max=1.0, cost_per_1k_tokens=0.0)
        # Clamping affects only the normalized quality term; the free-cost term stays.
        assert above == pytest.approx(1.0)
        assert below == pytest.approx(VALUE_SCORE_COST_WEIGHT)

    def test_custom_quality_scale(self):
        # Accuracy on a 0-100 scale: 85 -> norm 0.85
        s = value_score(quality=85.0, quality_min=0.0, quality_max=100.0, cost_per_1k_tokens=0.0)
        assert s == pytest.approx(VALUE_SCORE_QUALITY_WEIGHT * 0.85 + VALUE_SCORE_COST_WEIGHT * 1.0)

    def test_degenerate_quality_span_treated_as_zero_quality(self):
        s = value_score(quality=50.0, quality_min=10.0, quality_max=10.0, cost_per_1k_tokens=0.0)
        assert s == pytest.approx(VALUE_SCORE_COST_WEIGHT)  # only the free-cost term

    def test_weights_sum_to_one(self):
        assert pytest.approx(1.0) == VALUE_SCORE_QUALITY_WEIGHT + VALUE_SCORE_COST_WEIGHT

    def test_cost_term_formula_matches_definition(self):
        cost = 4.0
        expected_cost_term = 1.0 / (1.0 + math.log1p(cost))
        assert value_score(0.0, cost) == pytest.approx(VALUE_SCORE_COST_WEIGHT * expected_cost_term)


class TestValueScoreTreeParity:
    def test_service_tree_exposes_identical_helper(self):
        import model_evolution_service.evaluation.eval_gate as svc_gate

        assert svc_gate.value_score(0.9, 1.0) == pytest.approx(value_score(0.9, 1.0))
        assert svc_gate.VALUE_SCORE_QUALITY_WEIGHT == VALUE_SCORE_QUALITY_WEIGHT
