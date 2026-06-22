# tests/etl/test_wal_manager.py
import json
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

from etl.indexer.wal_manager import (
    WALManager,
    PIPELINE_CONFLUENCE,
    PIPELINE_JIRA,
    PIPELINE_GITLAB,
    PIPELINE_INDEXING,
    PIPELINE_GRAPH,
)


class TestWALManagerInit:
    def test_init_creates_dirs_and_empty_wal(self, tmp_path):
        wal_path = tmp_path / "wal_test.json"
        wm = WALManager(wal_path, use_lock=False)
        assert wal_path.exists()
        data = json.loads(wal_path.read_text())
        assert data == {}

    def test_init_loads_existing_wal(self, tmp_path):
        wal_path = tmp_path / "existing.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text(json.dumps({"test_pipeline": {"key": "value"}}))
        wm = WALManager(wal_path, use_lock=False)
        assert wm.get_checkpoint("test_pipeline", "key") == "value"

    def test_init_handles_corrupted_wal(self, tmp_path):
        wal_path = tmp_path / "corrupted.json"
        wal_path.write_text("not valid json{{{")
        wm = WALManager(wal_path, use_lock=False)
        # Should not raise, initializes empty
        assert wm.get_checkpoint("anything") == {}

    def test_init_with_lock_available(self, tmp_path, monkeypatch):
        # Only run if filelock is importable
        try:
            import filelock
        except ImportError:
            pytest.skip("filelock not installed")
        wal_path = tmp_path / "with_lock.json"
        wm = WALManager(wal_path, use_lock=True)
        assert wm.use_lock is True

    def test_init_with_lock_forced_off(self, tmp_path):
        wal_path = tmp_path / "no_lock.json"
        wm = WALManager(wal_path, use_lock=False)
        assert wm.use_lock is False


class TestWALManagerCheckpoint:
    def _make_wal(self, tmp_path):
        return WALManager(tmp_path / "wal.json", use_lock=False)

    def test_set_and_get_checkpoint_round_trip(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.set_checkpoint("pipe_a", {"foo": "bar", "count": 42})
        assert wm.get_checkpoint("pipe_a", "foo") == "bar"
        assert wm.get_checkpoint("pipe_a", "count") == 42

    def test_get_checkpoint_full_dict(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.set_checkpoint("pipe_a", {"a": 1, "b": 2})
        result = wm.get_checkpoint("pipe_a")
        assert result["a"] == 1
        assert result["b"] == 2
        assert "_updated_at" in result

    def test_get_checkpoint_nonexistent_pipeline(self, tmp_path):
        wm = self._make_wal(tmp_path)
        assert wm.get_checkpoint("nonexistent", "x") is None
        assert wm.get_checkpoint("nonexistent") == {}

    def test_set_checkpoint_merges_fields(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.set_checkpoint("pipe_a", {"x": 1})
        wm.set_checkpoint("pipe_a", {"y": 2})
        assert wm.get_checkpoint("pipe_a", "x") == 1
        assert wm.get_checkpoint("pipe_a", "y") == 2


class TestWALManagerLastRun:
    def _make_wal(self, tmp_path):
        return WALManager(tmp_path / "wal.json", use_lock=False)

    def test_update_and_get_last_run(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.update_last_run("pipe_a", "2025-06-01T00:00:00")
        assert wm.get_last_run("pipe_a") == "2025-06-01T00:00:00"

    def test_update_last_run_default_to_now(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.update_last_run("pipe_a")
        result = wm.get_last_run("pipe_a")
        assert result is not None
        # Should be a valid ISO timestamp
        datetime.fromisoformat(result)

    def test_update_last_run_with_datetime_object(self, tmp_path):
        wm = self._make_wal(tmp_path)
        dt = datetime(2025, 1, 15, 12, 30, 0)
        wm.update_last_run("pipe_a", dt)
        result = wm.get_last_run("pipe_a")
        assert "2025-01-15T12:30:00" in result

    def test_get_last_run_nonexistent(self, tmp_path):
        wm = self._make_wal(tmp_path)
        assert wm.get_last_run("nonexistent") is None


class TestWALManagerOffset:
    def _make_wal(self, tmp_path):
        return WALManager(tmp_path / "wal.json", use_lock=False)

    def test_update_and_get_offset(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.update_offset("pipe_a", 150)
        assert wm.get_offset("pipe_a") == 150

    def test_get_offset_default_zero(self, tmp_path):
        wm = self._make_wal(tmp_path)
        assert wm.get_offset("new_pipe") == 0


class TestWALManagerLastId:
    def _make_wal(self, tmp_path):
        return WALManager(tmp_path / "wal.json", use_lock=False)

    def test_update_and_get_last_id(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.update_last_id("pipe_a", "issue-12345")
        assert wm.get_last_id("pipe_a") == "issue-12345"

    def test_get_last_id_nonexistent(self, tmp_path):
        wm = self._make_wal(tmp_path)
        assert wm.get_last_id("nonexistent") is None


class TestWALManagerHashState:
    def _make_wal(self, tmp_path):
        return WALManager(tmp_path / "wal.json", use_lock=False)

    def test_update_and_get_hash_state(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.update_hash_state("pipe_a", "doc_1", "abc123")
        assert wm.get_hash_state("pipe_a", "doc_1") == "abc123"

    def test_update_multiple_hashes(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.update_hash_state("pipe_a", "doc_1", "hash_a")
        wm.update_hash_state("pipe_a", "doc_2", "hash_b")
        assert wm.get_hash_state("pipe_a", "doc_1") == "hash_a"
        assert wm.get_hash_state("pipe_a", "doc_2") == "hash_b"

    def test_get_hash_state_nonexistent(self, tmp_path):
        wm = self._make_wal(tmp_path)
        assert wm.get_hash_state("pipe_a", "no_doc") is None


class TestWALManagerReset:
    def _make_wal(self, tmp_path):
        return WALManager(tmp_path / "wal.json", use_lock=False)

    def test_reset_pipeline_full(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.set_checkpoint("pipe_a", {"x": 1, "y": 2})
        wm.set_checkpoint("pipe_b", {"z": 3})
        wm.reset_pipeline("pipe_a")
        assert wm.get_checkpoint("pipe_a") == {}
        assert wm.get_checkpoint("pipe_b", "z") == 3

    def test_reset_pipeline_keep_last_run(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.set_checkpoint("pipe_a", {"x": 1, "last_run": "2025-01-01T00:00:00"})
        wm.reset_pipeline("pipe_a", keep_last_run=True)
        assert wm.get_checkpoint("pipe_a", "last_run") == "2025-01-01T00:00:00"
        assert wm.get_checkpoint("pipe_a", "x") is None

    def test_reset_all(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.set_checkpoint("pipe_a", {"x": 1})
        wm.set_checkpoint("pipe_b", {"y": 2})
        wm.reset_all()
        assert wm.get_checkpoint("pipe_a") == {}
        assert wm.get_checkpoint("pipe_b") == {}


class TestWALManagerGetAllPipelines:
    def _make_wal(self, tmp_path):
        return WALManager(tmp_path / "wal.json", use_lock=False)

    def test_get_all_pipelines(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.set_checkpoint("pipe_a", {"x": 1})
        wm.set_checkpoint("pipe_b", {"y": 2})
        pipelines = wm.get_all_pipelines()
        assert sorted(pipelines) == ["pipe_a", "pipe_b"]

    def test_get_all_pipelines_empty(self, tmp_path):
        wm = self._make_wal(tmp_path)
        assert wm.get_all_pipelines() == []


class TestWALManagerVacuum:
    def _make_wal(self, tmp_path):
        return WALManager(tmp_path / "wal.json", use_lock=False)

    def test_vacuum_does_not_raise(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.set_checkpoint("pipe_a", {"hash_map": {"doc_1": "abc"}})
        wm.vacuum(max_age_days=0)

    def test_vacuum_empty_wal(self, tmp_path):
        wm = self._make_wal(tmp_path)
        wm.vacuum(max_age_days=30)
        assert wm.get_all_pipelines() == []


class TestPipelineConstants:
    def test_constants_are_strings(self):
        assert isinstance(PIPELINE_CONFLUENCE, str)
        assert isinstance(PIPELINE_JIRA, str)
        assert isinstance(PIPELINE_GITLAB, str)
        assert isinstance(PIPELINE_INDEXING, str)
        assert isinstance(PIPELINE_GRAPH, str)
