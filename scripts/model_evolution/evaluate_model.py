#!/usr/bin/env python3
"""Run evaluation gate against a model checkpoint or registry entry.

Compares model metrics against configurable thresholds, detects
baseline regression, and produces a pass/fail/warn decision.

Usage:
    # Evaluate with inline metrics
    python scripts/model_evolution/evaluate_model.py --model slm --metrics '{"accuracy": 0.93, "weighted_f1": 0.91}'

    # Evaluate from a metrics JSON file
    python scripts/model_evolution/evaluate_model.py --model llm --metrics-file ./eval_results.json

    # Evaluate against a baseline (regression detection)
    python scripts/model_evolution/evaluate_model.py --model reranker \\
        --metrics-file ./results.json --baseline-file ./baseline.json

    # Evaluate a registered model version
    python scripts/model_evolution/evaluate_model.py --model slm --from-registry --version 3

    # Output report to file
    python scripts/model_evolution/evaluate_model.py --model slm --metrics-file ./results.json --output ./report.txt
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def add_package_path() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


SLM_THRESHOLDS: list[dict[str, object]] = [
    {"metric_name": "accuracy", "threshold": 0.90, "comparison": "gte", "severity": "fail"},
    {"metric_name": "weighted_f1", "threshold": 0.85, "comparison": "gte", "severity": "fail"},
]

LLM_THRESHOLDS: list[dict[str, object]] = [
    {"metric_name": "rouge_l_f1", "threshold": 0.35, "comparison": "gte", "severity": "fail"},
    {"metric_name": "bleu_4", "threshold": 0.10, "comparison": "gte", "severity": "warn"},
    {"metric_name": "bertscore_f1", "threshold": 0.70, "comparison": "gte", "severity": "fail"},
    {"metric_name": "hallucination_rate", "threshold": 0.05, "comparison": "lte", "severity": "fail"},
]

RERANKER_THRESHOLDS: list[dict[str, object]] = [
    {"metric_name": "mrr", "threshold": 0.75, "comparison": "gte", "severity": "fail"},
    {"metric_name": "ndcg_10", "threshold": 0.70, "comparison": "gte", "severity": "fail"},
    {"metric_name": "precision_5", "threshold": 0.65, "comparison": "gte", "severity": "warn"},
]

DEFAULT_THRESHOLDS: dict[str, list[dict[str, object]]] = {
    "slm": SLM_THRESHOLDS,
    "llm": LLM_THRESHOLDS,
    "reranker": RERANKER_THRESHOLDS,
}


def main() -> None:
    add_package_path()

    from proxy.app.model_evolution.eval_gate import (
        EvalGate,
        EvalGateConfig,
        GateStatus,
        MetricThreshold,
    )

    parser = argparse.ArgumentParser(
        description="Run evaluation gate against a model checkpoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model", type=str, required=True,
        choices=["slm", "llm", "reranker"],
        help="Model type to evaluate",
    )
    parser.add_argument(
        "--metrics", type=str, default=None,
        help='Inline metrics dict as JSON string, e.g. \'{"accuracy": 0.93}\'',
    )
    parser.add_argument(
        "--metrics-file", type=str, default=None,
        help="Path to JSON file with metrics",
    )
    parser.add_argument(
        "--baseline-file", type=str, default=None,
        help="Path to JSON file with baseline metrics for regression detection",
    )
    parser.add_argument(
        "--from-registry", action="store_true",
        help="Load metrics from the model registry",
    )
    parser.add_argument(
        "--version", type=str, default=None,
        help="Model version to evaluate (with --from-registry)",
    )
    parser.add_argument(
        "--registry-path", type=str, default=None,
        help="Path to model registry JSON (default: from MODEL_REGISTRY_PATH env)",
    )
    parser.add_argument(
        "--thresholds-file", type=str, default=None,
        help="Path to custom thresholds JSON file",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Save evaluation report to file",
    )
    parser.add_argument(
        "--allow-warn", action="store_true",
        help="Treat WARN status as passing (exit code 0)",
    )
    parser.add_argument(
        "--tolerance", type=float, default=0.02,
        help="Baseline regression tolerance (default: 0.02)",
    )

    args = parser.parse_args()

    metrics: dict[str, float] = {}
    baseline_metrics: dict[str, float] | None = None
    version_str: str = args.version or "unknown"

    if args.from_registry:
        try:
            from proxy.app.model_evolution.model_registry import ModelRegistry
            registry = ModelRegistry(store_path=args.registry_path)
            if args.version:
                mv = registry.get(args.model, args.version)
            else:
                mv = registry.get_latest(args.model)
                if mv is None:
                    logger.error("No versions found for model '%s'", args.model)
                    sys.exit(1)
            metrics = mv.metrics or {}
            version_str = mv.version
            logger.info("Loaded metrics for %s v%s from registry", mv.name, mv.version)
        except (KeyError, ValueError) as exc:
            logger.error("Registry error: %s", exc)
            sys.exit(1)
        except ImportError as exc:
            logger.error("Cannot import model registry: %s", exc)
            sys.exit(1)

    if not metrics and args.metrics:
        try:
            metrics = json.loads(args.metrics)
        except json.JSONDecodeError as exc:
            logger.error("Invalid metrics JSON: %s", exc)
            sys.exit(1)

    if not metrics and args.metrics_file:
        metrics_path = Path(args.metrics_file)
        if not metrics_path.exists():
            logger.error("Metrics file not found: %s", args.metrics_file)
            sys.exit(1)
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Invalid metrics file: %s", exc)
            sys.exit(1)

    if not metrics:
        logger.error("No metrics provided. Use --metrics, --metrics-file, or --from-registry.")
        sys.exit(1)

    if args.baseline_file:
        baseline_path = Path(args.baseline_file)
        if not baseline_path.exists():
            logger.error("Baseline file not found: %s", args.baseline_file)
            sys.exit(1)
        try:
            baseline_metrics = json.loads(baseline_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Invalid baseline file: %s", exc)
            sys.exit(1)

    if args.from_registry:
        try:
            from proxy.app.model_evolution.model_registry import ModelRegistry
            registry = ModelRegistry(store_path=args.registry_path)
            prod_mv = registry.get_latest_production(args.model)
            if prod_mv:
                baseline_metrics = prod_mv.metrics or {}
                logger.info("Using production model v%s as baseline", prod_mv.version)
        except ImportError:
            pass

    thresholds_data = DEFAULT_THRESHOLDS.get(args.model, [])
    if args.thresholds_file:
        thresholds_path = Path(args.thresholds_file)
        if not thresholds_path.exists():
            logger.error("Thresholds file not found: %s", args.thresholds_file)
            sys.exit(1)
        try:
            thresholds_data = json.loads(thresholds_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Invalid thresholds file: %s", exc)
            sys.exit(1)

    thresholds = [
        MetricThreshold(
            metric_name=str(t["metric_name"]),
            threshold=float(str(t["threshold"])),
            comparison=str(t["comparison"]),
            severity=str(t.get("severity", "fail")),
            tolerance=float(str(t.get("tolerance", 0.0))),
        )
        for t in thresholds_data
    ]

    gate_config = EvalGateConfig(
        model_name=args.model,
        thresholds=thresholds,
        require_baseline_comparison=baseline_metrics is not None,
        baseline_regression_tolerance=args.tolerance,
    )

    gate_result = EvalGate.evaluate(
        metrics, gate_config,
        baseline_metrics=baseline_metrics,
        version=version_str,
    )

    report = EvalGate.format_report(gate_result)
    print("\n" + report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report + "\n", encoding="utf-8")
        logger.info("Report saved to %s", args.output)

    if gate_result.status == GateStatus.FAIL:
        logger.error("Eval gate FAILED — model does not meet quality thresholds")
        sys.exit(1)
    elif gate_result.status == GateStatus.WARN and not args.allow_warn:
        logger.warning("Eval gate WARN — review warnings before promotion")
        sys.exit(1)
    else:
        logger.info("Eval gate %s", gate_result.status.value.upper())


if __name__ == "__main__":
    main()
