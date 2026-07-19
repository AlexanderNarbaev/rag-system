"""Trainer base module — ABC, TrainingJob, TrainerRegistry for model fine-tuning."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TrainingStatus(Enum):
    """Job status lifecycle: QUEUED → RUNNING → VALIDATING → COMPLETED/FAILED."""

    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TrainingJob:
    """Represents a training job with its configuration, status, and results."""

    model_name: str
    dataset_path: str
    hyperparams: dict[str, Any] = field(default_factory=dict)
    status: TrainingStatus = TrainingStatus.QUEUED
    job_id: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None


class TrainerBase(ABC):
    """Abstract base class for all model trainers (SLM, LLM, Reranker)."""

    @abstractmethod
    def train(self, job: TrainingJob) -> TrainingJob:
        """Execute the training loop. Returns the updated job with status and metrics."""

    @abstractmethod
    def validate(self, job: TrainingJob) -> dict[str, float]:
        """Validate the trained model. Returns validation metrics."""

    @abstractmethod
    def save_checkpoint(self, job: TrainingJob, path: str) -> str:
        """Save a training checkpoint to the given path. Returns the checkpoint path."""

    @abstractmethod
    def load_checkpoint(self, path: str) -> TrainingJob:
        """Load a training checkpoint and restore a TrainingJob from it."""


class TrainerRegistry:
    """Registry for training implementations, keyed by trainer type name."""

    def __init__(self) -> None:
        self._trainers: dict[str, type[TrainerBase]] = {}

    def register_trainer(self, name: str, trainer_cls: type[TrainerBase]) -> None:
        """Register a trainer implementation under a unique name."""
        self._trainers[name] = trainer_cls

    def unregister_trainer(self, name: str) -> None:
        """Remove a trainer from the registry. No-op if not registered."""
        self._trainers.pop(name, None)

    def get_trainer(self, name: str) -> type[TrainerBase]:
        """Get a registered trainer class by name. Raises KeyError if not found."""
        if name not in self._trainers:
            raise KeyError(f"Trainer '{name}' not registered. Available: {list(self._trainers.keys())}")
        return self._trainers[name]

    def list_trainers(self) -> set[str]:
        """Return the set of registered trainer names."""
        return set(self._trainers.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._trainers

    def __len__(self) -> int:
        return len(self._trainers)
