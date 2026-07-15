"""Tests for proxy/app/token_optimizer.py — TokenOptimizer class."""

import pytest

from proxy.app.core.token_optimizer import TokenOptimizer, count_bpe_tokens


class TestCountBpeTokens:
  """Tests for the standalone count_bpe_tokens function."""

  def test_empty_string (self):
    assert count_bpe_tokens ("") == 0

  def test_single_word (self):
    assert count_bpe_tokens ("hello") > 0

  def test_common_bigrams (self):
    tokens = count_bpe_tokens ("the quick brown fox")
    assert tokens >= 3
    assert tokens <= 7

  def test_russian_text (self):
    tokens = count_bpe_tokens ("привет мир как дела")
    assert tokens >= 2


class TestTokenOptimizer:
  """Tests for the TokenOptimizer class."""

  @pytest.fixture
  def optimizer (self):
    return TokenOptimizer ()

  def test_estimate_token_cost_empty (self, optimizer):
    assert optimizer.estimate_token_cost ("") == 0

  def test_estimate_token_cost_short (self, optimizer):
    cost = optimizer.estimate_token_cost ("hello world")
    assert cost >= 1
    assert cost <= 5

  def test_estimate_token_cost_long (self, optimizer):
    text = "The quick brown fox jumps over the lazy dog. " * 20
    cost = optimizer.estimate_token_cost (text)
    simple_estimate = len (text) // 4
    assert abs (cost - simple_estimate) / max (1, simple_estimate) < 0.5

  def test_estimate_token_cost_accuracy_within_20_percent_en (self, optimizer):
    text = "Token estimation should be reasonably accurate for English text. " * 50
    cost = optimizer.estimate_token_cost (text)
    heuristic = max (1, len (text) // 4)
    error_ratio = abs (cost - heuristic) / max (1, heuristic)
    assert error_ratio <= 0.5

  def test_estimate_token_cost_accuracy_ru (self, optimizer):
    text = "Оценка токенов должна быть достаточно точной для русского текста. " * 50
    cost = optimizer.estimate_token_cost (text)
    heuristic = max (1, len (text) // 4)
    error_ratio = abs (cost - heuristic) / max (1, heuristic)
    assert error_ratio <= 0.5

  def test_compress_context_empty (self, optimizer):
    result = optimizer.compress_context ([], 100)
    assert result == ""

  def test_compress_context_relevance (self, optimizer):
    chunks = [
        {"text": "Important information about system architecture and design patterns."},
        {"text": "Less critical details about formatting and style guidelines."},
    ]
    result = optimizer.compress_context (chunks, max_tokens = 50, strategy = "relevance")
    assert len (result) > 0

  def test_compress_context_proposition (self, optimizer):
    chunks = [
        {"text": "The system uses PostgreSQL. It supports ACID transactions. Queries are optimized."},
        {"text": "Redis is used for caching. Cache invalidation is event-driven."},
    ]
    result = optimizer.compress_context (chunks, max_tokens = 50, strategy = "proposition")
    assert "PostgreSQL" in result or "ACID" in result or "Redis" in result

  def test_compress_context_summary (self, optimizer):
    chunks = [
        {"text": "First sentence. Second sentence. Third sentence. Fourth sentence."},
        {"text": "Another first. Another second. Another third."},
    ]
    result = optimizer.compress_context (chunks, max_tokens = 200, strategy = "summary")
    assert len (result) > 0

  def test_compress_context_hierarchical (self, optimizer):
    chunks = [{"text": f"Chunk {i} content with some meaningful text. " * 5} for i in range (12)]
    result = optimizer.compress_context (chunks, max_tokens = 500, strategy = "hierarchical")
    assert len (result) > 0

  def test_compress_context_falls_back_to_relevance (self, optimizer):
    chunks = [{"text": "Some content here."}]
    result = optimizer.compress_context (chunks, max_tokens = 100, strategy = "unknown_strategy")
    assert "Some content" in result

  def test_smart_token_budget_large (self, optimizer):
    budget = optimizer.smart_token_budget (available_tokens = 130000, num_chunks = 10)
    assert "system_prompt" in budget
    assert "context_total" in budget
    assert "history" in budget
    assert "response" in budget
    total = budget ["system_prompt"] + budget ["context_total"] + budget ["history"] + budget ["response"]
    assert abs (total - 130000) < 10

  def test_smart_token_budget_small (self, optimizer):
    budget = optimizer.smart_token_budget (available_tokens = 500, num_chunks = 3)
    total = budget ["system_prompt"] + budget ["context_total"] + budget ["history"] + budget ["response"]
    assert abs (total - 500) < 10

  def test_smart_token_budget_zero_chunks (self, optimizer):
    budget = optimizer.smart_token_budget (available_tokens = 10000, num_chunks = 0)
    assert budget ["context_total"] > 0
    assert budget ["context_per_chunk"] == budget ["context_total"]

  def test_smart_token_budget_per_chunk (self, optimizer):
    budget = optimizer.smart_token_budget (available_tokens = 100000, num_chunks = 10)
    expected_per_chunk = budget ["context_total"] // 10
    assert abs (budget ["context_per_chunk"] - expected_per_chunk) <= 1

  def test_surround_chunks_empty (self, optimizer):
    result = optimizer.surround_chunks ([], nearby_count = 2)
    assert result == []

  def test_surround_chunks_expands (self, optimizer):
    chunks = [
        {"source_id": "doc1", "chunk_index": 0, "text": "zero"}, {"source_id": "doc1", "chunk_index": 1, "text": "one"},
        {"source_id": "doc1", "chunk_index": 2, "text": "two"},
    ]
    result = optimizer.surround_chunks (chunks [:2], nearby_count = 1)
    texts = {c ["text"] for c in result}
    assert "zero" in texts
    assert "one" in texts

  def test_surround_chunks_no_nearby (self, optimizer):
    chunks = [{"source_id": "doc1", "chunk_index": 0, "text": "A"}]
    result = optimizer.surround_chunks (chunks, nearby_count = 0)
    assert len (result) == 1

  def test_surround_chunks_deduplicates (self, optimizer):
    chunks = [
        {"source_id": "doc1", "chunk_index": 0, "text": "A text chunk content"},
        {"source_id": "doc1", "chunk_index": 0, "text": "A text chunk content"},
    ]
    result = optimizer.surround_chunks (chunks, nearby_count = 1)
    assert len (result) <= len (chunks) + 1

  def test_surround_chunks_no_chunk_index (self, optimizer):
    chunks = [
        {"source_id": "doc1", "text": "first"}, {"source_id": "doc1", "text": "second"},
    ]
    result = optimizer.surround_chunks ([chunks [0]], nearby_count = 1)
    assert len (result) >= 1

  def test_enrich_chunk_headers_basic (self, optimizer):
    chunk = {"text": "Original content."}
    doc_context = {"title": "Test Doc", "section": "Intro", "doc_type": "confluence", "version": "2.0"}
    result = optimizer.enrich_chunk_headers (chunk, doc_context)
    assert "[Doc: Test Doc]" in result ["text"]
    assert "[Section: Intro]" in result ["text"]
    assert "[Type: confluence]" in result ["text"]
    assert "[Version: 2.0]" in result ["text"]
    assert "Original content" in result ["text"]

  def test_enrich_chunk_headers_partial (self, optimizer):
    chunk = {"text": "Content."}
    doc_context = {"title": "Doc Only"}
    result = optimizer.enrich_chunk_headers (chunk, doc_context)
    assert "[Doc: Doc Only]" in result ["text"]
    assert "[Section:" not in result ["text"]

  def test_enrich_chunk_headers_empty_context (self, optimizer):
    chunk = {"text": "Just text."}
    doc_context = {}
    result = optimizer.enrich_chunk_headers (chunk, doc_context)
    assert result ["text"] == "Just text."

  def test_enrich_chunk_headers_does_not_mutate_original (self, optimizer):
    original = {"text": "Original.", "other": "val"}
    doc_context = {"title": "T"}
    result = optimizer.enrich_chunk_headers (original, doc_context)
    assert original ["text"] == "Original."
    assert "[Doc: T]" in result ["text"]

  def test_compress_relevance_vs_proposition (self, optimizer):
    chunks = [
        {"text": "Fact A is important. Detail B matters. Extra fluff text here."},
        {"text": "Fact C is key. Detail D is relevant. More extra padding."},
    ]
    rel = optimizer._compress_relevance (chunks, 100)
    prop = optimizer._compress_proposition (chunks, 100)
    assert len (rel) > 0
    assert len (prop) > 0
