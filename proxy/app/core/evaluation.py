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


# ── F6: Cross-Lingual Benchmarks ──

_CROSS_LINGUAL_SAMPLE_QUERIES: dict[str, list[str]] = {
    "en": [
        "How do I set up a CI/CD pipeline?",
        "What is Retrieval-Augmented Generation?",
        "How to configure Jira automation rules?",
        "Explain the hybrid search architecture",
        "What are the best practices for Qdrant collections?",
    ],
    "de": [
        "Wie richte ich eine CI/CD-Pipeline ein?",
        "Was ist Retrieval-Augmented Generation?",
        "Wie konfiguriere ich Jira-Automatisierungsregeln?",
        "Erklären Sie die hybride Sucharchitektur",
        "Was sind die besten Praktiken für Qdrant-Sammlungen?",
    ],
    "fr": [
        "Comment configurer un pipeline CI/CD?",
        "Qu'est-ce que la génération augmentée par récupération?",
        "Comment configurer les règles d'automatisation Jira?",
        "Expliquez l'architecture de recherche hybride",
        "Quelles sont les meilleures pratiques pour les collections Qdrant?",
    ],
    "zh": [
        "如何设置CI/CD管道？",
        "什么是检索增强生成？",
        "如何配置Jira自动化规则？",
        "解释混合搜索架构",
        "Qdrant集合的最佳实践是什么？",
    ],
}

_RELEVANT_DOC_IDS: dict[str, list[set[str]]] = {
    "en": [
        {"cicd_setup"},
        {"rag_overview"},
        {"jira_proj123"},
        {"hybrid", "search"},
        {"qdrant", "collections"},
    ],
    "de": [
        {"cicd_setup"},
        {"rag_overview"},
        {"jira_proj123"},
        {"hybrid", "search"},
        {"qdrant", "collections"},
    ],
    "fr": [
        {"cicd_setup"},
        {"rag_overview"},
        {"jira_proj123"},
        {"hybrid", "search"},
        {"qdrant", "collections"},
    ],
    "zh": [
        {"cicd_setup"},
        {"rag_overview"},
        {"jira_proj123"},
        {"hybrid", "search"},
        {"qdrant", "collections"},
    ],
}


def evaluate_cross_lingual_retrieval(
    lang_pair: tuple[str, str],
    queries: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Evaluate cross-lingual retrieval performance for a language pair.

    Compares monolingual (query in source lang, retrieve in source lang)
    vs cross-lingual (query in source lang, retrieve in target lang).

    The bge-m3 model supports 100+ languages natively and provides
    cross-lingual embeddings out of the box.

    Args:
        lang_pair: (source_lang, target_lang) e.g. ("en", "de").
        queries: Dict mapping language code to list of query strings.
                 Uses built-in sample queries if None.

    Returns:
        Dict with source_lang, target_lang, monolingual metrics,
        cross_lingual metrics, comparison delta, and num_queries.
    """
    source_lang, target_lang = lang_pair

    if queries is None:
        q_source = _CROSS_LINGUAL_SAMPLE_QUERIES.get(source_lang, _CROSS_LINGUAL_SAMPLE_QUERIES["en"])
        q_target = _CROSS_LINGUAL_SAMPLE_QUERIES.get(target_lang, _CROSS_LINGUAL_SAMPLE_QUERIES["en"])
    else:
        q_source = queries.get(source_lang, queries.get("en", []))
        q_target = queries.get(target_lang, queries.get("en", []))

    relevant = _RELEVANT_DOC_IDS.get(source_lang, _RELEVANT_DOC_IDS["en"])

    if not q_source:
        return {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "monolingual": {},
            "cross_lingual": {},
            "comparison": {},
            "num_queries": 0,
        }

    n = min(len(q_source), len(relevant))
    q_source = q_source[:n]
    relevant = relevant[:n]

    try:
        from proxy.app.core.retrieval import hybrid_search

        def _id_from_hit(hit) -> str:
            try:
                return hit.payload.get("semantic_key", hit.payload.get("hash", str(hit.id)))
            except Exception:
                return str(hit.id)

        # Monolingual: query in source lang
        retrieved_mono = []
        for q in q_source:
            hits = hybrid_search(q, top_k=10)
            retrieved_mono.append([_id_from_hit(h) for h in hits])

        mono_metrics = compute_all_metrics(retrieved_mono, relevant)

        # Cross-lingual: query in target lang
        retrieved_cross = []
        for q in q_target:
            hits = hybrid_search(q, top_k=10)
            retrieved_cross.append([_id_from_hit(h) for h in hits])

        cross_metrics = compute_all_metrics(retrieved_cross, relevant)

    except Exception as e:
        logger.warning(f"Cross-lingual benchmark failed (retrieval unavailable): {e}")
        return {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "monolingual": {"mrr": 0.0, "recall@5": 0.0, "recall@10": 0.0},
            "cross_lingual": {"mrr": 0.0, "recall@5": 0.0, "recall@10": 0.0},
            "comparison": {"mrr_delta": 0.0},
            "num_queries": len(q_source),
        }

    comparison = {}
    for key in mono_metrics:
        if key != "num_queries" and key in cross_metrics:
            comparison[f"{key}_delta"] = round(cross_metrics[key] - mono_metrics[key], 4)

    return {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "monolingual": {k: v for k, v in mono_metrics.items() if k != "num_queries"},
        "cross_lingual": {k: v for k, v in cross_metrics.items() if k != "num_queries"},
        "comparison": comparison,
        "num_queries": len(q_source),
    }


def run_cross_lingual_benchmark() -> list[dict]:
    """Run cross-lingual benchmarks for all supported language pairs.

    Compares monolingual vs cross-lingual retrieval performance
    for each pair involving a non-English source language.

    Returns:
        List of results dicts, one per language pair.
    """
    pairs = [
        ("en", "de"),
        ("en", "fr"),
        ("en", "zh"),
        ("ru", "en"),
        ("ru", "de"),
    ]
    results = []
    for pair in pairs:
        try:
            result = evaluate_cross_lingual_retrieval(pair)
            result["lang_pair"] = f"{pair[0]}->{pair[1]}"
            results.append(result)
        except Exception as e:
            logger.warning(f"Benchmark failed for {pair}: {e}")
            results.append(
                {
                    "lang_pair": f"{pair[0]}->{pair[1]}",
                    "error": str(e),
                    "monolingual": {},
                    "cross_lingual": {},
                }
            )
    return results
