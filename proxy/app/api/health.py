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


def _check_qdrant () -> tuple [str, dict [str, Any]]:
  """Check Qdrant connectivity and collection count."""
  try:
    from proxy.app.core.retrieval import qdrant_client

    if qdrant_client is None:
      return "unavailable", {"reason": "client not initialized"}
    collections = qdrant_client.get_collections ()
    return "ok", {"collections": len (collections.collections)}
  except Exception as e:
    return f"error: {e}", {}


def _check_llm () -> tuple [str, dict [str, Any]]:
  """Check LLM endpoint connectivity."""
  try:
    import requests

    resp = requests.get (f"{LLM_ENDPOINT}/health", timeout = 2)
    if resp.status_code == 200:
      return "ok", {"endpoint": LLM_ENDPOINT}
    return "unhealthy", {"status_code": resp.status_code}
  except Exception as e:
    return f"error: {e}", {}


def _check_kb_manager () -> tuple [str, dict [str, Any]]:
  """Check Knowledge Base Manager status."""
  try:
    from proxy.app.main import kb_manager

    if kb_manager is None:
      return "unavailable", {"reason": "not initialized"}
    kbs = kb_manager.list_kbs ()
    return "ok", {"knowledge_bases": len (kbs)}
  except Exception as e:
    return f"error: {e}", {}


@router.get ("/v1/health")
async def health () -> JSONResponse:
  """Check proxy and dependency health."""
  status: dict [str, Any] = {"status": "ok", "timestamp": datetime.now (UTC).isoformat (), "components": {}}

  qdrant_status, qdrant_info = _check_qdrant ()
  status ["components"] ["qdrant"] = qdrant_status
  if qdrant_info:
    status ["components"] ["qdrant_info"] = qdrant_info
  if qdrant_status != "ok":
    status ["status"] = "degraded"

  llm_status, llm_info = _check_llm ()
  status ["components"] ["llm"] = llm_status
  if llm_info:
    status ["components"] ["llm_info"] = llm_info
  if llm_status != "ok":
    status ["status"] = "degraded"

  kb_status, kb_info = _check_kb_manager ()
  status ["components"] ["kb_manager"] = kb_status
  if kb_info:
    status ["components"] ["kb_manager_info"] = kb_info

  return JSONResponse (status_code = 200 if status ["status"] == "ok" else 503, content = status)


@router.get ("/v1/health/live")
async def health_live () -> JSONResponse:
  """Liveness probe — returns 200 if the process is alive."""
  return JSONResponse (status_code = 200, content = {"status": "alive", "timestamp": datetime.now (UTC).isoformat ()})


@router.get ("/v1/health/ready")
async def health_ready () -> JSONResponse:
  """Readiness probe — checks Qdrant and LLM connectivity."""
  status: dict [str, Any] = {"status": "ready", "timestamp": datetime.now (UTC).isoformat (), "components": {}}

  qdrant_status, _ = _check_qdrant ()
  status ["components"] ["qdrant"] = qdrant_status
  if qdrant_status != "ok":
    status ["status"] = "not_ready"

  llm_status, _ = _check_llm ()
  status ["components"] ["llm"] = llm_status
  if llm_status != "ok":
    status ["status"] = "not_ready"

  http_code = 200 if status ["status"] == "ready" else 503
  return JSONResponse (status_code = http_code, content = status)
