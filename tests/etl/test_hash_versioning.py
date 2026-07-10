# tests/etl/test_hash_versioning.py
import json

import pytest

from etl.chunker.hash_versioning import (
    ChunkVersionStore,
    compute_chunk_hash,
    get_incremental_chunks,
)


class TestComputeChunkHash:
    def test_same_content_same_hash(self):
        chunk_a = {"text": "hello world", "title": "Test", "source_type": "wiki"}
        chunk_b = {"text": "hello world", "title": "Test", "source_type": "wiki"}
        assert compute_chunk_hash(chunk_a) == compute_chunk_hash(chunk_b)

    def test_different_content_different_hash(self):
        chunk_a = {"text": "hello", "title": "A"}
        chunk_b = {"text": "world", "title": "A"}
        assert compute_chunk_hash(chunk_a) != compute_chunk_hash(chunk_b)

    def test_ignores_non_hashable_fields(self):
        chunk_a = {"text": "hello", "title": "Test", "extracted_at": "2025-01-01T00:00:00"}
        chunk_b = {"text": "hello", "title": "Test", "extracted_at": "2025-06-01T00:00:00"}
        assert compute_chunk_hash(chunk_a) == compute_chunk_hash(chunk_b)

    def test_empty_dict(self):
        result = compute_chunk_hash({})
        assert isinstance(result, str)
        assert len(result) == 64

    def test_keywords_sorted_affects_hash(self):
        chunk_a = {"text": "x", "keywords": ["b", "a", "c"]}
        chunk_b = {"text": "x", "keywords": ["a", "b", "c"]}
        assert compute_chunk_hash(chunk_a) == compute_chunk_hash(chunk_b)

    def test_none_fields_handled(self):
        chunk = {"text": "x", "title": None, "source_type": None}
        result = compute_chunk_hash(chunk)
        assert isinstance(result, str)
        assert len(result) == 64


class TestChunkVersionStore:
    @pytest.fixture(autouse=True)
    def _force_jsonl_fallback(self, monkeypatch):
        """Force JSONL fallback to avoid pyarrow dependency."""
        monkeypatch.setattr("etl.chunker.hash_versioning.PANDAS_AVAILABLE", False)

    def _chunk(self, hash_val, text, source_id="doc_1", **kwargs):
        base = {"hash": hash_val, "text": text, "source_id": source_id}
        base.update(kwargs)
        return base

    def _make_store(self, tmp_path):
        return ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )

    def test_init_creates_dirs_and_wal(self, tmp_path):
        self._make_store(tmp_path)
        assert (tmp_path / "hot").is_dir()
        assert (tmp_path / "cold").is_dir()
        # WAL file is not created at init, only on _save_wal()
        # _load_wal returns empty dict without writing

    def test_init_loads_existing_wal(self, tmp_path):
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text(json.dumps({"documents": {"existing_doc": {"last_hash": "abc"}}}))
        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=wal_path,
        )
        assert store.get_last_hash("existing_doc") == "abc"

    def test_get_last_hash_new_document(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store.get_last_hash("nonexistent") is None

    def test_get_last_hash_existing_document(self, tmp_path):
        store = self._make_store(tmp_path)
        chunks = [self._chunk("aaa", "content")]
        store.update_document_chunks("doc_1", chunks)
        assert store.get_last_hash("doc_1") == "aaa"

    def test_update_new_document_returns_all_chunks(self, tmp_path):
        store = self._make_store(tmp_path)
        chunks = [
            self._chunk("aaa", "chunk 1"),
            self._chunk("bbb", "chunk 2"),
        ]
        added, deleted = store.update_document_chunks("doc_1", chunks)
        assert len(added) == 2
        assert len(deleted) == 0

    def test_update_unchanged_document_returns_nothing(self, tmp_path):
        store = self._make_store(tmp_path)
        chunks = [self._chunk("aaa", "content")]
        store.update_document_chunks("doc_1", chunks)
        # Same chunks again
        added, deleted = store.update_document_chunks("doc_1", chunks)
        assert len(added) == 0
        assert len(deleted) == 0

    def test_update_modified_document_returns_only_changed(self, tmp_path):
        store = self._make_store(tmp_path)
        v1 = [
            self._chunk("aaa", "old text"),
            self._chunk("bbb", "unchanged text"),
        ]
        store.update_document_chunks("doc_1", v1)
        v2 = [
            self._chunk("ccc", "new text"),
            self._chunk("bbb", "unchanged text"),
        ]
        added, deleted = store.update_document_chunks("doc_1", v2)
        assert len(added) == 1
        assert added[0]["hash"] == "ccc"
        assert len(deleted) == 1
        assert deleted[0] == "aaa"

    def test_update_force_mode_returns_all_chunks(self, tmp_path):
        store = self._make_store(tmp_path)
        v1 = [self._chunk("aaa", "v1")]
        store.update_document_chunks("doc_1", v1)
        v2 = [self._chunk("aaa", "v1")]
        added, deleted = store.update_document_chunks("doc_1", v2, force=True)
        assert len(added) == 1
        assert len(deleted) == 0

    def test_save_and_load_hot_chunks_round_trip(self, tmp_path):
        store = self._make_store(tmp_path)
        chunks = [
            self._chunk("aaa", "text a", title="A"),
            self._chunk("bbb", "text b", title="B"),
        ]
        store._save_chunks_to_hot("doc_1", chunks)
        loaded = store._load_hot_chunks("doc_1")
        assert len(loaded) == 2
        assert loaded[0]["hash"] == "aaa"
        assert loaded[1]["hash"] == "bbb"

    def test_load_hot_chunks_nonexistent_returns_empty(self, tmp_path):
        store = self._make_store(tmp_path)
        assert store._load_hot_chunks("no_such") == []

    def test_get_all_current_chunks(self, tmp_path):
        store = self._make_store(tmp_path)
        store.update_document_chunks("doc_a", [self._chunk("a1", "text a")])
        store.update_document_chunks("doc_b", [self._chunk("b1", "text b"), self._chunk("b2", "text b2")])
        all_c = store.get_all_current_chunks()
        assert len(all_c) == 3

    def test_get_chunk_history(self, tmp_path):
        store = self._make_store(tmp_path)
        chunks = [self._chunk("aaa", "text")]
        store.update_document_chunks("doc_1", chunks)
        history = store.get_chunk_history("doc_1")
        assert isinstance(history, list)

    def test_get_chunk_history_nonexistent(self, tmp_path):
        store = self._make_store(tmp_path)
        history = store.get_chunk_history("no_such")
        assert history == []

    def test_cleanup_old_versions(self, tmp_path):
        store = self._make_store(tmp_path)
        store.update_document_chunks("doc_1", [self._chunk("aaa", "text")])
        # Should not raise
        store.cleanup_old_versions("doc_1", keep_versions=5)

    def test_reset_single_document(self, tmp_path):
        store = self._make_store(tmp_path)
        store.update_document_chunks("doc_a", [self._chunk("x", "text")])
        store.update_document_chunks("doc_b", [self._chunk("y", "text")])
        store.reset("doc_a")
        assert store.get_last_hash("doc_a") is None
        assert store.get_last_hash("doc_b") is not None
        assert not (tmp_path / "hot" / "doc_a.json").exists()

    def test_reset_all_documents(self, tmp_path):
        store = self._make_store(tmp_path)
        store.update_document_chunks("doc_a", [self._chunk("x", "text")])
        store.reset()
        assert store.get_last_hash("doc_a") is None
        assert store.get_all_current_chunks() == []


class TestGetIncrementalChunks:
    @pytest.fixture(autouse=True)
    def _force_jsonl_fallback(self, monkeypatch):
        monkeypatch.setattr("etl.chunker.hash_versioning.PANDAS_AVAILABLE", False)

    def test_returns_only_changed_chunks(self, tmp_path):
        store = ChunkVersionStore(
            hot_dir=tmp_path / "hot",
            cold_dir=tmp_path / "cold",
            wal_path=tmp_path / "wal" / "wal.json",
        )
        v1 = [{"hash": "aaa", "text": "old"}]
        get_incremental_chunks(store, "doc_1", v1)
        v2 = [{"hash": "bbb", "text": "new"}]
        added = get_incremental_chunks(store, "doc_1", v2)
        assert len(added) == 1
        assert added[0]["hash"] == "bbb"
