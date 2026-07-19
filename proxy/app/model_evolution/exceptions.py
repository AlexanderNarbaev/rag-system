"""Exception hierarchy for model evolution subsystem."""


class ModelEvolutionError(Exception):
    """Base exception for all model evolution errors."""


class TrainingError(ModelEvolutionError):
    """Errors during model training (data prep, GPU OOM, checkpoint failure)."""


class EvalGateError(ModelEvolutionError):
    """Errors from evaluation gates (threshold not met, baseline regression)."""


class AdapterError(ModelEvolutionError):
    """Errors from model adapters (load failure, version mismatch, memory error)."""


class CanaryError(ModelEvolutionError):
    """Errors from canary deployment (rollback failure, metric unavailability)."""
