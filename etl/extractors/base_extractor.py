"""Abstract base class for all ETL extractors."""

import hashlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ExtractorConfig:
  source_name: str
  source_type: str  # confluence, jira, gitlab, book, chat, doc
  base_url: str
  api_token: str = ""
  max_pages: int = 1000
  batch_size: int = 50
  timeout: int = 30
  exclude_patterns: list [str] = field (default_factory = list)


@dataclass
class ExtractedDocument:
  source_id: str
  source_type: str
  title: str
  content: str
  content_type: str  # html, markdown, text
  metadata: dict = field (default_factory = dict)
  access_level: str = "internal"
  version: str = ""
  extracted_at: str = ""
  links: list [dict] = field (default_factory = list)

  def __post_init__ (self):
    if not self.extracted_at:
      self.extracted_at = datetime.now (UTC).isoformat ()


class BaseExtractor (ABC):
  """All extractors must implement this interface."""

  def __init__ (self, config: ExtractorConfig):
    self.config = config

  @abstractmethod
  async def extract (self) -> AsyncIterator [ExtractedDocument]:
    """Yield extracted documents."""

  @abstractmethod
  async def validate_connection (self) -> bool:
    """Test connectivity to the source."""

  @abstractmethod
  def should_process (self, doc: ExtractedDocument, last_hash: str) -> bool:
    """Check if document needs processing (incremental)."""

  def compute_hash (self, content: str) -> str:
    """SHA-256 hash for change detection."""
    return hashlib.sha256 (content.encode ("utf-8")).hexdigest ()

  def _truncate_text (self, text: str, max_length: int = 10000) -> str:
    """Truncate text to a maximum length for logging/metadata."""
    if len (text) <= max_length:
      return text
    return text [:max_length] + "..."
