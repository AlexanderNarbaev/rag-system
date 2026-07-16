# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/model_evolution/slm_trainer.py — unit tests without GPU deps."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.slm_trainer import (
    ID_TO_INTENT,
    INTENT_LABELS,
    INTENT_TO_ID,
    SLMTrainer,
)


class TestIntentMappings:
    """Tests for intent label constants."""

    def test_intent_labels_count(self):
        assert len(INTENT_LABELS) == 7

    def test_intent_to_id_roundtrip(self):
        for label in INTENT_LABELS:
            idx = INTENT_TO_ID[label]
            assert ID_TO_INTENT[idx] == label

    def test_all_labels_present(self):
        expected = {"greeting", "simple_fact", "factual", "procedural", "comparison", "summarize", "complex"}
        assert set(INTENT_LABELS) == expected


class TestSLMTrainerUnit:
    """Tests for SLMTrainer methods that don't require GPU."""

    @pytest.fixture
    def trainer(self):
        return SLMTrainer()

    def test_prepare_data_valid(self, trainer):
        dataset = [
            {"query": "hello", "intent_label": "greeting"},
            {"query": "what is RAG", "intent_label": "factual"},
            {"query": "compare A and B", "intent_label": "comparison"},
        ]
        result = trainer.prepare_data(dataset, eval_split=0.3)
        assert "train" in result
        assert "eval" in result
        total = len(result["train"]) + len(result["eval"])
        assert total == 3

    def test_prepare_data_filters_invalid(self, trainer):
        dataset = [
            {"query": "hello", "intent_label": "greeting"},
            {"query": "bad", "intent_label": "invalid_label"},
        ]
        result = trainer.prepare_data(dataset)
        total = len(result["train"]) + len(result["eval"])
        assert total == 1

    def test_prepare_data_empty(self, trainer):
        result = trainer.prepare_data([])
        assert result == {"train": [], "eval": []}

    def test_prepare_data_all_invalid(self, trainer):
        dataset = [{"query": "x", "intent_label": "nonexistent"}]
        result = trainer.prepare_data(dataset)
        assert result == {"train": [], "eval": []}

    def test_evaluate_empty(self, trainer):
        result = trainer.evaluate(None, [])
        assert result == {"accuracy": 0.0, "weighted_f1": 0.0}

    def test_evaluate_correct_predictions(self, trainer):
        data = [
            {"query": "hi", "intent_label": "greeting", "predicted_label": "greeting"},
            {"query": "what", "intent_label": "factual", "predicted_label": "factual"},
        ]
        result = trainer.evaluate(None, data)
        assert result["accuracy"] == 1.0

    def test_evaluate_wrong_predictions(self, trainer):
        data = [
            {"query": "hi", "intent_label": "greeting", "predicted_label": "complex"},
        ]
        result = trainer.evaluate(None, data)
        assert result["accuracy"] == 0.0

    def test_evaluate_mixed(self, trainer):
        data = [
            {"query": "hi", "intent_label": "greeting", "predicted_label": "greeting"},
            {"query": "x", "intent_label": "factual", "predicted_label": "complex"},
        ]
        result = trainer.evaluate(None, data)
        assert 0.0 < result["accuracy"] < 1.0

    def test_fallback_predict_greeting(self, trainer):
        assert trainer._fallback_predict("hello there") == "greeting"
        assert trainer._fallback_predict("hi!") == "greeting"
        assert trainer._fallback_predict("hey, thanks") == "greeting"

    def test_fallback_predict_comparison(self, trainer):
        assert trainer._fallback_predict("compare A vs B") == "comparison"

    def test_fallback_predict_summarize(self, trainer):
        assert trainer._fallback_predict("tldr of tne document") == "summarize"

    def test_fallback_predict_procedural(self, trainer):
        assert trainer._fallback_predict("how to set up CI/CD") == "procedural"

    def test_fallback_predict_factual(self, trainer):
        assert trainer._fallback_predict("what is RAG") == "factual"

    def test_fallback_predict_complex(self, trainer):
        assert trainer._fallback_predict("tell me about X? and also Y?") == "complex"

    def test_fallback_predict_simple_fact(self, trainer):
        assert trainer._fallback_predict("weather") == "simple_fact"

    def test_resolve_device_cpu(self, trainer):
        from proxy.app.model_evolution.env_profile import EnvProfile
        from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig

        config = TrainingConfig(trainer_type=TrainerType.SLM, env_profile=EnvProfile.DEV)
        assert trainer._resolve_device(config) == "cpu"

    def test_resolve_device_no_torch(self, trainer):
        from proxy.app.model_evolution.env_profile import EnvProfile
        from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig

        config = TrainingConfig(trainer_type=TrainerType.SLM, env_profile=EnvProfile.DEV)
        with patch("proxy.app.model_evolution.slm_trainer._TORCH_AVAILABLE", False):
            assert trainer._resolve_device(config) == "cpu"

    def test_resolve_target_modules_bert(self, trainer):
        from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig

        config = TrainingConfig(trainer_type=TrainerType.SLM, base_model="bert-base-uncased")
        modules = trainer._resolve_target_modules(config)
        assert "query" in modules
        assert "value" in modules

    def test_resolve_target_modules_roberta(self, trainer):
        from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig

        config = TrainingConfig(trainer_type=TrainerType.SLM, base_model="roberta-base")
        modules = trainer._resolve_target_modules(config)
        assert "query" in modules

    def test_resolve_target_modules_llama(self, trainer):
        from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig

        config = TrainingConfig(trainer_type=TrainerType.SLM, base_model="llama-3b")
        modules = trainer._resolve_target_modules(config)
        assert "q_proj" in modules

    def test_resolve_target_modules_default(self, trainer):
        from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig

        config = TrainingConfig(trainer_type=TrainerType.SLM, base_model="unknown-model")
        modules = trainer._resolve_target_modules(config)
        assert "q_proj" in modules

    def test_extract_metrics(self, trainer):
        raw = {"eval_accuracy": 0.85, "eval_weighted_f1": 0.82, "eval_loss": 0.35}
        metrics = trainer._extract_metrics(raw)
        assert metrics["accuracy"] == 0.85
        assert metrics["weighted_f1"] == 0.82
        assert metrics["loss"] == 0.35

    def test_extract_metrics_missing_keys(self, trainer):
        raw = {}
        metrics = trainer._extract_metrics(raw)
        assert metrics["accuracy"] == 0.0

    def test_save_adapter(self, trainer, tmp_path):
        mock_model = MagicMock()
        mock_model.name_or_path = "test-model"
        mock_model.save_pretrained = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.save_pretrained = MagicMock()

        out = tmp_path / "adapter"
        result = trainer.save_adapter(mock_model, str(out), mock_tokenizer)
        assert Path(result).exists()
        mock_model.save_pretrained.assert_called_once()
        mock_tokenizer.save_pretrained.assert_called_once()
        # Config file written
        config_file = Path(result) / "trainer_config.json"
        assert config_file.exists()
        config_data = json.loads(config_file.read_text())
        assert config_data["model_type"] == "slm_intent_classifier"
        assert config_data["num_labels"] == 7
