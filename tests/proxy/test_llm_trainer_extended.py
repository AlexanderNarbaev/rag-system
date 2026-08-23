"""Tests for proxy/app/model_evolution/llm_trainer.py — additional unit tests."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.exceptions import TrainingError
from proxy.app.model_evolution.llm_trainer import LLMTrainer
from proxy.app.model_evolution.trainer import TrainerType


@pytest.fixture
def trainer():
    return LLMTrainer()


class TestLLMTrainerAdditional:
    def test_init_without_config(self, trainer):
        assert trainer.config.trainer_type == TrainerType.LLM

    def test_train_fails_with_exception(self, trainer, tmp_path):
        trainer.config.env_profile = EnvProfile.DEV
        trainer.config.output_dir = str(tmp_path)
        (tmp_path / "llm_train.json").write_text(json.dumps([{"messages": [{"role": "user", "content": "hi"}]}]))
        with (
            patch("proxy.app.model_evolution.llm_trainer.LLMTrainer._train_mock", side_effect=RuntimeError("boom")),
            pytest.raises(TrainingError, match="LLM training failed"),
        ):
            trainer.train(trainer.config)

    def test_train_mock_produces_metrics(self, trainer, tmp_path):
        trainer.config.env_profile = EnvProfile.DEV
        trainer.config.output_dir = str(tmp_path)
        data = [
            {"messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]},
            {"messages": [{"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"}]},
        ]
        (tmp_path / "llm_train.json").write_text(json.dumps(data))
        job = trainer.train(trainer.config)
        assert job.status == "completed"
        assert job.metrics is not None
        assert "train_loss" in job.metrics
        assert "val_loss" in job.metrics
        assert "bleu_1" in job.metrics
        assert "bleu_4" in job.metrics
        assert "rouge_l_f1" in job.metrics
        assert job.metrics["mock"] == 1.0

    def test_train_mock_single_sample(self, trainer, tmp_path):
        trainer.config.env_profile = EnvProfile.DEV
        trainer.config.output_dir = str(tmp_path)
        data = [{"messages": [{"role": "user", "content": "hello"}]}]
        (tmp_path / "llm_train.json").write_text(json.dumps(data))
        job = trainer.train(trainer.config)
        assert job.status == "completed"
        assert job.artifact_uri is not None

    def test_train_gpu_falls_back_to_mock_when_qlora_unavailable(self, trainer, tmp_path):
        trainer.config.env_profile = EnvProfile.PROD
        trainer.config.output_dir = str(tmp_path)
        data = [{"messages": [{"role": "user", "content": "hello"}]}]
        (tmp_path / "llm_train.json").write_text(json.dumps(data))
        with (
            patch("proxy.app.model_evolution.llm_trainer._QLORA_AVAILABLE", False),
            patch.object(trainer, "_cuda_available", return_value=True),
        ):
            job = trainer.train(trainer.config)
            assert job.status == "completed"
            assert "train_loss" in job.metrics

    def test_save_adapter_writes_adapter_config(self, trainer, tmp_path):
        trainer.config.base_model = "test-model"
        trainer.config.lora_r = 16
        trainer.config.use_qlora = True
        out = tmp_path / "adapter"
        result = trainer.save_adapter(str(out))
        config_file = Path(result) / "adapter_config.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["base_model_name_or_path"] == "test-model"
        assert data["lora_r"] == 16
        assert data["peft_type"] == "LORA"
        assert data["use_qlora"] is True

    def test_save_adapter_creates_safetensors_file(self, trainer, tmp_path):
        out = tmp_path / "adapter"
        result = trainer.save_adapter(str(out))
        adapter_file = Path(result) / "adapter_model.safetensors"
        assert adapter_file.exists()

    def test_push_to_registry_uses_artifact_uri(self, trainer):
        job = MagicMock()
        job.artifact_uri = "/path/to/model"
        job.job_id = "test-job"
        assert trainer.push_to_registry(job) == "/path/to/model"

    def test_push_to_registry_falls_back_to_job_id(self, trainer):
        job = MagicMock()
        job.artifact_uri = None
        job.job_id = "test-job-123"
        assert trainer.push_to_registry(job) == "test-job-123"

    def test_push_to_registry_none_raises_value_error(self, trainer):
        with pytest.raises(ValueError, match="No training job"):
            trainer.push_to_registry(None)

    def test_make_job_id_is_unique(self, trainer):
        ids = {LLMTrainer._make_job_id() for _ in range(10)}
        assert len(ids) == 10
        for jid in ids:
            assert jid.startswith("llm-")

    def test_cuda_available_checks_torch(self, trainer):
        with patch.dict("sys.modules", {"torch": None}):
            assert trainer._cuda_available() is False

    def test_find_lora_target_modules_dedup(self, trainer):
        mock_model = MagicMock()
        mock_model.named_modules.return_value = [
            ("layer.0.q_proj", MagicMock()),
            ("layer.1.q_proj", MagicMock()),
            ("layer.0.v_proj", MagicMock()),
        ]
        modules = LLMTrainer._find_lora_target_modules(mock_model)
        assert "q_proj" in modules
        assert "v_proj" in modules
        assert modules.count("q_proj") <= 1

    def test_find_lora_target_modules_all_types(self, trainer):
        mock_model = MagicMock()
        mock_model.named_modules.return_value = [
            ("layer.0.q_proj", MagicMock()),
            ("layer.0.k_proj", MagicMock()),
            ("layer.0.v_proj", MagicMock()),
            ("layer.0.o_proj", MagicMock()),
            ("layer.0.gate_proj", MagicMock()),
            ("layer.0.up_proj", MagicMock()),
            ("layer.0.down_proj", MagicMock()),
        ]
        modules = LLMTrainer._find_lora_target_modules(mock_model)
        assert len(modules) == 7
        assert sorted(modules) == ["down_proj", "gate_proj", "k_proj", "o_proj", "q_proj", "up_proj", "v_proj"]


class TestLLMTrainerEvaluate:
    def test_evaluate_empty_data(self, trainer):
        assert trainer.evaluate([]) == {}

    def test_evaluate_cpu_mode_returns_metrics(self, trainer):
        trainer.config.env_profile = EnvProfile.DEV
        result = trainer.evaluate([{"messages": []}])
        assert "train_loss" in result
        assert "val_loss" in result
        assert "bleu_1" in result
        assert result["mock"] == 1.0

    def test_evaluate_gpu_mode_computes_metrics_from_pairs(self, trainer):
        trainer.config.env_profile = EnvProfile.PROD
        eval_data = [
            {
                "messages": [
                    {"role": "user", "content": "q"},
                    {"role": "assistant", "content": "the reference"},
                ],
                "prediction": "the hypothesis",
            },
        ]
        fake_bleu = MagicMock()
        fake_bleu.BLEU.return_value.corpus_score.return_value = SimpleNamespace(score=50.0)
        fake_rouge = MagicMock()
        fake_rouge.rouge_scorer.RougeScorer.return_value.score.return_value = {
            "rougeL": SimpleNamespace(precision=0.4, recall=0.5, fmeasure=0.45),
        }
        fake_bert = MagicMock()
        fake_bert.score.return_value = (
            SimpleNamespace(mean=lambda: 0.6),
            SimpleNamespace(mean=lambda: 0.7),
            SimpleNamespace(mean=lambda: 0.65),
        )
        modules = {"sacrebleu": fake_bleu, "rouge_score": fake_rouge, "bert_score": fake_bert}
        with patch.dict("sys.modules", modules):
            result = trainer.evaluate(eval_data)
        assert result["bleu_1"] == pytest.approx(0.50)
        assert result["rouge_l_f1"] == pytest.approx(0.45)
        assert result["bertscore_f1"] == pytest.approx(0.65)
        assert "mock" not in result

    def test_evaluate_ci_mode_is_cpu(self, trainer):
        trainer.config.env_profile = EnvProfile.CI
        assert trainer._is_cpu_profile() is True
        result = trainer.evaluate([{"messages": []}])
        assert "train_loss" in result
        assert result["mock"] == 1.0


class TestLLMTrainerTokenizeDataset:
    def test_tokenize_dataset_with_chat_template(self, trainer):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.return_value = "<user>hello</user><assistant>hi</assistant>"
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }
        mock_tokenizer.pad_token = "[PAD]"

        data = [{"messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]}]
        result = trainer._tokenize_dataset(mock_tokenizer, data)

        assert len(result) == 1

    def test_tokenize_dataset_fallback_on_chat_template_failure(self, trainer):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.side_effect = RuntimeError("template error")
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }

        data = [{"messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]}]
        result = trainer._tokenize_dataset(mock_tokenizer, data)

        assert len(result) == 1

    def test_tokenize_dataset_multiple_samples(self, trainer):
        import torch

        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.return_value = "formatted"
        mock_tokenizer.return_value = {
            "input_ids": torch.tensor([[1, 2], [3, 4]]),
            "attention_mask": torch.tensor([[1, 1], [1, 1]]),
        }

        data = [
            {"messages": [{"role": "user", "content": "q1"}]},
            {"messages": [{"role": "user", "content": "q2"}]},
        ]
        result = trainer._tokenize_dataset(mock_tokenizer, data)
        assert len(result) == 2
