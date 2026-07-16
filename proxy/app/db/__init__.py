# proxy/app/db/__init__.py
"""Database migration framework for the RAG System.

Provides:
- MigrationManager for SQLite and Neo4j schema management
- Version tracking with _migrations table
- Up/down migrations with rollback support
- Dry-run mode for safe previews
- Audit trail of all migration operations

Usage:
    from proxy.app.db.migrations import MigrationManager

    manager = MigrationManager(db_path="./data/users.db")
    await manager.initialize()
    await manager.upgrade()
"""

from proxy.app.db.migrations import MigrationManager

__all__ = ["MigrationManager"]
