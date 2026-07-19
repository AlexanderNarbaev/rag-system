# model_evolution_service/api/health.py
"""Health check endpoints for the Model Evolution service."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "model-evolution"
    version: str = "1.0.0"


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse()
