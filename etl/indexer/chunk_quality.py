# etl/indexer/chunk_quality.py
"""Chunk quality filter using reranker relevance scoring.

After chunking, use the reranker to score each chunk's relevance to:
1. The document title (is this chunk about the document topic?)
2. The section heading (is this chunk relevant to its section?)

Low-scoring chunks (boilerplate, navigation menus, footers) are filtered
out before embedding and indexing. Also includes heuristic boilerplate
detection that runs with zero API calls.

Supports:
- Remote reranker API (POST /v1/rerank, Cohere-compatible format)
- Configurable relevance threshold
- Heuristic boilerplate detection (regex patterns)
- Batch scoring with safety limit
- Graceful degradation (skip filter on API failure)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

BOILERPLATE_PATTERNS: list[re.Pattern] = [
    # Common boilerplate indicators
    re.compile(r"(last\s*modified|последнее\s*изменение|изменено)", re.IGNORECASE),
    re.compile(r"(all rights reserved|все права защищены)", re.IGNORECASE),
    re.compile(r"(copyright|авторские права)\s*[©™℠]", re.IGNORECASE),
    re.compile(r"(powered by|работает на|создано с помощью)", re.IGNORECASE),
    re.compile(r"(terms of (use|service)|условия использования)", re.IGNORECASE),
    re.compile(r"(privacy policy|политика конфиденциальности)", re.IGNORECASE),
    re.compile(r"(cookie|куки)\s+(notice|policy|уведомление)", re.IGNORECASE),
    # Navigation / breadcrumbs
    re.compile(r"^(home|главная)\s*[>»/]\s*", re.IGNORECASE),
    re.compile(r"(breadcrumbs?|навигация|хлебные крошки)", re.IGNORECASE),
    re.compile(r"^(previous|next|prev|следующая|предыдущая)\s*(page|страница)?", re.IGNORECASE),
    # Footer boilerplate
    re.compile(r"(footer|подвал|нижний колонтитул)", re.IGNORECASE),
    re.compile(r"^\s*(©|\(c\))\s*\d{4}", re.IGNORECASE),
    re.compile(r"(subscribe|unsubscribe|подписаться|отписаться)", re.IGNORECASE),
    # Social media
    re.compile(r"(follow us|следите за нами|мы в соцсетях)", re.IGNORECASE),
    re.compile(r"(facebook|twitter|instagram|linkedin|telegram|vkontakte|одноклассники)", re.IGNORECASE),
    # Comments / discussions sections
    re.compile(r"^(comments?|discussions?|комментарии|обсуждения)\s*[:;]*\s*$", re.IGNORECASE),
    re.compile(r"^(leave a|оставить)\s+(comment|reply|ответ|комментарий)", re.IGNORECASE),
]

MINIMAL_CONTENT_PATTERNS: list[re.Pattern] = [
    # Very short or whitespace-only content
    re.compile(r"^\s*$"),
    re.compile(r"^\s*[-–—]{3,}\s*$"),  # horizontal rules
    re.compile(r"^\s*[*•·▪▸►]\s*$"),  # single bullet
]

MIN_CONTENT_CHARS = 20
MIN_CONTENT_WORDS = 3


class ChunkQualityFilter:
    """Filters low-quality chunks using reranker relevance scoring.

    Uses a remote reranker API (Cohere /v1/rerank compatible) to score
    each chunk against the document title and section heading.
    Chunks scoring below threshold are filtered out.

    Also performs heuristic boilerplate detection (zero API calls).

    Usage:
        quality_filter = ChunkQualityFilter(
            reranker_endpoint="http://rag-proxy:8080",
            model="BAAI/bge-reranker-v2-m3",
            threshold=0.3,
        )
        filtered = quality_filter.filter(
            doc_title="GitLab CI/CD Pipeline Setup",
            chunks=[{"text": "...", "heading": "Introduction", ...}, ...],
        )
    """

    def __init__(
        self,
        reranker_endpoint: str = "",
        model: str = "",
        api_key: str = "",
        threshold: float = 0.3,
        detect_boilerplate: bool = True,
        max_chunks_per_doc: int = 500,
        timeout: int = 30,
    ):
        base = reranker_endpoint.rstrip("/")
        for suffix in ("/v1/rerank", "/rerank", "/v1"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        self._endpoint = base
        self._rerank_url = f"{self._endpoint}/v1/rerank"
        self._model = model
        self._api_key = api_key
        self._threshold = threshold
        self._detect_boilerplate_enabled = detect_boilerplate
        self._max_chunks_per_doc = max_chunks_per_doc
        self._timeout = timeout
        self._healthy = True

        logger.info(
            "ChunkQualityFilter initialized: endpoint=%s, model=%s, threshold=%.2f, boilerplate=%s, max_chunks=%d",
            self._rerank_url,
            self._model,
            self._threshold,
            detect_boilerplate,
            max_chunks_per_doc,
        )

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    def _make_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def score_chunks(self, query: str, texts: list[str]) -> list[float]:
        """Score chunks against a query using remote reranker API.

        Calls POST /v1/rerank with query + documents.
        Returns list of relevance scores (higher = more relevant).

        :param query: The query to score against (e.g. document title).
        :param texts: List of chunk texts.
        :return: List of scores in the same order as texts.
        """
        if not texts or not query:
            return [0.5] * len(texts)

        import json
        import urllib.request

        payload = json.dumps(
            {
                "model": self._model or "default",
                "query": query,
                "documents": texts,
                "top_n": len(texts),
            },
        ).encode("utf-8")

        try:
            req = urllib.request.Request(
                self._rerank_url,
                data=payload,
                headers=self._make_headers(),
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Reranker API call failed: %s. Returning neutral scores.", exc)
            self._healthy = False
            return [0.5] * len(texts)

        results = body.get("results", [])
        scores = [0.0] * len(texts)
        for result in results:
            idx = result.get("index", 0)
            if idx < len(texts):
                scores[idx] = float(result.get("relevance_score", 0.0))

        return scores

    def detect_boilerplate(self, chunk_text: str) -> tuple[bool, str]:
        """Heuristic boilerplate detection (zero API calls).

        Checks for common boilerplate patterns:
        - "Last modified by" / translations
        - Navigation breadcrumbs
        - Copyright notices
        - Footer/social media links
        - Empty or minimal content

        :param chunk_text: The chunk text to check.
        :return: (is_boilerplate, reason) tuple.
        """
        text = chunk_text.strip()

        # Empty or minimal content
        for pattern in MINIMAL_CONTENT_PATTERNS:
            if pattern.match(text):
                return True, "minimal_or_empty_content"

        if len(text) < MIN_CONTENT_CHARS:
            return True, f"too_short_{len(text)}_chars"
        if len(text.split()) < MIN_CONTENT_WORDS:
            return True, f"too_few_words_{len(text.split())}"

        # Boilerplate patterns
        for pattern in BOILERPLATE_PATTERNS:
            if pattern.search(text):
                return True, f"boilerplate_pattern_{pattern.pattern[:40]}"

        return False, ""

    def filter(
        self,
        doc_title: str,
        chunks: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Filter low-quality chunks using reranker scoring and heuristics.

        Each chunk is scored against the document title.
        Additionally, if a chunk has a heading, it may be scored against
        that heading too. Chunks below threshold are removed.
        Heuristic boilerplate detection is applied first (zero API cost).

        :param doc_title: The document title to score against.
        :param chunks: List of chunk dicts (each must have "text" key).
        :return: (filtered_chunks, stats) tuple.
        """
        if not chunks:
            return [], {"total": 0, "kept": 0, "dropped": 0, "dropped_pct": 0.0}

        original_count = len(chunks)

        # Safety limit
        if len(chunks) > self._max_chunks_per_doc:
            logger.warning(
                "Document '%s' has %d chunks (max %d). Truncating.",
                doc_title[:80],
                len(chunks),
                self._max_chunks_per_doc,
            )
            chunks = chunks[: self._max_chunks_per_doc]

        kept: list[dict[str, Any]] = []
        dropped_boilerplate: int = 0
        dropped_relevance: int = 0

        # Phase 1: Heuristic boilerplate detection (zero API cost)
        for chunk in chunks:
            text = chunk.get("text", "")
            is_bp, reason = self.detect_boilerplate(text) if self._detect_boilerplate_enabled else (False, "")
            if is_bp:
                chunk["_filtered"] = "boilerplate"
                chunk["_filter_reason"] = reason
                dropped_boilerplate += 1
                continue
            kept.append(chunk)

        if not kept:
            stats: dict[str, Any] = {
                "total": original_count,
                "kept": 0,
                "dropped": original_count,
                "dropped_pct": 100.0,
                "dropped_boilerplate": dropped_boilerplate,
                "dropped_relevance": dropped_relevance,
            }
            logger.info(
                "Filtered 0/%d chunks (%.1f%% below threshold) for '%s' — all boilerplate",
                original_count,
                100.0,
                doc_title[:80],
            )
            return [], stats

        # Phase 2: Reranker scoring against document title
        chunk_texts = [c["text"] for c in kept]
        if not chunk_texts:
            boilerplate_stats = {
                "total": original_count,
                "kept": 0,
                "dropped": original_count,
                "dropped_pct": 100.0,
                "dropped_boilerplate": dropped_boilerplate,
                "dropped_relevance": dropped_relevance,
            }
            return [], boilerplate_stats

        title_scores = self.score_chunks(doc_title, chunk_texts)

        # Phase 3: Section heading scoring (additional signal)
        chunk_heading_scores: list[float] = [0.0] * len(kept)
        for i, chunk in enumerate(kept):
            heading = chunk.get("heading", "") or chunk.get("section", "")
            if heading:
                heading_score_result = self.score_chunks(heading, [chunk["text"]])
                if heading_score_result:
                    chunk_heading_scores[i] = heading_score_result[0]

        # Phase 4: Combine scores and filter by threshold
        title_weight = 0.6
        heading_weight = 0.4

        final_kept: list[dict[str, Any]] = []
        for i, chunk in enumerate(kept):
            title_score = title_scores[i] if i < len(title_scores) else 0.5
            hs = chunk_heading_scores[i] if i < len(chunk_heading_scores) else 0.0

            combined_score = title_weight * title_score + heading_weight * hs

            chunk["_quality_title_score"] = round(title_score, 4)
            chunk["_quality_heading_score"] = round(hs, 4)
            chunk["_quality_combined"] = round(combined_score, 4)

            if combined_score >= self._threshold:
                final_kept.append(chunk)
            else:
                chunk["_filtered"] = "low_relevance"
                dropped_relevance += 1

        total_dropped = dropped_boilerplate + dropped_relevance
        dropped_pct = (total_dropped / original_count * 100) if original_count else 0.0

        stats = {
            "total": original_count,
            "kept": len(final_kept),
            "dropped": total_dropped,
            "dropped_pct": round(dropped_pct, 1),
            "dropped_boilerplate": dropped_boilerplate,
            "dropped_relevance": dropped_relevance,
        }

        logger.info(
            "Filtered %d/%d chunks (%.1f%% below threshold) for '%s' (boilerplate=%d, relevance=%d)",
            len(final_kept),
            original_count,
            dropped_pct,
            doc_title[:80],
            dropped_boilerplate,
            dropped_relevance,
        )

        return final_kept, stats


def build_chunk_quality_filter_from_config(config: dict[str, Any]) -> ChunkQualityFilter | None:
    """Build a ChunkQualityFilter from the full ETL config dict.

    Reads quality_filter section. Returns None if not enabled.

    :param config: Full ETL YAML config as dict.
    :return: ChunkQualityFilter instance or None.
    """
    qf_cfg = config.get("quality_filter", {})
    if not qf_cfg.get("enabled", False):
        logger.info("Chunk quality filter is disabled")
        return None

    endpoint = qf_cfg.get("reranker_endpoint", "")
    if not endpoint:
        logger.warning("Chunk quality filter enabled but no reranker_endpoint configured. Disabling.")
        return None

    return ChunkQualityFilter(
        reranker_endpoint=endpoint,
        model=qf_cfg.get("reranker_model", ""),
        api_key=qf_cfg.get("api_key", ""),
        threshold=float(qf_cfg.get("relevance_threshold", 0.3)),
        detect_boilerplate=bool(qf_cfg.get("detect_boilerplate", True)),
        max_chunks_per_doc=int(qf_cfg.get("max_chunks_per_doc", 500)),
        timeout=int(qf_cfg.get("timeout", 30)),
    )
