# Database Migrations Guide

This guide covers the database migration framework for the RAG System, which manages schema changes for both SQLite (user database) and Neo4j (knowledge graph).

## Overview

The migration framework provides:

- **Version tracking** via `_migrations` table
- **Up/down migrations** for applying and rolling back changes
- **Dry-run mode** for safe previews
- **Audit trail** of all migration operations
- **Idempotent migrations** (safe to re-run)
- **Multi-backend support** (SQLite and Neo4j)

## Quick Start

### Check Migration Status

```bash
python scripts/migrate.py status
```

Output:
```
============================================================
  Database Migration Status
============================================================
  Current Version:    2
  Latest Available:   3
  Applied:            2
  Pending:            1
  Up to Date:         ✗ No
============================================================
```

### Apply Pending Migrations

```bash
# Apply all pending migrations
python scripts/migrate.py upgrade

# Preview what would be applied (dry run)
python scripts/migrate.py upgrade --dry-run

# Apply up to a specific version
python scripts/migrate.py upgrade --target 2
```

### Rollback Migrations

```bash
# Rollback to version 1
python scripts/migrate.py downgrade 1

# Preview rollback (dry run)
python scripts/migrate.py downgrade 1 --dry-run
```

### View Migration History

```bash
python scripts/migrate.py history
```

## Creating New Migrations

### Using the CLI

```bash
python scripts/migrate.py create add_user_preferences
```

This creates a new migration file with the next version number.

### Migration File Structure

```python
# proxy/app/db/migration_004_add_user_preferences.py
"""
Migration 004: Add User Preferences

Adds user preferences table for storing user settings.
"""

from proxy.app.db.migrations import MigrationInfo, register_migration

# ─── Up Migration ────────────────────────────────────────────────────────────

UP_SQL = """
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
"""

# ─── Down Migration ──────────────────────────────────────────────────────────

DOWN_SQL = """
DROP TABLE IF EXISTS user_preferences;
"""

# ─── Migration Registration ──────────────────────────────────────────────────

MIGRATION = MigrationInfo(
    version=4,
    name="add_user_preferences",
    description="Add user preferences table for storing user settings",
    up_sql=UP_SQL,
    down_sql=DOWN_SQL,
    backend="sqlite",
)

# Register when module is imported
register_migration(MIGRATION)
```

### Async Migrations

For complex migrations that need Python logic:

```python
from proxy.app.db.migrations import MigrationInfo, register_migration

async def migrate_up(conn):
    """Custom migration logic."""
    # Get existing data
    cursor = await conn.execute("SELECT id, roles FROM users")
    rows = await cursor.fetchall()
    
    # Transform and update
    for row in rows:
        user_id, roles_json = row
        # ... transformation logic ...
        await conn.execute(
            "UPDATE users SET roles = ? WHERE id = ?",
            (new_roles, user_id)
        )

async def migrate_down(conn):
    """Rollback logic."""
    pass

MIGRATION = MigrationInfo(
    version=5,
    name="migrate_roles",
    description="Migrate roles to new format",
    up_async=migrate_up,
    down_async=migrate_down,
    backend="sqlite",
)

register_migration(MIGRATION)
```

## Neo4j Migrations

For Neo4j schema changes:

```python
from proxy.app.db.migrations import MigrationInfo, register_migration

async def setup_schema(session):
    """Apply Neo4j constraints and indexes."""
    await session.run(
        "CREATE CONSTRAINT entity_id IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.id IS UNIQUE"
    )
    await session.run(
        "CREATE INDEX entity_name IF NOT EXISTS "
        "FOR (e:Entity) ON (e.name)"
    )

async def teardown_schema(session):
    """Remove schema elements."""
    await session.run("DROP CONSTRAINT entity_id IF EXISTS")
    await session.run("DROP INDEX entity_name IF EXISTS")

MIGRATION = MigrationInfo(
    version=6,
    name="neo4j_entity_schema",
    description="Add Entity constraints and indexes",
    up_async=setup_schema,
    down_async=teardown_schema,
    backend="neo4j",
)

register_migration(MIGRATION)
```

## Automatic Migrations on Startup

The application automatically applies pending migrations during startup:

```python
# In proxy/app/main.py lifespan()
from proxy.app.db.migrations import get_migration_manager

migration_manager = get_migration_manager(
    db_path=USER_DB_PATH,
    neo4j_uri=NEO4J_URI if GRAPH_ENABLED else None,
    neo4j_user=NEO4J_USER if GRAPH_ENABLED else None,
    neo4j_password=NEO4J_PASSWORD if GRAPH_ENABLED else None,
)
await migration_manager.initialize()
await migration_manager.upgrade()
```

To disable automatic migrations, set environment variable:

```bash
AUTO_MIGRATE=false
```

## Database Backups

**Always backup before running migrations in production:**

```bash
# SQLite backup
cp ./data/users.db ./data/users.db.backup.$(date +%Y%m%d%H%M%S)

# Neo4j backup (using scripts)
./scripts/ops/backup_neo4j.sh
```

## Migration Best Practices

1. **Keep migrations small** — One logical change per migration
2. **Always provide rollback** — Include `down_sql` or `down_async`
3. **Test migrations** — Use `--dry-run` before applying
4. **Backup first** — Always backup production databases
5. **Idempotent operations** — Use `IF NOT EXISTS` / `IF EXISTS`
6. **Avoid data loss** — Don't drop columns without migration period
7. **Document changes** — Clear description in migration metadata

## Troubleshooting

### Migration Failed

If a migration fails:

1. Check the error message in the output
2. Review the audit log: `python scripts/migrate.py history`
3. Fix the issue and re-run, or rollback:

```bash
# Rollback to previous version
python scripts/migrate.py downgrade <previous_version>
```

### Stuck Migration

If the database is in an inconsistent state:

1. Check `_migrations` table directly
2. Check `_migration_log` for error details
3. Manually fix if needed (with caution)

### Schema Drift

If the database schema doesn't match migrations:

1. Compare actual schema with migration SQL
2. Create a corrective migration
3. Or reset (development only):

```bash
# Development only — drops all data
rm ./data/users.db
python scripts/migrate.py upgrade
```

## API Reference

### MigrationManager

```python
from proxy.app.db.migrations import MigrationManager

manager = MigrationManager(
    db_path="./data/users.db",
    neo4j_uri="bolt://localhost:7687",
    neo4j_user="neo4j",
    neo4j_password="password",
)

await manager.initialize()
await manager.upgrade(dry_run=False, target_version=None)
await manager.downgrade(target_version=1, dry_run=False)
status = await manager.get_status()
log = await manager.get_audit_log(limit=100)
await manager.close()
```

### MigrationInfo

```python
from proxy.app.db.migrations import MigrationInfo

migration = MigrationInfo(
    version=1,                    # Unique version number
    name="initial_schema",        # Migration name
    description="Description",    # Human-readable description
    up_sql="SQL...",              # SQL for upgrade
    down_sql="SQL...",            # SQL for rollback
    up_async=None,                # Async callable for upgrade
    down_async=None,              # Async callable for rollback
    backend="sqlite",             # "sqlite" or "neo4j"
)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USER_DB_PATH` | `./data/users.db` | SQLite database path |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `neo4j` | Neo4j password |
| `GRAPH_ENABLED` | `false` | Enable Neo4j migrations |

## Related Documentation

- [Security Guide](security-guide.md) — Database security best practices
- [Operations Guide](operations-guide.md) — Backup and recovery procedures
- [Configuration Reference](configuration-reference.md) — All configuration options
