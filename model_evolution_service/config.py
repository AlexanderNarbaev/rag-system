# model_evolution_service/config.py
"""Configuration for the Model Evolution service.

Merges env_profile.py (training presets) with service-level configuration
(MLflow, MinIO, training parameters).
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any

from pydantic_settings import BaseSettings


class EnvProfile(Enum):
    """Training environment profile."""

    DEV = "dev"  # CPU only, small batch, fp32
    PROD = "prod"  # GPU, full batch, bf16
    CI = "ci"  # No GPU, smoke test, 1 epoch


_PRESETS: dict[EnvProfile, dict[str, Any]] = {
    EnvProfile.DEV: {
        "gpu_enabled": False,
        "epochs": 1,
        "batch_size": 2,
        "use_lora": True,
        "lora_r": 4,
        "lora_alpha": 8,
        "use_qlora": False,
        "load_in_4bit": False,
        "max_seq_length": 256,
        "eval_split": 0.2,
        "logging_steps": 5,
        "eval_steps": 50,
    },
    EnvProfile.PROD: {
        "gpu_enabled": True,
        "epochs": 5,
        "batch_size": 16,
        "use_lora": True,
        "lora_r": 16,
        "lora_alpha": 32,
        "use_qlora": True,
        "load_in_4bit": True,
        "bnb_4bit_compute_dtype": "bfloat16",
        "max_seq_length": 2048,
        "eval_split": 0.2,
        "warmup_steps": 100,
        "logging_steps": 10,
        "eval_steps": 500,
        "save_steps": 500,
    },
    EnvProfile.CI: {
        "gpu_enabled": False,
        "epochs": 1,
        "batch_size": 1,
        "use_lora": True,
        "lora_r": 2,
        "lora_alpha": 4,
        "use_qlora": False,
        "load_in_4bit": False,
        "max_seq_length": 128,
        "eval_split": 0.5,
        "logging_steps": 1,
        "eval_steps": 10,
    },
}


def get_preset(profile: EnvProfile) -> dict[str, Any]:
    """Return the training preset for a given environment profile."""
    return dict(_PRESETS[profile])


def get_profile(name: str) -> EnvProfile:
    """Resolve a profile name string to an EnvProfile enum value.

    Defaults to DEV for unknown names.
    """
    name_lower = name.lower()
    for profile in EnvProfile:
        if profile.value == name_lower:
            return profile
    return EnvProfile.DEV


class Settings(BaseSettings):
    """Service-level configuration loaded from environment variables."""

    # Service
    host: str = "0.0.0.0"
    port: int = 8090
    log_level: str = "INFO"

    # MLflow
    mlflow_tracking_uri: str | None = os.getenv("MLFLOW_TRACKING_URI")
    mlflow_experiment_name: str = "model-evolution"

    # MinIO / S3
    minio_endpoint: str | None = os.getenv("MINIO_ENDPOINT")
    minio_access_key: str | None = os.getenv("MINIO_ACCESS_KEY")
    minio_secret_key: str | None = os.getenv("MINIO_SECRET_KEY")
    minio_bucket: str = "rag-artifacts"
    minio_secure: bool = False

    # Model registry
    model_registry_path: str = os.getenv("MODEL_REGISTRY_PATH", "./data/model_registry.json")

    # Training defaults
    default_output_dir: str = "./models/training"
    default_env_profile: str = "dev"

    # Proxy callback (for backward compatibility)
    proxy_url: str | None = os.getenv("RAG_PROXY_URL")

    model_config = {"env_prefix": "MODEL_EVOLUTION_"}


settings = Settings()
