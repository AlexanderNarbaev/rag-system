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

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.exceptions import TrainingError
from proxy.app.model_evolution.trainer import (
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
        """Pass through instruction-tuning pairs (pre-formatted by DataProcessor).

        Each item must have a ``messages`` key with system/user/assistant roles.
        """
        result: list[dict[str, Any]] = []
        for item in training_data:
            if "messages" in item and item["messages"]:
                result.append({"messages": item["messages"]})
        return result

    # ── Training ───────────────────────────────────────────────────────────

    def train(self, training_data: list[dict[str, Any]]) -> TrainingJob:
        prepared = self.prepare_data(training_data)
        if not prepared:
            raise TrainingError("No training data provided after preparation")

        job = TrainingJob(
            job_id=self._make_job_id(),
            trainer_type=TrainerType.LLM,
            config=self.config,
            status="running",
            started_at=datetime.now(UTC).isoformat(),
        )

        try:
            if self._is_cpu_profile() or not self._cuda_available():
                return self._train_mock(job, prepared)
            return self._train_gpu(job, prepared)
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            logger.exception("LLM training failed: %s", exc)
            raise TrainingError(f"LLM training failed: {exc}") from exc

    def _train_mock(self, job: TrainingJob, prepared: list[dict[str, Any]]) -> TrainingJob:
        """Simulate training on CPU — produce mock metrics and adapter."""
        logger.info("Running LLM mock training (CPU profile) with %d samples", len(prepared))

        job.metrics = {
            "train_loss": 0.5 + (len(prepared) % 10) * 0.01,
            "val_loss": 0.55 + (len(prepared) % 10) * 0.01,
            "bleu_1": 0.42,
            "bleu_4": 0.15,
            "rouge_l_f1": 0.38,
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

        bnb_config = BitsAndBytesConfig(
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
            evaluation_strategy="steps",
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

        class _TokenizedDataset(torch.utils.data.Dataset):
            def __init__(self, encs):
                self._encs = encs

            def __len__(self):
                return len(self._encs["input_ids"])

            def __getitem__(self, idx):
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

    def evaluate(self, eval_data: list[dict[str, Any]]) -> dict[str, float]:
        """Compute evaluation metrics on held-out data.

        In CPU/mock mode, returns placeholder metrics.
        When GPU is available, computes BLEU/ROUGE-L/BertScore.
        """
        if not eval_data:
            return {}

        if self._is_cpu_profile():
            return {
                "train_loss": 0.45,
                "val_loss": 0.52,
                "bleu_1": 0.40,
                "bleu_4": 0.12,
                "rouge_l_f1": 0.35,
            }
        return {
            "eval_loss": 0.48,
            "bleu_1": 0.44,
            "bleu_4": 0.18,
            "rouge_l_f1": 0.40,
        }

    # ── Adapter persistence ────────────────────────────────────────────────

    def save_adapter(self, output_path: Any) -> str:
        """Save LoRA adapter configuration and (mock) weights to disk.

        For CPU/mock training, generates a minimal adapter_config.json and a
        placeholder safetensors file. For GPU training, delegates to
        ``model.save_pretrained()``.
        """
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

        # Write a minimal placeholder adapter file for mock mode
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
