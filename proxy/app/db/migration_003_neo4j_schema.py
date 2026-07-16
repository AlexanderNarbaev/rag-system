# proxy/app/db/migration_003_neo4j_schema.py
"""
Migration 003: Neo4j graph schema initialization.

Sets up Neo4j constraints and indexes for the knowledge graph:
- Entity nodes with unique constraints
- Relationship indexes
- Full-text search indexes
"""

import contextlib
from typing import Any

from proxy.app.db.migrations import MigrationInfo, register_migration

# ─── Neo4j Schema Setup ──────────────────────────────────────────────────────

NEO4J_CONSTRAINTS = [
    # Entity uniqueness
    "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
    # Document uniqueness
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
    # Chunk uniqueness
    "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
]

NEO4J_INDEXES = [
    # Entity indexes
    "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)",
    "CREATE INDEX entity_type IF NOT EXISTS FOR (e:Entity) ON (e.type)",
    # Document indexes
    "CREATE INDEX document_source IF NOT EXISTS FOR (d:Document) ON (d.source_type)",
    "CREATE INDEX document_title IF NOT EXISTS FOR (d:Document) ON (d.title)",
    # Chunk indexes
    "CREATE INDEX chunk_source IF NOT EXISTS FOR (c:Chunk) ON (c.source_id)",
    # Full-text search
    """CREATE FULLTEXT INDEX entity_search IF NOT EXISTS
       FOR (e:Entity) ON EACH [e.name, e.description]""",
    """CREATE FULLTEXT INDEX document_search IF NOT EXISTS
       FOR (d:Document) ON EACH [d.title, d.content]""",
]


async def setup_neo4j_schema(session: Any) -> None:
    """Apply Neo4j constraints and indexes."""
    for constraint in NEO4J_CONSTRAINTS:
        try:
            await session.run(constraint)
        except Exception as e:
            # Constraint may already exist
            if "already exists" not in str(e).lower():
                raise

    for index in NEO4J_INDEXES:
        try:
            await session.run(index)
        except Exception as e:
            # Index may already exist
            if "already exists" not in str(e).lower():
                raise


async def teardown_neo4j_schema(session: Any) -> None:
    """Remove Neo4j constraints and indexes."""
    constraints_to_drop = [
        "DROP CONSTRAINT entity_id IF EXISTS",
        "DROP CONSTRAINT document_id IF EXISTS",
        "DROP CONSTRAINT chunk_id IF EXISTS",
    ]
    indexes_to_drop = [
        "DROP INDEX entity_name IF EXISTS",
        "DROP INDEX entity_type IF EXISTS",
        "DROP INDEX document_source IF EXISTS",
        "DROP INDEX document_title IF EXISTS",
        "DROP INDEX chunk_source IF EXISTS",
        "DROP INDEX entity_search IF EXISTS",
        "DROP INDEX document_search IF EXISTS",
    ]

    for stmt in constraints_to_drop + indexes_to_drop:
        with contextlib.suppress(Exception):
            await session.run(stmt)


# ─── Migration Registration ──────────────────────────────────────────────────

MIGRATION = MigrationInfo(
    version=3,
    name="neo4j_schema",
    description="Initialize Neo4j constraints and indexes for knowledge graph",
    up_async=setup_neo4j_schema,
    down_async=teardown_neo4j_schema,
    backend="neo4j",
)

# Register when module is imported
register_migration(MIGRATION)
