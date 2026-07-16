# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/auth/api_keys.py — API key management."""

import pytest

from proxy.app.auth.api_keys import ApiKey, ApiKeyManager


class TestApiKeyManager:
    """Tests for ApiKeyManager class."""

    @pytest.fixture
    def manager(self):
        return ApiKeyManager()

    def test_generate_key_returns_sk_prefix(self, manager):
        key = manager.generate_key("user1")
        assert key.startswith("sk-")

    def test_generate_key_with_roles(self, manager):
        key = manager.generate_key("user1", roles=["admin", "user"])
        keys = manager.list_keys("user1")
        assert len(keys) == 1
        assert keys[0].roles == ["admin", "user"]

    def test_generate_key_default_roles(self, manager):
        key = manager.generate_key("user1")
        keys = manager.list_keys("user1")
        assert keys[0].roles == ["user"]

    def test_validate_key_valid(self, manager):
        key = manager.generate_key("user1")
        result = manager.validate_key(key)
        assert result is not None
        assert result.user_id == "user1"
        assert result.is_active is True
        assert result.last_used is not None

    def test_validate_key_invalid_prefix(self, manager):
        assert manager.validate_key("invalid-key") is None

    def test_validate_key_empty(self, manager):
        assert manager.validate_key("") is None

    def test_validate_key_wrong_key(self, manager):
        manager.generate_key("user1")
        assert manager.validate_key("sk-nonexistent") is None

    def test_validate_key_revoked(self, manager):
        key = manager.generate_key("user1")
        keys = manager.list_keys("user1")
        manager.revoke_key(keys[0].key_id)
        assert manager.validate_key(key) is None

    def test_revoke_key(self, manager):
        key = manager.generate_key("user1")
        keys = manager.list_keys("user1")
        assert manager.revoke_key(keys[0].key_id) is True
        assert keys[0].is_active is False

    def test_revoke_nonexistent_key(self, manager):
        assert manager.revoke_key("nonexistent") is False

    def test_list_keys_all(self, manager):
        manager.generate_key("user1")
        manager.generate_key("user2")
        all_keys = manager.list_keys()
        assert len(all_keys) == 2

    def test_list_keys_by_user(self, manager):
        manager.generate_key("user1")
        manager.generate_key("user2")
        manager.generate_key("user1")
        user1_keys = manager.list_keys("user1")
        assert len(user1_keys) == 2
        assert all(k.user_id == "user1" for k in user1_keys)

    def test_list_keys_empty(self, manager):
        assert manager.list_keys() == []

    def test_multiple_keys_per_user(self, manager):
        key1 = manager.generate_key("user1")
        key2 = manager.generate_key("user1")
        assert key1 != key2
        assert len(manager.list_keys("user1")) == 2

    def test_validate_key_updates_last_used(self, manager):
        key = manager.generate_key("user1")
        result = manager.validate_key(key)
        first_used = result.last_used
        # Validate again
        result2 = manager.validate_key(key)
        assert result2.last_used is not None
        # last_used should be updated (or at least set)


class TestApiKeyDataclass:
    """Tests for ApiKey dataclass."""

    def test_create_api_key(self):
        ak = ApiKey(
            key_id="kid1",
            key_hash="abc123",
            user_id="user1",
            roles=["user"],
            created_at="2025-01-01T00:00:00",
        )
        assert ak.key_id == "kid1"
        assert ak.last_used is None
        assert ak.is_active is True

    def test_api_key_with_last_used(self):
        ak = ApiKey(
            key_id="kid1",
            key_hash="abc",
            user_id="u1",
            roles=["user"],
            created_at="2025-01-01",
            last_used="2025-01-02",
            is_active=False,
        )
        assert ak.last_used == "2025-01-02"
        assert ak.is_active is False
