"""Tests for proxy/app/retrieval_evaluator.py — RetrievalEvaluator class."""

import pytest

from proxy.app.core.retrieval_evaluator import RetrievalEvaluator


class TestRetrievalEvaluator:
  """Tests for the RetrievalEvaluator class."""
  
  @pytest.fixture
  def evaluator (self):
    return RetrievalEvaluator ()
  
  def test_evaluate_quality_empty (self, evaluator):
    score = evaluator.evaluate_quality ("query", [])
    assert score == 0.0
  
  def test_evaluate_quality_returns_0_to_1 (self, evaluator):
    chunks = [
        {"text": "relevant content about the query", "score": 0.85}, {"text": "somewhat related", "score": 0.65},
        {"text": "not related at all", "score": 0.15},
    ]
    score = evaluator.evaluate_quality ("query", chunks)
    assert 0.0 <= score <= 1.0
  
  def test_high_similarity_high_confidence (self, evaluator):
    chunks = [
        {"text": "highly relevant text", "score": 0.92}, {"text": "also very relevant", "score": 0.88},
        {"text": "relevant too", "score": 0.85}, {"text": "another relevant", "score": 0.82},
    ]
    score = evaluator.evaluate_quality ("test query", chunks)
    assert score > 0.6
  
  def test_low_scores_low_confidence (self, evaluator):
    chunks = [
        {"text": "barely relevant", "score": 0.2}, {"text": "not very useful", "score": 0.25},
        {"text": "low quality", "score": 0.15},
    ]
    score = evaluator.evaluate_quality ("test query", chunks)
    assert score < 0.4
  
  def test_mixed_scores_medium_confidence (self, evaluator):
    chunks = [
        {"text": "good match", "score": 0.9}, {"text": "bad match", "score": 0.1}, {"text": "ok match", "score": 0.5},
    ]
    score = evaluator.evaluate_quality ("test query", chunks)
    assert 0.3 <= score <= 0.7
  
  def test_no_scores_uses_text_overlap (self, evaluator):
    chunks = [
        {"text": "machine learning algorithms for classification"}, {"text": "deep neural networks and training"},
        {"text": "unrelated content about gardening"},
    ]
    score = evaluator.evaluate_quality ("machine learning algorithms", chunks)
    assert 0.0 <= score <= 1.0
  
  def test_no_scores_no_text (self, evaluator):
    chunks = [
        {"text": ""}, {"text": ""},
    ]
    score = evaluator.evaluate_quality ("query", chunks)
    assert 0.0 <= score <= 1.0
  
  def test_action_use_for_high_confidence (self, evaluator):
    action = evaluator.get_action (0.85)
    assert action == "USE"
  
  def test_action_rewrite_for_medium_confidence (self, evaluator):
    action = evaluator.get_action (0.55)
    assert action == "REWRITE"
  
  def test_action_expand_for_low_confidence (self, evaluator):
    action = evaluator.get_action (0.35)
    assert action == "EXPAND"
  
  def test_action_fallback_for_very_low_confidence (self, evaluator):
    action = evaluator.get_action (0.05)
    assert action == "FALLBACK"
  
  def test_action_boundary_thresholds (self, evaluator):
    assert evaluator.get_action (0.7) == "USE"
    assert evaluator.get_action (0.69) == "REWRITE"
    assert evaluator.get_action (0.4) == "REWRITE"
    assert evaluator.get_action (0.39) == "EXPAND"
    assert evaluator.get_action (0.2) == "EXPAND"
    assert evaluator.get_action (0.19) == "FALLBACK"
  
  def test_decompose_chunks_empty (self, evaluator):
    result = evaluator.decompose_chunks ([])
    assert result == []
  
  def test_decompose_chunks_removes_low_score (self, evaluator):
    chunks = [
        {"text": "good content", "score": 0.9}, {"text": "bad content", "score": 0.05},
        {"text": "ok content", "score": 0.5},
    ]
    result = evaluator.decompose_chunks (chunks)
    texts = {c ["text"] for c in result}
    assert "good content" in texts
    assert "ok content" in texts
    assert "bad content" not in texts
  
  def test_decompose_chunks_removes_duplicates (self, evaluator):
    chunks = [
        {"text": "same text appears twice", "score": 0.8}, {"text": "same text appears twice", "score": 0.7},
        {"text": "unique text", "score": 0.6},
    ]
    result = evaluator.decompose_chunks (chunks)
    assert len (result) == 2
  
  def test_decompose_chunks_preserves_keys (self, evaluator):
    chunks = [
        {"text": "content", "score": 0.8, "source_id": "doc1", "version": "1.0"},
    ]
    result = evaluator.decompose_chunks (chunks)
    assert result [0] ["source_id"] == "doc1"
    assert result [0] ["version"] == "1.0"
  
  def test_evaluate_and_act_use (self, evaluator):
    chunks = [
        {"text": "great result", "score": 0.9}, {"text": "also great", "score": 0.88},
    ]
    confidence, action, processed = evaluator.evaluate_and_act ("q", chunks)
    assert action == "USE"
    assert len (processed) > 0
  
  def test_evaluate_and_act_fallback (self, evaluator):
    chunks = [
        {"text": "very poor result", "score": 0.01}, {"text": "also terrible", "score": 0.02},
    ]
    confidence, action, processed = evaluator.evaluate_and_act ("q", chunks)
    assert action == "FALLBACK"
    assert processed == []
  
  def test_evaluate_and_act_expand_keeps_chunks (self, evaluator):
    chunks = [
        {"text": "meh", "score": 0.3}, {"text": "also meh", "score": 0.28},
    ]
    confidence, action, processed = evaluator.evaluate_and_act ("q", chunks)
    assert action == "EXPAND"
    assert len (processed) == len (chunks)
  
  def test_get_action_invalid_input (self, evaluator):
    assert evaluator.get_action (0.0) == "FALLBACK"
    assert evaluator.get_action (1.0) == "USE"
  
  def test_text_overlap_fallback (self, evaluator):
    chunks = [
        {"text": "python is great for data science"}, {"text": "javascript for frontend development"},
    ]
    scores = evaluator._compute_text_overlap_scores ("python data science", chunks)
    assert len (scores) == 2
    assert scores [0] > scores [1]
  
  def test_score_from_score_field (self, evaluator):
    chunks = [
        {"text": "a", "score": 0.8},
    ]
    score = evaluator.evaluate_quality ("test", chunks)
    assert score > 0.0
  
  def test_score_from_underscore_score_field (self, evaluator):
    chunks = [
        {"text": "b", "_score": 0.6},
    ]
    score = evaluator.evaluate_quality ("test", chunks)
    assert score > 0.0
