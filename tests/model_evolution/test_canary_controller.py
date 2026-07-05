"""Tests for proxy/app/model_evolution/canary_controller.py — CanaryController."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from proxy.app.model_evolution.canary_controller import (
    CanaryConfig,
    CanaryController,
    CanaryPhase,
    canary_result_total,
    canary_traffic_total,
    canary_rollback_total,
)


class TestCanaryPhase:
    def test_enum_values(self):
        assert CanaryPhase.IDLE.value == "idle"
        assert CanaryPhase.RAMP_5.value == "ramp_5"
        assert CanaryPhase.RAMP_25.value == "ramp_25"
        assert CanaryPhase.RAMP_50.value == "ramp_50"
        assert CanaryPhase.RAMP_75.value == "ramp_75"
        assert CanaryPhase.FULL.value == "full"
        assert CanaryPhase.ROLLBACK.value == "rollback"


class TestCanaryConfig:
    def test_defaults(self):
        config = CanaryConfig()
        assert config.model_name == ""
        assert config.stable_version == "baseline"
        assert config.canary_version == ""
        assert config.canary_percent == 0.0
        assert config.min_samples == 100
        assert "error_rate" in config.rollback_thresholds
        assert config.cooldown_seconds == 3600

    def test_custom_thresholds(self):
        thresholds: dict[str, tuple[float, str]] = {"latency_p95_ms": (5000.0, "gt")}
        config = CanaryConfig(
            model_name="llm",
            canary_percent=0.1,
            rollback_thresholds=thresholds,
        )
        assert len(config.rollback_thresholds) == 1
        assert config.rollback_thresholds["latency_p95_ms"] == (5000, "gt")


class TestCanaryControllerSetSplit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_set_split_zero_sets_idle(self):
        self.controller.set_split("llm", 0.0)
        assert self.controller.get_phase("llm") == CanaryPhase.IDLE

    def test_set_split_full_sets_full(self):
        self.controller.set_split("llm", 1.0)
        assert self.controller.get_phase("llm") == CanaryPhase.FULL

    def test_set_split_partial(self):
        self.controller.set_split("llm", 0.1)
        phase = self.controller.get_phase("llm")
        assert phase in (CanaryPhase.RAMP_25, CanaryPhase.RAMP_5)

    def test_set_split_sets_gauge(self):
        self.controller.set_split("llm", 0.3)
        stable, canary = self.controller.get_split("llm")
        assert canary == pytest.approx(0.3)
        assert stable == pytest.approx(0.7)

    def test_set_split_out_of_range_raises(self):
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            self.controller.set_split("llm", 1.5)
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            self.controller.set_split("llm", -0.1)


class TestCanaryControllerConfigure:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_configure_sets_all_fields(self):
        self.controller.configure(
            model_name="slm",
            stable_version="v1.0",
            canary_version="v2.0",
            canary_percent=0.15,
            min_samples=200,
            cooldown_seconds=600,
        )
        stable, canary = self.controller.get_split("slm")
        assert canary == pytest.approx(0.15)
        assert stable == pytest.approx(0.85)

    def test_configure_sets_idle_for_zero_percent(self):
        self.controller.configure("llm", canary_percent=0.0)
        assert self.controller.get_phase("llm") == CanaryPhase.IDLE

    def test_configure_sets_full_for_100_percent(self):
        self.controller.configure("llm", canary_percent=1.0)
        assert self.controller.get_phase("llm") == CanaryPhase.FULL


class TestCanaryControllerRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_route_no_config_returns_stable(self):
        result = self.controller.route("unknown-model")
        assert result == "stable"

    def test_route_zero_canary_always_stable(self):
        self.controller.set_split("llm", 0.0)
        results = [self.controller.route("llm") for _ in range(100)]
        assert all(r == "stable" for r in results)

    def test_route_full_canary_always_canary(self):
        self.controller.set_split("llm", 1.0)
        results = [self.controller.route("llm") for _ in range(100)]
        assert all(r == "canary" for r in results)

    def test_route_partial_split_is_weighted(self):
        self.controller.set_split("llm", 0.5)
        results = [self.controller.route("llm") for _ in range(1000)]
        stable_count = sum(1 for r in results if r == "stable")
        canary_count = sum(1 for r in results if r == "canary")
        assert len(results) == 1000
        assert 400 <= canary_count <= 600
        assert 400 <= stable_count <= 600

    def test_route_during_cooldown_returns_stable(self):
        self.controller.configure("llm", canary_percent=0.5)
        self.controller.rollback("llm")
        results = [self.controller.route("llm") for _ in range(100)]
        assert all(r == "stable" for r in results)


class TestCanaryControllerRecordResult:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_record_success_increments_counters(self):
        self.controller.record_result("llm", "canary", success=True)
        self.controller.record_result("llm", "stable", success=False)

        metrics = self.controller.get_metrics("llm")
        assert metrics["total_canary"] >= 1
        assert metrics["total_stable"] >= 1

    def test_record_success_multiple(self):
        for _ in range(10):
            self.controller.record_result("llm", "canary", success=True)
        for _ in range(2):
            self.controller.record_result("llm", "canary", success=False)

        metrics = self.controller.get_metrics("llm")
        assert metrics["total_canary"] == 12
        assert metrics["errors_canary"] == 2
        assert metrics["canary_error_rate"] == pytest.approx(2 / 12)

    def test_record_with_latency(self):
        self.controller.record_result(
            "llm", "canary", success=True, latency_ms=250.0
        )
        metrics = self.controller.get_metrics("llm")
        assert metrics["total_canary"] >= 1

    def test_record_result_no_errors_for_all_success(self):
        for _ in range(20):
            self.controller.record_result("llm", "canary", success=True)

        metrics = self.controller.get_metrics("llm")
        assert metrics["errors_canary"] == 0
        assert metrics["canary_error_rate"] == 0.0
        assert metrics["total_canary"] == 20


class TestCanaryControllerShouldRollback:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_no_config_returns_false(self):
        assert self.controller.should_rollback("unknown") is False

    def test_idle_phase_returns_false(self):
        self.controller.configure("llm", canary_percent=0.0)
        assert self.controller.should_rollback("llm") is False

    def test_full_phase_returns_false(self):
        self.controller.configure("llm", canary_percent=1.0)
        assert self.controller.should_rollback("llm") is False

    def test_below_min_samples_returns_false(self):
        self.controller.configure(
            "llm", canary_percent=0.1, min_samples=100,
        )
        for _ in range(10):
            self.controller.record_result("llm", "canary", success=True)
        assert self.controller.should_rollback("llm") is False

    def test_error_rate_exceeds_threshold_triggers_rollback(self):
        self.controller.configure(
            "llm",
            canary_percent=0.1,
            min_samples=10,
            rollback_thresholds={"error_rate": (0.05, "gt")},
        )
        for _ in range(5):
            self.controller.record_result("llm", "canary", success=True)
        for _ in range(5):
            self.controller.record_result("llm", "canary", success=False)

        assert self.controller.should_rollback("llm") is True

    def test_error_rate_within_threshold_returns_false(self):
        self.controller.configure(
            "llm",
            canary_percent=0.1,
            min_samples=10,
            rollback_thresholds={"error_rate": (0.50, "gt")},
        )
        for _ in range(9):
            self.controller.record_result("llm", "canary", success=True)
        self.controller.record_result("llm", "canary", success=False)

        assert self.controller.should_rollback("llm") is False

    def test_during_cooldown_returns_false(self):
        self.controller.configure("llm", canary_percent=0.1, min_samples=1)
        for _ in range(5):
            self.controller.record_result("llm", "canary", success=False)
        self.controller.rollback("llm")
        assert self.controller.should_rollback("llm") is False


class TestCanaryControllerRollback:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_rollback_sets_zero_canary(self):
        self.controller.configure("llm", canary_percent=0.3)
        self.controller.rollback("llm")
        stable, canary = self.controller.get_split("llm")
        assert canary == 0.0
        assert stable == 1.0

    def test_rollback_sets_phase_to_rollback(self):
        self.controller.configure("llm", canary_percent=0.3)
        self.controller.rollback("llm")
        assert self.controller.get_phase("llm") == CanaryPhase.ROLLBACK

    def test_rollback_starts_cooldown(self):
        self.controller.configure("llm", canary_percent=0.3, cooldown_seconds=60)
        self.controller.rollback("llm")
        status = self.controller.status("llm")
        cooldown = status["llm"]["cooldown_remaining_seconds"]
        assert 0 < cooldown <= 60

    def test_rollback_no_config_creates_default(self):
        self.controller.rollback("unknown")
        assert self.controller.get_phase("unknown") == CanaryPhase.ROLLBACK
        stable, canary = self.controller.get_split("unknown")
        assert canary == 0.0


class TestCanaryControllerPromote:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_promote_sets_full_canary(self):
        self.controller.configure("llm", canary_percent=0.3, canary_version="v2")
        self.controller.promote("llm")
        stable, canary = self.controller.get_split("llm")
        assert canary == 1.0
        assert stable == 0.0

    def test_promote_sets_phase_to_full(self):
        self.controller.configure("llm", canary_percent=0.3, canary_version="v2")
        self.controller.promote("llm")
        assert self.controller.get_phase("llm") == CanaryPhase.FULL

    def test_promote_no_config_is_noop(self):
        self.controller.promote("unknown")
        assert self.controller.get_phase("unknown") == CanaryPhase.IDLE


class TestCanaryControllerStatus:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_status_returns_phase(self):
        self.controller.configure("llm", canary_percent=0.1)
        status = self.controller.status("llm")
        assert "llm" in status
        assert "phase" in status["llm"]
        assert status["llm"]["phase"] == CanaryPhase.RAMP_25.value

    def test_status_returns_split(self):
        self.controller.set_split("llm", 0.3)
        status = self.controller.status("llm")
        split = status["llm"]["split"]
        assert split["canary"] == pytest.approx(0.3)
        assert split["stable"] == pytest.approx(0.7)

    def test_status_returns_versions(self):
        self.controller.configure(
            "llm", stable_version="v1", canary_version="v2",
        )
        status = self.controller.status("llm")
        assert status["llm"]["stable_version"] == "v1"
        assert status["llm"]["canary_version"] == "v2"

    def test_status_returns_metrics(self):
        self.controller.configure("llm", canary_percent=0.1)
        self.controller.record_result("llm", "canary", success=True)
        status = self.controller.status("llm")
        assert "metrics" in status["llm"]
        assert "canary_error_rate" in status["llm"]["metrics"]

    def test_status_all_models(self):
        self.controller.configure("slm", canary_percent=0.1)
        self.controller.configure("llm", canary_percent=0.2)
        status = self.controller.status()
        assert "slm" in status
        assert "llm" in status


class TestCanaryControllerGetSplit:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_default_split_is_stable_only(self):
        stable, canary = self.controller.get_split("unknown")
        assert stable == 1.0
        assert canary == 0.0

    def test_configured_split(self):
        self.controller.set_split("llm", 0.25)
        stable, canary = self.controller.get_split("llm")
        assert stable == pytest.approx(0.75)
        assert canary == pytest.approx(0.25)


class TestCanaryControllerReset:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_reset_specific_model(self):
        self.controller.configure("llm", canary_percent=0.3)
        self.controller.reset("llm")
        stable, canary = self.controller.get_split("llm")
        assert stable == 1.0
        assert canary == 0.0

    def test_reset_all_models(self):
        self.controller.configure("llm", canary_percent=0.3)
        self.controller.configure("slm", canary_percent=0.5)
        self.controller.reset()
        assert self.controller.get_phase("llm") == CanaryPhase.IDLE
        assert self.controller.get_phase("slm") == CanaryPhase.IDLE


class TestCanaryControllerIntegration:
    """End-to-end canary lifecycle: configure → route → record → rollback."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.controller = CanaryController()

    def test_full_lifecycle_with_rollback(self):
        self.controller.configure(
            "llm",
            stable_version="v1",
            canary_version="v2",
            canary_percent=0.5,
            min_samples=10,
            rollback_thresholds={"error_rate": (0.10, "gt")},
        )

        for _ in range(20):
            target = self.controller.route("llm")
            success = target == "stable" or target == "canary"
            self.controller.record_result("llm", target, success=success)

        for _ in range(5):
            self.controller.record_result("llm", "canary", success=False)

        if self.controller.should_rollback("llm"):
            self.controller.rollback("llm")

        status = self.controller.status("llm")
        assert "phase" in status["llm"]
        assert status["llm"]["split"]["stable"] >= 0.0

    def test_promote_after_successful_canary(self):
        self.controller.configure(
            "reranker",
            stable_version="v1",
            canary_version="v2",
            canary_percent=0.5,
            min_samples=10,
        )

        for _ in range(30):
            target = self.controller.route("reranker")
            self.controller.record_result("reranker", target, success=True)

        self.controller.promote("reranker")
        assert self.controller.get_phase("reranker") == CanaryPhase.FULL
        stable, canary = self.controller.get_split("reranker")
        assert canary == 1.0
