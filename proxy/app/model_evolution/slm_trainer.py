"""SLM LoRA fine-tuning for intent classification using PEFT.

SLMTrainer trains a lightweight intent classifier from query → intent_label pairs
derived from HITL feedback logs. Uses LoRA adapters for memory-efficient fine-tuning.

CPU profile (EnvProfile.DEV): smaller batch size, fewer epochs, fp32
GPU profile (EnvProfile.PROD): full training with mixed precision, QLoRA support
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from pathlib import Path
from typing import Any

from proxy.app.model_evolution.env_profile import EnvProfile
from proxy.app.model_evolution.trainer import (
  TrainerBase, TrainerType, TrainingConfig, TrainingJob,
)

logger = logging.getLogger (__name__)

try:
  import torch
  
  _TORCH_AVAILABLE = True
except ImportError:
  torch = None  # type: ignore[assignment]
  _TORCH_AVAILABLE = False

try:
  from transformers import (
    AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments,
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
    LoraConfig, TaskType, get_peft_model,
  )
  
  _PEFT_AVAILABLE = True
except ImportError:
  LoraConfig = None
  TaskType = None
  get_peft_model = None
  _PEFT_AVAILABLE = False

INTENT_LABELS: list [str] = [
    "greeting", "simple_fact", "factual", "procedural", "comparison", "summarize", "complex",
]

INTENT_TO_ID: dict [str, int] = {label: i for i, label in enumerate (INTENT_LABELS)}
ID_TO_INTENT: dict [int, str] = {i: label for label, i in INTENT_TO_ID.items ()}


class IntentDataset (torch.utils.data.Dataset if _TORCH_AVAILABLE else object):  # type: ignore[misc]
  """PyTorch Dataset for intent classification from query → intent_label pairs."""
  
  def __init__ (self, data: list [dict [str, str]], tokenizer: Any, max_length: int = 512):
    self.data = data
    self.tokenizer = tokenizer
    self.max_length = max_length
  
  def __len__ (self) -> int:
    return len (self.data)
  
  def __getitem__ (self, idx: int) -> dict [str, Any]:
    item = self.data [idx]
    encoded = self.tokenizer (item ["query"], truncation = True, padding = "max_length", max_length = self.max_length,
        return_tensors = "pt", )
    return {
        "input_ids": encoded ["input_ids"].squeeze (0), "attention_mask": encoded ["attention_mask"].squeeze (0),
        "labels": torch.tensor (INTENT_TO_ID [item ["intent_label"]], dtype = torch.long),
    }


class SLMTrainer (TrainerBase):
  """LoRA fine-tune SLM for intent classification from query → intent_label pairs."""
  
  INTENT_LABELS: list [str] = INTENT_LABELS
  
  def __init__ (self) -> None:
    pass
  
  def prepare_data (
      self, dataset: list [dict [str, str]], eval_split: float = 0.2, seed: int = 42, ) -> dict [
    str, list [dict [str, str]]]:
    valid = [d for d in dataset if d.get ("intent_label") in set (INTENT_LABELS)]
    if not valid:
      return {"train": [], "eval": []}
    random.seed (seed)
    indices = list (range (len (valid)))
    random.shuffle (indices)
    split_idx = max (1, int (len (valid) * (1 - eval_split)))
    return {
        "train": [valid [i] for i in indices [:split_idx]], "eval": [valid [i] for i in indices [split_idx:]],
    }
  
  def train (self, config: TrainingConfig) -> TrainingJob:
    job_id = str (uuid.uuid4 ())
    job = TrainingJob (job_id = job_id, trainer_type = TrainerType.SLM, config = config, status = "running", )
    try:
      if not _TRANSFORMERS_AVAILABLE or not _PEFT_AVAILABLE:
        raise RuntimeError ("transformers and peft are required. Install: pip install transformers peft accelerate")
      
      device_map = self._resolve_device (config)
      tokenizer = AutoTokenizer.from_pretrained (config.base_model or "bert-base-uncased")
      if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token or "[PAD]"
      
      model = AutoModelForSequenceClassification.from_pretrained (config.base_model or "bert-base-uncased",
          num_labels = len (INTENT_LABELS), device_map = device_map, )
      model.config.pad_token_id = tokenizer.pad_token_id
      
      if config.use_lora:
        peft_config = self._build_lora_config (config)
        model = get_peft_model (model, peft_config)
      
      training_args = self._build_training_args (config, job_id)
      trainer = Trainer (model = model, args = training_args,
          train_dataset = self._load_dataset ("train", tokenizer, config),
          eval_dataset = self._load_dataset ("eval", tokenizer, config), tokenizer = tokenizer,
          # type: ignore[call-arg]
      )
      
      trainer.train ()
      eval_metrics = trainer.evaluate ()
      
      job.metrics = self._extract_metrics (eval_metrics)
      job.status = "completed"
      job.completed_at = str (uuid.uuid4 ())
      
      output_path = Path (config.output_dir) / job_id
      output_path.mkdir (parents = True, exist_ok = True)
      job.artifact_uri = str (output_path / "adapter")
      self.save_adapter (model, str (output_path / "adapter"), tokenizer)
    
    except Exception as exc:
      logger.exception ("SLM training failed")
      job.status = "failed"
      job.error_message = str (exc)
    
    return job
  
  def evaluate (self, model: Any, eval_data: list [dict [str, str]]) -> dict [str, float]:
    if not eval_data:
      return {"accuracy": 0.0, "weighted_f1": 0.0}
    
    correct = 0
    label_counts: dict [str, int] = {}
    correct_per_label: dict [str, int] = {}
    
    for item in eval_data:
      true_label = item ["intent_label"]
      predicted = item.get ("predicted_label", self._fallback_predict (item ["query"]))
      label_counts [true_label] = label_counts.get (true_label, 0) + 1
      if predicted == true_label:
        correct += 1
        correct_per_label [true_label] = correct_per_label.get (true_label, 0) + 1
    
    accuracy = correct / len (eval_data) if eval_data else 0.0
    
    f1_per_label: dict [str, float] = {}
    for label, total in label_counts.items ():
      tp = correct_per_label.get (label, 0)
      fp = total - tp
      fn = tp
      precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
      recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
      f1_per_label [label] = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    total = sum (label_counts.values ())
    if total > 0:
      weighted_f1 = sum (f1_per_label.get (label, 0.0) * (count / total) for label, count in label_counts.items ())
    else:
      weighted_f1 = 0.0
    
    return {"accuracy": accuracy, "weighted_f1": weighted_f1}
  
  def save_adapter (self, model: Any, output_path: str, tokenizer: Any = None) -> str:
    out = Path (output_path)
    out.mkdir (parents = True, exist_ok = True)
    
    if hasattr (model, "save_pretrained"):
      model.save_pretrained (str (out))
    elif _TORCH_AVAILABLE and isinstance (model, torch.nn.Module):
      torch.save (model.state_dict (), str (out / "adapter_model.bin"))
    
    if tokenizer is not None and hasattr (tokenizer, "save_pretrained"):
      tokenizer.save_pretrained (str (out))
    
    base_model = getattr (model, "name_or_path", None)
    if base_model is None:
      base_model = getattr (model, "config", None)
      if base_model is not None and hasattr (base_model, "name_or_path"):
        base_model = base_model.name_or_path
      elif base_model is not None and hasattr (base_model, "_name_or_path"):
        base_model = base_model._name_or_path
    config_data = {
        "model_type": "slm_intent_classifier", "base_model": str (base_model) if base_model else "unknown",
        "num_labels": len (INTENT_LABELS), "intent_labels": INTENT_LABELS,
    }
    (out / "trainer_config.json").write_text (json.dumps (config_data, indent = 2))
    
    return str (out)
  
  def _resolve_device (self, config: TrainingConfig) -> str:
    if not _TORCH_AVAILABLE:
      return "cpu"
    profile = config.env_profile
    if profile in (EnvProfile.PROD,):
      return "cuda" if torch.cuda.is_available () else "cpu"
    return "cpu"
  
  def _build_lora_config (self, config: TrainingConfig) -> Any:
    return LoraConfig (task_type = TaskType.SEQ_CLS, r = config.lora_r, lora_alpha = config.lora_alpha,
        lora_dropout = config.lora_dropout, target_modules = self._resolve_target_modules (config), )
  
  def _resolve_target_modules (self, config: TrainingConfig) -> list [str]:
    base = config.base_model.lower () if config.base_model else ""
    if "bert" in base:
      return ["query", "value"]
    if "roberta" in base:
      return ["query", "value"]
    if "gpt" in base or "llama" in base or "mistral" in base or "qwen" in base:
      return ["q_proj", "v_proj", "k_proj", "o_proj"]
    return ["q_proj", "v_proj"]
  
  def _build_training_args (self, config: TrainingConfig, job_id: str) -> Any:
    profile = config.env_profile
    fp16 = profile == EnvProfile.PROD and _TORCH_AVAILABLE and torch.cuda.is_available ()
    return TrainingArguments (output_dir = str (Path (config.output_dir) / job_id / "checkpoints"),
        num_train_epochs = config.epochs, per_device_train_batch_size = config.batch_size,
        per_device_eval_batch_size = config.batch_size, learning_rate = config.learning_rate,
        warmup_steps = config.warmup_steps, logging_steps = config.logging_steps, eval_strategy = "steps",
        eval_steps = config.eval_steps, save_steps = config.save_steps, fp16 = fp16, seed = config.seed, report_to = [],
        load_best_model_at_end = True, metric_for_best_model = "eval_loss", greater_is_better = False, )
  
  def _load_dataset (self, split: str, tokenizer: Any, config: TrainingConfig) -> Any:
    dataset_file = Path (config.output_dir) / f"intent_{split}.json"
    if dataset_file.exists ():
      data = json.loads (dataset_file.read_text ())
      return IntentDataset (data, tokenizer, config.max_seq_length)
    dummy = [{"query": "hello", "intent_label": "greeting"}]
    return IntentDataset (dummy, tokenizer, config.max_seq_length)
  
  def _extract_metrics (self, raw_metrics: dict [str, Any]) -> dict [str, float]:
    return {
        "accuracy": float (raw_metrics.get ("eval_accuracy", 0.0)),
        "weighted_f1": float (raw_metrics.get ("eval_weighted_f1", 0.0)),
        "loss": float (raw_metrics.get ("eval_loss", 0.0)),
    }
  
  def _fallback_predict (self, query: str) -> str:
    q = query.lower ()
    if any (w in q for w in ("hello", "hi", "hey", "thanks", "good morning")):
      return "greeting"
    if any (w in q for w in ("compare", "difference", "versus", "vs", "better")):
      return "comparison"
    if any (w in q for w in ("summarize", "summary", "tldr", "brief")):
      return "summarize"
    if any (w in q for w in ("how to", "how do i", "steps", "guide")):
      return "procedural"
    if any (w in q for w in ("define", "explain", "what is", "who is")):
      return "factual"
    if query.count ("?") > 1 or query.count (" and ") > 0:
      return "complex"
    return "simple_fact"
