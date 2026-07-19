# proxy/app/core/kb_manager.py
"""Knowledge Base Manager — multi-KB support with SQLite metadata and Qdrant collections.

Inspired by RAGFlow's Knowledgebase model: each KB has its own Qdrant collection,
embedding model config, and document tracking. Metadata lives in SQLite; vectors
live in Qdrant.

Responsibilities:
- CRUD for knowledge bases (create, list, get, update, delete)
- Auto-provisioning of Qdrant collections per KB
- Document/chunk counting and statistics
- ETL task tracking (status, progress)
"""

import contextlib
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default KB database path
_DEFAULT_DB_PATH = "data/knowledge_bases.db"


def _get_qdrant_hnsw_m() -> int:
    from proxy.app.shared.config import QDRANT_HNSW_M

    return QDRANT_HNSW_M


def _get_qdrant_hnsw_ef_construct() -> int:
    from proxy.app.shared.config import QDRANT_HNSW_EF_CONSTRUCT

    return QDRANT_HNSW_EF_CONSTRUCT


def _get_qdrant_quantization_enabled() -> bool:
    from proxy.app.shared.config import QDRANT_QUANTIZATION_ENABLED

    return QDRANT_QUANTIZATION_ENABLED


@dataclass
class KnowledgeBase:
    """Represents a single knowledge base."""

    id: str
    name: str
    description: str = ""
    collection_name: str = ""
    embedding_model: str = "BAAI/bge-m3"
    dense_vector_size: int = 1024
    parser_config: dict[str, Any] = field(default_factory=dict)
    doc_count: int = 0
    chunk_count: int = 0
    token_count: int = 0
    status: str = "active"  # active, deleted, indexing
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class ETLTask:
    """Represents an ETL processing task."""

    id: str
    kb_id: str
    source_type: str  # confluence, jira, gitlab, file
    source_id: str
    status: str = "pending"  # pending, running, completed, failed
    progress: float = 0.0
    error_message: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0


class KnowledgeBaseManager:
    """Manages knowledge bases with SQLite metadata and Qdrant collections."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH, qdrant_client: Any = None):
        self.db_path = db_path
        self.qdrant_client = qdrant_client
        # Ensure parent directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        try:
            conn.executescript("""
        CREATE TABLE IF NOT EXISTS knowledge_bases (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          description TEXT DEFAULT '',
          collection_name TEXT NOT NULL UNIQUE,
          embedding_model TEXT DEFAULT 'BAAI/bge-m3',
          dense_vector_size INTEGER DEFAULT 1024,
          parser_config TEXT DEFAULT '{}',
          doc_count INTEGER DEFAULT 0,
          chunk_count INTEGER DEFAULT 0,
          token_count INTEGER DEFAULT 0,
          status TEXT DEFAULT 'active',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS etl_tasks (
          id TEXT PRIMARY KEY,
          kb_id TEXT NOT NULL,
          source_type TEXT NOT NULL,
          source_id TEXT NOT NULL,
          status TEXT DEFAULT 'pending',
          progress REAL DEFAULT 0.0,
          error_message TEXT DEFAULT '',
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id)
        );

        CREATE INDEX IF NOT EXISTS idx_etl_tasks_kb_id ON etl_tasks(kb_id);
        CREATE INDEX IF NOT EXISTS idx_etl_tasks_status ON etl_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_kb_status ON knowledge_bases(status);
      """)
            conn.commit()
            logger.info("Knowledge base database initialized at %s", self.db_path)
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Knowledge Base CRUD
    # -----------------------------------------------------------------------

    def create_kb(
        self,
        name: str,
        description: str = "",
        embedding_model: str = "BAAI/bge-m3",
        dense_vector_size: int = 1024,
        parser_config: dict[str, Any] | None = None,
    ) -> KnowledgeBase:
        """Create a new knowledge base and its Qdrant collection."""
        kb_id = str(uuid.uuid4())
        collection_name = f"kb_{name.lower().replace(' ', '_').replace('-', '_')}"
        now = time.time()

        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO knowledge_bases (id, name, description, collection_name, "
                "embedding_model, dense_vector_size, parser_config, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    kb_id,
                    name,
                    description,
                    collection_name,
                    embedding_model,
                    dense_vector_size,
                    str(parser_config or {}),
                    now,
                    now,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Knowledge base '{name}' already exists") from e
        finally:
            conn.close()

        # Create Qdrant collection
        self._ensure_qdrant_collection(collection_name, dense_vector_size)

        kb = KnowledgeBase(
            id=kb_id,
            name=name,
            description=description,
            collection_name=collection_name,
            embedding_model=embedding_model,
            dense_vector_size=dense_vector_size,
            parser_config=parser_config or {},
            created_at=now,
            updated_at=now,
        )
        logger.info("Created knowledge base '%s' (id=%s, collection=%s)", name, kb_id, collection_name)
        return kb

    def get_kb(self, kb_id: str) -> KnowledgeBase | None:
        """Get a knowledge base by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM knowledge_bases WHERE id = ? AND status != 'deleted'",
                (kb_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_kb(row)
        finally:
            conn.close()

    def get_kb_by_name(self, name: str) -> KnowledgeBase | None:
        """Get a knowledge base by name."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM knowledge_bases WHERE name = ? AND status != 'deleted'",
                (name,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_kb(row)
        finally:
            conn.close()

    def list_kbs(self, include_deleted: bool = False) -> list[KnowledgeBase]:
        """List all knowledge bases."""
        conn = self._get_conn()
        try:
            if include_deleted:
                rows = conn.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_bases WHERE status != 'deleted' ORDER BY created_at DESC",
                ).fetchall()
            return [self._row_to_kb(row) for row in rows]
        finally:
            conn.close()

    def update_kb(self, kb_id: str, **kwargs: Any) -> KnowledgeBase:
        """Update a knowledge base."""
        allowed = {"name", "description", "embedding_model", "dense_vector_size", "parser_config", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            raise ValueError("No valid fields to update")

        updates["updated_at"] = time.time()
        if "parser_config" in updates:
            updates["parser_config"] = str(updates["parser_config"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [kb_id]

        conn = self._get_conn()
        try:
            conn.execute(f"UPDATE knowledge_bases SET {set_clause} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()

        kb = self.get_kb(kb_id)
        if kb is None:
            raise ValueError(f"Knowledge base {kb_id} not found")
        logger.info("Updated knowledge base %s: %s", kb_id, list(updates.keys()))
        return kb

    def delete_kb(self, kb_id: str, hard: bool = False) -> bool:
        """Delete a knowledge base (soft by default)."""
        conn = self._get_conn()
        try:
            if hard:
                # Delete from Qdrant
                kb = self.get_kb(kb_id)
                if kb and self.qdrant_client:
                    try:
                        self.qdrant_client.delete_collection(kb.collection_name)
                    except Exception as e:
                        logger.warning("Failed to delete Qdrant collection %s: %s", kb.collection_name, e)
                conn.execute("DELETE FROM etl_tasks WHERE kb_id = ?", (kb_id,))
                conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
            else:
                conn.execute(
                    "UPDATE knowledge_bases SET status = 'deleted', updated_at = ? WHERE id = ?",
                    (time.time(), kb_id),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # ETL Task management
    # -----------------------------------------------------------------------

    def create_task(self, kb_id: str, source_type: str, source_id: str) -> ETLTask:
        """Create an ETL task."""
        task_id = str(uuid.uuid4())
        now = time.time()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO etl_tasks (id, kb_id, source_type, source_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, kb_id, source_type, source_id, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return ETLTask(id=task_id, kb_id=kb_id, source_type=source_type, source_id=source_id, created_at=now)

    def update_task(self, task_id: str, **kwargs: Any) -> None:
        """Update an ETL task."""
        allowed = {"status", "progress", "error_message"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = time.time()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]
        conn = self._get_conn()
        try:
            conn.execute(f"UPDATE etl_tasks SET {set_clause} WHERE id = ?", values)
            conn.commit()
        finally:
            conn.close()

    def list_tasks(self, kb_id: str | None = None, status: str | None = None) -> list[ETLTask]:
        """List ETL tasks with optional filters."""
        conn = self._get_conn()
        try:
            query = "SELECT * FROM etl_tasks WHERE 1=1"
            params: list[Any] = []
            if kb_id:
                query += " AND kb_id = ?"
                params.append(kb_id)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_task(row) for row in rows]
        finally:
            conn.close()

    def get_task(self, task_id: str) -> ETLTask | None:
        """Get an ETL task by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM etl_tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_task(row)
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Statistics
    # -----------------------------------------------------------------------

    def update_kb_stats(self, kb_id: str) -> None:
        """Recalculate doc_count, chunk_count, token_count for a KB."""
        conn = self._get_conn()
        try:
            task_counts = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed "
                "FROM etl_tasks WHERE kb_id = ?",
                (kb_id,),
            ).fetchone()
            now = time.time()
            conn.execute(
                "UPDATE knowledge_bases SET doc_count = ?, updated_at = ? WHERE id = ?",
                (task_counts["completed"] if task_counts else 0, now, kb_id),
            )
            conn.commit()
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Qdrant collection management
    # -----------------------------------------------------------------------

    def _ensure_qdrant_collection(self, collection_name: str, vector_size: int = 1024) -> None:
        """Create a Qdrant collection if it doesn't exist."""
        if self.qdrant_client is None:
            logger.warning("Qdrant client not set — skipping collection creation for %s", collection_name)
            return
        try:
            from qdrant_client.http import models as qmodels

            existing = {c.name for c in self.qdrant_client.get_collections().collections}
            if collection_name in existing:
                logger.info("Qdrant collection '%s' already exists", collection_name)
                return

            create_kwargs: dict[str, Any] = {
                "collection_name": collection_name,
                "vectors_config": {
                    "dense": qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
                },
                "optimizers_config": qmodels.OptimizersConfigDiff(indexing_threshold=20000),
                "hnsw_config": qmodels.HnswConfigDiff(
                    m=_get_qdrant_hnsw_m(),
                    ef_construct=_get_qdrant_hnsw_ef_construct(),
                ),
            }

            if _get_qdrant_quantization_enabled():
                create_kwargs["quantization_config"] = qmodels.ScalarQuantization(
                    scalar=qmodels.ScalarQuantizationConfig(
                        type=qmodels.ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True,
                    ),
                )

            self.qdrant_client.create_collection(**create_kwargs)
            # Create payload indexes
            for field_name in ["source_type", "source_id", "version", "doc_title", "kb_id"]:
                self.qdrant_client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            logger.info("Created Qdrant collection '%s'", collection_name)
        except Exception as e:
            logger.error("Failed to create Qdrant collection '%s': %s", collection_name, e)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _row_to_kb(row: sqlite3.Row) -> KnowledgeBase:
        """Convert a database row to a KnowledgeBase."""
        import ast

        parser_config: dict[str, Any] = {}
        with contextlib.suppress(ValueError, SyntaxError):
            parser_config = ast.literal_eval(row["parser_config"]) if row["parser_config"] else {}

        return KnowledgeBase(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            collection_name=row["collection_name"],
            embedding_model=row["embedding_model"],
            dense_vector_size=row["dense_vector_size"],
            parser_config=parser_config,
            doc_count=row["doc_count"],
            chunk_count=row["chunk_count"],
            token_count=row["token_count"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> ETLTask:
        """Convert a database row to an ETLTask."""
        return ETLTask(
            id=row["id"],
            kb_id=row["kb_id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            status=row["status"],
            progress=row["progress"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
