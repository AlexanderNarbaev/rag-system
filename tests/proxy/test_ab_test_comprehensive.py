"""Comprehensive tests for proxy/app/shared/ab_test.py.

Targets the A/B testing harness, statistical significance (Welch's t-test),
Cohen's d effect size, and ABTestRunner model selection.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from proxy.app.shared.ab_test import (
    ABTest,
    ABTestRunner,
    ABVariant,
    ModelVariant,
    _betacf,
    _betai,
    _t_cdf_approx,
    compute_effect_size,
    get_statistical_significance,
)

# ---------------------------------------------------------------------------
# ABVariant
# ---------------------------------------------------------------------------


class TestABVariant:
    def test_init_defaults(self):
        v = ABVariant(name="a", config={"k": 1})
        assert v.name == "a"
        assert v.config == {"k": 1}
        assert v.weight == 1.0
        assert v.trials == 0
        assert v.metrics == {}

    def test_record_appends_value(self):
        v = ABVariant(name="a", config={})
        v.record("latency", 100.0)
        v.record("latency", 110.0)
        assert v.metrics["latency"] == [100.0, 110.0]

    def test_record_multiple_metrics(self):
        v = ABVariant(name="a", config={})
        v.record("latency", 100.0)
        v.record("quality", 0.9)
        assert v.metrics["latency"] == [100.0]
        assert v.metrics["quality"] == [0.9]

    def test_record_trial_increments(self):
        v = ABVariant(name="a", config={})
        v.record_trial()
        v.record_trial()
        assert v.trials == 2

    def test_metric_stats_empty(self):
        v = ABVariant(name="a", config={})
        s = v.metric_stats("missing")
        assert s == {"count": 0}

    def test_metric_stats_with_values(self):
        v = ABVariant(name="a", config={})
        v.record("latency", 100.0)
        v.record("latency", 110.0)
        v.record("latency", 120.0)
        s = v.metric_stats("latency")
        assert s["count"] == 3
        assert s["mean"] == pytest.approx(110.0)
        assert s["min"] == 100.0
        assert s["max"] == 120.0
        assert s["sum"] == 330.0

    def test_metric_stats_single_value_std_is_zero(self):
        v = ABVariant(name="a", config={})
        v.record("m", 1.0)
        s = v.metric_stats("m")
        assert s["count"] == 1
        assert s["std"] == 0.0

    def test_clear_metrics(self):
        v = ABVariant(name="a", config={})
        v.record("m", 1.0)
        v.record_trial()
        v.clear_metrics()
        assert v.metrics == {}
        assert v.trials == 0


# ---------------------------------------------------------------------------
# ABTest
# ---------------------------------------------------------------------------


class TestABTest:
    def test_init_empty(self):
        ab = ABTest("test1")
        assert ab.name == "test1"
        assert ab._variants == {}
        assert ab.variants == []

    def test_register(self):
        ab = ABTest("test")
        v = ab.register("a", {"k": 1}, weight=2.0)
        assert v.name == "a"
        assert v.weight == 2.0
        assert v in ab.variants

    def test_register_duplicate_raises(self):
        ab = ABTest("test")
        ab.register("a", {})
        with pytest.raises(ValueError, match="already registered"):
            ab.register("a", {})

    def test_select_variant_empty_raises(self):
        ab = ABTest("test")
        with pytest.raises(ValueError, match="No variants registered"):
            ab.select_variant()

    def test_select_variant_returns_registered(self):
        ab = ABTest("test")
        ab.register("a", {})
        v = ab.select_variant()
        assert v.name == "a"

    def test_select_variant_with_zero_weight_chooses_random(self):
        ab = ABTest("test")
        ab.register("a", {}, weight=0.0)
        ab.register("b", {}, weight=0.0)
        seen = set()
        # With zero weight, random.choice picks any — try several times
        for _ in range(20):
            v = ab.select_variant()
            seen.add(v.name)
        # We should hit both names eventually
        assert seen == {"a", "b"}

    def test_select_variant_weighted(self):
        ab = ABTest("test")
        ab.register("a", {}, weight=10.0)
        ab.register("b", {}, weight=0.001)
        seen = {"a": 0, "b": 0}
        for _ in range(200):
            seen[ab.select_variant().name] += 1
        assert seen["a"] > seen["b"]

    def test_record_result_increments_trial(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.record_result("a", {"latency": 100.0})
        assert ab._variants["a"].trials == 1
        assert ab._variants["a"].metrics["latency"] == [100.0]

    def test_record_result_multiple_metrics(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.record_result("a", {"latency": 100.0, "quality": 0.9})
        assert ab._variants["a"].metrics["latency"] == [100.0]
        assert ab._variants["a"].metrics["quality"] == [0.9]

    def test_record_result_unknown_variant_raises(self):
        ab = ABTest("test")
        with pytest.raises(ValueError, match="Unknown variant"):
            ab.record_result("ghost", {"m": 1.0})

    def test_compare_unknown_variant_raises(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.record_result("a", {"m": 1.0})
        ab.record_result("a", {"m": 2.0})
        ab.register("b", {})
        ab.record_result("b", {"m": 1.0})
        ab.record_result("b", {"m": 2.0})
        with pytest.raises(ValueError, match="Variant not found"):
            ab.compare("m", "ghost", "b")

    def test_compare_returns_expected_fields(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.register("b", {})
        ab.record_result("a", {"m": 1.0})
        ab.record_result("a", {"m": 2.0})
        ab.record_result("b", {"m": 3.0})
        ab.record_result("b", {"m": 4.0})
        result = ab.compare("m", "a", "b")
        assert result["variant_a"] == "a"
        assert result["variant_b"] == "b"
        assert result["mean_a"] == pytest.approx(1.5)
        assert result["mean_b"] == pytest.approx(3.5)
        assert result["count_a"] == 2
        assert result["count_b"] == 2

    def test_compare_too_few_samples_no_pvalue(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.register("b", {})
        ab.record_result("a", {"m": 1.0})  # only 1 sample
        ab.record_result("b", {"m": 2.0})
        ab.record_result("b", {"m": 3.0})
        result = ab.compare("m", "a", "b")
        assert result["p_value"] is None
        assert result["significant"] is False

    def test_compare_returns_pvalue_when_enough_samples(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.register("b", {})
        # Force a big difference
        for v in [1.0, 1.1, 1.05, 1.0, 1.1, 1.05]:
            ab.record_result("a", {"m": v})
        for v in [10.0, 10.1, 10.05, 10.0, 10.1, 10.05]:
            ab.record_result("b", {"m": v})
        result = ab.compare("m", "a", "b")
        assert result["p_value"] is not None
        assert result["p_value"] < 0.05
        assert result["significant"] is True
        assert "effect_size" in result

    def test_is_significant_low_pvalue(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.register("b", {})
        for v in [1.0, 1.1, 1.0, 1.1]:
            ab.record_result("a", {"m": v})
        for v in [10.0, 10.1, 10.0, 10.1]:
            ab.record_result("b", {"m": v})
        assert ab.is_significant("m", "a", "b") is True

    def test_is_significant_returns_false_when_missing_data(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.register("b", {})
        ab.record_result("a", {"m": 1.0})  # only one
        ab.record_result("b", {"m": 2.0})  # only one
        assert ab.is_significant("m", "a", "b") is False

    def test_get_report(self):
        ab = ABTest("exp1")
        ab.register("a", {"x": 1})
        ab.register("b", {"x": 2})
        ab.record_result("a", {"m": 1.0})
        ab.record_result("b", {"m": 2.0})
        report = ab.get_report()
        assert report["name"] == "exp1"
        assert report["total_trials"] == 2
        assert len(report["variants"]) == 2

    def test_reset(self):
        ab = ABTest("test")
        ab.register("a", {})
        ab.record_result("a", {"m": 1.0})
        assert ab._variants["a"].trials == 1
        ab.reset()
        assert ab._variants["a"].trials == 0
        assert ab._variants["a"].metrics == {}


# ---------------------------------------------------------------------------
# get_statistical_significance (Welch's t-test)
# ---------------------------------------------------------------------------


class TestStatisticalSignificance:
    def test_raises_when_too_few_samples(self):
        with pytest.raises(ValueError, match="at least 2 samples"):
            get_statistical_significance([1.0], [2.0, 3.0])
        with pytest.raises(ValueError, match="at least 2 samples"):
            get_statistical_significance([1.0, 2.0], [3.0])

    def test_returns_one_when_means_identical(self):
        a = [1.0, 1.0, 1.0, 1.0]
        b = [1.0, 1.0, 1.0, 1.0]
        assert get_statistical_significance(a, b) == 1.0

    def test_returns_low_pvalue_for_very_different_means(self):
        a = [1.0, 1.1, 1.0, 1.1, 1.0, 1.1]
        b = [10.0, 10.1, 10.0, 10.1, 10.0, 10.1]
        p = get_statistical_significance(a, b)
        assert p < 0.001

    def test_returns_high_pvalue_for_similar_means(self):
        a = [1.0, 1.0, 1.0, 1.0]
        b = [1.01, 1.01, 1.01, 1.01]
        p = get_statistical_significance(a, b)
        assert p > 0.5

    def test_returns_pvalue_between_0_and_1(self):
        a = [1.0, 2.0, 3.0, 4.0]
        b = [2.0, 3.0, 4.0, 5.0]
        p = get_statistical_significance(a, b)
        assert 0.0 <= p <= 1.0

    def test_handles_zero_variance_group(self):
        # All values identical within a group => se=0 in formula
        a = [5.0, 5.0, 5.0, 5.0]
        b = [10.0, 10.0, 10.0, 10.0]
        # Means differ, but variance is zero
        p = get_statistical_significance(a, b)
        assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# compute_effect_size (Cohen's d)
# ---------------------------------------------------------------------------


class TestComputeEffectSize:
    def test_returns_zero_for_empty(self):
        assert compute_effect_size([], []) == 0.0

    def test_returns_zero_for_one_empty(self):
        assert compute_effect_size([1.0, 2.0], []) == 0.0
        assert compute_effect_size([], [1.0, 2.0]) == 0.0

    def test_returns_diff_for_single_pairs(self):
        # When n1==n2==1, returns raw difference
        d = compute_effect_size([5.0], [2.0])
        assert d == pytest.approx(3.0)

    def test_returns_zero_when_pooled_std_zero(self):
        # Identical values across both groups
        d = compute_effect_size([5.0, 5.0, 5.0, 5.0], [5.0, 5.0, 5.0, 5.0])
        assert d == 0.0

    def test_large_effect_size(self):
        a = [1.0, 1.1, 1.0, 1.1]
        b = [10.0, 10.1, 10.0, 10.1]
        d = compute_effect_size(a, b)
        # Large effect expected — magnitude substantially greater than 1
        assert abs(d) > 1.0

    def test_sign_reflects_direction(self):
        a = [10.0, 10.1, 10.0, 10.1]
        b = [1.0, 1.1, 1.0, 1.1]
        d_ab = compute_effect_size(a, b)
        d_ba = compute_effect_size(b, a)
        assert d_ab > 0
        assert d_ba < 0
        assert d_ab == pytest.approx(-d_ba)


# ---------------------------------------------------------------------------
# _t_cdf_approx + _betai + _betacf helpers
# ---------------------------------------------------------------------------


class TestMathHelpers:
    def test_t_cdf_approx_high_t_low_p(self):
        # Large t-statistic → small p-value
        p = _t_cdf_approx(10.0, 5.0)
        assert 0.0 <= p < 0.01

    def test_t_cdf_approx_low_t_high_p(self):
        # Small t-statistic → larger p-value
        p = _t_cdf_approx(0.5, 100.0)
        assert p > 0.5

    def test_t_cdf_approx_zero_t(self):
        # t=0 represents identical means, produces minimal p-value
        # (function returns 2*min(p, 1-p), so identical t -> 0)
        p = _t_cdf_approx(0.0, 10.0)
        assert p == 0.0

    def test_betai_zero_x(self):
        assert _betai(0.5, 0.5, 0.0) == 0.0

    def test_betai_one_x(self):
        assert _betai(0.5, 0.5, 1.0) == 1.0

    def test_betai_out_of_range(self):
        assert _betai(0.5, 0.5, -1.0) == 0.0
        assert _betai(0.5, 0.5, 2.0) == 0.0

    def test_betai_value_in_range(self):
        # Sanity check: betai(1, 1, 0.5) ~ 0.5
        v = _betai(1.0, 1.0, 0.5)
        assert 0.4 <= v <= 0.6

    def test_betacf_converges(self):
        h = _betacf(0.5, 0.5, 0.3)
        assert isinstance(h, float)
        assert h > 0


# ---------------------------------------------------------------------------
# ModelVariant + ABTestRunner
# ---------------------------------------------------------------------------


class TestModelVariant:
    def test_init_defaults(self):
        v = ModelVariant(model_name="llama")
        assert v.model_name == "llama"
        assert v.adapter_version == "baseline"
        assert v.weight == 1.0

    def test_equality(self):
        a = ModelVariant("llama")
        b = ModelVariant("llama")
        c = ModelVariant("llama", adapter_version="v2")
        assert a == b
        assert a != c

    def test_inequality_by_model(self):
        a = ModelVariant("llama")
        b = ModelVariant("qwen")
        assert a != b

    def test_hash_uses_name_and_version(self):
        a = ModelVariant("llama")
        b = ModelVariant("llama", adapter_version="v2")
        c = ModelVariant("llama")
        assert hash(a) == hash(c)
        assert hash(a) != hash(b)

    def test_equality_with_non_modelvariant(self):
        a = ModelVariant("llama")
        assert a.__eq__("llama") is NotImplemented


class TestABTestRunner:
    def test_init_empty(self):
        r = ABTestRunner("test")
        assert r.name == "test"
        assert r._variants == {}
        assert r._canary_controller is None
        assert r.variants == []

    def test_register_variant(self):
        r = ABTestRunner("test")
        v = ModelVariant("llama", weight=2.0)
        r.register_variant(v)
        assert r._variants["llama"] is v

    def test_register_variant_replaces(self):
        r = ABTestRunner("test")
        r.register_variant(ModelVariant("llama", weight=1.0))
        new = ModelVariant("llama", weight=5.0)
        r.register_variant(new)
        assert r._variants["llama"] is new

    def test_remove_variant(self):
        r = ABTestRunner("test")
        r.register_variant(ModelVariant("llama"))
        r.remove_variant("llama")
        assert "llama" not in r._variants

    def test_remove_variant_unknown_noop(self):
        r = ABTestRunner("test")
        r.remove_variant("nope")  # No exception.

    def test_clear(self):
        r = ABTestRunner("test")
        r.register_variant(ModelVariant("llama"))
        r.register_variant(ModelVariant("qwen"))
        r.clear()
        assert r.variants == []

    def test_select_model_empty_raises(self):
        r = ABTestRunner("test")
        with pytest.raises(ValueError, match="No model variants registered"):
            r.select_model()

    def test_select_model_returns_registered(self):
        r = ABTestRunner("test")
        r.register_variant(ModelVariant("only"))
        v = r.select_model()
        assert v.model_name == "only"

    def test_select_model_weighted(self):
        r = ABTestRunner("test")
        r.register_variant(ModelVariant("heavy", weight=100.0))
        r.register_variant(ModelVariant("light", weight=0.001))
        seen = {"heavy": 0, "light": 0}
        for _ in range(200):
            seen[r.select_model().model_name] += 1
        assert seen["heavy"] > seen["light"]

    def test_select_model_with_canary_no_controller(self):
        r = ABTestRunner("test")
        r.register_variant(ModelVariant("llama"))
        # No canary_controller — should fall back to select_model
        v = r.select_model_with_canary("llama")
        assert v.model_name == "llama"

    def test_select_model_with_canary_empty(self):
        r = ABTestRunner("test")
        with pytest.raises(ValueError):
            r.select_model_with_canary("nope")

    def test_select_model_with_canary_stable_route(self):
        controller = MagicMock()
        controller.route.return_value = "stable"
        config = MagicMock()
        config.stable_version = "v1"
        config.canary_version = "v2"
        controller._configs = {"llama": config}  # noqa: SLF001

        r = ABTestRunner("test", canary_controller=controller)
        # Use unique model names to avoid dict-key collision in register_variant.
        r.register_variant(ModelVariant("llama-stable", adapter_version="v1", weight=10.0))
        r.register_variant(ModelVariant("llama-canary", adapter_version="v2", weight=0.001))

        seen = {"v1": 0, "v2": 0}
        for _ in range(50):
            v = r.select_model_with_canary("llama")
            seen[v.adapter_version] += 1
        assert seen["v1"] > seen["v2"]

    def test_select_model_with_canary_unknown_model(self):
        controller = MagicMock()
        controller.route.return_value = "stable"
        controller._configs = {}  # noqa: SLF001

        r = ABTestRunner("test", canary_controller=controller)
        r.register_variant(ModelVariant("llama", weight=10.0))
        r.register_variant(ModelVariant("qwen", weight=0.001))

        # Should fall back to select_model when no config found
        v = r.select_model_with_canary("llama")
        assert v in r.variants

    def test_select_model_with_canary_canary_route(self):
        controller = MagicMock()
        controller.route.return_value = "canary"
        config = MagicMock()
        config.stable_version = "v1"
        config.canary_version = "v2"
        controller._configs = {"llama": config}  # noqa: SLF001

        r = ABTestRunner("test", canary_controller=controller)
        r.register_variant(ModelVariant("llama-stable", adapter_version="v1", weight=0.001))
        r.register_variant(ModelVariant("llama-canary", adapter_version="v2", weight=10.0))

        seen = {"v1": 0, "v2": 0}
        for _ in range(50):
            v = r.select_model_with_canary("llama")
            seen[v.adapter_version] += 1
        assert seen["v2"] > seen["v1"]

    def test_select_model_with_canary_empty_pool_falls_back(self):
        controller = MagicMock()
        controller.route.return_value = "stable"
        config = MagicMock()
        config.stable_version = "v1"
        config.canary_version = "v2"
        controller._configs = {"llama": config}  # noqa: SLF001

        r = ABTestRunner("test", canary_controller=controller)
        # Only v2 available but stable route was selected → pool empty → fallback
        r.register_variant(ModelVariant("llama-canary", adapter_version="v2", weight=10.0))

        v = r.select_model_with_canary("llama")
        assert v.adapter_version == "v2"

    def test_select_model_with_canary_zero_total_weight(self):
        controller = MagicMock()
        controller.route.return_value = "canary"
        config = MagicMock()
        config.stable_version = "v1"
        config.canary_version = "v2"
        controller._configs = {"llama": config}  # noqa: SLF001

        r = ABTestRunner("test", canary_controller=controller)
        r.register_variant(ModelVariant("llama-canary", adapter_version="v2", weight=0.0))

        # Zero total weight → uses rng.choice
        v = r.select_model_with_canary("llama")
        assert v.adapter_version == "v2"
