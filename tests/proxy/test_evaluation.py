"""Tests for proxy/app/evaluation.py — retrieval evaluation metrics."""

import pytest

from proxy.app.core.evaluation import (
  compute_all_metrics, compute_mrr, compute_ndcg_at_k, compute_precision_at_k, compute_recall_at_k,
)


class TestComputeMRR:
  """Tests for Mean Reciprocal Rank."""
  
  def test_perfect_retrieval (self):
    retrieved_lists = [["a", "b", "c"]]
    relevant_sets = [{"a", "b"}]
    assert compute_mrr (retrieved_lists, relevant_sets) == 1.0
  
  def test_second_rank (self):
    retrieved_lists = [["x", "a", "b"]]
    relevant_sets = [{"a", "b"}]
    assert compute_mrr (retrieved_lists, relevant_sets) == 0.5
  
  def test_no_relevant_found (self):
    retrieved_lists = [["x", "y", "z"]]
    relevant_sets = [{"a", "b"}]
    assert compute_mrr (retrieved_lists, relevant_sets) == 0.0
  
  def test_empty_input (self):
    assert compute_mrr ([], []) == 0.0
  
  def test_multiple_queries (self):
    retrieved_lists = [["a", "b"], ["x", "a"]]
    relevant_sets = [{"a"}, {"a"}]
    mrr = compute_mrr (retrieved_lists, relevant_sets)
    assert mrr == (1.0 + 0.5) / 2.0
  
  def test_empty_relevant_set (self):
    retrieved_lists = [["a", "b"]]
    relevant_sets = [set ()]
    # MRR skips queries with empty relevant sets
    assert compute_mrr (retrieved_lists, relevant_sets) == 0.0
  
  def test_mismatched_lengths (self):
    retrieved_lists = [["a"], ["b"]]
    relevant_sets = [{"a"}]
    mrr = compute_mrr (retrieved_lists, relevant_sets)
    assert 0.0 <= mrr <= 1.0


class TestComputeRecallAtK:
  """Tests for Recall@k."""
  
  def test_perfect_recall (self):
    assert compute_recall_at_k (["a", "b", "c"], {"a", "b"}, k = 5) == 1.0
  
  def test_partial_recall (self):
    assert compute_recall_at_k (["a", "x", "y"], {"a", "b"}, k = 5) == 0.5
  
  def test_no_relevant_in_list (self):
    assert compute_recall_at_k (["x", "y"], {"a", "b"}, k = 5) == 0.0
  
  def test_empty_retrieved (self):
    assert compute_recall_at_k ([], {"a", "b"}, k = 5) == 0.0
  
  def test_empty_relevant_returns_one (self):
    assert compute_recall_at_k (["a", "b"], set (), k = 5) == 1.0
  
  def test_k_limits_results (self):
    recall_full = compute_recall_at_k (["x", "a", "b"], {"a", "b"}, k = 10)
    recall_limited = compute_recall_at_k (["x", "a", "b"], {"a", "b"}, k = 1)
    assert recall_limited <= recall_full


class TestComputeNDCGAtK:
  """Tests for nDCG@k."""
  
  def test_perfect_ordering (self):
    assert compute_ndcg_at_k (["a", "b", "c"], {"a", "b", "c"}, k = 3) == pytest.approx (1.0)
  
  def test_partial_ordering (self):
    score = compute_ndcg_at_k (["x", "a", "b"], {"a", "b"}, k = 3)
    assert 0.0 <= score <= 1.0
  
  def test_empty_relevant_returns_one (self):
    assert compute_ndcg_at_k (["a", "b"], set (), k = 5) == 1.0
  
  def test_no_relevant_found (self):
    assert compute_ndcg_at_k (["x", "y"], {"a", "b"}, k = 5) == 0.0
  
  def test_k_limits_scope (self):
    ndcg_k3 = compute_ndcg_at_k (["a", "b", "c", "d"], {"a", "b"}, k = 3)
    assert 0.0 <= ndcg_k3 <= 1.0


class TestComputePrecisionAtK:
  """Tests for Precision@k."""
  
  def test_perfect_precision (self):
    assert compute_precision_at_k (["a", "b"], {"a", "b"}, k = 2) == 1.0
  
  def test_half_precision (self):
    assert compute_precision_at_k (["a", "x", "y", "z"], {"a", "b"}, k = 4) == 0.25
  
  def test_empty_retrieved (self):
    assert compute_precision_at_k ([], {"a"}, k = 5) == 0.0
  
  def test_empty_relevant (self):
    assert compute_precision_at_k (["a", "b"], set (), k = 2) == 0.0
  
  def test_k_limits_precision (self):
    assert compute_precision_at_k (["a", "b", "c"], {"a"}, k = 1) == 1.0
    assert compute_precision_at_k (["x", "a", "b"], {"a"}, k = 1) == 0.0


class TestComputeAllMetrics:
  """Tests for compute_all_metrics convenience function."""
  
  def test_returns_all_keys (self):
    retrieved = [["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"] * 2]
    relevant = [{"a", "b"}]
    metrics = compute_all_metrics (retrieved, relevant)
    assert "mrr" in metrics
    assert "recall@5" in metrics
    assert "recall@10" in metrics
    assert "recall@20" in metrics
    assert "ndcg@5" in metrics
    assert "ndcg@10" in metrics
    assert "precision@5" in metrics
    assert "num_queries" in metrics
  
  def test_all_values_in_range (self):
    retrieved = [["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"] * 2]
    relevant = [{"a", "b"}]
    metrics = compute_all_metrics (retrieved, relevant)
    for key, value in metrics.items ():
      if key == "num_queries":
        continue
      assert 0.0 <= value <= 1.0, f"{key} = {value}"


class TestCrossLingualBenchmarks:
  """F6: Cross-lingual retrieval benchmark evaluation."""
  
  def test_evaluate_cross_lingual_returns_dict (self):
    from proxy.app.core.evaluation import evaluate_cross_lingual_retrieval
    
    result = evaluate_cross_lingual_retrieval (("en", "de"))
    assert isinstance (result, dict)
    assert "source_lang" in result
    assert "target_lang" in result
    assert "monolingual" in result
    assert "cross_lingual" in result
    assert "comparison" in result
    assert "num_queries" in result
    assert result ["source_lang"] == "en"
    assert result ["target_lang"] == "de"
    assert isinstance (result ["monolingual"], dict)
    assert isinstance (result ["cross_lingual"], dict)
    assert isinstance (result ["comparison"], dict)
  
  def test_evaluate_cross_lingual_has_required_keys (self):
    from proxy.app.core.evaluation import evaluate_cross_lingual_retrieval
    
    result = evaluate_cross_lingual_retrieval (("en", "fr"))
    assert "source_lang" in result
    assert "target_lang" in result
    assert "monolingual" in result
    assert "cross_lingual" in result
  
  def test_evaluate_cross_lingual_monolingual_metrics (self):
    from proxy.app.core.evaluation import evaluate_cross_lingual_retrieval
    
    result = evaluate_cross_lingual_retrieval (("en", "zh"))
    mono = result ["monolingual"]
    assert "mrr" in mono
    assert "recall@5" in mono
    assert "recall@10" in mono
    assert all (0.0 <= v <= 1.0 for k, v in mono.items () if not k.startswith ("_"))
  
  def test_evaluate_cross_lingual_cross_metrics (self):
    from proxy.app.core.evaluation import evaluate_cross_lingual_retrieval
    
    result = evaluate_cross_lingual_retrieval (("en", "de"))
    cross = result ["cross_lingual"]
    assert "mrr" in cross
    assert "recall@5" in cross
    assert "recall@10" in cross
    assert all (0.0 <= v <= 1.0 for k, v in cross.items () if not k.startswith ("_"))
  
  def test_evaluate_cross_lingual_with_custom_queries (self):
    from proxy.app.core.evaluation import evaluate_cross_lingual_retrieval
    
    queries = {"en": ["What is RAG?"], "de": ["Was ist RAG?"]}
    result = evaluate_cross_lingual_retrieval (("en", "de"), queries = queries)
    assert result ["num_queries"] == 1
  
  def test_evaluate_cross_lingual_comparison (self):
    from proxy.app.core.evaluation import evaluate_cross_lingual_retrieval
    
    result = evaluate_cross_lingual_retrieval (("en", "fr"))
    comparison = result.get ("comparison", {})
    assert isinstance (comparison, dict)
    assert "mrr_delta" in comparison
  
  def test_evaluate_cross_lingual_empty_queries (self):
    from proxy.app.core.evaluation import evaluate_cross_lingual_retrieval
    
    queries = {"en": [], "de": []}
    result = evaluate_cross_lingual_retrieval (("en", "de"), queries = queries)
    assert result ["num_queries"] == 0
  
  def test_evaluate_cross_lingual_all_pair_benchmark (self):
    from proxy.app.core.evaluation import run_cross_lingual_benchmark
    
    results = run_cross_lingual_benchmark ()
    assert isinstance (results, list)
    assert len (results) == 5  # en->de, en->fr, en->zh, ru->en, ru->de
    for r in results:
      assert "lang_pair" in r
      assert "monolingual" in r
      assert "cross_lingual" in r
      assert isinstance (r ["lang_pair"], str)
      assert "->" in r ["lang_pair"]
