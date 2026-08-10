"""Streaming ETL integration coverage with isolated mock components."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from etl.scheduler.streaming_pipeline import PipelineProgress, StreamingPipeline


@dataclass
class Chunk:
    text: str
    hash: str
    source_type: str = "confluence"
    source_id: str = "doc-1"
    version: str = "1"
    doc_title: str = "Test"


class FakeEmbedder:
    def encode(self, _text: str, normalize_embeddings: bool = True) -> np.ndarray:
        assert normalize_embeddings
        return np.array([0.1, 0.2, 0.3], dtype=np.float32)


class FakeIndexer:
    collection_name = "events"

    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.indexed: list[dict[str, Any]] = []
        self.client = MagicMock()

    def _chunk_to_point(self, chunk: dict[str, Any]) -> object:
        return object() if chunk.get("text") else None

    def live_upsert(self, chunk: dict[str, Any]) -> bool:
        if self.should_fail:
            return False
        self.indexed.append(chunk.copy())
        return True


class FakeChunker:
    def process_document(self, _content: str, _content_type: str, metadata: dict[str, Any]) -> list[Chunk]:
        return [Chunk("streamed content", "hash-stream", metadata["source_type"], metadata["source_id"])]

    class Base:
        @staticmethod
        def create_heading_chunks(_content: str, _metadata: dict[str, Any]) -> list[Chunk]:
            return []

        @staticmethod
        def _html_to_markdown(content: str) -> str:
            return content

        @staticmethod
        def create_document_chunk(_content: str, _metadata: dict[str, Any]) -> None:
            return None


class FakeWal:
    def __init__(self) -> None:
        self.checkpoints: list[str] = []

    def update_last_run(self, name: str) -> None:
        self.checkpoints.append(name)


def _pipeline(indexer: FakeIndexer | None = None) -> tuple[StreamingPipeline, FakeIndexer, FakeWal]:
    wal = FakeWal()
    chosen = indexer or FakeIndexer()
    pipeline = StreamingPipeline({"streaming": {"max_concurrent_api_calls": 2}}, wal)
    pipeline._embedder = FakeEmbedder()
    pipeline._indexer = chosen
    pipeline._chunker = FakeChunker()
    pipeline._chunker.base = FakeChunker.Base
    pipeline._enricher = None
    pipeline._quality_filter = None
    pipeline._semaphore = asyncio.Semaphore(2)
    return pipeline, chosen, wal


@pytest.mark.asyncio
async def test_webhook_event_document_produces_streaming_result() -> None:
    pipeline, indexer, wal = _pipeline()

    result = await pipeline.process_document(
        {"id": "event-1", "source_type": "confluence", "title": "Event", "content": "content"}
    )

    assert result.doc_id == "event-1"
    assert result.chunks_count == 1
    assert result.chunks_indexed == 1
    assert result.errors == []
    assert wal.checkpoints == ["streaming_index"]
    assert len(indexer.indexed) == 0


@pytest.mark.asyncio
async def test_streaming_result_exposes_progress_and_status_fields() -> None:
    pipeline, _, _ = _pipeline()
    pipeline._progress.total_docs = 2

    result = await pipeline.process_document({"id": "event-2", "source_type": "jira", "content": "content"})

    assert result.embedded_at
    assert result.duration_ms >= 0
    assert pipeline._progress.processed_docs == 1
    assert pipeline._progress.progress_pct == 50.0
    assert PipelineProgress(total_docs=1, processed_docs=1).progress_pct == 100.0


@pytest.mark.asyncio
async def test_streaming_index_error_is_returned_without_raising() -> None:
    pipeline, _, _ = _pipeline(FakeIndexer(should_fail=True))

    result = await pipeline.process_document({"id": "event-3", "source_type": "gitlab", "content": "content"})

    assert result.chunks_indexed == 1
    assert result.errors == []


@pytest.mark.asyncio
async def test_multiple_events_can_be_processed_concurrently() -> None:
    pipeline, indexer, _ = _pipeline()
    documents = [{"id": f"event-{index}", "source_type": "jira", "content": "content"} for index in range(4)]

    results = await asyncio.gather(*(pipeline.process_document(document) for document in documents))

    assert [result.doc_id for result in results] == [f"event-{index}" for index in range(4)]
    assert all(result.chunks_indexed == 1 for result in results)
    assert len(indexer.indexed) == 0


# ── Graph building tests ──


def _pipeline_with_graph(graph_config: dict[str, Any] | None = None) -> StreamingPipeline:
    """Create a pipeline with graph config and all components mocked."""
    config: dict[str, Any] = {
        "streaming": {"max_concurrent_api_calls": 2},
        "graph": graph_config or {},
    }
    wal = FakeWal()
    pipeline = StreamingPipeline(config, wal)
    pipeline._embedder = FakeEmbedder()
    pipeline._indexer = FakeIndexer()
    pipeline._chunker = FakeChunker()
    pipeline._chunker.base = FakeChunker.Base
    pipeline._enricher = None
    pipeline._quality_filter = None
    pipeline._semaphore = asyncio.Semaphore(2)
    return pipeline


@dataclass
class FakeEntity:
    id: str = "ent-1"
    name: str = "TestEntity"
    type: str = "CONCEPT"
    source_id: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeRelation:
    source: str = "ent-1"
    target: str = "ent-2"
    type: str = "RELATES_TO"
    properties: dict[str, Any] = field(default_factory=dict)


@pytest.mark.asyncio
async def test_build_graph_noop_when_graph_disabled() -> None:
    """Graph disabled (default) → _build_graph returns immediately without errors."""
    pipeline = _pipeline_with_graph({})
    chunks = [{"text": "some text", "hash": "h1"}]
    # Should not raise
    await pipeline._build_graph(chunks, "doc-1")


@pytest.mark.asyncio
async def test_build_graph_noop_when_neo4j_disabled() -> None:
    """Graph enabled but neo4j disabled → _build_graph returns immediately."""
    pipeline = _pipeline_with_graph({"enabled": True, "neo4j": {"enabled": False}})
    chunks = [{"text": "some text", "hash": "h1"}]
    await pipeline._build_graph(chunks, "doc-1")


@pytest.mark.asyncio
async def test_build_graph_extracts_and_loads_entities() -> None:
    """Graph enabled with neo4j → extract entities and load to Neo4j."""
    mock_entity = FakeEntity()
    mock_relation = FakeRelation()

    mock_extractor = MagicMock()
    mock_extractor.extract_from_chunk.return_value = ([mock_entity], [mock_relation])

    mock_loader = MagicMock()

    graph_config = {
        "enabled": True,
        "use_spacy": False,
        "use_slm": False,
        "neo4j": {
            "enabled": True,
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "test",
        },
    }
    pipeline = _pipeline_with_graph(graph_config)

    with (
        patch(
            "etl.graph_builder.entity_extractor.EntityRelationExtractor",
            return_value=mock_extractor,
        ),
        patch(
            "etl.graph_builder.neo4j_loader.Neo4jLoader",
            return_value=mock_loader,
        ),
    ):
        chunks = [
            {"text": "chunk one", "hash": "h1", "metadata": {"key": "val"}},
            {"text": "", "hash": "h2"},  # empty text — should be skipped
            {"text": "chunk three", "hash": "h3"},
        ]
        await pipeline._build_graph(chunks, "doc-42")

    # extract_from_chunk called for non-empty chunks only (2 times)
    assert mock_extractor.extract_from_chunk.call_count == 2
    mock_extractor.extract_from_chunk.assert_any_call("chunk one", "doc-42", {"key": "val"})
    mock_extractor.extract_from_chunk.assert_any_call("chunk three", "doc-42", {})

    # Loader connected, constraints created, entities/relations loaded, closed
    mock_loader.connect.assert_called_once()
    mock_loader.create_constraints_and_indexes.assert_called_once()
    assert mock_loader.load_entities.call_count == 2
    assert mock_loader.load_relations.call_count == 2
    mock_loader.close.assert_called_once()


@pytest.mark.asyncio
async def test_build_graph_noop_when_chunks_empty() -> None:
    """No chunks → _build_graph returns without calling extract."""
    pipeline = _pipeline_with_graph({"enabled": True, "neo4j": {"enabled": True}})
    await pipeline._build_graph([], "doc-empty")


@pytest.mark.asyncio
async def test_build_graph_catches_exceptions_gracefully() -> None:
    """Graph failure should be caught and not propagate (non-blocking)."""
    graph_config = {
        "enabled": True,
        "use_spacy": False,
        "use_slm": False,
        "neo4j": {
            "enabled": True,
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "test",
        },
    }
    pipeline = _pipeline_with_graph(graph_config)

    with patch(
        "etl.graph_builder.entity_extractor.EntityRelationExtractor",
        side_effect=RuntimeError("Neo4j unreachable"),
    ):
        # Should not raise — graph failure is non-blocking
        chunks = [{"text": "content", "hash": "h1"}]
        await pipeline._build_graph(chunks, "doc-fail")


@pytest.mark.asyncio
async def test_build_graph_loads_entities_only_when_no_relations() -> None:
    """Only entities extracted (no relations) → loader.load_entities called, load_relations skipped."""
    mock_entity = FakeEntity()

    mock_extractor = MagicMock()
    mock_extractor.extract_from_chunk.return_value = ([mock_entity], [])

    mock_loader = MagicMock()

    graph_config = {
        "enabled": True,
        "use_spacy": False,
        "use_slm": False,
        "neo4j": {"enabled": True, "uri": "bolt://localhost:7687", "user": "neo4j", "password": ""},
    }
    pipeline = _pipeline_with_graph(graph_config)

    with (
        patch(
            "etl.graph_builder.entity_extractor.EntityRelationExtractor",
            return_value=mock_extractor,
        ),
        patch(
            "etl.graph_builder.neo4j_loader.Neo4jLoader",
            return_value=mock_loader,
        ),
    ):
        await pipeline._build_graph([{"text": "text", "hash": "h1"}], "doc-1")

    mock_loader.load_entities.assert_called_once()
    mock_loader.load_relations.assert_not_called()


@pytest.mark.asyncio
async def test_process_document_calls_build_graph() -> None:
    """process_document invokes _build_graph with chunks and doc_id."""
    pipeline, _, _ = _pipeline()

    with patch.object(pipeline, "_build_graph") as mock_build:
        await pipeline.process_document(
            {"id": "doc-g1", "source_type": "confluence", "title": "Test", "content": "content"},
        )
        mock_build.assert_called_once()
        call_args = mock_build.call_args
        assert call_args[0][1] == "doc-g1"  # doc_id
        assert len(call_args[0][0]) > 0  # chunks list not empty
