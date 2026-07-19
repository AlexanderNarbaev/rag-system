# model_evolution_service/api/models.py
"""Model registry and lifecycle management endpoints."""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("model-evolution")

router = APIRouter(tags=["models"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PromoteRequest(BaseModel):
    model_name: str
    version: str


class PromoteResponse(BaseModel):
    model_name: str
    version: str
    previous_status: str
    new_status: str


class RollbackRequest(BaseModel):
    model_name: str


class RollbackResponse(BaseModel):
    model_name: str
    version: str
    previous_version: str
    status: str


class EvaluateRequest(BaseModel):
    model_name: str
    version: str = "unknown"
    metrics: dict[str, float]


class EvaluateResponse(BaseModel):
    model_name: str
    version: str
    status: str
    failures: list[str]
    warnings: list[str]
    metrics: dict[str, float]


class CanarySplitRequest(BaseModel):
    model_name: str
    traffic_split: float


class CanarySplitResponse(BaseModel):
    model_name: str
    traffic_split: float
    status: str


# ---------------------------------------------------------------------------
# In-memory canary state
# ---------------------------------------------------------------------------


class _CanaryState:
    """Thread-safe in-memory canary deployment state manager."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._models: dict[str, dict[str, Any]] = {}

    def set_split(self, model_name: str, traffic_split: float) -> dict[str, Any]:
        with self._lock:
            if model_name not in self._models:
                self._models[model_name] = {
                    "traffic_split": 0.0,
                    "stable_traffic": 1.0,
                    "phase": "idle",
                    "stable_version": None,
                    "canary_version": None,
                }
            entry = self._models[model_name]
            entry["traffic_split"] = traffic_split
            entry["stable_traffic"] = 1.0 - traffic_split
            if traffic_split > 0:
                entry["phase"] = "ramp"
            else:
                entry["phase"] = "idle"
            return dict(entry)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            result: dict[str, dict[str, float | str | None]] = {}
            for name, entry in self._models.items():
                result[name] = dict(entry)
            return {"canary_models": result}


canary_state = _CanaryState()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/admin/models")
async def admin_models_list() -> dict[str, Any]:
    """List all registered models with versions and stages."""
    from model_evolution_service.deployment.model_registry import ModelRegistry

    registry = ModelRegistry()
    models_data = {}
    for model_name in registry.list_models():
        versions = registry.list_versions(model_name)
        production = registry.get_latest_production(model_name)
        models_data[model_name] = {
            "versions": [
                {
                    "version": v.version,
                    "status": v.status,
                    "artifact_path": v.artifact_path,
                    "metrics": v.metrics,
                    "created_at": v.created_at,
                }
                for v in versions
            ],
            "production_version": production.version if production else None,
        }
    return {"models": models_data}


@router.post("/v1/admin/models/promote", response_model=PromoteResponse)
async def admin_models_promote(request: PromoteRequest) -> PromoteResponse:
    """Promote a model version through staging -> canary -> production."""
    from model_evolution_service.deployment.model_registry import ModelRegistry

    registry = ModelRegistry()
    try:
        mv = registry.get(request.model_name, request.version)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{request.model_name}' version '{request.version}' not found",
        ) from None
    previous_status = mv.status
    mv = registry.promote(request.model_name, request.version)
    return PromoteResponse(
        model_name=request.model_name,
        version=request.version,
        previous_status=previous_status,
        new_status=mv.status,
    )


@router.post("/v1/admin/models/rollback", response_model=RollbackResponse)
async def admin_models_rollback(request: RollbackRequest) -> RollbackResponse:
    """Rollback to previous production version."""
    from model_evolution_service.deployment.model_registry import ModelRegistry

    registry = ModelRegistry()
    try:
        current = registry.get_latest_production(request.model_name)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{request.model_name}' not found",
        ) from None
    if current is None:
        raise HTTPException(
            status_code=404,
            detail=f"No production version for model '{request.model_name}'",
        )
    try:
        previous = registry.rollback(request.model_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Rollback failed") from None
    return RollbackResponse(
        model_name=request.model_name,
        version=previous.version,
        previous_version=current.version,
        status=previous.status,
    )


@router.post("/v1/admin/models/evaluate", response_model=EvaluateResponse)
async def admin_models_evaluate(request: EvaluateRequest) -> EvaluateResponse:
    """Run eval gate on model metrics.

    Default thresholds: accuracy >= 0.90, weighted_f1 >= 0.85, mrr >= 0.70.
    """
    from model_evolution_service.deployment.model_registry import ModelRegistry
    from model_evolution_service.evaluation.eval_gate import EvalGate, EvalGateConfig, MetricThreshold

    thresholds = [
        MetricThreshold("accuracy", 0.90, "gte"),
        MetricThreshold("weighted_f1", 0.85, "gte"),
        MetricThreshold("mrr", 0.70, "gte"),
        MetricThreshold("recall_at_10", 0.65, "gte"),
        MetricThreshold("rouge_l_f1", 0.35, "gte"),
        MetricThreshold("eval_loss", 1.0, "lte", severity="warn"),
    ]
    config = EvalGateConfig(
        model_name=request.model_name,
        thresholds=thresholds,
        require_baseline_comparison=False,
    )

    baseline_metrics = None
    try:
        registry = ModelRegistry()
        production = registry.get_latest_production(request.model_name)
        if production:
            baseline_metrics = production.metrics
    except Exception:
        pass

    result = EvalGate.evaluate(
        metrics=request.metrics,
        config=config,
        baseline_metrics=baseline_metrics,
        version=request.version,
    )

    try:
        registry = ModelRegistry()
        registry.update_metrics(request.model_name, request.version, request.metrics)
    except KeyError:
        pass

    return EvaluateResponse(
        model_name=request.model_name,
        version=request.version,
        status=result.status.value.upper(),
        failures=result.failures,
        warnings=result.warnings,
        metrics=result.metrics,
    )


@router.post("/v1/admin/models/canary/split", response_model=CanarySplitResponse)
async def admin_models_canary_split(request: CanarySplitRequest) -> CanarySplitResponse:
    """Set canary traffic split for a model."""
    state = canary_state.set_split(request.model_name, request.traffic_split)
    return CanarySplitResponse(
        model_name=request.model_name,
        traffic_split=state["traffic_split"],
        status=state["phase"],
    )


@router.get("/v1/admin/models/canary/status")
async def admin_models_canary_status() -> dict[str, Any]:
    """Get current canary deployment status and metrics."""
    return canary_state.get_status()
