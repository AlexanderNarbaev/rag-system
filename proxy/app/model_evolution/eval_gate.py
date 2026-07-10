"""CI/CD evaluation gate for model promotion decisions.

Reads metrics, compares against configurable thresholds, detects
baseline regression, and produces pass/fail/warn decisions.
Includes NLI-based answer grounding evaluation via nli_evaluator module.

Integrates with ExperimentTracker for MLflow run context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class GateStatus(Enum):
    """Outcome of an evaluation gate run."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class MetricThreshold:
    """A single metric threshold with comparison operator and severity."""

    metric_name: str
    threshold: float
    comparison: str  # "gt", "gte", "lt", "lte"
    severity: str = "fail"  # "fail" or "warn"
    tolerance: float = 0.0  # Relative tolerance for "warn" status

    _COMPARATORS = {
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
    }

    def evaluate(self, value: float) -> bool:
        """Return True if the value passes this threshold."""
        comparator = self._COMPARATORS.get(self.comparison)
        if comparator is None:
            raise ValueError(f"Unknown comparison {self.comparison!r}")
        return comparator(value, self.threshold)


@dataclass
class GateResult:
    """Result of an evaluation gate run."""

    status: GateStatus = GateStatus.PASS
    model_name: str = ""
    version: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    thresholds: list[MetricThreshold] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    delta_metrics: dict[str, float] = field(default_factory=dict)
    mlflow_run_id: str | None = None
    report_path: str | None = None


@dataclass
class EvalGateConfig:
    """Configuration for an evaluation gate."""

    model_name: str
    thresholds: list[MetricThreshold] = field(default_factory=list)
    require_baseline_comparison: bool = True
    baseline_regression_tolerance: float = 0.02
    min_eval_samples: int = 50


class EvalGate:
    """CI/CD evaluation gate for model promotion decisions.

    Reads metrics, compares against configurable thresholds, detects
    baseline regression, and produces a pass/fail/warn decision.
    """

    @staticmethod
    def evaluate(
        metrics: dict[str, float],
        config: EvalGateConfig,
        baseline_metrics: dict[str, float] | None = None,
        version: str | None = None,
    ) -> GateResult:
        """Evaluate metrics against thresholds and optional baseline.

        Args:
            metrics: Current model evaluation metrics.
            config: EvalGateConfig with thresholds.
            baseline_metrics: Optional baseline metrics for regression detection.
            version: Model version string.

        Returns:
            GateResult with pass/fail/warn status and details.
        """
        failures: list[str] = []
        warnings: list[str] = []

        for threshold in config.thresholds:
            value = metrics.get(threshold.metric_name)
            if value is None:
                continue

            passed = threshold.evaluate(value)
            if not passed:
                message = f"{threshold.metric_name} {value} is not {threshold.comparison} {threshold.threshold}"
                if threshold.severity == "fail":
                    failures.append(message)
                else:
                    warnings.append(message)

        delta_metrics: dict[str, float] = {}
        if baseline_metrics:
            for key in metrics:
                if key in baseline_metrics:
                    delta_metrics[key] = metrics[key] - baseline_metrics[key]

            if config.baseline_regression_tolerance > 0:
                for threshold in config.thresholds:
                    if threshold.severity != "fail":
                        continue
                    if threshold.metric_name not in delta_metrics:
                        continue
                    delta = delta_metrics[threshold.metric_name]
                    if delta < -config.baseline_regression_tolerance:
                        warnings.append(
                            f"{threshold.metric_name} regressed by {abs(delta):.4f} "
                            f"(tolerance: {config.baseline_regression_tolerance})"
                        )
        elif config.require_baseline_comparison:
            warnings.append("No baseline metrics provided for comparison")

        if failures:
            status = GateStatus.FAIL
        elif warnings:
            status = GateStatus.WARN
        else:
            status = GateStatus.PASS

        return GateResult(
            status=status,
            model_name=config.model_name,
            version=version or "unknown",
            metrics=metrics,
            thresholds=config.thresholds,
            failures=failures,
            warnings=warnings,
            baseline_metrics=baseline_metrics or {},
            delta_metrics=delta_metrics,
        )

    @staticmethod
    def from_mlflow_run(
        metrics: dict[str, float],
        config: EvalGateConfig,
        tracker: Any = None,
        run_id: str | None = None,
        baseline_metrics: dict[str, float] | None = None,
    ) -> GateResult:
        """Create a GateResult from an MLflow run's metrics.

        Args:
            metrics: Metrics from the MLflow run.
            config: EvalGateConfig with thresholds.
            tracker: ExperimentTracker instance (logged with result for traceability).
            run_id: MLflow run ID.
            baseline_metrics: Optional baseline metrics.

        Returns:
            GateResult with pass/fail/warn status.
        """
        result = EvalGate.evaluate(
            metrics,
            config,
            baseline_metrics=baseline_metrics,
            version=run_id,
        )
        result.mlflow_run_id = run_id
        return result

    @staticmethod
    def format_report(result: GateResult) -> str:
        """Format a GateResult as a human-readable report string.

        Args:
            result: GateResult to format.

        Returns:
            Multi-line report string.
        """
        lines = [
            "=" * 60,
            "Eval Gate Report",
            "=" * 60,
            f"Model:    {result.model_name}",
            f"Version:  {result.version}",
            f"Status:   {result.status.value.upper()}",
        ]

        if result.mlflow_run_id:
            lines.append(f"Run ID:   {result.mlflow_run_id}")

        lines.append("")
        lines.append("-" * 60)
        lines.append("Metrics")
        lines.append("-" * 60)
        for name, value in sorted(result.metrics.items()):
            delta_str = ""
            if name in result.delta_metrics:
                d = result.delta_metrics[name]
                sign = "+" if d >= 0 else ""
                delta_str = f"  (Δ{sign}{d:.4f})"
            lines.append(f"  {name}: {value:.4f}{delta_str}")

        if result.thresholds:
            lines.append("")
            lines.append("-" * 60)
            lines.append("Thresholds")
            lines.append("-" * 60)
            for t in result.thresholds:
                value = result.metrics.get(t.metric_name)
                passed = t.evaluate(value) if value is not None else None
                status_mark = "PASS" if passed else ("FAIL" if passed is False else "N/A")
                lines.append(f"  {t.metric_name} {t.comparison} {t.threshold} [{status_mark}] ({t.severity})")

        if result.failures:
            lines.append("")
            lines.append("-" * 60)
            lines.append("FAILURES")
            lines.append("-" * 60)
            for f in result.failures:
                lines.append(f"  * {f}")

        if result.warnings:
            lines.append("")
            lines.append("-" * 60)
            lines.append("WARNINGS")
            lines.append("-" * 60)
            for w in result.warnings:
                lines.append(f"  ! {w}")

        if result.delta_metrics:
            lines.append("")
            lines.append("-" * 60)
            lines.append("Delta from Baseline")
            lines.append("-" * 60)
            for name, delta in sorted(result.delta_metrics.items()):
                sign = "+" if delta >= 0 else ""
                lines.append(f"  {name}: {sign}{delta:.4f}")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    @staticmethod
    def is_passing(result: GateResult) -> bool:
        """Return True if the gate result allows promotion (PASS or WARN).

        Only FAIL blocks promotion.
        """
        return result.status != GateStatus.FAIL

    @staticmethod
    def evaluate_with_nli(
        metrics: dict[str, float],
        config: EvalGateConfig,
        answer_context_pairs: list[tuple[str, str]] | None = None,
        baseline_metrics: dict[str, float] | None = None,
        version: str | None = None,
        use_real_nli: bool = True,
    ) -> GateResult:
        """Evaluate metrics + NLI grounding against thresholds and baseline.

        Args:
            metrics: Current model evaluation metrics.
            config: EvalGateConfig with thresholds.
            answer_context_pairs: Optional list of (answer, context) pairs for NLI scoring.
            baseline_metrics: Optional baseline metrics for regression detection.
            version: Model version string.
            use_real_nli: Whether to attempt real NLI model (falls back to proxy otherwise).

        Returns:
            GateResult with pass/fail/warn status including NLI metrics.
        """
        from proxy.app.model_evolution.nli_evaluator import evaluate_nli_batch

        if answer_context_pairs:
            nli_metrics = evaluate_nli_batch(answer_context_pairs, use_real_nli=use_real_nli)
            metrics = {**metrics, **nli_metrics}

        return EvalGate.evaluate(
            metrics,
            config,
            baseline_metrics=baseline_metrics,
            version=version,
        )
