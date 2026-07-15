"""Tests for RAGAS evaluation metrics."""

from proxy.app.core.ragas_eval import (
  compute_answer_relevance,
  compute_context_relevance,
  compute_faithfulness,
  evaluate_rag_response,
)


class TestFaithfulness:
  def test_high_faithfulness (self):
    answer = "Python is a programming language"
    context = "Python is a high-level programming language used for web development"
    score = compute_faithfulness (answer, context)
    assert score >= 0.7

  def test_low_faithfulness (self):
    answer = "Java is a database system"
    context = "Python is a programming language"
    score = compute_faithfulness (answer, context)
    assert score < 0.5

  def test_empty_inputs (self):
    assert compute_faithfulness ("", "") == 0.0
    assert compute_faithfulness ("test", "") == 0.0


class TestAnswerRelevance:
  def test_relevant_answer (self):
    question = "What is Python?"
    answer = "Python is a programming language used for development"
    score = compute_answer_relevance (question, answer)
    assert score >= 0.5

  def test_irrelevant_answer (self):
    question = "What is Python?"
    answer = "The weather is nice today"
    score = compute_answer_relevance (question, answer)
    assert score < 0.5


class TestContextRelevance:
  def test_relevant_contexts (self):
    question = "What is Python?"
    contexts = ["Python is a programming language", "Python is used for web development"]
    score = compute_context_relevance (question, contexts)
    assert score >= 0.5

  def test_irrelevant_contexts (self):
    question = "What is Python?"
    contexts = ["The weather is nice", "I like coffee"]
    score = compute_context_relevance (question, contexts)
    assert score < 0.5


class TestEvaluateRagResponse:
  def test_full_evaluation (self):
    scores = evaluate_rag_response (question = "What is Python?", answer = "Python is a programming language",
        contexts = ["Python is a high-level programming language"], )
    assert "faithfulness" in scores
    assert "answer_relevance" in scores
    assert "context_relevance" in scores
    assert "overall" in scores
    assert all (0 <= v <= 1 for v in scores.values ())
