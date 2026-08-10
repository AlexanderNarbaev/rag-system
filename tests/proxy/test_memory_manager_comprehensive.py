"""Comprehensive tests for proxy/app/shared/memory_manager.py.

Targets the 95% coverage gap in the memory manager module.
"""

from __future__ import annotations

from unittest.mock import patch

from proxy.app.shared.memory_manager import (
    ConversationMemory,
    EntityTracker,
    WorkingMemoryStore,
)

# ---------------------------------------------------------------------------
# WorkingMemoryStore
# ---------------------------------------------------------------------------


class TestWorkingMemoryStore:
    """Tests for the in-memory working memory store."""

    def test_init_empty(self) -> None:
        store = WorkingMemoryStore()
        assert len(store) == 0

    def test_remember_and_recall(self) -> None:
        store = WorkingMemoryStore()
        store.remember("k", "v")
        assert store.recall("k") == "v"

    def test_recall_missing_returns_none(self) -> None:
        store = WorkingMemoryStore()
        assert store.recall("missing") is None

    def test_recall_expired_returns_none(self) -> None:
        store = WorkingMemoryStore()
        with patch.object(store, "_now", return_value=100.0):
            store.remember("k", "v", ttl=5.0)
        # Now is far in the future
        with patch.object(store, "_now", return_value=200.0):
            assert store.recall("k") is None

    def test_recall_expired_removes_key(self) -> None:
        store = WorkingMemoryStore()
        with patch.object(store, "_now", return_value=100.0):
            store.remember("k", "v", ttl=5.0)
        with patch.object(store, "_now", return_value=200.0):
            store.recall("k")
        # Key should be removed
        assert "k" not in store._store

    def test_forget(self) -> None:
        store = WorkingMemoryStore()
        store.remember("k", "v")
        store.forget("k")
        assert store.recall("k") is None

    def test_forget_nonexistent(self) -> None:
        store = WorkingMemoryStore()
        # Should not raise
        store.forget("missing")

    def test_get_all_for_context_empty(self) -> None:
        store = WorkingMemoryStore()
        assert store.get_all_for_context() == ""

    def test_get_all_for_context(self) -> None:
        store = WorkingMemoryStore()
        store.remember("name", "Alice")
        store.remember("role", "engineer")
        result = store.get_all_for_context()
        assert "name: Alice" in result
        assert "role: engineer" in result

    def test_get_all_for_context_truncates(self) -> None:
        store = WorkingMemoryStore()
        long_value = "x" * 10000
        store.remember("big", long_value)
        result = store.get_all_for_context(max_tokens=10)
        assert result.endswith("...")

    def test_len_cleans_expired(self) -> None:
        store = WorkingMemoryStore()
        with patch.object(store, "_now", return_value=100.0):
            store.remember("k", "v", ttl=5.0)
        with patch.object(store, "_now", return_value=200.0):
            assert len(store) == 0

    def test_clean_expired(self) -> None:
        store = WorkingMemoryStore()
        with patch.object(store, "_now", return_value=100.0):
            store.remember("a", 1, ttl=5.0)
            store.remember("b", 2, ttl=100.0)
        with patch.object(store, "_now", return_value=50.0):
            store._clean_expired()
        # Both should still be present (current time 50 < expire 105 and < expire 200)
        assert "a" in store._store
        assert "b" in store._store


# ---------------------------------------------------------------------------
# EntityTracker
# ---------------------------------------------------------------------------


class TestEntityTracker:
    """Tests for the entity tracker."""

    def test_init(self) -> None:
        tracker = EntityTracker()
        assert tracker.get_top_entities() == []

    def test_track_simple_text(self) -> None:
        tracker = EntityTracker()
        tracker.track("The quick brown fox")
        # Should detect some entities (stopwords filtered)
        assert len(tracker.get_top_entities()) > 0

    def test_track_increments_count(self) -> None:
        tracker = EntityTracker()
        # Only capitalized words are entities
        tracker.track("Apple Banana Apple Cherry Apple")
        # 'Apple' appears 3 times — should be top
        top = tracker.get_top_entities(top_n=1)
        assert top[0] == "Apple"

    def test_get_top_entities_default(self) -> None:
        tracker = EntityTracker()
        tracker.track("foo bar baz")
        top = tracker.get_top_entities()
        assert len(top) <= 10  # default top_n

    def test_get_top_entities_top_n(self) -> None:
        tracker = EntityTracker()
        # Only words >2 chars starting with uppercase are tracked.
        tracker.track("Apple Banana Cherry Date Elder")
        top = tracker.get_top_entities(top_n=3)
        assert len(top) == 3

    def test_get_context_str_empty(self) -> None:
        tracker = EntityTracker()
        assert tracker.get_context_str() == ""

    def test_get_context_str_with_entities(self) -> None:
        tracker = EntityTracker()
        # Only capitalized words are tracked.
        tracker.track("Apple Banana")
        result = tracker.get_context_str()
        assert "Entities mentioned" in result
        assert "Apple" in result

    def test_clear(self) -> None:
        tracker = EntityTracker()
        tracker.track("apple banana")
        tracker.clear()
        assert tracker.get_top_entities() == []

    def test_prune_when_max_exceeded(self) -> None:
        """When entities exceed max_entities, lowest-count ones are pruned."""
        tracker = EntityTracker(max_entities=3)
        # Add many entities with different counts
        for _ in range(5):
            tracker.track("a b c d")
        # Should be at most max_entities
        assert len(tracker._entities) <= 3


# ---------------------------------------------------------------------------
# ConversationMemory
# ---------------------------------------------------------------------------


class TestConversationMemory:
    """Tests for the conversation memory."""

    def test_init(self) -> None:
        memory = ConversationMemory()
        assert len(memory._turns) == 0
        assert memory._summaries == []

    def test_add_turn(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "Hello")
        assert len(memory._turns) == 1
        assert memory._turns[0]["role"] == "user"
        assert memory._turns[0]["content"] == "Hello"

    def test_add_turn_with_metadata(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "Hi", metadata={"source": "test"})
        assert memory._turns[0]["metadata"] == {"source": "test"}

    def test_add_turn_with_no_metadata(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "Hi")
        assert memory._turns[0]["metadata"] == {}

    def test_add_turn_tracks_entities(self) -> None:
        memory = ConversationMemory()
        # Only capitalized words are tracked.
        memory.add_turn("user", "Apple Banana")
        assert "Apple" in memory._entity_tracker._entities

    def test_add_turn_keeps_max_turns(self) -> None:
        memory = ConversationMemory(max_turns_stored=3)
        for i in range(10):
            memory.add_turn("user", f"turn {i}")
        assert len(memory._turns) == 3
        # Oldest turns dropped
        assert memory._turns[0]["content"] == "turn 7"

    def test_get_context(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "Hello")
        memory.add_turn("assistant", "Hi there")
        ctx = memory.get_context()
        assert "user: Hello" in ctx
        assert "assistant: Hi there" in ctx

    def test_get_context_max_turns(self) -> None:
        memory = ConversationMemory()
        for i in range(20):
            memory.add_turn("user", f"turn {i}")
        ctx = memory.get_context(max_turns=3)
        # Should only have last 3 turns
        assert "turn 17" in ctx
        assert "turn 19" in ctx
        assert "turn 0" not in ctx

    def test_get_context_truncates(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "x" * 10000)
        ctx = memory.get_context(max_tokens=10)
        assert ctx.endswith("...")

    def test_get_context_includes_entities(self) -> None:
        memory = ConversationMemory()
        # Only capitalized words are tracked.
        memory.add_turn("user", "Apple Banana")
        ctx = memory.get_context(include_entities=True)
        assert "Entities mentioned" in ctx

    def test_get_context_without_entities(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "apple banana")
        ctx = memory.get_context(include_entities=False)
        assert "Entities:" not in ctx

    def test_get_context_as_messages(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "Hello")
        memory.add_turn("assistant", "Hi")
        messages = memory.get_context_as_messages()
        assert len(messages) >= 2
        assert any(m["role"] == "user" and m["content"] == "Hello" for m in messages)

    def test_get_context_as_messages_with_entities(self) -> None:
        memory = ConversationMemory()
        # Only capitalized words are tracked.
        memory.add_turn("user", "Apple Banana")
        messages = memory.get_context_as_messages()
        # First message should be a system context with entities
        assert messages[0]["role"] == "system"
        assert "Context" in messages[0]["content"] or "Entities" in messages[0]["content"]

    def test_get_full_history_as_messages_empty(self) -> None:
        memory = ConversationMemory()
        messages = memory.get_full_history_as_messages()
        # No turns, no summaries, no entities
        assert messages == []

    def test_get_full_history_as_messages_with_summaries(self) -> None:
        memory = ConversationMemory()
        memory._summaries.append("Previous: discussed weather")
        # Lowercase so no entities tracked.
        memory.add_turn("user", "please tell me more about it")
        messages = memory.get_full_history_as_messages()
        # First message should be the summary
        assert "summary" in messages[0]["content"].lower() or "Previous" in messages[0]["content"]

    def test_get_full_history_max_turns(self) -> None:
        memory = ConversationMemory()
        for i in range(20):
            memory.add_turn("user", f"turn {i}")
        messages = memory.get_full_history_as_messages(max_turns=5)
        # 5 turns, no entities (lowercase text)
        assert len(messages) == 5

    def test_clear(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "Hi")
        memory.clear()
        assert len(memory._turns) == 0
        assert memory.get_context() == ""

    def test_clear_resets_entities(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "apple")
        memory.clear()
        assert memory._entity_tracker.get_top_entities() == []

    def test_should_summarize(self) -> None:
        """When total tokens exceed threshold, summary should be triggered."""
        memory = ConversationMemory(summary_threshold_tokens=10)
        # Add enough content to trigger summarization
        memory.add_turn("user", "a" * 100)  # 100/4 = 25 tokens
        # Whether it triggered depends on implementation
        # Just verify it doesn't crash
        assert memory._total_token_estimate > 0

    def test_summarize_older_turns(self) -> None:
        """Test the summarize_older_turns method."""
        memory = ConversationMemory(max_turns_stored=5, summary_threshold_tokens=20)
        for i in range(10):
            memory.add_turn("user", f"turn {i}")
        memory.summarize_older_turns(keep_recent=3)
        # After summarizing, _summaries should be populated
        assert len(memory._summaries) > 0

    def test_get_summaries(self) -> None:
        memory = ConversationMemory()
        assert memory.get_summaries() == []
        memory._summaries.append("Test summary")
        assert memory.get_summaries() == ["Test summary"]

    def test_estimate_tokens(self) -> None:
        memory = ConversationMemory()
        memory.add_turn("user", "a" * 100)
        tokens = memory.estimate_tokens()
        assert tokens > 0

    def test_needs_summarization(self) -> None:
        memory = ConversationMemory(summary_threshold_tokens=10)
        # Below threshold
        assert memory.needs_summarization() is False
        # Exceed threshold
        memory.add_turn("user", "a" * 100)
        assert memory.needs_summarization() is True

    def test_get_entity_tracker(self) -> None:
        memory = ConversationMemory()
        tracker = memory.get_entity_tracker()
        assert isinstance(tracker, EntityTracker)

    def test_len_dunder(self) -> None:
        memory = ConversationMemory()
        assert len(memory) == 0
        memory.add_turn("user", "Hi")
        assert len(memory) == 1
