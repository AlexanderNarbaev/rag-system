# proxy/app/db/migrations.py
"""
Database migration framework for the RAG System.

Provides:
- MigrationManager for SQLite and Neo4j schema management
- Version tracking via `_migrations` table
- Up/down migrations with rollback support
- Dry-run mode for safe previews
- Audit trail of all migration operations
- Idempotent migrations (safe to re-run)

Usage:
    from proxy.app.db.migrations import MigrationManager

    manager = MigrationManager(db_path="./data/users.db")
    await manager.initialize()
    await manager.upgrade()

    # Or with dry-run
    await manager.upgrade(dry_run=True)

    # Rollback to version 1
    await manager.downgrade(target_version=1)
"""

import importlib
import logging
import pkgutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# ─── Migration Registry ──────────────────────────────────────────────────────


@dataclass
class MigrationInfo:
    """Metadata for a single migration."""

    version: int
    name: str
    description: str
    up_sql: str = ""
    down_sql: str = ""
    up_async: Any = None  # Optional async callable
    down_async: Any = None  # Optional async callable
    backend: str = "sqlite"  # "sqlite" or "neo4j"


# Global migration registry
_migration_registry: dict[int, MigrationInfo] = {}


def register_migration(migration: MigrationInfo) -> None:
    """Register a migration in the global registry."""
    if migration.version in _migration_registry:
        raise ValueError(f"Migration version {migration.version} already registered")
    _migration_registry[migration.version] = migration


def get_registered_migrations() -> dict[int, MigrationInfo]:
    """Return all registered migrations."""
    return dict(_migration_registry)


def clear_registry() -> None:
    """Clear the migration registry (for testing)."""
    _migration_registry.clear()


# ─── Migration Discovery ─────────────────────────────────────────────────────


def discover_migrations(package_path: str | None = None) -> None:
    """Auto-discover and load migration modules from the db package.

    Migration modules must be named `migration_NNN_*.py` and contain
    a `MIGRATION` attribute of type `MigrationInfo`.
    """
    if package_path is None:
        package_path = str(Path(__file__).parent)

    package = Path(package_path)
    for _finder, name, _is_pkg in pkgutil.iter_modules([str(package)]):
        if name.startswith("migration_"):
            try:
                module = importlib.import_module(f"proxy.app.db.{name}")
                if hasattr(module, "MIGRATION"):
                    migration = module.MIGRATION
                    if isinstance(migration, MigrationInfo) and migration.version not in _migration_registry:
                        register_migration(migration)
                        logger.debug("Discovered migration: v%d - %s", migration.version, migration.name)
            except Exception as e:
                logger.warning("Failed to load migration module '%s': %s", name, e)


# ─── Migration Manager ───────────────────────────────────────────────────────


@dataclass
class MigrationRecord:
    """Record of an applied migration."""

    version: int
    name: str
    applied_at: str
    execution_ms: float
    checksum: str = ""


class MigrationManager:
    """Manages database migrations with version tracking and rollback support.

    Features:
    - Version tracking in `_migrations` table
    - Up/down migrations
    - Dry-run mode
    - Rollback support
    - Audit trail
    - Idempotent operations
    """

    def __init__(
        self,
        db_path: str = "./data/users.db",
        neo4j_uri: str | None = None,
        neo4j_user: str | None = None,
        neo4j_password: str | None = None,
    ):
        self._db_path = db_path
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._conn: aiosqlite.Connection | None = None
        self._initialized = False
        self._neo4j_driver: Any = None

    async def initialize(self) -> None:
        """Initialize the migration manager and ensure tracking table exists."""
        if self._initialized:
            return

        # Ensure data directory exists
        db_dir = Path(self._db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # Connect to SQLite
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

        # Create migration tracking table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL,
                execution_ms REAL NOT NULL DEFAULT 0,
                checksum TEXT NOT NULL DEFAULT '',
                backend TEXT NOT NULL DEFAULT 'sqlite'
            )
        """)

        # Create migration audit log
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS _migration_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                executed_at TEXT NOT NULL,
                execution_ms REAL NOT NULL DEFAULT 0,
                success INTEGER NOT NULL DEFAULT 1,
                error_message TEXT
            )
        """)

        await self._conn.commit()

        # Discover available migrations
        discover_migrations()

        # Initialize Neo4j driver if configured
        if self._neo4j_uri:
            try:
                import importlib.util

                neo4j_spec = importlib.util.find_spec("neo4j")
                if neo4j_spec is not None:
                    from neo4j import AsyncGraphDatabase

                    self._neo4j_driver = AsyncGraphDatabase.driver(
                        self._neo4j_uri,
                        auth=(self._neo4j_user, self._neo4j_password) if self._neo4j_user else None,
                    )
                    logger.info("Neo4j driver initialized for migrations")
                else:
                    logger.warning("neo4j package not installed — Neo4j migrations disabled")
            except ImportError:
                logger.warning("neo4j package not installed — Neo4j migrations disabled")
            except Exception as e:
                logger.warning("Neo4j connection failed: %s — Neo4j migrations disabled", e)

        self._initialized = True
        logger.info("MigrationManager initialized (db=%s)", self._db_path)

    async def close(self) -> None:
        """Close database connections."""
        if self._conn:
            await self._conn.close()
            self._conn = None
        if self._neo4j_driver:
            await self._neo4j_driver.close()
            self._neo4j_driver = None
        self._initialized = False

    # ── Version Tracking ────────────────────────────────────────────────────

    async def current_version(self) -> int:
        """Get the current migration version."""
        await self.initialize()
        assert self._conn is not None

        cursor = await self._conn.execute("SELECT MAX(version) FROM _migrations")
        row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else 0

    async def pending_migrations(self) -> list[MigrationInfo]:
        """Get list of pending (unapplied) migrations."""
        await self.initialize()
        assert self._conn is not None

        cursor = await self._conn.execute("SELECT version FROM _migrations ORDER BY version")
        applied = {row[0] for row in await cursor.fetchall()}

        all_migrations = get_registered_migrations()
        pending = [m for v, m in sorted(all_migrations.items()) if v not in applied]
        return pending

    async def applied_migrations(self) -> list[MigrationRecord]:
        """Get list of all applied migrations."""
        await self.initialize()
        assert self._conn is not None

        cursor = await self._conn.execute(
            "SELECT version, name, applied_at, execution_ms, checksum FROM _migrations ORDER BY version"
        )
        rows = await cursor.fetchall()
        return [
            MigrationRecord(
                version=row[0],
                name=row[1],
                applied_at=row[2],
                execution_ms=row[3],
                checksum=row[4],
            )
            for row in rows
        ]

    async def get_status(self) -> dict[str, Any]:
        """Get comprehensive migration status."""
        current = await self.current_version()
        pending = await self.pending_migrations()
        applied = await self.applied_migrations()
        all_migrations = get_registered_migrations()

        return {
            "current_version": current,
            "latest_available": max(all_migrations.keys()) if all_migrations else 0,
            "applied_count": len(applied),
            "pending_count": len(pending),
            "pending_versions": [m.version for m in pending],
            "applied": [
                {
                    "version": r.version,
                    "name": r.name,
                    "applied_at": r.applied_at,
                    "execution_ms": r.execution_ms,
                }
                for r in applied
            ],
            "is_up_to_date": len(pending) == 0,
        }

    # ── Upgrade (Apply Migrations) ──────────────────────────────────────────

    async def upgrade(
        self,
        target_version: int | None = None,
        dry_run: bool = False,
    ) -> list[MigrationRecord]:
        """Apply pending migrations up to target version.

        Args:
            target_version: Apply up to this version (None = all pending)
            dry_run: If True, only show what would be done without executing

        Returns:
            List of applied migration records
        """
        await self.initialize()
        assert self._conn is not None

        pending = await self.pending_migrations()
        if target_version is not None:
            pending = [m for m in pending if m.version <= target_version]

        if not pending:
            logger.info("No pending migrations")
            return []

        if dry_run:
            logger.info("DRY RUN: Would apply %d migration(s):", len(pending))
            for m in pending:
                logger.info("  v%d: %s — %s", m.version, m.name, m.description)
            return []

        applied = []
        for migration in pending:
            record = await self._apply_migration(migration)
            applied.append(record)

        return applied

    async def _apply_migration(self, migration: MigrationInfo) -> MigrationRecord:
        """Apply a single migration."""
        assert self._conn is not None

        start_time = time.monotonic()
        now = datetime.now(UTC).isoformat()

        logger.info("Applying migration v%d: %s", migration.version, migration.name)

        try:
            # Execute migration
            if migration.backend == "sqlite":
                if migration.up_sql:
                    await self._conn.executescript(migration.up_sql)
                if migration.up_async:
                    await migration.up_async(self._conn)
            elif migration.backend == "neo4j":
                if migration.up_async and self._neo4j_driver:
                    async with self._neo4j_driver.session() as session:
                        await migration.up_async(session)

            execution_ms = (time.monotonic() - start_time) * 1000

            # Record migration
            await self._conn.execute(
                """INSERT INTO _migrations (version, name, description, applied_at, execution_ms, backend)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (migration.version, migration.name, migration.description, now, execution_ms, migration.backend),
            )

            # Audit log
            await self._conn.execute(
                """INSERT INTO _migration_log (version, action, details, executed_at, execution_ms, success)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (migration.version, "upgrade", f"Applied: {migration.name}", now, execution_ms),
            )

            await self._conn.commit()

            record = MigrationRecord(
                version=migration.version,
                name=migration.name,
                applied_at=now,
                execution_ms=execution_ms,
            )

            logger.info(
                "Migration v%d applied successfully (%.1fms)",
                migration.version,
                execution_ms,
            )
            return record

        except Exception as e:
            execution_ms = (time.monotonic() - start_time) * 1000

            # Log failure
            await self._conn.execute(
                """INSERT INTO _migration_log
                   (version, action, details, executed_at, execution_ms, success, error_message)
                   VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (migration.version, "upgrade_failed", f"Failed: {migration.name}", now, execution_ms, str(e)),
            )
            await self._conn.commit()

            logger.error("Migration v%d failed: %s", migration.version, e)
            raise RuntimeError(f"Migration v{migration.version} failed: {e}") from e

    # ── Downgrade (Rollback) ────────────────────────────────────────────────

    async def downgrade(
        self,
        target_version: int,
        dry_run: bool = False,
    ) -> list[MigrationRecord]:
        """Rollback migrations to target version.

        Args:
            target_version: Rollback to this version (inclusive)
            dry_run: If True, only show what would be done

        Returns:
            List of rolled-back migration records
        """
        await self.initialize()
        assert self._conn is not None

        current = await self.current_version()
        if target_version >= current:
            logger.info("Already at or below target version %d", target_version)
            return []

        # Get migrations to rollback (in reverse order)
        cursor = await self._conn.execute(
            "SELECT version FROM _migrations WHERE version > ? ORDER BY version DESC",
            (target_version,),
        )
        versions_to_rollback = [row[0] for row in await cursor.fetchall()]

        if not versions_to_rollback:
            logger.info("No migrations to rollback")
            return []

        if dry_run:
            logger.info("DRY RUN: Would rollback %d migration(s):", len(versions_to_rollback))
            for v in versions_to_rollback:
                migration = get_registered_migrations().get(v)
                if migration:
                    logger.info("  v%d: %s", v, migration.name)
            return []

        rolled_back = []
        for version in versions_to_rollback:
            migration = get_registered_migrations().get(version)
            if migration:
                record = await self._rollback_migration(migration)
                rolled_back.append(record)

        return rolled_back

    async def _rollback_migration(self, migration: MigrationInfo) -> MigrationRecord:
        """Rollback a single migration."""
        assert self._conn is not None

        start_time = time.monotonic()
        now = datetime.now(UTC).isoformat()

        logger.info("Rolling back migration v%d: %s", migration.version, migration.name)

        try:
            # Execute rollback
            if migration.backend == "sqlite":
                if migration.down_sql:
                    await self._conn.executescript(migration.down_sql)
                if migration.down_async:
                    await migration.down_async(self._conn)
            elif migration.backend == "neo4j":
                if migration.down_async and self._neo4j_driver:
                    async with self._neo4j_driver.session() as session:
                        await migration.down_async(session)

            execution_ms = (time.monotonic() - start_time) * 1000

            # Remove migration record
            await self._conn.execute(
                "DELETE FROM _migrations WHERE version = ?",
                (migration.version,),
            )

            # Audit log
            await self._conn.execute(
                """INSERT INTO _migration_log (version, action, details, executed_at, execution_ms, success)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (migration.version, "downgrade", f"Rolled back: {migration.name}", now, execution_ms),
            )

            await self._conn.commit()

            record = MigrationRecord(
                version=migration.version,
                name=migration.name,
                applied_at=now,
                execution_ms=execution_ms,
            )

            logger.info(
                "Migration v%d rolled back successfully (%.1fms)",
                migration.version,
                execution_ms,
            )
            return record

        except Exception as e:
            execution_ms = (time.monotonic() - start_time) * 1000

            # Log failure
            await self._conn.execute(
                """INSERT INTO _migration_log
                   (version, action, details, executed_at, execution_ms, success, error_message)
                   VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (
                    migration.version,
                    "downgrade_failed",
                    f"Failed rollback: {migration.name}",
                    now,
                    execution_ms,
                    str(e),
                ),
            )
            await self._conn.commit()

            logger.error("Migration v%d rollback failed: %s", migration.version, e)
            raise RuntimeError(f"Migration v{migration.version} rollback failed: {e}") from e

    # ── Audit Trail ─────────────────────────────────────────────────────────

    async def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get migration audit log."""
        await self.initialize()
        assert self._conn is not None

        cursor = await self._conn.execute(
            """SELECT version, action, details, executed_at, execution_ms, success, error_message
               FROM _migration_log
               ORDER BY id DESC
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "version": row[0],
                "action": row[1],
                "details": row[2],
                "executed_at": row[3],
                "execution_ms": row[4],
                "success": bool(row[5]),
                "error_message": row[6],
            }
            for row in rows
        ]

    # ── Neo4j Migrations ────────────────────────────────────────────────────

    async def ensure_neo4j_migration_tracking(self) -> None:
        """Ensure Neo4j has migration tracking nodes."""
        if not self._neo4j_driver:
            return

        async with self._neo4j_driver.session() as session:
            await session.run(
                """
                CREATE CONSTRAINT migration_version IF NOT EXISTS
                FOR (m:_Migration) REQUIRE m.version IS UNIQUE
                """
            )
            logger.info("Neo4j migration tracking initialized")

    async def get_neo4j_version(self) -> int:
        """Get current Neo4j migration version."""
        if not self._neo4j_driver:
            return 0

        async with self._neo4j_driver.session() as session:
            result = await session.run("MATCH (m:_Migration) RETURN m.version AS v ORDER BY v DESC LIMIT 1")
            record = await result.single()
            return record["v"] if record else 0


# ─── Singleton ───────────────────────────────────────────────────────────────

_migration_manager: MigrationManager | None = None


def get_migration_manager(
    db_path: str = "./data/users.db",
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
) -> MigrationManager:
    """Get or create the singleton MigrationManager instance."""
    global _migration_manager
    if _migration_manager is None:
        _migration_manager = MigrationManager(
            db_path=db_path,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
        )
    return _migration_manager
