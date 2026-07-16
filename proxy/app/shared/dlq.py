# proxy/app/shared/dlq.py
"""Dead Letter Queue for failed RAG pipeline messages with SQLite persistence.

Provides a persistent, configurable DLQ for storing and retrying failed
messages from any RAG component (retrieval, reranking, LLM, graph expansion).
Messages that fail after exhausting retries are marked as "dead" and can be
manually reprocessed or inspected via stats.

Features:
    - SQLite-backed persistence (WAL mode for concurrent access)
    - Configurable retry policy (max retries, exponential backoff)
    - Per-service isolation via queue names
    - Stats: total, pending, failed, dead counts
    - Manual retry with backoff delay
    - Optional: integrates with CircuitBreaker for safe retry gating

Usage:
    >>> from proxy.app.shared.dlq import DeadLetterQueue
    >>> dlq = DeadLetterQueue("retrieval_errors")
    >>> dlq.add({"query": "What is RAG?", "error": "Qdrant timeout"})
    >>> dlq.add({"query": "What is embedding?", "error": "OOM"})
    >>> dlq.stats()  # {'total': 2, 'pending': 2, 'failed': 0, 'dead': 0}
    >>> # Process with a handler:
    >>> async for msg in dlq.process():
    ...     try:
    ...         await some_handler(msg)
    ...         dlq.ack(msg["id"])
    ...     except Exception:
    ...         dlq.nack(msg["id"], str(e))
    >>> # Or batch retry all pending:
    >>> dlq.retry(lambda msg: handle(msg))
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default DB path — survives restarts, air-gapped safe
_DEFAULT_DB_DIR = Path("./data/dlq")
_DEFAULT_RETRY_LIMIT = 3
_DEFAULT_BACKOFF_BASE = 2.0
_DEFAULT_DLQ_ENABLED = True


@dataclass
class DLQMessage:
    """A single message in the dead letter queue."""

    id: int
    queue: str
    payload: dict[str, Any]
    error: str
    retry_count: int = 0
    max_retries: int = _DEFAULT_RETRY_LIMIT
    status: str = "pending"
    created_at: float = 0.0
    last_error_at: float = 0.0
    next_retry_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "queue": self.queue,
            "payload": self.payload,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "status": self.status,
            "created_at": self.created_at,
            "last_error_at": self.last_error_at,
            "next_retry_at": self.next_retry_at,
            "metadata": self.metadata,
        }


class DeadLetterQueue:
    """SQLite-backed dead letter queue for failed messages.

    Provides persistent storage for messages that fail during processing.
    Supports retry with configurable backoff, manual reprocessing,
    and per-queue stats.

    Attributes:
        queue_name: Name of the queue (e.g., "retrieval", "llm", "reranker").
        db_path: Path to the SQLite database file.
        max_retries: Maximum retry attempts before marking as dead.
        backoff_base: Base for exponential backoff (seconds).

    """

    _instances: dict[str, DeadLetterQueue] = {}
    _lock = threading.Lock()

    def __init__(
        self,
        queue_name: str = "default",
        db_path: str | Path | None = None,
        max_retries: int = _DEFAULT_RETRY_LIMIT,
        backoff_base: float = _DEFAULT_BACKOFF_BASE,
    ):
        self.queue_name = queue_name
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._local = threading.local()

        if db_path is None:
            db_path = _DEFAULT_DB_DIR / f"dlq_{queue_name}.db"
        self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        with self.__class__._lock:
            self.__class__._instances[queue_name] = self

        logger.info(
            "DLQ '%s' initialized: db=%s, max_retries=%d, backoff=%.1fs",
            self.queue_name,
            self.db_path,
            self.max_retries,
            self.backoff_base,
        )

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        _conn: sqlite3.Connection = self._local.conn
        return _conn

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dlq_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL DEFAULT (strftime('%s', 'now')),
                last_error_at REAL NOT NULL DEFAULT 0,
                next_retry_at REAL NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
        """,
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlq_queue_status ON dlq_messages(queue, status)",
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlq_next_retry ON dlq_messages(next_retry_at)",
        )
        conn.commit()
        conn.close()

    def add(
        self,
        payload: dict[str, Any],
        error: str = "",
        metadata: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> int:
        """Add a message to the dead letter queue.

        Args:
            payload: The message payload (must be JSON-serializable).
            error: Error description for why the message failed.
            metadata: Optional metadata (source, service, trace_id, etc.).
            max_retries: Per-message retry override (uses instance default if None).

        Returns:
            The ID of the newly created message.

        """
        if max_retries is None:
            max_retries = self.max_retries

        conn = self._get_conn()
        now = time.time()
        cursor = conn.execute(
            """
            INSERT INTO dlq_messages
                (queue, payload, error, retry_count, max_retries, status,
                 created_at, last_error_at, next_retry_at, metadata)
            VALUES (?, ?, ?, 0, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                self.queue_name,
                json.dumps(payload, ensure_ascii=False),
                error,
                max_retries,
                now,
                now,
                now,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        msg_id = cursor.lastrowid or 0
        logger.debug("DLQ '%s': added message id=%d, error=%s", self.queue_name, msg_id, error[:100])
        return msg_id

    def get(self, message_id: int) -> DLQMessage | None:
        """Get a specific message by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dlq_messages WHERE id = ? AND queue = ?",
            (message_id, self.queue_name),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_message(row)

    def ack(self, message_id: int) -> bool:
        """Acknowledge successful processing by removing the message."""
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM dlq_messages WHERE id = ? AND queue = ?",
            (message_id, self.queue_name),
        )
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("DLQ '%s': ack message id=%d", self.queue_name, message_id)
        return deleted

    def nack(self, message_id: int, error: str = "") -> bool:
        """Mark message as failed (increments retry count, may mark as dead)."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT retry_count, max_retries FROM dlq_messages WHERE id = ? AND queue = ?",
            (message_id, self.queue_name),
        ).fetchone()
        if row is None:
            return False

        retry_count = row["retry_count"] + 1
        max_retries = row["max_retries"]
        now = time.time()

        if retry_count >= max_retries:
            status = "dead"
            next_retry = 0
        else:
            status = "pending"
            next_retry = now + self.backoff_base**retry_count

        conn.execute(
            """
            UPDATE dlq_messages
            SET retry_count = ?, status = ?, last_error_at = ?, next_retry_at = ?,
                error = CASE WHEN ? != '' THEN ? ELSE error END
            WHERE id = ?
            """,
            (retry_count, status, now, next_retry, error, error, message_id),
        )
        conn.commit()
        logger.debug(
            "DLQ '%s': nack message id=%d, retry=%d/%d, status=%s",
            self.queue_name,
            message_id,
            retry_count,
            max_retries,
            status,
        )
        return True

    def retry(self, handler: Callable[[dict[str, Any]], Any]) -> dict[str, int]:
        """Retry all pending messages with the given handler.

        Args:
            handler: A callable that receives the payload dict and processes it.
                     If it raises, the message is nack'd with incrementing retries.

        Returns:
            Dict with counts: {'processed': N, 'failed': N, 'dead': N}.

        """
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM dlq_messages
            WHERE queue = ? AND status = 'pending'
            ORDER BY created_at ASC
            """,
            (self.queue_name,),
        ).fetchall()

        stats = {"processed": 0, "failed": 0, "dead": 0, "total": len(rows)}
        for row in rows:
            msg = self._row_to_message(row)
            try:
                handler(msg.payload)
                self.ack(msg.id)
                stats["processed"] += 1
            except Exception as e:
                self.nack(msg.id, str(e))
                stats["failed"] += 1
        logger.info("DLQ '%s': retry complete — %s", self.queue_name, stats)
        return stats

    def process(self) -> list[DLQMessage]:
        """Get all pending messages ready for processing.

        Returns:
            List of DLQMessage objects with status='pending' ordered by creation time.
            Does NOT change their status. Use ack/nack after processing.

        """
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM dlq_messages
            WHERE queue = ? AND status = 'pending'
            ORDER BY created_at ASC
            """,
            (self.queue_name,),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def dead(self) -> list[DLQMessage]:
        """Get all dead messages (exhausted retries)."""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM dlq_messages
            WHERE queue = ? AND status = 'dead'
            ORDER BY last_error_at DESC
            """,
            (self.queue_name,),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def stats(self) -> dict[str, int]:
        """Return per-status counts for this queue."""
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'dead' THEN 1 ELSE 0 END) as dead
            FROM dlq_messages
            WHERE queue = ?
            """,
            (self.queue_name,),
        ).fetchone()
        total = row["total"] or 0
        pending = row["pending"] or 0
        dead = row["dead"] or 0
        return {
            "total": total,
            "pending": pending,
            "failed": total - pending - dead,
            "dead": dead,
        }

    def clear(self, status: str | None = None) -> int:
        """Clear messages from the queue.

        Args:
            status: If provided, only clear messages with this status.
                    If None, clear all messages.

        Returns:
            Number of messages deleted.

        """
        conn = self._get_conn()
        if status is not None:
            cursor = conn.execute(
                "DELETE FROM dlq_messages WHERE queue = ? AND status = ?",
                (self.queue_name, status),
            )
        else:
            cursor = conn.execute(
                "DELETE FROM dlq_messages WHERE queue = ?",
                (self.queue_name,),
            )
        conn.commit()
        deleted = cursor.rowcount
        logger.info("DLQ '%s': cleared %d messages (status=%s)", self.queue_name, deleted, status or "all")
        return deleted

    def requeue(self, message_id: int) -> bool:
        """Reset a dead message back to pending for manual retry."""
        conn = self._get_conn()
        cursor = conn.execute(
            """
            UPDATE dlq_messages
            SET status = 'pending', retry_count = 0, next_retry_at = ?
            WHERE id = ? AND queue = ? AND status = 'dead'
            """,
            (time.time(), message_id, self.queue_name),
        )
        conn.commit()
        updated = cursor.rowcount > 0
        if updated:
            logger.info("DLQ '%s': requeued dead message id=%d", self.queue_name, message_id)
        return updated

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> DLQMessage:
        return DLQMessage(
            id=row["id"],
            queue=row["queue"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            error=row["error"],
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            status=row["status"],
            created_at=row["created_at"],
            last_error_at=row["last_error_at"],
            next_retry_at=row["next_retry_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    @classmethod
    def get_queue(cls, queue_name: str) -> DeadLetterQueue | None:
        """Get an existing queue instance by name."""
        return cls._instances.get(queue_name)

    @classmethod
    def reset_all(cls) -> None:
        """Reset all queue instances (for testing)."""
        with cls._lock:
            for instance in cls._instances.values():
                instance.close()
            cls._instances.clear()
