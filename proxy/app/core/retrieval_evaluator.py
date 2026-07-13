# proxy/app/retrieval_evaluator.py
"""
CRAG-style retrieval quality evaluation.

Evaluates the quality of retrieved chunks and triggers corrective actions:
- USE: good retrieval, proceed
- REWRITE: query needs reformulation
- EXPAND: expand search scope (graph, synonyms)
- FALLBACK: no useful results, use alternative strategy
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class RetrievalEvaluator:
    """Evaluates retrieval quality and triggers corrective actions."""

    HIGH_THRESHOLD = 0.7
    MEDIUM_THRESHOLD = 0.4
    LOW_THRESHOLD = 0.2

    def evaluate_quality(self, query: str, retrieved_chunks: list[dict[str, Any]]) -> float:
        """
        Return confidence score 0.0-1.0 based on:
        - Average similarity scores (if present)
        - Score distribution (variance/entropy)
        - Number of results above threshold
        - Query-chunk text overlap
        """
        if not retrieved_chunks:
            return 0.0

        scores = []
        for chunk in retrieved_chunks:
            score = chunk.get("score", chunk.get("_score", None))
            if score is not None:
                scores.append(float(score))

        if not scores:
            scores = self._compute_text_overlap_scores(query, retrieved_chunks)

        if not scores:
            return 0.0

        avg_score = sum(scores) / len(scores)
        variance = sum((s - avg_score) ** 2 for s in scores) / len(scores)

        high_count = sum(1 for s in scores if s > self.HIGH_THRESHOLD)
        med_count = sum(1 for s in scores if self.MEDIUM_THRESHOLD < s <= self.HIGH_THRESHOLD)
        coverage_ratio = (high_count * 1.0 + med_count * 0.5) / max(1, len(scores))

        result_count_factor = min(1.0, len(scores) / 5.0)

        decay = 1.0 / (1.0 + variance)
        confidence = avg_score * 0.4 + coverage_ratio * 0.3 + result_count_factor * 0.2 + decay * 0.1

        return min(1.0, max(0.0, confidence))

    def _compute_text_overlap_scores(self, query: str, chunks: list[dict[str, Any]]) -> list[float]:
        """Fallback: compute simple Jaccard-like overlap between query and chunk text."""
        query_tokens = set(re.findall(r"\w+", query.lower()))
        if not query_tokens:
            return []

        scores = []
        for chunk in chunks:
            text = chunk.get("text", "")
            if not text:
                scores.append(0.0)
                continue
            text_tokens = set(re.findall(r"\w+", text.lower()))
            if not text_tokens:
                scores.append(0.0)
                continue
            overlap = len(query_tokens & text_tokens)
            union = len(query_tokens | text_tokens)
            scores.append(overlap / union if union > 0 else 0.0)

        return scores

    def get_action(self, confidence: float) -> str:
        """
        Map confidence to action:
        - confidence >= 0.7: 'USE' — good results, use as-is
        - 0.4 <= confidence < 0.7: 'REWRITE' — reformulate query
        - 0.2 <= confidence < 0.4: 'EXPAND' — graph expansion or broader search
        - confidence < 0.2: 'FALLBACK' — alternative strategy
        """
        if confidence >= self.HIGH_THRESHOLD:
            return "USE"
        elif confidence >= self.MEDIUM_THRESHOLD:
            return "REWRITE"
        elif confidence >= self.LOW_THRESHOLD:
            return "EXPAND"
        else:
            return "FALLBACK"

    def decompose_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Decompose-then-recompose: filter noise, keep key information.
        Removes chunks with very low scores and near-duplicate content.
        Returns cleaned list of chunks.
        """
        if not chunks:
            return []

        cleaned = []
        seen_texts = set()

        for chunk in chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue

            text_signature = text[:120].lower()
            if text_signature in seen_texts:
                continue

            score = chunk.get("score", chunk.get("_score", 0.5))
            if score < self.LOW_THRESHOLD:
                continue

            seen_texts.add(text_signature)
            cleaned.append(dict(chunk))

        for _i, chunk in enumerate(cleaned):
            text = chunk.get("text", "")
            if len(text) > 3000:
                sentences = re.split(r"(?<=[.!?])\s+", text)
                key_sentences = []
                for s in sentences:
                    if len(s) > 15:
                        key_sentences.append(s)
                if key_sentences:
                    chunk["text"] = " ".join(key_sentences[:10])
                    chunk["_decomposed"] = True

        return cleaned

    def evaluate_and_act(self, query: str, retrieved_chunks: list[dict[str, Any]]) -> tuple[float, str, list[dict[str, Any]]]:
        """
        Combined: evaluate quality, get action, and optionally clean chunks.
        Returns (confidence, action, processed_chunks).
        """
        confidence = self.evaluate_quality(query, retrieved_chunks)
        action = self.get_action(confidence)

        if action == "FALLBACK":
            processed = []
        elif action == "EXPAND":
            processed = retrieved_chunks
        else:
            processed = self.decompose_chunks(retrieved_chunks)

        logger.debug(
            f"Retrieval eval: confidence={confidence:.3f}, action={action}, "
            f"chunks={len(retrieved_chunks)}->{len(processed)}"
        )
        return confidence, action, processed
