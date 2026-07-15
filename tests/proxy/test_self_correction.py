# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for self-correction engine: CRAG, reorder, self-critique, LLMLingua compression."""

import pytest

from proxy.app.core.context import (
  KnowledgeStrip,
  decompose_to_strips,
  reorder_chunks,
)
from proxy.app.core.token_optimizer import (
  TokenOptimizer,
  _compute_token_surprise,
  _score_sentence_by_keyword_density,
  compress_with_perplexity,
)

# ── F2: CRAG Knowledge Strip Decomposition ──


class TestDecomposeToStrips:
  """Tests for CRAG knowledge strip decomposition."""

  def test_decompose_single_chunk (self):
    chunks_with_scores = [
        (
            {
                "text": "Docker is a containerization platform. It uses OS-level virtualization.",
                "source_type": "docs",
            }, 0.95,
        )
    ]
    strips = decompose_to_strips (chunks_with_scores)
    assert len (strips) >= 1
    for s in strips:
      assert isinstance (s, KnowledgeStrip)
      assert len (s.text) > 0

  def test_decompose_multiple_chunks (self):
    chunks_with_scores = [
        ({"text": "First sentence. Second sentence. Third sentence.", "source_type": "wiki"}, 0.9),
        ({"text": "Another paragraph here. More details follow.", "source_type": "wiki"}, 0.7),
    ]
    strips = decompose_to_strips (chunks_with_scores)
    assert len (strips) >= 2

  def test_empty_chunks (self):
    strips = decompose_to_strips ([])
    assert strips == []

  def test_filter_below_threshold (self):
    chunks_with_scores = [
        ({"text": "High relevance content here.", "source_type": "docs"}, 0.9),
        ({"text": "Low relevance noise.", "source_type": "docs"}, 0.05),
    ]
    strips = decompose_to_strips (chunks_with_scores, relevance_threshold = 0.2)
    scores = [s.score for s in strips]
    assert any (s < 0.2 for s in scores) is False

  def test_strips_carry_metadata (self):
    chunks_with_scores = [
        ({"text": "This is a meaningful item sentence.", "source_type": "confluence", "doc_title": "My Doc"}, 0.85),
    ]
    strips = decompose_to_strips (chunks_with_scores)
    assert len (strips) > 0
    strip = strips [0]
    assert strip.source_type == "confluence"
    assert strip.doc_title == "My Doc"

  def test_recompose_to_context (self):
    chunks_with_scores = [
        ({"text": "First paragraph with text.", "source_type": "docs"}, 0.95),
        ({"text": "Second paragraph here.", "source_type": "docs"}, 0.7),
    ]
    strips = decompose_to_strips (chunks_with_scores)
    recomposed = " ".join (s.text for s in strips)
    assert len (recomposed) > 0


class TestKnowledgeStrip:
  """Tests for KnowledgeStrip dataclass."""

  def test_fields (self):
    ks = KnowledgeStrip (text = "Sample text", score = 0.85, source_type = "confluence", doc_title = "Test Doc",
        chunk_index = 0, sentence_index = 1, )
    assert ks.text == "Sample text"
    assert ks.score == 0.85
    assert ks.source_type == "confluence"
    assert ks.doc_title == "Test Doc"
    assert ks.chunk_index == 0
    assert ks.sentence_index == 1


# ── F4: LongContextReorder ──


class TestReorderChunks:
  """Tests for LongContextReorder (counters 'Lost in the Middle')."""

  def test_reorder_puts_best_at_start_and_end (self):
    chunks = [
        ({"text": "Best content", "score": 0.95}, 0.95), ({"text": "Good content", "score": 0.85}, 0.85),
        ({"text": "Medium content", "score": 0.60}, 0.60), ({"text": "Low content", "score": 0.30}, 0.30),
    ]
    reordered = reorder_chunks (chunks)
    assert len (reordered) == len (chunks)
    first_score = reordered [0] [1]
    last_score = reordered [-1] [1]
    assert first_score >= 0.8, f"Best should be first, got {first_score}"
    assert last_score >= 0.5, f"Second-best should be last, got {last_score}"

  def test_reorder_single_item (self):
    chunks = [({"text": "only", "score": 0.5}, 0.5)]
    result = reorder_chunks (chunks)
    assert len (result) == 1
    assert result [0] [0] ["text"] == "only"

  def test_reorder_empty (self):
    result = reorder_chunks ([])
    assert result == []

  def test_reorder_preserves_all_items (self):
    chunks = [({"text": f"chunk{i}", "score": 0.1 * i}, 0.1 * i) for i in range (1, 6)]
    result = reorder_chunks (chunks)
    assert len (result) == len (chunks)
    texts = {r [0] ["text"] for r in result}
    original = {c [0] ["text"] for c in chunks}
    assert texts == original


# ── F5: LLMLingua-style Compression ──


class TestTokenSurprise:
  """Tests for token-level surprise scoring."""

  def test_surprise_high_for_rare_words (self):
    text = "Quantum chromodynamics describes strong nuclear interactions."
    vocab = {
        "quantum": 0.95, "chromodynamics": 0.99, "describes": 0.1, "strong": 0.2, "nuclear": 0.15, "interactions": 0.12,
    }
    surprises = _compute_token_surprise (text, vocab)
    assert len (surprises) > 0
    assert max (surprises.values ()) > 0.5  # rare words score high surprise

  def test_surprise_low_for_common_words (self):
    text = "the and of to a in"
    vocab = {"the": 0.01, "and": 0.02, "of": 0.01, "to": 0.01, "a": 0.01, "in": 0.02}
    surprises = _compute_token_surprise (text, vocab)
    if surprises:
      assert max (surprises.values ()) < 0.3

  def test_surprise_empty_text (self):
    assert _compute_token_surprise ("", {}) == {}


class TestKeywordDensityScoring:
  """Tests for fallback keyword density sentence scoring."""

  def test_dense_sentence_scores_high (self):
    query = "Kubernetes deployment scaling"
    sentence = "Kubernetes deployment supports auto scaling of pods."
    score = _score_sentence_by_keyword_density (sentence, query)
    assert score > 0.0

  def test_irrelevant_sentence_scores_low (self):
    query = "Kubernetes deployment scaling"
    sentence = "The weather is nice today."
    score = _score_sentence_by_keyword_density (sentence, query)
    assert score == 0.0

  def test_empty_sentence_returns_zero (self):
    assert _score_sentence_by_keyword_density ("", "query") == 0.0


class TestCompressWithPerplexity:
  """Tests for LLMLingua-style SLM perplexity compression."""

  @pytest.fixture
  def optimizer (self):
    return TokenOptimizer ()

  def test_compress_keyword_fallback (self, optimizer):
    text = ("Kubernetes is an open-source platform. It automates deployment. "
            "It scales applications. The weather is nice today.")
    result = optimizer.compress_with_perplexity (text, budget = 15, strategy = "keyword")
    assert len (result) > 0
    assert len (result) < len (text)

  def test_compress_none_strategy (self, optimizer):
    text = "Some text content here."
    result = optimizer.compress_with_perplexity (text, budget = 100, strategy = "none")
    assert result == text

  def test_compress_empty_text (self, optimizer):
    assert optimizer.compress_with_perplexity ("", budget = 100, strategy = "keyword") == ""

  def test_compress_budget_larger_than_text (self, optimizer):
    text = "Short text."
    result = optimizer.compress_with_perplexity (text, budget = 1000, strategy = "keyword")
    assert result == text

  def test_compress_perplexity_strategy_falls_back (self, optimizer):
    text = "Some text to compress with the perplexity fallback mechanism."
    result = optimizer.compress_with_perplexity (text, budget = 10, strategy = "perplexity")
    assert len (result) > 0
    # when no SLM available, should fall back to keyword
    assert len (result) <= len (text)

  def test_standalone_function (self):
    text = "Token optimization reduces cost. It compresses context effectively."
    result = compress_with_perplexity (text, budget = 20)
    assert len (result) > 0


# ── F3: Self-Critique (ISUSE) ──


class TestSelfCritique:
  """Tests for the self_critique node in orchestrator."""

  def test_self_critique_node_returns_state (self):
    from proxy.app.core.orchestrator import self_critique

    state = {
        "query": "What is Docker?", "answer": "Docker is a container platform.",
        "context": "Docker is a containerization platform released in 2013.", "rewrite_count": 0, "confidence": 0.8,
    }
    result = self_critique (state)
    assert "self_critique_score" in result
    assert "needs_rewrite" in result
    assert "self_critique_count" in result
    assert isinstance (result ["self_critique_score"], int)
    assert 1 <= result ["self_critique_score"] <= 5
    assert isinstance (result ["needs_rewrite"], bool)
    assert isinstance (result ["self_critique_count"], int)
    assert result ["self_critique_count"] >= 1

  def test_self_critique_low_score_triggers_rewrite_flag (self):
    from proxy.app.core.orchestrator import self_critique

    state = {
        "query": "Complex question?", "answer": "I don't know.", "context": "Some context here.", "rewrite_count": 0,
        "confidence": 0.3,
    }
    result = self_critique (state)
    assert "needs_rewrite" in result

  def test_self_critique_max_rewrites_stops (self):
    from proxy.app.core.orchestrator import self_critique

    state = {
        "query": "Question?", "answer": "Weak answer.", "context": "Some context.", "rewrite_count": 5,
        "confidence": 0.2,
    }
    result = self_critique (state)
    assert result.get ("needs_rewrite") is False

  def test_self_critique_no_answer (self):
    from proxy.app.core.orchestrator import self_critique

    state = {
        "query": "Question?", "answer": "", "context": "Context.", "rewrite_count": 0, "confidence": 0.0,
    }
    result = self_critique (state)
    # Empty answer gets score 0 and no rewrite
    assert result ["self_critique_score"] == 0
    assert result ["needs_rewrite"] is False
    assert result ["self_critique_count"] == 0


class TestSelfCritiqueRoute:
  """Tests for the self_critique routing decision."""

  def test_route_to_done_when_no_rewrite_needed (self):
    from proxy.app.core.orchestrator import _self_critique_route

    state = {"needs_rewrite": False}
    assert _self_critique_route (state) == "done"

  def test_route_to_rewrite_when_needed (self):
    from proxy.app.core.orchestrator import _self_critique_route

    state = {"needs_rewrite": True}
    assert _self_critique_route (state) == "rewrite"


# ── F7: Query Complexity Scoring ──


class TestQueryComplexity:
  """Tests for query complexity scoring in slm_router."""

  def test_greeting_complexity_1 (self):
    from proxy.app.llm.slm import IntentType, get_complexity_score

    assert get_complexity_score (IntentType.GREETING) == 1

  def test_simple_fact_complexity_3 (self):
    from proxy.app.llm.slm import IntentType, get_complexity_score

    assert get_complexity_score (IntentType.SIMPLE_FACT) == 3

  def test_factual_complexity_5 (self):
    from proxy.app.llm.slm import IntentType, get_complexity_score

    assert get_complexity_score (IntentType.FACTUAL) == 5

  def test_procedural_complexity_7 (self):
    from proxy.app.llm.slm import IntentType, get_complexity_score

    assert get_complexity_score (IntentType.PROCEDURAL) == 7

  def test_comparison_complexity_8 (self):
    from proxy.app.llm.slm import IntentType, get_complexity_score

    assert get_complexity_score (IntentType.COMPARISON) == 8

  def test_complex_complexity_10 (self):
    from proxy.app.llm.slm import IntentType, get_complexity_score

    assert get_complexity_score (IntentType.COMPLEX) == 10

  def test_get_query_complexity (self):
    from proxy.app.llm.slm import get_query_complexity

    result = get_query_complexity ("Hello!")
    assert 1 <= result <= 10

  def test_intent_types_include_new_types (self):
    from proxy.app.llm.slm import IntentType

    intents = {e.value for e in IntentType}
    assert "simple_fact" in intents
    assert "complex" in intents
