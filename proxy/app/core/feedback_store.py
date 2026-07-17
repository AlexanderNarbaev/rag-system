"""SQLite-backed feedback store for querying, filtering, and analyzing feedback."""

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DB_PATH = Path("./data/feedback.db")


def _get_db_path() -> Path:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


class FeedbackEntry:
    def __init__(self, **kwargs: Any) -> None:
        self.id: str = kwargs.get("id", "")
        self.feedback_id: str = kwargs.get("feedback_id", "")
        self.user_id: str = kwargs.get("user_id", "")
        self.username: str = kwargs.get("username", "")
        self.role: str = kwargs.get("role", "")
        self.rating: str = kwargs.get("rating", "")
        self.feedback_type: str = kwargs.get("feedback_type", "")
        self.comment: str | None = kwargs.get("comment")
        self.correction: str | None = kwargs.get("correction")
        self.question: str | None = kwargs.get("question")
        self.answer: str | None = kwargs.get("answer")
        self.contexts_json: str | None = kwargs.get("contexts_json")
        self.kb_id: str | None = kwargs.get("kb_id")
        self.confidence: float | None = kwargs.get("confidence")
        self.chunk_feedback_json: str | None = kwargs.get("chunk_feedback_json")
        self.retrieval_quality: int | None = kwargs.get("retrieval_quality")
        self.status: str = kwargs.get("status", "pending")
        self.admin_notes: str | None = kwargs.get("admin_notes")
        self.created_at: str = kwargs.get("created_at", "")
        self.updated_at: str = kwargs.get("updated_at", "")

    @property
    def contexts(self) -> list[str]:
        if self.contexts_json:
            return json.loads(self.contexts_json)
        return []

    @property
    def chunk_feedback(self) -> list[dict[str, Any]]:
        if self.chunk_feedback_json:
            return json.loads(self.chunk_feedback_json)
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "feedback_id": self.feedback_id,
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "rating": self.rating,
            "feedback_type": self.feedback_type,
            "comment": self.comment,
            "correction": self.correction,
            "question": self.question,
            "answer": self.answer,
            "contexts": self.contexts,
            "kb_id": self.kb_id,
            "confidence": self.confidence,
            "chunk_feedback": self.chunk_feedback,
            "retrieval_quality": self.retrieval_quality,
            "status": self.status,
            "admin_notes": self.admin_notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class FeedbackStore:
    """Thread-safe SQLite store for feedback entries."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _get_db_path()
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock, sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                    CREATE TABLE IF NOT EXISTS feedback (
                        id TEXT PRIMARY KEY,
                        feedback_id TEXT NOT NULL,
                        user_id TEXT NOT NULL DEFAULT '',
                        username TEXT NOT NULL DEFAULT '',
                        role TEXT NOT NULL DEFAULT '',
                        rating TEXT NOT NULL DEFAULT '',
                        feedback_type TEXT NOT NULL DEFAULT '',
                        comment TEXT,
                        correction TEXT,
                        question TEXT,
                        answer TEXT,
                        contexts_json TEXT,
                        kb_id TEXT,
                        confidence REAL,
                        chunk_feedback_json TEXT,
                        retrieval_quality INTEGER,
                        status TEXT NOT NULL DEFAULT 'pending',
                        admin_notes TEXT,
                        created_at TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL DEFAULT ''
                    )
                """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_kb_id ON feedback(kb_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_feedback_id ON feedback(feedback_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at)")
            conn.commit()

    def _row_to_entry(self, row: tuple[Any, ...]) -> FeedbackEntry:
        columns = [
            "id", "feedback_id", "user_id", "username", "role", "rating",
            "feedback_type", "comment", "correction", "question", "answer",
            "contexts_json", "kb_id", "confidence", "chunk_feedback_json",
            "retrieval_quality", "status", "admin_notes", "created_at", "updated_at",
        ]
        return FeedbackEntry(**dict(zip(columns, row, strict=False)))

    def insert(self, entry: FeedbackEntry) -> None:
        now = datetime.now(UTC).isoformat()
        entry.id = entry.id or entry.feedback_id + "_" + now.replace(":", "").replace("-", "").replace("T", "_")
        entry.created_at = now
        entry.updated_at = now

        with self._lock, sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO feedback VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )""",
                (
                    entry.id,
                    entry.feedback_id,
                    entry.user_id,
                    entry.username,
                    entry.role,
                    entry.rating,
                    entry.feedback_type,
                    entry.comment,
                    entry.correction,
                    entry.question,
                    entry.answer,
                    entry.contexts_json,
                    entry.kb_id,
                    entry.confidence,
                    entry.chunk_feedback_json,
                    entry.retrieval_quality,
                    entry.status,
                    entry.admin_notes,
                    entry.created_at,
                    entry.updated_at,
                ),
            )
            conn.commit()

    def update(self, feedback_id: str, updates: dict[str, Any]) -> bool:
        updates["updated_at"] = datetime.now(UTC).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [feedback_id]

        with self._lock, sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.execute(
                f"UPDATE feedback SET {set_clause} WHERE feedback_id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0

    def get(self, feedback_id: str) -> FeedbackEntry | None:
        with self._lock, sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.execute(
                "SELECT * FROM feedback WHERE feedback_id = ?",
                (feedback_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_entry(row)
        return None

    def list(self, **filters: Any) -> list[FeedbackEntry]:
        conditions: list[str] = []
        params: list[Any] = []

        if "status" in filters and filters["status"]:
            conditions.append("status = ?")
            params.append(filters["status"])
        if "kb_id" in filters and filters["kb_id"]:
            conditions.append("kb_id = ?")
            params.append(filters["kb_id"])
        if "date_from" in filters and filters["date_from"]:
            conditions.append("created_at >= ?")
            params.append(filters["date_from"])
        if "date_to" in filters and filters["date_to"]:
            conditions.append("created_at <= ?")
            params.append(filters["date_to"])
        if "min_confidence" in filters and filters["min_confidence"] is not None:
            conditions.append("confidence <= ?")
            params.append(float(filters["min_confidence"]))

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        limit = int(filters.get("limit", 50))
        offset = int(filters.get("offset", 0))

        with self._lock, sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.execute(
                f"SELECT * FROM feedback{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]

    def stats(self, date_from: str | None = None, date_to: str | None = None) -> dict[str, Any]:
        conditions: list[str] = []
        params: list[Any] = []
        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        with self._lock, sqlite3.connect(str(self._db_path)) as conn:
            pos_neg = conn.execute(
                f"SELECT rating, COUNT(*) as cnt FROM feedback{where} GROUP BY rating",
                params,
            ).fetchall()

            total = sum(r[1] for r in pos_neg)
            pos = next((r[1] for r in pos_neg if r[0] == "positive"), 0)
            neg = next((r[1] for r in pos_neg if r[0] == "negative"), 0)

            corrected_topics = conn.execute(
                f"""SELECT question, COUNT(*) as cnt FROM feedback{where}
                        WHERE correction IS NOT NULL AND correction != ''
                        GROUP BY question ORDER BY cnt DESC LIMIT 10""",
                params,
            ).fetchall()

            avg_conf = conn.execute(
                f"SELECT AVG(confidence) FROM feedback{where} WHERE confidence IS NOT NULL",
                params,
            ).fetchone()

            volume_by_user = conn.execute(
                f"""SELECT username, role, COUNT(*) as cnt FROM feedback{where}
                        GROUP BY username, role ORDER BY cnt DESC""",
                params,
            ).fetchall()

            avg_retrieval = conn.execute(
                f"SELECT AVG(retrieval_quality) FROM feedback{where} WHERE retrieval_quality IS NOT NULL",
                params,
            ).fetchone()

        return {
            "total": total,
            "positive": pos,
            "negative": neg,
            "pos_ratio": round(pos / total, 4) if total > 0 else 0,
            "neg_ratio": round(neg / total, 4) if total > 0 else 0,
            "average_confidence": round(avg_conf[0], 4) if avg_conf and avg_conf[0] else None,
            "average_retrieval_quality": round(avg_retrieval[0], 2) if avg_retrieval and avg_retrieval[0] else None,
            "most_corrected_topics": [{"question": r[0][:100], "count": r[1]} for r in corrected_topics],
            "feedback_by_user": [{"username": r[0], "role": r[1], "count": r[2]} for r in volume_by_user],
        }

    def chunk_stats(self, min_count: int = 1) -> list[dict[str, Any]]:
        with self._lock, sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                """SELECT feedback_id, chunk_feedback_json, retrieval_quality
                       FROM feedback WHERE chunk_feedback_json IS NOT NULL"""
            ).fetchall()

        chunk_scores: dict[str, list[int]] = {}
        for _feedback_id, cf_json, _rq in rows:
            if not cf_json:
                continue
            chunk_feedback: list[dict[str, Any]] = json.loads(cf_json)
            for entry in chunk_feedback:
                cid = entry.get("chunk_id", "")
                score = entry.get("relevance_score")
                if cid and isinstance(score, int):
                    chunk_scores.setdefault(cid, []).append(score)

        results = []
        for cid, scores in chunk_scores.items():
            if len(scores) < min_count:
                continue
            avg_score = sum(scores) / len(scores)
            results.append({
                "chunk_id": cid,
                "average_relevance": round(avg_score, 2),
                "ratings_count": len(scores),
                "low_ratings": sum(1 for s in scores if s <= 2),
            })

        results.sort(key=lambda x: x["average_relevance"])
        return results

    def get_negative_training_pairs(self) -> list[dict[str, Any]]:
        with self._lock, sqlite3.connect(str(self._db_path)) as conn:
            rows = conn.execute(
                """SELECT question, chunk_feedback_json
                       FROM feedback WHERE chunk_feedback_json IS NOT NULL"""
            ).fetchall()

        pairs: list[dict[str, Any]] = []
        for question, cf_json in rows:
            if not cf_json or not question:
                continue
            chunk_feedback: list[dict[str, Any]] = json.loads(cf_json)
            for entry in chunk_feedback:
                if entry.get("relevance_score", 5) <= 2:
                    pairs.append({
                        "query": question.strip(),
                        "chunk_id": entry.get("chunk_id", ""),
                        "relevance_score": entry.get("relevance_score", 0),
                    })

        return pairs


_store: FeedbackStore | None = None


def get_feedback_store() -> FeedbackStore:
    global _store
    if _store is None:
        _store = FeedbackStore()
    return _store
