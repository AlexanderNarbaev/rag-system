"""Domain services — cross-aggregate business logic.

Domain services encapsulate business logic that doesn't naturally
belong to a single entity or value object. They are stateless and
operate on domain objects.
"""

from __future__ import annotations

from typing import Any

from proxy.app.domain.entities import Chunk, User
from proxy.app.domain.value_objects import ConfidenceScore


class AccessControlService:
    """Domain service for access control logic.

    Centralizes ACL filtering and Qdrant filter construction
    to keep access rules consistent across the system.
    """

    def filter_chunks_by_access(
        self,
        chunks: list[Chunk],
        user: User | None,
    ) -> list[Chunk]:
        """Filter chunks based on user's access level.

        Args:
            chunks: List of chunks to filter.
            user: Authenticated user (None = anonymous).

        Returns:
            Chunks the user is authorized to access.
        """
        if user is None or user.is_admin:
            return chunks

        return [
            chunk
            for chunk in chunks
            if user.can_access(
                chunk.access_level,
                chunk.allowed_groups,
                chunk.allowed_users,
            )
        ]

    def build_access_filter(self, user: User | None) -> dict[str, Any] | None:
        """Build Qdrant access filter from user context.

        Args:
            user: Authenticated user (None = anonymous).

        Returns:
            Qdrant filter dict, or None for unrestricted access.
        """
        if user is None or user.is_admin:
            return None

        return {
            "must": [
                {"key": "access_level", "match": {"value": "public"}},
            ],
            "should": [
                {"key": "allowed_users", "match": {"any": [user.id]}},
                {"key": "allowed_groups", "match": {"any": user.groups}},
            ],
        }


class RetrievalScoringService:
    """Domain service for retrieval scoring logic.

    Encapsulates RRF fusion, knee-point detection, and
    CRAG-style confidence computation.
    """

    def compute_rrf_score(
        self,
        dense_rank: int,
        sparse_rank: int,
        k: int = 60,
    ) -> float:
        """Compute Reciprocal Rank Fusion score.

        Combines dense and sparse retrieval rankings into a
        single score using the RRF formula.

        Args:
            dense_rank: 1-based rank from dense retrieval.
            sparse_rank: 1-based rank from sparse retrieval.
            k: RRF constant (default 60).

        Returns:
            Combined RRF score.
        """
        return 1.0 / (k + dense_rank) + 1.0 / (k + sparse_rank)

    def find_knee_point(self, scores: list[float]) -> int:
        """Find the knee point in a descending score distribution.

        The knee point is where the largest drop occurs, indicating
        the boundary between relevant and less-relevant results.

        Args:
            scores: Sorted (descending) list of scores.

        Returns:
            Index of the knee point.
        """
        if len(scores) < 3:
            return len(scores)

        max_drop = 0.0
        knee = len(scores)
        for i in range(1, len(scores)):
            drop = scores[i - 1] - scores[i]
            if drop > max_drop:
                max_drop = drop
                knee = i

        return knee

    def compute_confidence(
        self,
        score_distribution: list[float],
        coverage_ratio: float,
        result_count: int,
        recency_decay: float = 1.0,
    ) -> ConfidenceScore:
        """Compute CRAG-style confidence score.

        Combines multiple factors into a single confidence value
        and recommends an action for the pipeline.

        Args:
            score_distribution: List of retrieval scores.
            coverage_ratio: Fraction of query covered by results.
            result_count: Number of retrieved results.
            recency_decay: Recency decay factor (0.0 to 1.0).

        Returns:
            ConfidenceScore with value, factors, and action.
        """
        if not score_distribution:
            return ConfidenceScore(
                value=0.0,
                factors={"score": 0.0, "coverage": 0.0, "count": 0.0, "recency": 0.0},
                action="FALLBACK",
            )

        avg_score = sum(score_distribution) / len(score_distribution)
        score_factor = min(avg_score / 0.8, 1.0) * 0.4
        coverage_factor = min(coverage_ratio, 1.0) * 0.3
        count_factor = min(result_count / 5, 1.0) * 0.2
        recency_factor = recency_decay * 0.1

        value = score_factor + coverage_factor + count_factor + recency_factor

        if value >= 0.6:
            action = "USE"
        elif value >= 0.4:
            action = "REWRITE"
        elif value >= 0.2:
            action = "EXPAND"
        else:
            action = "FALLBACK"

        return ConfidenceScore(
            value=value,
            factors={
                "score": score_factor,
                "coverage": coverage_factor,
                "count": count_factor,
                "recency": recency_factor,
            },
            action=action,
        )
