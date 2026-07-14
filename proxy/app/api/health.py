# proxy/app/api/health.py
"""Health check endpoints — liveness, readiness, and component status."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from proxy.app.shared.config import LLM_ENDPOINT

logger = logging.getLogger ("rag-proxy")

router = APIRouter (tags = ["health"])


@router.get ("/v1/health")
async def health () -> JSONResponse:
  """Check proxy and dependency health."""
  status: dict [str, Any] = {"status": "ok", "timestamp": datetime.now (UTC).isoformat (), "components": {}}
  try:
    from proxy.app.core.retrieval import qdrant_client
    
    if qdrant_client is not None:
      qdrant_client.get_collections ()
    status ["components"] ["qdrant"] = "ok"
  except Exception as e:
    status ["components"] ["qdrant"] = f"error: {str (e)}"
    status ["status"] = "degraded"
  try:
    import requests
    
    resp = requests.get (f"{LLM_ENDPOINT}/health", timeout = 2)
    if resp.status_code == 200:
      status ["components"] ["llm"] = "ok"
    else:
      status ["components"] ["llm"] = "unhealthy"
  except Exception as e:
    status ["components"] ["llm"] = f"error: {str (e)}"
    status ["status"] = "degraded"
  return JSONResponse (status_code = 200 if status ["status"] == "ok" else 503, content = status)


@router.get ("/v1/health/live")
async def health_live () -> JSONResponse:
  """Liveness probe — returns 200 if the process is alive."""
  return JSONResponse (status_code = 200, content = {"status": "alive", "timestamp": datetime.now (UTC).isoformat ()})


@router.get ("/v1/health/ready")
async def health_ready () -> JSONResponse:
  """Readiness probe — checks Qdrant and LLM connectivity."""
  status: dict [str, Any] = {"status": "ready", "timestamp": datetime.now (UTC).isoformat (), "components": {}}
  try:
    from proxy.app.core.retrieval import qdrant_client
    
    if qdrant_client is not None:
      qdrant_client.get_collections ()
    status ["components"] ["qdrant"] = "ok"
  except Exception:
    status ["components"] ["qdrant"] = "unavailable"
    status ["status"] = "not_ready"
  try:
    import requests
    
    resp = requests.get (f"{LLM_ENDPOINT}/health", timeout = 2)
    if resp.status_code == 200:
      status ["components"] ["llm"] = "ok"
    else:
      status ["components"] ["llm"] = "unavailable"
      status ["status"] = "not_ready"
  except Exception:
    status ["components"] ["llm"] = "unavailable"
    status ["status"] = "not_ready"
  http_code = 200 if status ["status"] == "ready" else 503
  return JSONResponse (status_code = http_code, content = status)
