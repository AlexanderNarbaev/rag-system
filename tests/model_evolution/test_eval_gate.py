"""Tests for proxy/app/model_evolution/eval_gate.py — EvalGate CI/CD evaluation gate."""

from unittest.mock import patch

import pytest

from proxy.app.model_evolution.eval_gate import (
    EvalGate,
    EvalGateConfig,
    GateResult,
    GateStatus,
    MetricThreshold,
)


class TestGateStatus:
    def test_enum_values(self):
        assert GateStatus.PASS.value == "pass"
        assert GateStatus.FAIL.value == "fail"
        assert GateStatus.WARN.value == "warn"


class TestMetricThreshold:
    def test_gt_comparison_passes(self):
        t = MetricThreshold(metric_name="accuracy", threshold=0.90, comparison="gt")
        assert t.evaluate(0.95) is True
        assert t.evaluate(0.90) is False

    def test_gte_comparison(self):
        t = MetricThreshold(metric_name="f1", threshold=0.85, comparison="gte")
        assert t.evaluate(0.85) is True
        assert t.evaluate(0.90) is True
        assert t.evaluate(0.84) is False

    def test_lt_comparison(self):
        t = MetricThreshold(metric_name="hallucination_rate", threshold=0.05, comparison="lt")
        assert t.evaluate(0.03) is True
        assert t.evaluate(0.05) is False
        assert t.evaluate(0.07) is False

    def test_lte_comparison(self):
        t = MetricThreshold(metric_name="error_rate", threshold=0.10, comparison="lte")
        assert t.evaluate(0.10) is True
        assert t.evaluate(0.05) is True
        assert t.evaluate(0.11) is False

    def test_unknown_comparison_raises(self):
        t = MetricThreshold(metric_name="x", threshold=0.5, comparison="eq")
        with pytest.raises(ValueError, match="Unknown comparison"):
            t.evaluate(0.5)

    def test_default_severity_is_fail(self):
        t = MetricThreshold(metric_name="mrr", threshold=0.80, comparison="gt")
        assert t.severity == "fail"

    def test_warn_severity(self):
        t = MetricThreshold(
            metric_name="bleu",
            threshold=0.30,
            comparison="gte",
            severity="warn",
        )
        assert t.severity == "warn"


class TestGateResult:
    def test_default_status(self):
        result = GateResult(
            model_name="llm-domain-gen",
            version="v2",
            metrics={"rouge_l_f1": 0.42},
            thresholds=[],
        )
        assert result.status == GateStatus.PASS
        assert result.failures == []
        assert result.warnings == []

    def test_passing_result(self):
        result = GateResult(
            status=GateStatus.PASS,
            model_name="slm-intent",
            version="v3",
            metrics={"accuracy": 0.95, "weighted_f1": 0.93},
            thresholds=[
                MetricThreshold("accuracy", 0.90, "gt"),
                MetricThreshold("weighted_f1", 0.85, "gte"),
            ],
        )
        assert result.status == GateStatus.PASS

    def test_failing_result_with_failures(self):
        result = GateResult(
            status=GateStatus.FAIL,
            model_name="reranker-domain",
            version="v2",
            metrics={"mrr": 0.78},
            thresholds=[MetricThreshold("mrr", 0.85, "gt")],
            failures=["MRR 0.78 is not > 0.85"],
        )
        assert result.status == GateStatus.FAIL
        assert len(result.failures) == 1


class TestEvalGateConfig:
    def test_defaults(self):
        config = EvalGateConfig(model_name="test-model")
        assert config.model_name == "test-model"
        assert config.thresholds == []
        assert config.require_baseline_comparison is True
        assert config.baseline_regression_tolerance == 0.02
        assert config.min_eval_samples == 50

    def test_custom_thresholds(self):
        thresholds = [
            MetricThreshold("mrr", 0.80, "gt"),
            MetricThreshold("ndcg@10", 0.75, "gte"),
        ]
        config = EvalGateConfig(
            model_name="reranker",
            thresholds=thresholds,
            require_baseline_comparison=False,
            baseline_regression_tolerance=0.05,
            min_eval_samples=20,
        )
        assert len(config.thresholds) == 2
        assert config.require_baseline_comparison is False
        assert config.baseline_regression_tolerance == 0.05
        assert config.min_eval_samples == 20


class TestEvalGateEvaluate:
    def test_pass_when_all_thresholds_met(self):
        config = EvalGateConfig(
            model_name="slm-intent",
            thresholds=[
                MetricThreshold("accuracy", 0.90, "gt"),
                MetricThreshold("weighted_f1", 0.85, "gte"),
            ],
            require_baseline_comparison=False,
        )
        metrics = {"accuracy": 0.95, "weighted_f1": 0.91}
        result = EvalGate.evaluate(metrics, config)
        assert result.status == GateStatus.PASS
        assert len(result.failures) == 0
        assert len(result.warnings) == 0

    def test_fail_when_fail_severity_threshold_breached(self):
        config = EvalGateConfig(
            model_name="llm-domain-gen",
            thresholds=[
                MetricThreshold("bertscore_f1", 0.70, "gte"),
                MetricThreshold("hallucination_rate", 0.05, "lt", severity="fail"),
            ],
        )
        metrics = {"bertscore_f1": 0.72, "hallucination_rate": 0.12}
        result = EvalGate.evaluate(metrics, config)
        assert result.status == GateStatus.FAIL
        assert len(result.failures) > 0

    def test_warn_when_only_warn_severity_breached(self):
        config = EvalGateConfig(
            model_name="slm-intent",
            thresholds=[
                MetricThreshold("accuracy", 0.90, "gt", severity="fail"),
                MetricThreshold("weighted_f1", 0.85, "gte", severity="warn"),
            ],
        )
        metrics = {"accuracy": 0.93, "weighted_f1": 0.80}
        result = EvalGate.evaluate(metrics, config)
        assert result.status == GateStatus.WARN
        assert len(result.failures) == 0
        assert len(result.warnings) > 0

    def test_pass_when_all_fail_thresholds_pass_and_warn_breached(self):
        """Warn that are breached don't override pass if no fail thresholds breached."""
        config = EvalGateConfig(
            model_name="test",
            thresholds=[
                MetricThreshold("accuracy", 0.90, "gt", severity="fail"),
                MetricThreshold("bleu", 0.50, "gte", severity="warn"),
            ],
        )
        metrics = {"accuracy": 0.95, "bleu": 0.30}
        result = EvalGate.evaluate(metrics, config)
        assert result.status == GateStatus.WARN
        assert len(result.failures) == 0
        assert len(result.warnings) > 0

    def test_missing_metric_ignored_if_no_threshold_for_it(self):
        config = EvalGateConfig(
            model_name="test",
            thresholds=[MetricThreshold("accuracy", 0.90, "gt")],
            require_baseline_comparison=False,
        )
        metrics = {"accuracy": 0.95, "other": 0.50}
        result = EvalGate.evaluate(metrics, config)
        assert result.status == GateStatus.PASS

    def test_returns_all_metrics_in_result(self):
        config = EvalGateConfig(
            model_name="llm",
            thresholds=[MetricThreshold("bertscore_f1", 0.70, "gte")],
        )
        metrics = {"bertscore_f1": 0.78, "rouge_l_f1": 0.42, "bleu_4": 0.35}
        result = EvalGate.evaluate(metrics, config)
        assert result.metrics == metrics

    def test_result_includes_model_name_and_version(self):
        config = EvalGateConfig(model_name="reranker-v2")
        metrics = {"mrr": 0.88}
        result = EvalGate.evaluate(metrics, config, version="v3")
        assert result.model_name == "reranker-v2"
        assert result.version == "v3"

    def test_version_defaults_to_unknown(self):
        config = EvalGateConfig(model_name="test")
        result = EvalGate.evaluate({"mrr": 0.90}, config)
        assert result.version == "unknown"

    def test_result_includes_thresholds(self):
        thresholds = [MetricThreshold("mrr", 0.80, "gt")]
        config = EvalGateConfig(model_name="test", thresholds=thresholds)
        result = EvalGate.evaluate({"mrr": 0.85}, config)
        assert len(result.thresholds) == 1
        assert result.thresholds[0].metric_name == "mrr"


class TestEvalGateBaselineComparison:
    def test_pass_with_baseline_regression_within_tolerance(self):
        config = EvalGateConfig(
            model_name="reranker",
            thresholds=[MetricThreshold("mrr", 0.75, "gte")],
            baseline_regression_tolerance=0.05,
        )
        metrics = {"mrr": 0.80}
        baseline = {"mrr": 0.82}
        result = EvalGate.evaluate(metrics, config, baseline_metrics=baseline)
        assert result.status == GateStatus.PASS

    def test_warn_when_baseline_regression_exceeds_tolerance(self):
        config = EvalGateConfig(
            model_name="reranker",
            thresholds=[MetricThreshold("mrr", 0.75, "gte")],
            baseline_regression_tolerance=0.02,
        )
        metrics = {"mrr": 0.78}
        baseline = {"mrr": 0.82}
        result = EvalGate.evaluate(metrics, config, baseline_metrics=baseline)
        assert result.status == GateStatus.WARN
        assert len(result.failures) == 0
        assert len(result.warnings) > 0

    def test_delta_metrics_computed_from_baseline(self):
        config = EvalGateConfig(
            model_name="test",
            thresholds=[MetricThreshold("mrr", 0.70, "gte")],
        )
        metrics = {"mrr": 0.85, "recall@5": 0.72}
        baseline = {"mrr": 0.80, "recall@5": 0.75}
        result = EvalGate.evaluate(metrics, config, baseline_metrics=baseline)
        assert "mrr" in result.delta_metrics
        assert result.delta_metrics["mrr"] == pytest.approx(0.05)
        assert result.delta_metrics["recall@5"] == pytest.approx(-0.03)
        assert result.baseline_metrics == baseline

    def test_no_baseline_means_no_delta(self):
        config = EvalGateConfig(model_name="test")
        metrics = {"mrr": 0.80}
        result = EvalGate.evaluate(metrics, config)
        assert result.baseline_metrics == {}
        assert result.delta_metrics == {}

    def test_require_baseline_but_none_provided_warns(self):
        config = EvalGateConfig(
            model_name="test",
            thresholds=[MetricThreshold("mrr", 0.75, "gte")],
            require_baseline_comparison=True,
        )
        metrics = {"mrr": 0.85}
        result = EvalGate.evaluate(metrics, config)
        assert result.status == GateStatus.WARN
        assert "baseline" in " ".join(result.warnings).lower()

    def test_require_baseline_false_no_warning(self):
        config = EvalGateConfig(
            model_name="test",
            thresholds=[MetricThreshold("mrr", 0.75, "gte")],
            require_baseline_comparison=False,
        )
        metrics = {"mrr": 0.85}
        result = EvalGate.evaluate(metrics, config)
        assert result.status == GateStatus.PASS


class TestEvalGateIsPassing:
    def test_true_for_pass(self):
        result = GateResult(
            status=GateStatus.PASS,
            model_name="test",
            version="v1",
            metrics={},
            thresholds=[],
        )
        assert EvalGate.is_passing(result) is True

    def test_false_for_fail(self):
        result = GateResult(
            status=GateStatus.FAIL,
            model_name="test",
            version="v1",
            metrics={},
            thresholds=[],
        )
        assert EvalGate.is_passing(result) is False

    def test_true_for_warn(self):
        result = GateResult(
            status=GateStatus.WARN,
            model_name="test",
            version="v1",
            metrics={},
            thresholds=[],
        )
        assert EvalGate.is_passing(result) is True


class TestEvalGateFormatReport:
    def test_report_includes_header(self):
        result = GateResult(
            status=GateStatus.PASS,
            model_name="test-model",
            version="v2",
            metrics={"accuracy": 0.95},
            thresholds=[MetricThreshold("accuracy", 0.90, "gt")],
        )
        report = EvalGate.format_report(result)
        assert "Eval Gate Report" in report
        assert "test-model" in report
        assert "v2" in report
        assert "PASS" in report

    def test_report_includes_metrics_section(self):
        result = GateResult(
            status=GateStatus.PASS,
            model_name="test",
            version="v1",
            metrics={"mrr": 0.88, "recall@5": 0.72},
            thresholds=[],
        )
        report = EvalGate.format_report(result)
        assert "mrr" in report.lower() or "MRR" in report
        assert "0.88" in report

    def test_report_includes_failures_section_when_failed(self):
        result = GateResult(
            status=GateStatus.FAIL,
            model_name="test",
            version="v1",
            metrics={"mrr": 0.70},
            thresholds=[MetricThreshold("mrr", 0.85, "gt")],
            failures=["MRR 0.70 is not > 0.85"],
        )
        report = EvalGate.format_report(result)
        assert "FAILURES" in report.upper() or "Failures" in report
        assert "0.70" in report

    def test_report_includes_delta_when_baseline(self):
        result = GateResult(
            status=GateStatus.PASS,
            model_name="test",
            version="v2",
            metrics={"mrr": 0.85},
            thresholds=[],
            baseline_metrics={"mrr": 0.80},
            delta_metrics={"mrr": 0.05},
        )
        report = EvalGate.format_report(result)
        assert "Delta" in report or "delta" in report.lower() or "+0.05" in report


class TestEvalGateFromMlflowRun:
    def test_reads_metrics_from_tracker(self):
        mock_tracker = object()
        config = EvalGateConfig(
            model_name="test",
            thresholds=[MetricThreshold("accuracy", 0.90, "gt")],
        )

        run_metrics = {"accuracy": 0.95, "loss": 0.1}
        with patch.object(EvalGate, "evaluate", return_value=GateResult(
            status=GateStatus.PASS,
            model_name="test",
            version="mlflow-run-123",
            metrics=run_metrics,
            thresholds=config.thresholds,
        )):
            result = EvalGate.from_mlflow_run(
                run_metrics, config, tracker=mock_tracker, run_id="mlflow-run-123",
            )
            assert result.status == GateStatus.PASS
            assert result.mlflow_run_id == "mlflow-run-123"

    def test_from_mlflow_run_with_baseline(self):
        mock_tracker = object()
        config = EvalGateConfig(
            model_name="test",
            thresholds=[MetricThreshold("mrr", 0.75, "gte")],
        )

        run_metrics = {"mrr": 0.82}
        baseline_metrics = {"mrr": 0.78}
        result = EvalGate.from_mlflow_run(
            run_metrics, config, tracker=mock_tracker,
            run_id="run-1", baseline_metrics=baseline_metrics,
        )
        assert result.mlflow_run_id == "run-1"
        assert result.baseline_metrics == baseline_metrics
