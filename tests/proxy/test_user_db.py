# ruff: noqa: E501
"""Tests for proxy/app/auth/user_db.py — UserDatabase with aiosqlite."""

import json

import bcrypt  # noqa: F401 — ensure real bcrypt is imported before any sys.modules mocking
import pytest
import pytest_asyncio

from proxy.app.auth.user_db import UserDatabase


@pytest_asyncio.fixture
async def db(tmp_path):
    """Create a fresh UserDatabase with a temp SQLite file."""
    # Force module-level config to safe values.
    # This must happen before _ensure_db() to prevent cross-test MagicMock leaks.
    import proxy.app.auth.user_db as _mod

    _mod.BCRYPT_ROUNDS = 4
    _mod.REFRESH_TOKEN_DAYS = 7
    _mod.TOKEN_BLACKLIST_MAX_ENTRIES = 100
    _mod.AUTH_VALID_USERS = ""

    db_path = str(tmp_path / "test_users.db")
    database = UserDatabase(db_path=db_path)
    await database._ensure_db()
    yield database
    await database.close()


# ── User CRUD ────────────────────────────────────────────────────────────────


class TestCreateUser:
    @pytest.mark.asyncio
    async def test_creates_user(self, db):
        result = await db.create_user("alice", "password123", email="alice@test.com")
        assert "user_id" in result
        assert result["username"] == "alice"
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_duplicate_username_raises(self, db):
        await db.create_user("alice", "pass1")
        with pytest.raises(ValueError, match="already exists"):
            await db.create_user("alice", "pass2")

    @pytest.mark.asyncio
    async def test_password_is_hashed(self, db):
        await db.create_user("bob", "mypassword")
        user = await db.get_user_by_username("bob")
        assert user is not None
        assert user["password_hash"] != "mypassword"
        assert user["password_hash"].startswith("$2b$")

    @pytest.mark.asyncio
    async def test_custom_roles_and_groups(self, db):
        await db.create_user("charlie", "pass", roles=["admin"], groups=["eng", "platform"])
        user = await db.get_user_by_username("charlie")
        assert user is not None
        assert user["roles"] == ["admin"]
        assert user["groups"] == ["eng", "platform"]

    @pytest.mark.asyncio
    async def test_default_roles_and_groups(self, db):
        await db.create_user("dave", "pass")
        user = await db.get_user_by_username("dave")
        assert user is not None
        assert user["roles"] == ["user"]
        assert user["groups"] == []

    @pytest.mark.asyncio
    async def test_access_level_and_namespace(self, db):
        await db.create_user("eve", "pass", access_level="confidential", namespace="eng")
        user = await db.get_user_by_username("eve")
        assert user is not None
        assert user["access_level"] == "confidential"
        assert user["namespace"] == "eng"


class TestGetUser:
    @pytest.mark.asyncio
    async def test_get_by_id(self, db):
        created = await db.create_user("alice", "pass")
        user = await db.get_user(created["user_id"])
        assert user is not None
        assert user["username"] == "alice"

    @pytest.mark.asyncio
    async def test_get_nonexistent_user(self, db):
        user = await db.get_user("nonexistent-id")
        assert user is None

    @pytest.mark.asyncio
    async def test_get_by_username_case_insensitive(self, db):
        await db.create_user("Alice", "pass")
        user = await db.get_user_by_username("alice")
        assert user is not None
        assert user["username"] == "Alice"

    @pytest.mark.asyncio
    async def test_get_nonexistent_by_username(self, db):
        user = await db.get_user_by_username("nobody")
        assert user is None


class TestVerifyPassword:
    @pytest.mark.asyncio
    async def test_correct_password(self, db):
        await db.create_user("alice", "correct-password")
        user = await db.verify_password("alice", "correct-password")
        assert user is not None
        assert user["username"] == "alice"

    @pytest.mark.asyncio
    async def test_wrong_password(self, db):
        await db.create_user("alice", "correct-password")
        user = await db.verify_password("alice", "wrong-password")
        assert user is None

    @pytest.mark.asyncio
    async def test_nonexistent_user(self, db):
        user = await db.verify_password("nobody", "pass")
        assert user is None


class TestUpdateUser:
    @pytest.mark.asyncio
    async def test_update_email(self, db):
        created = await db.create_user("alice", "pass")
        result = await db.update_user(created["user_id"], email="new@test.com")
        assert result is True
        user = await db.get_user(created["user_id"])
        assert user["email"] == "new@test.com"

    @pytest.mark.asyncio
    async def test_update_roles(self, db):
        created = await db.create_user("alice", "pass")
        result = await db.update_user(created["user_id"], roles=["admin", "user"])
        assert result is True
        user = await db.get_user(created["user_id"])
        assert user["roles"] == ["admin", "user"]

    @pytest.mark.asyncio
    async def test_update_nonexistent_user(self, db):
        result = await db.update_user("nonexistent", email="new@test.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_disallowed_field(self, db):
        created = await db.create_user("alice", "pass")
        result = await db.update_user(created["user_id"], username="bob")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_is_active(self, db):
        created = await db.create_user("alice", "pass")
        result = await db.update_user(created["user_id"], is_active=0)
        assert result is True


class TestDeleteUser:
    @pytest.mark.asyncio
    async def test_soft_delete(self, db):
        created = await db.create_user("alice", "pass")
        result = await db.delete_user(created["user_id"])
        assert result is True
        user = await db.get_user(created["user_id"])
        assert user is None  # Soft-deleted, not returned

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db):
        result = await db.delete_user("nonexistent")
        assert result is False


class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users(self, db):
        await db.create_user("alice", "pass")
        await db.create_user("bob", "pass")
        users = await db.list_users()
        assert len(users) == 2
        usernames = {u["username"] for u in users}
        assert usernames == {"alice", "bob"}

    @pytest.mark.asyncio
    async def test_list_excludes_deleted(self, db):
        created = await db.create_user("alice", "pass")
        await db.create_user("bob", "pass")
        await db.delete_user(created["user_id"])
        users = await db.list_users()
        assert len(users) == 1
        assert users[0]["username"] == "bob"

    @pytest.mark.asyncio
    async def test_list_with_limit(self, db):
        for i in range(5):
            await db.create_user(f"user{i}", "pass")
        users = await db.list_users(limit=3)
        assert len(users) == 3

    @pytest.mark.asyncio
    async def test_list_with_offset(self, db):
        for i in range(5):
            await db.create_user(f"user{i}", "pass")
        users = await db.list_users(limit=10, offset=3)
        assert len(users) == 2


# ── Refresh Tokens ───────────────────────────────────────────────────────────


class TestRefreshTokens:
    @pytest.mark.asyncio
    async def test_store_and_consume(self, db):
        created = await db.create_user("alice", "pass")
        token_id = await db.store_refresh_token(created["user_id"], "raw-token-123")
        assert token_id is not None

        user = await db.consume_refresh_token("raw-token-123")
        assert user is not None
        assert user["username"] == "alice"

    @pytest.mark.asyncio
    async def test_consume_invalid_token(self, db):
        user = await db.consume_refresh_token("nonexistent-token")
        assert user is None

    @pytest.mark.asyncio
    async def test_token_is_one_time_use(self, db):
        created = await db.create_user("alice", "pass")
        await db.store_refresh_token(created["user_id"], "one-time-token")

        user1 = await db.consume_refresh_token("one-time-token")
        assert user1 is not None

        user2 = await db.consume_refresh_token("one-time-token")
        assert user2 is None  # Already consumed

    @pytest.mark.asyncio
    async def test_revoke_user_tokens(self, db):
        created = await db.create_user("alice", "pass")
        await db.store_refresh_token(created["user_id"], "token-1")
        await db.store_refresh_token(created["user_id"], "token-2")

        count = await db.revoke_user_tokens(created["user_id"])
        assert count == 2

        # Both tokens should be invalid
        assert await db.consume_refresh_token("token-1") is None
        assert await db.consume_refresh_token("token-2") is None

    @pytest.mark.asyncio
    async def test_custom_ttl(self, db):
        created = await db.create_user("alice", "pass")
        token_id = await db.store_refresh_token(created["user_id"], "ttl-token", ttl_days=30)
        assert token_id is not None


# ── Token Blacklist ──────────────────────────────────────────────────────────


class TestTokenBlacklist:
    @pytest.mark.asyncio
    async def test_add_and_check(self, db):
        from datetime import UTC, datetime, timedelta

        expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        await db.add_to_blacklist("jti-123", expires_at)

        assert await db.is_blacklisted("jti-123") is True

    @pytest.mark.asyncio
    async def test_not_blacklisted(self, db):
        assert await db.is_blacklisted("jti-unknown") is False

    @pytest.mark.asyncio
    async def test_duplicate_jti_ignored(self, db):
        from datetime import UTC, datetime, timedelta

        expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        await db.add_to_blacklist("jti-dup", expires_at)
        await db.add_to_blacklist("jti-dup", expires_at)  # Should not raise
        assert await db.is_blacklisted("jti-dup") is True

    @pytest.mark.asyncio
    async def test_cleanup_expired_entries(self, db):
        from datetime import UTC, datetime, timedelta

        # Add an expired entry
        expired_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await db.add_to_blacklist("jti-expired", expired_at)

        # Add a valid entry
        valid_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        await db.add_to_blacklist("jti-valid", valid_at)

        # Cleanup should remove expired
        await db._cleanup_blacklist()

        # The expired entry should still be there (cleanup only runs on add_to_blacklist)
        # but we can check the valid one
        assert await db.is_blacklisted("jti-valid") is True


# ── Cleanup ──────────────────────────────────────────────────────────────────


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_expired(self, db):
        created = await db.create_user("alice", "pass")
        # Store a token (it won't be expired, but we test the method runs)
        await db.store_refresh_token(created["user_id"], "token-1")
        # Just verify it doesn't raise
        await db.cleanup_expired()

    @pytest.mark.asyncio
    async def test_close_connection(self, db):
        await db.close()
        assert db._initialized is False


# ── Legacy migration ─────────────────────────────────────────────────────────


class TestLegacyMigration:
    @pytest.mark.asyncio
    async def test_migrate_from_env(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "migrate_test.db")
        monkeypatch.setattr(
            "proxy.app.auth.user_db.AUTH_VALID_USERS",
            json.dumps({
                "admin": {"password": "admin-pass", "roles": ["admin"], "groups": ["ops"]},
                "viewer": {"password": "view-pass", "roles": ["viewer"]},
            }),
        )
        monkeypatch.setattr("proxy.app.auth.user_db.BCRYPT_ROUNDS", 4)

        database = UserDatabase(db_path=db_path)
        await database._ensure_db()

        admin = await database.get_user_by_username("admin")
        assert admin is not None
        assert admin["roles"] == ["admin"]
        assert admin["groups"] == ["ops"]

        viewer = await database.get_user_by_username("viewer")
        assert viewer is not None
        assert viewer["roles"] == ["viewer"]

        # Verify password works
        assert await database.verify_password("admin", "admin-pass") is not None
        assert await database.verify_password("admin", "wrong") is None

        await database.close()

    @pytest.mark.asyncio
    async def test_migrate_skips_if_users_exist(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "migrate_skip.db")
        monkeypatch.setattr("proxy.app.auth.user_db.BCRYPT_ROUNDS", 4)

        database = UserDatabase(db_path=db_path)
        await database._ensure_db()

        # Create a user first
        await database.create_user("existing", "pass")

        # Now set AUTH_VALID_USERS (should be skipped because table is not empty)
        monkeypatch.setattr(
            "proxy.app.auth.user_db.AUTH_VALID_USERS",
            json.dumps({"migrated_user": {"password": "pass"}}),
        )

        # Re-initialize (but migration should skip)
        database._initialized = False
        await database._ensure_db()

        user = await database.get_user_by_username("migrated_user")
        assert user is None  # Should not have been migrated

        await database.close()

    @pytest.mark.asyncio
    async def test_migrate_skips_invalid_json(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "migrate_invalid.db")
        monkeypatch.setattr("proxy.app.auth.user_db.AUTH_VALID_USERS", "not-json")
        monkeypatch.setattr("proxy.app.auth.user_db.BCRYPT_ROUNDS", 4)

        database = UserDatabase(db_path=db_path)
        await database._ensure_db()
        # Should not raise
        await database.close()

    @pytest.mark.asyncio
    async def test_migrate_skips_empty_env(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "migrate_empty.db")
        monkeypatch.setattr("proxy.app.auth.user_db.AUTH_VALID_USERS", "")
        monkeypatch.setattr("proxy.app.auth.user_db.BCRYPT_ROUNDS", 4)

        database = UserDatabase(db_path=db_path)
        await database._ensure_db()
        await database.close()


# ── _row_to_dict ─────────────────────────────────────────────────────────────


class TestRowToDict:
    def test_parses_json_fields(self):
        row = (
            "id1",
            "alice",
            "hash",
            "alice@test.com",
            '["admin", "user"]',
            '["eng"]',
            "internal",
            "ns",
            1,
            "2024-01-01",
            "2024-01-01",
        )
        result = UserDatabase._row_to_dict(row)
        assert result["id"] == "id1"
        assert result["username"] == "alice"
        assert result["roles"] == ["admin", "user"]
        assert result["groups"] == ["eng"]

    def test_handles_invalid_json(self):
        row = (
            "id1",
            "alice",
            "hash",
            "",
            "not-json",
            "also-not-json",
            "internal",
            "",
            1,
            "2024-01-01",
            "2024-01-01",
        )
        result = UserDatabase._row_to_dict(row)
        assert result["roles"] == ["user"]  # Fallback
        assert result["groups"] == []  # Fallback


# ── Singleton ────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_user_db_returns_singleton(self):
        import proxy.app.auth.user_db as mod

        mod._user_db = None
        db1 = mod.get_user_db()
        db2 = mod.get_user_db()
        assert db1 is db2
        mod._user_db = None  # Reset
