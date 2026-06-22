# proxy/app/middleware.py
"""
Custom middleware for RAG proxy:
- Request ID injection (X-Request-ID)
- Request logging (method, path, status, duration)
- Correlation ID propagation
- CORS configuration
"""
import os
import time
import uuid
import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import FastAPI

from app.logging_config import RequestIdFilter

logger = logging.getLogger("rag-proxy.middleware")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Injects X-Request-ID header into every request/response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        RequestIdFilter.set_request_id(request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs each request with method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s %d %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Propagates X-Correlation-ID header.
    If absent from request, generates and injects a new one.
    """

    HEADER_NAME = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get(self.HEADER_NAME) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        response = await call_next(request)
        response.headers[self.HEADER_NAME] = correlation_id
        return response


def add_cors_middleware(app: FastAPI, origins: str = "*"):
    """Add CORS middleware with configurable origins."""
    allowed_origins = [o.strip() for o in origins.split(",")] if origins != "*" else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Correlation-ID", "Retry-After"],
    )


def setup_all_middleware(app: FastAPI):
    """Apply all standard middleware in correct order."""
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
