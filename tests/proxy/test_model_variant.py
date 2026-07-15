"""Tests for ModelVariant and ABTestRunner — model variant A/B testing."""

import pytest

from proxy.app.shared.ab_test import (
  ABTestRunner,
  ModelVariant,
)


class TestModelVariant:
  def test_create_with_defaults (self):
    v = ModelVariant (model_name = "llama-3-8b")
    assert v.model_name == "llama-3-8b"
    assert v.adapter_version == "baseline"
    assert v.weight == 1.0

  def test_create_with_all_fields (self):
    v = ModelVariant (model_name = "qwen-2.5-7b", adapter_version = "v2.1", weight = 0.5, )
    assert v.model_name == "qwen-2.5-7b"
    assert v.adapter_version == "v2.1"
    assert v.weight == 0.5

  def test_model_variant_equality (self):
    a = ModelVariant (model_name = "llama-3-8b")
    b = ModelVariant (model_name = "llama-3-8b")
    assert a == b

  def test_model_variant_inequality (self):
    a = ModelVariant (model_name = "llama-3-8b")
    b = ModelVariant (model_name = "qwen-2.5-7b")
    assert a != b

  def test_model_variant_inequality_different_adapter (self):
    a = ModelVariant (model_name = "llama-3-8b", adapter_version = "v1")
    b = ModelVariant (model_name = "llama-3-8b", adapter_version = "v2")
    assert a != b


class TestABTestRunnerSelectModel:
  def test_single_variant_default (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "llama-3-8b"))
    selected = runner.select_model ()
    assert selected == ModelVariant (model_name = "llama-3-8b")

  def test_weighted_selection_zero_weight_excluded (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "llama-3-8b", weight = 0.0))
    runner.register_variant (ModelVariant (model_name = "qwen-2.5-7b", weight = 1.0))
    for _ in range (30):
      selected = runner.select_model ()
      assert selected.model_name == "qwen-2.5-7b"

  def test_weighted_selection_distribution (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "a", weight = 0.9))
    runner.register_variant (ModelVariant (model_name = "b", weight = 0.1))
    counts = {"a": 0, "b": 0}
    for _ in range (1000):
      selected = runner.select_model ()
      counts [selected.model_name] += 1
    assert counts ["a"] > counts ["b"]
    assert counts ["a"] > 700  # roughly 90%
    assert counts ["b"] > 20  # roughly 10%

  def test_select_model_returns_model_variant (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "llama-3-8b"))
    selected = runner.select_model ()
    assert isinstance (selected, ModelVariant)
    assert selected.model_name == "llama-3-8b"
    assert selected.adapter_version == "baseline"

  def test_no_variants_raises (self):
    runner = ABTestRunner (name = "llm_test")
    with pytest.raises (ValueError, match = "No model variants"):
      runner.select_model ()


class TestABTestRunnerRegistration:
  def test_register_multiple_variants (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "a"))
    runner.register_variant (ModelVariant (model_name = "b"))
    runner.register_variant (ModelVariant (model_name = "c"))
    assert len (runner.variants) == 3

  def test_register_duplicate_replace (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "a", weight = 0.5))
    runner.register_variant (ModelVariant (model_name = "a", adapter_version = "v2", weight = 1.0))
    variants = runner.variants
    assert len (variants) == 1
    assert variants [0].adapter_version == "v2"
    assert variants [0].weight == 1.0

  def test_remove_variant (self):
    runner = ABTestRunner (name = "llm_test")
    v = ModelVariant (model_name = "a")
    runner.register_variant (v)
    runner.register_variant (ModelVariant (model_name = "b"))
    runner.remove_variant ("a")
    assert len (runner.variants) == 1
    assert runner.variants [0].model_name == "b"

  def test_remove_nonexistent_variant_no_error (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "a"))
    runner.remove_variant ("nonexistent")
    assert len (runner.variants) == 1

  def test_clear_all_variants (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "a"))
    runner.register_variant (ModelVariant (model_name = "b"))
    runner.clear ()
    assert len (runner.variants) == 0
    with pytest.raises (ValueError):
      runner.select_model ()


class TestABTestRunnerCanaryIntegration:
  def test_select_model_with_canary_stable (self):
    from proxy.app.model_evolution.canary_controller import CanaryController

    controller = CanaryController ()
    controller.configure ("llm", stable_version = "v1", canary_version = "v2", canary_percent = 0.0)

    runner = ABTestRunner (name = "llm_test", canary_controller = controller)
    runner.register_variant (ModelVariant (model_name = "stable-llm", adapter_version = "v1", weight = 1.0))
    runner.register_variant (ModelVariant (model_name = "canary-llm", adapter_version = "v2", weight = 1.0))

    for _ in range (20):
      selected = runner.select_model_with_canary (model_name = "llm")
      assert selected.model_name == "stable-llm"

  def test_select_model_with_canary_full_canary (self):
    from proxy.app.model_evolution.canary_controller import CanaryController

    controller = CanaryController ()
    controller.configure ("llm", stable_version = "v1", canary_version = "v2", canary_percent = 1.0)

    runner = ABTestRunner (name = "llm_test", canary_controller = controller)
    runner.register_variant (ModelVariant (model_name = "stable-llm", adapter_version = "v1", weight = 1.0))
    runner.register_variant (ModelVariant (model_name = "canary-llm", adapter_version = "v2", weight = 1.0))

    for _ in range (20):
      selected = runner.select_model_with_canary (model_name = "llm")
      assert selected.model_name == "canary-llm"

  def test_select_model_with_canary_no_variant_fallback (self):
    from proxy.app.model_evolution.canary_controller import CanaryController

    controller = CanaryController ()
    controller.configure ("llm", stable_version = "v1", canary_percent = 0.0)

    runner = ABTestRunner (name = "llm_test", canary_controller = controller)
    runner.register_variant (ModelVariant (model_name = "default-llm", adapter_version = "v1"))

    selected = runner.select_model_with_canary (model_name = "llm")
    assert selected.model_name == "default-llm"

  def test_select_model_with_canary_no_controller_fallback (self):
    runner = ABTestRunner (name = "llm_test")
    runner.register_variant (ModelVariant (model_name = "llama-3-8b"))
    runner.register_variant (ModelVariant (model_name = "qwen-2.5-7b"))
    selected = runner.select_model_with_canary (model_name = "llm")
    assert selected in runner.variants

  def test_select_model_with_canary_respects_weights_within_canary_pool (self):
    from proxy.app.model_evolution.canary_controller import CanaryController

    controller = CanaryController ()
    controller.configure ("slm", stable_version = "v1", canary_version = "v3", canary_percent = 0.5)

    runner = ABTestRunner (name = "slm_test", canary_controller = controller)
    runner.register_variant (ModelVariant (model_name = "stable-slm-a", adapter_version = "v1", weight = 0.2))
    runner.register_variant (ModelVariant (model_name = "stable-slm-b", adapter_version = "v1", weight = 0.8))
    runner.register_variant (ModelVariant (model_name = "canary-slm", adapter_version = "v3", weight = 1.0))

    counts: dict [str, int] = {}
    for _ in range (500):
      selected = runner.select_model_with_canary (model_name = "slm")
      counts [selected.model_name] = counts.get (selected.model_name, 0) + 1

    # Both stable variants should be reachable
    assert counts.get ("stable-slm-a", 0) > 0
    assert counts.get ("stable-slm-b", 0) > 0
    assert counts.get ("canary-slm", 0) > 0
    # stable-slm-b should appear more often than stable-slm-a
    assert counts.get ("stable-slm-b", 0) > counts.get ("stable-slm-a", 0)
