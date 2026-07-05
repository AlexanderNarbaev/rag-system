"""Training orchestration — base classes, config, job tracking, and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any

from proxy.app.model_evolution.env_profile import EnvProfile, get_preset


class TrainerType(Enum):
    SLM = "slm"
    LLM = "llm"
    RERANKER = "reranker"


@dataclass
class TrainingConfig:
    trainer_type: TrainerType
    env_profile: EnvProfile = EnvProfile.DEV
    base_model: str = ""
    output_dir: str = "./models/training"
    epochs: int = 3
    batch_size: int = 8
    learning_rate: float = 2e-4
    eval_split: float = 0.2
    max_seq_length: int = 512
    use_lora: bool = True
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    use_qlora: bool = False
    load_in_4bit: bool = False
    bnb_4bit_compute_dtype: str = "float16"
    warmup_steps: int = 100
    logging_steps: int = 10
    save_steps: int = 500
    eval_steps: int = 500
    seed: int = 42

    @classmethod
    def from_profile(cls, trainer_type: TrainerType, profile: EnvProfile, **overrides: Any) -> TrainingConfig:
        preset = get_preset(profile)
        preset.update(overrides)
        field_names = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in preset.items() if k in field_names}
        return cls(trainer_type=trainer_type, env_profile=profile, **filtered)


@dataclass
class TrainingJob:
    job_id: str
    trainer_type: TrainerType
    config: TrainingConfig
    status: str = "pending"
    mlflow_run_id: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    artifact_uri: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "trainer_type": self.trainer_type.value,
            "config": {
                "trainer_type": self.config.trainer_type.value,
                "env_profile": self.config.env_profile.value,
                "base_model": self.config.base_model,
                "output_dir": self.config.output_dir,
                "epochs": self.config.epochs,
                "batch_size": self.config.batch_size,
                "learning_rate": self.config.learning_rate,
                "eval_split": self.config.eval_split,
                "max_seq_length": self.config.max_seq_length,
                "use_lora": self.config.use_lora,
                "lora_r": self.config.lora_r,
                "lora_alpha": self.config.lora_alpha,
                "lora_dropout": self.config.lora_dropout,
                "use_qlora": self.config.use_qlora,
                "load_in_4bit": self.config.load_in_4bit,
                "seed": self.config.seed,
            },
            "status": self.status,
            "mlflow_run_id": self.mlflow_run_id,
            "metrics": self.metrics,
            "artifact_uri": self.artifact_uri,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error_message": self.error_message,
        }


class TrainerBase(ABC):
    @abstractmethod
    def prepare_data(self, *args: Any, **kwargs: Any) -> Any: ...

    @abstractmethod
    def train(self, config: TrainingConfig) -> TrainingJob: ...

    @abstractmethod
    def evaluate(self, model: Any, eval_data: Any) -> dict[str, float]: ...

    def save_adapter(self, model: Any, output_path: str) -> str:
        raise NotImplementedError("Subclasses must implement save_adapter")


class TrainerRegistry:
    _instance: TrainerRegistry | None = None

    def __new__(cls) -> TrainerRegistry:
        if cls._instance is None:
            instance = super().__new__(cls)
            object.__setattr__(instance, "_registry", {})
            cls._instance = instance
        return cls._instance

    def register(self, trainer_type: TrainerType, trainer_cls: type[TrainerBase]) -> None:
        self._registry[trainer_type] = trainer_cls  # type: ignore[attr-defined]

    def get(self, trainer_type: TrainerType) -> type[TrainerBase]:
        if trainer_type not in self._registry:  # type: ignore[attr-defined]
            raise KeyError(f"No trainer registered for type: {trainer_type}")
        return self._registry[trainer_type]  # type: ignore[attr-defined]

    def list_types(self) -> list[TrainerType]:
        return list(self._registry.keys())  # type: ignore[attr-defined]

    def get_instance(self, trainer_type: TrainerType) -> TrainerBase:
        trainer_cls = self.get(trainer_type)
        return trainer_cls()
