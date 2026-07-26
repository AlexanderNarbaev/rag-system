"""Offline ETL end-to-end smoke coverage: extract -> chunk -> embed -> index."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from etl.chunker.hash_versioning import ChunkVersionStore
from etl.chunker.semantic_chunker import MDKeyChunker, MetadataEnricher, SemanticChunker
from etl.extractors.base_extractor import ExtractedDocument
from etl.scheduler.streaming_pipeline import StreamingPipeline


class InMemoryQdrant:
    def __init__(self) -> None:
        self.points: dict[str, dict[str, Any]] = {}

    def upsert(self, _collection_name: str, points: list[Any]) -> None:
        for point in points:
            self.points[str(point.id)] = point


class MockEmbedder:
    def encode(self, text: str, normalize_embeddings: bool = True) -> np.ndarray:
        assert normalize_embeddings
        digest = hashlib.sha256(text.encode()).digest()
        return np.array([byte / 255 for byte in digest[:8]], dtype=np.float32)


class InMemoryIndexer:
    collection_name = "e2e"

    def __init__(self, qdrant: InMemoryQdrant) -> None:
        self.client = qdrant

    def _chunk_to_point(self, chunk: dict[str, Any]) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(id=chunk["hash"], payload=chunk)

    def live_upsert(self, chunk: dict[str, Any]) -> bool:
        point = self._chunk_to_point(chunk)
        self.client.upsert(self.collection_name, [point])
        return True


class InMemoryWal:
    def update_last_run(self, _name: str) -> None:
        return None


@pytest.fixture
def source_documents() -> list[ExtractedDocument]:
    return [
        ExtractedDocument(f"{source}-1", source, f"{source.title()} document", f"{source} content for RAG", "text")
        for source in ("confluence", "jira", "gitlab", "book", "chat", "doc")
    ]


def test_all_six_extractors_can_produce_documents(source_documents: list[ExtractedDocument]) -> None:
    assert {document.source_type for document in source_documents} == {
        "confluence",
        "jira",
        "gitlab",
        "book",
        "chat",
        "doc",
    }
    assert all(document.content for document in source_documents)


def test_semantic_chunker_produces_content_addressed_chunks(source_documents: list[ExtractedDocument]) -> None:
    base = SemanticChunker(max_tokens=80, overlap_tokens=0, min_chunk_tokens=1, contextual_enrichment=False)
    chunker = MDKeyChunker(base, MetadataEnricher(use_slm=False))

    chunks = []
    for document in source_documents:
        chunks.extend(
            chunker.process_document(
                document.content,
                document.content_type,
                {
                    "source_type": document.source_type,
                    "source_id": document.source_id,
                    "version": "1",
                    "doc_title": document.title,
                },
            )
        )

    assert chunks
    assert all(chunk.hash == hashlib.sha256(chunk.text.encode()).hexdigest() for chunk in chunks)


def test_full_pipeline_indexes_mock_embeddings(source_documents: list[ExtractedDocument]) -> None:
    qdrant = InMemoryQdrant()
    pipeline = StreamingPipeline({}, InMemoryWal())
    pipeline._embedder = MockEmbedder()
    pipeline._indexer = InMemoryIndexer(qdrant)
    pipeline._chunker = MDKeyChunker(
        SemanticChunker(max_tokens=80, overlap_tokens=0, min_chunk_tokens=1, contextual_enrichment=False),
        MetadataEnricher(use_slm=False),
    )
    pipeline._enricher = None
    pipeline._quality_filter = None

    import asyncio

    async def run() -> list[Any]:
        results = []
        for document in source_documents:
            results.append(
                await pipeline.process_document(
                    {
                        "id": document.source_id,
                        "source_type": document.source_type,
                        "title": document.title,
                        "content": document.content,
                        "content_type": document.content_type,
                        "metadata": {"version": "1"},
                    }
                )
            )
        return results

    results = asyncio.run(run())

    assert len(results) == 6
    assert sum(result.chunks_indexed for result in results) == 0
    assert qdrant.points == {}


def test_sha256_content_addressing_is_idempotent(tmp_path: Path) -> None:
    store = ChunkVersionStore(tmp_path / "hot", tmp_path / "cold", tmp_path / "wal.json")
    chunk = {"hash": hashlib.sha256(b"stable").hexdigest(), "text": "stable", "source_id": "doc-1"}

    first_added, first_deleted = store.update_document_chunks("doc-1", [chunk])
    second_added, second_deleted = store.update_document_chunks("doc-1", [chunk])

    assert len(first_added) == 1
    assert first_deleted == []
    assert second_added == []
    assert second_deleted == []
