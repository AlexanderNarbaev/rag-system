# proxy/app/middleware.py
"""
Custom middleware for RAG proxy:
- Request ID injection (X-Request-ID)
- Request logging (method, path, status, duration)
- Correlation ID propagation
- CORS configuration
- Security headers injection
- Audit logging
- Input sanitization
"""
import os
import time
import uuid
import logging
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import FastAPI

from app.logging_config import RequestIdFilter
from app.security import SecurityHeaders, InputValidator

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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects security-related HTTP headers into every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        headers = SecurityHeaders.get_headers()
        for header_name, header_value in headers.items():
            if header_name not in response.headers:
                response.headers[header_name] = header_value
        return response


class AuditMiddleware(BaseHTTPMiddleware):
    """Logs every request through AuditLogger for security auditing."""

    def __init__(self, app, audit_logger=None):
        super().__init__(app)
        self.audit_logger = audit_logger

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        start = time.monotonic()

        response = await call_next(request)

        duration_ms = (time.monotonic() - start) * 1000
        if self.audit_logger and response.status_code >= 400:
            try:
                self.audit_logger.log_error(
                    error_type=f"HTTP_{response.status_code}",
                    error_msg=f"{request.method} {request.url.path} returned {response.status_code}",
                    stack_trace=None,
                    client_ip=client_ip,
                    endpoint=request.url.path,
                )
            except Exception:
                pass

        return response


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """Sanitizes query parameters in requests to prevent injection attacks."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.query:
            sanitized_params = {}
            for key, values in request.query_params.multi_items():
                sanitized_key = InputValidator.validate_non_empty(key, max_len=256) or key
                sanitized_vals = []
                for v in values:
                    sv = InputValidator.validate_non_empty(v, max_len=4096)
                    sanitized_vals.append(sv if sv is not None else v)
                sanitized_params[sanitized_key] = sanitized_vals

        response = await call_next(request)
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


def setup_all_middleware(app: FastAPI, audit_logger=None):
    """Apply all standard middleware in correct order."""
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    if audit_logger is not None:
        app.add_middleware(AuditMiddleware, audit_logger=audit_logger)
    app.add_middleware(InputSanitizationMiddleware)
