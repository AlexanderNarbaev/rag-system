#!/usr/bin/env python3
"""Export training datasets for the model-evolution pipeline from HITL logs.

Reads interactions and expert feedback from the JSONL logs managed by
``proxy.app.core.hitl.InteractionLogger`` (respecting rotation/backups) and the
optional SQLite feedback database, then produces the six JSON files expected by
the SLM, LLM and reranker trainers.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import random
import sqlite3
import sys
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Allow running the script directly from the scripts/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proxy.app.core.hitl import InteractionLogger, get_logger

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

INTENT_LABELS: list[str] = [
    "greeting",
    "simple_fact",
    "factual",
    "procedural",
    "comparison",
    "summarize",
    "complex",
]
VALID_INTENT_LABELS: set[str] = set(INTENT_LABELS)

# Minimal fixture datasets used when real HITL data is insufficient and fallback
# is enabled. These mirror the previous inline CI fixture and satisfy the
# minimum schema requirements of each trainer.
FALLBACK_INTENT_DATA: list[dict[str, str]] = [
    {"query": "hello team", "intent_label": "greeting"},
    {"query": "how do I deploy via docker?", "intent_label": "procedural"},
    {"query": "compare llama vs mistral for rag", "intent_label": "comparison"},
    {"query": "what is the chunk size for bge-m3?", "intent_label": "factual"},
    {"query": "summarize the deployment guide", "intent_label": "summarize"},
    {"query": "explain how Qdrant hybrid search works and its tradeoffs", "intent_label": "complex"},
    {"query": "hi there", "intent_label": "greeting"},
    {"query": "steps to set up Keycloak OIDC", "intent_label": "procedural"},
    {"query": "compare bge-m3 vs e5-mistral embeddings", "intent_label": "comparison"},
    {"query": "define CRAG evaluator", "intent_label": "factual"},
    {"query": "briefly summarize the roadmap", "intent_label": "summarize"},
    {
        "query": "analyze how the orchestrator handles tool calling and self-reflection loops",
        "intent_label": "complex",
    },
    {"query": "Is the system open source?", "intent_label": "simple_fact"},
]

FALLBACK_RERANKER_DATA: list[list[Any]] = [
    [
        "how to deploy rag system",
        "docker-compose up -d in proxy/ starts all services including Qdrant, Neo4j, Redis, and vLLM",
        1.0,
    ],
    [
        "how to deploy rag system",
        "the system uses Python 3.11 with FastAPI for the proxy layer",
        0.5,
    ],
    [
        "chunk size configuration",
        "BGE-M3 uses 8192 token context with 1024-dim dense embeddings",
        1.0,
    ],
    [
        "chunk size configuration",
        "the default chunk size is 512 tokens with 128 token overlap",
        0.3,
    ],
    [
        "auth setup",
        "Keycloak OIDC integration with JWT token pairs and bcrypt passwords",
        1.0,
    ],
    [
        "auth setup",
        "the proxy runs on port 8080 by default",
        0.1,
    ],
]

SYSTEM_MESSAGE: dict[str, str] = {"role": "system", "content": "You are a RAG system assistant."}
FALLBACK_LLM_DATA: list[dict[str, list[dict[str, str]]]] = [
    {
        "messages": [
            SYSTEM_MESSAGE,
            {"role": "user", "content": "How do I deploy?"},
            {"role": "assistant", "content": "Use docker-compose up -d in the proxy/ directory."},
        ],
    },
    {
        "messages": [
            SYSTEM_MESSAGE,
            {"role": "user", "content": "What embedding model is used?"},
            {
                "role": "assistant",
                "content": "BAAI/bge-m3 with 1024-dim dense embeddings and sparse lexical vectors.",
            },
        ],
    },
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Export model-evolution training datasets from HITL logs.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where the six dataset JSON files will be written.",
    )
    parser.add_argument(
        "--eval-split",
        type=float,
        default=0.2,
        help="Fraction of the dataset to reserve for evaluation (default: 0.2).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for shuffling (default: 42).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=4,
        help="Minimum samples required per split before falling back to fixtures (default: 4).",
    )
    parser.add_argument(
        "--fallback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate minimal fixtures when real data is insufficient (default: True).",
    )
    return parser.parse_args(argv)


def read_jsonl_file(path: Path) -> list[dict[str, Any]]:
    """Read newline-delimited JSON records from a single file."""
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed JSONL line in %s", path)
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
    return records


def read_jsonl_with_rotations(path: Path, max_backups: int = 5) -> list[dict[str, Any]]:
    """Read a JSONL log file plus its rotated backups in chronological order."""
    records: list[dict[str, Any]] = []
    backup_files: list[tuple[int, Path]] = []
    for backup_path in path.parent.glob(f"{path.name}.*"):
        suffix = backup_path.suffix.lstrip(".")
        if suffix.isdigit():
            backup_files.append((int(suffix), backup_path))
    backup_files.sort(key=lambda item: item[0])

    for _suffix, backup_path in backup_files:
        records.extend(read_jsonl_file(backup_path))
    records.extend(read_jsonl_file(path))
    return records


def read_sqlite_feedback(db_path: Path) -> list[dict[str, Any]]:
    """Read feedback records from the optional SQLite feedback database."""
    records: list[dict[str, Any]] = []
    if not db_path.exists():
        return records
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='feedback'")
            if not cursor.fetchone():
                return records

            cursor.execute("PRAGMA table_info(feedback)")
            columns = {row["name"] for row in cursor.fetchall()}
            available = [
                col
                for col in ("request_id", "feedback_type", "comment", "corrected_response", "expert_id", "timestamp")
                if col in columns
            ]
            if not available:
                return records

            cursor.execute(f"SELECT {', '.join(available)} FROM feedback")
            for row in cursor.fetchall():
                records.append({key: row[key] for key in available})
    except sqlite3.Error as exc:
        logger.warning("Could not read feedback database %s: %s", db_path, exc)
    return records


def merge_feedback_into_interactions(
    interactions: list[dict[str, Any]],
    feedback_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Augment interaction records with expert feedback by request_id."""
    by_id: dict[str, dict[str, Any]] = {}
    for item in interactions:
        request_id = item.get("request_id")
        if request_id:
            by_id[request_id] = dict(item)

    for fb in feedback_records:
        request_id = fb.get("request_id")
        if not request_id:
            continue
        item = by_id.setdefault(request_id, {"request_id": request_id})
        if fb.get("corrected_response"):
            item["corrected_response"] = fb["corrected_response"]
        if fb.get("feedback_type"):
            item["user_feedback"] = fb["feedback_type"]

    return list(by_id.values())


def _load_intent_classifier() -> Callable[[str], tuple[Any, float]]:
    """Load the intent classifier configured via ``RAG_INTENT_CLASSIFIER``.

    Defaults to ``proxy.app.llm.slm:classify_intent``. The environment variable
    uses the form ``module.path:function_name``.
    """
    spec = os.getenv("RAG_INTENT_CLASSIFIER", "proxy.app.llm.slm:classify_intent")
    module_name, separator, function_name = spec.partition(":")
    if not separator:
        function_name = "classify_intent"
    module = importlib.import_module(module_name)
    return getattr(module, function_name)  # type: ignore[no-any-return]


def build_intent_dataset(interactions: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build query->intent_label pairs by classifying each user query."""
    classify = _load_intent_classifier()
    dataset: list[dict[str, str]] = []
    for item in interactions:
        query = (item.get("user_query") or "").strip()
        if not query:
            continue
        try:
            intent, _confidence = classify(query)
            label = intent.value
        except Exception as exc:  # noqa: BLE001
            logger.warning("Intent classification failed for query %r: %s", query, exc)
            continue
        if label not in VALID_INTENT_LABELS:
            continue
        dataset.append({"query": query, "intent_label": label})
    return dataset


def build_llm_dataset(interactions: list[dict[str, Any]]) -> list[dict[str, list[dict[str, str]]]]:
    """Build instruction-tuning message lists from positive/corrected interactions."""
    dataset: list[dict[str, list[dict[str, str]]]] = []
    for item in interactions:
        query = (item.get("user_query") or "").strip()
        if not query:
            continue
        corrected = item.get("corrected_response")
        response = item.get("response") or ""
        user_feedback = item.get("user_feedback")
        if not corrected and user_feedback != "positive":
            continue
        answer = corrected if corrected else response
        if not answer:
            continue
        dataset.append(
            {
                "messages": [
                    {"role": "system", "content": "You are a RAG system assistant."},
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": answer},
                ],
            },
        )
    return dataset


def split_chunks(text: str) -> list[str]:
    """Split a context string into candidate chunks."""
    # Try paragraph boundaries first, then fall back to newline splitting.
    separators = ["\n\n", "\n"]
    for sep in separators:
        if sep in text:
            chunks = [chunk.strip() for chunk in text.split(sep) if chunk.strip()]
            return [chunk for chunk in chunks if len(chunk) > 40]
    text = text.strip()
    if text and len(text) > 40:
        return [text]
    return []


def build_reranker_dataset(interactions: list[dict[str, Any]]) -> list[list[Any]]:
    """Build (query, chunk, relevance_score) triples from interaction contexts."""
    dataset: list[list[Any]] = []
    for item in interactions:
        query = (item.get("user_query") or "").strip()
        context = (item.get("context") or "").strip()
        if not query or not context:
            continue
        answer = (item.get("corrected_response") or item.get("response") or "").strip()
        chunks = split_chunks(context)
        if not chunks:
            continue
        if answer:
            positive_index, _best_score = max(
                enumerate(chunks),
                key=lambda idx_chunk: answer.lower() in idx_chunk[1].lower(),
            )
        else:
            positive_index = 0
        for idx, chunk in enumerate(chunks):
            score = 1.0 if idx == positive_index else 0.3
            dataset.append([query, chunk, score])
    return dataset


def _shuffle_split_plain(
    data: list[Any],
    eval_split: float,
    seed: int,
) -> tuple[list[Any], list[Any]]:
    """Shuffle and split a dataset, reserving ``eval_split`` for evaluation."""
    if len(data) < 2:
        return list(data), list(data)
    random.seed(seed)
    shuffled = list(data)
    random.shuffle(shuffled)
    split_idx = max(1, int(len(shuffled) * (1 - eval_split)))
    return shuffled[:split_idx], shuffled[split_idx:]


def _shuffle_split_stratified(
    data: list[Any],
    eval_split: float,
    seed: int,
    key_fn: Any,
) -> tuple[list[Any], list[Any]]:
    """Stratified shuffle split preserving the proportion of each group."""
    if len(data) < 2:
        return list(data), list(data)

    groups: dict[Any, list[Any]] = {}
    for item in data:
        groups.setdefault(key_fn(item), []).append(item)

    train: list[Any] = []
    eval_: list[Any] = []
    rng = random.Random(seed)
    for group in groups.values():
        shuffled = list(group)
        rng.shuffle(shuffled)
        split_idx = max(0, int(len(shuffled) * (1 - eval_split)))
        # Ensure at least one evaluation sample per group when possible.
        if len(shuffled) >= 2 and split_idx >= len(shuffled):
            split_idx = len(shuffled) - 1
        train.extend(shuffled[:split_idx])
        eval_.extend(shuffled[split_idx:])

    # Guarantee a non-empty eval split whenever the overall dataset has >= 2 items.
    if not eval_ and len(data) >= 2:
        eval_.append(train.pop())

    rng.shuffle(train)
    rng.shuffle(eval_)
    return train, eval_


def split_dataset(
    data: list[Any],
    eval_split: float,
    seed: int,
    stratify_key: Any = None,
) -> tuple[list[Any], list[Any]]:
    """Split a dataset, optionally stratifying by a key function."""
    if stratify_key is None:
        return _shuffle_split_plain(data, eval_split, seed)
    return _shuffle_split_stratified(data, eval_split, seed, stratify_key)


def _needs_fallback(train: list[Any], eval_: list[Any], min_samples: int) -> bool:
    """Return True when a split does not meet the minimum sample requirement."""
    return len(train) < min_samples or len(eval_) < min_samples


def _write_json(path: Path, data: Any) -> None:
    """Write JSON data to disk with stable formatting."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def export_datasets(
    output_dir: Path,
    eval_split: float,
    seed: int,
    min_samples: int,
    fallback: bool,
    logger_instance: InteractionLogger,
    feedback_db: Path,
) -> dict[str, bool]:
    """Read HITL logs and write the six trainer dataset files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    interactions = read_jsonl_with_rotations(logger_instance.interactions_file)
    feedback_jsonl = read_jsonl_with_rotations(logger_instance.feedback_file)
    feedback_sqlite = read_sqlite_feedback(feedback_db)
    all_feedback = feedback_jsonl + feedback_sqlite
    merged = merge_feedback_into_interactions(interactions, all_feedback)

    fallback_used: dict[str, bool] = {}

    # Intent dataset
    intent_data = build_intent_dataset(merged)
    intent_train, intent_eval = split_dataset(
        intent_data,
        eval_split,
        seed,
        stratify_key=lambda item: item["intent_label"],
    )
    if _needs_fallback(intent_train, intent_eval, min_samples):
        if not fallback:
            logger.error(
                "Intent dataset has %d train / %d eval samples (min=%d). Use --fallback to write fixtures.",
                len(intent_train),
                len(intent_eval),
                min_samples,
            )
            raise SystemExit(1)
        warnings.warn(
            f"Insufficient intent data ({len(intent_train)} train / {len(intent_eval)} eval); using fallback fixtures.",
            stacklevel=2,
        )
        fallback_used["intent"] = True
        intent_train, intent_eval = split_dataset(
            FALLBACK_INTENT_DATA,
            eval_split,
            seed,
            stratify_key=lambda item: item["intent_label"],
        )
    else:
        fallback_used["intent"] = False

    _write_json(output_dir / "intent_train.json", intent_train)
    _write_json(output_dir / "intent_eval.json", intent_eval)
    logger.info("Intent dataset: %d train / %d eval samples", len(intent_train), len(intent_eval))

    # LLM dataset
    llm_data = build_llm_dataset(merged)
    llm_train, llm_eval = split_dataset(llm_data, eval_split, seed)
    if _needs_fallback(llm_train, llm_eval, min_samples):
        if not fallback:
            logger.error(
                "LLM dataset has %d train / %d eval samples (min=%d). Use --fallback to write fixtures.",
                len(llm_train),
                len(llm_eval),
                min_samples,
            )
            raise SystemExit(1)
        warnings.warn(
            f"Insufficient LLM data ({len(llm_train)} train / {len(llm_eval)} eval); using fallback fixtures.",
            stacklevel=2,
        )
        fallback_used["llm"] = True
        llm_train, llm_eval = split_dataset(FALLBACK_LLM_DATA, eval_split, seed)
    else:
        fallback_used["llm"] = False

    _write_json(output_dir / "llm_train.json", llm_train)
    _write_json(output_dir / "llm_eval.json", llm_eval)
    logger.info("LLM dataset: %d train / %d eval samples", len(llm_train), len(llm_eval))

    # Reranker dataset
    reranker_data = build_reranker_dataset(merged)
    reranker_train, reranker_eval = split_dataset(
        reranker_data,
        eval_split,
        seed,
        stratify_key=lambda item: "positive" if item[2] >= 1.0 else "negative",
    )
    if _needs_fallback(reranker_train, reranker_eval, min_samples):
        if not fallback:
            logger.error(
                "Reranker dataset has %d train / %d eval samples (min=%d). Use --fallback to write fixtures.",
                len(reranker_train),
                len(reranker_eval),
                min_samples,
            )
            raise SystemExit(1)
        warnings.warn(
            f"Insufficient reranker data ({len(reranker_train)} train / {len(reranker_eval)} eval); "
            "using fallback fixtures.",
            stacklevel=2,
        )
        fallback_used["reranker"] = True
        reranker_train, reranker_eval = split_dataset(
            FALLBACK_RERANKER_DATA,
            eval_split,
            seed,
            stratify_key=lambda item: "positive" if item[2] >= 1.0 else "negative",
        )
    else:
        fallback_used["reranker"] = False

    _write_json(output_dir / "reranker_train.json", reranker_train)
    _write_json(output_dir / "reranker_eval.json", reranker_eval)
    logger.info(
        "Reranker dataset: %d train / %d eval samples",
        len(reranker_train),
        len(reranker_eval),
    )

    return fallback_used


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    feedback_db = Path(os.getenv("RAG_FEEDBACK_DB", "data/feedback.db")).resolve()

    logger_instance = get_logger()
    export_datasets(
        output_dir=output_dir,
        eval_split=args.eval_split,
        seed=args.seed,
        min_samples=args.min_samples,
        fallback=args.fallback,
        logger_instance=logger_instance,
        feedback_db=feedback_db,
    )

    print(str(output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
