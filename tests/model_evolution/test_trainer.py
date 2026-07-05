"""Tests for proxy/app/model_evolution/trainer.py — TrainerBase, TrainingJob, TrainerRegistry."""


import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.trainer import (
    TrainerBase,
    TrainerRegistry,
    TrainerType,
    TrainingConfig,
    TrainingJob,
)


class TestTrainerType:
    """Tests for TrainerType enum."""

    def test_has_slm(self):
        assert TrainerType.SLM.value == "slm"

    def test_has_llm(self):
        assert TrainerType.LLM.value == "llm"

    def test_has_reranker(self):
        assert TrainerType.RERANKER.value == "reranker"


class TestTrainingConfig:
    """Tests for TrainingConfig dataclass."""

    def test_default_values(self):
        cfg = TrainingConfig(trainer_type=TrainerType.SLM)
        assert cfg.trainer_type == TrainerType.SLM
        assert cfg.env_profile == EnvProfile.DEV
        assert cfg.epochs == 3
        assert cfg.batch_size == 8
        assert cfg.learning_rate == 2e-4
        assert cfg.lora_r == 8
        assert cfg.lora_alpha == 16

    def test_merge_with_preset(self):

        cfg = TrainingConfig.from_profile(TrainerType.SLM, EnvProfile.CI)
        assert cfg.batch_size == 1
        assert cfg.epochs == 1
        assert cfg.lora_r == 2
        assert cfg.lora_alpha == 4
        assert cfg.max_seq_length == 128

    def test_prod_preset_overrides_defaults(self):

        cfg = TrainingConfig.from_profile(TrainerType.SLM, EnvProfile.PROD)
        assert cfg.epochs == 5
        assert cfg.batch_size == 16
        assert cfg.lora_r == 16

    def test_env_profile_stored(self):
        cfg = TrainingConfig(
            trainer_type=TrainerType.SLM,
            env_profile=EnvProfile.PROD,
        )
        assert cfg.env_profile == EnvProfile.PROD


class TestTrainingJob:
    """Tests for TrainingJob dataclass."""

    def test_default_status_pending(self):
        job = TrainingJob(
            job_id="j1",
            trainer_type=TrainerType.SLM,
            config=TrainingConfig(trainer_type=TrainerType.SLM),
        )
        assert job.status == "pending"

    def test_to_dict(self):
        config = TrainingConfig(
            trainer_type=TrainerType.SLM,
            env_profile=EnvProfile.DEV,
            epochs=3,
            batch_size=8,
        )
        job = TrainingJob(
            job_id="j1",
            trainer_type=TrainerType.SLM,
            config=config,
            status="completed",
            mlflow_run_id="run-abc",
            metrics={"accuracy": 0.93, "weighted_f1": 0.91},
            artifact_uri="s3://bucket/models/slm/v1",
            started_at="2026-07-05T10:00:00Z",
            completed_at="2026-07-05T10:30:00Z",
        )
        d = job.to_dict()
        assert d["job_id"] == "j1"
        assert d["trainer_type"] == "slm"
        assert d["status"] == "completed"
        assert d["metrics"] == {"accuracy": 0.93, "weighted_f1": 0.91}
        assert d["artifact_uri"] == "s3://bucket/models/slm/v1"

    def test_to_dict_with_error(self):
        job = TrainingJob(
            job_id="j2",
            trainer_type=TrainerType.LLM,
            config=TrainingConfig(trainer_type=TrainerType.LLM),
            status="failed",
            error_message="GPU OOM",
        )
        d = job.to_dict()
        assert d["status"] == "failed"
        assert d["error_message"] == "GPU OOM"

    def test_to_dict_null_optional_fields(self):
        job = TrainingJob(
            job_id="j3",
            trainer_type=TrainerType.RERANKER,
            config=TrainingConfig(trainer_type=TrainerType.RERANKER),
        )
        d = job.to_dict()
        assert d["mlflow_run_id"] is None
        assert d["artifact_uri"] is None
        assert d["started_at"] is None
        assert d["completed_at"] is None
        assert d["error_message"] is None

    def test_config_included_in_dict(self):
        config = TrainingConfig(
            trainer_type=TrainerType.SLM,
            epochs=5,
            learning_rate=1e-4,
        )
        job = TrainingJob(job_id="j4", trainer_type=TrainerType.SLM, config=config)
        d = job.to_dict()
        assert "config" in d
        assert d["config"]["epochs"] == 5
        assert d["config"]["learning_rate"] == 1e-4


class TestTrainerBase:
    """Tests for TrainerBase ABC."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            TrainerBase()  # type: ignore[abstract]

    def test_concrete_subclass_can_instantiate(self):
        class ConcreteTrainer(TrainerBase):
            def prepare_data(self, *args, **kwargs):
                return None

            def train(self, config):
                return TrainingJob(
                    job_id="test",
                    trainer_type=TrainerType.SLM,
                    config=config,
                )

            def evaluate(self, model, eval_data):
                return {"accuracy": 0.5}

        trainer = ConcreteTrainer()
        assert isinstance(trainer, TrainerBase)
        assert trainer.evaluate(None, None) == {"accuracy": 0.5}

    def test_save_adapter_raises_not_implemented_by_default(self, tmp_path):
        class MinimalTrainer(TrainerBase):
            def prepare_data(self, *args, **kwargs):
                return None

            def train(self, config):
                return TrainingJob(
                    job_id="test",
                    trainer_type=TrainerType.SLM,
                    config=config,
                )

            def evaluate(self, model, eval_data):
                return {}

        trainer = MinimalTrainer()
        with pytest.raises(NotImplementedError):
            trainer.save_adapter(None, str(tmp_path / "adapter"))


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset TrainerRegistry singleton between tests."""
    TrainerRegistry._instance = None
    yield
    TrainerRegistry._instance = None


class TestTrainerRegistry:
    """Tests for TrainerRegistry singleton."""

    def test_singleton_returns_same_instance(self):
        r1 = TrainerRegistry()
        r2 = TrainerRegistry()
        assert r1 is r2

    def test_register_and_get(self):
        registry = TrainerRegistry()

        class DummyTrainer(TrainerBase):
            def prepare_data(self, *args, **kwargs):
                return None

            def train(self, config):
                return TrainingJob(
                    job_id="test",
                    trainer_type=TrainerType.SLM,
                    config=config,
                )

            def evaluate(self, model, eval_data):
                return {}

        registry.register(TrainerType.SLM, DummyTrainer)
        assert registry.get(TrainerType.SLM) is DummyTrainer

    def test_get_unregistered_raises_key_error(self):
        registry = TrainerRegistry()
        with pytest.raises(KeyError):
            registry.get(TrainerType.SLM)

    def test_list_types(self):
        registry = TrainerRegistry()

        class DummySLM(TrainerBase):
            def prepare_data(self, *args, **kwargs):
                return None

            def train(self, config):
                return TrainingJob(
                    job_id="test",
                    trainer_type=TrainerType.SLM,
                    config=config,
                )

            def evaluate(self, model, eval_data):
                return {}

        class DummyLLM(TrainerBase):
            def prepare_data(self, *args, **kwargs):
                return None

            def train(self, config):
                return TrainingJob(
                    job_id="test",
                    trainer_type=TrainerType.LLM,
                    config=config,
                )

            def evaluate(self, model, eval_data):
                return {}

        registry.register(TrainerType.SLM, DummySLM)
        registry.register(TrainerType.LLM, DummyLLM)

        types = registry.list_types()
        assert TrainerType.SLM in types
        assert TrainerType.LLM in types

    def test_get_instance_creates_new_instance(self):
        registry = TrainerRegistry()

        class DummyTrainer(TrainerBase):
            def __init__(self):
                self.name = "dummy"

            def prepare_data(self, *args, **kwargs):
                return None

            def train(self, config):
                return TrainingJob(
                    job_id="test",
                    trainer_type=TrainerType.SLM,
                    config=config,
                )

            def evaluate(self, model, eval_data):
                return {}

        registry.register(TrainerType.SLM, DummyTrainer)
        instance = registry.get_instance(TrainerType.SLM)
        assert isinstance(instance, DummyTrainer)
        assert instance.name == "dummy"
