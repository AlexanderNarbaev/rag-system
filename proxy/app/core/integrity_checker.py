# proxy/app/core/integrity_checker.py
"""Knowledge integrity validation for RAG knowledge bases.

Detects contradictions between chunks using NLI entailment models
and computes topic coverage gaps to assess knowledge base quality.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC
from typing import Any

from proxy.app.shared.config import (
    INTEGRITY_CHUNK_SAMPLE_LIMIT,
    INTEGRITY_NLI_CONTRADICTION_THRESHOLD,
)

logger = logging.getLogger(__name__)


def _get_nli_classifier() -> Any:
    """Lazy-import the NLI classifier pipeline."""
    try:
        from transformers import pipeline

        return pipeline(
            "text-classification",
            model="MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",
            device=-1,
        )
    except Exception:
        logger.debug("NLI pipeline not available for integrity checking")
        return None


def check_contradiction(
    chunk_a: str,
    chunk_b: str,
) -> dict[str, float]:
    """Check if two text chunks contradict each other using NLI.

    Args:
        chunk_a: First chunk text.
        chunk_b: Second chunk text.

    Returns:
        Dict with contradiction_score, entailment_score, neutral_score.
        Scores are in [0.0, 1.0].
    """
    if not chunk_a or not chunk_b:
        return {"contradiction_score": 0.0, "entailment_score": 0.0, "neutral_score": 0.0}

    nli = _get_nli_classifier()
    if nli is None:
        return _check_contradiction_lightweight(chunk_a, chunk_b)

    try:
        result = nli(
            f"{chunk_a[:512]}</s></s>{chunk_b[:512]}",
            truncation=True,
        )
        scores: dict[str, float] = {}
        for item in result:
            scores[item["label"].lower()] = float(item["score"])
        return {
            "contradiction_score": scores.get("contradiction", 0.0),
            "entailment_score": scores.get("entailment", 0.0),
            "neutral_score": scores.get("neutral", 0.0),
        }
    except Exception as e:
        logger.debug("NLI contradiction check failed, using lightweight fallback: %s", e)
        return _check_contradiction_lightweight(chunk_a, chunk_b)


def _check_contradiction_lightweight(chunk_a: str, chunk_b: str) -> dict[str, float]:
    """Lightweight contradiction check using keyword overlap and negation.

    Used as a fallback when the NLI model is unavailable.
    """
    import re

    tokens_a = set(re.findall(r"\w+", chunk_a.lower()))
    tokens_b = set(re.findall(r"\w+", chunk_b.lower()))

    if not tokens_a or not tokens_b:
        return {"contradiction_score": 0.0, "entailment_score": 0.0, "neutral_score": 1.0}

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    jaccard = len(intersection) / len(union) if union else 0.0

    negation_words = {"not", "no", "never", "none", "neither", "nor", "without", "cannot", "doesn"}
    has_neg_a = bool(tokens_a & negation_words)
    has_neg_b = bool(tokens_b & negation_words)

    if jaccard > 0.4 and (has_neg_a != has_neg_b):
        return {"contradiction_score": 0.6, "entailment_score": 0.1, "neutral_score": 0.3}

    if jaccard > 0.6:
        return {"contradiction_score": 0.05, "entailment_score": 0.7, "neutral_score": 0.25}

    return {"contradiction_score": 0.05, "entailment_score": 0.1, "neutral_score": 0.85}


def find_contradictions(
    kb_id: str,
    qdrant_client: Any,
    collection_name: str,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Find contradiction pairs within the same topic (same source_id).

    Args:
        kb_id: Knowledge base ID.
        qdrant_client: Qdrant client instance.
        collection_name: Qdrant collection name.
        threshold: Minimum contradiction score to report.

    Returns:
        List of contradiction pair dicts.
    """
    if threshold is None:
        threshold = INTEGRITY_NLI_CONTRADICTION_THRESHOLD

    if qdrant_client is None:
        logger.warning("Qdrant client not available for integrity checking")
        return []

    from qdrant_client.http import models

    try:
        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="kb_id",
                        match=models.MatchValue(value=kb_id),
                    ),
                ],
            ),
            limit=INTEGRITY_CHUNK_SAMPLE_LIMIT,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        logger.warning("Failed to query Qdrant for integrity check: %s", e)
        return []

    if not results:
        return []

    by_source_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in results:
        payload = point.payload or {}
        sid = payload.get("source_id", "")
        by_source_id[sid].append(
            {
                "id": point.id,
                "text": payload.get("text", "")[:512],
                "title": payload.get("title") or payload.get("doc_title", ""),
                "source_type": payload.get("source_type", ""),
            }
        )

    contradictions: list[dict[str, Any]] = []

    for source_id, chunks in by_source_id.items():
        if len(chunks) < 2:
            continue

        for i in range(len(chunks)):
            for j in range(i + 1, min(i + 10, len(chunks))):
                result = check_contradiction(chunks[i]["text"], chunks[j]["text"])
                if result["contradiction_score"] >= threshold:
                    contradictions.append(
                        {
                            "source_id": source_id,
                            "chunk_a_id": chunks[i]["id"],
                            "chunk_a_title": chunks[i]["title"],
                            "chunk_b_id": chunks[j]["id"],
                            "chunk_b_title": chunks[j]["title"],
                            "source_type": chunks[i]["source_type"],
                            "contradiction_score": round(result["contradiction_score"], 3),
                            "entailment_score": round(result["entailment_score"], 3),
                            "neutral_score": round(result["neutral_score"], 3),
                            "text_preview_a": chunks[i]["text"][:150],
                            "text_preview_b": chunks[j]["text"][:150],
                        }
                    )

    contradictions.sort(key=lambda c: c["contradiction_score"], reverse=True)
    return contradictions[:100]


def compute_knowledge_coverage(
    kb_id: str,
    qdrant_client: Any,
    collection_name: str,
) -> dict[str, Any]:
    """Compute knowledge coverage metrics for a knowledge base.

    Analyzes topic distribution, source type distribution, and
    identifies potential coverage gaps.

    Args:
        kb_id: Knowledge base ID.
        qdrant_client: Qdrant client instance.
        collection_name: Qdrant collection name.

    Returns:
        Dict with coverage metrics.
    """
    if qdrant_client is None:
        return {"error": "Qdrant client not available"}

    from qdrant_client.http import models

    try:
        results, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="kb_id",
                        match=models.MatchValue(value=kb_id),
                    ),
                ],
            ),
            limit=INTEGRITY_CHUNK_SAMPLE_LIMIT,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        logger.warning("Failed to query Qdrant for coverage check: %s", e)
        return {"error": str(e)}

    if not results:
        return {
            "total_chunks": 0,
            "source_distribution": {},
            "topic_distribution": {},
            "coverage_gaps": [],
        }

    source_dist: dict[str, int] = defaultdict(int)
    topic_dist: dict[str, int] = defaultdict(int)
    has_timestamps = 0
    latest_ts = 0.0
    oldest_ts = float("inf")

    for point in results:
        payload = point.payload or {}
        source_type = payload.get("source_type", "unknown")
        source_dist[source_type] += 1

        title = payload.get("title") or payload.get("doc_title", "")
        if title:
            topic_dist[title[:80]] += 1

        ts = payload.get("last_updated") or payload.get("updated_at") or payload.get("created_at")
        if ts:
            has_timestamps += 1
            ts_f = float(ts)
            latest_ts = max(latest_ts, ts_f)
            oldest_ts = min(oldest_ts, ts_f)

    coverage_gaps: list[dict[str, Any]] = []
    if len(source_dist) == 1:
        coverage_gaps.append(
            {
                "type": "single_source",
                "message": "Only one source type present; consider adding more sources for comprehensive coverage",
                "source": list(source_dist.keys())[0],
            }
        )

    if has_timestamps > 0 and latest_ts > 0 and oldest_ts < float("inf"):
        from datetime import datetime

        now = datetime.now(UTC).timestamp()
        age_days = (now - latest_ts) / 86400
        if age_days > 30:
            coverage_gaps.append(
                {
                    "type": "outdated",
                    "message": f"Latest document is {age_days:.0f} days old",
                    "age_days": round(age_days, 1),
                }
            )

    return {
        "total_chunks": len(results),
        "unique_sources": len(source_dist),
        "source_distribution": dict(source_dist),
        "topic_distribution": dict(topic_dist),
        "coverage_gaps": coverage_gaps,
    }


def compute_integrity_score(
    kb_id: str,
    qdrant_client: Any,
    collection_name: str,
) -> dict[str, Any]:
    """Compute overall knowledge integrity score for a KB.

    Combines contradiction rate and coverage metrics into a 0-100 score.

    Returns:
        Dict with overall_score, contradictions (list), coverage (dict).
    """
    contradictions = find_contradictions(kb_id, qdrant_client, collection_name)
    coverage = compute_knowledge_coverage(kb_id, qdrant_client, collection_name)

    contradiction_penalty = min(len(contradictions) * 2, 40)
    coverage_score = min(len(coverage.get("source_distribution", {})) * 10, 50)
    freshness_bonus = 10 if not any(g["type"] == "outdated" for g in coverage.get("coverage_gaps", [])) else 0

    overall_score = 100 - contradiction_penalty - (50 - coverage_score) + freshness_bonus
    overall_score = max(0, min(100, overall_score))

    try:
        from proxy.app.shared.metrics import rag_knowledge_integrity_score

        rag_knowledge_integrity_score.labels(kb_id=kb_id).set(overall_score)
    except Exception:
        pass

    return {
        "kb_id": kb_id,
        "overall_score": round(overall_score, 1),
        "contradictions": contradictions,
        "coverage": coverage,
    }
