# proxy/app/user_db.py
"""SQLite-backed user database for the RAG proxy.

Provides:
- User CRUD (create, get, update, delete, list)
- bcrypt password hashing and verification
- Refresh token storage and revocation
- Token blacklist with TTL-based cleanup
- Auto-migration from AUTH_VALID_USERS env var on first start

All operations are async via aiosqlite.
Single-worker safe (WORKERS=1); WAL mode enabled for future multi-worker safety.
"""

import hashlib
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import bcrypt

from proxy.app.shared.config import (
    AUTH_VALID_USERS,
    BCRYPT_ROUNDS,
    REFRESH_TOKEN_DAYS,
    TOKEN_BLACKLIST_MAX_ENTRIES,
    USER_DB_PATH,
)

logger = logging.getLogger(__name__)

# ─── Schema ──────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    email TEXT,
    roles TEXT NOT NULL DEFAULT '["user"]',
    groups TEXT NOT NULL DEFAULT '[]',
    access_level TEXT NOT NULL DEFAULT 'user',
    namespace TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires ON refresh_tokens(expires_at);

CREATE TABLE IF NOT EXISTS token_blacklist (
    jti TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    blacklisted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_blacklist_expires ON token_blacklist(expires_at);

CREATE TABLE IF NOT EXISTS password_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_history_user ON password_history(user_id);
CREATE INDEX IF NOT EXISTS idx_password_history_created ON password_history(created_at);
"""


# ─── Database Manager ────────────────────────────────────────────────────────


class UserDatabase:
    """Async SQLite user database with bcrypt password hashing."""

    def __init__(self, db_path: str = USER_DB_PATH):
        self._db_path = db_path
        self._initialized = False

    async def _ensure_db(self) -> None:
        """Lazy initialization: create directory, execute schema, migrate legacy users."""
        if self._initialized:
            return

        import aiosqlite

        # Ensure data directory exists
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

        # One-time migration: import users from AUTH_VALID_USERS env var
        await self._migrate_legacy_users()

        self._initialized = True
        logger.info("User database initialized at %s", self._db_path)

    async def _migrate_legacy_users(self) -> None:
        """Import users from AUTH_VALID_USERS JSON env var into SQLite.

        Only runs if the users table is empty and AUTH_VALID_USERS is set.
        """
        raw = AUTH_VALID_USERS
        if not raw or raw in ("{}", ""):
            return

        # Check if users table is empty
        cursor = await self._conn.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        if row and row[0] > 0:
            return  # Already has users, skip migration

        try:
            legacy_users = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid AUTH_VALID_USERS JSON, skipping migration")
            return

        if not isinstance(legacy_users, dict):
            return

        now = datetime.now(UTC).isoformat()
        count = 0

        for username, user_data in legacy_users.items():
            if not isinstance(user_data, dict):
                continue

            password = user_data.get("password", "")
            user_id = user_data.get("user_id", hashlib.sha256(username.encode()).hexdigest()[:16])
            roles = json.dumps(user_data.get("roles", ["user"]))
            groups = json.dumps(user_data.get("groups", []))
            access_level = user_data.get("access_level", "user")
            namespace = user_data.get("namespace", "")
            email = user_data.get("email", "")

            password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode(
                "utf-8",
            )

            try:
                await self._conn.execute(
                    """INSERT OR IGNORE INTO users
                       (id, username, password_hash, email, roles, groups,
                        access_level, namespace, is_active, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    (user_id, username, password_hash, email, roles, groups, access_level, namespace, now, now),
                )
                count += 1
            except Exception:
                logger.warning("Failed to migrate user '%s'", username, exc_info=True)

        if count:
            await self._conn.commit()
            logger.info("Migrated %d users from AUTH_VALID_USERS to SQLite", count)

    # ── User CRUD ────────────────────────────────────────────────────────────

    async def create_user(
        self,
        username: str,
        password: str,
        email: str = "",
        roles: list[str] | None = None,
        groups: list[str] | None = None,
        access_level: str = "user",
        namespace: str = "",
    ) -> dict[str, Any]:
        """Create a new user with bcrypt-hashed password.

        Returns:
            dict with user_id, username, created_at.

        Raises:
            ValueError if username already exists.

        """
        await self._ensure_db()

        user_id = hashlib.sha256(f"{username}:{time.time()}".encode()).hexdigest()[:24]
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")
        now = datetime.now(UTC).isoformat()
        roles_json = json.dumps(roles or ["user"])
        groups_json = json.dumps(groups or [])

        try:
            await self._conn.execute(
                """INSERT INTO users
                   (id, username, password_hash, email, roles, groups,
                    access_level, namespace, is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (user_id, username, password_hash, email, roles_json, groups_json, access_level, namespace, now, now),
            )
            await self._conn.commit()
        except Exception as e:
            if "UNIQUE" in str(e).upper():
                raise ValueError(f"Username '{username}' already exists") from e
            raise

        logger.info("User created: %s (id=%s)", username, user_id)
        return {"user_id": user_id, "username": username, "created_at": now}

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Get user by ID."""
        await self._ensure_db()
        cursor = await self._conn.execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,))
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        """Get user by username (case-insensitive)."""
        await self._ensure_db()
        cursor = await self._conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND is_active = 1",
            (username,),
        )
        row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def verify_password(self, username: str, password: str) -> dict[str, Any] | None:
        """Verify password for a user. Returns user dict or None."""
        user = await self.get_user_by_username(username)
        if not user:
            return None

        stored_hash = user["password_hash"].encode("utf-8")
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash):
            return user
        return None

    async def update_user(self, user_id: str, **fields: Any) -> bool:
        """Update user fields. Returns True if updated."""
        await self._ensure_db()

        allowed = {"email", "roles", "groups", "access_level", "namespace", "is_active"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False

        updates["updated_at"] = datetime.now(UTC).isoformat()

        # Handle JSON fields
        for json_field in ("roles", "groups"):
            if json_field in updates and not isinstance(updates[json_field], str):
                updates[json_field] = json.dumps(updates[json_field])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]

        cursor = await self._conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", values)
        await self._conn.commit()
        return cursor.rowcount > 0

    async def delete_user(self, user_id: str) -> bool:
        """Soft-delete a user (set is_active=0)."""
        await self._ensure_db()
        cursor = await self._conn.execute(
            "UPDATE users SET is_active = 0, updated_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), user_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def list_users(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """List active users."""
        await self._ensure_db()
        cursor = await self._conn.execute(
            "SELECT * FROM users WHERE is_active = 1 ORDER BY username LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── Refresh Tokens ───────────────────────────────────────────────────────

    async def store_refresh_token(self, user_id: str, raw_token: str, ttl_days: int | None = None) -> str:
        """Store a refresh token. Returns the token ID."""
        await self._ensure_db()

        ttl = ttl_days or REFRESH_TOKEN_DAYS
        import secrets as _secrets

        token_id = _secrets.token_hex(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        now = datetime.now(UTC)
        expires_at = (now + timedelta(days=ttl)).isoformat()

        await self._conn.execute(
            """INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (token_id, user_id, token_hash, expires_at, now.isoformat()),
        )
        await self._conn.commit()
        return token_id

    async def consume_refresh_token(self, raw_token: str) -> dict[str, Any] | None:
        """Validate and consume a refresh token. Returns user dict or None."""
        await self._ensure_db()

        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        now = datetime.now(UTC).isoformat()

        cursor = await self._conn.execute(
            """SELECT rt.id, rt.user_id, rt.expires_at
               FROM refresh_tokens rt
               WHERE rt.token_hash = ? AND rt.revoked = 0 AND rt.expires_at > ?""",
            (token_hash, now),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        token_id, user_id, _ = row

        # Mark as revoked (one-time use)
        await self._conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE id = ?", (token_id,))
        await self._conn.commit()

        # Get user
        return await self.get_user(user_id)

    async def revoke_user_tokens(self, user_id: str) -> int:
        """Revoke all refresh tokens for a user. Returns count."""
        await self._ensure_db()
        cursor = await self._conn.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        )
        await self._conn.commit()
        return cursor.rowcount

    # ── Token Blacklist ──────────────────────────────────────────────────────

    async def add_to_blacklist(self, jti: str, expires_at: str) -> None:
        """Add a JWT ID to the blacklist."""
        await self._ensure_db()
        now = datetime.now(UTC).isoformat()

        await self._conn.execute(
            "INSERT OR IGNORE INTO token_blacklist (jti, expires_at, blacklisted_at) VALUES (?, ?, ?)",
            (jti, expires_at, now),
        )
        await self._conn.commit()

        # Periodic cleanup: keep only non-expired + max entries
        await self._cleanup_blacklist()

    async def is_blacklisted(self, jti: str) -> bool:
        """Check if a JWT ID is blacklisted."""
        await self._ensure_db()
        cursor = await self._conn.execute("SELECT 1 FROM token_blacklist WHERE jti = ?", (jti,))
        row = await cursor.fetchone()
        return row is not None

    async def _cleanup_blacklist(self) -> None:
        """Remove expired blacklist entries. Limit total entries."""
        now = datetime.now(UTC).isoformat()

        # Remove expired
        await self._conn.execute("DELETE FROM token_blacklist WHERE expires_at < ?", (now,))

        # Enforce max entries
        cursor = await self._conn.execute("SELECT COUNT(*) FROM token_blacklist")
        row = await cursor.fetchone()
        if row and row[0] > TOKEN_BLACKLIST_MAX_ENTRIES:
            # Delete oldest entries beyond the limit
            excess = row[0] - TOKEN_BLACKLIST_MAX_ENTRIES
            await self._conn.execute(
                """DELETE FROM token_blacklist WHERE jti IN
                   (SELECT jti FROM token_blacklist ORDER BY blacklisted_at ASC LIMIT ?)""",
                (excess,),
            )

        await self._conn.commit()

    # ── Password History ─────────────────────────────────────────────────────

    async def add_password_to_history(self, user_id: str, password_hash: str) -> None:
        """Record a password hash in the user's password history."""
        await self._ensure_db()
        now = datetime.now(UTC).isoformat()
        await self._conn.execute(
            "INSERT INTO password_history (user_id, password_hash, created_at) VALUES (?, ?, ?)",
            (user_id, password_hash, now),
        )
        await self._conn.commit()

    async def get_password_history(self, user_id: str, limit: int = 10) -> list[str]:
        """Get the most recent password hashes for a user.

        Returns list of password_hash strings, most recent first.
        """
        await self._ensure_db()
        cursor = await self._conn.execute(
            "SELECT password_hash FROM password_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def is_password_reused(self, user_id: str, new_password: str, max_history: int = 5) -> bool:
        """Check if a password has been used before within the history window.

        Returns True if the password matches any in the user's history.
        """
        history = await self.get_password_history(user_id, limit=max_history)
        return any(bcrypt.checkpw(new_password.encode("utf-8"), old_hash.encode("utf-8")) for old_hash in history)

    async def clear_password_history(self, user_id: str) -> int:
        """Delete all password history for a user. Returns count of deleted entries."""
        await self._ensure_db()
        cursor = await self._conn.execute(
            "DELETE FROM password_history WHERE user_id = ?",
            (user_id,),
        )
        await self._conn.commit()
        return cursor.rowcount

    async def cleanup_old_password_history(self, max_entries_per_user: int = 20) -> int:
        """Keep only the most recent entries per user. Returns total deleted."""
        await self._ensure_db()
        cursor = await self._conn.execute(
            """DELETE FROM password_history WHERE id NOT IN (
                SELECT id FROM password_history ph2
                WHERE ph2.user_id = password_history.user_id
                ORDER BY ph2.created_at DESC
                LIMIT ?
            )""",
            (max_entries_per_user,),
        )
        await self._conn.commit()
        return cursor.rowcount

    # ── Cleanup ──────────────────────────────────────────────────────────────

    async def cleanup_expired(self) -> None:
        """Periodic cleanup of expired refresh tokens."""
        await self._ensure_db()
        now = datetime.now(UTC).isoformat()

        await self._conn.execute("DELETE FROM refresh_tokens WHERE expires_at < ?", (now,))
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if hasattr(self, "_conn") and self._conn:
            await self._conn.close()
            self._initialized = False

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a SQLite row to a dict with parsed JSON fields."""
        columns = [
            "id",
            "username",
            "password_hash",
            "email",
            "roles",
            "groups",
            "access_level",
            "namespace",
            "is_active",
            "created_at",
            "updated_at",
        ]
        result = dict(zip(columns, row, strict=False))

        # Parse JSON fields
        for field in ("roles", "groups"):
            try:
                result[field] = json.loads(result[field])
            except (json.JSONDecodeError, TypeError):
                result[field] = [] if field == "groups" else ["user"]

        return result


# ─── Singleton ───────────────────────────────────────────────────────────────

_user_db: UserDatabase | None = None


def get_user_db() -> UserDatabase:
    """Get or create the singleton UserDatabase instance."""
    global _user_db
    if _user_db is None:
        _user_db = UserDatabase()
    return _user_db
