"""Path sanitization utilities for the RAG proxy.

Provides safe path resolution that prevents directory traversal attacks
by verifying resolved paths are within an allowed base directory.
"""

from __future__ import annotations

from pathlib import Path


def sanitize_path(path: str | Path, base_dir: Path | None = None) -> Path:
    """Resolve and optionally verify path containment.

    Args:
        path: The path to resolve and verify.
        base_dir: Optional allowed base directory.

    Returns:
        Resolved Path object.

    Raises:
        ValueError: If base_dir is provided and path escapes it.
    """
    resolved = Path(path).resolve()
    if base_dir is not None:
        base_resolved = base_dir.resolve()
        if not str(resolved).startswith(str(base_resolved) + "/") and str(resolved) != str(base_resolved):
            raise ValueError(f"Path {path} escapes base directory {base_dir}")
    return resolved
