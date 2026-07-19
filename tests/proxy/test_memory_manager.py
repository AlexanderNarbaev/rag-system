"""Tests for proxy/app/memory_manager.py - multi-tier memory architecture."""

import time
from unittest.mock import patch

from proxy.app.shared.memory_manager import (
    ConversationMemory,
    EntityTracker,
    MemoryManager,
    QueryCache,
    WorkingMemoryStore,
    _conversation_store,
    clear_conversation,
    enrich_query_with_context,
    get_conversation,
    prune_expired_sessions,
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

    def test_get_context_truncates_long_result(self):
        mem = ConversationMemory()
        # Add turns with long content to exceed max_tokens * 4 chars
        long_content = "x" * 5000
        mem.add_turn("user", long_content)
        ctx = mem.get_context(max_tokens=100)  # 100 * 4 = 400 chars limit
        assert len(ctx) <= 403  # 400 + "..."
        assert ctx.endswith("...")


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


class TestEntityTracker:
    """Tests for EntityTracker — entity tracking across conversation turns."""

    def test_track_capitalized_words(self):
        tracker = EntityTracker()
        tracker.track("Let's discuss RAG and Neo4j deployment.")
        top = tracker.get_top_entities(5)
        assert "RAG" in top
        assert "Neo4j" in top

    def test_track_underscored_terms(self):
        tracker = EntityTracker()
        tracker.track("Use the deploy_k8s.sh script.")
        top = tracker.get_top_entities(5)
        assert "deploy_k8s.sh" in top

    def test_clears_entities(self):
        tracker = EntityTracker()
        tracker.track("RAG is great")
        tracker.clear()
        assert tracker.get_top_entities() == []

    def test_get_context_str_non_empty(self):
        tracker = EntityTracker()
        tracker.track("RAG and Neo4j integration")
        ctx = tracker.get_context_str()
        assert "RAG" in ctx
        assert "Entities mentioned in conversation" in ctx

    def test_get_context_str_empty(self):
        tracker = EntityTracker()
        assert tracker.get_context_str() == ""

    def test_ignores_short_words(self):
        tracker = EntityTracker()
        tracker.track("Hi AI")
        top = tracker.get_top_entities(5)
        assert "Hi" not in top

    def test_prune_max_entities(self):
        tracker = EntityTracker(max_entities=3)
        for i in range(5):
            tracker.track(f"Entity{i}")
        assert len(tracker._entities) <= 3


class TestSessionTTL:
    """Tests for session TTL and expiration."""

    def setup_method(self):
        for sid in list(_conversation_store.keys()):
            del _conversation_store[sid]

    def teardown_method(self):
        for sid in list(_conversation_store.keys()):
            del _conversation_store[sid]

    @patch("proxy.app.shared.memory_manager._get_session_ttl", return_value=1)
    def test_session_expires_after_ttl(self, _mock):
        conv = get_conversation("test-session-1")
        conv.add_turn("user", "hello")
        assert len(conv) == 1
        time.sleep(1.1)
        conv2 = get_conversation("test-session-1")
        assert len(conv2) == 0
        assert conv2 is not conv

    @patch("proxy.app.shared.memory_manager._get_session_ttl", return_value=0)
    def test_ttl_zero_no_expiry(self, _mock):
        conv = get_conversation("test-session-2")
        conv.add_turn("user", "hello")
        conv2 = get_conversation("test-session-2")
        assert len(conv2) == 1
        assert conv2 is conv

    @patch("proxy.app.shared.memory_manager._get_session_ttl", return_value=3600)
    def test_no_expiry_within_ttl(self, _mock):
        conv = get_conversation("test-session-3")
        conv.add_turn("user", "hello")
        conv2 = get_conversation("test-session-3")
        assert len(conv2) == 1
        assert conv2 is conv

    @patch("proxy.app.shared.memory_manager._get_session_ttl", return_value=1)
    def test_prune_expired_sessions(self, _mock):
        conv1 = get_conversation("session-a")
        conv1.add_turn("user", "a")
        time.sleep(1.1)
        conv2 = get_conversation("session-b")
        conv2.add_turn("user", "b")
        pruned = prune_expired_sessions()
        assert pruned >= 1
        assert "session-a" not in _conversation_store
        assert "session-b" in _conversation_store

    @patch("proxy.app.shared.memory_manager._get_session_ttl", return_value=0)
    def test_prune_with_ttl_zero_does_nothing(self, _mock):
        get_conversation("sess")
        assert prune_expired_sessions() == 0


class TestEnrichQueryWithContext:
    """Tests for query enrichment with conversation context."""

    def test_enrich_empty_conversation(self):
        conv = ConversationMemory()
        result = enrich_query_with_context(conv, "hello")
        assert result == "hello"

    def test_enrich_with_prior_turns(self):
        conv = ConversationMemory()
        conv.add_turn("user", "What is RAG?")
        conv.add_turn("assistant", "RAG is Retrieval Augmented Generation.")
        result = enrich_query_with_context(conv, "How does it work?")
        assert "What is RAG" in result
        assert "Retrieval Augmented" in result
        assert "How does it work?" in result

    def test_enrich_includes_entities(self):
        conv = ConversationMemory()
        conv.add_turn("user", "Tell me about Neo4j and Qdrant")
        conv.add_turn("assistant", "Neo4j is a graph DB, Qdrant is a vector DB")
        result = enrich_query_with_context(conv, "How do they compare?")
        assert "Neo4j" in result
        assert "Qdrant" in result

    def test_enrich_with_anaphoric_reference(self):
        conv = ConversationMemory()
        conv.add_turn("user", "Расскажи про архитектуру RAG")
        conv.add_turn("assistant", "RAG использует гибридный поиск через Qdrant")
        result = enrich_query_with_context(conv, "А как насчёт этого?")
        assert "Расскажи про архитектуру" in result
        assert "гибридный поиск" in result
        assert "как насчёт этого" in result
        assert "RAG" in result

    def test_enrich_only_last_2_turns(self):
        conv = ConversationMemory()
        for i in range(5):
            conv.add_turn("user", f"question {i}")
            conv.add_turn("assistant", f"answer {i}")
        result = enrich_query_with_context(conv, "latest question")
        assert "question 4" in result
        assert "answer 4" in result
        assert "question 0" not in result
        assert "question 3" not in result

    def test_clear_conversation_removes_from_store(self):
        get_conversation("test-clear")
        assert "test-clear" in _conversation_store
        clear_conversation("test-clear")
        assert "test-clear" not in _conversation_store
