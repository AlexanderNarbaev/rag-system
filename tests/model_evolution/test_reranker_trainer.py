"""Tests for proxy/app/model_evolution/reranker_trainer.py — RerankerTrainer + LoRA FT."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.trainer import (
    TrainerBase,
    TrainerType,
    TrainingConfig,
    TrainingJob,
)


@pytest.fixture
def cpu_config():
    return TrainingConfig.from_profile(TrainerType.RERANKER, EnvProfile.DEV)


@pytest.fixture
def gpu_config():
    return TrainingConfig.from_profile(TrainerType.RERANKER, EnvProfile.PROD)


@pytest.fixture
def ci_config():
    return TrainingConfig.from_profile(TrainerType.RERANKER, EnvProfile.CI)


@pytest.fixture
def sample_pairs():
    return [
        ("how to install docker", "Docker installation guide for Ubuntu 22.04", 1.0),
        ("how to install docker", "Docker compose reference", 0.8),
        ("how to install docker", "Kubernetes pod configuration", 0.0),
        ("python async tutorial", "AsyncIO event loop basics in Python", 1.0),
        ("python async tutorial", "Threading vs multiprocessing in Python", 0.3),
        ("python async tutorial", "JavaScript promise chain example", 0.0),
        ("git rebase workflow", "Interactive rebase squash and reword", 1.0),
        ("git rebase workflow", "Git merge vs rebase comparison", 0.7),
        ("git rebase workflow", "SVN to Git migration guide", 0.1),
    ]


class TestRerankerTrainerInit:
    def test_is_subclass_of_trainer_base(self):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        assert issubclass(RerankerTrainer, TrainerBase)

    def test_can_instantiate(self):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        assert isinstance(trainer, RerankerTrainer)
        assert isinstance(trainer, TrainerBase)


class TestRerankerTrainerPrepareData:
    def test_returns_dict_with_required_keys(self, sample_pairs):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        result = trainer.prepare_data(sample_pairs)
        assert isinstance(result, dict)
        assert "train" in result
        assert "eval" in result

    def test_train_eval_split_respects_ratio(self, sample_pairs):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        result = trainer.prepare_data(sample_pairs, eval_split=0.3)
        total = len(result["train"]) + len(result["eval"])
        assert total == len(sample_pairs)

    def test_each_split_item_is_tuple_of_three(self, sample_pairs):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        result = trainer.prepare_data(sample_pairs)
        for item in result["train"]:
            assert isinstance(item, tuple)
            assert len(item) == 3
            assert isinstance(item[0], str)
            assert isinstance(item[1], str)
            assert isinstance(item[2], float)

    def test_empty_dataset_returns_empty(self):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        result = trainer.prepare_data([])
        assert result["train"] == []
        assert result["eval"] == []

    def test_filter_zero_length_strings(self):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        dataset = [
            ("valid query", "valid chunk", 1.0),
            ("", "valid chunk", 1.0),
            ("valid query", "", 0.0),
            ("", "", 0.0),
        ]
        trainer = RerankerTrainer()
        result = trainer.prepare_data(dataset)
        all_items = result["train"] + result["eval"]
        assert len(all_items) <= 2

    def test_reproducible_with_seed(self, sample_pairs):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        result1 = trainer.prepare_data(sample_pairs, seed=42)
        result2 = trainer.prepare_data(sample_pairs, seed=42)
        assert result1["train"] == result2["train"]
        assert result1["eval"] == result2["eval"]


class TestRerankerTrainerTrain:
    @pytest.fixture
    def mock_deps_lora(self):
        with (
            patch("proxy.app.model_evolution.reranker_trainer._TRANSFORMERS_AVAILABLE", True),
            patch("proxy.app.model_evolution.reranker_trainer._PEFT_AVAILABLE", True),
            patch("proxy.app.model_evolution.reranker_trainer._TORCH_AVAILABLE", True),
            patch("proxy.app.model_evolution.reranker_trainer.AutoTokenizer") as mock_tok,
            patch("proxy.app.model_evolution.reranker_trainer.AutoModelForSequenceClassification") as mock_model,
            patch("proxy.app.model_evolution.reranker_trainer.Trainer") as mock_trainer_cls,
            patch("proxy.app.model_evolution.reranker_trainer.TrainingArguments"),
            patch("proxy.app.model_evolution.reranker_trainer.LoraConfig"),
            patch("proxy.app.model_evolution.reranker_trainer.TaskType"),
            patch("proxy.app.model_evolution.reranker_trainer.get_peft_model"),
            patch("proxy.app.model_evolution.reranker_trainer.torch") as mock_torch,
        ):
            mock_tok.from_pretrained.return_value.pad_token = "[PAD]"
            mock_tok.from_pretrained.return_value.pad_token_id = 0

            mock_model.from_pretrained.return_value.config.pad_token_id = 0
            mock_model.from_pretrained.return_value.config.hidden_size = 384

            mock_trainer_instance = MagicMock()
            mock_trainer_cls.return_value = mock_trainer_instance
            mock_trainer_instance.train.return_value = None
            mock_trainer_instance.evaluate.return_value = {
                "eval_loss": 0.15,
                "eval_mrr": 0.85,
                "eval_ndcg_at_10": 0.78,
                "eval_precision_at_5": 0.82,
            }

            mock_torch.cuda.is_available.return_value = True

            yield

    @pytest.fixture
    def mock_deps_crossencoder(self):
        with (
            patch("proxy.app.model_evolution.reranker_trainer.CrossEncoder") as mock_ce,
            patch("proxy.app.model_evolution.reranker_trainer.CROSS_ENCODER_AVAILABLE", True),
            patch("proxy.app.model_evolution.reranker_trainer._TORCH_AVAILABLE", True),
            patch("proxy.app.model_evolution.reranker_trainer.torch") as mock_torch,
        ):
            mock_ce_instance = MagicMock()
            mock_ce.return_value = mock_ce_instance
            mock_torch.cuda.is_available.return_value = False
            yield mock_ce

    def test_train_returns_training_job_lora(self, gpu_config, mock_deps_lora):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        job = trainer.train(gpu_config)
        assert isinstance(job, TrainingJob)
        assert job.trainer_type == TrainerType.RERANKER
        assert job.status == "completed"

    def test_train_lora_job_has_metrics(self, gpu_config, mock_deps_lora):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        job = trainer.train(gpu_config)
        assert "mrr" in job.metrics
        assert "ndcg_at_10" in job.metrics
        assert "precision_at_5" in job.metrics

    def test_train_lora_job_has_artifact_uri(self, gpu_config, mock_deps_lora):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        job = trainer.train(gpu_config)
        assert job.artifact_uri is not None
        assert "adapter" in str(job.artifact_uri)

    def test_train_cpu_full_finetune(self, cpu_config, mock_deps_crossencoder):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        cpu_config.use_lora = False
        job = trainer.train(cpu_config)
        assert job.status == "completed"
        mock_deps_crossencoder.return_value.fit.assert_called_once()
        mock_deps_crossencoder.return_value.save.assert_called_once()

    def test_train_cpu_mode_uses_crossencoder(self, cpu_config, mock_deps_crossencoder):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        cpu_config.use_lora = False
        job = trainer.train(cpu_config)
        assert job.trainer_type == TrainerType.RERANKER
        assert job.artifact_uri is not None

    def test_train_ci_profile_minimal(self, ci_config):
        assert ci_config.epochs == 1
        assert ci_config.batch_size == 1

    def test_train_uses_lora_config(self, gpu_config):
        assert gpu_config.use_lora is True
        assert gpu_config.lora_r > 0
        assert gpu_config.lora_alpha > 0

    def test_train_error_returns_failed_job(self, cpu_config):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        cpu_config.base_model = ""
        cpu_config.use_lora = False
        job = trainer.train(cpu_config)
        assert job.status == "failed"
        assert job.error_message is not None

    def test_train_no_pairs_warning(self, caplog):
        import logging

        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer
        caplog.set_level(logging.WARNING)
        trainer = RerankerTrainer()
        cfg = TrainingConfig.from_profile(TrainerType.RERANKER, EnvProfile.CI)
        cfg.base_model = ""
        cfg.use_lora = False
        with patch("proxy.app.model_evolution.reranker_trainer.CROSS_ENCODER_AVAILABLE", False):
            job = trainer.train(cfg)
        assert job.status == "failed"
        assert "sentence-transformers required" in job.error_message


class TestRerankerTrainerEvaluate:
    def test_evaluate_returns_float_dict(self, sample_pairs):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        result = trainer.evaluate(None, sample_pairs)
        assert isinstance(result, dict)
        assert "mrr" in result
        assert "ndcg_at_10" in result
        assert "precision_at_5" in result
        for v in result.values():
            assert isinstance(v, float)

    def test_evaluate_empty_data_returns_zeros(self):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        result = trainer.evaluate(None, [])
        assert result == {"mrr": 0.0, "ndcg_at_10": 0.0, "precision_at_5": 0.0}

    def test_evaluate_perfect_ordering(self):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        perfect = [
            ("q1", "best", 1.0),
            ("q1", "good", 1.0),
            ("q1", "relevant", 1.0),
            ("q1", "ok", 1.0),
            ("q1", "surprise", 0.5),
        ]
        result = trainer.evaluate(None, perfect)
        assert result["mrr"] == 1.0
        assert result["precision_at_5"] == 0.8

    def test_evaluate_single_query_single_chunk(self):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        result = trainer.evaluate(None, [("q1", "c1", 1.0)])
        assert result["mrr"] == 1.0
        assert result["precision_at_5"] == 1.0

    def test_evaluate_queries_grouped_correctly(self):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        data = [
            ("q1", "c1", 0.0),
            ("q1", "c2", 1.0),
            ("q2", "c3", 1.0),
            ("q2", "c4", 0.0),
        ]
        result = trainer.evaluate(None, data)
        assert result["mrr"] == 1.0
        assert result["ndcg_at_10"] == 1.0


class TestRerankerTrainerSaveAdapter:
    def test_save_adapter_peft_model(self, tmp_path):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        output_dir = tmp_path / "adapter"
        mock_model = MagicMock()
        mock_model.save_pretrained = MagicMock()

        path = trainer.save_adapter(mock_model, str(output_dir))
        assert Path(path).exists()
        mock_model.save_pretrained.assert_called_once_with(str(output_dir))

    def test_save_adapter_creates_directory(self, tmp_path):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        output_dir = tmp_path / "nested" / "adapter"
        mock_model = MagicMock()
        mock_model.save_pretrained = MagicMock()

        path = trainer.save_adapter(mock_model, str(output_dir))
        assert Path(path).exists()
        mock_model.save_pretrained.assert_called_once()

    def test_save_adapter_with_tokenizer(self, tmp_path):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        output_dir = tmp_path / "adapter_tok"
        mock_model = MagicMock()
        mock_model.save_pretrained = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.save_pretrained = MagicMock()

        path = trainer.save_adapter(mock_model, str(output_dir), mock_tokenizer)
        assert Path(path).exists()
        mock_tokenizer.save_pretrained.assert_called_once_with(str(output_dir))

    def test_save_adapter_torch_fallback(self, tmp_path):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        output_dir = tmp_path / "torch_fallback"

        import torch

        class SimpleModule(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.linear = torch.nn.Linear(10, 1)

        model = SimpleModule()
        path = trainer.save_adapter(model, str(output_dir))
        assert Path(path).exists()
        assert (Path(path) / "adapter_model.bin").exists()

    def test_save_adapter_config(self, tmp_path):
        from proxy.app.model_evolution.reranker_trainer import RerankerTrainer

        trainer = RerankerTrainer()
        output_dir = tmp_path / "adapter_cfg"
        mock_model = MagicMock()
        mock_model.save_pretrained = MagicMock()
        mock_model.name_or_path = "cross-encoder/ms-marco-MiniLM-L-6-v2"

        trainer.save_adapter(mock_model, str(output_dir))
        assert (output_dir / "trainer_config.json").exists()


class TestRerankerConfigs:
    def test_cpu_profile_has_correct_lora_r(self, cpu_config):
        from proxy.app.model_evolution.reranker_trainer import RERANKER_LORA_ALPHA, RERANKER_LORA_R

        assert RERANKER_LORA_R > 0
        assert RERANKER_LORA_ALPHA > 0

    def test_cpu_config_no_lora_format(self, cpu_config):
        cpu_config.use_lora = False
        assert cpu_config.use_lora is False

    def test_prod_profile_has_epochs(self, gpu_config):
        assert gpu_config.epochs >= 3

    def test_relevance_score_in_range(self, sample_pairs):
        for _, _, score in sample_pairs:
            assert 0.0 <= score <= 1.0
