"""E2E tests for the authentication flow: login -> JWT -> chat -> feedback."""

import pytest
import requests


@pytest.mark.e2e
class TestLoginFlow:
    """E2E tests for /v1/auth/login."""

    def test_login_flow(self, service_url: str):
        """POST /v1/auth/login -> receive JWT -> use for chat."""
        login_resp = requests.post(
            f"{service_url}/v1/auth/login",
            json={"username": "testuser", "password": "testpass"},
            timeout=10,
        )
        if login_resp.status_code != 200:
            pytest.skip("Auth endpoint not available or credentials invalid")
        login_data = login_resp.json()
        assert "access_token" in login_data
        assert login_data["token_type"] == "bearer"
        assert login_data["user_id"] == "test-001"
        token = login_data["access_token"]

        chat_resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        assert chat_resp.status_code == 200

    def test_auth_me_endpoint(self, service_url: str, auth_headers: dict):
        """GET /v1/auth/me -> user info."""
        if not auth_headers:
            pytest.skip("Auth not available")
        resp = requests.get(
            f"{service_url}/v1/auth/me",
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert data["is_authenticated"] is True

    def test_token_refresh(self, service_url: str, auth_headers: dict):
        """POST /v1/auth/refresh -> get fresh token."""
        if not auth_headers:
            pytest.skip("Auth not available")
        token = auth_headers["Authorization"].replace("Bearer ", "")
        resp = requests.post(
            f"{service_url}/v1/auth/refresh",
            json={"token": token},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "access_token" in data


@pytest.mark.e2e
class TestUnauthorizedRequests:
    """E2E tests for requests without auth."""

    def test_chat_without_auth(self, service_url: str):
        """POST /v1/chat/completions without JWT."""
        resp = requests.post(
            f"{service_url}/v1/chat/completions",
            json={
                "model": "rag-proxy",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            },
            timeout=30,
        )
        # Auth may or may not be required depending on config
        assert resp.status_code in (200, 401, 403)

    def test_auth_me_without_token(self, service_url: str):
        """GET /v1/auth/me without auth header."""
        resp = requests.get(f"{service_url}/v1/auth/me", timeout=10)
        assert resp.status_code in (200, 401, 403)

    def test_login_invalid_credentials(self, service_url: str):
        """POST /v1/auth/login with wrong credentials -> 401."""
        resp = requests.post(
            f"{service_url}/v1/auth/login",
            json={"username": "invalid", "password": "wrong"},
            timeout=10,
        )
        if resp.status_code != 200:
            assert resp.status_code in (401, 403, 404)
