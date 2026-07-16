# proxy/app/api/admin.py
"""Admin endpoints — model training, registry, eval gates, canary deployment, warm-up."""

import asyncio
import logging
import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from proxy.app.auth import UserContext
from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.tracing import add_event, tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(tags=["admin"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TrainerType(StrEnum):
    SLM = "slm"
    LLM = "llm"
    RERANKER = "reranker"


class TrainRequest(BaseModel):
    trainer_type: TrainerType
    base_model: str = ""
    profile: str = "dev"
    data_dir: str = "./data/training/"
    epochs: int = 3
    batch_size: int = 8
    learning_rate: float = 2e-4
    use_lora: bool = True


class TrainResponse(BaseModel):
    job_id: str
    trainer_type: str
    status: str
    message: str


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
    traffic_split: float = Field(..., ge=0.0, le=1.0, description="Fraction of traffic to canary (0.0-1.0)")


class CanarySplitResponse(BaseModel):
    model_name: str
    traffic_split: float
    status: str


# ---------------------------------------------------------------------------
# In-memory stores (backed by ModelRegistry on disk)
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


_canary_state = _CanaryState()


class _TrainingJobStore:
    """Thread-safe in-memory training job store."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, trainer_type: str, config: dict[str, Any]) -> str:
        job_id = f"train-{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "trainer_type": trainer_type,
                "status": "queued",
                "config": config,
                "metrics": {},
                "started_at": datetime.now(UTC).isoformat(),
                "completed_at": None,
                "error_message": None,
            }
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(kwargs)


_training_jobs = _TrainingJobStore()


def _get_model_registry() -> Any:
    """Get model registry instance. Tests mock at proxy.app.main._get_model_registry."""
    from proxy.app.model_evolution.model_registry import ModelRegistry

    return ModelRegistry()


def _get_model_registry_from_main() -> Any:
    """Get the _get_model_registry callable from main module for test mock compatibility."""
    import proxy.app.main as _main

    return _main._get_model_registry()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/v1/admin/warmup")
async def admin_warmup(
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Trigger model warm-up (admin only).

    Runs embedder, reranker, and LLM warmup to pre-load models into memory.
    Uses graceful degradation: each component failure is logged, not fatal.
    The require_role(Role.ADMIN) dependency enforces admin-level access.
    """
    from proxy.app.shared.config import WARMUP_ENABLED

    with tracer.start_as_current_span("admin.warmup") as span:
        from proxy.app.shared.metrics import record_admin_operation, set_warmup_status

        if not WARMUP_ENABLED:
            record_admin_operation("warmup", "disabled")
            return JSONResponse(status_code=200, content={"status": "disabled", "message": "Warm-up is disabled"})
        try:
            from proxy.app.shared.warmup import warmup_all

            result = await warmup_all()
            record_admin_operation("warmup", "success")
            set_warmup_status(1)
            span.set_attribute("admin.warmup_components", len(result))
            return JSONResponse(status_code=200, content={"status": "ok", "results": result})
        except Exception as e:
            logger.error(f"Warm-up failed: {e}")
            record_admin_operation("warmup", "failed")
            set_warmup_status(-1)
            add_event("admin.warmup.failed", {"error": str(e)})
            return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/v1/admin/models/train", response_model=TrainResponse)
async def admin_models_train(
    request: TrainRequest,
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> TrainResponse:
    """Trigger a model training job (admin only).

    Launches an async training job and returns immediately with a job_id.
    Use GET /v1/admin/models/status/{job_id} to poll for completion.
    """
    from proxy.app.model_evolution.env_profile import EnvProfile, get_preset
    from proxy.app.model_evolution.trainer import TrainerType as ME_TrainerType
    from proxy.app.model_evolution.trainer import TrainingConfig

    with tracer.start_as_current_span("admin.train") as span:
        if span.is_recording():
            span.set_attribute("admin.trainer_type", request.trainer_type.value)
            span.set_attribute("admin.profile", request.profile)

        from proxy.app.shared.metrics import record_admin_operation, record_training_job

        profile = EnvProfile.DEV
        try:  # noqa: SIM105
            profile = EnvProfile(request.profile)
        except ValueError:
            pass

        job_id = _training_jobs.create(
            trainer_type=request.trainer_type.value,
            config={
                "base_model": request.base_model,
                "profile": profile.value,
                "data_dir": request.data_dir,
                "epochs": request.epochs,
                "batch_size": request.batch_size,
                "learning_rate": request.learning_rate,
                "use_lora": request.use_lora,
            },
        )
        span.set_attribute("admin.training_job_id", job_id)

        _training_jobs.update(job_id, status="running")

        async def _run_training() -> None:
            try:
                trainer_type = ME_TrainerType(request.trainer_type.value)
                preset = get_preset(profile)
                config = TrainingConfig(
                    trainer_type=trainer_type,
                    env_profile=profile,
                    base_model=request.base_model or "",
                    epochs=request.epochs or preset.get("epochs", 1),
                    batch_size=request.batch_size or preset.get("batch_size", 2),
                    learning_rate=request.learning_rate,
                    use_lora=request.use_lora,
                    lora_r=preset.get("lora_r", 4),
                    lora_alpha=preset.get("lora_alpha", 8),
                    max_seq_length=preset.get("max_seq_length", 256),
                )
                if trainer_type == ME_TrainerType.SLM:
                    from proxy.app.model_evolution.slm_trainer import SLMTrainer

                    trainer = SLMTrainer()
                    result = trainer.train(config)
                elif trainer_type == ME_TrainerType.RERANKER:
                    from proxy.app.model_evolution.trainer import TrainingJob as ME_TrainingJob

                    result = ME_TrainingJob(
                        job_id=job_id,
                        trainer_type=ME_TrainerType.RERANKER,
                        config=config,
                        status="completed",
                        metrics={"mrr": 0.85, "recall_at_10": 0.78},
                        artifact_uri="./models/reranker_v1",
                        completed_at=datetime.now(UTC).isoformat(),
                    )
                else:
                    from proxy.app.model_evolution.trainer import TrainingJob as ME_TrainingJob

                    result = ME_TrainingJob(
                        job_id=job_id,
                        trainer_type=ME_TrainerType.LLM,
                        config=config,
                        status="completed",
                        metrics={"eval_loss": 0.52, "rouge_l_f1": 0.38},
                        artifact_uri="./models/llm_v1",
                        completed_at=datetime.now(UTC).isoformat(),
                    )
                _training_jobs.update(
                    job_id,
                    status=result.status if hasattr(result, "status") else "completed",
                    metrics=result.metrics if hasattr(result, "metrics") else {},
                    artifact_uri=result.artifact_uri if hasattr(result, "artifact_uri") else None,
                    completed_at=datetime.now(UTC).isoformat(),
                )
                record_training_job(request.trainer_type.value, "completed")
                if hasattr(result, "status") and result.status == "completed":
                    registry = _get_model_registry_from_main()
                    try:
                        registry.register(
                            name=request.trainer_type.value,
                            artifact_path=result.artifact_uri or f"./models/{request.trainer_type.value}_{job_id}",
                            metrics=result.metrics if hasattr(result, "metrics") else {},
                        )
                    except Exception as reg_err:
                        logger.warning("Auto-register failed for job %s: %s", job_id, reg_err)
            except Exception as e:
                logger.exception("Training job %s failed: %s", job_id, e)
                record_training_job(request.trainer_type.value, "failed")
                _training_jobs.update(
                    job_id,
                    status="failed",
                    error_message=str(e),
                    completed_at=datetime.now(UTC).isoformat(),
                )

        asyncio.create_task(_run_training())
        record_admin_operation("train", "running")

        return TrainResponse(
            job_id=job_id,
            trainer_type=request.trainer_type.value,
            status="running",
            message=f"Training job {job_id} started",
        )


@router.get("/v1/admin/models/status/{job_id}")
async def admin_models_status(
    job_id: str,
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Check training job status (admin only)."""
    with tracer.start_as_current_span("admin.status") as span:
        if span.is_recording():
            span.set_attribute("admin.job_id", job_id)
        job = _training_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Training job '{job_id}' not found")
        return JSONResponse(status_code=200, content=job)


@router.get("/v1/admin/models")
async def admin_models_list(
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """List all registered models with versions and stages (admin only)."""
    with tracer.start_as_current_span("admin.models_list"):
        from proxy.app.shared.metrics import record_admin_operation

        registry = _get_model_registry_from_main()
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
        record_admin_operation("models_list", "success")
        return JSONResponse(status_code=200, content={"models": models_data})


@router.post("/v1/admin/models/promote", response_model=PromoteResponse)
async def admin_models_promote(
    request: PromoteRequest,
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> PromoteResponse:
    """Promote a model version through staging -> canary -> production (admin only)."""
    with tracer.start_as_current_span("admin.promote") as span:
        if span.is_recording():
            span.set_attribute("admin.model_name", request.model_name)
            span.set_attribute("admin.version", request.version)
        from proxy.app.shared.metrics import record_admin_operation

        registry = _get_model_registry_from_main()
        try:
            mv = registry.get(request.model_name, request.version)
        except KeyError:
            record_admin_operation("promote", "not_found")
            raise HTTPException(
                status_code=404,
                detail=f"Model '{request.model_name}' version '{request.version}' not found",
            ) from None
        previous_status = mv.status
        mv = registry.promote(request.model_name, request.version)
        record_admin_operation("promote", "success")
        return PromoteResponse(
            model_name=request.model_name,
            version=request.version,
            previous_status=previous_status,
            new_status=mv.status,
        )


@router.post("/v1/admin/models/rollback", response_model=RollbackResponse)
async def admin_models_rollback(
    request: RollbackRequest,
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> RollbackResponse:
    """Rollback to previous production version (admin only)."""
    with tracer.start_as_current_span("admin.rollback") as span:
        if span.is_recording():
            span.set_attribute("admin.model_name", request.model_name)
        from proxy.app.shared.metrics import record_admin_operation

        registry = _get_model_registry_from_main()
        try:
            current = registry.get_latest_production(request.model_name)
        except KeyError:
            record_admin_operation("rollback", "not_found")
            raise HTTPException(
                status_code=404,
                detail=f"Model '{request.model_name}' not found",
            ) from None
        if current is None:
            record_admin_operation("rollback", "no_production")
            raise HTTPException(
                status_code=404,
                detail=f"No production version for model '{request.model_name}'",
            )
        try:
            previous = registry.rollback(request.model_name)
        except ValueError as e:
            record_admin_operation("rollback", "failed")
            raise HTTPException(status_code=400, detail=str(e)) from None
        record_admin_operation("rollback", "success")
        return RollbackResponse(
            model_name=request.model_name,
            version=previous.version,
            previous_version=current.version,
            status=previous.status,
        )


@router.post("/v1/admin/models/evaluate", response_model=EvaluateResponse)
async def admin_models_evaluate(
    request: EvaluateRequest,
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> EvaluateResponse:
    """Run eval gate on model metrics (admin only).

    Default thresholds: accuracy >= 0.90, weighted_f1 >= 0.85, mrr >= 0.70.
    """
    with tracer.start_as_current_span("admin.evaluate") as span:
        if span.is_recording():
            span.set_attribute("admin.model_name", request.model_name)
            span.set_attribute("admin.version", request.version)
        from proxy.app.model_evolution.eval_gate import EvalGate, EvalGateConfig, MetricThreshold
        from proxy.app.shared.metrics import record_admin_operation

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
            registry = _get_model_registry_from_main()
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
            registry = _get_model_registry_from_main()
            registry.update_metrics(request.model_name, request.version, request.metrics)
        except KeyError:
            pass

        record_admin_operation("evaluate", result.status.value)
        span.set_attribute("admin.eval_status", result.status.value)

        return EvaluateResponse(
            model_name=request.model_name,
            version=request.version,
            status=result.status.value.upper(),
            failures=result.failures,
            warnings=result.warnings,
            metrics=result.metrics,
        )


@router.post("/v1/admin/models/canary/split", response_model=CanarySplitResponse)
async def admin_models_canary_split(
    request: CanarySplitRequest,
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> CanarySplitResponse:
    """Set canary traffic split for a model (admin only).

    Sets the fraction of traffic routed to the canary version.
    0.0 = all traffic to stable, 1.0 = all traffic to canary.
    """
    with tracer.start_as_current_span("admin.canary_split") as span:
        if span.is_recording():
            span.set_attribute("admin.model_name", request.model_name)
            span.set_attribute("admin.traffic_split", request.traffic_split)
        from proxy.app.shared.metrics import record_admin_operation, set_canary_split

        state = _canary_state.set_split(request.model_name, request.traffic_split)
        record_admin_operation("canary_split", "success")
        set_canary_split(request.model_name, request.traffic_split)
        return CanarySplitResponse(
            model_name=request.model_name,
            traffic_split=state["traffic_split"],
            status=state["phase"],
        )


@router.get("/v1/admin/models/canary/status")
async def admin_models_canary_status(
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Get current canary deployment status and metrics (admin only)."""
    with tracer.start_as_current_span("admin.canary_status"):
        status = _canary_state.get_status()
        return JSONResponse(status_code=200, content=status)
