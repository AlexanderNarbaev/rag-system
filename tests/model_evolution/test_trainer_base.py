"""Tests for proxy/app/model_evolution/trainer_base.py — TrainerBase, TrainingJob, TrainerRegistry."""

import json
import tempfile
from abc import ABC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.trainer_base import (
    TrainerBase,
    TrainerRegistry,
    TrainingJob,
    TrainingStatus,
)


class TestTrainingStatus:
    """Tests for TrainingStatus enum."""

    def test_enum_values(self):
        assert TrainingStatus.QUEUED.value == "queued"
        assert TrainingStatus.RUNNING.value == "running"
        assert TrainingStatus.VALIDATING.value == "validating"
        assert TrainingStatus.COMPLETED.value == "completed"
        assert TrainingStatus.FAILED.value == "failed"

    def test_enum_membership(self):
        members = {s for s in TrainingStatus}
        assert len(members) == 5
        assert TrainingStatus.QUEUED in members
        assert TrainingStatus.RUNNING in members
        assert TrainingStatus.VALIDATING in members
        assert TrainingStatus.COMPLETED in members
        assert TrainingStatus.FAILED in members

    def test_from_string(self):
        assert TrainingStatus("queued") == TrainingStatus.QUEUED
        assert TrainingStatus("running") == TrainingStatus.RUNNING
        assert TrainingStatus("validating") == TrainingStatus.VALIDATING
        assert TrainingStatus("completed") == TrainingStatus.COMPLETED
        assert TrainingStatus("failed") == TrainingStatus.FAILED

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            TrainingStatus("invalid")


class TestTrainingJob:
    """Tests for TrainingJob dataclass."""

    def test_create_with_required_fields(self):
        job = TrainingJob(
            model_name="slm-intent-classifier",
            dataset_path="/data/training/slm_intent.jsonl",
        )
        assert job.model_name == "slm-intent-classifier"
        assert job.dataset_path == "/data/training/slm_intent.jsonl"
        assert job.status == TrainingStatus.QUEUED
        assert job.hyperparams == {}
        assert job.job_id == ""
        assert job.metrics == {}
        assert job.started_at is None
        assert job.completed_at is None
        assert job.error_message is None

    def test_create_with_all_fields(self):
        job = TrainingJob(
            model_name="llm-domain-generator",
            dataset_path="/data/training/llm_completion.jsonl",
            hyperparams={"epochs": 3, "batch_size": 8, "lora_r": 16},
            status=TrainingStatus.RUNNING,
            job_id="job-abc-123",
            metrics={"accuracy": 0.95},
            started_at="2026-07-05T10:00:00Z",
            completed_at=None,
            error_message=None,
        )
        assert job.model_name == "llm-domain-generator"
        assert job.dataset_path == "/data/training/llm_completion.jsonl"
        assert job.hyperparams == {"epochs": 3, "batch_size": 8, "lora_r": 16}
        assert job.status == TrainingStatus.RUNNING
        assert job.job_id == "job-abc-123"
        assert job.metrics == {"accuracy": 0.95}
        assert job.started_at == "2026-07-05T10:00:00Z"
        assert job.completed_at is None
        assert job.error_message is None

    def test_default_status_is_queued(self):
        job = TrainingJob(model_name="test", dataset_path="/tmp/data.jsonl")
        assert job.status == TrainingStatus.QUEUED

    def test_status_transition_to_running(self):
        job = TrainingJob(model_name="test", dataset_path="/tmp/data.jsonl")
        assert job.status == TrainingStatus.QUEUED
        job.status = TrainingStatus.RUNNING
        assert job.status == TrainingStatus.RUNNING

    def test_status_transition_to_validating(self):
        job = TrainingJob(model_name="test", dataset_path="/tmp/data.jsonl")
        job.status = TrainingStatus.RUNNING
        job.status = TrainingStatus.VALIDATING
        assert job.status == TrainingStatus.VALIDATING

    def test_status_transition_to_completed(self):
        job = TrainingJob(model_name="test", dataset_path="/tmp/data.jsonl")
        job.status = TrainingStatus.RUNNING
        job.status = TrainingStatus.VALIDATING
        job.status = TrainingStatus.COMPLETED
        assert job.status == TrainingStatus.COMPLETED

    def test_status_transition_to_failed(self):
        job = TrainingJob(model_name="test", dataset_path="/tmp/data.jsonl")
        job.status = TrainingStatus.RUNNING
        job.status = TrainingStatus.FAILED
        assert job.status == TrainingStatus.FAILED

    def test_failed_job_captures_error(self):
        job = TrainingJob(
            model_name="test",
            dataset_path="/tmp/data.jsonl",
            status=TrainingStatus.FAILED,
            error_message="GPU OOM during training",
        )
        assert job.status == TrainingStatus.FAILED
        assert job.error_message == "GPU OOM during training"

    def test_completed_job_has_metrics(self):
        job = TrainingJob(
            model_name="test",
            dataset_path="/tmp/data.jsonl",
            status=TrainingStatus.COMPLETED,
            metrics={"bertscore_f1": 0.78, "rouge_l": 0.42, "hallucination_rate": 0.03},
            started_at="2026-07-05T10:00:00Z",
            completed_at="2026-07-05T10:30:00Z",
        )
        assert job.status == TrainingStatus.COMPLETED
        assert job.metrics == {"bertscore_f1": 0.78, "rouge_l": 0.42, "hallucination_rate": 0.03}
        assert job.completed_at == "2026-07-05T10:30:00Z"


class TestTrainerBaseABC:
    """Tests for TrainerBase abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            TrainerBase()  # type: ignore[abstract]

    def test_concrete_subclass_can_instantiate(self):
        class ConcreteTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="loaded", dataset_path=path)

        trainer = ConcreteTrainer()
        assert isinstance(trainer, TrainerBase)
        assert isinstance(trainer, ABC)

    def test_abstract_methods_required(self):
        class IncompleteTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

        with pytest.raises(TypeError):
            IncompleteTrainer()  # type: ignore[abstract]

    def test_train_method(self):
        class DummyTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                job.status = TrainingStatus.COMPLETED
                job.metrics = {"accuracy": 0.92}
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {"val_accuracy": 0.90}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return str(Path(path) / "checkpoint.pt")

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="restored", dataset_path=path)

        trainer = DummyTrainer()
        job = TrainingJob(model_name="test-model", dataset_path="/data/train.jsonl")
        result = trainer.train(job)
        assert result.status == TrainingStatus.COMPLETED
        assert result.metrics == {"accuracy": 0.92}

    def test_validate_method(self):
        class DummyTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {"val_loss": 0.1, "val_accuracy": 0.95}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="x", dataset_path=path)

        trainer = DummyTrainer()
        job = TrainingJob(model_name="test-model", dataset_path="/data/train.jsonl")
        metrics = trainer.validate(job)
        assert metrics == {"val_loss": 0.1, "val_accuracy": 0.95}

    def test_save_checkpoint(self):
        class DummyTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                checkpoint_path = Path(path) / "checkpoint.pt"
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                checkpoint_path.write_text("model weights")
                return str(checkpoint_path)

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="x", dataset_path=path)

        trainer = DummyTrainer()
        job = TrainingJob(model_name="test-model", dataset_path="/data/train.jsonl")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = trainer.save_checkpoint(job, tmpdir)
            assert result == str(Path(tmpdir) / "checkpoint.pt")
            assert Path(result).exists()
            assert Path(result).read_text() == "model weights"

    def test_load_checkpoint(self):
        class DummyTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                data = json.loads(Path(path).read_text())
                return TrainingJob(
                    model_name=data["model_name"],
                    dataset_path=data["dataset_path"],
                    status=TrainingStatus(data["status"]),
                    hyperparams=data.get("hyperparams", {}),
                    metrics=data.get("metrics", {}),
                )

        trainer = DummyTrainer()
        with tempfile.TemporaryDirectory() as tmpdir:
            cp_path = Path(tmpdir) / "checkpoint.json"
            cp_path.write_text(json.dumps({
                "model_name": "restored-model",
                "dataset_path": "/data/train.jsonl",
                "status": "running",
                "hyperparams": {"epochs": 5},
                "metrics": {"loss": 0.5},
            }))
            job = trainer.load_checkpoint(str(cp_path))
            assert job.model_name == "restored-model"
            assert job.dataset_path == "/data/train.jsonl"
            assert job.status == TrainingStatus.RUNNING
            assert job.hyperparams == {"epochs": 5}
            assert job.metrics == {"loss": 0.5}


class TestTrainerRegistry:
    """Tests for TrainerRegistry."""

    def test_register_trainer(self):
        class TestTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="x", dataset_path=path)

        registry = TrainerRegistry()
        registry.register_trainer("test", TestTrainer)
        assert "test" in registry
        assert registry.get_trainer("test") == TestTrainer

    def test_register_multiple_trainers(self):
        class TrainerA(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="a", dataset_path=path)

        class TrainerB(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="b", dataset_path=path)

        registry = TrainerRegistry()
        registry.register_trainer("trainer_a", TrainerA)
        registry.register_trainer("trainer_b", TrainerB)
        assert len(registry) == 2
        assert registry.get_trainer("trainer_a") == TrainerA
        assert registry.get_trainer("trainer_b") == TrainerB

    def test_unregister_trainer(self):
        class TestTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="x", dataset_path=path)

        registry = TrainerRegistry()
        registry.register_trainer("test", TestTrainer)
        assert "test" in registry
        registry.unregister_trainer("test")
        assert "test" not in registry

    def test_unregister_nonexistent_trainer(self):
        registry = TrainerRegistry()
        registry.unregister_trainer("nonexistent")

    def test_get_trainer_returns_class(self):
        class TestTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="x", dataset_path=path)

        registry = TrainerRegistry()
        registry.register_trainer("test", TestTrainer)
        trainer_cls = registry.get_trainer("test")
        assert trainer_cls == TestTrainer
        assert issubclass(trainer_cls, TrainerBase)

    def test_get_nonexistent_trainer_raises(self):
        registry = TrainerRegistry()
        with pytest.raises(KeyError, match="unknown_type"):
            registry.get_trainer("unknown_type")

    def test_list_trainers(self):
        class TrainerA(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="a", dataset_path=path)

        registry = TrainerRegistry()
        registry.register_trainer("type_a", TrainerA)
        registry.register_trainer("type_b", TrainerA)
        trainers = registry.list_trainers()
        assert trainers == {"type_a", "type_b"}

    def test_list_trainers_empty(self):
        registry = TrainerRegistry()
        assert registry.list_trainers() == set()

    def test_contains_dunder(self):
        class TestTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="x", dataset_path=path)

        registry = TrainerRegistry()
        assert "test" not in registry
        registry.register_trainer("test", TestTrainer)
        assert "test" in registry

    def test_len_dunder(self):
        class TestTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="x", dataset_path=path)

        registry = TrainerRegistry()
        assert len(registry) == 0
        registry.register_trainer("t1", TestTrainer)
        assert len(registry) == 1
        registry.register_trainer("t2", TestTrainer)
        assert len(registry) == 2
        registry.unregister_trainer("t1")
        assert len(registry) == 1

    def test_duplicate_registration_overwrites(self):
        class TrainerV1(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="v1", dataset_path=path)

        class TrainerV2(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return path

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="v2", dataset_path=path)

        registry = TrainerRegistry()
        registry.register_trainer("test", TrainerV1)
        registry.register_trainer("test", TrainerV2)
        assert registry.get_trainer("test") == TrainerV2
        assert len(registry) == 1


class TestTrainingJobLifecycle:
    """End-to-end test: register trainer, create job, run through status pipeline."""

    def test_full_lifecycle(self):
        class FullTrainer(TrainerBase):
            def train(self, job: TrainingJob) -> TrainingJob:
                job.status = TrainingStatus.RUNNING
                job.started_at = "2026-07-05T10:00:00Z"
                job.metrics["train_loss"] = 0.3
                return job

            def validate(self, job: TrainingJob) -> dict:
                return {"val_loss": 0.25, "val_accuracy": 0.93}

            def save_checkpoint(self, job: TrainingJob, path: str) -> str:
                return str(Path(path) / "checkpoint.pt")

            def load_checkpoint(self, path: str) -> TrainingJob:
                return TrainingJob(model_name="restored", dataset_path=path)

        registry = TrainerRegistry()
        registry.register_trainer("full", FullTrainer)

        trainer_cls = registry.get_trainer("full")
        trainer = trainer_cls()

        job = TrainingJob(
            model_name="intent-classifier",
            dataset_path="/data/intent_train.jsonl",
            hyperparams={"epochs": 3, "lora_r": 8},
            status=TrainingStatus.QUEUED,
        )
        assert job.status == TrainingStatus.QUEUED

        trainer.train(job)
        assert job.status == TrainingStatus.RUNNING
        assert job.started_at == "2026-07-05T10:00:00Z"
        assert job.metrics.get("train_loss") == 0.3

        val_metrics = trainer.validate(job)
        assert val_metrics["val_loss"] == 0.25
        assert val_metrics["val_accuracy"] == 0.93

        job.status = TrainingStatus.VALIDATING
        job.metrics.update(val_metrics)
        assert job.status == TrainingStatus.VALIDATING
        assert job.metrics == {"train_loss": 0.3, "val_loss": 0.25, "val_accuracy": 0.93}

        job.status = TrainingStatus.COMPLETED
        job.completed_at = "2026-07-05T10:30:00Z"
        assert job.status == TrainingStatus.COMPLETED
        assert job.completed_at == "2026-07-05T10:30:00Z"
