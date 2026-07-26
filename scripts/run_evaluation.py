#!/usr/bin/env python3
"""Run retrieval evaluation pipeline against a labeled dataset.

Usage:
    python scripts/run_evaluation.py --dataset data/eval_dataset.json --output results/
    python scripts/run_evaluation.py --dataset data/eval_dataset.json --top-k 10
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Make `proxy` importable when invoked as a plain script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proxy.app.core.evaluation import RetrievalEvaluator  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run retrieval evaluation against a labeled dataset",
    )
    parser.add_argument("--dataset", required=True, help="Path to eval dataset JSON")
    parser.add_argument(
        "--output",
        default="results/",
        help="Output directory (default: results/)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=20,
        help="Number of chunks to consider for ranked metrics (default: 20)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        logger.error("Dataset not found: %s", dataset_path)
        return 1

    with open(dataset_path, encoding="utf-8") as fh:
        dataset = json.load(fh)
    if not isinstance(dataset, list):
        logger.error("Expected a JSON array of {query, relevant_docs} records, got %s", type(dataset).__name__)
        return 1

    logger.info("Loaded %d eval records from %s", len(dataset), dataset_path)

    evaluator = RetrievalEvaluator()
    results = evaluator.evaluate_dataset(dataset, top_k=args.top_k)

    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    metrics_file = output_path / "metrics.json"
    with open(metrics_file, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    logger.info("Wrote metrics to %s", metrics_file)

    # Print a compact summary
    print()
    print("Retrieval Evaluation Results")
    print("=" * 40)
    print(f"  Queries evaluated: {results['num_queries']}")
    print(f"  MRR:               {results['mrr']:.3f}")
    for k, v in sorted(results["recall_at_k"].items()):
        print(f"  Recall@{k:<2}:          {v:.3f}")
    for k, v in sorted(results["ndcg_at_k"].items()):
        print(f"  nDCG@{k:<2}:            {v:.3f}")
    for k, v in sorted(results["precision_at_k"].items()):
        print(f"  Precision@{k:<2}:       {v:.3f}")
    print("=" * 40)
    return 0


if __name__ == "__main__":
    sys.exit(main())
