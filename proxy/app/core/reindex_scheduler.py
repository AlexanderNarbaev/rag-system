# proxy/app/core/reindex_scheduler.py
"""Automated reindexing scheduler for stale knowledge base documents.

Periodically checks all knowledge bases for stale documents and
triggers ETL re-extraction tasks for documents that exceed the
staleness threshold. Uses an asyncio background task with configurable
check interval.
"""

import asyncio
import logging
import time
from typing import Any

from proxy.app.shared.config import (
    REINDEX_CHECK_INTERVAL,
    REINDEX_ENABLED,
    REINDEX_MAX_CONCURRENT_TASKS,
    REINDEX_STALENESS_THRESHOLD,
)

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task[None] | None = None
_scheduler_running = False
_last_check_time: float = 0.0
_reindex_status: dict[str, Any] = {
    "running": False,
    "last_check_time": None,
    "total_stale_found": 0,
    "tasks_triggered": 0,
    "errors": [],
    "per_kb": {},
}


def get_reindex_status() -> dict[str, Any]:
    """Get current reindex scheduler status."""
    return dict(_reindex_status)


async def _trigger_reindex_for_document(
    kb_id: str,
    source_type: str,
    source_id: str,
    kb_manager: Any,
) -> bool:
    """Create an ETL task for a single stale document."""
    try:
        task = kb_manager.create_task(
            kb_id=kb_id,
            source_type=source_type,
            source_id=source_id,
        )
        kb_manager.update_task(task.id, status="running")
        logger.info("Reindex task created: %s for %s/%s", task.id, source_type, source_id)
        _record_reindex_metric(kb_id, "triggered")
        return True
    except Exception as e:
        logger.error("Failed to trigger reindex for %s/%s: %s", source_type, source_id, e)
        _record_reindex_metric(kb_id, "failed")
        return False


def _record_reindex_metric(kb_id: str, status: str) -> None:
    try:
        from proxy.app.shared.metrics import rag_reindex_tasks_total

        rag_reindex_tasks_total.labels(kb_id=kb_id, status=status).inc()
    except Exception:
        pass


async def force_reindex_stale(kb_id: str, kb_manager: Any, qdrant_client: Any) -> dict[str, Any]:
    """Force reindex all stale documents in a knowledge base.

    Args:
        kb_id: Knowledge base ID.
        kb_manager: KnowledgeBaseManager instance.
        qdrant_client: Qdrant client.

    Returns:
        Dict with results: kb_id, stale_count, tasks_created, errors.
    """
    from proxy.app.core.stale_detector import detect_stale_documents

    kb = kb_manager.get_kb(kb_id)
    if kb is None:
        return {"kb_id": kb_id, "error": "KB not found"}

    stale_docs = detect_stale_documents(
        kb_id=kb_id,
        kb_manager=kb_manager,
        qdrant_client=qdrant_client,
        collection_name=kb.collection_name,
        threshold=float(REINDEX_STALENESS_THRESHOLD),
    )

    result: dict[str, Any] = {
        "kb_id": kb_id,
        "stale_count": len(stale_docs),
        "tasks_created": 0,
        "errors": [],
        "documents": stale_docs,
    }

    semaphore = asyncio.Semaphore(REINDEX_MAX_CONCURRENT_TASKS)

    async def _trigger_with_limit(doc: dict[str, Any]) -> None:
        async with semaphore:
            success = await _trigger_reindex_for_document(
                kb_id=kb_id,
                source_type=doc["source_type"],
                source_id=doc["source_id"],
                kb_manager=kb_manager,
            )
            if success:
                result["tasks_created"] += 1
            else:
                result["errors"].append(f"Failed: {doc['source_type']}/{doc['source_id']}")

    tasks = [_trigger_with_limit(d) for d in stale_docs]
    if tasks:
        await asyncio.gather(*tasks)

    _reindex_status["per_kb"][kb_id] = {
        "last_run": time.time(),
        "stale_count": len(stale_docs),
        "tasks_created": result["tasks_created"],
    }

    try:
        from proxy.app.shared.metrics import rag_reindex_last_run_seconds

        rag_reindex_last_run_seconds.labels(kb_id=kb_id).set(time.time())
    except Exception:
        pass

    return result


async def _reindex_check_loop(kb_manager: Any, qdrant_client: Any) -> None:
    """Background loop that periodically checks for stale documents."""
    global _scheduler_running, _last_check_time

    logger.info(
        "Reindex scheduler started (interval=%ds, threshold=%d)",
        REINDEX_CHECK_INTERVAL,
        REINDEX_STALENESS_THRESHOLD,
    )

    while _scheduler_running:
        try:
            _reindex_status["running"] = True
            _reindex_status["last_check_time"] = time.time()
            _last_check_time = time.time()

            kbs = kb_manager.list_kbs(include_deleted=False)
            total_stale = 0
            total_triggered = 0

            for kb in kbs:
                from proxy.app.core.stale_detector import detect_stale_documents, update_prometheus_metrics

                stale_docs = detect_stale_documents(
                    kb_id=kb.id,
                    kb_manager=kb_manager,
                    qdrant_client=qdrant_client,
                    collection_name=kb.collection_name,
                    threshold=float(REINDEX_STALENESS_THRESHOLD),
                )
                update_prometheus_metrics(kb.id, len(stale_docs))

                if stale_docs:
                    total_stale += len(stale_docs)
                    semaphore = asyncio.Semaphore(REINDEX_MAX_CONCURRENT_TASKS)

                    async def _reindex_one(
                        doc: dict[str, Any],
                        _kb_id: str = kb.id,
                        _sem: asyncio.Semaphore = semaphore,
                    ) -> None:
                        async with _sem:
                            await _trigger_reindex_for_document(
                                kb_id=_kb_id,
                                source_type=doc["source_type"],
                                source_id=doc["source_id"],
                                kb_manager=kb_manager,
                            )

                    reindex_tasks = [_reindex_one(d) for d in stale_docs]
                    if reindex_tasks:
                        await asyncio.gather(*reindex_tasks)
                        total_triggered += len(reindex_tasks)

                    _reindex_status["per_kb"][kb.id] = {
                        "last_run": time.time(),
                        "stale_count": len(stale_docs),
                        "tasks_triggered": len(stale_docs),
                    }

                    try:
                        from proxy.app.shared.metrics import rag_reindex_last_run_seconds

                        rag_reindex_last_run_seconds.labels(kb_id=kb.id).set(time.time())
                    except Exception:
                        pass

                else:
                    _reindex_status["per_kb"][kb.id] = {
                        "last_run": time.time(),
                        "stale_count": 0,
                        "tasks_triggered": 0,
                    }

            _reindex_status["total_stale_found"] = total_stale
            _reindex_status["tasks_triggered"] = total_triggered
            _reindex_status["running"] = False

            if total_stale > 0:
                logger.info("Reindex check complete: %d stale docs, %d tasks triggered", total_stale, total_triggered)

        except Exception as e:
            logger.error("Reindex scheduler error: %s", e, exc_info=True)
            _reindex_status["errors"].append(str(e))
            _reindex_status["running"] = False

        await asyncio.sleep(REINDEX_CHECK_INTERVAL)


async def start_reindex_scheduler(kb_manager: Any, qdrant_client: Any) -> None:
    """Start the background reindex scheduler."""
    global _scheduler_task, _scheduler_running

    if not REINDEX_ENABLED:
        logger.info("Reindex scheduler disabled via config")
        return

    if _scheduler_running:
        logger.warning("Reindex scheduler already running")
        return

    _scheduler_running = True
    _scheduler_task = asyncio.create_task(_reindex_check_loop(kb_manager, qdrant_client))
    logger.info("Reindex scheduler background task created")


async def stop_reindex_scheduler() -> None:
    """Stop the background reindex scheduler."""
    global _scheduler_task, _scheduler_running

    _scheduler_running = False
    import contextlib

    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _scheduler_task
    logger.info("Reindex scheduler stopped")
