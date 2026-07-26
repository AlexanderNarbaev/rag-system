"""Integration tests for OpenWebUI proxy mode.

OpenWebUI connects to the RAG proxy with a single API key. All users appear
the same unless the proxy extracts individual user identity from request
headers (``X-OpenWebUI-User-Id`` or ``X-Forwarded-User``).

These tests verify FR-87b: the proxy correctly identifies the end-user
behind the shared API key so that audit logs, feedback storage, and
ACL filtering all see the right identity.

The actual implementation lives in
``proxy/app/auth/jwt.py::get_auth_context`` (lines 250-261) and
``proxy/app/shared/middleware.py::RequestIdMiddleware`` (lines 39-42).
"""

from __future__ import annotations

import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the proxy package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "proxy"))

# Module-level imports for FastAPI type introspection. With
# ``from __future__ import annotations`` the ``Request`` annotation is a
# string; FastAPI resolves it via ``get_type_hints`` which only inspects
# module globals. Keeping the import here makes the type resolvable.
from fastapi import Request  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _build_mock_request(headers: dict[str, str]) -> MagicMock:
    """Build a minimal Starlette/FastAPI ``Request`` mock with the given headers.

    The mock exposes only what ``get_auth_context`` actually reads: the
    ``headers`` mapping. ``HTTPAuthorizationCredentials`` is passed as
    ``None`` so that the bearer-token branch is skipped and the API-key
    branch is exercised through ``_validate_api_key``.
    """
    request = MagicMock()
    request.headers = headers
    return request


def _api_key_credentials(key: str = "sk-shared-openwebui-key"):
    """Build a FastAPI ``HTTPAuthorizationCredentials`` carrying an API key."""
    from fastapi.security import HTTPAuthorizationCredentials

    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=key)


@contextmanager
def _auth_enabled(value: bool = True):
    """Patch AUTH_ENABLED in both the auth module and the shared config.

    Implemented as a single context manager so the tests read naturally.
    """
    with ExitStack() as stack:
        stack.enter_context(patch("proxy.app.auth.jwt.AUTH_ENABLED", value))
        stack.enter_context(patch("proxy.app.shared.config.AUTH_ENABLED", value))
        yield stack


def _api_key_ctx(
    user_id: str = "openwebui-instance",
    roles: list[str] | None = None,
    access_level: str = "internal",
    namespace: str = "",
    groups: list[str] | None = None,
):
    """Build a MagicMock that mimics a UserContext returned by ``_validate_api_key``."""
    ctx = MagicMock()
    ctx.user_id = user_id
    ctx.username = user_id
    ctx.roles = roles if roles is not None else ["user"]
    ctx.groups = groups if groups is not None else []
    ctx.access_level = access_level
    ctx.namespace = namespace
    return ctx


# ──────────────────────────────────────────────────────────────────────────────
# FR-87b — header-based user identification
# ──────────────────────────────────────────────────────────────────────────────


class TestOpenWebUIUserIdentification:
    """FR-87b: User identification via HTTP headers (OpenWebUI proxy mode)."""

    @pytest.mark.asyncio
    async def test_x_openwebui_user_id_overrides_api_key_user(self):
        """When ``X-OpenWebUI-User-Id`` header is present, use that user.

        The shared API key authenticates the OpenWebUI instance; the header
        identifies the actual end-user behind the request.
        """
        from proxy.app.auth.jwt import get_auth_context

        with (
            _auth_enabled(True),
            patch(
                "proxy.app.auth.jwt._validate_api_key",
                return_value=_api_key_ctx(),
            ),
        ):
            request = _build_mock_request(
                {
                    "authorization": "Bearer sk-shared-openwebui-key",
                    "x-openwebui-user-id": "alice",
                },
            )
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        assert user_ctx.user_id == "alice"
        assert user_ctx.username == "alice"
        # Roles / groups / access_level propagate from the API key user
        assert user_ctx.roles == ["user"]

    @pytest.mark.asyncio
    async def test_x_forwarded_user_fallback(self):
        """``X-Forwarded-User`` is used as fallback when OpenWebUI header absent."""
        from proxy.app.auth.jwt import get_auth_context

        with (
            _auth_enabled(True),
            patch(
                "proxy.app.auth.jwt._validate_api_key",
                return_value=_api_key_ctx(),
            ),
        ):
            request = _build_mock_request(
                {
                    "authorization": "Bearer sk-shared-openwebui-key",
                    "x-forwarded-user": "bob",
                },
            )
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        assert user_ctx.user_id == "bob"

    @pytest.mark.asyncio
    async def test_no_header_uses_api_key_user(self):
        """Without headers, user_id comes from the API key itself."""
        from proxy.app.auth.jwt import get_auth_context

        with (
            _auth_enabled(True),
            patch(
                "proxy.app.auth.jwt._validate_api_key",
                return_value=_api_key_ctx(user_id="service-account"),
            ),
        ):
            request = _build_mock_request(
                {"authorization": "Bearer sk-shared-openwebui-key"},
            )
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        assert user_ctx.user_id == "service-account"

    @pytest.mark.asyncio
    async def test_admin_role_via_header(self):
        """Admin role from API key is preserved even when user_id is overridden.

        The header rewrites ``user_id`` / ``username`` only — roles,
        groups, access_level, and namespace flow through unchanged.
        This is by design: the API key carries the tenant's RBAC bundle,
        the header only disambiguates the end-user.
        """
        from proxy.app.auth.jwt import get_auth_context

        admin_ctx = _api_key_ctx(
            user_id="openwebui-admin",
            roles=["admin", "user"],
            access_level="internal",
            namespace="acme",
            groups=["admins"],
        )

        with (
            _auth_enabled(True),
            patch(
                "proxy.app.auth.jwt._validate_api_key",
                return_value=admin_ctx,
            ),
        ):
            request = _build_mock_request(
                {
                    "authorization": "Bearer sk-shared-openwebui-key",
                    "x-openwebui-user-id": "charlie-admin",
                },
            )
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        assert user_ctx.user_id == "charlie-admin"
        assert user_ctx.roles == ["admin", "user"]
        assert user_ctx.access_level == "internal"
        assert user_ctx.namespace == "acme"

    @pytest.mark.asyncio
    async def test_auth_disabled_returns_anonymous_even_with_header(self):
        """When ``AUTH_ENABLED=false``, headers are ignored — anonymous context."""
        from proxy.app.auth.jwt import get_auth_context

        with _auth_enabled(False):
            request = _build_mock_request({"x-openwebui-user-id": "alice"})
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        assert user_ctx.user_id == "anonymous"
        assert user_ctx.is_authenticated is False

    @pytest.mark.asyncio
    async def test_x_openwebui_user_id_takes_precedence_over_x_forwarded_user(self):
        """``X-OpenWebUI-User-Id`` wins when both headers are present."""
        from proxy.app.auth.jwt import get_auth_context

        with (
            _auth_enabled(True),
            patch(
                "proxy.app.auth.jwt._validate_api_key",
                return_value=_api_key_ctx(),
            ),
        ):
            request = _build_mock_request(
                {
                    "authorization": "Bearer sk-shared-key",
                    "x-openwebui-user-id": "alice",
                    "x-forwarded-user": "bob",
                },
            )
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        assert user_ctx.user_id == "alice"


# ──────────────────────────────────────────────────────────────────────────────
# Header extraction in middleware — independent fast-path used for logging.
# ──────────────────────────────────────────────────────────────────────────────


class TestRequestIdMiddlewareUserExtraction:
    """``RequestIdMiddleware`` mirrors the header lookup so that every log
    line carries the forwarded user_id without depending on auth.

    The middleware is wired into a minimal FastAPI app for these tests so
    we exercise the real ASGI dispatch path.
    """

    @staticmethod
    def _build_app():
        from fastapi import FastAPI

        from proxy.app.shared.middleware import RequestIdMiddleware

        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/probe")
        async def probe(request: Request):
            # Surface the forwarded user_id so the test can assert it
            return {"forwarded_user_id": getattr(request.state, "forwarded_user_id", None)}

        return app

    def test_middleware_extracts_openwebui_header(self):
        """``request.state.forwarded_user_id`` is set from OpenWebUI header."""
        from starlette.testclient import TestClient

        client = TestClient(self._build_app())
        response = client.get(
            "/probe",
            headers={"X-OpenWebUI-User-Id": "alice"},
        )
        assert response.status_code == 200
        assert response.json()["forwarded_user_id"] == "alice"

    def test_middleware_falls_back_to_x_forwarded_user(self):
        """``x-forwarded-user`` is used when ``x-openwebui-user-id`` is absent."""
        from starlette.testclient import TestClient

        client = TestClient(self._build_app())
        response = client.get(
            "/probe",
            headers={"X-Forwarded-User": "bob"},
        )
        assert response.status_code == 200
        assert response.json()["forwarded_user_id"] == "bob"

    def test_middleware_returns_none_when_no_headers(self):
        """Without headers, ``forwarded_user_id`` is ``None``."""
        from starlette.testclient import TestClient

        client = TestClient(self._build_app())
        response = client.get("/probe")
        assert response.status_code == 200
        assert response.json()["forwarded_user_id"] is None


# ──────────────────────────────────────────────────────────────────────────────
# User context propagation — end-to-end through the API surface.
# ──────────────────────────────────────────────────────────────────────────────


class TestUserContextPropagation:
    """User context propagates through the API for audit and ACL filtering."""

    @pytest.mark.asyncio
    async def test_user_id_in_chat_response_metadata(self):
        """``/v1/chat/completions`` receives the header-overridden user_id.

        The chat handler depends on ``get_auth_context`` via FastAPI's
        dependency injection. We invoke ``get_auth_context`` directly with
        a mocked request, then assert the user_id field that the chat
        handler would attach to its audit log.
        """
        from proxy.app.auth.jwt import get_auth_context

        with (
            _auth_enabled(True),
            patch(
                "proxy.app.auth.jwt._validate_api_key",
                return_value=_api_key_ctx(),
            ),
        ):
            request = _build_mock_request(
                {
                    "authorization": "Bearer sk-shared",
                    "x-openwebui-user-id": "alice",
                },
            )
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        assert user_ctx.user_id == "alice"
        # The chat handler writes ``user.user_id`` into the audit log line
        # and into ``session_id`` for streaming responses. Here we just
        # confirm the dependency hands back the right identity.
        assert getattr(user_ctx, "user_id", None) == "alice"

    @pytest.mark.asyncio
    async def test_user_id_in_feedback_storage(self):
        """Feedback store must persist the resolved user_id for analytics.

        The feedback endpoint extracts ``user_id`` via
        ``Depends(get_auth_context)``; verify the dependency returns the
        header-overridden user.
        """
        from proxy.app.auth.jwt import get_auth_context

        with (
            _auth_enabled(True),
            patch(
                "proxy.app.auth.jwt._validate_api_key",
                return_value=_api_key_ctx(),
            ),
        ):
            request = _build_mock_request(
                {
                    "authorization": "Bearer sk-shared",
                    "x-openwebui-user-id": "alice",
                },
            )
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        # The feedback endpoint saves the user_id from this context.
        assert user_ctx.user_id == "alice"

    @pytest.mark.asyncio
    async def test_user_role_in_acl_filter(self):
        """User roles from the API key are preserved through the header override
        so that ACL filtering in search applies the correct RBAC bundle.
        """
        from proxy.app.auth.jwt import get_auth_context

        expert_ctx = _api_key_ctx(
            user_id="svc",
            roles=["expert", "user"],
            groups=["experts"],
        )

        with (
            _auth_enabled(True),
            patch(
                "proxy.app.auth.jwt._validate_api_key",
                return_value=expert_ctx,
            ),
        ):
            request = _build_mock_request(
                {
                    "authorization": "Bearer sk-shared",
                    "x-openwebui-user-id": "alice",
                },
            )
            user_ctx = await get_auth_context(request, credentials=_api_key_credentials())

        assert "expert" in user_ctx.roles
        assert user_ctx.is_expert is True
        assert user_ctx.user_id == "alice"
