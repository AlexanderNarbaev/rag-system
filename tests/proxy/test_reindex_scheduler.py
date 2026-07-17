"""Tests for reindex_scheduler module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxy.app.core.reindex_scheduler import (
    _record_reindex_metric,
    _trigger_reindex_for_document,
    force_reindex_stale,
    get_reindex_status,
    stop_reindex_scheduler,
)


class TestGetReindexStatus:
    def test_returns_dict(self):
        status = get_reindex_status()
        assert isinstance(status, dict)
        assert "running" in status
        assert "total_stale_found" in status


class TestRecordReindexMetric:
    @patch("proxy.app.shared.metrics.rag_reindex_tasks_total", None)
    def test_does_not_raise_when_metric_is_none(self):
        _record_reindex_metric("kb-1", "triggered")

    def test_does_not_raise_on_import_error(self):
        with patch(
            "proxy.app.shared.metrics.rag_reindex_tasks_total",
            side_effect=ImportError,
        ):
            _record_reindex_metric("kb-1", "triggered")

    def test_increments_counter(self):
        mock_metric = MagicMock()
        with patch(
            "proxy.app.shared.metrics.rag_reindex_tasks_total",
            mock_metric,
        ):
            _record_reindex_metric("kb-1", "triggered")
            mock_metric.labels.assert_called_once_with(kb_id="kb-1", status="triggered")
            mock_metric.labels.return_value.inc.assert_called_once()


class TestTriggerReindexForDocument:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_task = MagicMock()
        mock_task.id = "task-1"
        mock_kb_manager = MagicMock()
        mock_kb_manager.create_task.return_value = mock_task
        mock_kb_manager.update_task = MagicMock()

        with patch("proxy.app.core.reindex_scheduler._record_reindex_metric"):
            result = await _trigger_reindex_for_document(
                kb_id="kb-1",
                source_type="confluence",
                source_id="conf-123",
                kb_manager=mock_kb_manager,
            )
        assert result is True
        mock_kb_manager.create_task.assert_called_once_with(
            kb_id="kb-1", source_type="confluence", source_id="conf-123",
        )
        mock_kb_manager.update_task.assert_called_once_with("task-1", status="running")

    @pytest.mark.asyncio
    async def test_failure(self):
        mock_kb_manager = MagicMock()
        mock_kb_manager.create_task.side_effect = RuntimeError("boom")

        with patch("proxy.app.core.reindex_scheduler._record_reindex_metric") as mock_record:
            result = await _trigger_reindex_for_document(
                kb_id="kb-1",
                source_type="confluence",
                source_id="conf-123",
                kb_manager=mock_kb_manager,
            )
            assert result is False
            mock_record.assert_called_once_with("kb-1", "failed")


class TestForceReindexStale:
    @pytest.mark.asyncio
    async def test_kb_not_found(self):
        mock_kb_manager = MagicMock()
        mock_kb_manager.get_kb.return_value = None

        result = await force_reindex_stale("kb-1", mock_kb_manager, MagicMock())
        assert result["kb_id"] == "kb-1"
        assert "error" in result
        assert result["error"] == "KB not found"

    @pytest.mark.asyncio
    async def test_no_stale_documents(self):
        mock_kb = MagicMock()
        mock_kb.collection_name = "test_collection"
        mock_kb_manager = MagicMock()
        mock_kb_manager.get_kb.return_value = mock_kb

        with patch("proxy.app.core.stale_detector.detect_stale_documents", return_value=[]):
            result = await force_reindex_stale("kb-1", mock_kb_manager, MagicMock())
            assert result["stale_count"] == 0
            assert result["tasks_created"] == 0
            assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_with_stale_documents_all_success(self):
        mock_kb = MagicMock()
        mock_kb.collection_name = "test_collection"
        mock_kb_manager = MagicMock()
        mock_kb_manager.get_kb.return_value = mock_kb
        mock_task = MagicMock()
        mock_task.id = "t1"
        mock_kb_manager.create_task.return_value = mock_task
        mock_kb_manager.update_task = MagicMock()

        stale_docs = [
            {"source_type": "confluence", "source_id": "s1"},
            {"source_type": "jira", "source_id": "s2"},
        ]

        with (
            patch("proxy.app.core.stale_detector.detect_stale_documents", return_value=stale_docs),
            patch("proxy.app.core.reindex_scheduler._record_reindex_metric"),
        ):
            result = await force_reindex_stale("kb-1", mock_kb_manager, MagicMock())
            assert result["stale_count"] == 2
            assert result["tasks_created"] == 2
            assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_with_stale_documents_partial_failure(self):
        mock_kb = MagicMock()
        mock_kb.collection_name = "test_collection"
        mock_kb_manager = MagicMock()
        mock_kb_manager.get_kb.return_value = mock_kb
        mock_task = MagicMock()
        mock_task.id = "t1"
        mock_kb_manager.create_task.side_effect = [mock_task, RuntimeError("fail")]
        mock_kb_manager.update_task = MagicMock()

        stale_docs = [
            {"source_type": "confluence", "source_id": "s1"},
            {"source_type": "jira", "source_id": "s2"},
        ]

        with (
            patch("proxy.app.core.stale_detector.detect_stale_documents", return_value=stale_docs),
            patch("proxy.app.core.reindex_scheduler._record_reindex_metric"),
        ):
            result = await force_reindex_stale("kb-1", mock_kb_manager, MagicMock())
            assert result["stale_count"] == 2
            assert result["tasks_created"] == 1
            assert len(result["errors"]) == 1


class TestStartReindexScheduler:
    @pytest.mark.asyncio
    async def test_disabled_via_config(self):
        import proxy.app.core.reindex_scheduler as scheduler

        saved_enabled = scheduler.REINDEX_ENABLED
        scheduler.REINDEX_ENABLED = False
        try:
            from proxy.app.core.reindex_scheduler import start_reindex_scheduler

            await start_reindex_scheduler(AsyncMock(), MagicMock())
            assert scheduler._scheduler_running is False
        finally:
            scheduler.REINDEX_ENABLED = saved_enabled

    @pytest.mark.asyncio
    async def test_already_running(self):
        import proxy.app.core.reindex_scheduler as scheduler

        saved_enabled = scheduler.REINDEX_ENABLED
        saved_running = scheduler._scheduler_running
        scheduler.REINDEX_ENABLED = True
        scheduler._scheduler_running = True
        try:
            await scheduler.start_reindex_scheduler(AsyncMock(), MagicMock())
        finally:
            scheduler.REINDEX_ENABLED = saved_enabled
            scheduler._scheduler_running = saved_running


class TestStopReindexScheduler:
    @pytest.mark.asyncio
    async def test_stops_running_scheduler(self):
        import proxy.app.core.reindex_scheduler as scheduler

        saved_running = scheduler._scheduler_running
        saved_task = scheduler._scheduler_task

        scheduler._scheduler_running = True
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.cancel = MagicMock()
        scheduler._scheduler_task = mock_task
        try:
            await stop_reindex_scheduler()
            assert scheduler._scheduler_running is False
            mock_task.cancel.assert_not_called()
        finally:
            scheduler._scheduler_running = saved_running
            scheduler._scheduler_task = saved_task

    @pytest.mark.asyncio
    async def test_already_stopped_noop(self):
        import proxy.app.core.reindex_scheduler as scheduler

        saved_running = scheduler._scheduler_running
        saved_task = scheduler._scheduler_task
        scheduler._scheduler_running = False
        scheduler._scheduler_task = None
        try:
            await stop_reindex_scheduler()
            assert scheduler._scheduler_running is False
        finally:
            scheduler._scheduler_running = saved_running
            scheduler._scheduler_task = saved_task

    @pytest.mark.asyncio
    async def test_already_done_noop(self):
        import proxy.app.core.reindex_scheduler as scheduler

        saved_running = scheduler._scheduler_running
        saved_task = scheduler._scheduler_task

        scheduler._scheduler_running = True
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.cancel = MagicMock()
        scheduler._scheduler_task = mock_task
        try:
            await stop_reindex_scheduler()
            assert scheduler._scheduler_running is False
            mock_task.cancel.assert_not_called()
        finally:
            scheduler._scheduler_running = saved_running
            scheduler._scheduler_task = saved_task
