# proxy/app/api/__init__.py
"""Presentation layer — FastAPI routers for each bounded context."""

from proxy.app.api.admin import router as admin_router
from proxy.app.api.auth_endpoints import router as auth_router
from proxy.app.api.chat import router as chat_router
from proxy.app.api.feedback import router as feedback_router
from proxy.app.api.files import router as files_router
from proxy.app.api.health import router as health_router
from proxy.app.api.metrics import router as metrics_router
from proxy.app.api.tools import router as tools_router
from proxy.app.api.widget import router as widget_router

__all__ = [
    "admin_router",
    "auth_router",
    "chat_router",
    "feedback_router",
    "files_router",
    "health_router",
    "metrics_router",
    "tools_router",
    "widget_router",
]
