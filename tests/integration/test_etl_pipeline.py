# tests/integration/test_etl_pipeline.py
"""Integration tests for the ETL pipeline (extract -> chunk -> index).

Tests the full pipeline with mocks for Confluence, Jira extractors,
SemanticChunker, QdrantHybridIndexer, and EntityRelationExtractor.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "etl"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestFullExtractChunkIndexPipeline:
    """Tests for the full extract -> chunk -> index ETL pipeline."""

    def make_sample_chunk(self, idx, source_type, source_id, version, text):
        return {
            "hash": f"hash_{source_type}_{idx}",
            "text": text,
            "title": f"Section {idx}",
            "source_type": source_type,
            "source_id": source_id,
            "version": version,
            "doc_title": f"Document {source_id}",
            "keywords": ["test"],
            "entities": [],
            "summary": "",
            "position": idx,
            "semantic_key": "",
        }

    @pytest.fixture
    def mock_confluence_extractor(self):
        """Mock ConfluenceExtractor returning sample pages."""
        with patch("etl.extractors.confluence.ConfluenceExtractor") as mock:
            instance = mock.return_value
            instance.run.return_value = None
            yield mock

    @pytest.fixture
    def mock_chunker(self):
        """Mock SemanticChunker + MDKeyChunker producing sample chunks."""
        with (
            patch("etl.chunker.semantic_chunker.SemanticChunker"),
            patch("etl.chunker.semantic_chunker.MetadataEnricher"),
        ):

            class FakeChunk:
                def __init__(self, idx, source_metadata):
                    self.text = f"Fake chunk text {idx}"
                    self.hash = f"hash_{idx}"
                    self.__dict__ = {
                        "hash": f"hash_{idx}",
                        "text": f"Fake chunk text {idx}",
                        "title": "Section",
                        "source_type": source_metadata.get("source_type", ""),
                        "source_id": source_metadata.get("source_id", ""),
                        "version": source_metadata.get("version", ""),
                        "doc_title": source_metadata.get("doc_title", ""),
                        "keywords": [],
                        "entities": [],
                        "summary": "",
                        "position": idx,
                        "semantic_key": f"key_{idx}",
                    }

            with patch("etl.chunker.semantic_chunker.MDKeyChunker") as mock_md:

                def process_doc(content, content_type, source_metadata):
                    return [FakeChunk(i, source_metadata) for i in range(3)]

                mock_md.return_value.process_document.side_effect = process_doc
                yield mock_md

    @pytest.fixture
    def mock_qdrant_indexer(self):
        """Mock QdrantHybridIndexer tracking indexed chunks."""
        with patch("etl.indexer.qdrant_hybrid.QdrantHybridIndexer") as mock:
            instance = mock.return_value
            instance.create_collection.return_value = True
            instance.index_chunks.return_value = 5
            instance.get_chunk_count.return_value = 5
            instance.collection_exists.return_value = True
            yield mock

    @pytest.fixture
    def mock_entity_extractor(self):
        """Mock EntityRelationExtractor returning sample entities and relations."""
        with patch("etl.graph_builder.entity_extractor.EntityRelationExtractor") as mock:
            instance = mock.return_value

            from etl.graph_builder.entity_extractor import Entity, Relation

            entities = [
                Entity(id="ent_1", name="RAG", type="CONCEPT", source_id="doc_1"),
                Entity(id="ent_2", name="Qdrant", type="TECHNOLOGY", source_id="doc_1"),
                Entity(id="ent_3", name="LLM", type="TECHNOLOGY", source_id="doc_1"),
            ]
            relations = [
                Relation(source="ent_1", target="ent_2", type="USES"),
                Relation(source="ent_1", target="ent_3", type="USES"),
            ]
            instance.extract_batch.return_value = (entities, relations)
            yield mock

    def test_full_extract_chunk_index_flow(self, mock_confluence_extractor, mock_chunker, mock_qdrant_indexer):
        """Full pipeline: extract Confluence -> chunk -> index in Qdrant."""
        # Simulate extraction
        extractor = mock_confluence_extractor.return_value
        extractor.run()
        extractor.run.assert_called_once()

        # Simulate chunking
        chunker = mock_chunker.return_value
        source_meta = {
            "source_type": "confluence",
            "source_id": "confluence_123",
            "version": "1.0",
            "doc_title": "Test Doc",
        }
        chunks = chunker.process_document("<p>Test content</p>", "html", source_meta)
        assert len(chunks) == 3

        # Simulate indexing
        indexer = mock_qdrant_indexer.return_value
        indexer.create_collection(recreate=False)
        indexer.create_collection.assert_called_once()

        chunk_dicts = [ch.__dict__ for ch in chunks]
        count = indexer.index_chunks(chunk_dicts)
        assert count == 5
        indexer.index_chunks.assert_called_once()

    def test_extract_then_chunk_with_metadata_preservation(self, mock_chunker):
        """Source metadata (source_type, version, doc_title) propagates to chunks."""
        chunker = mock_chunker.return_value

        source_meta = {
            "source_type": "jira",
            "source_id": "jira_PROJ-456",
            "version": "2.1",
            "doc_title": "PROJ-456: Add search module",
        }
        chunks = chunker.process_document("Jira task description", "html", source_meta)
        assert len(chunks) == 3

    def test_entity_extraction_integration(self, mock_entity_extractor):
        """Entity extractor produces entities and relations from batch of chunks."""
        extractor = mock_entity_extractor.return_value

        chunk_inputs = [
            {"text": "RAG uses Qdrant and LLM.", "source_id": "doc_1", "metadata": {}},
        ]
        entities, relations = extractor.extract_batch(chunk_inputs)
        assert len(entities) == 3
        assert len(relations) == 2
        entity_names = [e.name for e in entities]
        assert "RAG" in entity_names
        assert "Qdrant" in entity_names


class TestVersionChangeDetection:
    """Tests for version/hash change detection during incremental updates."""

    def test_hash_change_detection_triggers_reindex(self, tmp_path):
        """When chunk hash changes, the chunk is detected as needing reindex."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        hot_dir = tmp_path / "hot"
        cold_dir = tmp_path / "cold"
        wal_path = tmp_path / "wal" / "version_wal.json"

        store = ChunkVersionStore(hot_dir=hot_dir, cold_dir=cold_dir, wal_path=wal_path)

        doc_id = "confluence_789"
        chunks_v1 = [
            {"hash": "aaa111", "text": "Original text", "source_id": doc_id, "version": "1.0"},
            {"hash": "bbb222", "text": "Second chunk", "source_id": doc_id, "version": "1.0"},
        ]
        added, deleted = store.update_document_chunks(doc_id, chunks_v1)
        assert len(added) == 2
        assert len(deleted) == 0

        # Version 2: one chunk changed, one unchanged, one removed
        chunks_v2 = [
            {"hash": "ccc333", "text": "Updated text for chunk 1", "source_id": doc_id, "version": "2.0"},
            {"hash": "bbb222", "text": "Second chunk", "source_id": doc_id, "version": "2.0"},
        ]
        added, deleted = store.update_document_chunks(doc_id, chunks_v2)
        assert len(added) == 1
        assert added[0]["hash"] == "ccc333"
        assert len(deleted) == 1
        assert deleted[0] == "aaa111"

    def test_hash_unchanged_no_reindex(self, tmp_path):
        """When chunk hash is unchanged, it is not reindexed."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        hot_dir = tmp_path / "hot"
        cold_dir = tmp_path / "cold"
        wal_path = tmp_path / "wal" / "version_wal.json"

        store = ChunkVersionStore(hot_dir=hot_dir, cold_dir=cold_dir, wal_path=wal_path)

        doc_id = "gitlab_commit_abc"
        chunks = [
            {"hash": "hash_stable", "text": "Stable text", "source_id": doc_id, "version": "latest"},
        ]
        added, deleted = store.update_document_chunks(doc_id, chunks)
        assert len(added) == 1

        # Same chunks again — no changes
        added2, deleted2 = store.update_document_chunks(doc_id, chunks)
        assert len(added2) == 0
        assert len(deleted2) == 0


class TestWALCheckpointing:
    """Tests for WAL checkpointing across pipeline stages."""

    def test_wal_records_pipeline_checkpoints(self, tmp_path):
        """WAL correctly records and retrieves checkpoints for each pipeline stage."""
        from etl.indexer.wal_manager import PIPELINE_CONFLUENCE, PIPELINE_INDEXING, PIPELINE_JIRA, WALManager

        wal_path = tmp_path / "etl_wal.json"
        wal = WALManager(wal_path, use_lock=False)

        wal.update_last_run(PIPELINE_CONFLUENCE, "2025-06-01T10:00:00")
        wal.update_last_run(PIPELINE_JIRA, "2025-06-01T11:00:00")
        wal.set_checkpoint(PIPELINE_INDEXING, {"added": 150, "deleted": 3})

        assert wal.get_last_run(PIPELINE_CONFLUENCE) == "2025-06-01T10:00:00"
        assert wal.get_last_run(PIPELINE_JIRA) == "2025-06-01T11:00:00"
        assert wal.get_checkpoint(PIPELINE_INDEXING, "added") == 150

    def test_wal_persistence_across_instances(self, tmp_path):
        """WAL data persists across multiple WALManager instances sharing the same file."""
        from etl.indexer.wal_manager import PIPELINE_CONFLUENCE, WALManager

        wal_path = tmp_path / "etl_wal.json"

        wal1 = WALManager(wal_path, use_lock=False)
        wal1.update_last_run(PIPELINE_CONFLUENCE, "2025-01-01T00:00:00")

        wal2 = WALManager(wal_path, use_lock=False)
        assert wal2.get_last_run(PIPELINE_CONFLUENCE) == "2025-01-01T00:00:00"

    def test_wal_supports_hash_state_tracking(self, tmp_path):
        """WAL hash_map tracks per-document chunk hashes for indexing pipeline."""
        from etl.indexer.wal_manager import PIPELINE_INDEXING, WALManager

        wal_path = tmp_path / "etl_wal.json"
        wal = WALManager(wal_path, use_lock=False)

        wal.update_hash_state(PIPELINE_INDEXING, "confluence_123", "abc123hash")
        wal.update_hash_state(PIPELINE_INDEXING, "confluence_456", "def456hash")

        assert wal.get_hash_state(PIPELINE_INDEXING, "confluence_123") == "abc123hash"
        assert wal.get_hash_state(PIPELINE_INDEXING, "confluence_456") == "def456hash"
        assert wal.get_hash_state(PIPELINE_INDEXING, "unknown_doc") is None


class TestIncrementalUpdateFlow:
    """Tests for the incremental ETL update flow using LiveVectorLake."""

    def test_incremental_sync_adds_new_chunks(self, tmp_path):
        """LiveVectorLake.sync_document adds new chunks and removes stale ones."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        hot_dir = tmp_path / "hot"
        cold_dir = tmp_path / "cold"
        wal_path = tmp_path / "wal" / "version_wal.json"

        with patch("etl.indexer.qdrant_hybrid.QdrantHybridIndexer") as mock_qdrant_class:
            mock_qdrant = mock_qdrant_class.return_value
            mock_qdrant.index_chunks.return_value = 3
            mock_qdrant.delete_chunks.return_value = 1

            from etl.indexer.live_vector_lake import LiveVectorLake

            version_store = ChunkVersionStore(hot_dir=hot_dir, cold_dir=cold_dir, wal_path=wal_path)
            lake = LiveVectorLake(
                qdrant_indexer=mock_qdrant,
                version_store=version_store,
                cold_storage_dir=tmp_path / "cold_lake",
                use_delta=False,
            )

            doc_chunks = [
                {"hash": f"hash_{i}", "text": f"Chunk text {i}", "source_id": "doc_1", "version": "1.0"}
                for i in range(3)
            ]
            added, deleted = lake.sync_document("doc_1", doc_chunks)
            assert added == 3
            assert deleted == 0

    def test_incremental_sync_handles_empty_document(self, tmp_path):
        """LiveVectorLake handles documents with no chunks (deletion scenario)."""
        from etl.chunker.hash_versioning import ChunkVersionStore

        hot_dir = tmp_path / "hot"
        cold_dir = tmp_path / "cold"
        wal_path = tmp_path / "wal" / "version_wal.json"

        with patch("etl.indexer.qdrant_hybrid.QdrantHybridIndexer") as mock_qdrant_class:
            mock_qdrant = mock_qdrant_class.return_value
            mock_qdrant.index_chunks.return_value = 0
            mock_qdrant.delete_chunks.return_value = 0

            from etl.indexer.live_vector_lake import LiveVectorLake

            version_store = ChunkVersionStore(hot_dir=hot_dir, cold_dir=cold_dir, wal_path=wal_path)
            lake = LiveVectorLake(
                qdrant_indexer=mock_qdrant,
                version_store=version_store,
                cold_storage_dir=tmp_path / "cold_lake",
                use_delta=False,
            )

            added, deleted = lake.sync_document("doc_1", [])
            assert added == 0
