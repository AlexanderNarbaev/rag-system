"""Value objects — immutable, compared by value.

Value objects have no identity. Two value objects are equal iff all
their attributes are equal. They are frozen (immutable) to prevent
accidental mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchQuery:
    """Value object for a search query.

    Encapsulates the query text and retrieval parameters.
    Immutable once created — any modified query is a new object.
    """

    text: str
    version: str | None = None
    top_k: int = 20
    access_filter: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Query text cannot be empty")
        if self.top_k < 1:
            raise ValueError("top_k must be >= 1")


@dataclass(frozen=True)
class RetrievalResult:
    """Value object for a single retrieval result.

    Represents one chunk returned from the retrieval pipeline,
    including provenance metadata and relevance scoring.
    """

    chunk_id: str
    text: str
    score: float
    source_type: str
    source_id: str
    title: str
    version: str
    metadata: dict[str, Any]

    @property
    def relevance(self) -> str:
        """Categorize relevance based on score thresholds."""
        if self.score >= 0.8:
            return "high"
        elif self.score >= 0.5:
            return "medium"
        return "low"


@dataclass(frozen=True)
class ConfidenceScore:
    """Value object for confidence scoring.

    Encapsulates the computed confidence value, contributing factors,
    and the recommended action for the retrieval-augmented pipeline.
    """

    value: float  # 0.0 to 1.0
    factors: dict[str, float]
    action: str  # USE, REWRITE, EXPAND, FALLBACK

    @property
    def is_confident(self) -> bool:
        """Check if confidence is high enough to use directly."""
        return self.value >= 0.6

    @property
    def needs_review(self) -> bool:
        """Check if result needs human review."""
        return self.value < 0.5


@dataclass(frozen=True)
class TokenBudget:
    """Value object for token budget management.

    Tracks total, used, and reserved tokens for context assembly.
    Immutable — returns new instances for budget changes.
    """

    total: int
    used: int = 0
    reserved: int = 0

    @property
    def remaining(self) -> int:
        """Tokens available for use."""
        return max(0, self.total - self.used - self.reserved)

    @property
    def utilization(self) -> float:
        """Fraction of total budget used (0.0 to 1.0)."""
        return self.used / self.total if self.total > 0 else 0.0

    def can_fit(self, tokens: int) -> bool:
        """Check if a chunk of given size fits in remaining budget."""
        return tokens <= self.remaining

    def allocate(self, tokens: int) -> TokenBudget:
        """Return a new budget with tokens allocated."""
        return TokenBudget(
            total=self.total,
            used=self.used + tokens,
            reserved=self.reserved,
        )
