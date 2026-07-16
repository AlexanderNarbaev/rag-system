#!/usr/bin/env python3
# scripts/migrate.py
"""
Database migration CLI for the RAG System.

Usage:
    python scripts/migrate.py status              # Show current migration status
    python scripts/migrate.py upgrade             # Apply all pending migrations
    python scripts/migrate.py upgrade --dry-run   # Preview pending migrations
    python scripts/migrate.py upgrade --target 2  # Apply up to version 2
    python scripts/migrate.py downgrade 1         # Rollback to version 1
    python scripts/migrate.py downgrade 1 --dry-run  # Preview rollback
    python scripts/migrate.py history             # Show migration history
    python scripts/migrate.py create <name>       # Create new migration file

Examples:
    # Check current status
    python scripts/migrate.py status

    # Apply all pending migrations
    python scripts/migrate.py upgrade

    # Preview what would be applied
    python scripts/migrate.py upgrade --dry-run

    # Rollback to version 1
    python scripts/migrate.py downgrade 1

    # Create a new migration
    python scripts/migrate.py create add_user_preferences
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def cmd_status(manager) -> None:
    """Show current migration status."""
    status = await manager.get_status()

    print("\n" + "=" * 60)
    print("  Database Migration Status")
    print("=" * 60)
    print(f"  Current Version:    {status['current_version']}")
    print(f"  Latest Available:   {status['latest_available']}")
    print(f"  Applied:            {status['applied_count']}")
    print(f"  Pending:            {status['pending_count']}")
    print(f"  Up to Date:         {'✓ Yes' if status['is_up_to_date'] else '✗ No'}")
    print("=" * 60)

    if status["pending_versions"]:
        print("\n  Pending Migrations:")
        for v in status["pending_versions"]:
            print(f"    - Version {v}")
        print()

    if status["applied"]:
        print("\n  Applied Migrations:")
        for m in status["applied"]:
            print(f"    v{m['version']}: {m['name']} ({m['applied_at'][:19]})")
        print()


async def cmd_upgrade(manager, dry_run: bool = False, target: int | None = None) -> None:
    """Apply pending migrations."""
    if dry_run:
        print("\n  DRY RUN — No changes will be made\n")

    applied = await manager.upgrade(target_version=target, dry_run=dry_run)

    if dry_run:
        pending = await manager.pending_migrations()
        if target is not None:
            pending = [m for m in pending if m.version <= target]

        if pending:
            print("  Would apply the following migrations:")
            for m in pending:
                print(f"    v{m.version}: {m.name} — {m.description}")
        else:
            print("  No pending migrations")
    else:
        if applied:
            print(f"\n  ✓ Applied {len(applied)} migration(s):")
            for m in applied:
                print(f"    v{m.version}: {m.name} ({m.execution_ms:.1f}ms)")
        else:
            print("\n  No pending migrations to apply")


async def cmd_downgrade(manager, target_version: int, dry_run: bool = False) -> None:
    """Rollback migrations to target version."""
    if dry_run:
        print("\n  DRY RUN — No changes will be made\n")

    current = await manager.current_version()

    if dry_run:
        if target_version >= current:
            print(f"  Already at or below version {target_version}")
            return

        print(f"  Would rollback from version {current} to {target_version}:")
        from proxy.app.db.migrations import get_registered_migrations
        all_migrations = get_registered_migrations()
        for v in range(current, target_version, -1):
            if v in all_migrations:
                m = all_migrations[v]
                print(f"    v{v}: {m.name}")
    else:
        rolled_back = await manager.downgrade(target_version=target_version, dry_run=dry_run)

        if rolled_back:
            print(f"\n  ✓ Rolled back {len(rolled_back)} migration(s):")
            for m in rolled_back:
                print(f"    v{m.version}: {m.name} ({m.execution_ms:.1f}ms)")
        else:
            print(f"\n  No migrations to rollback (target: {target_version})")


async def cmd_history(manager) -> None:
    """Show migration audit log."""
    log = await manager.get_audit_log(limit=50)

    if not log:
        print("\n  No migration history found")
        return

    print("\n" + "=" * 70)
    print("  Migration History")
    print("=" * 70)
    print(f"  {'Version':<10} {'Action':<20} {'Details':<30} {'Time'}")
    print("-" * 70)

    for entry in log:
        status = "✓" if entry["success"] else "✗"
        print(
            f"  v{entry['version']:<9} {entry['action']:<20} "
            f"{entry['details'][:28]:<30} {entry['executed_at'][:19]}"
        )
        if entry.get("error_message"):
            print(f"    └─ Error: {entry['error_message'][:60]}")

    print()


async def cmd_create(name: str) -> None:
    """Create a new migration file."""
    db_dir = project_root / "proxy" / "app" / "db"

    # Find next version number
    existing = sorted(db_dir.glob("migration_*.py"))
    if existing:
        last = existing[-1].stem
        # Extract version number from filename
        parts = last.split("_", 2)
        next_version = int(parts[1]) + 1
    else:
        next_version = 1

    # Create filename
    safe_name = name.lower().replace(" ", "_").replace("-", "_")
    filename = f"migration_{next_version:03d}_{safe_name}.py"
    filepath = db_dir / filename

    # Template
    template = f'''# proxy/app/db/{filename}
"""
Migration {next_version:03d}: {name.replace('_', ' ').replace('-', ' ').title()}

Description of what this migration does.
"""

from proxy.app.db.migrations import MigrationInfo, register_migration

# ─── Up Migration ────────────────────────────────────────────────────────────

UP_SQL = """
-- Add your SQL here
"""

# ─── Down Migration ──────────────────────────────────────────────────────────

DOWN_SQL = """
-- Add rollback SQL here
"""

# ─── Migration Registration ──────────────────────────────────────────────────

MIGRATION = MigrationInfo(
    version={next_version},
    name="{safe_name}",
    description="Description of {name.replace('_', ' ').replace('-', ' ').title()}",
    up_sql=UP_SQL,
    down_sql=DOWN_SQL,
    backend="sqlite",
)

# Register when module is imported
register_migration(MIGRATION)
'''

    filepath.write_text(template)
    print(f"\n  ✓ Created migration file: {filepath}")
    print(f"    Version: {next_version}")
    print(f"    Name: {safe_name}")


def main():
    parser = argparse.ArgumentParser(
        description="Database migration CLI for the RAG System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Status command
    subparsers.add_parser("status", help="Show current migration status")

    # Upgrade command
    upgrade_parser = subparsers.add_parser("upgrade", help="Apply pending migrations")
    upgrade_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying"
    )
    upgrade_parser.add_argument(
        "--target", type=int, help="Apply up to this version"
    )

    # Downgrade command
    downgrade_parser = subparsers.add_parser("downgrade", help="Rollback migrations")
    downgrade_parser.add_argument("version", type=int, help="Target version to rollback to")
    downgrade_parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without applying"
    )

    # History command
    subparsers.add_parser("history", help="Show migration audit log")

    # Create command
    create_parser = subparsers.add_parser("create", help="Create new migration file")
    create_parser.add_argument("name", help="Migration name (e.g., add_user_preferences)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Import after path setup
    from proxy.app.db.migrations import get_migration_manager
    from proxy.app.shared.config import NEO4J_PASSWORD, NEO4J_URI, NEO4J_USER, USER_DB_PATH

    # Initialize manager
    manager = get_migration_manager(
        db_path=USER_DB_PATH,
        neo4j_uri=NEO4J_URI,
        neo4j_user=NEO4J_USER,
        neo4j_password=NEO4J_PASSWORD,
    )

    async def run():
        try:
            if args.command == "status":
                await cmd_status(manager)
            elif args.command == "upgrade":
                await cmd_upgrade(manager, dry_run=args.dry_run, target=args.target)
            elif args.command == "downgrade":
                await cmd_downgrade(manager, args.version, dry_run=args.dry_run)
            elif args.command == "history":
                await cmd_history(manager)
            elif args.command == "create":
                await cmd_create(args.name)
        finally:
            await manager.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
