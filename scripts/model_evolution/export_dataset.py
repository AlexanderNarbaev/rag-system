#!/usr/bin/env python3
"""Export training datasets from HITL feedback logs.

Produces JSONL files for SLM (intent classification), LLM (domain generation),
and reranker (pairwise relevance) fine-tuning.

Usage:
    # Export all dataset types
    python scripts/model_evolution/export_dataset.py --all --output-dir ./data/training

    # Export only SLM intent dataset
    python scripts/model_evolution/export_dataset.py --slm --output-dir ./data/training

    # Export with custom HITL log directory
    python scripts/model_evolution/export_dataset.py --all --hitl-dir ./logs/hitl --output-dir ./data/training

    # Export with data processor pipeline
    python scripts/model_evolution/export_dataset.py --llm --output-dir ./data/training --use-processor
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def add_package_path() -> None:
    """Ensure the proxy package is importable."""
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


DEFAULT_INTENT_LABELS = [
    "greeting", "simple_fact", "factual", "procedural",
    "comparison", "summarize", "complex",
]


def export_slm_intent_dataset(hitl_dir: str, output_path: Path) -> int:
    """Export SLM intent classification pairs from HITL interactions.

    Each line is a JSON object: {"query": "...", "intent_label": "..."}

    Intent labels are extracted from HITL metadata or inferred via keywords.
    """
    hitl_path = Path(hitl_dir)
    if not hitl_path.exists():
        logger.error("HITL directory not found: %s", hitl_dir)
        return 0

    intent_keywords = {
        "greeting": ("hello", "hi", "hey", "thanks", "good morning"),
        "comparison": ("compare", "difference", "versus", "vs", "better"),
        "summarize": ("summarize", "summary", "tldr", "brief"),
        "procedural": ("how to", "how do i", "steps", "guide"),
        "factual": ("define", "explain", "what is", "who is"),
    }

    def infer_intent(query_text: str) -> str:
        q = query_text.lower()
        for label, keywords in intent_keywords.items():
            if any(kw in q for kw in keywords):
                return label
        if q.count("?") > 1 or q.count(" and ") > 0:
            return "complex"
        return "simple_fact"

    samples: list[dict[str, str]] = []
    seen_queries: set[str] = set()

    for jsonl_file in sorted(hitl_path.glob("*.jsonl")):
        try:
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    query = record.get("user_query") or record.get("query", "")
                    if not query or query in seen_queries:
                        continue
                    seen_queries.add(query)

                    intent = (record.get("metadata", {}).get("intent")
                              or record.get("intent")
                              or infer_intent(query))

                    if intent not in DEFAULT_INTENT_LABELS:
                        continue

                    samples.append({"query": query, "intent_label": intent})
        except OSError as exc:
            logger.warning("Failed to read HITL file %s: %s", jsonl_file, exc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for sample in samples:
            json.dump(sample, f, ensure_ascii=False)
            f.write("\n")

    logger.info("Exported %d SLM intent samples → %s", len(samples), output_path)
    return len(samples)


def export_llm_completion_dataset(hitl_dir: str, output_path: Path, min_length: int = 50) -> int:
    """Export LLM prompt-completion pairs from HITL logs.

    Delegates to hitl.export_training_dataset() for the main logic.
    """
    try:
        from proxy.app.hitl import export_training_dataset
    except ImportError as exc:
        logger.error("Cannot import hitl module: %s", exc)
        return 0

    export_training_dataset(output_path, min_length=min_length, use_processor=False)
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            count = sum(1 for _ in f)
        logger.info("Exported %d LLM completion pairs → %s", count, output_path)
        return count
    return 0


def export_reranker_pairs(hitl_dir: str, output_path: Path) -> int:
    """Export reranker training triples (query, chunk_text, score)."""
    try:
        from proxy.app.rerank import collect_training_pairs
    except ImportError as exc:
        logger.error("Cannot import rerank module: %s", exc)
        return 0

    pairs = collect_training_pairs()
    if not pairs:
        logger.warning("No reranker training pairs collected from HITL logs")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for query, chunk_text, score in pairs:
            json.dump({"query": query, "chunk_text": chunk_text, "score": score}, f, ensure_ascii=False)
            f.write("\n")

    logger.info("Exported %d reranker pairs → %s", len(pairs), output_path)
    return len(pairs)


def export_all(hitl_dir: str, output_dir: Path, min_length: int = 50) -> dict[str, int]:
    """Export all dataset types and return counts."""
    counts: dict[str, int] = {}

    logger.info("Exporting SLM intent dataset...")
    counts["slm"] = export_slm_intent_dataset(hitl_dir, output_dir / "slm_intent.jsonl")

    logger.info("Exporting LLM completion dataset...")
    counts["llm"] = export_llm_completion_dataset(hitl_dir, output_dir / "llm_completion.jsonl", min_length)

    logger.info("Exporting reranker pairs dataset...")
    counts["reranker"] = export_reranker_pairs(hitl_dir, output_dir / "reranker_pairs.jsonl")

    return counts


def main() -> None:
    add_package_path()

    parser = argparse.ArgumentParser(
        description="Export training datasets from HITL feedback logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Export all dataset types (SLM, LLM, reranker)",
    )
    parser.add_argument(
        "--slm", action="store_true",
        help="Export SLM intent classification dataset",
    )
    parser.add_argument(
        "--llm", action="store_true",
        help="Export LLM completion pairs dataset",
    )
    parser.add_argument(
        "--reranker", action="store_true",
        help="Export reranker training pairs dataset",
    )
    parser.add_argument(
        "--hitl-dir", type=str, default="./logs/hitl",
        help="Directory with HITL interaction logs (default: ./logs/hitl)",
    )
    parser.add_argument(
        "--output-dir", type=str, required=True,
        help="Output directory for exported datasets",
    )
    parser.add_argument(
        "--min-length", type=int, default=50,
        help="Minimum completion length for LLM pairs (default: 50)",
    )
    parser.add_argument(
        "--use-processor", action="store_true",
        help="Use DataProcessor pipeline for richer export",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.all or (not args.slm and not args.llm and not args.reranker):
        counts = export_all(args.hitl_dir, output_dir, args.min_length)
        if args.use_processor:
            try:
                from proxy.app.hitl import export_training_dataset
                export_training_dataset(output_dir / "llm_completion_processed.jsonl",
                                       min_length=args.min_length, use_processor=True)
            except ImportError:
                pass
    else:
        counts = {}
        if args.slm:
            counts["slm"] = export_slm_intent_dataset(args.hitl_dir, output_dir / "slm_intent.jsonl")
        if args.llm:
            if args.use_processor:
                try:
                    from proxy.app.hitl import export_training_dataset
                    export_training_dataset(output_dir / "llm_completion.jsonl",
                                           min_length=args.min_length, use_processor=True)
                except ImportError:
                    pass
            counts["llm"] = export_llm_completion_dataset(
                args.hitl_dir, output_dir / "llm_completion.jsonl", args.min_length)
        if args.reranker:
            counts["reranker"] = export_reranker_pairs(args.hitl_dir, output_dir / "reranker_pairs.jsonl")

    total = sum(counts.values())
    if total == 0:
        logger.warning("No training data exported. Check that HITL logs exist at %s", args.hitl_dir)
        sys.exit(1)

    logger.info("Export complete: %d total samples across %d dataset types", total, len(counts))


if __name__ == "__main__":
    main()
