# proxy/app/memory_manager.py
"""Multi-tier memory architecture for RAG system.

Three-tier memory:
1. WorkingMemoryStore - session-specific, TTL-based, Redis/in-memory
2. ConversationMemory - episodic, conversation history with summarization
3. QueryCache - semantic query cache for similar queries
"""

import asyncio
import contextlib
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


class EntityTracker:
    """Tracks entities mentioned across conversation turns."""

    def __init__(self, max_entities: int = 500) -> None:
        self._entities: dict[str, int] = {}  # entity name -> mention count
        self._max_entities = max_entities

    def _prune(self) -> None:
        while len(self._entities) > self._max_entities:
            oldest = min(self._entities.keys(), key=lambda k: self._entities[k])
            del self._entities[oldest]

    def track(self, text: str) -> None:
        """Track capitalized words and technical terms from text."""
        words = text.split()
        for word in words:
            clean = word.strip(".,;:!?()[]{}'\"")
            if len(clean) > 2 and (clean[0].isupper() or "_" in clean or "-" in clean):
                self._entities[clean] = self._entities.get(clean, 0) + 1
        if len(self._entities) > self._max_entities:
            self._prune()

    def get_top_entities(self, top_n: int = 10) -> list[str]:
        """Return most frequently mentioned entities."""
        sorted_entities = sorted(self._entities.items(), key=lambda x: -x[1])
        return [e for e, _ in sorted_entities[:top_n]]

    def get_context_str(self) -> str:
        entities = self.get_top_entities(5)
        if not entities:
            return ""
        return f"Entities mentioned in conversation: {', '.join(entities)}"

    def clear(self) -> None:
        self._entities.clear()


class ConversationMemory:
    """Episodic memory for conversation context with entity tracking and summarization."""

    def __init__(self, max_turns_stored: int = 100, summary_threshold_tokens: int = 2000):
        self._turns: list[dict[str, Any]] = []
        self._summaries: list[str] = []
        self._max_turns_stored = max_turns_stored
        self._summary_threshold_tokens = summary_threshold_tokens
        self._entity_tracker = EntityTracker()
        self._total_token_estimate = 0

    def add_turn(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        """Add a conversation turn with entity tracking."""
        self._turns.append(
            {
                "role": role,
                "content": content,
                "timestamp": time.time(),
                "metadata": metadata or {},
            },
        )
        self._entity_tracker.track(content)
        self._total_token_estimate += len(content) // 4
        if len(self._turns) > self._max_turns_stored:
            self._turns = self._turns[-self._max_turns_stored :]

    def get_context(
        self,
        max_turns: int = 10,
        max_tokens: int = 2000,
        include_entities: bool = True,
    ) -> str:
        """Get recent conversation turns as context string."""
        turns = self._turns[-max_turns:]
        lines = []
        for t in turns:
            lines.append(f"{t['role']}: {t['content']}")
        if include_entities:
            entities_str = self._entity_tracker.get_context_str()
            if entities_str:
                lines.insert(0, entities_str)
        result = "\n".join(lines)
        if len(result) > max_tokens * 4:
            result = result[: max_tokens * 4] + "..."
        return result

    def get_context_as_messages(self, max_turns: int = 10) -> list[dict[str, str]]:
        """Get recent turns as a list of message dicts for LLM prompts."""
        turns = self._turns[-max_turns:]
        messages = []
        for t in turns:
            messages.append({"role": t["role"], "content": t["content"]})
        entities_str = self._entity_tracker.get_context_str()
        if entities_str:
            messages.insert(0, {"role": "system", "content": f"[Context] {entities_str}"})
        return messages

    def get_full_history_as_messages(self, max_turns: int = 10) -> list[dict[str, str]]:
        """Get recent turns formatted for LLM, including summaries."""
        messages: list[dict[str, str]] = []
        if self._summaries:
            summary_text = "\n".join(self._summaries)
            messages.append(
                {
                    "role": "system",
                    "content": f"[Previous conversation summary]\n{summary_text}",
                },
            )
        turns = self._turns[-max_turns:]
        for t in turns:
            messages.append({"role": t["role"], "content": t["content"]})
        entities_str = self._entity_tracker.get_context_str()
        if entities_str:
            messages.insert(0, {"role": "system", "content": f"[Context] {entities_str}"})
        return messages

    def estimate_tokens(self) -> int:
        """Estimate total tokens in conversation memory."""
        total = self._total_token_estimate
        for s in self._summaries:
            total += len(s) // 4
        return total

    def needs_summarization(self, threshold_tokens: int | None = None) -> bool:
        """Check if conversation needs summarization."""
        threshold = threshold_tokens or self._summary_threshold_tokens
        return self.estimate_tokens() > threshold

    def summarize_older_turns(self, keep_recent: int = 5) -> None:
        """Summarize older conversation turns into a compressed form."""
        if len(self._turns) <= keep_recent:
            return
        older = self._turns[:-keep_recent]
        recent = self._turns[-keep_recent:]
        summary_parts = []
        for t in older:
            role_short = t["role"][:1].upper()
            content_preview = t["content"][:120].replace("\n", " ")
            summary_parts.append(f"{role_short}: {content_preview}...")
        self._summaries.append("[SUMMARY] " + " | ".join(summary_parts))
        self._turns = recent
        self._total_token_estimate = sum(len(t["content"]) // 4 for t in recent)
        if len(self._summaries) > 3:
            self._summaries = self._summaries[-3:]

    def get_summaries(self) -> list[str]:
        return list(self._summaries)

    def get_entity_tracker(self) -> EntityTracker:
        return self._entity_tracker

    def clear(self) -> None:
        self._turns.clear()
        self._summaries.clear()
        self._entity_tracker.clear()
        self._total_token_estimate = 0

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


# Process-level conversation store keyed by session_id
# Each entry: (ConversationMemory, created_at_timestamp)
_conversation_store: dict[str, tuple[ConversationMemory, float]] = {}
_store_max_entries = 1000


def _get_session_ttl() -> int:
    from proxy.app.shared.config import SESSION_TTL

    return SESSION_TTL


def get_conversation(session_id: str) -> ConversationMemory:
    """Get or create a ConversationMemory for a session.

    If the existing session has expired (older than SESSION_TTL),
    a fresh ConversationMemory is created in its place.
    """
    now = time.time()
    ttl = _get_session_ttl()

    if session_id in _conversation_store:
        memory, created_at = _conversation_store[session_id]
        if ttl > 0 and (now - created_at) > ttl:
            logger.info(
                "Session %s expired (age=%.0fs, ttl=%ds), creating fresh session",
                session_id[:12],
                now - created_at,
                ttl,
            )
            del _conversation_store[session_id]
        else:
            return memory

    from proxy.app.shared.config import CONVERSATION_SUMMARY_THRESHOLD_TOKENS

    _conversation_store[session_id] = (
        ConversationMemory(
            summary_threshold_tokens=CONVERSATION_SUMMARY_THRESHOLD_TOKENS,
        ),
        now,
    )
    _prune_store()
    return _conversation_store[session_id][0]


def _prune_store() -> None:
    """Prune oldest sessions if store exceeds max size."""
    global _conversation_store
    if len(_conversation_store) > _store_max_entries:
        keys = sorted(_conversation_store.keys())
        to_remove = keys[: len(keys) - _store_max_entries // 2]
        for k in to_remove:
            del _conversation_store[k]


def prune_expired_sessions() -> int:
    """Prune all sessions older than SESSION_TTL. Returns count of sessions pruned."""
    ttl = _get_session_ttl()
    if ttl <= 0:
        return 0
    now = time.time()
    expired = [sid for sid, (_, created_at) in _conversation_store.items() if (now - created_at) > ttl]
    for sid in expired:
        del _conversation_store[sid]
    if expired:
        logger.info(
            "Pruned %d expired session(s) (ttl=%ds, remaining=%d)",
            len(expired),
            ttl,
            len(_conversation_store),
        )
    return len(expired)


_cleanup_task: asyncio.Task[None] | None = None


async def _session_cleanup_loop(interval_seconds: int = 300) -> None:
    """Background loop that periodically prunes expired sessions."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            pruned = prune_expired_sessions()
            if pruned:
                logger.info("Periodic session cleanup pruned %d expired sessions", pruned)
        except Exception:
            logger.exception("Error during periodic session cleanup")


def start_session_cleanup(interval_seconds: int = 300) -> None:
    """Start the background session cleanup loop (call from FastAPI lifespan)."""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.ensure_future(_session_cleanup_loop(interval_seconds))
        logger.info("Session cleanup started (interval=%ds, ttl=%ds)", interval_seconds, _get_session_ttl())


async def stop_session_cleanup() -> None:
    """Stop the background session cleanup loop."""
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _cleanup_task
        _cleanup_task = None
        logger.info("Session cleanup stopped")


def enrich_query_with_context(conversation: ConversationMemory, user_query: str) -> str:
    """Enrich a user query with conversation context for better retrieval.

    Prepends last 2 conversation turns and tracked entities as context,
    helping resolve anaphoric references like "this", "that", "это", "этого".
    """
    if len(conversation) == 0:
        return user_query

    parts: list[str] = []

    entities = conversation.get_entity_tracker().get_top_entities(5)
    if entities:
        parts.append(f"[Entities: {', '.join(entities)}]")

    recent_context = conversation.get_context(max_turns=2, include_entities=False)
    if recent_context:
        parts.append(f"[Previous conversation:\n{recent_context}\n]")

    if not parts:
        return user_query

    parts.append(f"Current question: {user_query}")
    return "\n".join(parts)


def clear_conversation(session_id: str) -> None:
    """Clear conversation memory for a session."""
    if session_id in _conversation_store:
        _conversation_store[session_id][0].clear()
        del _conversation_store[session_id]
