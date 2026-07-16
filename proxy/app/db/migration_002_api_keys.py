# proxy/app/db/migration_002_api_keys.py
"""
Migration 002: Add API keys table.

Adds API key management for programmatic access:
- api_keys table for storing hashed API keys
- Support for key scoping (roles, namespaces)
- Expiration and revocation support
- Usage tracking
"""

from proxy.app.db.migrations import MigrationInfo, register_migration

# ─── Up Migration ────────────────────────────────────────────────────────────

UP_SQL = """
-- API Keys table for programmatic access
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    roles TEXT NOT NULL DEFAULT '["user"]',
    namespace TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    expires_at TEXT,
    last_used_at TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Indexes for API keys
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active);
CREATE INDEX IF NOT EXISTS idx_api_keys_expires ON api_keys(expires_at);
"""

# ─── Down Migration ──────────────────────────────────────────────────────────

DOWN_SQL = """
DROP TABLE IF EXISTS api_keys;
"""

# ─── Migration Registration ──────────────────────────────────────────────────

MIGRATION = MigrationInfo(
    version=2,
    name="add_api_keys",
    description="Add api_keys table for programmatic access management",
    up_sql=UP_SQL,
    down_sql=DOWN_SQL,
    backend="sqlite",
)

# Register when module is imported
register_migration(MIGRATION)
