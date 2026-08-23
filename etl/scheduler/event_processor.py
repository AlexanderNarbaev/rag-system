# etl/scheduler/event_processor.py
"""Real event processing for the event-driven streaming pipeline.

Converts webhook events (Confluence, GitLab) into documents and runs them
through the standard ETL chain: chunk (MDKeyChunker) → enrich (ChunkEnricher,
optional) → index (QdrantHybridIndexer). Deletion events (page_removed,
page_deleted) remove existing chunks from Qdrant and clear the local version
store.

Graceful degradation:
- Missing embedder/Qdrant at init → processing deferred (event not ACKed,
  retried later by the consumer group).
- Enrichment failure → chunk is indexed with basic metadata only.
- Events without indexable content (comments, unknown types) → skipped and
  acknowledged so they do not poison the pending queue.
- Deletion failures are logged and return False so the event can be retried.

See Also:
    - etl/scheduler/streaming_pipeline.py — batch-mode equivalent wiring
    - etl/scheduler/stream_consumer.py — base Redis Streams consumer
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from etl.scheduler.stream_consumer import StreamConsumer

logger = logging.getLogger("EventProcessor")

# Event types that carry no indexable content — acknowledged without processing.
_SKIP_EVENT_TYPES = frozenset(
    {
        "comment_created",
        "comment_updated",
        "comment_removed",
    }
)

# Event types that signal a document should be removed from the index.
_DELETE_EVENT_TYPES = frozenset({"page_removed", "page_deleted"})


class EventProcessor:
    """Processes a single stream event through chunk → enrich → index.

    Components are created lazily from the ETL YAML config so the processor
    can start (and retry) even when Qdrant or the embedding service is
    temporarily unavailable.

    Attributes:
        stats: Processing counters (processed, skipped, failed, chunks_indexed).

    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._chunker: Any = None
        self._indexer: Any = None
        self._enricher: Any = None
        self._enricher_checked = False
        self.stats: dict[str, int] = {
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "chunks_indexed": 0,
        }

    # ── Component wiring (mirrors StreamingPipeline config layout) ──────

    def _create_chunker(self) -> Any:
        """Create an MDKeyChunker from the ``chunking`` config section."""
        from etl.chunker.semantic_chunker import MDKeyChunker, MetadataEnricher, SemanticChunker

        chunker_cfg = self._config.get("chunking", {})
        base_chunker = SemanticChunker(
            max_tokens=int(chunker_cfg.get("max_tokens", 1500)) if chunker_cfg.get("max_tokens") != "auto" else 1500,
            overlap_tokens=chunker_cfg.get("overlap_tokens", 200),
            min_chunk_tokens=chunker_cfg.get("min_chunk_tokens", 100),
        )
        enricher = MetadataEnricher(
            use_slm=chunker_cfg.get("use_slm", False),
            slm_endpoint=chunker_cfg.get("slm_endpoint"),
        )
        return MDKeyChunker(base_chunker, enricher)

    def _create_embedder(self) -> Any:
        """Create a RemoteEmbedder from the ``remote_services.embedder`` section.

        Returns None when no remote endpoint is configured — the indexer will
        then fall back to a local SentenceTransformer model.
        """
        remote_cfg = self._config.get("remote_services", {})
        embedder_cfg = remote_cfg.get("embedder", {})
        endpoint = embedder_cfg.get("endpoint", embedder_cfg.get("url", ""))
        if not endpoint:
            return None

        from etl.indexer.remote_embedder import RemoteEmbedder, RetryConfig

        retry_cfg = RetryConfig(
            max_attempts=embedder_cfg.get("max_retries", 5),
            base_delay=embedder_cfg.get("retry_delay", 2.0),
            max_delay=embedder_cfg.get("retry_max_delay", 30.0),
            retryable_http_statuses=(429, 500, 502, 503, 504),
        )
        return RemoteEmbedder(
            endpoint=endpoint,
            model=embedder_cfg.get("model", ""),
            api_key=embedder_cfg.get("api_key", remote_cfg.get("api_key", "")),
            timeout=embedder_cfg.get("timeout", 60),
            max_batch_size=embedder_cfg.get("batch_size", 64),
            retry_config=retry_cfg,
            connection_pool_size=embedder_cfg.get("connection_pool_size", 16),
        )

    def _create_indexer(self) -> Any:
        """Create a QdrantHybridIndexer from the ``indexing`` config section."""
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        index_cfg = self._config.get("indexing", {})
        return QdrantHybridIndexer(
            host=index_cfg.get("qdrant_host", "localhost"),
            port=int(index_cfg.get("qdrant_port", 6333)),
            collection_name=index_cfg.get("collection_name", "knowledge_base"),
            embedder_model_name=index_cfg.get("embedder_model", "BAAI/bge-m3"),
            embedder_device=index_cfg.get("embedder_device", "cpu"),
            batch_size=index_cfg.get("batch_size", 100),
            embedder=self._create_embedder(),
        )

    def _ensure_components(self) -> bool:
        """Lazily initialize chunker and indexer.

        Returns True when both are ready. On failure, logs a warning and
        returns False so the caller can leave the event un-ACKed and retry
        later (components are retried on the next event).
        """
        if self._chunker is not None and self._indexer is not None:
            return True

        if self._chunker is None:
            try:
                self._chunker = self._create_chunker()
            except Exception as e:
                logger.warning("Chunker initialization failed: %s — event processing deferred", e)
                return False

        if self._indexer is None:
            try:
                self._indexer = self._create_indexer()
            except Exception as e:
                logger.warning("Indexer initialization failed: %s — event processing deferred", e)
                return False

        if not self._enricher_checked:
            self._enricher_checked = True
            try:
                from etl.indexer.chunk_enricher import build_chunk_enricher_from_config

                self._enricher = build_chunk_enricher_from_config(self._config)
            except Exception as e:
                logger.warning("Chunk enricher unavailable: %s — continuing without enrichment", e)
                self._enricher = None

        return True

    # ── Event → document mapping ────────────────────────────────────────

    def _event_to_document(
        self,
        source: str,
        event_type: str,
        doc_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Map a webhook event to a document dict for the chunking pipeline.

        Returns None when the event carries no indexable content (caller
        should ACK it as a no-op). Deletion events are handled in
        ``process_event`` before this method is called.
        """
        if event_type in _SKIP_EVENT_TYPES:
            logger.info("Skipping non-indexable event: source=%s type=%s doc_id=%s", source, event_type, doc_id)
            return None

        if source == "confluence":
            return self._confluence_document(event_type, doc_id, payload)
        if source == "gitlab":
            return self._gitlab_document(event_type, doc_id, payload)

        logger.warning("Unsupported event source: %s (doc_id=%s)", source, doc_id)
        return None

    @staticmethod
    def _normalize_document_id(source: str, doc_id: str) -> str:
        """Prefix a raw document id with its source type.

        Mirrors the id construction in ``_confluence_document`` and
        ``_gitlab_document``.
        """
        prefix = f"{source}_"
        if str(doc_id).startswith(prefix):
            return str(doc_id)
        return f"{prefix}{doc_id}"

    @staticmethod
    def _confluence_document(event_type: str, doc_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Build a document from a Confluence page event payload."""
        page = payload.get("page", payload)
        title = page.get("title", "")
        content = (
            page.get("body", {}).get("storage", {}).get("value")
            or page.get("body", {}).get("view", {}).get("value")
            or page.get("body_storage_raw")
            or ""
        )
        if not content.strip():
            logger.info("Confluence %s: page=%s has no content — skipping", event_type, doc_id)
            return None

        version = page.get("version", {})
        return {
            "id": doc_id if str(doc_id).startswith("confluence_") else f"confluence_{doc_id}",
            "source_type": "confluence",
            "title": title,
            "content": content,
            "content_type": "html",
            "metadata": {
                "version": str(version.get("number", "latest")) if isinstance(version, dict) else str(version),
                "page_id": str(page.get("id", doc_id)),
                "space_key": page.get("space", {}).get("key", "") if isinstance(page.get("space"), dict) else "",
                "event_type": event_type,
            },
        }

    @staticmethod
    def _gitlab_document(event_type: str, doc_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Build a document from a GitLab event payload (push, MR, wiki)."""
        project = payload.get("project", {})
        project_name = project.get("name", doc_id) if isinstance(project, dict) else doc_id

        if event_type == "push":
            parts: list[str] = []
            for commit in payload.get("commits", [])[:100]:
                message = commit.get("message", "")
                if message:
                    parts.append(message)
                for diff in commit.get("diff", [])[:5]:
                    parts.append(f"{diff.get('new_path', '')}: {diff.get('diff', '')[:200]}")
            content = "\n".join(parts)
            if not content.strip():
                logger.info("GitLab push: project=%s has no commit content — skipping", doc_id)
                return None
            return {
                "id": doc_id if str(doc_id).startswith("gitlab_") else f"gitlab_push_{doc_id}",
                "source_type": "gitlab_commit",
                "title": f"Push to {project_name}",
                "content": content,
                "content_type": "markdown",
                "metadata": {"project": project_name, "event_type": event_type},
            }

        if event_type in ("merge_request", "wiki_page"):
            attrs = payload.get("object_attributes", {})
            title = attrs.get("title", "")
            content = attrs.get("description", "") or attrs.get("content", "") or title
            if not str(content).strip():
                logger.info("GitLab %s: id=%s has no content — skipping", event_type, doc_id)
                return None
            prefix = "gitlab_mr" if event_type == "merge_request" else "gitlab_wiki"
            return {
                "id": doc_id if str(doc_id).startswith("gitlab_") else f"{prefix}_{doc_id}",
                "source_type": "gitlab_merge_request" if event_type == "merge_request" else "gitlab_wiki",
                "title": title,
                "content": str(content),
                "content_type": "markdown",
                "metadata": {"project": project_name, "event_type": event_type},
            }

        logger.info("Unsupported GitLab event type: %s (doc_id=%s) — skipping", event_type, doc_id)
        return None

    # ── Processing ──────────────────────────────────────────────────────

    @staticmethod
    def _normalize_event(event: dict[Any, Any]) -> dict[str, Any]:
        """Decode bytes keys/values from raw Redis Stream entries."""
        normalized: dict[str, Any] = {}
        for key, value in event.items():
            str_key = key.decode() if isinstance(key, bytes) else str(key)
            normalized[str_key] = value.decode() if isinstance(value, bytes) else value
        return normalized

    def _enrich_chunks(self, chunk_dicts: list[dict[str, Any]]) -> None:
        """Best-effort SLM enrichment of chunk dicts (in-place)."""
        if self._enricher is None:
            return
        for ch in chunk_dicts:
            try:
                result = self._enricher.enrich(ch.get("text", ""), ch.get("metadata", {}))
                if result.get("keywords"):
                    ch["keywords"] = result["keywords"]
                if result.get("entities"):
                    ch["entities"] = result["entities"]
                if result.get("hyde_questions"):
                    ch["hypothetical_questions"] = result["hyde_questions"]
                if result.get("summary"):
                    ch["summary"] = result["summary"]
            except Exception as e:
                logger.debug("Chunk enrichment failed for %s: %s", ch.get("hash", "?"), e)

    def _version_store(self) -> Any:
        """Build a ChunkVersionStore from config paths or sane defaults."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        indexing_cfg = self._config.get("indexing", {})
        hot_dir = indexing_cfg.get("hot_dir", "./data/etl/versions/hot")
        cold_dir = indexing_cfg.get("cold_dir", "./data/etl/versions/cold")
        wal_path = indexing_cfg.get("version_wal", "./data/etl/versions/wal.json")
        return ChunkVersionStore(
            hot_dir=Path(hot_dir),
            cold_dir=Path(cold_dir),
            wal_path=Path(wal_path),
        )

    def _delete_document(self, source: str, doc_id: str) -> bool:
        """Remove all indexed chunks for a document and clear its version store.

        Returns True when the Qdrant deletion succeeded (including the case
        where no points matched). Returns False when components are unavailable
        or Qdrant reported an error, so the event can be retried.
        """
        document_id = self._normalize_document_id(source, doc_id)

        if not self._ensure_components():
            return False

        try:
            deleted = self._indexer.delete_by_source_id(document_id)
        except Exception as e:
            logger.error("Failed to delete document %s from index: %s", document_id, e)
            return False

        try:
            version_store = self._version_store()
            version_store.reset(document_id)
        except Exception as e:
            logger.warning("Failed to reset version store for %s: %s", document_id, e)

        logger.info("Deleted document %s (%d points)", document_id, deleted)
        return True

    def process_event(self, event: dict[Any, Any]) -> bool:
        """Process a single event: map to document, chunk, enrich, index.

        Deletion events (``page_removed``, ``page_deleted``) are routed to
        ``_delete_document`` instead of the chunking pipeline.

        Returns True when the event was indexed, deleted, or intentionally
        skipped (safe to ACK). Returns False on retryable failures (component
        unavailable, indexing/deletion error) so the message stays pending.
        """
        event = self._normalize_event(event)

        source = event.get("source", "")
        event_type = event.get("event_type", "")
        doc_id = str(event.get("doc_id", ""))
        payload_raw = event.get("payload", "{}")

        if not source:
            logger.warning("Event without source, skipping: %s", event)
            return False

        try:
            payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid payload JSON for event doc_id=%s", doc_id)
            return False

        if event_type in _DELETE_EVENT_TYPES and source in ("confluence", "gitlab"):
            if self._delete_document(source, doc_id):
                self.stats["processed"] += 1
                return True
            self.stats["failed"] += 1
            return False

        document = self._event_to_document(source, event_type, doc_id, payload)
        if document is None:
            self.stats["skipped"] += 1
            return True

        if not self._ensure_components():
            self.stats["failed"] += 1
            return False

        try:
            chunks = self._chunker.process_document(
                document["content"],
                document.get("content_type", "html"),
                {
                    "source_type": document["source_type"],
                    "source_id": document["id"],
                    "version": document.get("metadata", {}).get("version", "latest"),
                    "doc_title": document.get("title", ""),
                },
            )
        except Exception as e:
            logger.error("Chunking failed for %s: %s", document["id"], e)
            self.stats["failed"] += 1
            return False

        chunk_dicts = [ch.__dict__ for ch in chunks]
        if not chunk_dicts:
            logger.info("No chunks produced for %s — acknowledging as no-op", document["id"])
            self.stats["skipped"] += 1
            return True

        self._enrich_chunks(chunk_dicts)

        try:
            indexed = self._indexer.index_chunks(chunk_dicts)
        except Exception as e:
            logger.error("Indexing failed for %s: %s", document["id"], e)
            self.stats["failed"] += 1
            return False

        if indexed == 0:
            logger.warning("No chunks indexed for %s — will retry", document["id"])
            self.stats["failed"] += 1
            return False

        self.stats["processed"] += 1
        self.stats["chunks_indexed"] += indexed
        logger.info(
            "Event processed: source=%s type=%s doc=%s chunks=%d indexed=%d",
            source,
            event_type,
            document["id"],
            len(chunk_dicts),
            indexed,
        )
        return True


class ProcessingStreamConsumer(StreamConsumer):
    """StreamConsumer that routes events through EventProcessor.

    The base class handles Redis mechanics (XREADGROUP, ACK, pending claims);
    this subclass replaces the stub per-source handlers with the real
    chunk → enrich → index pipeline.
    """

    def __init__(
        self,
        *args: Any,
        processor: EventProcessor | None = None,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._processor = processor if processor is not None else EventProcessor(config or {})

    @property
    def processor(self) -> EventProcessor:
        """Return the underlying EventProcessor."""
        return self._processor

    def process_event(self, event: dict[Any, Any]) -> bool:
        """Process an event through the real chunk → enrich → index chain."""
        return self._processor.process_event(event)
