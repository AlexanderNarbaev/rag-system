"""Tests for proxy/app/model_evolution/llm_trainer.py — LLMTrainer (QLoRA)."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.exceptions import TrainingError
from proxy.app.model_evolution.llm_trainer import LLMTrainer
from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig, TrainingJob

# ── Sample HITL training data ──────────────────────────────────────────────

_SAMPLE_TRAINING_DATA = [
    {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": "Context: CI/CD documentation\n\nQuestion: How to configure CI/CD pipeline?",
            },
            {
                "role": "assistant",
                "content": "Create a .gitlab-ci.yml file with stages: build, test, deploy.",
            },
        ],
        "metadata": {"request_id": "r1", "feedback_type": "correction", "has_correction": True},
    },
    {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": "Context: Docker documentation\n\nQuestion: What is Docker?",
            },
            {
                "role": "assistant",
                "content": (
                    "Docker is a platform for developing, shipping, "
                    "and running applications in containers."
                ),
            },
        ],
        "metadata": {"request_id": "r2", "feedback_type": "positive", "has_correction": False},
    },
]


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def cpu_config():
    return TrainingConfig(
        trainer_type=TrainerType.LLM,
        env_profile=EnvProfile.DEV,
        base_model="test-model",
        output_dir="/tmp/test_training",
        epochs=1,
        batch_size=2,
        learning_rate=2e-4,
        max_seq_length=256,
        use_lora=True,
        lora_r=8,
        lora_alpha=16,
        use_qlora=False,
        load_in_4bit=False,
        seed=42,
    )


@pytest.fixture
def gpu_config():
    return TrainingConfig(
        trainer_type=TrainerType.LLM,
        env_profile=EnvProfile.PROD,
        base_model="test-model",
        output_dir="/tmp/test_training_gpu",
        epochs=2,
        batch_size=8,
        learning_rate=2e-4,
        max_seq_length=2048,
        use_lora=True,
        lora_r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        use_qlora=True,
        load_in_4bit=True,
        bnb_4bit_compute_dtype="bfloat16",
        warmup_steps=100,
        seed=42,
    )


@pytest.fixture
def trainer_cpu(cpu_config):
    return LLMTrainer(config=cpu_config)


@pytest.fixture
def trainer_gpu(gpu_config):
    return LLMTrainer(config=gpu_config)


# ── Initialization ──────────────────────────────────────────────────────────

class TestLLMTrainerInit:
    def test_creates_with_config(self, cpu_config):
        trainer = LLMTrainer(config=cpu_config)
        assert trainer.config == cpu_config
        assert trainer.config.trainer_type == TrainerType.LLM

    def test_creates_with_default_config(self):
        trainer = LLMTrainer()
        assert trainer.config.trainer_type == TrainerType.LLM
        assert trainer.config.env_profile == EnvProfile.DEV

    def test_detects_cpu_profile(self, cpu_config):
        trainer = LLMTrainer(config=cpu_config)
        assert trainer._is_cpu_profile() is True

    def test_detects_gpu_profile(self, gpu_config):
        trainer = LLMTrainer(config=gpu_config)
        assert trainer._is_cpu_profile() is False


# ── prepare_data ────────────────────────────────────────────────────────────

class TestPrepareData:
    def test_prepares_training_data_from_hitl_pairs(self, trainer_cpu):
        result = trainer_cpu.prepare_data(_SAMPLE_TRAINING_DATA)
        assert len(result) == 2
        for item in result:
            assert "messages" in item

    def test_prepare_data_returns_empty_on_empty_input(self, trainer_cpu):
        result = trainer_cpu.prepare_data([])
        assert result == []

    def test_prepare_data_preserves_messages_structure(self, trainer_cpu):
        result = trainer_cpu.prepare_data(_SAMPLE_TRAINING_DATA)
        assert len(result[0]["messages"]) == 3
        assert result[0]["messages"][0]["role"] == "system"

    def test_prepare_data_handles_single_item(self, trainer_cpu):
        single = [_SAMPLE_TRAINING_DATA[0]]
        result = trainer_cpu.prepare_data(single)
        assert len(result) == 1


# ── train (CPU / mock) ──────────────────────────────────────────────────────

class TestTrainCPU:
    def test_train_cpu_returns_training_job(self, trainer_cpu):
        job = trainer_cpu.train(_SAMPLE_TRAINING_DATA)
        assert isinstance(job, TrainingJob)
        assert job.trainer_type == TrainerType.LLM
        assert job.status == "completed"

    def test_train_cpu_job_has_metrics(self, trainer_cpu):
        job = trainer_cpu.train(_SAMPLE_TRAINING_DATA)
        assert "train_loss" in job.metrics
        assert "val_loss" in job.metrics
        assert isinstance(job.metrics["train_loss"], float)

    def test_train_cpu_with_empty_data_raises(self, trainer_cpu):
        with pytest.raises(TrainingError, match="No training data"):
            trainer_cpu.train([])

    def test_train_cpu_produces_mock_adapter(self, trainer_cpu, tmp_path):
        trainer_cpu.config.output_dir = str(tmp_path)
        job = trainer_cpu.train(_SAMPLE_TRAINING_DATA)
        assert job.artifact_uri is not None
        adapter_dir = Path(job.artifact_uri)
        assert adapter_dir.exists()
        assert (adapter_dir / "adapter_config.json").exists()

    def test_train_cpu_job_has_run_id(self, trainer_cpu):
        job = trainer_cpu.train(_SAMPLE_TRAINING_DATA)
        assert job.job_id is not None
        assert len(job.job_id) > 0


# ── train (GPU / QLoRA) ─────────────────────────────────────────────────────

class TestTrainGPU:
    def test_train_gpu_configures_qlora(self, gpu_config):
        assert gpu_config.use_qlora is True
        assert gpu_config.load_in_4bit is True
        assert gpu_config.lora_r == 16
        assert gpu_config.lora_alpha == 32

    def test_train_gpu_mocked_returns_job(self, trainer_gpu):
        with patch("torch.cuda.is_available", return_value=True), \
             patch("proxy.app.model_evolution.llm_trainer._QLORA_AVAILABLE", True), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.AutoModelForCausalLM", create=True
             ) as mock_auto, \
             patch(
                 "proxy.app.model_evolution.llm_trainer.AutoTokenizer", create=True
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.BitsAndBytesConfig", create=True
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.LoraConfig", create=True
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.get_peft_model", create=True
             ) as mock_peft, \
             patch(
                 "proxy.app.model_evolution.llm_trainer.prepare_model_for_kbit_training",
                 create=True,
             ) as mock_prepare_kbit, \
             patch(
                 "proxy.app.model_evolution.llm_trainer.TrainingArguments", create=True
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.Trainer", create=True
             ) as mock_hf_trainer:
            mock_model = MagicMock()
            mock_auto.from_pretrained.return_value = mock_model
            mock_peft.return_value = mock_model
            mock_prepare_kbit.return_value = mock_model

            mock_hf_trainer_instance = MagicMock()
            mock_hf_trainer_instance.train.return_value = MagicMock()
            mock_hf_trainer_instance.evaluate.return_value = {"eval_loss": 0.5}
            mock_hf_trainer.return_value = mock_hf_trainer_instance

            job = trainer_gpu.train(_SAMPLE_TRAINING_DATA)
            assert isinstance(job, TrainingJob)
            assert job.status == "completed"
            assert "eval_loss" in job.metrics

    def test_train_gpu_no_cuda_falls_back_to_mock(self, trainer_gpu):
        with patch("torch.cuda.is_available", return_value=False):
            job = trainer_gpu.train(_SAMPLE_TRAINING_DATA)
            assert isinstance(job, TrainingJob)
            assert job.status == "completed"

    def test_train_gpu_saves_adapter(self, trainer_gpu, tmp_path):
        trainer_gpu.config.output_dir = str(tmp_path)
        with patch("torch.cuda.is_available", return_value=True), \
             patch("proxy.app.model_evolution.llm_trainer._QLORA_AVAILABLE", True), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.AutoModelForCausalLM", create=True
             ) as mock_auto, \
             patch(
                 "proxy.app.model_evolution.llm_trainer.AutoTokenizer", create=True
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.BitsAndBytesConfig", create=True
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.LoraConfig", create=True
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.get_peft_model", create=True
             ) as mock_peft, \
             patch(
                 "proxy.app.model_evolution.llm_trainer.prepare_model_for_kbit_training",
                 create=True,
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.TrainingArguments", create=True
             ), \
             patch(
                 "proxy.app.model_evolution.llm_trainer.Trainer", create=True
             ) as mock_hf_trainer:
            mock_model = MagicMock()
            mock_auto.from_pretrained.return_value = mock_model
            mock_peft.return_value = mock_model
            mock_hf_trainer_instance = MagicMock()
            mock_hf_trainer.return_value = mock_hf_trainer_instance

            job = trainer_gpu.train(_SAMPLE_TRAINING_DATA)
            assert job.artifact_uri is not None
            mock_model.save_pretrained.assert_called_once()


# ── save_adapter ────────────────────────────────────────────────────────────

class TestSaveAdapter:
    def test_save_adapter_creates_directory(self, trainer_cpu, tmp_path):
        adapter_path = tmp_path / "adapter"
        result = trainer_cpu.save_adapter(adapter_path)
        assert Path(result).exists()
        assert (Path(result) / "adapter_config.json").exists()

    def test_save_adapter_writes_config(self, trainer_cpu, tmp_path):
        adapter_path = tmp_path / "adapter"
        result = trainer_cpu.save_adapter(adapter_path)
        config_path = Path(result) / "adapter_config.json"
        with open(config_path) as f:
            config = json.load(f)
        assert "base_model_name_or_path" in config
        assert "lora_r" in config
        assert "lora_alpha" in config
        assert config["base_model_name_or_path"] == trainer_cpu.config.base_model

    def test_save_adapter_overwrites_existing(self, trainer_cpu, tmp_path):
        adapter_path = tmp_path / "adapter"
        adapter_path.mkdir(parents=True)
        (adapter_path / "adapter_config.json").write_text("old")
        result = trainer_cpu.save_adapter(adapter_path)
        with open(Path(result) / "adapter_config.json") as f:
            config = json.load(f)
        assert config["base_model_name_or_path"] == trainer_cpu.config.base_model


# ── evaluate ────────────────────────────────────────────────────────────────

class TestEvaluate:
    def test_evaluate_returns_metrics_dict(self, trainer_cpu):
        eval_data = [
            {
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Question: What is CI?"},
                    {"role": "assistant", "content": "CI is Continuous Integration."},
                ]
            }
        ]
        metrics = trainer_cpu.evaluate(eval_data)
        assert isinstance(metrics, dict)
        assert "train_loss" in metrics or "val_loss" in metrics or "bleu_1" in metrics

    def test_evaluate_empty_data_returns_empty(self, trainer_cpu):
        metrics = trainer_cpu.evaluate([])
        assert metrics == {}

    def test_evaluate_with_references(self, trainer_cpu):
        eval_data = [
            {
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Question: What is CI?"},
                    {"role": "assistant", "content": "CI is Continuous Integration."},
                ],
                "reference": "Continuous Integration is a development practice.",
            }
        ]
        metrics = trainer_cpu.evaluate(eval_data)
        assert isinstance(metrics, dict)


# ── push_to_registry (stub) ─────────────────────────────────────────────────

class TestPushToRegistry:
    def test_push_to_registry_returns_artifact_uri(self, trainer_cpu):
        job = trainer_cpu.train(_SAMPLE_TRAINING_DATA)
        result = trainer_cpu.push_to_registry(job)
        assert result is not None
        assert len(result) > 0

    def test_push_to_registry_no_job_raises(self, trainer_cpu):
        with pytest.raises(ValueError, match="No training job"):
            trainer_cpu.push_to_registry(None)
