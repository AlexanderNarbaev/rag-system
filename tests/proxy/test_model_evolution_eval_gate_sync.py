"""Sync tests: proxy and standalone-service eval gates must share logic and API.

``proxy/app/model_evolution/eval_gate.py`` and
``model_evolution_service/evaluation/eval_gate.py`` are two copies of the same
gate. These tests guard against the implementations drifting apart again.
"""

from model_evolution_service.evaluation import eval_gate as service_gate
from proxy.app.model_evolution import eval_gate as proxy_gate

PUBLIC_METHODS = [
    "evaluate",
    "from_mlflow_run",
    "format_report",
    "is_passing",
    "evaluate_with_nli",
    "evaluate_with_ragas",
]

PUBLIC_NAMES = ["EvalGate", "EvalGateConfig", "MetricThreshold", "GateStatus", "GateResult"]


def _scenarios(gate_module):
    """Build equivalent gate scenarios for a given eval_gate module."""
    eval_gate_cls = gate_module.EvalGate
    gate_config_cls = gate_module.EvalGateConfig
    metric_threshold_cls = gate_module.MetricThreshold

    passing = gate_config_cls(
        model_name="m",
        thresholds=[metric_threshold_cls("accuracy", 0.8, "gte", "fail")],
        require_baseline_comparison=False,
    )
    failing = gate_config_cls(
        model_name="m",
        thresholds=[
            metric_threshold_cls("accuracy", 0.9, "gte", "fail"),
            metric_threshold_cls("latency", 100.0, "lte", "warn"),
        ],
        require_baseline_comparison=False,
    )
    regression = gate_config_cls(
        model_name="m",
        thresholds=[metric_threshold_cls("accuracy", 0.5, "gte", "fail")],
        require_baseline_comparison=True,
        baseline_regression_tolerance=0.02,
    )
    return [
        (eval_gate_cls.evaluate({"accuracy": 0.95}, passing, version="v1")),
        (eval_gate_cls.evaluate({"accuracy": 0.95, "latency": 200.0}, failing)),
        (eval_gate_cls.evaluate({"accuracy": 0.80}, failing)),
        (eval_gate_cls.evaluate({"accuracy": 0.90}, regression, baseline_metrics={"accuracy": 0.95})),
        (eval_gate_cls.evaluate({"accuracy": 0.90}, regression, baseline_metrics=None)),
    ]


class TestEvalGateApiParity:
    """Both modules must expose the same public API used by CI workflows."""

    def test_public_names_exist_in_both(self):
        for name in PUBLIC_NAMES:
            assert hasattr(proxy_gate, name), f"proxy gate missing {name}"
            assert hasattr(service_gate, name), f"service gate missing {name}"

    def test_eval_gate_staticmethods_exist_in_both(self):
        for method in PUBLIC_METHODS:
            assert isinstance(proxy_gate.EvalGate.__dict__.get(method), staticmethod), method
            assert isinstance(service_gate.EvalGate.__dict__.get(method), staticmethod), method

    def test_metric_threshold_positional_api(self):
        """MetricThreshold(name, threshold, comparison, severity) — CI workflow contract."""
        for module in (proxy_gate, service_gate):
            threshold = module.MetricThreshold("accuracy", 0.9, "gte", "fail")
            assert threshold.metric_name == "accuracy"
            assert threshold.threshold == 0.9
            assert threshold.comparison == "gte"
            assert threshold.severity == "fail"
            assert threshold.evaluate(0.95) is True
            assert threshold.evaluate(0.85) is False


class TestEvalGateLogicParity:
    """Identical inputs must produce identical gate decisions in both modules."""

    def test_same_decisions(self):
        proxy_results = _scenarios(proxy_gate)
        service_results = _scenarios(service_gate)
        for proxy_result, service_result in zip(proxy_results, service_results, strict=True):
            assert proxy_result.status.value == service_result.status.value
            assert proxy_result.failures == service_result.failures
            assert proxy_result.warnings == service_result.warnings
            assert proxy_result.delta_metrics == service_result.delta_metrics

    def test_format_report_parity(self):
        proxy_result = _scenarios(proxy_gate)[0]
        service_result = _scenarios(service_gate)[0]
        proxy_report = proxy_gate.EvalGate.format_report(proxy_result)
        service_report = service_gate.EvalGate.format_report(service_result)
        assert proxy_report == service_report
