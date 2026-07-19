"""Tests for proxy/app/ab_test.py — A/B test harness for pipeline variants."""

import pytest

from proxy.app.shared.ab_test import (
    ABTest,
    ABVariant,
    compute_effect_size,
    get_statistical_significance,
)


class TestABVariant:
    def test_create_variant(self):
        v = ABVariant(name="control", config={"reranker": "MiniLM"}, weight=0.5)
        assert v.name == "control"
        assert v.config == {"reranker": "MiniLM"}
        assert v.weight == 0.5
        assert v.trials == 0
        assert v.metrics == {}

    def test_default_weight(self):
        v = ABVariant(name="test", config={})
        assert v.weight == 1.0

    def test_record_metric(self):
        v = ABVariant(name="test", config={})
        v.record("latency_ms", 150)
        v.record("latency_ms", 200)
        v.record_trial()
        assert v.metrics["latency_ms"] == [150, 200]
        assert v.trials == 1

    def test_record_metric_increments_trials(self):
        v = ABVariant(name="test", config={})
        v.record_trial()
        v.record_trial()
        assert v.trials == 2

    def test_metric_stats(self):
        v = ABVariant(name="test", config={})
        v.record("score", 0.8)
        v.record("score", 0.6)
        v.record("score", 1.0)
        stats = v.metric_stats("score")
        assert stats["count"] == 3
        assert abs(stats["mean"] - 0.8) < 0.01
        assert stats["min"] == 0.6
        assert stats["max"] == 1.0

    def test_metric_stats_empty(self):
        v = ABVariant(name="test", config={})
        stats = v.metric_stats("nonexistent")
        assert stats["count"] == 0


class TestABTest:
    def test_register_variant(self):
        ab = ABTest(name="reranker_test")
        v = ab.register("baseline", {"reranker": "none"})
        assert v.name == "baseline"
        assert len(ab.variants) == 1

    def test_register_duplicate_raises(self):
        ab = ABTest(name="test")
        ab.register("v1", {})
        with pytest.raises(ValueError, match="already registered"):
            ab.register("v1", {})

    def test_select_variant_returns_correct_type(self):
        ab = ABTest(name="test")
        ab.register("control", {})
        selected = ab.select_variant()
        assert isinstance(selected, ABVariant)
        assert selected.name == "control"

    def test_select_variant_weighted(self):
        ab = ABTest(name="test")
        ab.register("a", {}, weight=0.0)
        ab.register("b", {}, weight=1.0)
        for _ in range(20):
            selected = ab.select_variant()
            assert selected.name == "b"

    def test_record_result(self):
        ab = ABTest(name="test")
        v = ab.register("v1", {})
        ab.record_result("v1", {"latency_ms": 100, "confidence": 0.9})
        assert v.trials == 1
        assert v.metrics["latency_ms"] == [100]
        assert v.metrics["confidence"] == [0.9]

    def test_record_result_unknown_variant(self):
        ab = ABTest(name="test")
        with pytest.raises(ValueError, match="Unknown variant"):
            ab.record_result("nonexistent", {})

    def test_compare_metrics_between_variants(self):
        ab = ABTest(name="test")
        va = ab.register("a", {})
        vb = ab.register("b", {})
        va.record("score", 0.8)
        va.record("score", 0.7)
        va.record("score", 0.9)
        vb.record("score", 0.6)
        vb.record("score", 0.5)
        vb.record("score", 0.7)
        comparison = ab.compare("score", "a", "b")
        assert "p_value" in comparison
        assert "mean_a" in comparison
        assert "mean_b" in comparison
        assert comparison["mean_a"] > comparison["mean_b"]

    def test_is_significant(self):
        ab = ABTest(name="test")
        va = ab.register("a", {})
        vb = ab.register("b", {})
        import random

        for _ in range(30):
            va.record("score", 0.9 + random.uniform(-0.05, 0.05))
            vb.record("score", 0.5 + random.uniform(-0.05, 0.05))
        assert ab.is_significant("score", "a", "b", threshold=0.05) is True

    def test_get_report(self):
        ab = ABTest(name="test")
        ab.register("v1", {"top_k": 20}, weight=0.5)
        ab.register("v2", {"top_k": 50}, weight=0.5)
        report = ab.get_report()
        assert report["name"] == "test"
        assert len(report["variants"]) == 2
        assert report["total_trials"] == 0


class TestStatisticalSignificance:
    def test_clear_difference(self):
        control = [0.9, 0.85, 0.88, 0.92, 0.87]
        treatment = [0.5, 0.45, 0.48, 0.52, 0.47]
        p_value = get_statistical_significance(control, treatment)
        assert p_value < 0.01

    def test_no_difference(self):
        control = [0.701, 0.702, 0.703, 0.704, 0.705]
        treatment = [0.702, 0.703, 0.704, 0.705, 0.706]
        p_value = get_statistical_significance(control, treatment)
        assert p_value > 0.5

    def test_returns_float(self):
        p = get_statistical_significance([0.5, 0.6, 0.7], [0.3, 0.4, 0.5])
        assert isinstance(p, float)
        assert 0.0 <= p <= 1.0

    def test_single_element_raises(self):
        with pytest.raises(ValueError):
            get_statistical_significance([0.5], [0.3])

    def test_empty_lists_raises(self):
        with pytest.raises(ValueError):
            get_statistical_significance([], [])

    def test_different_sizes(self):
        p = get_statistical_significance([0.8, 0.85, 0.82, 0.87, 0.83, 0.86, 0.84, 0.88], [0.6, 0.55, 0.58, 0.57])
        assert isinstance(p, float)
        assert p < 0.05


class TestEffectSize:
    def test_large_effect(self):
        d = compute_effect_size([0.9, 0.88, 0.92, 0.87, 0.91], [0.5, 0.48, 0.52, 0.47, 0.51])
        assert d > 1.0  # large effect

    def test_small_effect(self):
        d = compute_effect_size([0.7, 0.71, 0.69, 0.72, 0.7], [0.7, 0.71, 0.69, 0.72, 0.7])
        assert abs(d) < 0.5

    def test_empty_lists(self):
        d = compute_effect_size([], [])
        assert d == 0.0

    def test_single_element_each(self):
        d = compute_effect_size([0.8], [0.5])
        assert abs(d - 0.3) < 1e-10

    def test_one_empty_list(self):
        d = compute_effect_size([0.8, 0.9], [])
        assert d == 0.0

    def test_zero_std_returns_zero(self):
        d = compute_effect_size([0.5, 0.5, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5])
        assert d == 0.0


class TestABVariantEdgeCases:
    """Tests for ABVariant edge cases."""

    def test_clear_metrics(self):
        v = ABVariant(name="test", config={})
        v.record("latency", 100)
        v.record("latency", 200)
        v.record_trial()
        v.clear_metrics()
        assert v.trials == 0
        assert v.metrics == {}

    def test_metric_stats_single_value(self):
        v = ABVariant(name="test", config={})
        v.record("score", 0.85)
        stats = v.metric_stats("score")
        assert stats["count"] == 1
        assert stats["std"] == 0.0


class TestABTestEdgeCases:
    """Tests for ABTest edge cases."""

    def test_select_variant_no_variants(self):
        ab = ABTest(name="empty")
        with pytest.raises(ValueError, match="No variants registered"):
            ab.select_variant()

    def test_select_variant_zero_weight_fallback(self):
        ab = ABTest(name="zero_weight")
        ab.register("a", {}, weight=0.0)
        v = ab.select_variant()
        assert v.name == "a"

    def test_compare_unknown_variant_raises(self):
        ab = ABTest(name="test")
        ab.register("a", {})
        with pytest.raises(ValueError, match="Variant not found"):
            ab.compare("metric", "a", "unknown")

    def test_is_significant_no_p_value(self):
        ab = ABTest(name="test")
        ab.register("a", {})
        ab.register("b", {})
        ab.record_result("a", {"score": 0.8})
        ab.record_result("b", {"score": 0.5})
        assert ab.is_significant("score", "a", "b") is False

    def test_reset_clears_all_variants(self):
        ab = ABTest(name="test")
        ab.register("a", {})
        ab.register("b", {})
        ab.record_result("a", {"score": 0.8})
        ab.record_result("b", {"score": 0.5})
        ab.reset()
        for v in ab.variants:
            assert v.trials == 0
            assert v.metrics == {}

    def test_get_statistical_significance_equal_means(self):
        values = [0.5, 0.5, 0.5]
        p = get_statistical_significance(values, values)
        assert p == 1.0

    def test_get_statistical_significance_zero_se(self):
        p = get_statistical_significance([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
        assert p == 1.0


class TestModelVariant:
    """Tests for ModelVariant dataclass."""

    def test_equality(self):
        from proxy.app.shared.ab_test import ModelVariant

        mv1 = ModelVariant(model_name="llama-3", adapter_version="v1", weight=0.8)
        mv2 = ModelVariant(model_name="llama-3", adapter_version="v1", weight=0.5)
        mv3 = ModelVariant(model_name="llama-3", adapter_version="v2")
        assert mv1 == mv2
        assert mv1 != mv3

    def test_equality_not_model_variant(self):
        from proxy.app.shared.ab_test import ModelVariant

        mv = ModelVariant(model_name="test")
        assert mv != "not_a_variant"
        assert mv != 42

    def test_hash(self):
        from proxy.app.shared.ab_test import ModelVariant

        mv1 = ModelVariant(model_name="m1", adapter_version="v1")
        mv2 = ModelVariant(model_name="m1", adapter_version="v1")
        assert hash(mv1) == hash(mv2)

    def test_defaults(self):
        from proxy.app.shared.ab_test import ModelVariant

        mv = ModelVariant(model_name="default-test")
        assert mv.adapter_version == "baseline"
        assert mv.weight == 1.0


class TestABTestRunner:
    """Tests for ABTestRunner class."""

    def test_register_variant(self):
        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        runner = ABTestRunner("test")
        mv = ModelVariant(model_name="llama-3")
        runner.register_variant(mv)
        assert len(runner.variants) == 1

    def test_remove_variant(self):
        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        runner = ABTestRunner("test")
        runner.register_variant(ModelVariant(model_name="m1"))
        runner.register_variant(ModelVariant(model_name="m2"))
        runner.remove_variant("m1")
        assert len(runner.variants) == 1
        assert runner.variants[0].model_name == "m2"

    def test_remove_nonexistent_variant(self):
        from proxy.app.shared.ab_test import ABTestRunner

        runner = ABTestRunner("test")
        runner.remove_variant("nonexistent")

    def test_clear(self):
        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        runner = ABTestRunner("test")
        runner.register_variant(ModelVariant(model_name="m1"))
        runner.register_variant(ModelVariant(model_name="m2"))
        runner.clear()
        assert len(runner.variants) == 0

    def test_select_model_no_variants(self):
        from proxy.app.shared.ab_test import ABTestRunner

        runner = ABTestRunner("empty")
        with pytest.raises(ValueError, match="No model variants"):
            runner.select_model()

    def test_select_model_zero_weight(self):
        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        runner = ABTestRunner("test")
        runner.register_variant(ModelVariant(model_name="m1", weight=0.0))
        v = runner.select_model()
        assert v.model_name == "m1"

    def test_select_model_with_canary_no_variants(self):
        from proxy.app.shared.ab_test import ABTestRunner

        runner = ABTestRunner("empty")
        with pytest.raises(ValueError, match="No model variants"):
            runner.select_model_with_canary("llama")

    def test_select_model_with_canary_no_controller(self):
        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        runner = ABTestRunner("test", canary_controller=None)
        runner.register_variant(ModelVariant(model_name="m1"))
        v = runner.select_model_with_canary("any_model")
        assert v.model_name == "m1"

    def test_select_model_with_canary_no_config(self):
        from unittest.mock import MagicMock

        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        canary = MagicMock()
        canary.route.return_value = "stable"
        canary._configs = {}

        runner = ABTestRunner("test", canary_controller=canary)
        runner.register_variant(ModelVariant(model_name="m1"))
        v = runner.select_model_with_canary("unknown_model")
        assert v.model_name == "m1"

    def test_select_model_with_canary_empty_pool(self):
        from unittest.mock import MagicMock

        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        canary = MagicMock()
        canary.route.return_value = "stable"
        canary._configs = {"llama": MagicMock(stable_version="v2", canary_version="v3")}

        runner = ABTestRunner("test", canary_controller=canary)
        runner.register_variant(ModelVariant(model_name="llama", adapter_version="v1"))
        v = runner.select_model_with_canary("llama")
        assert v is not None

    def test_select_model_with_canary_stable_pool(self):
        from unittest.mock import MagicMock

        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        canary = MagicMock()
        canary.route.return_value = "stable"
        canary._configs = {"llama": MagicMock(stable_version="v1", canary_version="v2")}

        runner = ABTestRunner("test", canary_controller=canary)
        runner.register_variant(ModelVariant(model_name="llama", adapter_version="v1"))
        v = runner.select_model_with_canary("llama")
        assert v.model_name == "llama"

    def test_select_model_with_canary_canary_pool(self):
        from unittest.mock import MagicMock

        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        canary = MagicMock()
        canary.route.return_value = "canary"
        canary._configs = {"llama": MagicMock(stable_version="v1", canary_version="v2")}

        runner = ABTestRunner("test", canary_controller=canary)
        runner.register_variant(ModelVariant(model_name="llama", adapter_version="v2"))
        v = runner.select_model_with_canary("llama")
        assert v.model_name == "llama"

    def test_select_model_with_canary_pool_zero_weight(self):
        from unittest.mock import MagicMock

        from proxy.app.shared.ab_test import ABTestRunner, ModelVariant

        canary = MagicMock()
        canary.route.return_value = "stable"
        canary._configs = {"llama": MagicMock(stable_version="v1", canary_version="v2")}

        runner = ABTestRunner("test", canary_controller=canary)
        runner.register_variant(ModelVariant(model_name="llama", adapter_version="v1", weight=0.0))
        v = runner.select_model_with_canary("llama")
        assert v.model_name == "llama"
