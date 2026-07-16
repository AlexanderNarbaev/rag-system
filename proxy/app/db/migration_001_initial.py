# proxy/app/db/migration_001_initial.py
"""
Migration 001: Initial schema — baseline for existing databases.

This migration captures the existing schema from user_db.py as the baseline.
For databases that already exist, this migration will be recorded as applied
without modifying the schema (idempotent).

Tables:
- users: User accounts with bcrypt password hashing
- refresh_tokens: JWT refresh token storage
- token_blacklist: Revoked JWT tokens
"""

from proxy.app.db.migrations import MigrationInfo, register_migration

# ─── Up Migration ────────────────────────────────────────────────────────────

UP_SQL = """
-- Users table
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

-- Refresh tokens table
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);

-- Indexes for refresh_tokens
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires ON refresh_tokens(expires_at);

-- Token blacklist table
CREATE TABLE IF NOT EXISTS token_blacklist (
    jti TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    blacklisted_at TEXT NOT NULL
);

-- Index for blacklist cleanup
CREATE INDEX IF NOT EXISTS idx_blacklist_expires ON token_blacklist(expires_at);
"""

# ─── Down Migration ──────────────────────────────────────────────────────────

DOWN_SQL = """
DROP TABLE IF EXISTS token_blacklist;
DROP TABLE IF EXISTS refresh_tokens;
DROP TABLE IF EXISTS users;
"""

# ─── Async Migration (for existing DB detection) ─────────────────────────────


async def check_existing_schema(conn) -> None:
    """Check if tables already exist and skip creation if so.

    This makes the migration idempotent for existing databases.
    """
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    )
    exists = await cursor.fetchone()
    if exists:
        # Tables already exist — this is an existing database
        # The IF NOT EXISTS clauses in UP_SQL handle idempotency
        pass


# ─── Migration Registration ──────────────────────────────────────────────────

MIGRATION = MigrationInfo(
    version=1,
    name="initial_schema",
    description="Baseline schema: users, refresh_tokens, token_blacklist tables",
    up_sql=UP_SQL,
    down_sql=DOWN_SQL,
    up_async=check_existing_schema,
    backend="sqlite",
)

# Register when module is imported
register_migration(MIGRATION)
