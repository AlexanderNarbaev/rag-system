# proxy/app/api/metrics.py
"""Prometheus metrics endpoint for monitoring and observability."""

from fastapi import APIRouter
from fastapi.responses import Response

from proxy.app.shared.metrics import metrics_endpoint

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics in OpenMetrics text format.

    Returns:
        Response containing all registered counters, histograms, and gauges
        in Prometheus exposition format.

    """
    return metrics_endpoint()
