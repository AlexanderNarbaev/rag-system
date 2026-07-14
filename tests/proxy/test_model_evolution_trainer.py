"""Tests for proxy/app/model_evolution/trainer.py — TrainingJob, TrainingConfig, TrainerRegistry."""

from __future__ import annotations

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.trainer import (
  TrainerBase, TrainerRegistry, TrainerType, TrainingConfig, TrainingJob,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_config (**overrides: object) -> TrainingConfig:
  """Create a TrainingConfig with sensible defaults, accepting overrides."""
  kwargs: dict [str, object] = {
      "trainer_type": TrainerType.SLM, "env_profile": EnvProfile.DEV, "base_model": "test-model",
      "output_dir": "/tmp/test-training", "epochs": 3, "batch_size": 8, "learning_rate": 2e-4,
  }
  kwargs.update (overrides)
  return TrainingConfig (**kwargs)  # type: ignore[arg-type]


def _make_job (**overrides: object) -> TrainingJob:
  """Create a TrainingJob with sensible defaults, accepting overrides."""
  config = overrides.pop ("config", _make_config ())
  kwargs: dict [str, object] = {
      "job_id": "test-job-001", "trainer_type": TrainerType.SLM, "config": config,
  }
  kwargs.update (overrides)
  return TrainingJob (**kwargs)  # type: ignore[arg-type]


# ── TrainingConfig ────────────────────────────────────────────────────────────


class TestTrainingConfig:
  """Test TrainingConfig dataclass and factory methods."""
  
  def test_default_config_values (self):
    cfg = TrainingConfig (trainer_type = TrainerType.SLM)
    assert cfg.trainer_type == TrainerType.SLM
    assert cfg.env_profile == EnvProfile.DEV
    assert cfg.epochs == 3
    assert cfg.batch_size == 8
    assert cfg.learning_rate == 2e-4
    assert cfg.use_lora is True
    assert cfg.lora_r == 8
    assert cfg.lora_alpha == 16
    assert cfg.seed == 42
  
  def test_config_custom_values (self):
    cfg = _make_config (epochs = 10, batch_size = 32, learning_rate = 1e-3, seed = 123)
    assert cfg.epochs == 10
    assert cfg.batch_size == 32
    assert cfg.learning_rate == 1e-3
    assert cfg.seed == 123
  
  def test_config_all_trainer_types (self):
    for ttype in TrainerType:
      cfg = TrainingConfig (trainer_type = ttype)
      assert cfg.trainer_type == ttype
  
  def test_config_from_profile_dev (self):
    cfg = TrainingConfig.from_profile (TrainerType.SLM, EnvProfile.DEV)
    assert cfg.trainer_type == TrainerType.SLM
    assert cfg.env_profile == EnvProfile.DEV
    # DEV profile should set small batch_size
    assert cfg.batch_size <= 8
  
  def test_config_from_profile_prod (self):
    cfg = TrainingConfig.from_profile (TrainerType.LLM, EnvProfile.PROD)
    assert cfg.trainer_type == TrainerType.LLM
    assert cfg.env_profile == EnvProfile.PROD
  
  def test_config_from_profile_with_overrides (self):
    cfg = TrainingConfig.from_profile (TrainerType.RERANKER, EnvProfile.CI, epochs = 1, seed = 99)
    assert cfg.trainer_type == TrainerType.RERANKER
    assert cfg.env_profile == EnvProfile.CI
    assert cfg.epochs == 1
    assert cfg.seed == 99
  
  def test_config_from_profile_filters_unknown_keys (self):
    """Unknown override keys should be silently ignored."""
    cfg = TrainingConfig.from_profile (TrainerType.SLM, EnvProfile.DEV, nonexistent_key = "value")
    assert not hasattr (cfg, "nonexistent_key")


# ── TrainingJob ───────────────────────────────────────────────────────────────


class TestTrainingJob:
  """Test TrainingJob dataclass creation, defaults, and serialization."""
  
  def test_job_creation_with_valid_config (self):
    job = _make_job ()
    assert job.job_id == "test-job-001"
    assert job.trainer_type == TrainerType.SLM
    assert job.config is not None
    assert job.config.trainer_type == TrainerType.SLM
  
  def test_job_default_status_is_pending (self):
    job = _make_job ()
    assert job.status == "pending"
  
  def test_job_default_metrics_empty (self):
    job = _make_job ()
    assert job.metrics == {}
  
  def test_job_default_optional_fields_none (self):
    job = _make_job ()
    assert job.mlflow_run_id is None
    assert job.artifact_uri is None
    assert job.started_at is None
    assert job.completed_at is None
    assert job.error_message is None
  
  def test_job_status_transitions (self):
    """Test that job status can be updated like a regular dataclass field."""
    job = _make_job ()
    assert job.status == "pending"
    
    job.status = "running"
    assert job.status == "running"
    
    job.status = "completed"
    assert job.status == "completed"
  
  def test_job_status_failed_with_error (self):
    job = _make_job ()
    job.status = "failed"
    job.error_message = "GPU out of memory"
    assert job.status == "failed"
    assert job.error_message == "GPU out of memory"
  
  def test_job_metrics_tracking (self):
    job = _make_job ()
    job.metrics = {"loss": 0.42, "accuracy": 0.91, "f1": 0.88}
    assert job.metrics ["loss"] == 0.42
    assert job.metrics ["accuracy"] == 0.91
    assert len (job.metrics) == 3
  
  def test_job_to_dict_basic (self):
    job = _make_job ()
    d = job.to_dict ()
    assert d ["job_id"] == "test-job-001"
    assert d ["trainer_type"] == "slm"
    assert d ["status"] == "pending"
    assert d ["metrics"] == {}
    assert d ["mlflow_run_id"] is None
  
  def test_job_to_dict_includes_config (self):
    job = _make_job ()
    d = job.to_dict ()
    assert "config" in d
    cfg = d ["config"]
    assert cfg ["trainer_type"] == "slm"
    assert cfg ["base_model"] == "test-model"
    assert cfg ["epochs"] == 3
    assert cfg ["use_lora"] is True
  
  def test_job_to_dict_reflects_changes (self):
    job = _make_job ()
    job.status = "running"
    job.metrics = {"loss": 0.5}
    job.started_at = "2026-07-12T10:00:00"
    d = job.to_dict ()
    assert d ["status"] == "running"
    assert d ["metrics"] ["loss"] == 0.5
    assert d ["started_at"] == "2026-07-12T10:00:00"
  
  def test_job_to_dict_with_llm_trainer_type (self):
    job = _make_job (trainer_type = TrainerType.LLM, config = _make_config (trainer_type = TrainerType.LLM), )
    d = job.to_dict ()
    assert d ["trainer_type"] == "llm"
    assert d ["config"] ["trainer_type"] == "llm"
  
  def test_job_to_dict_with_reranker_trainer_type (self):
    job = _make_job (trainer_type = TrainerType.RERANKER, config = _make_config (trainer_type = TrainerType.RERANKER), )
    d = job.to_dict ()
    assert d ["trainer_type"] == "reranker"


# ── TrainerType ───────────────────────────────────────────────────────────────


class TestTrainerType:
  """Test TrainerType enum values."""
  
  def test_enum_values (self):
    assert TrainerType.SLM.value == "slm"
    assert TrainerType.LLM.value == "llm"
    assert TrainerType.RERANKER.value == "reranker"
  
  def test_enum_members (self):
    assert set (TrainerType) == {TrainerType.SLM, TrainerType.LLM, TrainerType.RERANKER}


# ── TrainerRegistry (singleton from trainer.py) ──────────────────────────────


class TestTrainerRegistry:
  """Test the singleton TrainerRegistry in trainer.py."""
  
  @pytest.fixture (autouse = True)
  def _reset_registry (self):
    """Reset the singleton before each test."""
    TrainerRegistry._instance = None
    yield
    TrainerRegistry._instance = None
  
  def test_registry_is_singleton (self):
    r1 = TrainerRegistry ()
    r2 = TrainerRegistry ()
    assert r1 is r2
  
  def test_register_and_get (self):
    class DummyTrainer (TrainerBase):
      def prepare_data (self, *args, **kwargs):
        return None
      
      def train (self, config):
        return _make_job (config = config)
      
      def evaluate (self, model, eval_data):
        return {}
    
    registry = TrainerRegistry ()
    registry.register (TrainerType.SLM, DummyTrainer)
    result = registry.get (TrainerType.SLM)
    assert result is DummyTrainer
  
  def test_get_unregistered_raises_key_error (self):
    registry = TrainerRegistry ()
    with pytest.raises (KeyError, match = "No trainer registered"):
      registry.get (TrainerType.LLM)
  
  def test_list_types (self):
    class TrainerA (TrainerBase):
      def prepare_data (self, *a, **kw):
        return None
      
      def train (self, config):
        return _make_job (config = config)
      
      def evaluate (self, m, e):
        return {}
    
    class TrainerB (TrainerBase):
      def prepare_data (self, *a, **kw):
        return None
      
      def train (self, config):
        return _make_job (config = config)
      
      def evaluate (self, m, e):
        return {}
    
    registry = TrainerRegistry ()
    registry.register (TrainerType.SLM, TrainerA)
    registry.register (TrainerType.RERANKER, TrainerB)
    types = registry.list_types ()
    assert TrainerType.SLM in types
    assert TrainerType.RERANKER in types
    assert TrainerType.LLM not in types
  
  def test_get_instance (self):
    class InstantiableTrainer (TrainerBase):
      def __init__ (self):
        self.instantiated = True
      
      def prepare_data (self, *a, **kw):
        return None
      
      def train (self, config):
        return _make_job (config = config)
      
      def evaluate (self, m, e):
        return {}
    
    registry = TrainerRegistry ()
    registry.register (TrainerType.LLM, InstantiableTrainer)
    instance = registry.get_instance (TrainerType.LLM)
    assert isinstance (instance, InstantiableTrainer)
    assert instance.instantiated is True
  
  def test_get_instance_unregistered_raises (self):
    registry = TrainerRegistry ()
    with pytest.raises (KeyError):
      registry.get_instance (TrainerType.RERANKER)
  
  def test_register_overwrites (self):
    class TrainerV1 (TrainerBase):
      def prepare_data (self, *a, **kw):
        return None
      
      def train (self, config):
        return _make_job (config = config)
      
      def evaluate (self, m, e):
        return {}
    
    class TrainerV2 (TrainerBase):
      def prepare_data (self, *a, **kw):
        return None
      
      def train (self, config):
        return _make_job (config = config)
      
      def evaluate (self, m, e):
        return {}
    
    registry = TrainerRegistry ()
    registry.register (TrainerType.SLM, TrainerV1)
    registry.register (TrainerType.SLM, TrainerV2)
    assert registry.get (TrainerType.SLM) is TrainerV2


# ── TrainerBase (ABC contract) ────────────────────────────────────────────────


class TestTrainerBase:
  """Test that TrainerBase cannot be instantiated and requires implementation."""
  
  def test_cannot_instantiate_abstract (self):
    with pytest.raises (TypeError):
      TrainerBase ()
  
  def test_concrete_subclass_works (self):
    class ConcreteTrainer (TrainerBase):
      def prepare_data (self, *args, **kwargs):
        return [1, 2, 3]
      
      def train (self, config):
        job = _make_job (config = config)
        job.status = "completed"
        job.metrics = {"loss": 0.1}
        return job
      
      def evaluate (self, model, eval_data):
        return {"accuracy": 0.95}
    
    trainer = ConcreteTrainer ()
    data = trainer.prepare_data ()
    assert data == [1, 2, 3]
    
    config = _make_config ()
    job = trainer.train (config)
    assert job.status == "completed"
    assert job.metrics ["loss"] == 0.1
    
    metrics = trainer.evaluate (None, None)
    assert metrics ["accuracy"] == 0.95
  
  def test_save_adapter_not_implemented_by_default (self):
    class MinimalTrainer (TrainerBase):
      def prepare_data (self, *a, **kw):
        return None
      
      def train (self, config):
        return _make_job (config = config)
      
      def evaluate (self, m, e):
        return {}
    
    trainer = MinimalTrainer ()
    with pytest.raises (NotImplementedError, match = "save_adapter"):
      trainer.save_adapter (None, "/tmp/model")
