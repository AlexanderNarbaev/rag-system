# model_evolution_service/main.py
"""FastAPI application for the Model Evolution service.

Provides endpoints for model training, registry management, evaluation,
and canary deployment as an independent microservice.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from model_evolution_service.api.health import router as health_router
from model_evolution_service.api.models import router as models_router
from model_evolution_service.api.training import router as training_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("model-evolution")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle."""
    logger.info("Starting Model Evolution service...")
    yield
    logger.info("Model Evolution service shutdown")


app = FastAPI(
    title="Model Evolution Service",
    description=(
        "Standalone service for model training, fine-tuning, evaluation, and deployment.\n\n"
        "## Features\n"
        "- **Training** — SLM LoRA, LLM QLoRA, Reranker fine-tuning\n"
        "- **Evaluation** — Eval gates, NLI-based grounding, metrics generation\n"
        "- **Deployment** — Hot-reload adapters, canary traffic splitting, model registry\n"
        "- **Experiment Tracking** — MLflow integration with local fallback\n\n"
        "## Endpoints\n"
        "- `POST /v1/admin/models/train` — trigger training job\n"
        "- `GET /v1/admin/models/status/{job_id}` — poll training status\n"
        "- `GET /v1/admin/models` — list registered models\n"
        "- `POST /v1/admin/models/promote` — promote model version\n"
        "- `POST /v1/admin/models/rollback` — rollback model version\n"
        "- `POST /v1/admin/models/evaluate` — evaluate model metrics\n"
        "- `GET /health` — health check"
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "health", "description": "Health and readiness probes"},
        {"name": "training", "description": "Model training job management"},
        {"name": "models", "description": "Model registry and lifecycle"},
    ],
)

# Include routers
app.include_router(health_router)
app.include_router(training_router)
app.include_router(models_router)
