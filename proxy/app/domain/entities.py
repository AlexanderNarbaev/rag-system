"""Domain entities with identity and lifecycle.

Entities are objects that have a distinct identity that runs through time
and different representations. Two entities are equal iff their identities
are equal, regardless of attribute values.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DocumentStatus(Enum):
    """Lifecycle status of a document."""

    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"


class ChunkStatus(Enum):
    """Lifecycle status of a chunk."""

    INDEXED = "indexed"
    STALE = "stale"
    DELETED = "deleted"


@dataclass
class Document:
    """Document entity — represents a source document.

    A Document is the root entity for a knowledge source. It tracks
    provenance (source_type, source_id), versioning, and owns a
    collection of Chunks.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    source_type: str = ""  # confluence, jira, gitlab, etc.
    source_id: str = ""  # original ID in source system
    version: str = "v1"
    status: DocumentStatus = DocumentStatus.ACTIVE
    content_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    chunks: list[Chunk] = field(default_factory=list)

    def mark_stale(self) -> None:
        """Transition document to stale status."""
        self.status = DocumentStatus.STALE
        self.updated_at = datetime.utcnow()

    def mark_archived(self) -> None:
        """Transition document to archived status."""
        self.status = DocumentStatus.ARCHIVED
        self.updated_at = datetime.utcnow()

    def update_version(self, new_version: str) -> None:
        """Update document version and bump timestamp."""
        self.version = new_version
        self.updated_at = datetime.utcnow()

    def add_chunk(self, chunk: Chunk) -> None:
        """Add a chunk to this document."""
        chunk.document_id = self.id
        self.chunks.append(chunk)
        self.updated_at = datetime.utcnow()

    @property
    def is_stale(self) -> bool:
        """Check if document is stale."""
        return self.status == DocumentStatus.STALE


@dataclass
class Chunk:
    """Chunk entity — represents an indexed text chunk.

    A Chunk is a unit of retrievable content. It carries ACL metadata
    for fine-grained access control and quality scores for ranking.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    text: str = ""
    content_hash: str = ""
    version: str = "v1"
    status: ChunkStatus = ChunkStatus.INDEXED
    access_level: str = "public"
    allowed_groups: list[str] = field(default_factory=list)
    allowed_users: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)

    def mark_stale(self) -> None:
        """Transition chunk to stale status."""
        self.status = ChunkStatus.STALE

    def mark_deleted(self) -> None:
        """Transition chunk to deleted status."""
        self.status = ChunkStatus.DELETED

    @property
    def is_accessible_publicly(self) -> bool:
        """Check if chunk is publicly accessible."""
        return self.access_level == "public"


@dataclass
class KnowledgeBase:
    """Knowledge base entity — aggregates documents and chunks.

    A KnowledgeBase represents a named collection of documents,
    typically backed by a Qdrant collection. It tracks aggregate
    counts for monitoring.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    collection_name: str = ""
    document_count: int = 0
    chunk_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_document(self, doc: Document) -> None:
        """Register a document in this knowledge base."""
        self.document_count += 1
        self.chunk_count += len(doc.chunks)
        self.updated_at = datetime.utcnow()

    def remove_document(self, chunk_count: int = 0) -> None:
        """Remove a document from this knowledge base."""
        self.document_count = max(0, self.document_count - 1)
        self.chunk_count = max(0, self.chunk_count - chunk_count)
        self.updated_at = datetime.utcnow()


@dataclass
class User:
    """User entity — represents an authenticated user.

    A User carries role and group memberships that determine
    access control decisions across the system.
    """

    id: str = ""
    username: str = ""
    roles: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    is_active: bool = True

    @property
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return "admin" in self.roles

    @property
    def is_expert(self) -> bool:
        """Check if user has expert role (admin implies expert)."""
        return "expert" in self.roles or self.is_admin

    def can_access(
        self,
        access_level: str,
        allowed_groups: list[str],
        allowed_users: list[str],
    ) -> bool:
        """Check if user can access a chunk with given ACL.

        Access rules:
        - Admins always have access
        - Public content is accessible to all
        - Users in allowed_users have access
        - Users in any allowed_group have access
        """
        if self.is_admin:
            return True
        if access_level == "public":
            return True
        if self.id in allowed_users:
            return True
        return any(g in self.groups for g in allowed_groups)
