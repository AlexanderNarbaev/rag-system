# proxy/app/api/health.py
"""Health check endpoints — liveness, readiness, and component status."""

import logging
import os
import subprocess
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from proxy.app.shared.config import LLM_ENDPOINT

logger = logging.getLogger("rag-proxy")

router = APIRouter(tags=["health"])


def _check_qdrant() -> tuple[str, dict[str, Any]]:
    """Check Qdrant connectivity and collection count."""
    try:
        from proxy.app.core.retrieval import qdrant_client

        if qdrant_client is None:
            return "unavailable", {"reason": "client not initialized"}
        collections = qdrant_client.get_collections()
        return "ok", {"collections": len(collections.collections)}
    except Exception as e:
        return f"error: {e}", {}


def _check_llm() -> tuple[str, dict[str, Any]]:
    """Check LLM endpoint connectivity."""
    try:
        import requests

        resp = requests.get(f"{LLM_ENDPOINT}/health", timeout=2)
        if resp.status_code == 200:
            return "ok", {"endpoint": LLM_ENDPOINT}
        return "unhealthy", {"status_code": resp.status_code}
    except Exception as e:
        return f"error: {e}", {}


def _check_kb_manager() -> tuple[str, dict[str, Any]]:
    """Check Knowledge Base Manager status."""
    try:
        from proxy.app.main import kb_manager

        if kb_manager is None:
            return "unavailable", {"reason": "not initialized"}
        kbs = kb_manager.list_kbs()
        return "ok", {"knowledge_bases": len(kbs)}
    except Exception as e:
        return f"error: {e}", {}


def _check_tls() -> tuple[str, dict[str, Any]]:
    """Check TLS configuration and certificate status."""
    try:
        # Check if TLS is enabled via environment or headers
        tls_enabled = os.getenv("TLS_ENABLED", "false").lower() == "true"

        # Check for TLS headers from reverse proxy
        # In production, nginx/HAProxy sets these headers
        tls_info: dict[str, Any] = {
            "enabled": tls_enabled,
            "proxy_headers_detected": False,
            "certificate_valid": False,
            "days_until_expiry": None,
            "version": None,
            "cipher": None,
        }

        # Check if running behind TLS-terminating proxy
        # Look for common proxy headers
        forwarded_proto = os.getenv("HTTP_X_FORWARDED_PROTO", "")
        if forwarded_proto == "https":
            tls_info["proxy_headers_detected"] = True
            tls_info["enabled"] = True

        # Try to get TLS info from nginx health endpoint
        try:
            import requests

            nginx_tls_url = "http://nginx/nginx-tls-info"
            resp = requests.get(nginx_tls_url, timeout=2)
            if resp.status_code == 200:
                nginx_info = resp.json()
                tls_info["version"] = nginx_info.get("protocol")
                tls_info["cipher"] = nginx_info.get("cipher")
                tls_info["proxy_headers_detected"] = True
                tls_info["enabled"] = True
        except Exception:
            # nginx not available or not configured
            pass

        # Check certificate file if available
        cert_path = os.getenv("TLS_CERT_PATH", "/etc/nginx/ssl/server.crt")
        if os.path.exists(cert_path):
            try:
                # Use openssl command to check certificate
                result = subprocess.run(
                    ["openssl", "x509", "-in", cert_path, "-noout", "-enddate"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if result.returncode == 0:
                    # Parse output: "notAfter=Mon Jan  1 00:00:00 2027"
                    date_str = result.stdout.strip().split("=")[1]
                    expiry = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
                    now = datetime.now(UTC)
                    days_until_expiry = (expiry - now).days

                    tls_info["certificate_valid"] = days_until_expiry > 0
                    tls_info["days_until_expiry"] = days_until_expiry

                    if days_until_expiry < 30:
                        logger.warning(f"TLS certificate expires in {days_until_expiry} days")

            except Exception as e:
                logger.debug(f"Could not check certificate: {e}")

        # Determine status
        if tls_info["enabled"] and tls_info["certificate_valid"]:
            return "ok", tls_info
        elif tls_info["enabled"]:
            return "degraded", tls_info
        else:
            return "disabled", tls_info

    except Exception as e:
        return f"error: {e}", {}


def _check_secret_rotation() -> tuple[str, dict[str, Any]]:
    """Check secret rotation status and JWT key freshness."""
    try:
        from proxy.app.auth.secret_rotation import get_rotation_manager

        manager = get_rotation_manager()
        rotation_info = manager.get_rotation_status()
        status = rotation_info.pop("status", "ok")

        # Map rotation status to health status
        if status == "error":
            return "error", rotation_info
        if status in ("degraded", "stale_key"):
            return status, rotation_info
        return "ok", rotation_info
    except ImportError:
        return "unavailable", {"reason": "secret_rotation module not installed"}
    except Exception as e:
        return f"error: {e}", {}


@router.get("/v1/health")
async def health() -> JSONResponse:
    """Check proxy and dependency health."""
    status: dict[str, Any] = {"status": "ok", "timestamp": datetime.now(UTC).isoformat(), "components": {}}

    qdrant_status, qdrant_info = _check_qdrant()
    status["components"]["qdrant"] = qdrant_status
    if qdrant_info:
        status["components"]["qdrant_info"] = qdrant_info
    if qdrant_status != "ok":
        status["status"] = "degraded"

    llm_status, llm_info = _check_llm()
    status["components"]["llm"] = llm_status
    if llm_info:
        status["components"]["llm_info"] = llm_info
    if llm_status != "ok":
        status["status"] = "degraded"

    kb_status, kb_info = _check_kb_manager()
    status["components"]["kb_manager"] = kb_status
    if kb_info:
        status["components"]["kb_manager_info"] = kb_info

    rotation_status, rotation_info = _check_secret_rotation()
    status["components"]["secret_rotation"] = rotation_status
    if rotation_info:
        status["components"]["secret_rotation_info"] = rotation_info
    if rotation_status not in ("ok", "unavailable"):
        status["status"] = "degraded"

    return JSONResponse(status_code=200 if status["status"] == "ok" else 503, content=status)


@router.get("/v1/health/live")
async def health_live() -> JSONResponse:
    """Liveness probe — returns 200 if the process is alive."""
    return JSONResponse(status_code=200, content={"status": "alive", "timestamp": datetime.now(UTC).isoformat()})


@router.get("/v1/health/ready")
async def health_ready() -> JSONResponse:
    """Readiness probe — checks Qdrant and LLM connectivity."""
    status: dict[str, Any] = {"status": "ready", "timestamp": datetime.now(UTC).isoformat(), "components": {}}

    qdrant_status, _ = _check_qdrant()
    status["components"]["qdrant"] = qdrant_status
    if qdrant_status != "ok":
        status["status"] = "not_ready"

    llm_status, _ = _check_llm()
    status["components"]["llm"] = llm_status
    if llm_status != "ok":
        status["status"] = "not_ready"

    http_code = 200 if status["status"] == "ready" else 503
    return JSONResponse(status_code=http_code, content=status)


@router.get("/v1/health/tls")
async def health_tls() -> JSONResponse:
    """TLS health check — verifies TLS configuration and certificate status."""
    status: dict[str, Any] = {"status": "ok", "timestamp": datetime.now(UTC).isoformat(), "components": {}}

    tls_status, tls_info = _check_tls()
    status["components"]["tls"] = tls_status
    if tls_info:
        status["components"]["tls_info"] = tls_info

    # Set status based on TLS health
    if tls_status == "error":
        status["status"] = "error"
    elif tls_status == "degraded":
        status["status"] = "degraded"
    elif tls_status == "disabled":
        status["status"] = "disabled"

    # Check if certificate is about to expire
    if tls_info.get("days_until_expiry") is not None:
        days = tls_info["days_until_expiry"]
        if days < 0:
            status["status"] = "expired"
            status["warning"] = "TLS certificate has expired"
        elif days < 30:
            status["warning"] = f"TLS certificate expires in {days} days"

    http_code = 200 if status["status"] in ["ok", "disabled"] else 503
    return JSONResponse(status_code=http_code, content=status)
