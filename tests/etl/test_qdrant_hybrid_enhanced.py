# tests/etl/test_qdrant_hybrid_enhanced.py
"""Tests for QdrantHybridIndexer — validates collection management, indexing, and search."""

from unittest.mock import MagicMock, patch

import pytest


class _StubPointStruct:
    """Minimal PointStruct replacement for when proxy tests leak MagicMock into sys.modules."""

    def __init__(self, id=None, vector=None, payload=None, **kwargs):
        self.id = id
        self.vector = vector
        self.payload = payload or {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_qdrant_client():
    """Mock QdrantClient with standard responses."""
    client = MagicMock()
    # get_collections returns empty list by default
    client.get_collections.return_value = MagicMock(collections=[])
    # create_collection succeeds
    client.create_collection.return_value = True
    # upsert succeeds
    client.upsert.return_value = MagicMock(operation_id=1, status="completed")
    # query_points returns empty results
    client.query_points.return_value = MagicMock(points=[])
    return client


@pytest.fixture
def sample_chunks():
    """Sample chunk dicts for indexing."""
    return [
        {
            "hash": "abc123",
            "text": "This is test chunk one about Python programming.",
            "title": "Python Guide",
            "source_type": "confluence",
            "source_id": "page-1",
            "version": "v1",
            "doc_title": "Python Programming Guide",
            "keywords": ["python", "programming"],
            "entities": ["Python"],
            "summary": "Test chunk about Python.",
            "position": 0,
            "semantic_key": "python-guide-0",
        },
        {
            "hash": "def456",
            "text": "This is test chunk two about machine learning.",
            "title": "ML Guide",
            "source_type": "jira",
            "source_id": "ISSUE-42",
            "version": "v1",
            "doc_title": "Machine Learning Guide",
            "keywords": ["ml", "machine-learning"],
            "entities": [],
            "summary": "Test chunk about ML.",
            "position": 1,
            "semantic_key": "ml-guide-1",
        },
    ]


# ---------------------------------------------------------------------------
# Collection management tests
# ---------------------------------------------------------------------------


class TestQdrantHybridIndexerCollections:
    """Test collection creation and management."""

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_create_collection_when_not_exists(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        # Collection doesn't exist yet
        mock_qdrant_client.get_collections.return_value = MagicMock(collections=[])

        # create_collection should call the client
        indexer.create_collection()
        mock_qdrant_client.create_collection.assert_called_once()

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_create_collection_skips_when_exists(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        # Collection already exists
        existing = MagicMock()
        existing.name = "test_kb"
        mock_qdrant_client.get_collections.return_value = MagicMock(collections=[existing])

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        indexer.create_collection()
        # Should NOT create since it already exists
        mock_qdrant_client.create_collection.assert_not_called()


# ---------------------------------------------------------------------------
# Indexing tests
# ---------------------------------------------------------------------------


class TestQdrantHybridIndexerIndexing:
    """Test chunk indexing functionality."""

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_index_chunks_calls_upsert(self, mock_client_cls, mock_st, mock_qdrant_client, sample_chunks):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
        mock_st.return_value = mock_embedder

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        count = indexer.index_chunks(sample_chunks)

        assert count == 2
        mock_qdrant_client.upsert.assert_called_once()

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_index_chunks_skips_empty_text(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
        mock_st.return_value = mock_embedder

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        # Chunk with empty text should be skipped
        bad_chunks = [{"hash": "bad1", "text": "", "title": "Empty"}]
        count = indexer.index_chunks(bad_chunks)
        assert count == 0
        mock_qdrant_client.upsert.assert_not_called()

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_index_chunks_skips_missing_hash(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
        mock_st.return_value = mock_embedder

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        # Chunk without hash should be skipped
        bad_chunks = [{"text": "No hash here", "title": "No Hash"}]
        count = indexer.index_chunks(bad_chunks)
        assert count == 0
        mock_qdrant_client.upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Chunk-to-point conversion tests
# ---------------------------------------------------------------------------


class TestQdrantHybridIndexerConversion:
    """Test chunk-to-point conversion logic."""

    @patch("etl.indexer.qdrant_hybrid.PointStruct", _StubPointStruct)
    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_chunk_to_point_creates_valid_point(self, mock_client_cls, mock_st, mock_qdrant_client, sample_chunks):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
        mock_st.return_value = mock_embedder

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        point = indexer._chunk_to_point(sample_chunks[0])

        assert point is not None
        assert point.id == "abc123"
        assert "text" in point.payload
        assert point.payload["source_type"] == "confluence"

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_chunk_to_point_returns_none_for_empty(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        point = indexer._chunk_to_point({"hash": "x", "text": ""})
        assert point is None


class TestQdrantHybridIndexerLiveOps:
    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_live_upsert_success(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
        mock_st.return_value = mock_embedder

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        chunk = {
            "hash": "abc123",
            "text": "test chunk text for live upsert",
            "title": "Test",
            "source_type": "wiki",
            "source_id": "42",
        }
        result = indexer.live_upsert(chunk)
        assert result is True
        mock_qdrant_client.upsert.assert_called_once()

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_live_upsert_empty_text(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        chunk = {"hash": "x", "text": ""}
        result = indexer.live_upsert(chunk)
        assert result is False

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_live_delete_success(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        result = indexer.live_delete("abc123")
        assert result is True

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_live_delete_empty_id(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        result = indexer.live_delete("")
        assert result is False


class TestQdrantHybridIndexerColbert:
    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_compute_colbert_disabled(self, mock_client_cls, mock_st, mock_qdrant_client):
        import etl.indexer.qdrant_hybrid as qdrant_mod
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
        mock_st.return_value = mock_embedder

        original_colbert = qdrant_mod.COLBERT_ENABLED
        try:
            qdrant_mod.COLBERT_ENABLED = False
            indexer = QdrantHybridIndexer(
                host="localhost",
                port=6333,
                collection_name="test_kb",
                embedder_model_name="BAAI/bge-m3",
            )
            result = indexer._compute_colbert_vectors("test text")
            assert len(result) == 1
            assert isinstance(result[0], list)
        finally:
            qdrant_mod.COLBERT_ENABLED = original_colbert

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_index_with_colbert_disabled(self, mock_client_cls, mock_st, mock_qdrant_client):
        import etl.indexer.qdrant_hybrid as qdrant_mod
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        original_colbert = qdrant_mod.COLBERT_ENABLED
        try:
            qdrant_mod.COLBERT_ENABLED = False
            indexer = QdrantHybridIndexer(
                host="localhost",
                port=6333,
                collection_name="test_kb",
                embedder_model_name="BAAI/bge-m3",
            )
            result = indexer.index_with_colbert("test")
            assert result is False
        finally:
            qdrant_mod.COLBERT_ENABLED = original_colbert

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_search_colbert_disabled(self, mock_client_cls, mock_st, mock_qdrant_client):
        import etl.indexer.qdrant_hybrid as qdrant_mod
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        original_colbert = qdrant_mod.COLBERT_ENABLED
        try:
            qdrant_mod.COLBERT_ENABLED = False
            indexer = QdrantHybridIndexer(
                host="localhost",
                port=6333,
                collection_name="test_kb",
                embedder_model_name="BAAI/bge-m3",
            )
            result = indexer.search_colbert("query")
            assert result == []
        finally:
            qdrant_mod.COLBERT_ENABLED = original_colbert

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_compute_colbert_success(self, mock_client_cls, mock_st, mock_qdrant_client):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        mock_client_cls.return_value = mock_qdrant_client
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(
            tolist=lambda: [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
        )
        mock_st.return_value = mock_embedder

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )
        result = indexer._compute_colbert_vectors("test")
        assert isinstance(result, list)
        assert len(result) == 3


class TestBatchIndexFromJsonFiles:
    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_batch_index_from_files(self, mock_client_cls, mock_st, mock_qdrant_client, tmp_path):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer, batch_index_from_json_files

        mock_client_cls.return_value = mock_qdrant_client
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = MagicMock(tolist=lambda: [0.1] * 1024)
        mock_st.return_value = mock_embedder

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )

        chunks_dir = tmp_path / "chunks"
        chunks_dir.mkdir()
        json_file = chunks_dir / "chunks.json"
        import json

        json_file.write_text(
            json.dumps(
                [
                    {
                        "hash": "test1",
                        "text": "test text one",
                        "title": "Test1",
                        "source_type": "wiki",
                        "source_id": "1",
                    },
                    {
                        "hash": "test2",
                        "text": "test text two",
                        "title": "Test2",
                        "source_type": "wiki",
                        "source_id": "2",
                    },
                ],
            ),
        )

        batch_index_from_json_files(indexer, chunks_dir)
        mock_qdrant_client.upsert.assert_called_once()

    @patch("etl.indexer.qdrant_hybrid.SentenceTransformer")
    @patch("etl.indexer.qdrant_hybrid.QdrantClient")
    def test_batch_index_empty_dir(self, mock_client_cls, mock_st, mock_qdrant_client, tmp_path):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer, batch_index_from_json_files

        mock_client_cls.return_value = mock_qdrant_client
        mock_st.return_value = MagicMock()

        indexer = QdrantHybridIndexer(
            host="localhost",
            port=6333,
            collection_name="test_kb",
            embedder_model_name="BAAI/bge-m3",
        )

        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        batch_index_from_json_files(indexer, empty_dir)
        mock_qdrant_client.upsert.assert_not_called()
