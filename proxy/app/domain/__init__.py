"""Domain-Driven Design models for the RAG system.

This package contains:
- Entities: objects with identity and lifecycle
- Value Objects: immutable objects compared by value
- Domain Events: side effects and audit trail
- Domain Services: cross-aggregate business logic
"""

from proxy.app.domain.entities import (
    Chunk,
    ChunkStatus,
    Document,
    DocumentStatus,
    KnowledgeBase,
    User,
)
from proxy.app.domain.events import (
    DocumentIndexed,
    DocumentUpdated,
    DomainEvent,
    FeedbackSubmitted,
    ModelPromoted,
    RetrievalPerformed,
)
from proxy.app.domain.services import (
    AccessControlService,
    RetrievalScoringService,
)
from proxy.app.domain.value_objects import (
    ConfidenceScore,
    RetrievalResult,
    SearchQuery,
    TokenBudget,
)

__all__ = [
    # Entities
    "Chunk",
    "ChunkStatus",
    "Document",
    "DocumentStatus",
    "KnowledgeBase",
    "User",
    # Value Objects
    "ConfidenceScore",
    "RetrievalResult",
    "SearchQuery",
    "TokenBudget",
    # Events
    "DocumentIndexed",
    "DocumentUpdated",
    "DomainEvent",
    "FeedbackSubmitted",
    "ModelPromoted",
    "RetrievalPerformed",
    # Services
    "AccessControlService",
    "RetrievalScoringService",
]
