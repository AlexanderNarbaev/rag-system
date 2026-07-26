"""Graph retention policy: remove stale entities and relationships.

FR-25: Graph schema versioning with 90-day retention.

Nodes and relationships are deleted when their ``updated_at`` timestamp is
older than ``retention_days``. The Neo4j driver can be either the synchronous
``neo4j.Driver`` (with an async wrapper) or any object exposing an
``async with session()`` context manager that yields an object with a
``run(query, params)`` coroutine returning an awaitable single-record iterator.

This module is decoupled from the rest of the ETL pipeline and can be
scheduled by :func:`schedule_retention_task` or invoked manually from the
ETL orchestrator.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 90


def get_stale_threshold(days: int = DEFAULT_RETENTION_DAYS) -> datetime:
    """Return the timestamp threshold for staleness.

    Nodes/relationships with ``updated_at`` strictly less than this value are
    considered stale and eligible for deletion.
    """
    return datetime.utcnow() - timedelta(days=days)


async def cleanup_stale_entities(
    neo4j_driver: Any,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
) -> dict[str, int]:
    """Remove entities and relationships older than ``retention_days``.

    Args:
        neo4j_driver: Neo4j driver (or compatible mock) exposing
            ``async with session()`` → ``session.run(query, params)``.
        retention_days: Age threshold in days (default 90).
        dry_run: If ``True``, only count the stale items; do not delete.

    Returns:
        Dict with ``nodes_deleted``, ``relationships_deleted`` and a
        ``dry_run`` flag. Both counts are zero when nothing matched.
    """
    threshold = get_stale_threshold(retention_days)
    iso_threshold = threshold.isoformat()

    query_count_nodes = "MATCH (n) WHERE n.updated_at < datetime($threshold) RETURN count(n) AS count"
    query_count_rels = "MATCH ()-[r]->() WHERE r.updated_at < datetime($threshold) RETURN count(r) AS count"
    query_detach_nodes = "MATCH (n) WHERE n.updated_at < datetime($threshold) DETACH DELETE n"
    query_delete_rels = "MATCH ()-[r]->() WHERE r.updated_at < datetime($threshold) DELETE r"

    nodes_count = 0
    rels_count = 0

    async with neo4j_driver.session() as session:
        # Count stale nodes/relationships first so the caller sees real
        # numbers even when ``dry_run`` is True.
        node_result = await session.run(query_count_nodes, threshold=iso_threshold)
        node_record = await node_result.single()
        if node_record is not None:
            nodes_count = int(node_record["count"])

        rel_result = await session.run(query_count_rels, threshold=iso_threshold)
        rel_record = await rel_result.single()
        if rel_record is not None:
            rels_count = int(rel_record["count"])

        if dry_run:
            logger.info(
                "Graph retention dry-run: would delete %d nodes, %d relationships older than %d days",
                nodes_count,
                rels_count,
                retention_days,
            )
            return {
                "nodes_deleted": nodes_count,
                "relationships_deleted": rels_count,
                "dry_run": True,
            }

        await session.run(query_detach_nodes, threshold=iso_threshold)
        await session.run(query_delete_rels, threshold=iso_threshold)

    logger.info(
        "Graph retention: deleted %d nodes, %d relationships older than %d days",
        nodes_count,
        rels_count,
        retention_days,
    )

    return {
        "nodes_deleted": nodes_count,
        "relationships_deleted": rels_count,
        "dry_run": False,
    }


async def schedule_retention_task(
    neo4j_driver: Any,
    interval_hours: int = 24,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> asyncio.Task:
    """Schedule periodic retention cleanup as a background asyncio task.

    The task runs immediately on start, then every ``interval_hours`` hours.
    Failures are logged but do not stop the task.
    """

    async def _run_periodically() -> None:
        while True:
            try:
                await cleanup_stale_entities(neo4j_driver, retention_days)
            except asyncio.CancelledError:
                logger.info("Graph retention task cancelled")
                raise
            except Exception as exc:
                logger.exception("Retention task failed: %s", exc)
            await asyncio.sleep(interval_hours * 3600)

    return asyncio.create_task(_run_periodically())
