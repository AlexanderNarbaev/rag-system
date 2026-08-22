# tests/etl/test_event_processor.py
"""Tests for EventProcessor — real chunk → enrich → index event handlers."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def config():
    """Minimal ETL config for EventProcessor."""
    return {
        "chunking": {"max_tokens": 1500, "overlap_tokens": 200, "min_chunk_tokens": 100},
        "indexing": {
            "qdrant_host": "localhost",
            "qdrant_port": 6333,
            "collection_name": "knowledge_base",
        },
        "remote_services": {"embedder": {"endpoint": ""}},
        "enrichment": {"enabled": False},
    }


@pytest.fixture
def confluence_event():
    """Confluence page_created event as read from a Redis Stream."""
    return {
        "source": "confluence",
        "event_type": "page_created",
        "doc_id": "123456",
        "timestamp": "2026-01-01T00:00:00Z",
        "payload": json.dumps(
            {
                "page": {
                    "id": "123456",
                    "title": "Deployment Guide",
                    "body": {"storage": {"value": "<p>How to deploy the RAG proxy service.</p>"}},
                    "version": {"number": 3},
                },
            },
        ),
    }


def _make_processor(config, chunks=None, indexed=1):
    """Build an EventProcessor with mocked chunker/indexer wired in."""
    from etl.scheduler.event_processor import EventProcessor

    processor = EventProcessor(config)
    chunker = MagicMock()
    default_chunks = [SimpleNamespace(hash="abc123", text="chunk text", title="t")]
    chunker.process_document.return_value = chunks if chunks is not None else default_chunks
    indexer = MagicMock()
    indexer.index_chunks.return_value = indexed
    processor._chunker = chunker
    processor._indexer = indexer
    return processor, chunker, indexer


class TestEventToDocument:
    """Event → document mapping."""

    def test_confluence_page_created(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        payload = {
            "page": {
                "id": "123",
                "title": "Guide",
                "body": {"storage": {"value": "<p>content</p>"}},
                "version": {"number": 2},
            },
        }
        doc = processor._event_to_document("confluence", "page_created", "123", payload)
        assert doc is not None
        assert doc["id"] == "confluence_123"
        assert doc["source_type"] == "confluence"
        assert doc["content_type"] == "html"
        assert doc["content"] == "<p>content</p>"
        assert doc["metadata"]["version"] == "2"

    def test_confluence_empty_content_returns_none(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        doc = processor._event_to_document("confluence", "page_created", "123", {"page": {"title": "Empty"}})
        assert doc is None

    def test_confluence_body_storage_raw_fallback(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        payload = {"page": {"id": "9", "title": "T", "body_storage_raw": "<p>raw</p>"}}
        doc = processor._event_to_document("confluence", "page_updated", "9", payload)
        assert doc is not None
        assert doc["content"] == "<p>raw</p>"

    def test_gitlab_push_event(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        payload = {
            "project": {"name": "rag"},
            "commits": [{"message": "fix: retrieval bug", "diff": []}],
        }
        doc = processor._event_to_document("gitlab", "push", "rag", payload)
        assert doc is not None
        assert doc["source_type"] == "gitlab_commit"
        assert "fix: retrieval bug" in doc["content"]

    def test_gitlab_merge_request_event(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        payload = {
            "project": {"name": "rag"},
            "object_attributes": {"title": "Add feature", "description": "Details here"},
        }
        doc = processor._event_to_document("gitlab", "merge_request", "42", payload)
        assert doc is not None
        assert doc["source_type"] == "gitlab_merge_request"
        assert "Details here" in doc["content"]

    def test_gitlab_unknown_type_returns_none(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        doc = processor._event_to_document("gitlab", "pipeline", "1", {"project": {}})
        assert doc is None

    def test_skip_event_types_return_none(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        doc = processor._event_to_document("confluence", "page_removed", "1", {"page": {"title": "X"}})
        assert doc is None

    def test_unknown_source_returns_none(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        doc = processor._event_to_document("jira", "issue_created", "1", {})
        assert doc is None


class TestProcessEvent:
    """process_event success and failure paths."""

    def test_success_indexes_chunks(self, config, confluence_event):
        processor, chunker, indexer = _make_processor(config)

        result = processor.process_event(confluence_event)

        assert result is True
        chunker.process_document.assert_called_once()
        indexer.index_chunks.assert_called_once()
        assert processor.stats["processed"] == 1
        assert processor.stats["chunks_indexed"] == 1

    def test_missing_source_returns_false(self, config):
        processor, _, _ = _make_processor(config)
        assert processor.process_event({"event_type": "x", "payload": "{}"}) is False
        assert processor.stats["failed"] == 0  # rejected before processing

    def test_invalid_payload_json_returns_false(self, config):
        processor, _, _ = _make_processor(config)
        event = {"source": "confluence", "event_type": "page_created", "doc_id": "1", "payload": "not json"}
        assert processor.process_event(event) is False

    def test_skippable_event_returns_true_without_indexing(self, config):
        processor, chunker, indexer = _make_processor(config)
        event = {
            "source": "confluence",
            "event_type": "page_removed",
            "doc_id": "1",
            "payload": json.dumps({"page": {"title": "Gone"}}),
        }
        assert processor.process_event(event) is True
        chunker.process_document.assert_not_called()
        indexer.index_chunks.assert_not_called()
        assert processor.stats["skipped"] == 1

    def test_bytes_event_normalized(self, config, confluence_event):
        processor, _, indexer = _make_processor(config)
        bytes_event = {k.encode(): (v.encode() if isinstance(v, str) else v) for k, v in confluence_event.items()}
        assert processor.process_event(bytes_event) is True
        indexer.index_chunks.assert_called_once()

    def test_chunker_failure_returns_false(self, config, confluence_event):
        processor, chunker, indexer = _make_processor(config)
        chunker.process_document.side_effect = RuntimeError("chunk boom")

        assert processor.process_event(confluence_event) is False
        indexer.index_chunks.assert_not_called()
        assert processor.stats["failed"] == 1

    def test_indexer_failure_returns_false(self, config, confluence_event):
        processor, _, indexer = _make_processor(config)
        indexer.index_chunks.side_effect = ConnectionError("qdrant down")

        assert processor.process_event(confluence_event) is False
        assert processor.stats["failed"] == 1

    def test_zero_indexed_returns_false_for_retry(self, config, confluence_event):
        processor, _, indexer = _make_processor(config)
        indexer.index_chunks.return_value = 0

        assert processor.process_event(confluence_event) is False
        assert processor.stats["failed"] == 1

    def test_no_chunks_returns_true_noop(self, config, confluence_event):
        processor, _, indexer = _make_processor(config, chunks=[])

        assert processor.process_event(confluence_event) is True
        indexer.index_chunks.assert_not_called()
        assert processor.stats["skipped"] == 1

    def test_components_unavailable_returns_false(self, config, confluence_event):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        with patch.object(EventProcessor, "_create_chunker", side_effect=ImportError("no deps")):
            assert processor.process_event(confluence_event) is False
        assert processor.stats["failed"] == 1

    def test_enrichment_failure_does_not_block_indexing(self, config, confluence_event):
        processor, _, indexer = _make_processor(config)
        enricher = MagicMock()
        enricher.enrich.side_effect = RuntimeError("slm down")
        processor._enricher = enricher

        assert processor.process_event(confluence_event) is True
        indexer.index_chunks.assert_called_once()


class TestEnsureComponents:
    """Lazy component initialization and graceful degradation."""

    def test_enricher_none_when_disabled(self, config):
        processor, _, _ = _make_processor(config)
        assert processor._ensure_components() is True
        assert processor._enricher is None

    def test_indexer_init_failure_degrades(self, config):
        from etl.scheduler.event_processor import EventProcessor

        processor = EventProcessor(config)
        processor._chunker = MagicMock()
        with patch.object(EventProcessor, "_create_indexer", side_effect=Exception("qdrant unreachable")):
            assert processor._ensure_components() is False
        assert processor._indexer is None

    def test_enricher_init_failure_is_non_fatal(self, config):
        processor, _, _ = _make_processor(config)
        with patch(
            "etl.indexer.chunk_enricher.build_chunk_enricher_from_config",
            side_effect=RuntimeError("bad config"),
        ):
            assert processor._ensure_components() is True
        assert processor._enricher is None


class TestProcessingStreamConsumer:
    """ProcessingStreamConsumer wiring."""

    def test_delegates_to_processor(self, config, confluence_event):
        from etl.scheduler.event_processor import EventProcessor, ProcessingStreamConsumer

        processor = EventProcessor(config)
        processor.process_event = MagicMock(return_value=True)

        consumer = ProcessingStreamConsumer(redis_client=None, processor=processor)
        assert consumer.process_event(confluence_event) is True
        processor.process_event.assert_called_once_with(confluence_event)

    def test_creates_default_processor_from_config(self, config):
        from etl.scheduler.event_processor import EventProcessor, ProcessingStreamConsumer

        consumer = ProcessingStreamConsumer(redis_client=None, config=config)
        assert isinstance(consumer.processor, EventProcessor)

    def test_is_stream_consumer_subclass(self, config):
        from etl.scheduler.event_processor import ProcessingStreamConsumer
        from etl.scheduler.stream_consumer import StreamConsumer

        consumer = ProcessingStreamConsumer(redis_client=None, config=config)
        assert isinstance(consumer, StreamConsumer)
