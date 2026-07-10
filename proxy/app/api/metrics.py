# proxy/app/api/metrics.py
"""Prometheus metrics endpoint."""

from fastapi import APIRouter

from proxy.app.shared.metrics import metrics_endpoint

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics():
    return metrics_endpoint()
