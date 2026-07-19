"""Domain events for side effects and audit trail.

Domain events represent things that happened in the domain. They are
immutable facts used for audit logging, event sourcing, and triggering
side effects (e.g., cache invalidation, notifications).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DomainEvent:
    """Base domain event.

    All domain events carry a unique ID and timestamp for
    ordering and deduplication.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_type: str = ""


@dataclass
class DocumentIndexed(DomainEvent):
    """Fired when a document is indexed into the vector store."""

    document_id: str = ""
    chunk_count: int = 0
    source_type: str = ""
    event_type: str = "document.indexed"


@dataclass
class DocumentUpdated(DomainEvent):
    """Fired when a document version is updated."""

    document_id: str = ""
    old_version: str = ""
    new_version: str = ""
    event_type: str = "document.updated"


@dataclass
class FeedbackSubmitted(DomainEvent):
    """Fired when expert feedback is submitted."""

    feedback_id: str = ""
    user_id: str = ""
    feedback_type: str = ""  # positive, negative
    query: str = ""
    event_type: str = "feedback.submitted"


@dataclass
class ModelPromoted(DomainEvent):
    """Fired when a model version is promoted to production."""

    model_name: str = ""
    version: str = ""
    promoted_by: str = ""
    event_type: str = "model.promoted"


@dataclass
class RetrievalPerformed(DomainEvent):
    """Fired when a retrieval operation is performed."""

    query: str = ""
    result_count: int = 0
    latency_ms: float = 0.0
    cache_hit: bool = False
    event_type: str = "retrieval.performed"


@dataclass
class ChunkCreated(DomainEvent):
    """Fired when a new chunk is created during ETL."""

    chunk_id: str = ""
    document_id: str = ""
    text_length: int = 0
    event_type: str = "chunk.created"


@dataclass
class UserAuthenticated(DomainEvent):
    """Fired when a user authenticates."""

    user_id: str = ""
    method: str = ""  # jwt, api_key, ldap
    success: bool = True
    event_type: str = "user.authenticated"
