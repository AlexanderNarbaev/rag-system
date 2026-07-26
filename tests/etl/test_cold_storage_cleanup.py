"""Cold-storage retention integration coverage (FR-57)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from etl.scheduler.cold_storage_cleanup import cleanup_cold_storage


def _version(path, version: int, age_days: int) -> None:
    path.write_bytes(b"parquet placeholder")
    timestamp = (datetime.now(UTC) - timedelta(days=age_days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_cleanup_removes_versions_older_than_90_days_and_keeps_current(tmp_path) -> None:
    for version in range(1, 5):
        _version(tmp_path / f"doc_v{version}.parquet", version, 100 - version)

    deleted = cleanup_cold_storage(str(tmp_path), max_versions=1)

    assert deleted == 3
    assert (tmp_path / "doc_v4.parquet").exists()
    assert not (tmp_path / "doc_v1.parquet").exists()


def test_mid_age_versions_are_archived_by_retention_policy(tmp_path) -> None:
    for version in range(1, 4):
        _version(tmp_path / f"doc_v{version}.parquet", version, 45)

    deleted = cleanup_cold_storage(str(tmp_path), max_versions=2)

    assert deleted == 1
    assert (tmp_path / "doc_v2.parquet").exists()
    assert (tmp_path / "doc_v3.parquet").exists()


def test_current_version_is_retained_when_no_old_versions_exist(tmp_path) -> None:
    _version(tmp_path / "doc_v7.parquet", 7, 1)

    assert cleanup_cold_storage(str(tmp_path), max_versions=1) == 0
    assert (tmp_path / "doc_v7.parquet").exists()


def test_cleanup_does_not_touch_non_version_files(tmp_path) -> None:
    marker = tmp_path / "README.txt"
    marker.write_text("keep", encoding="utf-8")

    assert cleanup_cold_storage(str(tmp_path), max_versions=1) == 0
    assert marker.exists()
