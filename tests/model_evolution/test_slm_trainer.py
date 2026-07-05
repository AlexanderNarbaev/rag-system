"""Tests for proxy/app/model_evolution/slm_trainer.py — SLMTrainer LoRA fine-tuning."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.slm_trainer import SLMTrainer
from proxy.app.model_evolution.trainer import (
    TrainerBase,
    TrainerType,
    TrainingConfig,
    TrainingJob,
)

VALID_INTENTS = [
    "greeting", "simple_fact", "factual", "procedural",
    "comparison", "summarize", "complex",
]


@pytest.fixture
def cpu_config():
    return TrainingConfig.from_profile(TrainerType.SLM, EnvProfile.DEV)


@pytest.fixture
def gpu_config():
    return TrainingConfig.from_profile(TrainerType.SLM, EnvProfile.PROD)


@pytest.fixture
def ci_config():
    return TrainingConfig.from_profile(TrainerType.SLM, EnvProfile.CI)


@pytest.fixture
def sample_dataset():
    return [
        {"query": "hello there", "intent_label": "greeting"},
        {"query": "how to install nginx", "intent_label": "procedural"},
        {"query": "compare redis and memcached", "intent_label": "comparison"},
        {"query": "summarize the document", "intent_label": "summarize"},
        {"query": "what is docker", "intent_label": "simple_fact"},
        {"query": "explain quantum computing", "intent_label": "factual"},
        {"query": "what is X and how to use it with Y", "intent_label": "complex"},
    ]


class TestSLMTrainerInit:
    """Tests for SLMTrainer instantiation."""

    def test_is_subclass_of_trainer_base(self):
        assert issubclass(SLMTrainer, TrainerBase)

    def test_can_instantiate(self):
        trainer = SLMTrainer()
        assert isinstance(trainer, SLMTrainer)
        assert isinstance(trainer, TrainerBase)


class TestSLMTrainerPrepareData:
    """Tests for SLMTrainer.prepare_data()."""

    def test_returns_dict_with_required_keys(self, sample_dataset):
        trainer = SLMTrainer()
        result = trainer.prepare_data(sample_dataset)
        assert isinstance(result, dict)
        assert "train" in result
        assert "eval" in result

    def test_train_eval_split_respects_ratio(self, sample_dataset):
        trainer = SLMTrainer()
        result = trainer.prepare_data(sample_dataset, eval_split=0.3)
        total = len(result["train"]) + len(result["eval"])
        assert total <= len(sample_dataset)

    def test_filters_out_unknown_intents(self):
        dataset = [
            {"query": "hello", "intent_label": "greeting"},
            {"query": "test", "intent_label": "unknown"},
        ]
        trainer = SLMTrainer()
        result = trainer.prepare_data(dataset)
        all_samples = result["train"] + result["eval"]
        assert len(all_samples) == 1
        assert all_samples[0]["intent_label"] == "greeting"

    def test_empty_dataset_returns_empty(self):
        trainer = SLMTrainer()
        result = trainer.prepare_data([])
        assert result["train"] == []
        assert result["eval"] == []

    def test_uses_slm_router_intents(self, sample_dataset):
        trainer = SLMTrainer()
        result = trainer.prepare_data(sample_dataset)
        all_data = result["train"] + result["eval"]
        for item in all_data:
            assert item["intent_label"] in VALID_INTENTS


class TestSLMTrainerTrain:
    """Tests for SLMTrainer.train()."""

    @pytest.fixture
    def mock_deps(self):
        """Mock peft/transformers to avoid needing actual models."""
        with (
            patch("proxy.app.model_evolution.slm_trainer._TRANSFORMERS_AVAILABLE", True),
            patch("proxy.app.model_evolution.slm_trainer._PEFT_AVAILABLE", True),
            patch("proxy.app.model_evolution.slm_trainer._TORCH_AVAILABLE", True),
            patch("proxy.app.model_evolution.slm_trainer.AutoTokenizer") as mock_tok,
            patch("proxy.app.model_evolution.slm_trainer.AutoModelForSequenceClassification") as mock_model,
            patch("proxy.app.model_evolution.slm_trainer.Trainer") as mock_trainer,
            patch("proxy.app.model_evolution.slm_trainer.TrainingArguments"),
            patch("proxy.app.model_evolution.slm_trainer.LoraConfig"),
            patch("proxy.app.model_evolution.slm_trainer.TaskType"),
            patch("proxy.app.model_evolution.slm_trainer.get_peft_model"),
            patch("proxy.app.model_evolution.slm_trainer.torch") as mock_torch,
        ):
            mock_tok.from_pretrained.return_value.pad_token = None
            mock_tok.from_pretrained.return_value.eos_token = "[EOS]"
            mock_tok.from_pretrained.return_value.pad_token_id = 0

            mock_model.from_pretrained.return_value.config.pad_token_id = 0

            mock_trainer_instance = MagicMock()
            mock_trainer.return_value = mock_trainer_instance
            mock_trainer_instance.train.return_value = None
            mock_trainer_instance.evaluate.return_value = {
                "eval_accuracy": 0.93,
                "eval_weighted_f1": 0.91,
                "eval_loss": 0.25,
            }

            mock_torch.cuda.is_available.return_value = False

            yield

    def test_train_returns_training_job(self, cpu_config, mock_deps):
        trainer = SLMTrainer()
        job = trainer.train(cpu_config)
        assert isinstance(job, TrainingJob)
        assert job.trainer_type == TrainerType.SLM
        assert job.status == "completed"

    def test_train_job_has_metrics(self, cpu_config, mock_deps):
        trainer = SLMTrainer()
        job = trainer.train(cpu_config)
        assert "accuracy" in job.metrics
        assert "weighted_f1" in job.metrics
        assert "loss" in job.metrics
        assert 0.0 <= job.metrics["accuracy"] <= 1.0

    def test_train_job_has_artifact_uri(self, cpu_config, mock_deps):
        trainer = SLMTrainer()
        job = trainer.train(cpu_config)
        assert job.artifact_uri is not None
        assert "adapter" in str(job.artifact_uri)

    def test_train_cpu_profile_smaller_batch(self, cpu_config):
        assert cpu_config.batch_size <= 4

    def test_train_ci_profile_minimal(self, ci_config):
        assert ci_config.epochs == 1
        assert ci_config.batch_size == 1

    def test_train_with_gpu_uses_mixed_precision(self, gpu_config):
        assert gpu_config.use_qlora is True

    def test_train_uses_lora_config(self, cpu_config):
        assert cpu_config.use_lora is True
        assert cpu_config.lora_r > 0
        assert cpu_config.lora_alpha > 0

    def test_train_sets_seed(self, cpu_config):
        assert cpu_config.seed == 42

    def test_train_error_returns_failed_job(self, cpu_config):
        trainer = SLMTrainer()
        cpu_config.base_model = "nonexistent/model"
        job = trainer.train(cpu_config)
        assert job.status == "failed"
        assert job.error_message is not None


class TestSLMTrainerEvaluate:
    """Tests for SLMTrainer.evaluate()."""

    def test_evaluate_returns_float_dict(self, sample_dataset):
        trainer = SLMTrainer()
        data = trainer.prepare_data(sample_dataset)
        eval_data = data["eval"] if data["eval"] else data["train"]
        result = trainer.evaluate(None, eval_data)
        assert isinstance(result, dict)
        assert "accuracy" in result
        assert "weighted_f1" in result
        for v in result.values():
            assert isinstance(v, float)

    def test_evaluate_with_empty_data(self):
        trainer = SLMTrainer()
        result = trainer.evaluate(None, [])
        assert result == {"accuracy": 0.0, "weighted_f1": 0.0}


class TestSLMTrainerSaveAdapter:
    """Tests for SLMTrainer.save_adapter()."""

    def test_save_adapter_creates_directory(self, tmp_path):
        trainer = SLMTrainer()
        output_dir = tmp_path / "slm_adapter"
        mock_model = MagicMock()
        mock_model.save_pretrained = MagicMock()
        mock_tokenizer = MagicMock()
        mock_tokenizer.save_pretrained = MagicMock()

        path = trainer.save_adapter(mock_model, str(output_dir), mock_tokenizer)
        assert Path(path).exists()
        mock_model.save_pretrained.assert_called_once()

    def test_save_adapter_without_tokenizer(self, tmp_path):
        trainer = SLMTrainer()
        output_dir = tmp_path / "slm_adapter_no_tok"
        mock_model = MagicMock()
        mock_model.save_pretrained = MagicMock()

        path = trainer.save_adapter(mock_model, str(output_dir))
        assert Path(path).exists()

    def test_save_adapter_with_config_file(self, tmp_path):
        trainer = SLMTrainer()
        output_dir = tmp_path / "slm_adapter_cfg"
        mock_model = MagicMock()
        mock_model.save_pretrained = MagicMock()

        trainer.save_adapter(mock_model, str(output_dir))
        mock_model.save_pretrained.assert_called_with(str(output_dir))


class TestSLMTrainerIntentMapping:
    """Tests for intent label mapping."""

    def test_trainer_has_intent_map(self):
        trainer = SLMTrainer()
        assert hasattr(trainer, "INTENT_LABELS")
        assert "greeting" in trainer.INTENT_LABELS
        assert "complex" in trainer.INTENT_LABELS

    def test_label_to_id_is_bidirectional(self):
        trainer = SLMTrainer()
        labels = trainer.INTENT_LABELS
        assert len(labels) == len(set(labels))
        assert labels[0] == "greeting"
