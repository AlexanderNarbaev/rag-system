"""Tests for etl/scheduler/streaming_pipeline.py."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from etl.scheduler.streaming_pipeline import (
    PipelineProgress,
    StreamingPipeline,
    StreamingResult,
)


class TestStreamingResult:
    def test_defaults(self) -> None:
        result = StreamingResult(source="confluence", doc_id="test_1")
        assert result.source == "confluence"
        assert result.doc_id == "test_1"
        assert result.chunks_count == 0
        assert result.chunks_indexed == 0
        assert result.errors == []
        assert result.duration_ms == 0.0
        assert result.embedded_at == ""

    def test_with_data(self) -> None:
        result = StreamingResult(
            source="jira",
            doc_id="jira_PROJ-1",
            chunks_count=5,
            chunks_indexed=4,
            errors=["Chunk 3 failed"],
            duration_ms=120.5,
            embedded_at="2025-01-01T00:00:00Z",
        )
        assert result.chunks_count == 5
        assert result.chunks_indexed == 4
        assert len(result.errors) == 1


class TestPipelineProgress:
    def test_initial_state(self) -> None:
        progress = PipelineProgress(total_docs=100)
        assert progress.total_docs == 100
        assert progress.processed_docs == 0
        assert progress.progress_pct == 0.0

    def test_partial_progress(self) -> None:
        progress = PipelineProgress(total_docs=100, processed_docs=50)
        assert progress.progress_pct == 50.0

    def test_zero_total(self) -> None:
        progress = PipelineProgress()
        assert progress.progress_pct == 0.0


class TestStreamingPipelineInit:
    def test_init_with_config(self) -> None:
        config: dict[str, Any] = {
            "remote_services": {
                "embedder": {
                    "endpoint": "http://embedder:8080/v1/embeddings",
                    "model": "bge-m3",
                    "timeout": 30,
                },
            },
            "indexing": {
                "qdrant_host": "localhost",
                "qdrant_port": 6333,
                "collection_name": "test_kb",
            },
            "chunking": {
                "max_tokens": 500,
                "overlap_tokens": 50,
                "use_slm": False,
            },
            "streaming": {
                "progress_interval": 10,
                "max_concurrent_api_calls": 5,
            },
        }
        wal = MagicMock()
        pipeline = StreamingPipeline(config, wal)
        assert pipeline._max_concurrent == 5
        assert pipeline._progress_interval == 10


class TestStreamingPipelineExtractDocuments:
    @pytest.fixture
    def sample_etl_config(self, tmp_path: Path) -> dict[str, Any]:
        source_dir = tmp_path / "raw_data" / "confluence"
        source_dir.mkdir(parents=True)
        page_dir = source_dir / "page_1"
        page_dir.mkdir()
        page_data = {
            "id": "12345",
            "title": "Test Page",
            "body_view_html": "<p>Hello World</p>",
            "body_storage_raw": "",
            "version": "3",
            "space": "DEV",
            "space_key": "DEV",
            "author": "tester",
            "contributors": [],
            "labels": ["rag"],
            "restrictions": {},
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        }
        (page_dir / "page.json").write_text(json.dumps(page_data))
        return {
            "confluence": {"output_dir": str(source_dir)},
            "jira": {"output_dir": str(tmp_path / "raw_data" / "jira")},
            "gitlab": {"output_dir": str(tmp_path / "raw_data" / "gitlab")},
        }

    def test_extract_confluence_docs(self, sample_etl_config: dict[str, Any]) -> None:
        pipeline = StreamingPipeline(sample_etl_config, MagicMock())
        docs = list(pipeline._extract_documents_generator())
        assert len(docs) == 1
        assert docs[0]["id"] == "confluence_12345"
        assert docs[0]["source_type"] == "confluence"
        assert docs[0]["content"] == "<p>Hello World</p>"
        assert docs[0]["metadata"]["space"] == "DEV"


class TestStreamingPipelineProcessDocument:
    @pytest.fixture
    def pipeline_with_mocks(self) -> StreamingPipeline:
        config: dict[str, Any] = {
            "remote_services": {
                "embedder": {
                    "endpoint": "http://embedder:8080/v1/embeddings",
                    "model": "bge-m3",
                    "timeout": 30,
                    "batch_size": 64,
                    "connection_pool_size": 4,
                },
            },
            "indexing": {
                "qdrant_host": "localhost",
                "qdrant_port": 6333,
                "collection_name": "test_kb",
            },
            "chunking": {
                "max_tokens": 1500,
                "overlap_tokens": 200,
                "use_slm": False,
            },
            "streaming": {
                "progress_interval": 50,
                "max_concurrent_api_calls": 3,
            },
        }
        wal = MagicMock()
        pipeline = StreamingPipeline(config, wal)

        # Create mock components
        mock_chunker = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.__dict__ = {
            "text": "test chunk text",
            "hash": "abc123",
            "title": "Test",
            "source_type": "confluence",
            "source_id": "test_1",
            "version": "latest",
            "doc_title": "Test Doc",
            "keywords": [],
            "entities": [],
            "summary": "",
            "hypothetical_questions": [],
            "semantic_key": "",
            "position": 0,
            "tokens_approx": 10,
            "parent_metadata": {},
            "original_text": "test chunk text",
            "enriched": False,
        }
        mock_chunker.process_document.return_value = [mock_chunk]
        pipeline._chunker = mock_chunker

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        pipeline._embedder = mock_embedder

        mock_indexer = MagicMock()
        mock_point = MagicMock()
        mock_indexer._chunk_to_point.return_value = mock_point
        mock_indexer.collection_name = "test_kb"
        pipeline._indexer = mock_indexer

        import asyncio

        pipeline._semaphore = asyncio.Semaphore(3)

        return pipeline

    def _sample_doc(self) -> dict[str, Any]:
        return {
            "id": "test_1",
            "source_type": "confluence",
            "title": "Test Document",
            "content": "<p>Test content for chunking.</p>",
            "content_type": "html",
            "metadata": {
                "version": "1.0",
                "space": "DEV",
            },
        }

    @pytest.mark.asyncio
    async def test_process_document_success(self, pipeline_with_mocks: StreamingPipeline) -> None:
        pipeline = pipeline_with_mocks
        doc = self._sample_doc()

        result = await pipeline.process_document(doc)

        assert result.source == "confluence"
        assert result.doc_id == "test_1"
        assert result.chunks_count == 1
        assert result.chunks_indexed == 1
        assert result.errors == []

        pipeline._chunker.process_document.assert_called_once()
        pipeline._embedder.encode.assert_called_once_with("test chunk text", normalize_embeddings=True)
        pipeline._indexer._chunk_to_point.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_document_chunking_error(self, pipeline_with_mocks: StreamingPipeline) -> None:
        pipeline = pipeline_with_mocks
        pipeline._chunker.process_document.side_effect = ValueError("Bad HTML")

        doc = self._sample_doc()
        result = await pipeline.process_document(doc)

        assert result.errors
        assert "Bad HTML" in result.errors[0]

    @pytest.mark.asyncio
    async def test_progress_increments(self, pipeline_with_mocks: StreamingPipeline) -> None:
        pipeline = pipeline_with_mocks
        doc = self._sample_doc()

        assert pipeline._progress.processed_docs == 0
        await pipeline.process_document(doc)
        assert pipeline._progress.processed_docs == 1
        assert pipeline._progress.total_chunks == 1
        assert pipeline._progress.indexed_chunks == 1

    @pytest.mark.asyncio
    async def test_shutdown_flag_respected(self, pipeline_with_mocks: StreamingPipeline) -> None:
        import threading

        pipeline = pipeline_with_mocks
        shutdown = threading.Event()
        shutdown.set()
        pipeline._shutdown_event = shutdown

        [self._sample_doc(), self._sample_doc()]
        pipeline._chunker.process_document.reset_mock()

        count = 0
        async for _ in pipeline.run():
            count += 1
        assert count == 0


class TestStreamingPipelineRun:
    @pytest.fixture
    def pipeline_for_run(self, tmp_path: Path) -> StreamingPipeline:
        source_dir = tmp_path / "raw_data" / "confluence"
        source_dir.mkdir(parents=True)
        page_dir = source_dir / "page_1"
        page_dir.mkdir()
        page_data = {
            "id": "999",
            "title": "Test",
            "body_view_html": "<p>Hello</p>",
            "body_storage_raw": "",
            "version": "1",
            "space": "DEV",
            "space_key": "DEV",
            "author": "tester",
            "contributors": [],
            "labels": [],
            "restrictions": {},
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }
        (page_dir / "page.json").write_text(json.dumps(page_data))

        config: dict[str, Any] = {
            "confluence": {"output_dir": str(source_dir)},
            "jira": {"output_dir": str(tmp_path / "raw_data" / "jira")},
            "gitlab": {"output_dir": str(tmp_path / "raw_data" / "gitlab")},
            "remote_services": {
                "embedder": {
                    "endpoint": "http://embedder:8080/v1/embeddings",
                    "model": "bge-m3",
                    "timeout": 30,
                    "batch_size": 64,
                    "connection_pool_size": 4,
                },
            },
            "indexing": {
                "qdrant_host": "localhost",
                "qdrant_port": 6333,
                "collection_name": "test_kb",
            },
            "chunking": {
                "max_tokens": 1500,
                "overlap_tokens": 200,
                "use_slm": False,
            },
            "streaming": {
                "progress_interval": 50,
                "max_concurrent_api_calls": 3,
            },
        }
        wal = MagicMock()
        pipeline = StreamingPipeline(config, wal)

        mock_chunker = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.__dict__ = {
            "text": "test content",
            "hash": "hash1",
            "title": "Test",
            "source_type": "confluence",
            "source_id": "confluence_999",
            "version": "1",
            "doc_title": "Test",
            "keywords": [],
            "entities": [],
            "summary": "",
            "hypothetical_questions": [],
            "semantic_key": "",
            "position": 0,
            "tokens_approx": 10,
            "parent_metadata": {},
            "original_text": "test content",
            "enriched": False,
        }
        mock_chunker.process_document.return_value = [mock_chunk]
        pipeline._chunker = mock_chunker

        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        pipeline._embedder = mock_embedder

        mock_indexer = MagicMock()
        mock_point = MagicMock()
        mock_indexer._chunk_to_point.return_value = mock_point
        mock_indexer.collection_name = "test_kb"
        pipeline._indexer = mock_indexer

        import asyncio

        pipeline._semaphore = asyncio.Semaphore(3)

        return pipeline

    @pytest.mark.asyncio
    async def test_run_processes_all_docs(self, pipeline_for_run: StreamingPipeline) -> None:
        pipeline = pipeline_for_run
        results: list[StreamingResult] = []
        async for result in pipeline.run():
            results.append(result)
        assert len(results) == 1
        assert results[0].source == "confluence"
        assert results[0].doc_id == "confluence_999"

    @pytest.mark.asyncio
    async def test_run_with_errors_continues(self, pipeline_for_run: StreamingPipeline) -> None:
        pipeline = pipeline_for_run
        pipeline._chunker.process_document.side_effect = [ValueError("fail"), MagicMock()]
        results: list[StreamingResult] = []
        async for result in pipeline.run():
            results.append(result)
        assert len(results) >= 1


class TestMainStreaming:
    @pytest.mark.asyncio
    async def test_main_streaming_runs(self) -> None:
        config: dict[str, Any] = {
            "confluence": {"output_dir": "./raw_data/confluence"},
            "jira": {"output_dir": "./raw_data/jira"},
            "gitlab": {"output_dir": "./raw_data/gitlab"},
            "remote_services": {
                "embedder": {
                    "endpoint": "http://embedder:8080/v1/embeddings",
                    "model": "bge-m3",
                    "timeout": 30,
                },
            },
            "indexing": {
                "qdrant_host": "localhost",
                "qdrant_port": 6333,
                "collection_name": "test_kb",
            },
            "chunking": {
                "max_tokens": 1500,
                "overlap_tokens": 200,
                "use_slm": False,
            },
            "streaming": {
                "progress_interval": 50,
                "max_concurrent_api_calls": 3,
            },
        }
        wal = MagicMock()

        with patch.object(StreamingPipeline, "_init_components", new_callable=AsyncMock):
            pipeline = StreamingPipeline(config, wal)
            pipeline._indexer = MagicMock()
            pipeline._indexer.create_collection = MagicMock(return_value=True)
            pipeline._extract_documents_generator = lambda: iter([])

            results = await pipeline._run_collect()
            assert results == []
