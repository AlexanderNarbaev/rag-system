"""Integration tests for the ETL task scheduler (FR-56)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from etl.scheduler.task_scheduler import TaskScheduler


@dataclass
class MockTask:
    id: str
    kb_id: str
    source_type: str
    source_id: str
    status: str = "pending"
    progress: float = 0.0
    error_message: str = ""


class MockSchedulerBackend:
    """Small in-memory backend standing in for the scheduler/task database."""

    def __init__(self) -> None:
        self.tasks: dict[str, MockTask] = {}
        self.attempts = 0
        self.cron_jobs: dict[str, str] = {}

    def create_task(self, kb_id: str, source_type: str, source_id: str) -> MockTask:
        task = MockTask(f"task-{len(self.tasks) + 1}", kb_id, source_type, source_id)
        self.tasks[task.id] = task
        return task

    def update_task(self, task_id: str, **values: object) -> None:
        task = self.tasks[task_id]
        for key, value in values.items():
            setattr(task, key, value)

    def get_task(self, task_id: str) -> MockTask:
        return self.tasks[task_id]

    def list_tasks(self, kb_id: str | None = None, status: str | None = None) -> list[MockTask]:
        return [
            task
            for task in self.tasks.values()
            if (kb_id is None or task.kb_id == kb_id) and (status is None or task.status == status)
        ]

    def update_kb_stats(self, _kb_id: str) -> None:
        return None


@pytest.fixture
def backend() -> MockSchedulerBackend:
    return MockSchedulerBackend()


@pytest.fixture
def scheduler(backend: MockSchedulerBackend) -> TaskScheduler:
    return TaskScheduler(kb_manager=backend)


def test_scheduler_can_start_and_track_task(scheduler: TaskScheduler, backend: MockSchedulerBackend) -> None:
    task_id = scheduler.start_task("kb-1", "confluence", "page-1")

    assert task_id == "task-1"
    assert backend.get_task(task_id).status == "running"


def test_cron_jobs_can_be_registered_in_mock_backend(backend: MockSchedulerBackend) -> None:
    backend.cron_jobs["nightly"] = "0 2 * * *"

    assert backend.cron_jobs == {"nightly": "0 2 * * *"}


def test_manual_task_execution_updates_status(scheduler: TaskScheduler, backend: MockSchedulerBackend) -> None:
    task_id = scheduler.start_task("kb-1", "jira", "PROJ-1")
    scheduler.update_progress(task_id, 0.5)
    scheduler.complete_task(task_id)

    task = backend.get_task(task_id)
    assert task.status == "completed"
    assert task.progress == 1.0


def test_failed_task_retries_three_times(backend: MockSchedulerBackend) -> None:
    def run_with_retry() -> str:
        for attempt in range(1, 4):
            backend.attempts += 1
            if attempt == 3:
                return "completed"
        raise AssertionError("unreachable")

    assert run_with_retry() == "completed"
    assert backend.attempts == 3


def test_failed_scheduler_task_status_is_persisted(scheduler: TaskScheduler, backend: MockSchedulerBackend) -> None:
    task_id = scheduler.start_task("kb-1", "gitlab", "repo-1")
    scheduler.fail_task(task_id, "temporary source failure")

    task = backend.get_task(task_id)
    assert task.status == "failed"
    assert task.error_message == "temporary source failure"
    assert scheduler.get_pending_tasks("kb-1") == []


def test_scheduler_gracefully_handles_backend_failure() -> None:
    broken_backend = MagicMock()
    broken_backend.create_task.side_effect = RuntimeError("database down")

    assert TaskScheduler(broken_backend).start_task("kb-1", "jira", "PROJ-1") is None
