# etl/scheduler/cold_storage_cleanup.py
"""TTL-based Parquet version pruning for cold storage."""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

COLD_STORAGE_ENABLED = True
COLD_STORAGE_MAX_VERSIONS = 5


def _list_parquet_versions(cold_dir: Path) -> dict[str, list[tuple[Path, int]]]:
    """Scan cold_dir for Parquet files and group by document name.

    Each file named like "doc_vN.parquet" is grouped under document key "doc".
    The version number N is extracted for sorting.

    :return: dict mapping document name -> list of (path, version_number) sorted by version desc
    """
    if not cold_dir.is_dir():
        return {}

    pattern = re.compile(r"^(.+?)_v(\d+(?:_\d+)*)\.parquet$")
    groups: dict[str, list[tuple[Path, int]]] = {}

    for f in cold_dir.glob("*.parquet"):
        m = pattern.match(f.name)
        if not m:
            continue
        doc_name = m.group(1)
        version_str = m.group(2)
        major_version = int(version_str.split("_")[0])
        groups.setdefault(doc_name, []).append((f, major_version))

    for doc_name in groups:
        groups[doc_name].sort(key=lambda x: x[1], reverse=True)

    return groups


def _prune_old_versions(version_map: dict[str, list[tuple[Path, int]]], max_versions: int) -> int:
    """Delete oldest version files, keeping at most max_versions per document."""
    deleted = 0
    for _doc_name, files in version_map.items():
        if len(files) <= max_versions:
            continue
        to_delete = files[max_versions:]
        for file_path, _ in to_delete:
            try:
                os.remove(file_path)
                deleted += 1
                logger.info("Pruned cold storage file: %s", file_path)
            except PermissionError:
                logger.warning("Permission denied deleting %s", file_path)
            except OSError as e:
                logger.error("Failed to delete %s: %s", file_path, e)
    return deleted


def cleanup_cold_storage(cold_dir: str, max_versions: int | None = None) -> int:
    """TTL-based cleanup: keep last N versions per document in cold storage.

    :param cold_dir: path to cold storage directory with Parquet files
    :param max_versions: max versions to retain (default: COLD_STORAGE_MAX_VERSIONS)
    :return: number of deleted files
    """
    if not COLD_STORAGE_ENABLED:
        logger.info("Cold storage cleanup is disabled")
        return 0

    if max_versions is None:
        max_versions = COLD_STORAGE_MAX_VERSIONS

    cold_path = Path(cold_dir)
    if not cold_path.is_dir():
        logger.warning("Cold storage directory not found: %s", cold_dir)
        return 0

    version_map = _list_parquet_versions(cold_path)
    total = sum(len(v) for v in version_map.values())

    if total == 0:
        logger.info("No Parquet files found in %s", cold_dir)
        return 0

    deleted = _prune_old_versions(version_map, max_versions)
    logger.info(
        "Cold storage cleanup: pruned %d files from %d total across %d documents",
        deleted,
        total,
        len(version_map),
    )
    return deleted
