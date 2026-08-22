# model_evolution_service/trainers/llm.py
"""LLM QLoRA fine-tuning for domain-specific generation.

Uses bitsandbytes (4-bit NF4 quantization) + PEFT (LoRA) for memory-efficient
fine-tuning. Falls back to mock training on CPU or when GPU libs are unavailable.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from model_evolution_service.config import EnvProfile
from model_evolution_service.exceptions import TrainingError
from model_evolution_service.trainers.base import (
    TrainerBase,
    TrainerType,
    TrainingConfig,
    TrainingJob,
)

logger = logging.getLogger(__name__)

# ── Optional GPU dependencies ─────────────────────────────────────────────────

_QLORA_AVAILABLE = False
try:
    import bitsandbytes as bnb  # noqa: F401
    import peft  # noqa: F401
    import torch  # noqa: F401
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        Trainer,
        TrainingArguments,
    )

    _QLORA_AVAILABLE = True
except ImportError:
    pass


# ── LLMTrainer ────────────────────────────────────────────────────────────────


class LLMTrainer(TrainerBase):
    """QLoRA fine-tune for domain-specific generation using instruction-tuning pairs.

    EnvProfile.CPU → mock training (CPU can't run 4-bit quantization).
    EnvProfile.GPU → full QLoRA with bitsandbytes + PEFT + gradient checkpointing.
    """

    def __init__(self, config: TrainingConfig | None = None):
        if config is None:
            config = TrainingConfig(trainer_type=TrainerType.LLM)
        config.trainer_type = TrainerType.LLM
        self.config = config

    # ── Profile detection ─────────────────────────────────────────────────

    def _is_cpu_profile(self) -> bool:
        """Return True if the current env profile cannot use GPU training."""
        return self.config.env_profile in (EnvProfile.DEV, EnvProfile.CI)

    def _cuda_available(self) -> bool:
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    # ── Data preparation ───────────────────────────────────────────────────

    def prepare_data(self, training_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pass through instruction-tuning pairs (pre-formatted by DataProcessor)."""
        result: list[dict[str, Any]] = []
        for item in training_data:
            if item.get("messages"):
                result.append({"messages": item["messages"]})
        return result

    # ── Training ───────────────────────────────────────────────────────────

    def train(self, config: TrainingConfig) -> TrainingJob:
        """Execute training from a TrainingConfig (unified trainer interface).

        Loads instruction-tuning pairs from ``llm_train.json`` inside
        ``config.output_dir``, prepares them via :meth:`prepare_data`, then runs
        mock (CPU profile) or QLoRA (GPU profile) training.

        Args:
            config: Training configuration with hyperparameters and output_dir.

        Returns:
            TrainingJob with status, metrics, and artifact URI.

        Raises:
            TrainingError: If the dataset is missing/empty or training fails.

        """
        config.trainer_type = TrainerType.LLM
        self.config = config

        job = TrainingJob(
            job_id=self._make_job_id(),
            trainer_type=TrainerType.LLM,
            config=config,
            status="running",
            started_at=datetime.now(UTC).isoformat(),
        )

        try:
            prepared = self.prepare_data(self._load_training_data(config))
            if not prepared:
                raise TrainingError("No training data provided after preparation")
            if self._is_cpu_profile() or not self._cuda_available():
                return self._train_mock(job, prepared)
            return self._train_gpu(job, prepared)
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            logger.exception("LLM training failed: %s", exc)
            if isinstance(exc, TrainingError):
                raise
            raise TrainingError(f"LLM training failed: {exc}") from exc

    @staticmethod
    def _load_training_data(config: TrainingConfig) -> list[dict[str, Any]]:
        """Load instruction-tuning pairs from ``llm_train.json`` in output_dir.

        Raises:
            FileNotFoundError: If the dataset file does not exist — training
                must never fall back to a silent dummy dataset.

        """
        dataset_file = Path(config.output_dir) / "llm_train.json"
        if not dataset_file.exists():
            raise FileNotFoundError(
                f"LLM training dataset not found: {dataset_file}. "
                "Export instruction-tuning pairs to llm_train.json in config.output_dir before training.",
            )
        data: list[dict[str, Any]] = json.loads(dataset_file.read_text())
        return data

    def _train_mock(self, job: TrainingJob, prepared: list[dict[str, Any]]) -> TrainingJob:
        """Simulate training on CPU — produce mock metrics and adapter.

        Metrics are explicitly flagged with ``mock=1.0`` so placeholders cannot
        be mistaken for real measurements downstream (e.g. by the eval gate).
        """
        logger.info("Running LLM mock training (CPU profile) with %d samples", len(prepared))

        job.metrics = {
            "train_loss": 0.5 + (len(prepared) % 10) * 0.01,
            "val_loss": 0.55 + (len(prepared) % 10) * 0.01,
            "bleu_1": 0.42,
            "bleu_4": 0.15,
            "rouge_l_f1": 0.38,
            "mock": 1.0,
        }

        output_dir = Path(self.config.output_dir) / f"run_{job.job_id}"
        job.artifact_uri = self.save_adapter(output_dir)
        job.status = "completed"
        job.completed_at = datetime.now(UTC).isoformat()
        return job

    def _train_gpu(self, job: TrainingJob, prepared: list[dict[str, Any]]) -> TrainingJob:
        """Full QLoRA fine-tuning on GPU with bitsandbytes 4-bit quantization + PEFT LoRA."""
        if not _QLORA_AVAILABLE:
            logger.warning("GPU profile requested but QLoRA libs unavailable, falling back to mock")
            return self._train_mock(job, prepared)

        import torch

        logger.info(
            "Starting QLoRA training with %d samples on %s",
            len(prepared),
            torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
        )

        bnb_config = BitsAndBytesConfig(  # type: ignore[no-untyped-call]
            load_in_4bit=self.config.load_in_4bit,
            bnb_4bit_compute_dtype=getattr(torch, self.config.bnb_4bit_compute_dtype, torch.float16),
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )

        model = AutoModelForCausalLM.from_pretrained(
            self.config.base_model,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )
        model.config.use_cache = False

        tokenizer = AutoTokenizer.from_pretrained(self.config.base_model, trust_remote_code=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = prepare_model_for_kbit_training(model)

        peft_config = LoraConfig(
            r=self.config.lora_r,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=self._find_lora_target_modules(model),
        )

        model = get_peft_model(model, peft_config)

        tokenized = self._tokenize_dataset(tokenizer, prepared)

        training_args = TrainingArguments(
            output_dir=str(Path(self.config.output_dir) / f"checkpoints_{job.job_id}"),
            num_train_epochs=self.config.epochs,
            per_device_train_batch_size=self.config.batch_size,
            gradient_accumulation_steps=4,
            gradient_checkpointing=True,
            warmup_steps=self.config.warmup_steps,
            learning_rate=self.config.learning_rate,
            logging_steps=self.config.logging_steps,
            save_steps=self.config.save_steps,
            eval_steps=self.config.eval_steps,
            eval_strategy="steps",
            save_strategy="steps",
            load_best_model_at_end=True,
            fp16=torch.cuda.is_available(),
            bf16=False,
            seed=self.config.seed,
            report_to="none",
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=tokenized,
            tokenizer=tokenizer,
            # type: ignore[call-arg]
        )

        trainer.train()

        eval_results = trainer.evaluate()
        job.metrics = {
            "eval_loss": float(eval_results.get("eval_loss", 0.0)),
        }

        output_dir = Path(self.config.output_dir) / f"adapter_{job.job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))
        job.artifact_uri = str(output_dir)

        job.status = "completed"
        job.completed_at = datetime.now(UTC).isoformat()
        return job

    def _tokenize_dataset(self, tokenizer: Any, prepared: list[dict[str, Any]]) -> Any:
        """Tokenize instruction-tuning pairs for training."""
        import torch

        texts: list[str] = []
        for item in prepared:
            messages = item["messages"]
            try:
                text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
                texts.append(text)
            except Exception:
                fallback = ""
                for msg in messages:
                    fallback += f"{msg['role']}: {msg['content']}\n"
                texts.append(fallback.strip())

        encodings = tokenizer(
            texts,
            truncation=True,
            padding=True,
            max_length=self.config.max_seq_length,
            return_tensors="pt",
        )
        encodings["labels"] = encodings["input_ids"].clone()

        class _TokenizedDataset(torch.utils.data.Dataset[Any]):
            def __init__(self, encs: dict[str, Any]) -> None:
                self._encs = encs

            def __len__(self) -> int:
                return len(self._encs["input_ids"])

            def __getitem__(self, idx: int) -> dict[str, Any]:
                return {k: v[idx] for k, v in self._encs.items()}

        return _TokenizedDataset(encodings)

    @staticmethod
    def _find_lora_target_modules(model: Any) -> list[str]:
        """Find linear layers suitable for LoRA adaptation."""
        import re

        modules = set()
        for name, _ in model.named_modules():
            if re.search(r"(q_proj|v_proj|k_proj|o_proj|gate_proj|up_proj|down_proj)", name):
                modules.add(name.split(".")[-1])
        if not modules:
            return ["q_proj", "v_proj"]
        return sorted(modules)

    # ── Evaluation ─────────────────────────────────────────────────────────

    def evaluate(  # type: ignore[override]
        self,
        eval_data: list[dict[str, Any]],
        model: Any = None,
        tokenizer: Any = None,
    ) -> dict[str, float]:
        """Compute evaluation metrics on held-out data.

        CPU/mock profile: returns placeholder metrics explicitly flagged with
        ``mock=1.0`` so they cannot be mistaken for real measurements.
        GPU profile: computes BLEU (sacrebleu), ROUGE-L (rouge-score), and
        BertScore (bert-score) over reference/hypothesis pairs. Each metric
        library is imported lazily — if a package is unavailable, a warning is
        logged and only the available metrics are returned.
        """
        if not eval_data:
            return {}

        if self._is_cpu_profile():
            logger.warning("CPU/mock profile: returning placeholder LLM eval metrics (mock=1.0)")
            return {
                "train_loss": 0.45,
                "val_loss": 0.52,
                "bleu_1": 0.40,
                "bleu_4": 0.12,
                "rouge_l_f1": 0.35,
                "mock": 1.0,
            }

        references, hypotheses = self._extract_eval_pairs(eval_data, model, tokenizer)
        if not references:
            logger.warning("No reference/hypothesis pairs could be derived from eval data")
            return {}

        metrics: dict[str, float] = {}
        metrics.update(self._compute_bleu(references, hypotheses))
        metrics.update(self._compute_rouge_l(references, hypotheses))
        metrics.update(self._compute_bertscore(references, hypotheses))
        return metrics

    def _extract_eval_pairs(
        self,
        eval_data: list[dict[str, Any]],
        model: Any = None,
        tokenizer: Any = None,
    ) -> tuple[list[str], list[str]]:
        """Build (reference, hypothesis) pairs from eval data.

        Reference: content of the last assistant message. Hypothesis: an
        explicit ``prediction``/``hypothesis`` field on the item, or text
        generated by the provided model/tokenizer from the prompt messages.
        """
        references: list[str] = []
        hypotheses: list[str] = []
        for item in eval_data:
            reference = self._reference_from_messages(item.get("messages") or [])
            if not reference:
                continue
            hypothesis = item.get("prediction") or item.get("hypothesis")
            if hypothesis is None and model is not None and tokenizer is not None:
                hypothesis = self._generate_hypothesis(model, tokenizer, item.get("messages") or [])
            if not hypothesis:
                continue
            references.append(reference)
            hypotheses.append(str(hypothesis))
        return references, hypotheses

    @staticmethod
    def _reference_from_messages(messages: list[dict[str, Any]]) -> str:
        """Return the content of the last assistant message, or an empty string."""
        for message in reversed(messages):
            if message.get("role") == "assistant" and message.get("content"):
                return str(message["content"])
        return ""

    def _generate_hypothesis(self, model: Any, tokenizer: Any, messages: list[dict[str, Any]]) -> str:
        """Generate an answer from prompt messages using the fine-tuned model."""
        import torch

        prompt_messages = [m for m in messages if m.get("role") != "assistant"]
        try:
            prompt = tokenizer.apply_chat_template(prompt_messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            prompt = "".join(f"{m['role']}: {m['content']}\n" for m in prompt_messages)

        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=self.config.max_seq_length)
        with torch.no_grad():
            output_ids = model.generate(**inputs, max_new_tokens=256)
        generated = output_ids[0][inputs["input_ids"].shape[-1] :]
        return str(tokenizer.decode(generated, skip_special_tokens=True))

    @staticmethod
    def _compute_bleu(references: list[str], hypotheses: list[str]) -> dict[str, float]:
        """Compute corpus BLEU-1/BLEU-4 via sacrebleu (normalized to 0-1)."""
        try:
            import sacrebleu
        except ImportError:
            logger.warning("sacrebleu is not installed; skipping BLEU metrics")
            return {}
        bleu_1 = sacrebleu.corpus_bleu(hypotheses, [references], weights=[1.0, 0.0, 0.0, 0.0])
        bleu_4 = sacrebleu.corpus_bleu(hypotheses, [references])
        return {"bleu_1": bleu_1.score / 100.0, "bleu_4": bleu_4.score / 100.0}

    @staticmethod
    def _compute_rouge_l(references: list[str], hypotheses: list[str]) -> dict[str, float]:
        """Compute mean ROUGE-L precision/recall/F1 via rouge-score."""
        try:
            from rouge_score import rouge_scorer
        except ImportError:
            logger.warning("rouge-score is not installed; skipping ROUGE-L metrics")
            return {}
        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        scores = [scorer.score(ref, hyp)["rougeL"] for ref, hyp in zip(references, hypotheses, strict=False)]
        count = max(1, len(scores))
        return {
            "rouge_l_precision": sum(s.precision for s in scores) / count,
            "rouge_l_recall": sum(s.recall for s in scores) / count,
            "rouge_l_f1": sum(s.fmeasure for s in scores) / count,
        }

    @staticmethod
    def _compute_bertscore(references: list[str], hypotheses: list[str]) -> dict[str, float]:
        """Compute mean BertScore F1 via bert-score."""
        try:
            from bert_score import score as bert_score
        except ImportError:
            logger.warning("bert-score is not installed; skipping BertScore metrics")
            return {}
        _precision, _recall, f1 = bert_score(hypotheses, references, lang="en", verbose=False)
        return {"bertscore_f1": float(f1.mean())}

    # ── Adapter persistence ────────────────────────────────────────────────

    def save_adapter(self, output_path: Any, model: Any = None) -> str:  # type: ignore[override]
        """Save LoRA adapter configuration and (mock) weights to disk."""
        out = Path(str(output_path))
        out.mkdir(parents=True, exist_ok=True)

        adapter_config = {
            "base_model_name_or_path": self.config.base_model,
            "lora_r": self.config.lora_r,
            "lora_alpha": self.config.lora_alpha,
            "lora_dropout": self.config.lora_dropout,
            "bias": "none",
            "task_type": "CAUSAL_LM",
            "peft_type": "LORA",
            "use_qlora": self.config.use_qlora,
            "load_in_4bit": self.config.load_in_4bit,
        }

        with open(out / "adapter_config.json", "w") as f:
            json.dump(adapter_config, f, indent=2)

        adapter_file = out / "adapter_model.safetensors"
        if not adapter_file.exists():
            try:
                import torch
                from safetensors.torch import save_file

                save_file({"mock": torch.zeros(1)}, str(adapter_file))
            except ImportError:
                adapter_file.write_text('{"__mock__": true}')

        return str(out)

    # ── Registry push ──────────────────────────────────────────────────────

    def push_to_registry(self, job: TrainingJob | None) -> str:
        if job is None:
            raise ValueError("No training job provided")
        return job.artifact_uri or job.job_id

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _make_job_id() -> str:
        return f"llm-{uuid.uuid4().hex[:12]}"
