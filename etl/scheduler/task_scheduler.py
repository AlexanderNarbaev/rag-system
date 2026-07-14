# etl/scheduler/task_scheduler.py
"""
ETL Task Scheduler — integrates KB manager task tracking with the ETL pipeline.

When ETL runs, it updates task status in the SQLite database via the KB manager.
This module provides the bridge between the ETL orchestrator and the admin UI.

Usage:
    scheduler = TaskScheduler(kb_manager)
    scheduler.start_extraction_task(kb_id, "confluence", "page-123")
    # ... run extraction ...
    scheduler.complete_task(task_id)
"""

import logging
import time
from typing import Any

logger = logging.getLogger (__name__)


class TaskScheduler:
  """Bridges ETL pipeline execution with KB manager task tracking."""
  
  def __init__ (self, kb_manager: Any = None):
    self.kb_manager = kb_manager
    self._active_tasks: dict [str, str] = {}  # task_key -> task_id
  
  def start_task (self, kb_id: str, source_type: str, source_id: str) -> str | None:
    """Register a new ETL task and mark it as running.
    
    Returns task_id if tracking is enabled, None otherwise.
    """
    if self.kb_manager is None:
      logger.debug ("KB manager not set — task tracking disabled")
      return None
    
    try:
      task = self.kb_manager.create_task (kb_id = kb_id, source_type = source_type, source_id = source_id)
      self.kb_manager.update_task (task.id, status = "running")
      task_key = f"{kb_id}:{source_type}:{source_id}"
      self._active_tasks [task_key] = task.id
      logger.info ("Started ETL task %s for %s/%s", task.id, source_type, source_id)
      return task.id
    except Exception as e:
      logger.warning ("Failed to create ETL task: %s", e)
      return None
  
  def update_progress (self, task_id: str, progress: float, message: str = "") -> None:
    """Update task progress (0.0 to 1.0)."""
    if self.kb_manager is None or task_id is None:
      return
    try:
      self.kb_manager.update_task (task_id, progress = progress)
    except Exception as e:
      logger.warning ("Failed to update task progress: %s", e)
  
  def complete_task (self, task_id: str) -> None:
    """Mark a task as completed."""
    if self.kb_manager is None or task_id is None:
      return
    try:
      self.kb_manager.update_task (task_id, status = "completed", progress = 1.0)
      # Update KB statistics
      task = self.kb_manager.get_task (task_id)
      if task:
        self.kb_manager.update_kb_stats (task.kb_id)
      logger.info ("ETL task %s completed", task_id)
    except Exception as e:
      logger.warning ("Failed to complete task: %s", e)
  
  def fail_task (self, task_id: str, error_message: str) -> None:
    """Mark a task as failed."""
    if self.kb_manager is None or task_id is None:
      return
    try:
      self.kb_manager.update_task (task_id, status = "failed", error_message = error_message)
      logger.warning ("ETL task %s failed: %s", task_id, error_message)
    except Exception as e:
      logger.warning ("Failed to mark task as failed: %s", e)
  
  def get_pending_tasks (self, kb_id: str | None = None) -> list:
    """Get all pending tasks, optionally filtered by KB."""
    if self.kb_manager is None:
      return []
    return self.kb_manager.list_tasks (kb_id = kb_id, status = "pending")
  
  def get_running_tasks (self, kb_id: str | None = None) -> list:
    """Get all running tasks, optionally filtered by KB."""
    if self.kb_manager is None:
      return []
    return self.kb_manager.list_tasks (kb_id = kb_id, status = "running")
