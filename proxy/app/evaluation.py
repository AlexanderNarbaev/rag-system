# proxy/app/evaluation.py
"""
Retrieval evaluation pipeline for RAG system.

Computes standard IR metrics:
- MRR (Mean Reciprocal Rank)
- Recall@k (k=5, 10, 20)
- nDCG@k (k=5, 10)
- Precision@k (k=5)

Used by scripts/evaluate_retrieval.py and optionally in CI pipelines.
"""

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


def compute_mrr(retrieved_lists: list[list[str]], relevant_sets: list[set[str]]) -> float:
    """Compute MRR (Mean Reciprocal Rank) over all queries."""
    if not retrieved_lists:
        return 0.0

    rr_sum = 0.0
    query_count = 0
    for retrieved, relevant in zip(retrieved_lists, relevant_sets, strict=False):
        if not relevant:
            continue
        query_count += 1
        for rank, doc in enumerate(retrieved, start=1):
            if doc in relevant:
                rr_sum += 1.0 / rank
                break

    return rr_sum / query_count if query_count > 0 else 0.0


def compute_recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Compute Recall@k."""
    if not relevant:
        return 1.0
    retrieved_k = set(retrieved[:k])
    hits = len(retrieved_k & relevant)
    return hits / len(relevant)


def compute_ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Compute nDCG@k with binary relevance."""
    if not relevant:
        return 1.0

    binary_relevance = [1.0 if doc in relevant else 0.0 for doc in retrieved[:k]]
    ideal_relevance = sorted([1.0] * min(len(relevant), k) + [0.0] * max(0, k - len(relevant)), reverse=True)

    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(binary_relevance[:k]))
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_relevance[:k]))

    return dcg / idcg if idcg > 0 else 0.0


def compute_precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Compute Precision@k."""
    if not retrieved:
        return 0.0
    retrieved_k = set(retrieved[:k])
    hits = len(retrieved_k & relevant)
    return hits / k if k > 0 else 0.0


def compute_all_metrics(
    retrieved_lists: list[list[str]],
    relevant_sets: list[set[str]],
) -> dict[str, float]:
    """Compute all evaluation metrics for a set of queries.

    Args:
        retrieved_lists: List of retrieved document IDs per query.
        relevant_sets: List of relevant document ID sets per query.

    Returns:
        Dictionary with MRR, Recall@k, nDCG@k, Precision@k, and num_queries.
    """
    metrics: dict[str, float] = {}

    metrics["mrr"] = compute_mrr(retrieved_lists, relevant_sets)

    for k in (5, 10, 20):
        recalls = [compute_recall_at_k(r, rel, k) for r, rel in zip(retrieved_lists, relevant_sets, strict=False)]
        metrics[f"recall@{k}"] = sum(recalls) / len(recalls) if recalls else 0.0

    for k in (5, 10):
        ndcgs = [compute_ndcg_at_k(r, rel, k) for r, rel in zip(retrieved_lists, relevant_sets, strict=False)]
        metrics[f"ndcg@{k}"] = sum(ndcgs) / len(ndcgs) if ndcgs else 0.0

    for k in (5,):
        precisions = [compute_precision_at_k(r, rel, k) for r, rel in zip(retrieved_lists, relevant_sets, strict=False)]
        metrics[f"precision@{k}"] = sum(precisions) / len(precisions) if precisions else 0.0

    metrics["num_queries"] = float(len(retrieved_lists))
    return metrics


def load_eval_dataset(dataset_path: str) -> list[dict[str, Any]]:
    """Load a labeled evaluation dataset from a JSON or JSONL file.

    Supports both:
    - JSON array: [{"query": "...", "relevant_docs": [...]}, ...]
    - JSONL: one JSON object per line
    """
    import json
    from pathlib import Path

    path = Path(dataset_path)
    if not path.exists():
        logger.error(f"Dataset not found: {dataset_path}")
        return []

    pairs = []
    if path.suffix == ".jsonl":
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    record = json.loads(line)
                    if "query" in record and "relevant_docs" in record:
                        pairs.append(record)
                except json.JSONDecodeError:
                    continue
    elif path.suffix == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for record in data:
                    if "query" in record and "relevant_docs" in record:
                        pairs.append(record)
            elif isinstance(data, dict) and "query" in data:
                pairs.append(data)

    logger.info(f"Loaded {len(pairs)} eval pairs from {dataset_path}")
    return pairs
