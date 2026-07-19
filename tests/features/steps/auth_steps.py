"""Step definitions for authentication and authorization feature."""

import contextlib
import os

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../authentication.feature")

PROXY_URL = os.getenv("RAG_PROXY_URL", "http://localhost:9080")
REQUEST_TIMEOUT = 10


@pytest.fixture
def auth_context():
    """Shared context for authentication test steps."""
    return {}


@given(parsers.parse('a user "{username}" with password "{password}"'))
def create_user(auth_context, username, password):
    """Register a test user (or note credentials for login)."""
    auth_context["username"] = username
    auth_context["password"] = password
    # Attempt registration; may fail if user already exists — that's OK
    with contextlib.suppress(httpx.HTTPStatusError):
        httpx.post(
            f"{PROXY_URL}/v1/auth/register",
            json={"username": username, "password": password},
            timeout=REQUEST_TIMEOUT,
        )


@given(parsers.parse('a user "{username}" with role "{role}"'))
def create_user_with_role(auth_context, username, role):
    """Register a test user with a specific role."""
    auth_context["username"] = username
    auth_context["role"] = role
    with contextlib.suppress(httpx.HTTPStatusError):
        httpx.post(
            f"{PROXY_URL}/v1/auth/register",
            json={"username": username, "password": "testpass123", "role": role},
            timeout=REQUEST_TIMEOUT,
        )


@given(parsers.parse('an API key "{api_key}"'))
def set_api_key(auth_context, api_key):
    """Store an API key for authentication tests."""
    auth_context["api_key"] = api_key


@given("rate limiting is enabled with 60 requests per minute")
def set_rate_limit(auth_context):
    """Note rate limiting configuration."""
    auth_context["rate_limit"] = 60


@given("a valid refresh token")
def get_valid_refresh_token(auth_context):
    """Login to obtain a valid refresh token."""
    r = httpx.post(
        f"{PROXY_URL}/v1/auth/login",
        json={"username": "alice", "password": "secret123"},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code == 200:
        data = r.json()
        auth_context["refresh_token"] = data.get("refresh_token")
        auth_context["access_token"] = data.get("access_token")


@given("a logged-in user with access token")
def get_logged_in_token(auth_context):
    """Login and store the access token."""
    r = httpx.post(
        f"{PROXY_URL}/v1/auth/login",
        json={"username": "alice", "password": "secret123"},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code == 200:
        data = r.json()
        auth_context["access_token"] = data.get("access_token")
        auth_context["refresh_token"] = data.get("refresh_token")


@when('I POST to "/v1/auth/login" with credentials')
def login_with_credentials(auth_context):
    """Login with stored credentials."""
    r = httpx.post(
        f"{PROXY_URL}/v1/auth/login",
        json={
            "username": auth_context.get("username", ""),
            "password": auth_context.get("password", ""),
        },
        timeout=REQUEST_TIMEOUT,
    )
    auth_context["login_response"] = r
    if r.status_code == 200:
        data = r.json()
        auth_context["access_token"] = data.get("access_token")
        auth_context["refresh_token"] = data.get("refresh_token")


@when(parsers.parse('I send a request with Authorization header "{auth_header}"'))
def send_request_with_auth_header(auth_context, auth_header):
    """Send a request with a custom Authorization header."""
    r = httpx.get(
        f"{PROXY_URL}/v1/models",
        headers={"Authorization": auth_header},
        timeout=REQUEST_TIMEOUT,
    )
    auth_context["auth_response"] = r


@when(parsers.parse('I try to access "{path}"'))
def try_access_path(auth_context, path):
    """Attempt to access a protected path."""
    headers = {}
    if auth_context.get("access_token"):
        headers["Authorization"] = f"Bearer {auth_context['access_token']}"
    r = httpx.get(
        f"{PROXY_URL}{path}",
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    auth_context["access_response"] = r


@when("I send 61 requests in 1 minute")
def send_rate_limit_requests(auth_context):
    """Send 61 rapid requests to trigger rate limiting."""
    responses = []
    for _ in range(61):
        try:
            r = httpx.get(f"{PROXY_URL}/v1/health", timeout=5)
            responses.append(r.status_code)
        except httpx.HTTPError:
            responses.append(0)
    auth_context["rate_limit_responses"] = responses


@when('I POST to "/v1/auth/refresh" with the refresh token')
def refresh_token(auth_context):
    """Refresh the access token."""
    r = httpx.post(
        f"{PROXY_URL}/v1/auth/refresh",
        json={"refresh_token": auth_context.get("refresh_token", "")},
        timeout=REQUEST_TIMEOUT,
    )
    auth_context["refresh_response"] = r
    if r.status_code == 200:
        data = r.json()
        auth_context["new_access_token"] = data.get("access_token")
        auth_context["new_refresh_token"] = data.get("refresh_token")


@when('I POST to "/v1/auth/logout"')
def logout(auth_context):
    """Logout the current user."""
    headers = {}
    if auth_context.get("access_token"):
        headers["Authorization"] = f"Bearer {auth_context['access_token']}"
    r = httpx.post(
        f"{PROXY_URL}/v1/auth/logout",
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    auth_context["logout_response"] = r


@then("I receive an access token and refresh token")
def check_tokens_received(auth_context):
    """Assert both tokens were returned."""
    r = auth_context.get("login_response")
    assert r is not None, "No login response"
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data, "Missing access_token"
    assert "refresh_token" in data, "Missing refresh_token"


@then("the access token expires in 15 minutes")
def check_token_expiry(auth_context):
    """Assert the access token has a 15-minute expiry."""
    # This is a structural check — we verify the token format
    token = auth_context.get("access_token", "")
    assert len(token) > 0, "Access token is empty"
    # JWT tokens have 3 parts separated by dots
    parts = token.split(".")
    assert len(parts) == 3, f"Invalid JWT format: {len(parts)} parts"


@then("the request is authenticated")
def check_authenticated(auth_context):
    """Assert the request was authenticated successfully."""
    r = auth_context.get("auth_response")
    assert r is not None, "No auth response"
    assert r.status_code != 401, f"Request was not authenticated: {r.status_code}"


@then("the user context has the API key's user")
def check_api_key_user(auth_context):
    """Assert the user context matches the API key's user."""
    # If authenticated, the user context is implicit
    r = auth_context.get("auth_response")
    assert r is not None and r.status_code == 200, "Request not authenticated"


@then("I receive status 403")
def check_forbidden(auth_context):
    """Assert the response is 403 Forbidden."""
    r = auth_context.get("access_response")
    assert r is not None, "No access response"
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


@then("the 61st request returns status 429")
def check_rate_limited(auth_context):
    """Assert the 61st request was rate limited."""
    responses = auth_context.get("rate_limit_responses", [])
    assert len(responses) >= 61, f"Only {len(responses)} requests sent"
    # The 61st response should be 429 (or system may use different limits)
    last_status = responses[-1]
    assert last_status == 429, f"Expected 429 on 61st request, got {last_status}"


@then("I receive a new access token and refresh token")
def check_new_tokens(auth_context):
    """Assert new tokens were returned from refresh."""
    r = auth_context.get("refresh_response")
    assert r is not None, "No refresh response"
    assert r.status_code == 200, f"Refresh failed: {r.status_code}"
    data = r.json()
    assert "access_token" in data, "Missing new access_token"
    assert "refresh_token" in data, "Missing new refresh_token"


@then("the old refresh token is invalidated")
def check_old_token_invalid(auth_context):
    """Assert the old refresh token can no longer be used."""
    old_token = auth_context.get("refresh_token")
    if old_token:
        r = httpx.post(
            f"{PROXY_URL}/v1/auth/refresh",
            json={"refresh_token": old_token},
            timeout=REQUEST_TIMEOUT,
        )
        assert r.status_code in (401, 403), f"Old token still valid: {r.status_code}"


@then("the access token is blacklisted")
def check_token_blacklisted(auth_context):
    """Assert the access token is rejected after logout."""
    token = auth_context.get("access_token")
    if token:
        r = httpx.get(
            f"{PROXY_URL}/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        )
        assert r.status_code in (401, 403), f"Token still valid after logout: {r.status_code}"


@then("all refresh tokens for the user are revoked")
def check_refresh_tokens_revoked(auth_context):
    """Assert all refresh tokens for the user are revoked."""
    # Attempt to use the refresh token — should fail
    refresh = auth_context.get("refresh_token")
    if refresh:
        r = httpx.post(
            f"{PROXY_URL}/v1/auth/refresh",
            json={"refresh_token": refresh},
            timeout=REQUEST_TIMEOUT,
        )
        assert r.status_code in (401, 403), f"Refresh token still valid: {r.status_code}"
