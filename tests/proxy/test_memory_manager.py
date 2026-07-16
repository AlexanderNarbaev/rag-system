"""Tests for proxy/app/memory_manager.py - multi-tier memory architecture."""

import time

from proxy.app.shared.memory_manager import (
    ConversationMemory,
    MemoryManager,
    QueryCache,
    WorkingMemoryStore,
)


class TestWorkingMemoryStore:
    """Tests for WorkingMemoryStore - TTL-based in-memory store."""

    def test_remember_and_recall(self):
        store = WorkingMemoryStore()
        store.remember("key1", "value1")
        assert store.recall("key1") == "value1"

    def test_recall_missing_key(self):
        store = WorkingMemoryStore()
        assert store.recall("nonexistent") is None

    def test_recall_after_ttl_expiry(self):
        store = WorkingMemoryStore()
        store.remember("key1", "value1", ttl=0.01)
        time.sleep(0.02)
        assert store.recall("key1") is None

    def test_forget(self):
        store = WorkingMemoryStore()
        store.remember("key1", "value1")
        store.forget("key1")
        assert store.recall("key1") is None

    def test_forget_nonexistent(self):
        store = WorkingMemoryStore()
        store.forget("nonexistent")

    def test_get_all_for_context(self):
        store = WorkingMemoryStore()
        store.remember("topic", "RAG architecture")
        store.remember("version", "2.0")
        context = store.get_all_for_context()
        assert "RAG architecture" in context
        assert "2.0" in context

    def test_get_all_for_context_empty(self):
        store = WorkingMemoryStore()
        assert store.get_all_for_context() == ""

    def test_get_all_for_context_token_limit(self):
        store = WorkingMemoryStore()
        store.remember("key", "x" * 10000)
        context = store.get_all_for_context(max_tokens=10)
        assert len(context) <= 10 * 4 + 3

    def test_len_excludes_expired(self):
        store = WorkingMemoryStore()
        store.remember("key1", "v1", ttl=0.01)
        store.remember("key2", "v2", ttl=300)
        time.sleep(0.02)
        assert len(store) == 1

    def test_complex_values(self):
        store = WorkingMemoryStore()
        data = {"nested": [1, 2, 3], "flag": True}
        store.remember("complex", data)
        assert store.recall("complex") == data


class TestConversationMemory:
    """Tests for ConversationMemory - episodic conversation history."""

    def test_add_turn_and_get_context(self):
        mem = ConversationMemory()
        mem.add_turn("user", "What is RAG?")
        mem.add_turn("assistant", "RAG is Retrieval Augmented Generation.")
        ctx = mem.get_context()
        assert "What is RAG" in ctx
        assert "Retrieval Augmented" in ctx

    def test_get_context_respects_max_turns(self):
        mem = ConversationMemory()
        for i in range(20):
            mem.add_turn("user", f"question {i}")
            mem.add_turn("assistant", f"answer {i}")
        ctx = mem.get_context(max_turns=4)
        lines = ctx.split("\n")
        assert len(lines) == 4

    def test_summarize_older_turns(self):
        mem = ConversationMemory()
        for i in range(10):
            mem.add_turn("user", f"question {i}")
            mem.add_turn("assistant", f"answer {i}")
        mem.summarize_older_turns(keep_recent=4)
        summaries = mem.get_summaries()
        assert len(summaries) == 1
        assert "[SUMMARY]" in summaries[0]
        assert len(mem) == 4

    def test_summarize_noop_when_few_turns(self):
        mem = ConversationMemory()
        mem.add_turn("user", "hello")
        mem.summarize_older_turns(keep_recent=5)
        assert len(mem) == 1
        assert mem.get_summaries() == []

    def test_clear(self):
        mem = ConversationMemory()
        mem.add_turn("user", "hello")
        mem.summarize_older_turns(keep_recent=0)
        assert len(mem.get_summaries()) > 0
        mem.clear()
        assert len(mem) == 0
        assert mem.get_summaries() == []

    def test_turns_include_metadata(self):
        mem = ConversationMemory()
        mem.add_turn("user", "query", metadata={"source": "web"})
        ctx = mem.get_context()
        assert "query" in ctx

    def test_max_turns_stored_truncates(self):
        mem = ConversationMemory(max_turns_stored=5)
        for i in range(10):
            mem.add_turn("user", f"q{i}")
        assert len(mem) == 5
        ctx = mem.get_context(max_turns=10)
        assert "q5" in ctx
        assert "q0" not in ctx


class TestQueryCache:
    """Tests for QueryCache - semantic similarity matching."""

    def test_find_similar_returns_none_when_empty(self):
        cache = QueryCache()
        assert cache.find_similar([0.1, 0.2, 0.3]) is None

    def test_store_and_find_similar_exact_match(self):
        cache = QueryCache()
        embedding = [0.1, 0.2, 0.3]
        cache.store(embedding, "cached response")
        result = cache.find_similar(embedding, threshold=0.95)
        assert result == "cached response"

    def test_find_similar_high_similarity(self):
        cache = QueryCache()
        emb1 = [0.1, 0.2, 0.3]
        emb2 = [0.1, 0.2, 0.31]
        cache.store(emb1, "response from similar query")
        result = cache.find_similar(emb2, threshold=0.99)
        assert result == "response from similar query"

    def test_find_similar_below_threshold(self):
        cache = QueryCache()
        emb1 = [0.1, 0.2, 0.3]
        emb2 = [0.9, 0.8, 0.7]
        cache.store(emb1, "response")
        result = cache.find_similar(emb2, threshold=0.95)
        assert result is None

    def test_ttl_expiration_removes_entry(self):
        cache = QueryCache()
        embedding = [0.1, 0.2, 0.3]
        cache.store(embedding, "response", ttl=0.01)
        time.sleep(0.02)
        result = cache.find_similar(embedding)
        assert result is None

    def test_clear_removes_all(self):
        cache = QueryCache()
        cache.store([0.1, 0.2], "r1")
        cache.store([0.3, 0.4], "r2")
        cache.clear()
        assert len(cache) == 0

    def test_cosine_different_lengths(self):
        cache = QueryCache()
        cache.store([0.1, 0.2, 0.3], "r1")
        result = cache.find_similar([0.1, 0.2])
        assert result is None

    def test_cosine_zero_vector(self):
        cache = QueryCache()
        cache.store([0.0, 0.0, 0.0], "zero")
        result = cache.find_similar([0.0, 0.0, 0.0])
        assert result is None


class TestMemoryManager:
    """Tests for MemoryManager - multi-tier memory orchestration."""

    def test_add_turn_delegates_to_conversation(self):
        mm = MemoryManager()
        mm.add_turn("user", "test query")
        ctx = mm.get_full_context()
        assert "test query" in ctx

    def test_get_full_context_includes_working_memory(self):
        mm = MemoryManager()
        mm.working_memory.remember("topic", "RAG")
        ctx = mm.get_full_context()
        assert "Working memory" in ctx
        assert "RAG" in ctx

    def test_get_full_context_includes_conversation(self):
        mm = MemoryManager()
        mm.add_turn("user", "hello")
        ctx = mm.get_full_context()
        assert "Conversation history" in ctx
        assert "hello" in ctx

    def test_get_full_context_empty(self):
        mm = MemoryManager()
        ctx = mm.get_full_context()
        assert ctx == ""

    def test_query_cache_is_accessible(self):
        mm = MemoryManager()
        emb = [0.1, 0.2, 0.3]
        mm.query_cache.store(emb, "response")
        assert mm.query_cache.find_similar(emb) == "response"
