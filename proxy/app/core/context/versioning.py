# proxy/app/core/context/versioning.py
"""Version extraction and resolution for RAG context."""

import logging
import re
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def extract_version_from_query(query: str) -> str | None:
    """Extracts a document version from the query text.
    Supported patterns:
    - v1.2, v2.0.1
    - version 1.2
    - version=1.2
    - as of 2023-01-01 (date as a version)
    """
    if not query:
        return None

    # Search for semantic versions
    patterns = [
        r"(?:v|version)[\s]*(\d+(?:\.\d+)+(?:\.\d+)?)",  # v1.2.3, version 1.2.3
        r"version[\s]*[=:][\s]*(\d+(?:\.\d+)+)",  # version=1.2
        r"версия[\s]*(\d+(?:\.\d+)+)",  # Russian variant
    ]
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1)

    # Search for a date as a version (YYYY-MM-DD)
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", query)
    if date_match:
        return date_match.group(1)

    return None


def resolve_versions(
    chunks_with_scores: list[tuple[dict[str, Any], float]],
    requested_version: str | None = None,
) -> list[tuple[dict[str, Any], float]]:
    """Version resolution: for each document (source_id) keeps chunks of only one version.
    If a specific version is requested (requested_version) — keeps only that one.
    Otherwise — selects chunks with the highest version (ignoring outdated ones).
    Assumes the version is stored in the chunk's 'version' field (a string, e.g. "1.2" or "2025-01-01").
    """
    if not chunks_with_scores:
        return []

    # Group by source_id
    groups = defaultdict(list)
    for chunk, score in chunks_with_scores:
        source_id = chunk.get("source_id", "unknown")
        groups[source_id].append((chunk, score))

    resolved = []
    for source_id, group in groups.items():
        # If a specific version was requested
        if requested_version:
            filtered = [(ch, sc) for ch, sc in group if ch.get("version") == requested_version]
            if filtered:
                resolved.extend(filtered)
                continue
            # If no chunks have the requested version, try to find the closest one (by version semantics)
            logger.warning(f"Requested version {requested_version} not found for {source_id}, using latest")

        # Find the highest version (simple string comparison works for dates and semantic versions)
        def version_key(chunk: dict[str, Any]) -> tuple[int, ...]:
            v = chunk.get("version", "0")
            # Try to convert to a tuple of numbers
            parts = re.split(r"[.-]", v)
            try:
                return tuple(int(p) for p in parts if p.isdigit())
            except Exception:
                return (0,)

        best_chunk = max(group, key=lambda x: version_key(x[0]))
        resolved.append(best_chunk)

    logger.debug(
        f"Version resolution: {len(chunks_with_scores)} -> {len(resolved)} chunks (requested: {requested_version})",
    )
    return resolved
