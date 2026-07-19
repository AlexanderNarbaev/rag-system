"""Tests for proxy/app/model_evolution/reranker_trainer.py — unit tests without GPU deps."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.reranker_trainer import (
    RerankerTrainer,
)
from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig


@pytest.fixture
def trainer():
    return RerankerTrainer()


class TestRerankerDataPrep:
    def test_prepare_data_valid(self, trainer):
        data = [
            ("q1", "c1", 1.0),
            ("q2", "c2", 0.5),
            ("q3", "c3", 0.0),
        ]
        result = trainer.prepare_data(data, eval_split=0.33, seed=42)
        assert "train" in result
        assert "eval" in result
        total = len(result["train"]) + len(result["eval"])
        assert total == 3
        assert len(result["eval"]) >= 1

    def test_prepare_data_filters_empty_strings(self, trainer):
        data = [
            ("", "c1", 1.0),
            ("q2", "", 0.5),
            ("q3", "c3", 0.0),
        ]
        result = trainer.prepare_data(data)
        total = len(result["train"]) + len(result["eval"])
        assert total == 1

    def test_prepare_data_filters_non_strings(self, trainer):
        data = [
            (123, "c1", 1.0),
            ("q2", 456, 0.5),
        ]
        result = trainer.prepare_data(data)
        total = len(result["train"]) + len(result["eval"])
        assert total == 0

    def test_prepare_data_empty(self, trainer):
        result = trainer.prepare_data([])
        assert result == {"train": [], "eval": []}

    def test_prepare_data_small_dataset_single_eval(self, trainer):
        data = [("q1", "c1", 1.0), ("q2", "c2", 0.5)]
        result = trainer.prepare_data(data, eval_split=0.5)
        assert len(result["eval"]) >= 1
        assert len(result["train"]) >= 1


class TestRerankerEvaluation:
    def test_evaluate_empty(self, trainer):
        result = trainer.evaluate(None, [])
        assert result == {"mrr": 0.0, "ndcg_at_10": 0.0, "precision_at_5": 0.0}

    def test_evaluate_single_query(self, trainer):
        data = [
            ("q1", "c1", 1.0),
        ]
        result = trainer.evaluate(None, data)
        assert "mrr" in result
        assert 0.0 <= result["mrr"] <= 1.0

    def test_evaluate_multiple_queries(self, trainer):
        data = [
            ("q1", "c1", 1.0),
            ("q1", "c2", 0.5),
            ("q2", "c3", 1.0),
        ]
        result = trainer.evaluate(None, data)
        assert "mrr" in result
        assert "ndcg_at_10" in result
        assert "precision_at_5" in result

    def test_evaluate_all_relevant(self, trainer):
        data = [("q1", f"c{i}", 3.0) for i in range(5)]
        result = trainer.evaluate(None, data)
        assert result["mrr"] == 1.0

    def test_evaluate_no_relevant(self, trainer):
        data = [("q1", f"c{i}", 0.0) for i in range(5)]
        result = trainer.evaluate(None, data)
        assert result["mrr"] == 0.0
        assert result["precision_at_5"] == 0.0


class TestRerankerMetrics:
    def test_compute_mrr_first_rank(self, trainer):
        labels = [1.0, 0.5, 0.0]
        mrr = trainer._compute_mrr(labels)
        assert mrr == 1.0

    def test_compute_mrr_second_rank(self, trainer):
        labels = [0.5, 1.0, 0.0]
        mrr = trainer._compute_mrr(labels)
        assert mrr == 0.5

    def test_compute_mrr_no_relevant(self, trainer):
        labels = [0.0, 0.0, 0.0]
        mrr = trainer._compute_mrr(labels)
        assert mrr == 0.0

    def test_compute_mrr_score_above_threshold(self, trainer):
        labels = [0.9, 1.1, 0.5]
        mrr = trainer._compute_mrr(labels)
        assert mrr == 0.5

    def test_compute_ndcg_perfect(self, trainer):
        labels = [3.0, 2.0, 1.0]
        ndcg = trainer._compute_ndcg(labels, k=10)
        assert ndcg == 1.0

    def test_compute_ndcg_non_ideal(self, trainer):
        labels = [1.0, 3.0, 2.0]
        ndcg = trainer._compute_ndcg(labels, k=10)
        assert 0.0 < ndcg < 1.0

    def test_compute_ndcg_all_zeros(self, trainer):
        labels = [0.0, 0.0]
        ndcg = trainer._compute_ndcg(labels, k=10)
        assert ndcg == 0.0

    def test_compute_precision_at_5_all_relevant(self, trainer):
        labels = [1.0, 2.0, 3.0, 4.0, 5.0]
        prec = trainer._compute_precision_at_k(labels, k=5)
        assert prec == 1.0

    def test_compute_precision_at_5_none_relevant(self, trainer):
        labels = [0.0, 0.5, 0.8, 0.9, 0.99]
        prec = trainer._compute_precision_at_k(labels, k=5)
        assert prec == 0.0

    def test_compute_precision_at_k_empty(self, trainer):
        prec = trainer._compute_precision_at_k([], k=5)
        assert prec == 0.0

    def test_extract_metrics_from_raw(self, trainer):
        raw = {"eval_mrr": 0.85, "eval_ndcg_at_10": 0.72, "eval_precision_at_5": 0.90, "eval_loss": 0.15}
        metrics = trainer._extract_metrics(raw)
        assert metrics["mrr"] == 0.85
        assert metrics["ndcg_at_10"] == 0.72
        assert metrics["precision_at_5"] == 0.90
        assert metrics["loss"] == 0.15

    def test_extract_metrics_missing_keys(self, trainer):
        raw = {}
        metrics = trainer._extract_metrics(raw)
        assert metrics["mrr"] == 0.0
        assert metrics["loss"] == 0.0


class TestRerankerTargetModules:
    def test_bert_like_model(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, base_model="bert-base-uncased")
        modules = trainer._resolve_target_modules(config)
        assert "query" in modules
        assert "value" in modules

    def test_minilm_model(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, base_model="cross-encoder/MiniLM-L-6")
        modules = trainer._resolve_target_modules(config)
        assert "query" in modules
        assert "value" in modules

    def test_roberta_model(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, base_model="roberta-base")
        modules = trainer._resolve_target_modules(config)
        assert "query" in modules
        assert "value" in modules

    def test_llama_model(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, base_model="llama-3b")
        modules = trainer._resolve_target_modules(config)
        assert "q_proj" in modules
        assert "v_proj" in modules
        assert "k_proj" in modules

    def test_qwen_model(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, base_model="qwen-7b")
        modules = trainer._resolve_target_modules(config)
        assert "q_proj" in modules
        assert "o_proj" in modules

    def test_mistral_model(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, base_model="mistral-7b")
        modules = trainer._resolve_target_modules(config)
        assert "q_proj" in modules

    def test_unknown_model_default(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, base_model="unknown-model")
        modules = trainer._resolve_target_modules(config)
        assert modules == ["query", "value"]

    def test_no_base_model(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, base_model="")
        modules = trainer._resolve_target_modules(config)
        assert modules == ["query", "value"]


class TestRerankerDeviceResolution:
    def test_no_torch_returns_cpu(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, env_profile=EnvProfile.PROD)
        with patch("proxy.app.model_evolution.reranker_trainer._TORCH_AVAILABLE", False):
            assert trainer._resolve_device(config) == "cpu"

    def test_dev_profile(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, env_profile=EnvProfile.DEV)
        with patch("proxy.app.model_evolution.reranker_trainer.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            assert trainer._resolve_device(config) == "cpu"

    def test_ci_profile(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, env_profile=EnvProfile.CI)
        with patch("proxy.app.model_evolution.reranker_trainer.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            assert trainer._resolve_device(config) == "cpu"


class TestRerankerSaveAdapter:
    def test_save_adapter_with_pretrained(self, trainer, tmp_path):
        mock_model = MagicMock()
        mock_model.name_or_path = "test-reranker"
        mock_model.save_pretrained = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.save_pretrained = MagicMock()

        out = tmp_path / "adapter"
        result = trainer.save_adapter(mock_model, str(out), mock_tokenizer)
        assert Path(result).exists()
        mock_model.save_pretrained.assert_called_once()
        mock_tokenizer.save_pretrained.assert_called_once()
        config_file = Path(result) / "trainer_config.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["model_type"] == "reranker_cross_encoder"
        assert data["base_model"] == "test-reranker"

    def test_save_adapter_no_save_pretrained_no_tokenizer(self, trainer, tmp_path):
        mock_model = MagicMock()
        mock_model.name_or_path = "test-fallback"
        mock_model.save_pretrained = MagicMock()

        out = tmp_path / "adapter"
        result = trainer.save_adapter(mock_model, str(out), None)
        assert Path(result).exists()
        mock_model.save_pretrained.assert_called_once()

    def test_save_adapter_base_model_from_name_or_path(self, trainer, tmp_path):
        mock_model = MagicMock()
        mock_model.name_or_path = "direct-name"
        mock_model.save_pretrained = MagicMock()

        out = tmp_path / "adapter"
        result = trainer.save_adapter(mock_model, str(out), None)
        data = json.loads((Path(result) / "trainer_config.json").read_text())
        assert data["base_model"] == "direct-name"


class TestRerankerLoadDataset:
    def test_load_json_dataset_file_exists(self, trainer, tmp_path):
        data = [["q1", "c1", 1.0], ["q2", "c2", 0.5]]
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, output_dir=str(tmp_path))
        (tmp_path / "reranker_train.json").write_text(json.dumps(data))
        result = trainer._load_json_dataset("reranker_train.json", config)
        assert len(result) == 2
        assert result[0][0] == "q1"
        assert result[0][1] == "c1"
        assert result[0][2] == 1.0

    def test_load_json_dataset_not_found_uses_dummy(self, trainer, tmp_path):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, output_dir=str(tmp_path))
        result = trainer._load_json_dataset("reranker_train.json", config)
        assert len(result) == 1
        assert result[0][2] == 1.0

    def test_load_json_dataset_config_none(self, trainer):
        result = trainer._load_json_dataset("nonexistent.json")
        assert len(result) == 1


class TestRerankerTrainFull:
    def test_train_fails_without_sentence_transformers(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, use_lora=False, env_profile=EnvProfile.DEV)
        with patch("proxy.app.model_evolution.reranker_trainer.CROSS_ENCODER_AVAILABLE", False):
            job = trainer.train(config)
            assert job.status == "failed"

    def test_train_with_lora_fails_without_peft(self, trainer):
        config = TrainingConfig(trainer_type=TrainerType.RERANKER, use_lora=True, env_profile=EnvProfile.PROD)
        with (
            patch("proxy.app.model_evolution.reranker_trainer._TRANSFORMERS_AVAILABLE", False),
            patch("proxy.app.model_evolution.reranker_trainer._PEFT_AVAILABLE", False),
            patch("proxy.app.model_evolution.reranker_trainer._TORCH_AVAILABLE", False),
            patch("proxy.app.model_evolution.reranker_trainer.CROSS_ENCODER_AVAILABLE", False),
        ):
            job = trainer.train(config)
            assert job.status == "failed"
