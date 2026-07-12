"""Tests for proxy/app/model_evolution/eval_gate.py — EvalGate, MetricThreshold, GateResult."""

from __future__ import annotations

import pytest

from proxy.app.model_evolution.eval_gate import (
    EvalGate,
    EvalGateConfig,
    GateResult,
    GateStatus,
    MetricThreshold,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _threshold(metric: str, value: float, comp: str = "gte", severity: str = "fail") -> MetricThreshold:
    return MetricThreshold(metric_name=metric, threshold=value, comparison=comp, severity=severity)


def _gate_config(
    model: str = "test-model",
    thresholds: list[MetricThreshold] | None = None,
    require_baseline: bool = False,
    tolerance: float = 0.02,
) -> EvalGateConfig:
    return EvalGateConfig(
        model_name=model,
        thresholds=thresholds or [],
        require_baseline_comparison=require_baseline,
        baseline_regression_tolerance=tolerance,
    )


# ── MetricThreshold ──────────────────────────────────────────────────────────


class TestMetricThreshold:
    """Test individual threshold evaluation with all comparison operators."""

    def test_gt_pass(self):
        t = _threshold("score", 0.5, "gt")
        assert t.evaluate(0.6) is True

    def test_gt_fail(self):
        t = _threshold("score", 0.5, "gt")
        assert t.evaluate(0.5) is False

    def test_gte_pass_equal(self):
        t = _threshold("score", 0.5, "gte")
        assert t.evaluate(0.5) is True

    def test_gte_fail(self):
        t = _threshold("score", 0.5, "gte")
        assert t.evaluate(0.49) is False

    def test_lt_pass(self):
        t = _threshold("loss", 0.1, "lt")
        assert t.evaluate(0.05) is True

    def test_lt_fail(self):
        t = _threshold("loss", 0.1, "lt")
        assert t.evaluate(0.1) is False

    def test_lte_pass_equal(self):
        t = _threshold("loss", 0.1, "lte")
        assert t.evaluate(0.1) is True

    def test_lte_fail(self):
        t = _threshold("loss", 0.1, "lte")
        assert t.evaluate(0.11) is False

    def test_unknown_comparison_raises(self):
        t = _threshold("score", 0.5, "neq")
        with pytest.raises(ValueError, match="Unknown comparison"):
            t.evaluate(0.5)


# ── EvalGate.evaluate — PASS ─────────────────────────────────────────────────


class TestEvalGatePass:
    """Test gate evaluation when all metrics pass thresholds."""

    def test_single_threshold_pass(self):
        cfg = _gate_config(thresholds=[_threshold("accuracy", 0.85, "gte")])
        result = EvalGate.evaluate({"accuracy": 0.90}, cfg)
        assert result.status == GateStatus.PASS
        assert result.failures == []
        assert result.warnings == []

    def test_multiple_thresholds_all_pass(self):
        cfg = _gate_config(
            thresholds=[
                _threshold("accuracy", 0.85, "gte"),
                _threshold("loss", 0.1, "lt"),
            ]
        )
        result = EvalGate.evaluate({"accuracy": 0.90, "loss": 0.05}, cfg)
        assert result.status == GateStatus.PASS

    def test_no_thresholds_always_passes(self):
        cfg = _gate_config()
        result = EvalGate.evaluate({"any_metric": 1.0}, cfg)
        assert result.status == GateStatus.PASS

    def test_missing_metric_skipped(self):
        """Metrics not in the data are silently skipped."""
        cfg = _gate_config(thresholds=[_threshold("missing_metric", 0.5, "gte")])
        result = EvalGate.evaluate({"other_metric": 1.0}, cfg)
        assert result.status == GateStatus.PASS


# ── EvalGate.evaluate — FAIL ─────────────────────────────────────────────────


class TestEvalGateFail:
    """Test gate evaluation when metrics fail thresholds."""

    def test_single_threshold_fail(self):
        cfg = _gate_config(thresholds=[_threshold("accuracy", 0.85, "gte")])
        result = EvalGate.evaluate({"accuracy": 0.70}, cfg)
        assert result.status == GateStatus.FAIL
        assert len(result.failures) == 1
        assert "accuracy" in result.failures[0]

    def test_multiple_failures(self):
        cfg = _gate_config(
            thresholds=[
                _threshold("accuracy", 0.85, "gte"),
                _threshold("f1", 0.80, "gte"),
            ]
        )
        result = EvalGate.evaluate({"accuracy": 0.50, "f1": 0.60}, cfg)
        assert result.status == GateStatus.FAIL
        assert len(result.failures) == 2

    def test_fail_overrides_warn(self):
        """FAIL status takes priority over WARN when both are present."""
        cfg = _gate_config(
            thresholds=[
                _threshold("accuracy", 0.85, "gte", severity="fail"),
                _threshold("latency", 100, "lte", severity="warn"),
            ]
        )
        result = EvalGate.evaluate({"accuracy": 0.50, "latency": 200}, cfg)
        assert result.status == GateStatus.FAIL
        assert len(result.failures) == 1
        assert len(result.warnings) == 1


# ── EvalGate.evaluate — WARN ─────────────────────────────────────────────────


class TestEvalGateWarn:
    """Test gate evaluation with warn-only thresholds."""

    def test_warn_only_threshold(self):
        cfg = _gate_config(
            thresholds=[
                _threshold("latency", 100, "lte", severity="warn"),
            ]
        )
        result = EvalGate.evaluate({"latency": 200}, cfg)
        assert result.status == GateStatus.WARN
        assert len(result.warnings) == 1
        assert result.failures == []

    def test_pass_and_warn_mixed(self):
        cfg = _gate_config(
            thresholds=[
                _threshold("accuracy", 0.85, "gte", severity="fail"),
                _threshold("latency", 100, "lte", severity="warn"),
            ]
        )
        result = EvalGate.evaluate({"accuracy": 0.90, "latency": 200}, cfg)
        assert result.status == GateStatus.WARN
        assert result.failures == []
        assert len(result.warnings) == 1


# ── EvalGate.evaluate — Baseline Regression ──────────────────────────────────


class TestEvalGateBaselineRegression:
    """Test baseline regression detection."""

    def test_regression_detected_as_warning(self):
        cfg = _gate_config(
            thresholds=[_threshold("accuracy", 0.80, "gte")],
            tolerance=0.02,
        )
        baseline = {"accuracy": 0.90}
        current = {"accuracy": 0.85}  # regressed by 0.05 > tolerance 0.02
        result = EvalGate.evaluate(current, cfg, baseline_metrics=baseline)
        assert result.status == GateStatus.WARN
        assert any("regressed" in w for w in result.warnings)

    def test_regression_within_tolerance_no_warning(self):
        cfg = _gate_config(
            thresholds=[_threshold("accuracy", 0.80, "gte")],
            tolerance=0.05,
        )
        baseline = {"accuracy": 0.90}
        current = {"accuracy": 0.88}  # regressed by 0.02 < tolerance 0.05
        result = EvalGate.evaluate(current, cfg, baseline_metrics=baseline)
        assert result.status == GateStatus.PASS

    def test_improvement_over_baseline_no_warning(self):
        cfg = _gate_config(
            thresholds=[_threshold("accuracy", 0.80, "gte")],
            tolerance=0.02,
        )
        baseline = {"accuracy": 0.85}
        current = {"accuracy": 0.90}  # improved
        result = EvalGate.evaluate(current, cfg, baseline_metrics=baseline)
        assert result.status == GateStatus.PASS
        assert result.delta_metrics["accuracy"] == pytest.approx(0.05)

    def test_no_baseline_with_require_flag_warns(self):
        cfg = _gate_config(
            thresholds=[_threshold("accuracy", 0.80, "gte")],
            require_baseline=True,
        )
        result = EvalGate.evaluate({"accuracy": 0.90}, cfg, baseline_metrics=None)
        assert result.status == GateStatus.WARN
        assert any("baseline" in w.lower() for w in result.warnings)

    def test_delta_metrics_computed(self):
        cfg = _gate_config(thresholds=[_threshold("accuracy", 0.80, "gte")])
        baseline = {"accuracy": 0.85, "f1": 0.70}
        current = {"accuracy": 0.90, "f1": 0.75}
        result = EvalGate.evaluate(current, cfg, baseline_metrics=baseline)
        assert result.delta_metrics["accuracy"] == pytest.approx(0.05)
        assert result.delta_metrics["f1"] == pytest.approx(0.05)


# ── GateResult ────────────────────────────────────────────────────────────────


class TestGateResult:
    """Test GateResult dataclass defaults and fields."""

    def test_default_values(self):
        r = GateResult()
        assert r.status == GateStatus.PASS
        assert r.model_name == ""
        assert r.version == ""
        assert r.metrics == {}
        assert r.failures == []
        assert r.warnings == []
        assert r.mlflow_run_id is None

    def test_result_populated(self):
        cfg = _gate_config(thresholds=[_threshold("acc", 0.8, "gte")])
        result = EvalGate.evaluate({"acc": 0.9}, cfg, version="v1.0")
        assert result.version == "v1.0"
        assert result.model_name == "test-model"
        assert result.metrics["acc"] == 0.9


# ── EvalGate.from_mlflow_run ─────────────────────────────────────────────────


class TestEvalGateFromMlflow:
    """Test EvalGate.from_mlflow_run static method."""

    def test_sets_mlflow_run_id(self):
        cfg = _gate_config(thresholds=[_threshold("acc", 0.8, "gte")])
        result = EvalGate.from_mlflow_run({"acc": 0.9}, cfg, run_id="run-abc-123")
        assert result.mlflow_run_id == "run-abc-123"
        assert result.version == "run-abc-123"
        assert result.status == GateStatus.PASS

    def test_passes_baseline_through(self):
        cfg = _gate_config(thresholds=[_threshold("acc", 0.8, "gte")], tolerance=0.02)
        result = EvalGate.from_mlflow_run({"acc": 0.85}, cfg, run_id="run-1", baseline_metrics={"acc": 0.90})
        assert result.mlflow_run_id == "run-1"
        assert "regressed" in result.warnings[0]


# ── EvalGate.format_report ───────────────────────────────────────────────────


class TestEvalGateFormatReport:
    """Test report formatting."""

    def test_report_contains_model_and_status(self):
        cfg = _gate_config(thresholds=[_threshold("acc", 0.8, "gte")])
        result = EvalGate.evaluate({"acc": 0.9}, cfg, version="v2")
        report = EvalGate.format_report(result)
        assert "test-model" in report
        assert "PASS" in report
        assert "v2" in report

    def test_report_contains_failures(self):
        cfg = _gate_config(thresholds=[_threshold("acc", 0.95, "gte")])
        result = EvalGate.evaluate({"acc": 0.50}, cfg)
        report = EvalGate.format_report(result)
        assert "FAILURES" in report
        assert "acc" in report

    def test_report_contains_warnings(self):
        cfg = _gate_config(thresholds=[_threshold("lat", 50, "lte", severity="warn")])
        result = EvalGate.evaluate({"lat": 200}, cfg)
        report = EvalGate.format_report(result)
        assert "WARNINGS" in report

    def test_report_contains_deltas(self):
        cfg = _gate_config(thresholds=[_threshold("acc", 0.8, "gte")])
        result = EvalGate.evaluate({"acc": 0.90}, cfg, baseline_metrics={"acc": 0.85})
        report = EvalGate.format_report(result)
        assert "Delta" in report

    def test_report_contains_run_id(self):
        cfg = _gate_config(thresholds=[_threshold("acc", 0.8, "gte")])
        result = EvalGate.from_mlflow_run({"acc": 0.9}, cfg, run_id="run-xyz")
        report = EvalGate.format_report(result)
        assert "run-xyz" in report


# ── EvalGate.is_passing ──────────────────────────────────────────────────────


class TestEvalGateIsPassing:
    """Test is_passing decision logic."""

    def test_pass_is_passing(self):
        r = GateResult(status=GateStatus.PASS)
        assert EvalGate.is_passing(r) is True

    def test_warn_is_passing(self):
        """WARN allows promotion — only FAIL blocks."""
        r = GateResult(status=GateStatus.WARN)
        assert EvalGate.is_passing(r) is True

    def test_fail_is_not_passing(self):
        r = GateResult(status=GateStatus.FAIL)
        assert EvalGate.is_passing(r) is False


# ── GateStatus enum ──────────────────────────────────────────────────────────


class TestGateStatus:
    """Test GateStatus enum values."""

    def test_enum_values(self):
        assert GateStatus.PASS.value == "pass"
        assert GateStatus.FAIL.value == "fail"
        assert GateStatus.WARN.value == "warn"

    def test_all_members(self):
        assert len(GateStatus) == 3


# ── Edge Cases ────────────────────────────────────────────────────────────────


class TestEvalGateEdgeCases:
    """Test boundary conditions and edge cases."""

    def test_empty_metrics(self):
        cfg = _gate_config(thresholds=[_threshold("acc", 0.8, "gte")])
        result = EvalGate.evaluate({}, cfg)
        assert result.status == GateStatus.PASS  # metric missing → skipped

    def test_many_thresholds(self):
        thresholds = [_threshold(f"metric_{i}", 0.5, "gte") for i in range(50)]
        metrics = {f"metric_{i}": 0.6 for i in range(50)}
        cfg = _gate_config(thresholds=thresholds)
        result = EvalGate.evaluate(metrics, cfg)
        assert result.status == GateStatus.PASS

    def test_all_metrics_fail(self):
        thresholds = [_threshold(f"m{i}", 0.9, "gte") for i in range(5)]
        metrics = {f"m{i}": 0.1 for i in range(5)}
        cfg = _gate_config(thresholds=thresholds)
        result = EvalGate.evaluate(metrics, cfg)
        assert result.status == GateStatus.FAIL
        assert len(result.failures) == 5

    def test_version_defaults_to_unknown(self):
        cfg = _gate_config(thresholds=[])
        result = EvalGate.evaluate({}, cfg)
        assert result.version == "unknown"

    def test_version_set_explicitly(self):
        cfg = _gate_config(thresholds=[])
        result = EvalGate.evaluate({}, cfg, version="v3.1.0")
        assert result.version == "v3.1.0"
