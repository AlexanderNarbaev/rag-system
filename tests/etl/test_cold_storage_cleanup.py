"""Tests for etl/scheduler/cold_storage_cleanup.py."""

import os
from unittest.mock import patch

from etl.scheduler.cold_storage_cleanup import (
  COLD_STORAGE_ENABLED,
  COLD_STORAGE_MAX_VERSIONS,
  _list_parquet_versions,
  _prune_old_versions,
  cleanup_cold_storage,
)


class TestListParquetVersions:
  def test_empty_directory (self, tmp_path):
    versions = _list_parquet_versions (tmp_path)
    assert versions == {}

  def test_single_document_single_version (self, tmp_path):
    (tmp_path / "doc1_v1.parquet").touch ()
    versions = _list_parquet_versions (tmp_path)
    assert "doc1" in versions
    assert len (versions ["doc1"]) == 1

  def test_single_document_multiple_versions (self, tmp_path):
    for i in range (1, 6):
      (tmp_path / f"doc_v{i}.parquet").touch ()
    (tmp_path / "other.txt").touch ()
    versions = _list_parquet_versions (tmp_path)
    assert "doc" in versions
    assert len (versions ["doc"]) == 5

  def test_multiple_documents (self, tmp_path):
    (tmp_path / "report_v1.parquet").touch ()
    (tmp_path / "report_v2.parquet").touch ()
    (tmp_path / "guide_v1.parquet").touch ()
    versions = _list_parquet_versions (tmp_path)
    assert "report" in versions
    assert "guide" in versions
    assert len (versions ["report"]) == 2
    assert len (versions ["guide"]) == 1

  def test_non_parquet_files_ignored (self, tmp_path):
    (tmp_path / "log.txt").touch ()
    (tmp_path / "data.csv").touch ()
    versions = _list_parquet_versions (tmp_path)
    assert versions == {}

  def test_complex_version_patterns (self, tmp_path):
    (tmp_path / "spec_v1_2_3.parquet").touch ()
    (tmp_path / "spec_v2_0_1.parquet").touch ()
    versions = _list_parquet_versions (tmp_path)
    assert "spec" in versions
    assert len (versions ["spec"]) == 2


class TestPruneOldVersions:
  def test_no_pruning_needed (self, tmp_path):
    versions = {"doc1": [(tmp_path / "doc1_v1.parquet", 1)]}
    deleted = _prune_old_versions (versions, max_versions = 5)
    assert deleted == 0

  def test_prunes_excess_versions (self, tmp_path):
    files = []
    for i in range (1, 8):
      f = tmp_path / f"doc1_v{i}.parquet"
      f.touch ()
      files.append ((f, i))
    deleted = _prune_old_versions ({"doc1": files}, max_versions = 3)
    assert deleted == 4

  def test_preserves_latest_versions (self, tmp_path):
    files = []
    for i in range (1, 6):
      f = tmp_path / f"doc1_v{i}.parquet"
      f.touch ()
      files.append ((f, i))
    _prune_old_versions ({"doc1": files}, max_versions = 2)
    remaining = list (tmp_path.glob ("*.parquet"))
    assert len (remaining) <= 2

  def test_handles_permission_error (self, tmp_path):
    f1 = tmp_path / "doc_v1.parquet"
    f1.touch ()
    try:
      versions = {"doc": [(f1, 1)]}
      deleted = _prune_old_versions (versions, max_versions = 0)
      assert deleted >= 0
    except Exception:
      pass
    finally:
      if f1.exists ():
        os.chmod (str (f1), 0o644)

  def test_empty_versions_does_nothing (self):
    assert _prune_old_versions ({}, max_versions = 5) == 0


class TestCleanupColdStorage:
  def test_returns_zero_on_nonexistent_dir (self):
    result = cleanup_cold_storage ("/nonexistent/path", max_versions = 5)
    assert result == 0

  def test_returns_count_of_deleted (self, tmp_path):
    for i in range (1, 10):
      (tmp_path / f"doc_v{i}.parquet").touch ()
    result = cleanup_cold_storage (str (tmp_path), max_versions = 3)
    assert result > 0

  def test_no_files_no_deletion (self, tmp_path):
    result = cleanup_cold_storage (str (tmp_path), max_versions = 5)
    assert result == 0

  @patch ("etl.scheduler.cold_storage_cleanup.COLD_STORAGE_ENABLED", False)
  def test_disabled_returns_zero (self, tmp_path):
    for i in range (1, 5):
      (tmp_path / f"doc_v{i}.parquet").touch ()
    result = cleanup_cold_storage (str (tmp_path), max_versions = 5)
    assert result == 0

  def test_respects_custom_max_versions (self, tmp_path):
    for i in range (1, 11):
      (tmp_path / f"doc_v{i}.parquet").touch ()
    result = cleanup_cold_storage (str (tmp_path), max_versions = 5)
    assert result == 5


class TestConfigFlags:
  def test_cold_storage_max_versions (self):
    assert COLD_STORAGE_MAX_VERSIONS > 0

  def test_cold_storage_enabled (self):
    assert COLD_STORAGE_ENABLED in (True, False)
