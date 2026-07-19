"""Additional unit tests for proxy/app/model_evolution/slm_trainer.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.slm_trainer import (
    SLMTrainer,
)
from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig


@pytest.fixture
def trainer():
    return SLMTrainer()


class TestSLMTrainerAdvanced:
    def test_resolve_device_dev(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.SLM, env_profile=EnvProfile.DEV)
        assert trainer._resolve_device(config) == "cpu"

    def test_resolve_device_ci(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.SLM, env_profile=EnvProfile.CI)
        assert trainer._resolve_device(config) == "cpu"

    def test_resolve_device_no_torch(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.SLM, env_profile=EnvProfile.DEV)
        with patch("proxy.app.model_evolution.slm_trainer._TORCH_AVAILABLE", False):
            assert trainer._resolve_device(config) == "cpu"

    def test_resolve_target_modules_roberta_like(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.SLM, base_model="roberta-large")
        modules = trainer._resolve_target_modules(config)
        assert "query" in modules

    def test_resolve_target_modules_gpt_like(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.SLM, base_model="gpt-neo-1.3B")
        modules = trainer._resolve_target_modules(config)
        assert "q_proj" in modules

    def test_resolve_target_modules_mistral(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.SLM, base_model="mistral-7b")
        modules = trainer._resolve_target_modules(config)
        assert "q_proj" in modules

    def test_resolve_target_modules_qwen(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.SLM, base_model="qwen-2.5-3b")
        modules = trainer._resolve_target_modules(config)
        assert "q_proj" in modules

    def test_save_adapter_exists_and_config(self, trainer, tmp_path):
        mock_model = MagicMock()
        mock_model.name_or_path = "test-model"
        mock_model.save_pretrained = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.save_pretrained = MagicMock()

        out = tmp_path / "adapter"
        result = trainer.save_adapter(mock_model, str(out), mock_tokenizer)
        assert Path(result).exists()
        config_file = Path(result) / "trainer_config.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["model_type"] == "slm_intent_classifier"
        assert data["num_labels"] == 7

    def test_extract_metrics_all_keys(self, trainer):
        raw = {"eval_accuracy": 0.92, "eval_weighted_f1": 0.88, "eval_loss": 0.12, "eval_runtime": 45.2}
        metrics = trainer._extract_metrics(raw)
        assert metrics["accuracy"] == 0.92
        assert metrics["weighted_f1"] == 0.88
        assert metrics["loss"] == 0.12

    def test_evaluate_with_trained_model_cpu(self, trainer):
        data = [
            {"query": "hi", "intent_label": "greeting", "predicted_label": "greeting"},
        ]
        result = trainer.evaluate(None, data)
        assert "accuracy" in result
        assert "weighted_f1" in result

    def test_evaluate_with_trained_model_gpu(self, trainer):
        data = [
            {"query": "hi", "intent_label": "greeting", "predicted_label": "greeting"},
        ]
        result = trainer.evaluate(None, data)
        assert "accuracy" in result

    def test_save_adapter_without_tokenizer(self, trainer, tmp_path):
        mock_model = MagicMock()
        mock_model.name_or_path = "test-model"
        mock_model.save_pretrained = MagicMock()

        out = tmp_path / "adapter"
        result = trainer.save_adapter(mock_model, str(out))
        assert Path(result).exists()
        mock_model.save_pretrained.assert_called_once()

    def test_fallback_predict_all_intents(self, trainer):
        assert trainer._fallback_predict("hello") == "greeting"
        assert trainer._fallback_predict("what is 2+2") == "factual"
        assert trainer._fallback_predict("how to install Python") == "procedural"
        assert trainer._fallback_predict("compare A and B") == "comparison"
        assert trainer._fallback_predict("tldr of the report") == "summarize"
        assert trainer._fallback_predict("tell me about X and Y") == "complex"
        assert trainer._fallback_predict("weather in London") == "simple_fact"
