"""Tests for proxy/app/auth/jwt.py — token pair creation, refresh, blacklist, and OIDC discovery.

Complements test_auth.py (basic create/verify) and test_auth_enhanced.py (middleware/aliases).
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest

from proxy.app.auth.jwt import (
    UserContext,
    _get_verify_key,
    blacklist_access_token,
    create_mock_token,
    create_token,
    create_token_pair,
    verify_refresh_token,
)


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-unit-tests-ok")
    monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "test-secret-key-for-unit-tests-ok")
    monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "test-secret-key-for-unit-tests-ok")
    monkeypatch.setattr("proxy.app.shared.config.JWT_ALGORITHM", "HS256")
    monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")
    monkeypatch.setattr("proxy.app.shared.config.AUTH_ENABLED", False)
    monkeypatch.setattr("proxy.app.auth.jwt.AUTH_ENABLED", False)
    monkeypatch.setattr("proxy.app.shared.config.ACCESS_TOKEN_MINUTES", 15)
    monkeypatch.setattr("proxy.app.auth.jwt.ACCESS_TOKEN_MINUTES", 15)
    monkeypatch.setattr("proxy.app.shared.config.TOKEN_EXPIRE_HOURS", 24)
    monkeypatch.setattr("proxy.app.auth.jwt.TOKEN_EXPIRE_HOURS", 24)
    monkeypatch.setattr("proxy.app.shared.config.KEYCLOAK_URL", "")
    monkeypatch.setattr("proxy.app.auth.jwt.KEYCLOAK_URL", "")
    monkeypatch.setattr("proxy.app.shared.config.KEYCLOAK_REALM", "master")
    monkeypatch.setattr("proxy.app.auth.jwt.KEYCLOAK_REALM", "master")
    monkeypatch.setattr("proxy.app.shared.config.JWT_PUBLIC_KEY", "")
    monkeypatch.setattr("proxy.app.auth.jwt.JWT_PUBLIC_KEY", "")


# ── _get_verify_key ──────────────────────────────────────────────────────────


class TestGetVerifyKey:
    def test_returns_secret_for_hs256(self, monkeypatch):
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "HS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "my-long-enough-secret-for-testing")
        key = _get_verify_key()
        assert key == "my-long-enough-secret-for-testing"

    def test_returns_public_key_for_rs256(self, monkeypatch):
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "RS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\nMIIB...")
        key = _get_verify_key()
        assert key == "-----BEGIN PUBLIC KEY-----\nMIIB..."

    def test_returns_none_when_no_key(self, monkeypatch):
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_ALGORITHM", "RS256")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_PUBLIC_KEY", "")
        key = _get_verify_key()
        assert key is None


# ── create_token_pair ────────────────────────────────────────────────────────


class TestCreateTokenPair:
    @pytest.mark.asyncio
    async def test_returns_access_and_refresh_tokens(self):
        mock_db = MagicMock()
        mock_db.store_refresh_token = AsyncMock(return_value="token_id_123")

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            user = {"id": "u1", "username": "alice", "roles": ["user"], "groups": ["eng"]}
            result = await create_token_pair(user)

            assert "access_token" in result
            assert "refresh_token" in result
            assert result["token_type"] == "bearer"
            assert result["expires_in"] == 15 * 60
            assert len(result["access_token"]) > 0
            assert len(result["refresh_token"]) > 0

    @pytest.mark.asyncio
    async def test_access_token_contains_claims(self):
        mock_db = MagicMock()
        mock_db.store_refresh_token = AsyncMock(return_value="token_id_123")

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            user = {"id": "u1", "username": "alice", "roles": ["admin"], "groups": ["eng"]}
            result = await create_token_pair(user)

            decoded = jwt.decode(
                result["access_token"],
                key="test-secret-key-for-unit-tests-ok",
                algorithms=["HS256"],
                options={"verify_exp": False},
            )
            assert decoded["sub"] == "u1"
            assert decoded["preferred_username"] == "alice"
            assert decoded["roles"] == ["admin"]
            assert decoded["type"] == "access"
            assert "jti" in decoded

    @pytest.mark.asyncio
    async def test_stores_refresh_token_in_db(self):
        mock_db = MagicMock()
        mock_db.store_refresh_token = AsyncMock(return_value="token_id_456")

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            user = {"id": "u1", "username": "alice"}
            await create_token_pair(user)
            mock_db.store_refresh_token.assert_called_once()
            call_args = mock_db.store_refresh_token.call_args
            assert call_args[0][0] == "u1"  # user_id
            assert len(call_args[0][1]) > 0  # raw_token

    @pytest.mark.asyncio
    async def test_raises_without_jwt_secret(self, monkeypatch):
        monkeypatch.setattr("proxy.app.shared.config.JWT_SECRET", "")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_SECRET", "")

        mock_db = MagicMock()
        mock_db.store_refresh_token = AsyncMock(return_value="token_id")

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            user = {"id": "u1", "username": "alice"}
            with pytest.raises(ValueError, match="JWT_SECRET is not configured"):
                await create_token_pair(user)


# ── verify_refresh_token ─────────────────────────────────────────────────────


class TestVerifyRefreshToken:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self):
        mock_db = MagicMock()
        mock_db.consume_refresh_token = AsyncMock(return_value={"id": "u1", "username": "alice"})

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            result = await verify_refresh_token("valid-refresh-token")
            assert result is not None
            assert result["id"] == "u1"

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self):
        mock_db = MagicMock()
        mock_db.consume_refresh_token = AsyncMock(return_value=None)

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            result = await verify_refresh_token("invalid-token")
            assert result is None

    @pytest.mark.asyncio
    async def test_calls_consume_refresh_token(self):
        mock_db = MagicMock()
        mock_db.consume_refresh_token = AsyncMock(return_value=None)

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            await verify_refresh_token("test-token")
            mock_db.consume_refresh_token.assert_called_once_with("test-token")


# ── blacklist_access_token ───────────────────────────────────────────────────


class TestBlacklistAccessToken:
    @pytest.mark.asyncio
    async def test_blacklists_valid_token_with_jti(self):
        """Tokens with jti (from create_token_pair) should be blacklisted."""
        mock_db = MagicMock()
        mock_db.add_to_blacklist = AsyncMock()

        # Create a token with jti (like create_token_pair does)
        now = int(time.time())
        payload = {
            "sub": "u1",
            "preferred_username": "alice",
            "roles": ["user"],
            "groups": [],
            "access_level": "internal",
            "namespace": "",
            "iat": now,
            "exp": now + 3600,
            "jti": "unique-jti-123",
            "type": "access",
        }
        token = jwt.encode(payload, key="test-secret-key-for-unit-tests-ok", algorithm="HS256")

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            await blacklist_access_token(token)
            mock_db.add_to_blacklist.assert_called_once()
            call_args = mock_db.add_to_blacklist.call_args[0]
            assert call_args[0] == "unique-jti-123"  # jti
            assert len(call_args[1]) > 0  # expires_at

    @pytest.mark.asyncio
    async def test_skips_blacklist_when_no_jti(self):
        """Tokens without jti (from create_token) should skip blacklist."""
        mock_db = MagicMock()
        mock_db.add_to_blacklist = AsyncMock()

        # create_token doesn't include jti
        token = create_token(user_id="u1", username="alice")

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            await blacklist_access_token(token)
            mock_db.add_to_blacklist.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_invalid_token(self):
        mock_db = MagicMock()
        mock_db.add_to_blacklist = AsyncMock()

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            await blacklist_access_token("not.a.valid.token")
            mock_db.add_to_blacklist.assert_not_called()

    @pytest.mark.asyncio
    async def test_blacklists_expired_token_with_jti(self):
        """Even expired tokens with jti should be blacklisted (decode without expiry check)."""
        mock_db = MagicMock()
        mock_db.add_to_blacklist = AsyncMock()

        now = int(time.time())
        payload = {
            "sub": "u1",
            "preferred_username": "alice",
            "roles": [],
            "groups": [],
            "access_level": "internal",
            "iat": now - 7200,
            "exp": now - 3600,  # Expired
            "jti": "expired-jti-456",
            "type": "access",
        }
        token = jwt.encode(payload, key="test-secret-key-for-unit-tests-ok", algorithm="HS256")

        with patch("proxy.app.auth.user_db.get_user_db", return_value=mock_db):
            await blacklist_access_token(token)
            mock_db.add_to_blacklist.assert_called_once()


# ── UserContext.effective_namespace ───────────────────────────────────────────


class TestUserContextEffectiveNamespace:
    def test_explicit_namespace(self):
        ctx = UserContext(user_id="u1", username="alice", namespace="eng", groups=["platform"])
        assert ctx.effective_namespace == "eng"

    def test_fallback_to_first_group(self):
        ctx = UserContext(user_id="u1", username="alice", groups=["platform", "devops"])
        assert ctx.effective_namespace == "platform"

    def test_empty_when_no_namespace_or_groups(self):
        ctx = UserContext(user_id="u1", username="alice")
        assert ctx.effective_namespace == ""

    def test_anonymous_falls_back_to_group(self):
        ctx = UserContext.anonymous()
        assert ctx.effective_namespace == "everyone"


# ── create_mock_token ────────────────────────────────────────────────────────


class TestCreateMockToken:
    def test_creates_valid_token(self):
        token = create_mock_token(user_id="mock-1", username="mockuser", roles=["admin"])
        decoded = jwt.decode(
            token,
            key="test-secret-key-for-unit-tests-ok",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert decoded["sub"] == "mock-1"
        assert decoded["preferred_username"] == "mockuser"
        assert decoded["roles"] == ["admin"]

    def test_defaults(self):
        token = create_mock_token()
        decoded = jwt.decode(
            token,
            key="test-secret-key-for-unit-tests-ok",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert decoded["sub"] == "test-user"
        assert decoded["preferred_username"] == "testuser"
        assert decoded["roles"] == ["user"]
        assert decoded["groups"] == ["everyone"]

    def test_custom_secret(self):
        token = create_mock_token(secret="custom-key-for-testing-32chars-ok")
        decoded = jwt.decode(
            token,
            key="custom-key-for-testing-32chars-ok",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert decoded["sub"] == "test-user"

    def test_with_namespace(self):
        token = create_mock_token(namespace="engineering")
        decoded = jwt.decode(
            token,
            key="test-secret-key-for-unit-tests-ok",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert decoded["namespace"] == "engineering"


# ── Keycloak OIDC discovery ─────────────────────────────────────────────────


class TestKeycloakDiscovery:
    def test_fetch_jwks_returns_none_without_keycloak_url(self, monkeypatch):
        monkeypatch.setattr("proxy.app.auth.jwt.KEYCLOAK_URL", "")
        from proxy.app.auth.jwt import _fetch_jwks_oidc

        result = _fetch_jwks_oidc()
        assert result is None

    def test_fetch_jwks_caches_result(self, monkeypatch):
        import proxy.app.auth.jwt as mod

        monkeypatch.setattr("proxy.app.auth.jwt.KEYCLOAK_URL", "http://keycloak:8080")
        monkeypatch.setattr("proxy.app.auth.jwt.KEYCLOAK_REALM", "master")

        # Reset cache
        mod._jwks_cache = None
        mod._jwks_cache_ts = 0.0

        mock_jwks = {"keys": [{"kid": "k1", "kty": "RSA"}]}
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = __import__("json").dumps(mock_jwks).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            from proxy.app.auth.jwt import _fetch_jwks_oidc

            result1 = _fetch_jwks_oidc()
            result2 = _fetch_jwks_oidc()

            # Should be called only once due to caching
            assert mock_urlopen.call_count == 1
            assert result1 == mock_jwks
            assert result2 == mock_jwks

    def test_get_keycloak_verify_key_fallback(self, monkeypatch):
        monkeypatch.setattr("proxy.app.auth.jwt.KEYCLOAK_URL", "")
        monkeypatch.setattr("proxy.app.auth.jwt.JWT_PUBLIC_KEY", "fallback-key")

        from proxy.app.auth.jwt import _get_keycloak_verify_key

        result = _get_keycloak_verify_key(kid="nonexistent")
        assert result == "fallback-key"
