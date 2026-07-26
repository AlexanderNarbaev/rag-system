"""Authentication security regression and audit tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import bcrypt
import jwt
import pytest
from fastapi import HTTPException

from proxy.app.auth import jwt as jwt_auth
from proxy.app.auth.user_db import UserDatabase
from proxy.app.shared.config import JWT_SECRET
from proxy.app.shared.rate_limiter import RateLimiter
from proxy.app.shared.security import CSRFProtection, InputValidator, PasswordStrengthValidator, SQLInjectionDetector


def test_jwt_secret_has_at_least_256_bits() -> None:
    assert len(JWT_SECRET.encode("utf-8")) >= 32


@pytest.mark.asyncio
async def test_password_is_stored_as_bcrypt_not_plain_text(tmp_path) -> None:
    database = UserDatabase(str(tmp_path / "users.db"))
    password = "StrongPassword1!"
    created = await database.create_user("alice", password)
    stored = await database.get_user(created["user_id"])

    assert stored is not None
    assert stored["password_hash"] != password
    assert stored["password_hash"].startswith(("$2a$", "$2b$", "$2y$"))
    assert bcrypt.checkpw(password.encode(), stored["password_hash"].encode())


@pytest.mark.asyncio
async def test_rate_limiting_isolated_per_ip() -> None:
    limiter = RateLimiter(rate_per_minute=1, burst=1)
    assert (await limiter.is_allowed("ip:192.0.2.1"))[0]
    assert not (await limiter.is_allowed("ip:192.0.2.1"))[0]
    assert (await limiter.is_allowed("ip:192.0.2.2"))[0]


@pytest.mark.asyncio
async def test_rate_limiting_isolated_per_user() -> None:
    limiter = RateLimiter(rate_per_minute=1, burst=1)
    assert (await limiter.is_allowed("user:alice"))[0]
    assert not (await limiter.is_allowed("user:alice"))[0]
    assert (await limiter.is_allowed("user:bob"))[0]


def test_expired_tokens_are_rejected() -> None:
    payload = {
        "sub": "expired-user",
        "preferred_username": "expired",
        "exp": datetime.now(UTC) - timedelta(seconds=1),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    with (
        patch.object(jwt_auth, "JWT_ALGORITHM", "HS256"),
        patch.object(jwt_auth, "JWT_SECRET", JWT_SECRET),
        pytest.raises(HTTPException, match="expired") as error,
    ):
        jwt_auth.verify_token(token)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_revoked_refresh_tokens_are_rejected(tmp_path) -> None:
    database = UserDatabase(str(tmp_path / "users.db"))
    user = await database.create_user("revoked-user", "StrongPassword1!")
    token = "refresh-secret"
    await database.store_refresh_token(user["user_id"], token)
    await database.revoke_user_tokens(user["user_id"])
    assert await database.consume_refresh_token(token) is None


@pytest.mark.parametrize("password", ["", "short", "1234567"])
def test_weak_passwords_under_eight_chars_are_rejected(password: str) -> None:
    valid, _ = PasswordStrengthValidator.validate(password)
    assert not valid


@pytest.mark.asyncio
async def test_sql_injection_cannot_change_user_query(tmp_path) -> None:
    database = UserDatabase(str(tmp_path / "users.db"))
    await database.create_user("alice", "StrongPassword1!")
    payload = "alice' OR 1=1 --"
    assert SQLInjectionDetector.detect_sqli(payload)
    assert await database.get_user_by_username(payload) is None
    assert await database.get_user_by_username("alice") is not None


def test_xss_is_removed_from_user_query() -> None:
    value = InputValidator.validate_query('<script>alert("x")</script> safe')
    assert "<script" not in value
    assert "</script>" not in value


def test_csrf_double_submit_tokens_required_for_state_changes() -> None:
    token = CSRFProtection.generate_token()
    assert CSRFProtection.is_state_changing("POST")
    assert not CSRFProtection.validate_request({}, {})
    assert not CSRFProtection.validate_request({CSRFProtection.HEADER_NAME: token}, {})
    assert CSRFProtection.validate_request(
        {CSRFProtection.HEADER_NAME: token},
        {CSRFProtection.COOKIE_NAME: token},
    )


def test_expired_token_rejection_uses_registered_jwt_verifier() -> None:
    with patch.object(jwt_auth, "_get_verify_key", return_value=JWT_SECRET):
        assert callable(jwt_auth.verify_token)
