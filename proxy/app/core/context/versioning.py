# proxy/app/core/context/versioning.py
"""Version extraction and resolution for RAG context."""

import logging
import re
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def extract_version_from_query(query: str) -> str | None:
    """
    Извлекает версию документа из текстового запроса.
    Поддерживаемые паттерны:
    - v1.2, v2.0.1
    - version 1.2
    - version=1.2
    - as of 2023-01-01 (дата как версия)
    """
    if not query:
        return None

    # Поиск семантических версий
    patterns = [
        r"(?:v|version)[\s]*(\d+(?:\.\d+)+(?:\.\d+)?)",  # v1.2.3, version 1.2.3
        r"version[\s]*[=:][\s]*(\d+(?:\.\d+)+)",  # version=1.2
        r"версия[\s]*(\d+(?:\.\d+)+)",  # русский вариант
    ]
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1)

    # Поиск даты как версии (YYYY-MM-DD)
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", query)
    if date_match:
        return date_match.group(1)

    return None


def resolve_versions(
    chunks_with_scores: list[tuple[dict[str, Any], float]], requested_version: str | None = None
) -> list[tuple[dict[str, Any], float]]:
    """
    Разрешение версий: для каждого документа (source_id) оставляет чанки только одной версии.
    Если запрошена конкретная версия (requested_version) – оставляет только её.
    Иначе – выбирает чанки с максимальной версией (игнорируя устаревшие).
    Предполагается, что версия хранится в поле 'version' чанка (строка, например "1.2" или "2025-01-01").
    """
    if not chunks_with_scores:
        return []

    # Группировка по source_id
    groups = defaultdict(list)
    for chunk, score in chunks_with_scores:
        source_id = chunk.get("source_id", "unknown")
        groups[source_id].append((chunk, score))

    resolved = []
    for source_id, group in groups.items():
        # Если запрошена конкретная версия
        if requested_version:
            filtered = [(ch, sc) for ch, sc in group if ch.get("version") == requested_version]
            if filtered:
                resolved.extend(filtered)
                continue
            # Если нет чанков с запрошенной версией, пробуем найти ближайшую (по семантике версий)
            logger.warning(f"Requested version {requested_version} not found for {source_id}, using latest")

        # Найти максимальную версию (простейшее строковое сравнение, для дат и семантических версий)
        def version_key(chunk: dict[str, Any]) -> tuple[int, ...]:
            v = chunk.get("version", "0")
            # Пытаемся преобразовать в кортеж чисел
            parts = re.split(r"[.-]", v)
            try:
                return tuple(int(p) for p in parts if p.isdigit())
            except Exception:
                return (0,)

        best_chunk = max(group, key=lambda x: version_key(x[0]))
        resolved.append(best_chunk)

    logger.debug(
        f"Version resolution: {len(chunks_with_scores)} -> {len(resolved)} chunks (requested: {requested_version})"
    )
    return resolved
