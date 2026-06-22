#!/usr/bin/env python3
"""Train SLM intent classifier from HITL data using LoRA fine-tuning.

The script loads intent-labelled query data, configures an SLMTrainer,
runs training, evaluates the result, and optionally registers the model.

Usage:
    # Train with dev profile (CPU, small batch)
    python scripts/model_evolution/train_slm.py --profile dev --data-dir ./data/training

    # Train with prod profile (GPU, full training)
    python scripts/model_evolution/train_slm.py --profile prod --data-dir ./data/training --base-model bert-base-uncased

    # Train with CI profile (smoke test)
    python scripts/model_evolution/train_slm.py --profile ci --data-dir ./data/training

    # Train and register the resulting model
    python scripts/model_evolution/train_slm.py --profile prod --data-dir ./data/training --register
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


def load_intent_dataset(data_path: Path) -> list[dict[str, str]]:
    """Load intent-labelled JSONL dataset."""
    samples: list[dict[str, str]] = []
    if not data_path.exists():
        logger.error("Dataset file not found: %s", data_path)
        return samples

    with open(data_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if "query" in entry and "intent_label" in entry:
                    samples.append(entry)
            except json.JSONDecodeError:
                continue

    logger.info("Loaded %d intent samples from %s", len(samples), data_path)
    return samples


def main() -> None:
    add_package_path()

    from proxy.app.model_evolution.env_profile import get_profile
    from proxy.app.model_evolution.eval_gate import (
        EvalGate,
        EvalGateConfig,
        GateStatus,
        MetricThreshold,
    )
    from proxy.app.model_evolution.slm_trainer import SLMTrainer
    from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig

    parser = argparse.ArgumentParser(
        description="Train SLM intent classifier via LoRA fine-tuning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile", type=str, default="dev",
        choices=["dev", "prod", "ci"],
        help="Training environment profile (default: dev)",
    )
    parser.add_argument(
        "--data-dir", type=str, default="./data/training",
        help="Directory with training datasets (default: ./data/training)",
    )
    parser.add_argument(
        "--base-model", type=str, default="",
        help="Base model name/path (default: bert-base-uncased)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="./models/training",
        help="Output directory for checkpoints and adapters (default: ./models/training)",
    )
    parser.add_argument(
        "--epochs", type=int, default=None,
        help="Override number of training epochs",
    )
    parser.add_argument(
        "--batch-size", type=int, default=None,
        help="Override training batch size",
    )
    parser.add_argument(
        "--learning-rate", type=float, default=None,
        help="Override learning rate",
    )
    parser.add_argument(
        "--lora-r", type=int, default=None,
        help="Override LoRA rank",
    )
    parser.add_argument(
        "--lora-alpha", type=int, default=None,
        help="Override LoRA alpha",
    )
    parser.add_argument(
        "--register", action="store_true",
        help="Register the trained model in the model registry",
    )
    parser.add_argument(
        "--registry-path", type=str, default=None,
        help="Path to model registry JSON (default: from MODEL_REGISTRY_PATH env)",
    )
    parser.add_argument(
        "--skip-eval-gate", action="store_true",
        help="Skip the evaluation gate check after training",
    )

    args = parser.parse_args()

    profile = get_profile(args.profile)
    logger.info("Training profile: %s (epochs=%s)", profile.value, args.epochs or "auto")

    overrides: dict[str, object] = {}
    if args.epochs is not None:
        overrides["epochs"] = args.epochs
    if args.batch_size is not None:
        overrides["batch_size"] = args.batch_size
    if args.learning_rate is not None:
        overrides["learning_rate"] = args.learning_rate
    if args.lora_r is not None:
        overrides["lora_r"] = args.lora_r
    if args.lora_alpha is not None:
        overrides["lora_alpha"] = args.lora_alpha

    config = TrainingConfig.from_profile(TrainerType.SLM, profile, **overrides)
    config.base_model = args.base_model or "bert-base-uncased"
    config.output_dir = args.output_dir

    data_dir = Path(args.data_dir)
    dataset_file = data_dir / "slm_intent.jsonl"
    if not dataset_file.exists():
        logger.error("SLM intent dataset not found at %s", dataset_file)
        logger.info("Generate it with: python scripts/model_evolution/export_dataset.py --slm --output-dir %s",
                     data_dir)
        sys.exit(1)

    samples = load_intent_dataset(dataset_file)
    if not samples:
        logger.error("No valid intent samples found in %s", dataset_file)
        sys.exit(1)

    trainer = SLMTrainer()
    splits = trainer.prepare_data(samples, eval_split=config.eval_split, seed=config.seed)
    logger.info("Data split: %d train, %d eval", len(splits["train"]), len(splits["eval"]))

    # Write split datasets for the trainer to consume
    for split_name, split_data in splits.items():
        split_path = Path(config.output_dir) / f"intent_{split_name}.json"
        split_path.parent.mkdir(parents=True, exist_ok=True)
        split_path.write_text(json.dumps(split_data, indent=2, ensure_ascii=False))

    logger.info("Starting SLM training...")
    try:
        job = trainer.train(config)
    except Exception as exc:
        logger.exception("SLM training failed: %s", exc)
        sys.exit(1)

    if job.status == "failed":
        logger.error("SLM training failed: %s", job.error_message)
        sys.exit(1)

    logger.info("Training completed: job_id=%s status=%s", job.job_id, job.status)
    for metric_name, metric_value in job.metrics.items():
        logger.info("  %s: %.4f", metric_name, metric_value)

    if not args.skip_eval_gate:
        thresholds = [
            MetricThreshold("accuracy", 0.90, "gte", severity="fail"),
            MetricThreshold("weighted_f1", 0.85, "gte", severity="fail"),
        ]
        gate_config = EvalGateConfig(
            model_name="slm-intent-classifier",
            thresholds=thresholds,
            require_baseline_comparison=False,
        )
        gate_result = EvalGate.evaluate(job.metrics, gate_config, version=job.job_id)
        report = EvalGate.format_report(gate_result)
        print("\n" + report)

        if gate_result.status == GateStatus.FAIL:
            logger.error("Eval gate FAILED — model does not meet quality thresholds")
            sys.exit(1)

    if args.register and job.artifact_uri:
        try:
            from proxy.app.model_evolution.model_registry import ModelRegistry
            registry = ModelRegistry(store_path=args.registry_path)
            mv = registry.register(
                name="slm-intent-classifier",
                artifact_path=job.artifact_uri,
                metrics=job.metrics,
            )
            logger.info("Registered as %s v%s → %s", mv.name, mv.version, mv.status)
        except Exception as exc:
            logger.error("Failed to register model: %s", exc)
            sys.exit(1)


if __name__ == "__main__":
    main()
