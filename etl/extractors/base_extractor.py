"""Abstract base class for all ETL extractors."""

import hashlib
import json
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExtractorConfig:
    source_name: str
    source_type: str  # confluence, jira, gitlab, book, chat, doc
    base_url: str
    api_token: str = ""
    max_pages: int = 1000
    batch_size: int = 50
    timeout: int = 30
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    source_id: str
    source_type: str
    title: str
    content: str
    content_type: str  # html, markdown, text
    metadata: dict[str, Any] = field(default_factory=dict)
    access_level: str = "internal"
    allowed_groups: list[str] = field(default_factory=list)
    allowed_users: list[str] = field(default_factory=list)
    version: str = ""
    extracted_at: str = ""
    links: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.extracted_at:
            self.extracted_at = datetime.now(UTC).isoformat()


class BaseExtractor(ABC):
    """All extractors must implement this interface."""

    def __init__(self, config: ExtractorConfig):
        self.config = config

    @abstractmethod
    async def extract(self) -> AsyncIterator[ExtractedDocument]:
        """Yield extracted documents."""

    @abstractmethod
    async def validate_connection(self) -> bool:
        """Test connectivity to the source."""

    @abstractmethod
    def should_process(self, doc: ExtractedDocument, last_hash: str) -> bool:
        """Check if document needs processing (incremental)."""

    def compute_hash(self, content: str) -> str:
        """SHA-256 hash for change detection."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _truncate_text(self, text: str, max_length: int = 10000) -> str:
        """Truncate text to a maximum length for logging/metadata."""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."


class SyncExtractor:
    """Mixin providing shared sync methods for legacy extractors.

    ConfluenceExtractor, JiraExtractor, GitLabExtractor inherit from
    this to avoid duplicating ``_check_shutdown``, ``_interruptible_sleep``,
    ``_save_wal``, and the shutdown event management.
    """

    def _init_sync_extractor(self, config: dict[str, Any]) -> None:
        """Initialise shared sync extractor state.

        Called from the concrete extractor's ``__init__``.
        """
        self._shutdown_event: threading.Event | None = None
        self.wal_path = Path(config.get("wal_file", "./wal/default_wal.json"))
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self.wal_data: dict[str, Any] = self._load_wal(config)

    def _load_wal(self, config: dict[str, Any]) -> dict[str, Any]:
        """Load WAL file with configurable defaults.

        Subclasses may override to change the default WAL structure.
        """
        default = config.get("_wal_default", {"last_run": None})
        if self.wal_path.exists():
            try:
                with open(self.wal_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("WAL file %s corrupted: %s. Reinitializing.", self.wal_path, e)
                return default
        return default

    def _save_wal(self) -> None:
        """Persist WAL data to disk."""
        with open(self.wal_path, "w") as f:
            json.dump(self.wal_data, f, indent=2)

    def _check_shutdown(self) -> None:
        """Raise InterruptedError if shutdown has been requested."""
        if self._shutdown_event and self._shutdown_event.is_set():
            raise InterruptedError("Shutdown requested")

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that is interrupted by a shutdown signal."""
        if self._shutdown_event and self._shutdown_event.wait(timeout=seconds):
            raise InterruptedError("Shutdown during sleep")
