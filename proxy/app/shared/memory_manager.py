# proxy/app/memory_manager.py
"""
Multi-tier memory architecture for RAG system.

Three-tier memory:
1. WorkingMemoryStore - session-specific, TTL-based, Redis/in-memory
2. ConversationMemory - episodic, conversation history with summarization
3. QueryCache - semantic query cache for similar queries
"""

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class WorkingMemoryStore:
    """Working memory with TTL, backed by Redis or in-memory."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}

    def _now(self) -> float:
        return time.monotonic()

    def remember(self, key: str, value: Any, ttl: float = 300) -> None:
        self._store[key] = (value, self._now() + ttl)

    def recall(self, key: str) -> Any | None:
        if key not in self._store:
            return None
        value, expire_at = self._store[key]
        if self._now() > expire_at:
            del self._store[key]
            return None
        return value

    def forget(self, key: str) -> None:
        self._store.pop(key, None)

    def get_all_for_context(self, max_tokens: int = 500) -> str:
        self._clean_expired()
        if not self._store:
            return ""
        lines = []
        for key, (value, _) in self._store.items():
            lines.append(f"- {key}: {value}")
        result = "\n".join(lines)
        if len(result) > max_tokens * 4:
            result = result[: max_tokens * 4] + "..."
        return result

    def _clean_expired(self) -> None:
        now = self._now()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]

    def __len__(self) -> int:
        self._clean_expired()
        return len(self._store)


class ConversationMemory:
    """Episodic memory for conversation context."""

    def __init__(self, max_turns_stored: int = 100):
        self._turns: list[dict[str, Any]] = []
        self._summaries: list[str] = []
        self._max_turns_stored = max_turns_stored

    def add_turn(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        self._turns.append(
            {
                "role": role,
                "content": content,
                "timestamp": time.time(),
                "metadata": metadata or {},
            }
        )
        if len(self._turns) > self._max_turns_stored:
            self._turns = self._turns[-self._max_turns_stored :]

    def get_context(self, max_turns: int = 10, max_tokens: int = 2000) -> str:
        turns = self._turns[-max_turns:]
        lines = []
        for t in turns:
            lines.append(f"{t['role']}: {t['content']}")
        result = "\n".join(lines)
        if len(result) > max_tokens * 4:
            result = result[: max_tokens * 4] + "..."
        return result

    def summarize_older_turns(self, keep_recent: int = 5) -> None:
        if len(self._turns) <= keep_recent:
            return
        older = self._turns[:-keep_recent]
        recent = self._turns[-keep_recent:]
        summary_parts = []
        for t in older:
            summary_parts.append(f"{t['role']}: {t['content'][:80]}...")
        self._summaries.append("[SUMMARY] " + " | ".join(summary_parts))
        self._turns = recent

    def get_summaries(self) -> list[str]:
        return list(self._summaries)

    def clear(self) -> None:
        self._turns.clear()
        self._summaries.clear()

    def __len__(self) -> int:
        return len(self._turns)


class QueryCache:
    """Semantic query cache: returns cached response for similar queries."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, float]] = {}
        self._embeddings: dict[str, list[float]] = {}

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        result: float = dot / (norm_a * norm_b)
        return result

    def _hash_embedding(self, embedding: list[float]) -> str:
        raw = json.dumps([round(x, 6) for x in embedding]).encode()
        return hashlib.md5(raw).hexdigest()

    def find_similar(self, query_embedding: list[float], threshold: float = 0.95) -> str | None:
        now = time.monotonic()
        best_key = None
        best_score = 0.0
        for key, (_response, expire_at) in list(self._cache.items()):
            if now > expire_at:
                del self._cache[key]
                self._embeddings.pop(key, None)
                continue
            if key in self._embeddings:
                score = self._cosine_similarity(query_embedding, self._embeddings[key])
                if score > best_score:
                    best_score = score
                    best_key = key
        if best_key and best_score >= threshold:
            return self._cache[best_key][0]
        return None

    def store(self, query_embedding: list[float], response: str, ttl: float = 3600) -> None:
        key = self._hash_embedding(query_embedding)
        self._embeddings[key] = query_embedding
        self._cache[key] = (response, time.monotonic() + ttl)

    def clear(self) -> None:
        self._cache.clear()
        self._embeddings.clear()

    def __len__(self) -> int:
        return len(self._cache)


class MemoryManager:
    """Multi-tier memory system for RAG."""

    def __init__(self) -> None:
        self.working_memory = WorkingMemoryStore()
        self.conversation_memory = ConversationMemory()
        self.query_cache = QueryCache()

    def add_turn(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        self.conversation_memory.add_turn(role, content, metadata)

    def get_full_context(self, max_turns: int = 10, max_tokens: int = 2000) -> str:
        parts = []
        wm = self.working_memory.get_all_for_context(max_tokens=max_tokens // 2)
        if wm:
            parts.append(f"Working memory:\n{wm}")
        cm = self.conversation_memory.get_context(max_turns=max_turns, max_tokens=max_tokens)
        if cm:
            parts.append(f"Conversation history:\n{cm}")
        return "\n\n".join(parts)
