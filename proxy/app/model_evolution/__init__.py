"""Model Evolution package — fine-tuning, eval gates, hot-reload, canary deployment."""

from proxy.app.model_evolution.env_profile import (
    EnvProfile,
    get_preset,
    get_profile,
)
from proxy.app.model_evolution.exceptions import (
    AdapterError,
    EvalGateError,
    ModelEvolutionError,
    TrainingError,
)
from proxy.app.model_evolution.trainer_base import (
    TrainerBase,
    TrainerRegistry,
    TrainingJob,
    TrainingStatus,
)
from proxy.app.model_evolution.eval_gate import (
    EvalGate,
    EvalGateConfig,
    GateResult,
    GateStatus,
    MetricThreshold,
)

__all__ = [
    "ModelEvolutionError",
    "TrainingError",
    "EvalGateError",
    "AdapterError",
    "EnvProfile",
    "get_preset",
    "get_profile",
    "TrainerBase",
    "TrainerRegistry",
    "TrainingJob",
    "TrainingStatus",
    "EvalGate",
    "EvalGateConfig",
    "GateResult",
    "GateStatus",
    "MetricThreshold",
]
