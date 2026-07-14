# tests/etl/test_live_vector_lake.py
from unittest.mock import MagicMock

from etl.chunker.hash_versioning import ChunkVersionStore
from etl.indexer.live_vector_lake import (
  LiveVectorLake, incremental_index_pipeline,
)


class TestLiveVectorLakeInit:
  def test_init_creates_cold_dir (self, tmp_path):
    mock_qdrant = MagicMock ()
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    assert (tmp_path / "cold_storage").is_dir ()
  
  def test_init_with_delta_disabled (self, tmp_path):
    mock_qdrant = MagicMock ()
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    assert lake.use_delta is False
    assert lake.delta_available is False


class TestLiveVectorLakeSyncDocument:
  def _make_lake (self, tmp_path):
    mock_qdrant = MagicMock ()
    mock_qdrant.index_chunks.return_value = 2
    mock_qdrant.delete_chunks.return_value = 1
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    return lake, mock_qdrant, version_store
  
  def test_sync_new_document (self, tmp_path):
    lake, mock_qdrant, _ = self._make_lake (tmp_path)
    chunks = [
        {"hash": "c1", "text": "First chunk", "source_type": "wiki"},
        {"hash": "c2", "text": "Second chunk", "source_type": "wiki"},
    ]
    added, deleted = lake.sync_document ("doc_1", chunks)
    assert added == 2
    assert deleted == 0
    mock_qdrant.index_chunks.assert_called ()
  
  def test_sync_unchanged_document (self, tmp_path):
    lake, mock_qdrant, _ = self._make_lake (tmp_path)
    chunks = [{"hash": "c1", "text": "content"}]
    lake.sync_document ("doc_1", chunks)
    mock_qdrant.reset_mock ()
    added, deleted = lake.sync_document ("doc_1", chunks)
    assert added == 0
    assert deleted == 0
    mock_qdrant.index_chunks.assert_not_called ()
    mock_qdrant.delete_chunks.assert_not_called ()
  
  def test_sync_with_deleted_chunks (self, tmp_path):
    lake, mock_qdrant, _ = self._make_lake (tmp_path)
    v1 = [
        {"hash": "c1", "text": "chunk 1"}, {"hash": "c2", "text": "chunk 2"},
    ]
    lake.sync_document ("doc_1", v1)
    mock_qdrant.reset_mock ()
    mock_qdrant.index_chunks.return_value = 1
    mock_qdrant.delete_chunks.return_value = 1
    v2 = [{"hash": "c2", "text": "chunk 2"}]
    added, deleted = lake.sync_document ("doc_1", v2)
    assert added == 0
    assert deleted == 1
  
  def test_sync_force_mode (self, tmp_path):
    lake, mock_qdrant, _ = self._make_lake (tmp_path)
    chunks = [{"hash": "c1", "text": "content"}]
    lake.sync_document ("doc_1", chunks)
    mock_qdrant.reset_mock ()
    mock_qdrant.index_chunks.return_value = 1
    added, deleted = lake.sync_document ("doc_1", chunks, force = True)
    assert added == 1
    mock_qdrant.index_chunks.assert_called ()


class TestLiveVectorLakeBulkSync:
  def _make_lake (self, tmp_path):
    mock_qdrant = MagicMock ()
    mock_qdrant.index_chunks.return_value = 1
    mock_qdrant.delete_chunks.return_value = 0
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    return lake
  
  def test_bulk_sync_multiple_documents (self, tmp_path):
    lake = self._make_lake (tmp_path)
    documents = {
        "doc_a": [{"hash": "a1", "text": "text a"}], "doc_b": [{"hash": "b1", "text": "text b"}],
    }
    results = lake.bulk_sync (documents)
    assert len (results) == 2
    assert "doc_a" in results
    assert "doc_b" in results
  
  def test_bulk_sync_empty (self, tmp_path):
    lake = self._make_lake (tmp_path)
    results = lake.bulk_sync ({})
    assert results == {}


class TestLiveVectorLakeGetDocumentHistory:
  def test_no_history_for_new_document (self, tmp_path):
    mock_qdrant = MagicMock ()
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    history = lake.get_document_history ("no_such_doc")
    assert history.empty


class TestLiveVectorLakeRollback:
  def test_rollback_nonexistent (self, tmp_path):
    mock_qdrant = MagicMock ()
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    result = lake.rollback_document ("no_doc", "2025-01-01T00:00:00")
    assert result == 0


class TestLiveVectorLakeGetAllCurrentChunks:
  def test_returns_all_chunks (self, tmp_path):
    mock_qdrant = MagicMock ()
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    chunks = [
        {"hash": "c1", "text": "text 1"}, {"hash": "c2", "text": "text 2"},
    ]
    lake.sync_document ("doc_1", chunks)
    all_c = lake.get_all_current_chunks ()
    assert len (all_c) == 2


class TestLiveVectorLakeCleanup:
  def test_cleanup_old_versions (self, tmp_path):
    mock_qdrant = MagicMock ()
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    lake.cleanup_old_versions ("doc_1", keep_versions = 5)


class TestIncrementalIndexPipeline:
  def test_pipeline_returns_true_when_changes (self, tmp_path):
    mock_qdrant = MagicMock ()
    mock_qdrant.index_chunks.return_value = 1
    mock_qdrant.delete_chunks.return_value = 0
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    chunks = [{"hash": "c1", "text": "new text"}]
    result = incremental_index_pipeline (lake, "doc_1", chunks)
    assert result is True
  
  def test_pipeline_returns_false_when_no_changes (self, tmp_path):
    mock_qdrant = MagicMock ()
    mock_qdrant.index_chunks.return_value = 1
    mock_qdrant.delete_chunks.return_value = 0
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    chunks = [{"hash": "c1", "text": "text"}]
    # First sync creates the state
    incremental_index_pipeline (lake, "doc_1", chunks)
    # Second sync with same chunks
    result = incremental_index_pipeline (lake, "doc_1", chunks)
    assert result is False
  
  def test_pipeline_force_reindex (self, tmp_path):
    mock_qdrant = MagicMock ()
    mock_qdrant.index_chunks.return_value = 1
    mock_qdrant.delete_chunks.return_value = 0
    version_store = ChunkVersionStore (hot_dir = tmp_path / "hot", cold_dir = tmp_path / "cold",
        wal_path = tmp_path / "wal" / "wal.json", )
    lake = LiveVectorLake (qdrant_indexer = mock_qdrant, version_store = version_store,
        cold_storage_dir = tmp_path / "cold_storage", use_delta = False, )
    chunks = [{"hash": "c1", "text": "text"}]
    incremental_index_pipeline (lake, "doc_1", chunks)
    # Force reindex
    result = incremental_index_pipeline (lake, "doc_1", chunks, force_reindex = True)
    assert result is True
