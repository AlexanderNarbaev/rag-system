# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/model_evolution/llm_trainer.py — unit tests without GPU deps."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.exceptions import TrainingError
from proxy.app.model_evolution.llm_trainer import LLMTrainer
from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig


class TestLLMTrainerInit:
    """Tests for LLMTrainer initialization."""

    def test_default_init(self):
        trainer = LLMTrainer()
        assert trainer.config.trainer_type == TrainerType.LLM

    def test_custom_config(self):
        config = TrainingConfig(trainer_type=TrainerType.LLM, base_model="test-model")
        trainer = LLMTrainer(config)
        assert trainer.config.base_model == "test-model"


class TestLLMTrainerDataPrep:
    """Tests for LLMTrainer.prepare_data."""

    def test_valid_messages(self):
        trainer = LLMTrainer()
        data = [
            {"messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]},
            {"messages": [{"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"}]},
        ]
        result = trainer.prepare_data(data)
        assert len(result) == 2

    def test_missing_messages(self):
        trainer = LLMTrainer()
        data = [{"no_messages": True}]
        result = trainer.prepare_data(data)
        assert len(result) == 0

    def test_empty_messages(self):
        trainer = LLMTrainer()
        data = [{"messages": []}]
        result = trainer.prepare_data(data)
        assert len(result) == 0

    def test_mixed_data(self):
        trainer = LLMTrainer()
        data = [
            {"messages": [{"role": "user", "content": "hi"}]},
            {"no_messages": True},
        ]
        result = trainer.prepare_data(data)
        assert len(result) == 1


class TestLLMTrainerCPU:
    """Tests for LLMTrainer CPU/mock training path."""

    def test_is_cpu_profile_dev(self):
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.DEV
        assert trainer._is_cpu_profile() is True

    def test_is_cpu_profile_ci(self):
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.CI
        assert trainer._is_cpu_profile() is True

    def test_is_cpu_profile_prod(self):
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.PROD
        assert trainer._is_cpu_profile() is False

    def test_train_mock(self, tmp_path):
        config = TrainingConfig(
            trainer_type=TrainerType.LLM,
            env_profile=EnvProfile.DEV,
            output_dir=str(tmp_path),
        )
        trainer = LLMTrainer(config)
        data = [
            {"messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]},
        ]
        job = trainer.train(data)
        assert job.status == "completed"
        assert job.metrics is not None
        assert "train_loss" in job.metrics
        assert job.artifact_uri is not None

    def test_train_empty_data_raises(self):
        trainer = LLMTrainer()
        with pytest.raises(TrainingError):
            trainer.train([])

    def test_evaluate_empty(self):
        trainer = LLMTrainer()
        assert trainer.evaluate([]) == {}

    def test_evaluate_cpu_mode(self):
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.DEV
        result = trainer.evaluate([{"messages": []}])
        assert "train_loss" in result

    def test_evaluate_gpu_mode(self):
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.PROD
        result = trainer.evaluate([{"messages": []}])
        assert "eval_loss" in result

    def test_save_adapter_creates_files(self, tmp_path):
        config = TrainingConfig(
            trainer_type=TrainerType.LLM,
            output_dir=str(tmp_path),
            base_model="test-model",
        )
        trainer = LLMTrainer(config)
        result = trainer.save_adapter(tmp_path / "adapter")
        assert Path(result).exists()
        config_file = Path(result) / "adapter_config.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["peft_type"] == "LORA"
        assert data["base_model_name_or_path"] == "test-model"

    def test_push_to_registry_with_job(self):
        trainer = LLMTrainer()
        job = MagicMock()
        job.artifact_uri = "/path/to/adapter"
        job.job_id = "test-job"
        assert trainer.push_to_registry(job) == "/path/to/adapter"

    def test_push_to_registry_none_raises(self):
        trainer = LLMTrainer()
        with pytest.raises(ValueError):
            trainer.push_to_registry(None)

    def test_make_job_id(self):
        jid = LLMTrainer._make_job_id()
        assert jid.startswith("llm-")
        assert len(jid) > 4

    def test_cuda_available_no_torch(self):
        trainer = LLMTrainer()
        with patch.dict("sys.modules", {"torch": None}):
            assert trainer._cuda_available() is False

    def test_find_lora_target_modules_empty(self):
        mock_model = MagicMock()
        mock_model.named_modules.return_value = []
        modules = LLMTrainer._find_lora_target_modules(mock_model)
        assert modules == ["q_proj", "v_proj"]

    def test_find_lora_target_modules_with_layers(self):
        mock_model = MagicMock()
        mock_model.named_modules.return_value = [
            ("layer.0.q_proj", MagicMock()),
            ("layer.0.v_proj", MagicMock()),
            ("layer.0.k_proj", MagicMock()),
        ]
        modules = LLMTrainer._find_lora_target_modules(mock_model)
        assert "q_proj" in modules
        assert "v_proj" in modules
        assert "k_proj" in modules
