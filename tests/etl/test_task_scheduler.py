# tests/etl/test_task_scheduler.py
"""Tests for TaskScheduler — ETL task tracking integration."""

import pytest

from etl.scheduler.task_scheduler import TaskScheduler
from proxy.app.core.kb_manager import KnowledgeBaseManager


@pytest.fixture
def kb_manager (tmp_path):
  """Create a KBManager with a temporary database."""
  return KnowledgeBaseManager (db_path = str (tmp_path / "test.db"), qdrant_client = None)


@pytest.fixture
def sample_kb (kb_manager):
  """Create a sample knowledge base."""
  return kb_manager.create_kb (name = "Test KB", description = "For testing")


@pytest.fixture
def scheduler (kb_manager):
  """Create a TaskScheduler with a real KB manager."""
  return TaskScheduler (kb_manager = kb_manager)


@pytest.fixture
def no_tracking_scheduler ():
  """Create a TaskScheduler without KB manager (tracking disabled)."""
  return TaskScheduler (kb_manager = None)


class TestTaskSchedulerWithTracking:
  """Test task scheduler with KB manager tracking enabled."""
  
  def test_start_task_creates_and_runs (self, scheduler, sample_kb):
    task_id = scheduler.start_task (sample_kb.id, "confluence", "page-123")
    assert task_id is not None
    # Task should be running
    task = scheduler.kb_manager.get_task (task_id)
    assert task.status == "running"
    assert task.source_type == "confluence"
    assert task.source_id == "page-123"
  
  def test_update_progress (self, scheduler, sample_kb):
    task_id = scheduler.start_task (sample_kb.id, "jira", "ISSUE-42")
    scheduler.update_progress (task_id, 0.5)
    task = scheduler.kb_manager.get_task (task_id)
    assert task.progress == 0.5
  
  def test_complete_task (self, scheduler, sample_kb):
    task_id = scheduler.start_task (sample_kb.id, "gitlab", "proj-1")
    scheduler.complete_task (task_id)
    task = scheduler.kb_manager.get_task (task_id)
    assert task.status == "completed"
    assert task.progress == 1.0
  
  def test_fail_task (self, scheduler, sample_kb):
    task_id = scheduler.start_task (sample_kb.id, "confluence", "page-456")
    scheduler.fail_task (task_id, "Connection timeout")
    task = scheduler.kb_manager.get_task (task_id)
    assert task.status == "failed"
    assert task.error_message == "Connection timeout"
  
  def test_get_pending_tasks (self, scheduler, sample_kb):
    # Create a pending task directly
    scheduler.kb_manager.create_task (sample_kb.id, "confluence", "p1")
    pending = scheduler.get_pending_tasks (sample_kb.id)
    assert len (pending) == 1
    assert pending [0].status == "pending"
  
  def test_get_running_tasks (self, scheduler, sample_kb):
    scheduler.start_task (sample_kb.id, "jira", "i1")
    running = scheduler.get_running_tasks (sample_kb.id)
    assert len (running) == 1
    assert running [0].status == "running"


class TestTaskSchedulerWithoutTracking:
  """Test task scheduler when KB manager is not set (graceful no-op)."""
  
  def test_start_task_returns_none (self, no_tracking_scheduler):
    task_id = no_tracking_scheduler.start_task ("kb-1", "confluence", "page-1")
    assert task_id is None
  
  def test_update_progress_noop (self, no_tracking_scheduler):
    # Should not raise
    no_tracking_scheduler.update_progress ("fake-id", 0.5)
  
  def test_complete_task_noop (self, no_tracking_scheduler):
    # Should not raise
    no_tracking_scheduler.complete_task ("fake-id")
  
  def test_fail_task_noop (self, no_tracking_scheduler):
    # Should not raise
    no_tracking_scheduler.fail_task ("fake-id", "error")
  
  def test_get_pending_tasks_returns_empty (self, no_tracking_scheduler):
    assert no_tracking_scheduler.get_pending_tasks () == []
  
  def test_get_running_tasks_returns_empty (self, no_tracking_scheduler):
    assert no_tracking_scheduler.get_running_tasks () == []
