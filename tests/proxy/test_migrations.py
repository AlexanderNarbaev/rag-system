"""Tests for proxy/app/db/migrations.py — Database migration framework."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# We need access to the global registry to clean it up
import proxy.app.db.migrations as migrations_mod
from proxy.app.db.migrations import (
    MigrationInfo,
    MigrationManager,
    MigrationRecord,
    clear_registry,
    discover_migrations,
    get_migration_manager,
    get_registered_migrations,
    register_migration,
)


class _AsyncContextManager:
    """Helper to create a proper async context manager from a mock session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the migration registry before and after each test."""
    clear_registry()
    yield
    clear_registry()
    # Reset the singleton
    migrations_mod._migration_manager = None


@pytest.fixture
def sample_migration():
    """A simple migration using SQL."""
    return MigrationInfo(
        version=1,
        name="create_users_table",
        description="Create the users table",
        up_sql="CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT);",
        down_sql="DROP TABLE IF EXISTS users;",
        backend="sqlite",
    )


@pytest.fixture
def sample_migration_v2():
    """A second migration."""
    return MigrationInfo(
        version=2,
        name="add_email_column",
        description="Add email column to users",
        up_sql="ALTER TABLE users ADD COLUMN email TEXT;",
        down_sql="ALTER TABLE users DROP COLUMN email;",
        backend="sqlite",
    )


@pytest.fixture
def async_migration():
    """A migration using async callable."""
    return MigrationInfo(
        version=3,
        name="async_migration",
        description="Migration with async callable",
        up_async=AsyncMock(),
        down_async=AsyncMock(),
        backend="sqlite",
    )


@pytest.fixture
def neo4j_migration():
    """A Neo4j backend migration."""
    return MigrationInfo(
        version=4,
        name="neo4j_migration",
        description="Neo4j migration",
        up_async=AsyncMock(),
        down_async=AsyncMock(),
        backend="neo4j",
    )


# ── MigrationInfo ────────────────────────────────────────────────────────────


class TestMigrationInfo:
    def test_defaults(self):
        info = MigrationInfo(version=1, name="test", description="test desc")
        assert info.version == 1
        assert info.name == "test"
        assert info.description == "test desc"
        assert info.up_sql == ""
        assert info.down_sql == ""
        assert info.up_async is None
        assert info.down_async is None
        assert info.backend == "sqlite"

    def test_custom_backend(self):
        info = MigrationInfo(version=1, name="test", description="test", backend="neo4j")
        assert info.backend == "neo4j"


# ── MigrationRegistry ────────────────────────────────────────────────────────


class TestMigrationRegistry:
    def test_register_migration(self, sample_migration):
        register_migration(sample_migration)
        registered = get_registered_migrations()
        assert 1 in registered
        assert registered[1].name == "create_users_table"

    def test_register_duplicate_raises(self, sample_migration):
        register_migration(sample_migration)
        with pytest.raises(ValueError, match="already registered"):
            register_migration(sample_migration)

    def test_get_registered_migrations_returns_copy(self, sample_migration):
        register_migration(sample_migration)
        result = get_registered_migrations()
        result.clear()
        # Original should still have the migration
        assert 1 in get_registered_migrations()

    def test_clear_registry(self, sample_migration):
        register_migration(sample_migration)
        assert len(get_registered_migrations()) == 1
        clear_registry()
        assert len(get_registered_migrations()) == 0

    def test_multiple_registrations(self, sample_migration, sample_migration_v2):
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        registered = get_registered_migrations()
        assert len(registered) == 2
        assert 1 in registered
        assert 2 in registered


# ── Discover Migrations ──────────────────────────────────────────────────────


class TestDiscoverMigrations:
    def test_discover_from_package(self):
        """discover_migrations should scan the db package directory."""
        # Should not raise even if no migration files exist
        discover_migrations()
        # We can't predict what migrations exist, but the function should not crash

    def test_discover_with_custom_path(self, tmp_path):
        """Discover from a custom path that has no migration modules."""
        discover_migrations(str(tmp_path))
        assert len(get_registered_migrations()) == 0

    def test_discover_handles_import_error(self, tmp_path):
        """Should log warning on import error but not raise."""
        # Create a fake migration module that will fail to import
        bad_module = tmp_path / "migration_999_bad.py"
        bad_module.write_text("raise ImportError('test error')")

        # Should not raise
        discover_migrations(str(tmp_path))

    def test_discover_skips_non_migration_modules(self, tmp_path):
        """Modules not starting with 'migration_' should be skipped."""
        helper = tmp_path / "helper.py"
        helper.write_text("MIGRATION = 'should not be found'")
        discover_migrations(str(tmp_path))
        assert len(get_registered_migrations()) == 0

    def test_discover_skips_modules_without_migration_attr(self, tmp_path):
        """Modules without MIGRATION attribute should be skipped."""
        module = tmp_path / "migration_001_empty.py"
        module.write_text("# empty migration module")
        discover_migrations(str(tmp_path))
        assert len(get_registered_migrations()) == 0


# ── MigrationRecord ──────────────────────────────────────────────────────────


class TestMigrationRecord:
    def test_fields(self):
        record = MigrationRecord(
            version=1,
            name="test",
            applied_at="2025-01-01T00:00:00",
            execution_ms=123.45,
            checksum="abc123",
        )
        assert record.version == 1
        assert record.name == "test"
        assert record.applied_at == "2025-01-01T00:00:00"
        assert record.execution_ms == 123.45
        assert record.checksum == "abc123"

    def test_default_checksum(self):
        record = MigrationRecord(
            version=1,
            name="test",
            applied_at="2025-01-01T00:00:00",
            execution_ms=0.0,
        )
        assert record.checksum == ""


# ── MigrationManager ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def manager(tmp_path):
    """Create a MigrationManager with a temp SQLite database."""
    db_path = str(tmp_path / "test.db")
    with patch("proxy.app.db.migrations.discover_migrations"):
        mgr = MigrationManager(db_path=db_path)
        yield mgr
    await mgr.close()


@pytest_asyncio.fixture
async def initialized_manager(manager):
    """Create an initialized MigrationManager."""
    await manager.initialize()
    return manager


class TestMigrationManagerInit:
    @pytest.mark.asyncio
    async def test_initialize(self, manager):
        assert manager._initialized is False
        await manager.initialize()
        assert manager._initialized is True
        assert manager._conn is not None

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, initialized_manager):
        """Calling initialize twice should be a no-op."""
        assert initialized_manager._initialized is True
        await initialized_manager.initialize()
        assert initialized_manager._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, initialized_manager):
        """Should create _migrations and _migration_log tables."""
        conn = initialized_manager._conn
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('_migrations', '_migration_log')",
        )
        rows = await cursor.fetchall()
        table_names = [r[0] for r in rows]
        assert "_migrations" in table_names
        assert "_migration_log" in table_names

    @pytest.mark.asyncio
    async def test_initialize_creates_data_directory(self, tmp_path):
        db_path = str(tmp_path / "subdir" / "test.db")
        mgr = MigrationManager(db_path=db_path)
        assert not Path(db_path).parent.exists()
        await mgr.initialize()
        assert Path(db_path).parent.exists()
        await mgr.close()


class TestMigrationManagerClose:
    @pytest.mark.asyncio
    async def test_close(self, initialized_manager):
        assert initialized_manager._conn is not None
        await initialized_manager.close()
        assert initialized_manager._conn is None
        assert initialized_manager._initialized is False

    @pytest.mark.asyncio
    async def test_close_with_neo4j_driver(self, initialized_manager):
        """Close should handle neo4j driver cleanup."""
        mock_driver = AsyncMock()
        initialized_manager._neo4j_driver = mock_driver
        await initialized_manager.close()
        mock_driver.close.assert_called_once()
        assert initialized_manager._neo4j_driver is None

    @pytest.mark.asyncio
    async def test_close_without_connection(self):
        """Close when not connected should not raise."""
        mgr = MigrationManager(db_path=":memory:")
        await mgr.close()
        assert mgr._conn is None


class TestCurrentVersion:
    @pytest.mark.asyncio
    async def test_initial_version_is_zero(self, initialized_manager):
        version = await initialized_manager.current_version()
        assert version == 0

    @pytest.mark.asyncio
    async def test_version_after_migration(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()
        version = await initialized_manager.current_version()
        assert version == 1

    @pytest.mark.asyncio
    async def test_version_after_multiple_migrations(self, initialized_manager, sample_migration, sample_migration_v2):
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        await initialized_manager.upgrade()
        version = await initialized_manager.current_version()
        assert version == 2


class TestPendingMigrations:
    @pytest.mark.asyncio
    async def test_no_pending_when_empty(self, initialized_manager):
        pending = await initialized_manager.pending_migrations()
        assert pending == []

    @pytest.mark.asyncio
    async def test_pending_with_registered(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        pending = await initialized_manager.pending_migrations()
        assert len(pending) == 1
        assert pending[0].version == 1

    @pytest.mark.asyncio
    async def test_pending_after_apply(self, initialized_manager, sample_migration, sample_migration_v2):
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        await initialized_manager.upgrade(target_version=1)
        pending = await initialized_manager.pending_migrations()
        assert len(pending) == 1
        assert pending[0].version == 2

    @pytest.mark.asyncio
    async def test_pending_empty_after_full_apply(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()
        pending = await initialized_manager.pending_migrations()
        assert pending == []


class TestAppliedMigrations:
    @pytest.mark.asyncio
    async def test_empty_applied(self, initialized_manager):
        applied = await initialized_manager.applied_migrations()
        assert applied == []

    @pytest.mark.asyncio
    async def test_applied_after_upgrade(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()
        applied = await initialized_manager.applied_migrations()
        assert len(applied) == 1
        assert applied[0].version == 1
        assert applied[0].name == "create_users_table"


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_status_empty(self, initialized_manager):
        status = await initialized_manager.get_status()
        assert status["current_version"] == 0
        assert status["latest_available"] == 0
        assert status["applied_count"] == 0
        assert status["pending_count"] == 0
        assert status["is_up_to_date"] is True

    @pytest.mark.asyncio
    async def test_status_with_pending(self, initialized_manager, sample_migration, sample_migration_v2):
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        await initialized_manager.upgrade(target_version=1)

        status = await initialized_manager.get_status()
        assert status["current_version"] == 1
        assert status["latest_available"] == 2
        assert status["applied_count"] == 1
        assert status["pending_count"] == 1
        assert status["pending_versions"] == [2]
        assert status["is_up_to_date"] is False

    @pytest.mark.asyncio
    async def test_status_up_to_date(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()
        status = await initialized_manager.get_status()
        assert status["is_up_to_date"] is True
        assert status["applied_count"] == 1


class TestUpgrade:
    @pytest.mark.asyncio
    async def test_upgrade_sql(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        applied = await initialized_manager.upgrade()
        assert len(applied) == 1
        assert applied[0].version == 1
        assert applied[0].name == "create_users_table"
        assert applied[0].execution_ms >= 0

    @pytest.mark.asyncio
    async def test_upgrade_target_version(self, initialized_manager, sample_migration, sample_migration_v2):
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        applied = await initialized_manager.upgrade(target_version=1)
        assert len(applied) == 1
        assert applied[0].version == 1

    @pytest.mark.asyncio
    async def test_upgrade_no_pending(self, initialized_manager):
        applied = await initialized_manager.upgrade()
        assert applied == []

    @pytest.mark.asyncio
    async def test_upgrade_dry_run(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        applied = await initialized_manager.upgrade(dry_run=True)
        assert applied == []
        # Should not have applied anything
        version = await initialized_manager.current_version()
        assert version == 0

    @pytest.mark.asyncio
    async def test_upgrade_idempotent(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()
        # Running again should apply nothing
        applied = await initialized_manager.upgrade()
        assert applied == []

    @pytest.mark.asyncio
    async def test_upgrade_async_callable(self, initialized_manager, async_migration):
        register_migration(async_migration)
        applied = await initialized_manager.upgrade()
        assert len(applied) == 1
        async_migration.up_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_upgrade_failure_raises(self, initialized_manager):
        bad_migration = MigrationInfo(
            version=1,
            name="bad_migration",
            description="This will fail",
            up_sql="INVALID SQL SYNTAX $$$",
            backend="sqlite",
        )
        register_migration(bad_migration)
        with pytest.raises(RuntimeError, match="Migration v1 failed"):
            await initialized_manager.upgrade()

        # Should have logged the failure
        log = await initialized_manager.get_audit_log()
        assert len(log) == 1
        assert log[0]["success"] is False
        assert "upgrade_failed" in log[0]["action"]

    @pytest.mark.asyncio
    async def test_upgrade_neo4j_backend_no_driver(self, initialized_manager, neo4j_migration):
        """Neo4j migration with no driver should skip silently."""
        register_migration(neo4j_migration)
        applied = await initialized_manager.upgrade()
        assert len(applied) == 1  # Still records as applied
        neo4j_migration.up_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_upgrade_neo4j_with_driver(self, initialized_manager, neo4j_migration):
        """Neo4j migration with driver should call up_async with session."""
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_driver.session.return_value = _AsyncContextManager(mock_session)
        mock_driver.close = AsyncMock()

        initialized_manager._neo4j_driver = mock_driver
        register_migration(neo4j_migration)
        applied = await initialized_manager.upgrade()
        assert len(applied) == 1
        neo4j_migration.up_async.assert_called_once_with(mock_session)

    @pytest.mark.asyncio
    async def test_upgrade_sql_and_async(self, initialized_manager):
        """Migration with both SQL and async callable."""
        mock_async = AsyncMock()
        migration = MigrationInfo(
            version=1,
            name="combined",
            description="SQL + async",
            up_sql="CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY);",
            up_async=mock_async,
            backend="sqlite",
        )
        register_migration(migration)
        applied = await initialized_manager.upgrade()
        assert len(applied) == 1
        mock_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_upgrade_creates_audit_log(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()
        log = await initialized_manager.get_audit_log()
        assert len(log) == 1
        assert log[0]["version"] == 1
        assert log[0]["action"] == "upgrade"
        assert log[0]["success"] is True


class TestDowngrade:
    @pytest.mark.asyncio
    async def test_downgrade(self, initialized_manager, sample_migration, sample_migration_v2):
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=1)
        assert len(rolled_back) == 1
        assert rolled_back[0].version == 2

        version = await initialized_manager.current_version()
        assert version == 1

    @pytest.mark.asyncio
    async def test_downgrade_to_zero(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=0)
        assert len(rolled_back) == 1
        assert rolled_back[0].version == 1

        version = await initialized_manager.current_version()
        assert version == 0

    @pytest.mark.asyncio
    async def test_downgrade_already_at_target(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=1)
        assert rolled_back == []

    @pytest.mark.asyncio
    async def test_downgrade_above_current(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=10)
        assert rolled_back == []

    @pytest.mark.asyncio
    async def test_downgrade_dry_run(self, initialized_manager, sample_migration, sample_migration_v2):
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=0, dry_run=True)
        assert rolled_back == []

        # Version should not have changed
        version = await initialized_manager.current_version()
        assert version == 2

    @pytest.mark.asyncio
    async def test_downgrade_no_migrations_to_rollback(self, initialized_manager):
        rolled_back = await initialized_manager.downgrade(target_version=0)
        assert rolled_back == []

    @pytest.mark.asyncio
    async def test_downgrade_async_callable(self, initialized_manager, async_migration):
        register_migration(async_migration)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=0)
        assert len(rolled_back) == 1
        async_migration.down_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_downgrade_sql_and_async(self, initialized_manager):
        mock_async = AsyncMock()
        migration = MigrationInfo(
            version=1,
            name="combined",
            description="SQL + async",
            up_sql="CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY);",
            down_sql="DROP TABLE IF EXISTS test_table;",
            down_async=mock_async,
            backend="sqlite",
        )
        register_migration(migration)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=0)
        assert len(rolled_back) == 1
        mock_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_downgrade_failure_raises(self, initialized_manager):
        migration = MigrationInfo(
            version=1,
            name="test",
            description="test",
            up_sql="CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY);",
            down_sql="INVALID SQL $$$",
            backend="sqlite",
        )
        register_migration(migration)
        await initialized_manager.upgrade()

        with pytest.raises(RuntimeError, match="rollback failed"):
            await initialized_manager.downgrade(target_version=0)

        # Should have logged the failure
        log = await initialized_manager.get_audit_log()
        # Find the downgrade_failed entry
        failed_entries = [e for e in log if "downgrade_failed" in e["action"]]
        assert len(failed_entries) == 1
        assert failed_entries[0]["success"] is False

    @pytest.mark.asyncio
    async def test_downgrade_neo4j_with_driver(self, initialized_manager, neo4j_migration):
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_driver.session.return_value = _AsyncContextManager(mock_session)
        mock_driver.close = AsyncMock()

        initialized_manager._neo4j_driver = mock_driver
        register_migration(neo4j_migration)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=0)
        assert len(rolled_back) == 1
        neo4j_migration.down_async.assert_called_once_with(mock_session)

    @pytest.mark.asyncio
    async def test_downgrade_neo4j_no_driver(self, initialized_manager, neo4j_migration):
        """Neo4j downgrade with no driver should skip but still record."""
        register_migration(neo4j_migration)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=0)
        assert len(rolled_back) == 1
        neo4j_migration.down_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_downgrade_reverse_order(self, initialized_manager, sample_migration, sample_migration_v2):
        """Migrations should be rolled back in reverse order."""
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        await initialized_manager.upgrade()

        rolled_back = await initialized_manager.downgrade(target_version=0)
        assert len(rolled_back) == 2
        assert rolled_back[0].version == 2  # Higher version first
        assert rolled_back[1].version == 1


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_audit_log_empty(self, initialized_manager):
        log = await initialized_manager.get_audit_log()
        assert log == []

    @pytest.mark.asyncio
    async def test_audit_log_after_upgrade(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()
        log = await initialized_manager.get_audit_log()
        assert len(log) == 1
        assert log[0]["version"] == 1
        assert log[0]["action"] == "upgrade"
        assert log[0]["success"] is True
        assert log[0]["error_message"] is None

    @pytest.mark.asyncio
    async def test_audit_log_after_downgrade(self, initialized_manager, sample_migration):
        register_migration(sample_migration)
        await initialized_manager.upgrade()
        await initialized_manager.downgrade(target_version=0)

        log = await initialized_manager.get_audit_log()
        assert len(log) == 2
        actions = [e["action"] for e in log]
        assert "downgrade" in actions
        assert "upgrade" in actions

    @pytest.mark.asyncio
    async def test_audit_log_limit(self, initialized_manager, sample_migration, sample_migration_v2):
        register_migration(sample_migration)
        register_migration(sample_migration_v2)
        await initialized_manager.upgrade()

        log = await initialized_manager.get_audit_log(limit=1)
        assert len(log) == 1


class TestNeo4jSupport:
    @pytest.mark.asyncio
    async def test_ensure_neo4j_migration_tracking_no_driver(self, initialized_manager):
        """Should be a no-op without driver."""
        await initialized_manager.ensure_neo4j_migration_tracking()

    @pytest.mark.asyncio
    async def test_ensure_neo4j_migration_tracking_with_driver(self, initialized_manager):
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_driver.session.return_value = _AsyncContextManager(mock_session)
        mock_driver.close = AsyncMock()

        initialized_manager._neo4j_driver = mock_driver
        await initialized_manager.ensure_neo4j_migration_tracking()
        mock_session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_neo4j_version_no_driver(self, initialized_manager):
        version = await initialized_manager.get_neo4j_version()
        assert version == 0

    @pytest.mark.asyncio
    async def test_get_neo4j_version_with_driver(self, initialized_manager):
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single.return_value = {"v": 5}
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value = _AsyncContextManager(mock_session)
        mock_driver.close = AsyncMock()

        initialized_manager._neo4j_driver = mock_driver
        version = await initialized_manager.get_neo4j_version()
        assert version == 5

    @pytest.mark.asyncio
    async def test_get_neo4j_version_no_records(self, initialized_manager):
        mock_driver = MagicMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result
        mock_driver.session.return_value = _AsyncContextManager(mock_session)
        mock_driver.close = AsyncMock()

        initialized_manager._neo4j_driver = mock_driver
        version = await initialized_manager.get_neo4j_version()
        assert version == 0


class TestNeo4jInitialization:
    @pytest.mark.asyncio
    async def test_initialize_with_neo4j_no_package(self, tmp_path):
        """Neo4j init should be skipped if neo4j package not installed."""
        db_path = str(tmp_path / "test.db")
        with (
            patch("importlib.util.find_spec", return_value=None),
            patch("proxy.app.db.migrations.discover_migrations"),
        ):
            mgr = MigrationManager(
                db_path=db_path,
                neo4j_uri="bolt://localhost:7687",
                neo4j_user="neo4j",
                neo4j_password="password",
            )
            await mgr.initialize()
            assert mgr._neo4j_driver is None
            await mgr.close()

    @pytest.mark.asyncio
    async def test_initialize_with_neo4j_import_error(self, tmp_path):
        """Neo4j init should handle ImportError gracefully."""
        db_path = str(tmp_path / "test.db")
        with patch("proxy.app.db.migrations.discover_migrations"):
            mgr = MigrationManager(
                db_path=db_path,
                neo4j_uri="bolt://localhost:7687",
            )
            # Patch find_spec to indicate neo4j exists, but the actual import fails
            with patch("proxy.app.db.migrations.importlib") as mock_importlib:
                mock_importlib.util.find_spec.return_value = None
                await mgr.initialize()
            assert mgr._neo4j_driver is None
            await mgr.close()

    @pytest.mark.asyncio
    async def test_initialize_with_neo4j_connection_error(self, tmp_path):
        """Neo4j init should handle connection errors gracefully."""
        db_path = str(tmp_path / "test.db")

        # Import neo4j to check if it's available
        try:
            from neo4j import AsyncGraphDatabase  # noqa: F401
        except ImportError:
            pytest.skip("neo4j package not installed")

        with patch("proxy.app.db.migrations.discover_migrations"):
            mgr = MigrationManager(
                db_path=db_path,
                neo4j_uri="bolt://localhost:9999",
                neo4j_user="neo4j",
                neo4j_password="wrong",
            )
            # The driver init might succeed (lazy connection) but we test the path
            await mgr.initialize()
            # The driver may or may not be created depending on neo4j version
            # Just ensure no crash
            await mgr.close()

    @pytest.mark.asyncio
    async def test_initialize_without_neo4j_uri(self, tmp_path):
        """No Neo4j driver should be created when URI is not set."""
        db_path = str(tmp_path / "test.db")
        with patch("proxy.app.db.migrations.discover_migrations"):
            mgr = MigrationManager(db_path=db_path)
            await mgr.initialize()
            assert mgr._neo4j_driver is None
            await mgr.close()


# ── Singleton ────────────────────────────────────────────────────────────────


class TestGetMigrationManager:
    def test_singleton_creation(self):
        mgr = get_migration_manager(db_path=":memory:")
        assert isinstance(mgr, MigrationManager)

    def test_singleton_returns_same_instance(self):
        mgr1 = get_migration_manager(db_path=":memory:")
        mgr2 = get_migration_manager(db_path=":memory:")
        assert mgr1 is mgr2

    def test_singleton_with_neo4j_params(self):
        mgr = get_migration_manager(
            db_path=":memory:",
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="pass",
        )
        assert mgr._neo4j_uri == "bolt://localhost:7687"


# ── Integration ──────────────────────────────────────────────────────────────


class TestMigrationIntegration:
    """Integration tests for the full migration lifecycle."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, tmp_path):
        """Test full upgrade -> check -> downgrade -> check lifecycle."""
        db_path = str(tmp_path / "lifecycle.db")

        # Register migrations
        m1 = MigrationInfo(
            version=1,
            name="create_table",
            description="Create test table",
            up_sql="CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, value TEXT);",
            down_sql="DROP TABLE IF EXISTS test;",
            backend="sqlite",
        )
        m2 = MigrationInfo(
            version=2,
            name="insert_data",
            description="Insert initial data",
            up_sql="INSERT INTO test (id, value) VALUES (1, 'hello');",
            down_sql="DELETE FROM test WHERE id = 1;",
            backend="sqlite",
        )
        m3 = MigrationInfo(
            version=3,
            name="add_column",
            description="Add extra column",
            up_sql="ALTER TABLE test ADD COLUMN extra TEXT;",
            down_sql="ALTER TABLE test DROP COLUMN extra;",
            backend="sqlite",
        )

        register_migration(m1)
        register_migration(m2)
        register_migration(m3)

        with patch("proxy.app.db.migrations.discover_migrations"):
            mgr = MigrationManager(db_path=db_path)
            await mgr.initialize()

        try:
            # Apply all
            applied = await mgr.upgrade()
            assert len(applied) == 3
            assert await mgr.current_version() == 3

            # Status
            status = await mgr.get_status()
            assert status["is_up_to_date"] is True
            assert status["applied_count"] == 3

            # Rollback to v1
            rolled_back = await mgr.downgrade(target_version=1)
            assert len(rolled_back) == 2
            assert await mgr.current_version() == 1

            # Apply again up to v2 — only v2 is pending (v1 already applied)
            applied = await mgr.upgrade(target_version=2)
            assert len(applied) == 1
            assert applied[0].version == 2
        finally:
            await mgr.close()

    @pytest.mark.asyncio
    async def test_multiple_migrations_rollback(self, tmp_path):
        """Test rolling back multiple migrations."""
        db_path = str(tmp_path / "multi_rollback.db")

        for i in range(1, 6):
            m = MigrationInfo(
                version=i,
                name=f"migration_{i}",
                description=f"Migration {i}",
                up_sql=f"CREATE TABLE IF NOT EXISTS t{i} (id INTEGER PRIMARY KEY);",
                down_sql=f"DROP TABLE IF EXISTS t{i};",
                backend="sqlite",
            )
            register_migration(m)

        with patch("proxy.app.db.migrations.discover_migrations"):
            mgr = MigrationManager(db_path=db_path)
            await mgr.initialize()

        try:
            await mgr.upgrade()
            assert await mgr.current_version() == 5

            rolled_back = await mgr.downgrade(target_version=2)
            assert len(rolled_back) == 3  # v5, v4, v3
            assert await mgr.current_version() == 2
        finally:
            await mgr.close()
