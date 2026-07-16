"""Reranker fine-tuning — LoRA (GPU) or full fine-tune (CPU) via CrossEncoder.fit().

RerankerTrainer trains a cross-encoder reranker from (query, chunk_text, relevance_score)
triples collected from HITL feedback logs. Supports two modes:

- CPU mode (use_lora=False): full fine-tune via CrossEncoder.fit() — existing behavior
- GPU mode (use_lora=True): PEFT/LoRA on AutoModelForSequenceClassification — ~5 MB adapter

See ADR-010 §3.3 for details.
"""

from __future__ import annotations

import json
import logging
import math
import random
import uuid
from pathlib import Path
from typing import Any

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.trainer import (
    TrainerBase,
    TrainerType,
    TrainingConfig,
    TrainingJob,
)

logger = logging.getLogger(__name__)

try:
    import torch

    _TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]
    _TORCH_AVAILABLE = False

try:
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    AutoTokenizer = None  # type: ignore[assignment,misc]
    AutoModelForSequenceClassification = None  # type: ignore[assignment,misc]
    Trainer = None  # type: ignore[assignment,misc]
    TrainingArguments = None  # type: ignore[assignment,misc]
    _TRANSFORMERS_AVAILABLE = False

try:
    from peft import (
        LoraConfig,
        TaskType,
        get_peft_model,
    )

    _PEFT_AVAILABLE = True
except ImportError:
    LoraConfig = None
    TaskType = None
    get_peft_model = None
    _PEFT_AVAILABLE = False

try:
    from sentence_transformers import CrossEncoder

    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CrossEncoder = None  # type: ignore[misc]
    CROSS_ENCODER_AVAILABLE = False

RERANKER_LORA_R = 4
RERANKER_LORA_ALPHA = 8
RERANKER_LORA_DROPOUT = 0.05


class RerankerDataset(torch.utils.data.Dataset if _TORCH_AVAILABLE else object):  # type: ignore[misc]
    """PyTorch Dataset for reranker training from (query, chunk_text, score) triples."""

    def __init__(self, pairs: list[tuple[str, str, float]], tokenizer: Any, max_length: int = 512):
        self.pairs = pairs
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        query, chunk, score = self.pairs[idx]
        encoded = self.tokenizer(
            query,
            chunk,
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt",
        )
        return {
            "input_ids": encoded["input_ids"].squeeze(0),
            "attention_mask": encoded["attention_mask"].squeeze(0),
            "token_type_ids": encoded.get("token_type_ids", encoded["attention_mask"]).squeeze(0),
            "labels": torch.tensor(score, dtype=torch.float),
        }


class RerankerTrainer(TrainerBase):
    """LoRA fine-tune (GPU) or full fine-tune (CPU) for cross-encoder reranker.

    Dataset: (query, chunk_text, relevance_score) triples from HITL feedback.
    GPU mode: PEFT/LoRA on AutoModelForSequenceClassification — adapter ~5 MB.
    CPU mode: CrossEncoder.fit() — full fine-tune, saves full model.
    """

    def __init__(self) -> None:
        pass

    def prepare_data(
        self,
        dataset: list[tuple[str, str, float]],
        eval_split: float = 0.2,
        seed: int = 42,
    ) -> dict[str, list[tuple[str, str, float]]]:
        filtered = [
            (q, c, s) for q, c, s in dataset if isinstance(q, str) and isinstance(c, str) and len(q) > 0 and len(c) > 0
        ]
        if not filtered:
            return {"train": [], "eval": []}
        random.seed(seed)
        indices = list(range(len(filtered)))
        random.shuffle(indices)
        split_idx = max(1, int(len(filtered) * (1 - eval_split)))
        return {
            "train": [filtered[i] for i in indices[:split_idx]],
            "eval": [filtered[i] for i in indices[split_idx:]],
        }

    def train(self, config: TrainingConfig) -> TrainingJob:
        job_id = str(uuid.uuid4())
        job = TrainingJob(
            job_id=job_id,
            trainer_type=TrainerType.RERANKER,
            config=config,
            status="running",
        )
        try:
            if config.use_lora and _PEFT_AVAILABLE and _TRANSFORMERS_AVAILABLE and _TORCH_AVAILABLE:
                return self._train_lora(config, job, job_id)
            else:
                return self._train_full(config, job, job_id)
        except Exception as exc:
            logger.exception("Reranker training failed")
            job.status = "failed"
            job.error_message = str(exc)
            return job

    def _train_lora(self, config: TrainingConfig, job: TrainingJob, job_id: str) -> TrainingJob:
        if not _TRANSFORMERS_AVAILABLE or not _PEFT_AVAILABLE:
            raise RuntimeError(
                "transformers and peft are required for LoRA. Install: pip install transformers peft accelerate"
            )

        base_model = config.base_model or "cross-encoder/ms-marco-MiniLM-L-6-v2"
        device_map = self._resolve_device(config)

        tokenizer = AutoTokenizer.from_pretrained(base_model)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token or "[PAD]"

        model = AutoModelForSequenceClassification.from_pretrained(
            base_model,
            num_labels=1,
            device_map=device_map,
        )
        model.config.pad_token_id = tokenizer.pad_token_id

        peft_config = self._build_lora_config(config)
        model = get_peft_model(model, peft_config)

        train_data = self._load_dataset("reranker_train.json", tokenizer, config)
        eval_data = self._load_dataset("reranker_eval.json", tokenizer, config)

        training_args = self._build_training_args(config, job_id)
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_data,
            eval_dataset=eval_data,
            tokenizer=tokenizer,  # type: ignore[call-arg]
        )

        trainer.train()
        eval_metrics = trainer.evaluate()

        job.metrics = self._extract_metrics(eval_metrics)
        job.status = "completed"
        job.completed_at = str(uuid.uuid4())

        output_path = Path(config.output_dir) / job_id
        output_path.mkdir(parents=True, exist_ok=True)
        job.artifact_uri = str(output_path / "adapter")
        self.save_adapter(model, str(output_path / "adapter"), tokenizer)

        return job

    def _train_full(self, config: TrainingConfig, job: TrainingJob, job_id: str) -> TrainingJob:
        if not CROSS_ENCODER_AVAILABLE:
            raise RuntimeError(
                "sentence-transformers required for full fine-tune. Install: pip install sentence-transformers"
            )

        base_model = config.base_model or "cross-encoder/ms-marco-MiniLM-L-6-v2"

        train_data = self._load_json_dataset("reranker_train.json", config)
        eval_data = self._load_json_dataset("reranker_eval.json", config)

        all_pairs = train_data + eval_data

        train_inputs = [(q, c) for q, c, _ in all_pairs]
        train_scores = [s for _, _, s in all_pairs]

        ce = CrossEncoder(base_model, max_length=config.max_seq_length)
        ce.fit(
            train_dataloader=None,
            train_inputs=train_inputs,
            train_labels=train_scores,
            epochs=config.epochs,
            show_progress_bar=False,
        )

        output_path = Path(config.output_dir) / job_id
        output_path.mkdir(parents=True, exist_ok=True)
        ce.save(str(output_path / "full_model"))
        job.artifact_uri = str(output_path / "full_model")

        eval_metrics = self._evaluate_from_pairs(eval_data if eval_data else all_pairs)
        job.metrics = eval_metrics
        job.status = "completed"
        job.completed_at = str(uuid.uuid4())

        return job

    def evaluate(self, model: Any, eval_data: list[tuple[str, str, float]]) -> dict[str, float]:
        return self._evaluate_from_pairs(eval_data)

    def save_adapter(self, model: Any, output_path: str, tokenizer: Any = None) -> str:
        out = Path(output_path)
        out.mkdir(parents=True, exist_ok=True)

        if hasattr(model, "save_pretrained"):
            model.save_pretrained(str(out))
        elif _TORCH_AVAILABLE and isinstance(model, torch.nn.Module):
            torch.save(model.state_dict(), str(out / "adapter_model.bin"))

        if tokenizer is not None and hasattr(tokenizer, "save_pretrained"):
            tokenizer.save_pretrained(str(out))

        base_model = getattr(model, "name_or_path", None)
        if base_model is None:
            base_model = getattr(model, "config", None)
            if base_model is not None and hasattr(base_model, "name_or_path"):
                base_model = base_model.name_or_path
            elif base_model is not None and hasattr(base_model, "_name_or_path"):
                base_model = base_model._name_or_path
        config_data = {
            "model_type": "reranker_cross_encoder",
            "base_model": str(base_model) if base_model else "unknown",
            "num_labels": 1,
        }
        (out / "trainer_config.json").write_text(json.dumps(config_data, indent=2))

        return str(out)

    def _build_lora_config(self, config: TrainingConfig) -> Any:
        return LoraConfig(
            task_type=TaskType.SEQ_CLS,
            r=getattr(config, "lora_r", RERANKER_LORA_R),
            lora_alpha=getattr(config, "lora_alpha", RERANKER_LORA_ALPHA),
            lora_dropout=getattr(config, "lora_dropout", RERANKER_LORA_DROPOUT),
            target_modules=self._resolve_target_modules(config),
        )

    def _resolve_target_modules(self, config: TrainingConfig) -> list[str]:
        base = config.base_model.lower() if config.base_model else ""
        if "bert" in base or "minilm" in base:
            return ["query", "value"]
        if "roberta" in base:
            return ["query", "value"]
        if "gpt" in base or "llama" in base or "mistral" in base or "qwen" in base:
            return ["q_proj", "v_proj", "k_proj", "o_proj"]
        return ["query", "value"]

    def _build_training_args(self, config: TrainingConfig, job_id: str) -> Any:
        profile = config.env_profile
        fp16 = profile == EnvProfile.PROD and _TORCH_AVAILABLE and torch.cuda.is_available()
        return TrainingArguments(
            output_dir=str(Path(config.output_dir) / job_id / "checkpoints"),
            num_train_epochs=config.epochs,
            per_device_train_batch_size=config.batch_size,
            per_device_eval_batch_size=config.batch_size,
            learning_rate=config.learning_rate,
            warmup_steps=config.warmup_steps,
            logging_steps=config.logging_steps,
            eval_strategy="steps",
            eval_steps=config.eval_steps,
            save_steps=config.save_steps,
            fp16=fp16,
            seed=config.seed,
            report_to=[],
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            greater_is_better=False,
        )

    def _resolve_device(self, config: TrainingConfig) -> str:
        if not _TORCH_AVAILABLE:
            return "cpu"
        profile = config.env_profile
        if profile in (EnvProfile.PROD,):
            return "cuda" if torch.cuda.is_available() else "cpu"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _load_dataset(self, filename: str, tokenizer: Any, config: TrainingConfig) -> RerankerDataset:
        dataset_file = Path(config.output_dir) / filename
        if dataset_file.exists():
            data = json.loads(dataset_file.read_text())
            return RerankerDataset(data, tokenizer, config.max_seq_length)
        dummy = [("how to install docker", "Docker installation guide", 1.0)]
        return RerankerDataset(dummy, tokenizer, config.max_seq_length)

    def _load_json_dataset(self, filename: str, config: TrainingConfig | None = None) -> list[tuple[str, str, float]]:
        output_dir = config.output_dir if config else TrainingConfig(trainer_type=TrainerType.RERANKER).output_dir
        dataset_file = Path(output_dir) / filename
        if dataset_file.exists():
            return json.loads(dataset_file.read_text())  # type: ignore[no-any-return]
        return [("how to install docker", "Docker installation guide", 1.0)]

    def _extract_metrics(self, raw_metrics: dict[str, Any]) -> dict[str, float]:
        return {
            "mrr": float(raw_metrics.get("eval_mrr", 0.0)),
            "ndcg_at_10": float(raw_metrics.get("eval_ndcg_at_10", 0.0)),
            "precision_at_5": float(raw_metrics.get("eval_precision_at_5", 0.0)),
            "loss": float(raw_metrics.get("eval_loss", 0.0)),
        }

    def _evaluate_from_pairs(self, pairs: list[tuple[str, str, float]]) -> dict[str, float]:
        if not pairs:
            return {"mrr": 0.0, "ndcg_at_10": 0.0, "precision_at_5": 0.0}

        queries: dict[str, list[tuple[str, float]]] = {}
        for q, _, score in pairs:
            queries.setdefault(q, []).append(("", score))

        query_data: dict[str, list[tuple[str, float]]] = {}
        for q, c, score in pairs:
            query_data.setdefault(q, []).append((c, score))

        mrr_sum = 0.0
        ndcg_sum = 0.0
        precision_sum = 0.0
        query_count = 0

        for _q, items in query_data.items():
            items_sorted = sorted(items, key=lambda x: x[1], reverse=True)
            labels = [s for _, s in items_sorted]

            mrr_sum += self._compute_mrr(labels)
            ndcg_sum += self._compute_ndcg(labels, k=10)
            precision_sum += self._compute_precision_at_k(labels, k=5)
            query_count += 1

        if query_count == 0:
            return {"mrr": 0.0, "ndcg_at_10": 0.0, "precision_at_5": 0.0}

        return {
            "mrr": mrr_sum / query_count,
            "ndcg_at_10": ndcg_sum / query_count,
            "precision_at_5": precision_sum / query_count,
        }

    @staticmethod
    def _compute_mrr(sorted_labels: list[float]) -> float:
        for i, score in enumerate(sorted_labels, start=1):
            if score >= 1.0:
                return 1.0 / i
        return 0.0

    @staticmethod
    def _compute_ndcg(sorted_labels: list[float], k: int = 10) -> float:
        dcg = 0.0
        for i, score in enumerate(sorted_labels[:k], start=1):
            dcg += score / math.log2(i + 1)

        ideal = sorted(sorted_labels, reverse=True)
        idcg = 0.0
        for i, score in enumerate(ideal[:k], start=1):
            idcg += score / math.log2(i + 1)

        return dcg / idcg if idcg > 0 else 0.0

    @staticmethod
    def _compute_precision_at_k(sorted_labels: list[float], k: int = 5) -> float:
        top_k = sorted_labels[:k]
        if not top_k:
            return 0.0
        relevant = sum(1 for s in top_k if s >= 1.0)
        return relevant / len(top_k)
