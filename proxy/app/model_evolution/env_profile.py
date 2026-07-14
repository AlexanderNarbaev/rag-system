"""Environment profiles for model training (dev/prod/ci)."""

from enum import Enum
from typing import Any


class EnvProfile (Enum):
  """Training environment profile."""
  
  DEV = "dev"  # CPU only, small batch, fp32
  PROD = "prod"  # GPU, full batch, bf16
  CI = "ci"  # No GPU, smoke test, 1 epoch


_PRESETS: dict [EnvProfile, dict [str, Any]] = {
    EnvProfile.DEV: {
        "gpu_enabled": False, "epochs": 1, "batch_size": 2, "use_lora": True, "lora_r": 4, "lora_alpha": 8,
        "use_qlora": False, "load_in_4bit": False, "max_seq_length": 256, "eval_split": 0.2, "logging_steps": 5,
        "eval_steps": 50,
    }, EnvProfile.PROD: {
        "gpu_enabled": True, "epochs": 5, "batch_size": 16, "use_lora": True, "lora_r": 16, "lora_alpha": 32,
        "use_qlora": True, "load_in_4bit": True, "bnb_4bit_compute_dtype": "bfloat16", "max_seq_length": 2048,
        "eval_split": 0.2, "warmup_steps": 100, "logging_steps": 10, "eval_steps": 500, "save_steps": 500,
    }, EnvProfile.CI: {
        "gpu_enabled": False, "epochs": 1, "batch_size": 1, "use_lora": True, "lora_r": 2, "lora_alpha": 4,
        "use_qlora": False, "load_in_4bit": False, "max_seq_length": 128, "eval_split": 0.5, "logging_steps": 1,
        "eval_steps": 10,
    },
}


def get_preset (profile: EnvProfile) -> dict [str, Any]:
  """Return the training preset for a given environment profile."""
  return dict (_PRESETS [profile])


def get_profile (name: str) -> EnvProfile:
  """Resolve a profile name string to an EnvProfile enum value.

  Defaults to DEV for unknown names.
  """
  name_lower = name.lower ()
  for profile in EnvProfile:
    if profile.value == name_lower:
      return profile
  return EnvProfile.DEV
