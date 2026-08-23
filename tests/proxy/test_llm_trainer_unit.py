"""Tests for proxy/app/model_evolution/llm_trainer.py — unit tests without GPU deps."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.exceptions import TrainingError
from proxy.app.model_evolution.llm_trainer import LLMTrainer
from proxy.app.model_evolution.trainer import TrainerType, TrainingConfig


def _write_llm_dataset(output_dir: Path, data: list[dict]) -> None:
    """Write an llm_train.json dataset fixture into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "llm_train.json").write_text(json.dumps(data))


def _make_fake_metric_modules() -> dict[str, object]:
    """Build fake sacrebleu/rouge_score/bert_score modules for sys.modules patching."""

    class _FakeBLEU:
        def __init__(self, max_ngram_order: int = 4) -> None:
            self.max_ngram_order = max_ngram_order

        def corpus_score(self, hypotheses: list[str], references: list[list[str]]) -> object:
            return SimpleNamespace(score=42.0)

    sacrebleu = SimpleNamespace(BLEU=_FakeBLEU)

    rouge_result = SimpleNamespace(precision=0.5, recall=0.6, fmeasure=0.55)
    scorer = SimpleNamespace(score=lambda ref, hyp: {"rougeL": rouge_result})
    rouge_scorer = SimpleNamespace(RougeScorer=lambda names, use_stemmer=True: scorer)
    rouge_score = SimpleNamespace(rouge_scorer=rouge_scorer)

    bert_score = SimpleNamespace(
        score=lambda hyps, refs, **kwargs: (
            SimpleNamespace(mean=lambda: 0.7),
            SimpleNamespace(mean=lambda: 0.8),
            SimpleNamespace(mean=lambda: 0.75),
        ),
    )
    return {"sacrebleu": sacrebleu, "rouge_score": rouge_score, "bert_score": bert_score}


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
        _write_llm_dataset(
            tmp_path,
            [{"messages": [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]}],
        )
        trainer = LLMTrainer(config)
        job = trainer.train(config)
        assert job.status == "completed"
        assert job.metrics is not None
        assert "train_loss" in job.metrics
        assert job.artifact_uri is not None

    def test_train_accepts_training_config(self, tmp_path):
        """LLMTrainer.train takes a TrainingConfig, matching SLM/Reranker trainers."""
        config = TrainingConfig(
            trainer_type=TrainerType.LLM,
            env_profile=EnvProfile.DEV,
            output_dir=str(tmp_path),
        )
        _write_llm_dataset(
            tmp_path,
            [{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}],
        )
        trainer = LLMTrainer()
        job = trainer.train(config)
        assert job.status == "completed"
        assert job.config is config
        assert trainer.config is config

    def test_train_missing_dataset_raises(self, tmp_path):
        """A missing llm_train.json must fail loudly instead of using dummy data."""
        config = TrainingConfig(
            trainer_type=TrainerType.LLM,
            env_profile=EnvProfile.DEV,
            output_dir=str(tmp_path),
        )
        trainer = LLMTrainer(config)
        with pytest.raises(TrainingError, match="dataset not found"):
            trainer.train(config)

    def test_train_empty_data_raises(self, tmp_path):
        config = TrainingConfig(
            trainer_type=TrainerType.LLM,
            env_profile=EnvProfile.DEV,
            output_dir=str(tmp_path),
        )
        _write_llm_dataset(tmp_path, [{"no_messages": True}])
        trainer = LLMTrainer(config)
        with pytest.raises(TrainingError, match="No training data"):
            trainer.train(config)

    def test_evaluate_empty(self):
        trainer = LLMTrainer()
        assert trainer.evaluate([]) == {}

    def test_evaluate_cpu_mode(self):
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.DEV
        result = trainer.evaluate([{"messages": []}])
        assert "train_loss" in result
        assert result["mock"] == 1.0

    def test_evaluate_gpu_mode_computes_real_metrics(self):
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.PROD
        eval_data = [
            {
                "messages": [
                    {"role": "user", "content": "q"},
                    {"role": "assistant", "content": "reference answer"},
                ],
                "prediction": "hypothesis answer",
            },
        ]
        with patch.dict("sys.modules", _make_fake_metric_modules()):
            result = trainer.evaluate(eval_data)
        assert result["bleu_1"] == pytest.approx(0.42)
        assert result["bleu_4"] == pytest.approx(0.42)
        assert result["rouge_l_f1"] == pytest.approx(0.55)
        assert result["rouge_l_precision"] == pytest.approx(0.5)
        assert result["rouge_l_recall"] == pytest.approx(0.6)
        assert result["bertscore_f1"] == pytest.approx(0.75)
        assert "mock" not in result

    def test_evaluate_gpu_mode_missing_libs_returns_available_only(self):
        """Unavailable metric packages are skipped with a warning, not an error."""
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.PROD
        eval_data = [
            {
                "messages": [{"role": "assistant", "content": "ref"}],
                "prediction": "hyp",
            },
        ]
        fake = _make_fake_metric_modules()
        modules = {"sacrebleu": fake["sacrebleu"], "rouge_score": None, "bert_score": None}
        with patch.dict("sys.modules", modules):
            result = trainer.evaluate(eval_data)
        assert "bleu_1" in result
        assert "rouge_l_f1" not in result
        assert "bertscore_f1" not in result

    def test_evaluate_gpu_mode_no_pairs_returns_empty(self):
        trainer = LLMTrainer()
        trainer.config.env_profile = EnvProfile.PROD
        result = trainer.evaluate([{"messages": [{"role": "user", "content": "q only"}]}])
        assert result == {}

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
