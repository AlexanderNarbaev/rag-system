"""Tests for proxy/app/model_evolution/canary_controller.py — CanaryController, CanaryConfig, CanaryPhase."""

from __future__ import annotations

import pytest

from proxy.app.model_evolution.canary_controller import (
    CanaryConfig,
    CanaryController,
    CanaryPhase,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def controller() -> CanaryController:
    return CanaryController()


# ── CanaryPhase ───────────────────────────────────────────────────────────────


class TestCanaryPhase:
    """Test CanaryPhase enum values."""

    def test_all_phases_exist(self):
        assert CanaryPhase.IDLE.value == "idle"
        assert CanaryPhase.RAMP_5.value == "ramp_5"
        assert CanaryPhase.RAMP_25.value == "ramp_25"
        assert CanaryPhase.RAMP_50.value == "ramp_50"
        assert CanaryPhase.RAMP_75.value == "ramp_75"
        assert CanaryPhase.FULL.value == "full"
        assert CanaryPhase.ROLLBACK.value == "rollback"

    def test_phase_count(self):
        assert len(CanaryPhase) == 7


# ── CanaryConfig ──────────────────────────────────────────────────────────────


class TestCanaryConfig:
    """Test CanaryConfig dataclass defaults."""

    def test_default_values(self):
        cfg = CanaryConfig()
        assert cfg.model_name == ""
        assert cfg.stable_version == "baseline"
        assert cfg.canary_version == ""
        assert cfg.canary_percent == 0.0
        assert cfg.min_samples == 100
        assert cfg.cooldown_seconds == 3600
        assert "error_rate" in cfg.rollback_thresholds
        assert "p95_latency_ms" in cfg.rollback_thresholds


# ── Traffic Splitting ─────────────────────────────────────────────────────────


class TestCanaryTrafficSplitting:
    """Test set_split, configure, route, get_split."""

    def test_set_split_valid(self, controller):
        controller.set_split("llm", 0.25)
        stable, canary = controller.get_split("llm")
        assert canary == pytest.approx(0.25)
        assert stable == pytest.approx(0.75)

    def test_set_split_zero(self, controller):
        controller.set_split("llm", 0.0)
        stable, canary = controller.get_split("llm")
        assert canary == 0.0
        assert stable == 1.0

    def test_set_split_full(self, controller):
        controller.set_split("llm", 1.0)
        stable, canary = controller.get_split("llm")
        assert canary == 1.0
        assert stable == 0.0

    def test_set_split_out_of_range_raises(self, controller):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            controller.set_split("llm", 1.5)
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            controller.set_split("llm", -0.1)

    def test_get_split_no_config_returns_all_stable(self, controller):
        stable, canary = controller.get_split("nonexistent")
        assert stable == 1.0
        assert canary == 0.0

    def test_configure_sets_split(self, controller):
        controller.configure(
            model_name="llm",
            stable_version="v1",
            canary_version="v2",
            canary_percent=0.10,
        )
        stable, canary = controller.get_split("llm")
        assert canary == pytest.approx(0.10)

    def test_route_no_config_returns_stable(self, controller):
        for _ in range(100):
            assert controller.route("nonexistent") == "stable"

    def test_route_zero_canary_always_stable(self, controller):
        controller.set_split("llm", 0.0)
        for _ in range(100):
            assert controller.route("llm") == "stable"

    def test_route_full_canary_always_canary(self, controller):
        controller.set_split("llm", 1.0)
        for _ in range(100):
            assert controller.route("llm") == "canary"

    def test_route_split_distributes_traffic(self, controller):
        controller.set_split("llm", 0.5)
        results = {"stable": 0, "canary": 0}
        for _ in range(10000):
            results[controller.route("llm")] += 1
        # With 50/50 split and 10k samples, expect ~5000 each (±10%)
        assert 3000 < results["canary"] < 7000
        assert 3000 < results["stable"] < 7000


# ── Phase Tracking ────────────────────────────────────────────────────────────


class TestCanaryPhaseTracking:
    """Test phase inference from split percentage and get_phase."""

    def test_phase_idle_at_zero(self, controller):
        controller.set_split("llm", 0.0)
        assert controller.get_phase("llm") == CanaryPhase.IDLE

    def test_phase_full_at_one(self, controller):
        controller.set_split("llm", 1.0)
        assert controller.get_phase("llm") == CanaryPhase.FULL

    def test_phase_ramp_5(self, controller):
        controller.set_split("llm", 0.03)
        assert controller.get_phase("llm") == CanaryPhase.RAMP_5

    def test_phase_ramp_25(self, controller):
        controller.set_split("llm", 0.10)
        assert controller.get_phase("llm") == CanaryPhase.RAMP_25

    def test_phase_ramp_50(self, controller):
        controller.set_split("llm", 0.40)
        assert controller.get_phase("llm") == CanaryPhase.RAMP_50

    def test_phase_ramp_75(self, controller):
        controller.set_split("llm", 0.60)
        assert controller.get_phase("llm") == CanaryPhase.RAMP_75

    def test_phase_unknown_model_is_idle(self, controller):
        assert controller.get_phase("nonexistent") == CanaryPhase.IDLE

    def test_configure_sets_phase(self, controller):
        controller.configure(model_name="llm", canary_percent=0.40)
        assert controller.get_phase("llm") == CanaryPhase.RAMP_50


# ── Result Recording ──────────────────────────────────────────────────────────


class TestCanaryResultRecording:
    """Test record_result and get_metrics."""

    def test_record_success(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        controller.record_result("llm", "canary", True, latency_ms=50.0)
        metrics = controller.get_metrics("llm")
        assert metrics["total_canary"] == 1
        assert metrics["errors_canary"] == 0
        assert metrics["canary_error_rate"] == 0.0

    def test_record_error(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        controller.record_result("llm", "canary", False, latency_ms=100.0)
        metrics = controller.get_metrics("llm")
        assert metrics["total_canary"] == 1
        assert metrics["errors_canary"] == 1
        assert metrics["canary_error_rate"] == 1.0

    def test_record_mixed_results(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        for _ in range(8):
            controller.record_result("llm", "canary", True)
        for _ in range(2):
            controller.record_result("llm", "canary", False)
        metrics = controller.get_metrics("llm")
        assert metrics["total_canary"] == 10
        assert metrics["errors_canary"] == 2
        assert metrics["canary_error_rate"] == pytest.approx(0.2)

    def test_record_stable_and_canary_independent(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        controller.record_result("llm", "stable", True)
        controller.record_result("llm", "stable", True)
        controller.record_result("llm", "canary", False)
        metrics = controller.get_metrics("llm")
        assert metrics["total_stable"] == 2
        assert metrics["errors_stable"] == 0
        assert metrics["total_canary"] == 1
        assert metrics["errors_canary"] == 1

    def test_get_metrics_no_data(self, controller):
        metrics = controller.get_metrics("llm")
        assert metrics["total_stable"] == 0
        assert metrics["total_canary"] == 0
        assert metrics["stable_error_rate"] == 0.0
        assert metrics["canary_error_rate"] == 0.0


# ── Rollback ──────────────────────────────────────────────────────────────────


class TestCanaryRollback:
    """Test rollback behavior."""

    def test_rollback_sets_zero_split(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        controller.rollback("llm")
        stable, canary = controller.get_split("llm")
        assert canary == 0.0
        assert stable == 1.0

    def test_rollback_sets_phase(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        controller.rollback("llm")
        assert controller.get_phase("llm") == CanaryPhase.ROLLBACK

    def test_rollback_sets_cooldown(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5, cooldown_seconds=60)
        controller.rollback("llm")
        status = controller.status("llm")
        assert status["llm"]["cooldown_remaining_seconds"] > 0

    def test_rollback_on_nonexistent_model_creates_config(self, controller):
        controller.rollback("new-model")
        assert controller.get_phase("new-model") == CanaryPhase.ROLLBACK

    def test_should_rollback_no_config(self, controller):
        assert controller.should_rollback("nonexistent") is False

    def test_should_rollback_idle_phase(self, controller):
        controller.set_split("llm", 0.0)
        assert controller.should_rollback("llm") is False

    def test_should_rollback_full_phase(self, controller):
        controller.set_split("llm", 1.0)
        assert controller.should_rollback("llm") is False

    def test_should_rollback_below_min_samples(self, controller):
        controller.configure(
            model_name="llm",
            canary_percent=0.5,
            min_samples=100,
            rollback_thresholds={"error_rate": (0.05, "gt")},
        )
        # Record only 10 results (below min_samples of 100)
        for _ in range(10):
            controller.record_result("llm", "canary", False)
        assert controller.should_rollback("llm") is False

    def test_should_rollback_high_error_rate(self, controller):
        controller.configure(
            model_name="llm",
            canary_percent=0.5,
            min_samples=10,
            rollback_thresholds={"error_rate": (0.05, "gt")},
        )
        # Record 20 results with 50% error rate
        for _ in range(10):
            controller.record_result("llm", "canary", True)
        for _ in range(10):
            controller.record_result("llm", "canary", False)
        assert controller.should_rollback("llm") is True

    def test_should_rollback_low_error_rate(self, controller):
        controller.configure(
            model_name="llm",
            canary_percent=0.5,
            min_samples=10,
            rollback_thresholds={"error_rate": (0.05, "gt")},
        )
        # Record 100 results with 2% error rate
        for _ in range(98):
            controller.record_result("llm", "canary", True)
        for _ in range(2):
            controller.record_result("llm", "canary", False)
        assert controller.should_rollback("llm") is False

    def test_rollback_during_cooldown_does_not_retrigger(self, controller):
        controller.configure(
            model_name="llm",
            canary_percent=0.5,
            min_samples=5,
            cooldown_seconds=3600,
            rollback_thresholds={"error_rate": (0.01, "gt")},
        )
        for _ in range(10):
            controller.record_result("llm", "canary", False)
        controller.rollback("llm")
        # During cooldown, should_rollback should be False even with bad metrics
        assert controller.should_rollback("llm") is False


# ── Promote ───────────────────────────────────────────────────────────────────


class TestCanaryPromote:
    """Test canary promotion."""

    def test_promote_sets_full_phase(self, controller):
        controller.configure(
            model_name="llm",
            stable_version="v1",
            canary_version="v2",
            canary_percent=0.5,
        )
        controller.promote("llm")
        assert controller.get_phase("llm") == CanaryPhase.FULL

    def test_promote_sets_full_traffic(self, controller):
        controller.configure(
            model_name="llm",
            stable_version="v1",
            canary_version="v2",
            canary_percent=0.5,
        )
        controller.promote("llm")
        stable, canary = controller.get_split("llm")
        assert canary == 1.0

    def test_promote_swaps_versions(self, controller):
        controller.configure(
            model_name="llm",
            stable_version="v1",
            canary_version="v2",
            canary_percent=0.5,
        )
        controller.promote("llm")
        status = controller.status("llm")
        assert status["llm"]["stable_version"] == "v2"
        assert status["llm"]["canary_version"] == ""

    def test_promote_nonexistent_is_noop(self, controller):
        controller.promote("nonexistent")  # Should not raise


# ── Status ────────────────────────────────────────────────────────────────────


class TestCanaryStatus:
    """Test status reporting."""

    def test_status_single_model(self, controller):
        controller.configure(
            model_name="llm",
            stable_version="v1",
            canary_version="v2",
            canary_percent=0.10,
        )
        status = controller.status("llm")
        assert "llm" in status
        assert status["llm"]["phase"] == "ramp_25"
        assert status["llm"]["stable_version"] == "v1"
        assert status["llm"]["canary_version"] == "v2"
        assert status["llm"]["split"]["canary"] == pytest.approx(0.10)
        assert status["llm"]["split"]["stable"] == pytest.approx(0.90)

    def test_status_all_models(self, controller):
        controller.set_split("llm", 0.5)
        controller.set_split("slm", 0.1)
        status = controller.status()
        assert "llm" in status
        assert "slm" in status

    def test_status_nonexistent_returns_empty(self, controller):
        status = controller.status("ghost")
        assert status == {}

    def test_status_includes_metrics(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        controller.record_result("llm", "canary", True)
        status = controller.status("llm")
        assert "metrics" in status["llm"]
        assert status["llm"]["metrics"]["total_canary"] == 1


# ── Reset ─────────────────────────────────────────────────────────────────────


class TestCanaryReset:
    """Test reset functionality."""

    def test_reset_single_model(self, controller):
        controller.set_split("llm", 0.5)
        controller.set_split("slm", 0.1)
        controller.reset("llm")
        assert controller.get_phase("llm") == CanaryPhase.IDLE
        assert controller.get_phase("slm") == CanaryPhase.RAMP_25  # unchanged

    def test_reset_all(self, controller):
        controller.set_split("llm", 0.5)
        controller.set_split("slm", 0.1)
        controller.reset()
        assert controller.get_phase("llm") == CanaryPhase.IDLE
        assert controller.get_phase("slm") == CanaryPhase.IDLE

    def test_reset_clears_stats(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        controller.record_result("llm", "canary", True)
        controller.reset("llm")
        metrics = controller.get_metrics("llm")
        assert metrics["total_canary"] == 0


# ── Edge Cases ────────────────────────────────────────────────────────────────


class TestCanaryEdgeCases:
    """Test boundary conditions."""

    def test_multiple_models_independent(self, controller):
        controller.set_split("llm", 0.5)
        controller.set_split("slm", 0.1)
        assert controller.get_split("llm") == (0.5, 0.5)
        assert controller.get_split("slm") == (0.9, 0.1)

    def test_set_split_updates_existing(self, controller):
        controller.set_split("llm", 0.1)
        assert controller.get_split("llm") == (0.9, 0.1)
        controller.set_split("llm", 0.5)
        assert controller.get_split("llm") == (0.5, 0.5)

    def test_route_after_rollback_goes_to_stable(self, controller):
        controller.configure(
            model_name="llm",
            canary_percent=0.5,
            cooldown_seconds=3600,
        )
        controller.rollback("llm")
        # During cooldown, all traffic should go to stable
        for _ in range(100):
            assert controller.route("llm") == "stable"

    def test_rollback_then_promote(self, controller):
        """After rollback, promoting should work."""
        controller.configure(
            model_name="llm",
            stable_version="v1",
            canary_version="v2",
            canary_percent=0.5,
        )
        controller.rollback("llm")
        controller.promote("llm")
        assert controller.get_phase("llm") == CanaryPhase.FULL

    def test_record_result_zero_latency(self, controller):
        controller.configure(model_name="llm", canary_percent=0.5)
        # Should not crash with zero latency
        controller.record_result("llm", "canary", True, latency_ms=0.0)
        metrics = controller.get_metrics("llm")
        assert metrics["total_canary"] == 1
