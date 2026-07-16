"""Model Evolution package — fine-tuning, eval gates, hot-reload, canary deployment."""

from proxy.app.model_evolution.env_profile import (
    EnvProfile,
    get_preset,
    get_profile,
)
from proxy.app.model_evolution.eval_gate import (
    EvalGate,
    EvalGateConfig,
    GateResult,
    GateStatus,
    MetricThreshold,
)
from proxy.app.model_evolution.exceptions import (
    AdapterError,
    EvalGateError,
    ModelEvolutionError,
    TrainingError,
)
from proxy.app.model_evolution.nli_evaluator import (
    NLIEvaluationResult,
    evaluate_nli,
    evaluate_nli_batch,
    is_nli_model_available,
)
from proxy.app.model_evolution.trainer_base import (
    TrainerBase,
    TrainerRegistry,
    TrainingJob,
    TrainingStatus,
)

__all__ = [
    "AdapterError",
    "EnvProfile",
    "EvalGate",
    "EvalGateConfig",
    "EvalGateError",
    "GateResult",
    "GateStatus",
    "MetricThreshold",
    "ModelEvolutionError",
    "NLIEvaluationResult",
    "TrainerBase",
    "TrainerRegistry",
    "TrainingError",
    "TrainingJob",
    "TrainingStatus",
    "evaluate_nli",
    "evaluate_nli_batch",
    "get_preset",
    "get_profile",
    "is_nli_model_available",
]
