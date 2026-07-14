"""Tests for proxy/app/model_evolution/metrics_gen.py — Generation metrics.

Covers: BLEU, ROUGE-L, hallucination rate, perplexity, compute_generation_metrics.
"""

import math

from proxy.app.model_evolution.metrics_gen import (
  GenerationMetrics, compute_bleu, compute_generation_metrics, compute_hallucination_rate, compute_perplexity,
  compute_rouge_l,
)


# ---------------------------------------------------------------------------
# GenerationMetrics dataclass
# ---------------------------------------------------------------------------


class TestGenerationMetrics:
  def test_default_values (self):
    m = GenerationMetrics ()
    assert m.bleu_1 == 0.0
    assert m.bleu_4 == 0.0
    assert m.rouge_l_f1 == 0.0
    assert m.bertscore_f1 is None
    assert m.hallucination_rate == 0.0
    assert m.perplexity is None
    assert m.extra == {}
  
  def test_custom_values (self):
    m = GenerationMetrics (bleu_1 = 0.8, bleu_4 = 0.5, rouge_l_f1 = 0.7, hallucination_rate = 0.1, )
    assert m.bleu_1 == 0.8
    assert m.hallucination_rate == 0.1


# ---------------------------------------------------------------------------
# compute_bleu
# ---------------------------------------------------------------------------


class TestComputeBleu:
  def test_identical_sentences_give_high_bleu (self):
    refs = ["The cat sat on the mat."]
    hyps = ["The cat sat on the mat."]
    result = compute_bleu (refs, hyps)
    
    assert result ["bleu_1"] > 0.9
    assert result ["bleu_4"] > 0.9
  
  def test_completely_different_gives_low_bleu (self):
    refs = ["The cat sat on the mat."]
    hyps = ["A dog ran through the park."]
    result = compute_bleu (refs, hyps)
    
    assert result ["bleu_1"] < 0.5
  
  def test_partial_overlap (self):
    refs = ["The quick brown fox jumps over the lazy dog in the park"]
    hyps = ["The quick brown fox leaps over a lazy dog in the garden"]
    result = compute_bleu (refs, hyps)
    
    assert result ["bleu_1"] > 0.4
  
  def test_empty_hypothesis (self):
    refs = ["Some reference text."]
    hyps = [""]
    result = compute_bleu (refs, hyps)
    
    assert result ["bleu_1"] == 0.0
  
  def test_empty_reference (self):
    refs = [""]
    hyps = ["Some hypothesis."]
    result = compute_bleu (refs, hyps)
    
    # BLEU should still compute (brevity penalty applies)
    assert "bleu_1" in result
  
  def test_multiple_pairs (self):
    refs = ["The cat sat.", "Dogs are great.", "Python is a language."]
    hyps = ["The cat sat.", "Dogs are amazing.", "Python is coding."]
    result = compute_bleu (refs, hyps)
    
    assert 0.0 <= result ["bleu_1"] <= 1.0
    assert 0.0 <= result ["bleu_4"] <= 1.0
  
  def test_bleu_4_leq_bleu_1 (self):
    """BLEU-4 should be <= BLEU-1 (stricter n-gram matching)."""
    refs = ["The quick brown fox jumps over the lazy dog"]
    hyps = ["The quick brown fox leaps over a lazy dog"]
    result = compute_bleu (refs, hyps)
    
    assert result ["bleu_4"] <= result ["bleu_1"] + 1e-6
  
  def test_returns_all_n_grams (self):
    refs = ["test sentence"]
    hyps = ["test sentence"]
    result = compute_bleu (refs, hyps, max_n = 4)
    
    assert "bleu_1" in result
    assert "bleu_2" in result
    assert "bleu_3" in result
    assert "bleu_4" in result
  
  def test_case_insensitive (self):
    refs = ["THE CAT SAT ON THE MAT"]
    hyps = ["the cat sat on the mat"]
    result = compute_bleu (refs, hyps)
    
    assert result ["bleu_1"] > 0.9


# ---------------------------------------------------------------------------
# compute_rouge_l
# ---------------------------------------------------------------------------


class TestComputeRougeL:
  def test_identical_sentences_perfect_rouge (self):
    refs = ["The cat sat on the mat."]
    hyps = ["The cat sat on the mat."]
    result = compute_rouge_l (refs, hyps)
    
    assert result ["rouge_l_f1"] > 0.99
    assert result ["rouge_l_precision"] > 0.99
    assert result ["rouge_l_recall"] > 0.99
  
  def test_no_overlap_gives_zero (self):
    refs = ["completely different words here"]
    hyps = ["zzzz zzzz zzzz zzzz"]
    result = compute_rouge_l (refs, hyps)
    
    assert result ["rouge_l_f1"] < 0.1
  
  def test_subset_reference (self):
    """Hypothesis is a subset of reference → high precision, lower recall."""
    refs = ["The quick brown fox jumps over the lazy dog"]
    hyps = ["The quick brown fox"]
    result = compute_rouge_l (refs, hyps)
    
    assert result ["rouge_l_precision"] > 0.9
    assert result ["rouge_l_recall"] < 0.6
  
  def test_superset_reference (self):
    """Hypothesis contains reference → lower precision, high recall."""
    refs = ["The cat sat"]
    hyps = ["The cat sat on the mat in the garden"]
    result = compute_rouge_l (refs, hyps)
    
    assert result ["rouge_l_recall"] > 0.9
    assert result ["rouge_l_precision"] < 0.5
  
  def test_multiple_pairs (self):
    refs = ["The cat sat.", "Dogs are great."]
    hyps = ["The cat sat.", "Dogs are wonderful."]
    result = compute_rouge_l (refs, hyps)
    
    assert 0.0 <= result ["rouge_l_f1"] <= 1.0
    assert 0.0 <= result ["rouge_l_precision"] <= 1.0
    assert 0.0 <= result ["rouge_l_recall"] <= 1.0
  
  def test_empty_hypothesis (self):
    refs = ["Some text."]
    hyps = [""]
    result = compute_rouge_l (refs, hyps)
    
    assert result ["rouge_l_precision"] == 0.0
    assert result ["rouge_l_recall"] == 0.0
  
  def test_f1_is_harmonic_mean (self):
    refs = ["The cat sat on the mat."]
    hyps = ["The cat sat."]
    result = compute_rouge_l (refs, hyps)
    
    p = result ["rouge_l_precision"]
    r = result ["rouge_l_recall"]
    expected_f1 = 2 * p * r / max (1e-10, p + r)
    assert abs (result ["rouge_l_f1"] - expected_f1) < 1e-6


# ---------------------------------------------------------------------------
# compute_hallucination_rate
# ---------------------------------------------------------------------------


class TestComputeHallucinationRate:
  def test_identical_texts_zero_hallucination (self):
    refs = ["The cat sat on the mat."]
    hyps = ["The cat sat on the mat."]
    rate = compute_hallucination_rate (refs, hyps)
    assert rate == 0.0
  
  def test_all_novel_words_high_rate (self):
    refs = ["The cat sat."]
    hyps = ["XYZ ABC DEF."]
    rate = compute_hallucination_rate (refs, hyps)
    assert rate == 1.0
  
  def test_partial_overlap (self):
    refs = ["The cat sat on the mat."]
    hyps = ["The cat danced on the stage."]
    rate = compute_hallucination_rate (refs, hyps)
    
    # "danced" and "stage" are novel → some hallucination
    assert 0.0 < rate < 1.0
  
  def test_empty_hypothesis (self):
    refs = ["Some text."]
    hyps = [""]
    rate = compute_hallucination_rate (refs, hyps)
    assert rate == 0.0  # no words to count
  
  def test_empty_reference (self):
    refs = [""]
    hyps = ["All words are novel."]
    rate = compute_hallucination_rate (refs, hyps)
    assert rate == 1.0
  
  def test_multiple_pairs (self):
    refs = ["The cat sat.", "Dogs run fast."]
    hyps = ["The cat slept.", "XYZ ABC."]
    rate = compute_hallucination_rate (refs, hyps)
    
    assert 0.0 <= rate <= 1.0
  
  def test_case_insensitive (self):
    refs = ["The Cat Sat"]
    hyps = ["the cat sat"]
    rate = compute_hallucination_rate (refs, hyps)
    assert rate == 0.0


# ---------------------------------------------------------------------------
# compute_perplexity
# ---------------------------------------------------------------------------


class TestComputePerplexity:
  def test_high_likelihood_low_perplexity (self):
    log_likelihoods = [-0.1, -0.1, -0.1, -0.1]
    ppl = compute_perplexity (log_likelihoods)
    assert ppl < 2.0
  
  def test_low_likelihood_high_perplexity (self):
    log_likelihoods = [-5.0, -5.0, -5.0]
    ppl = compute_perplexity (log_likelihoods)
    assert ppl > 50.0
  
  def test_empty_returns_inf (self):
    ppl = compute_perplexity ([])
    assert ppl == float ("inf")
  
  def test_zero_log_likelihood (self):
    log_likelihoods = [0.0, 0.0, 0.0]
    ppl = compute_perplexity (log_likelihoods)
    assert abs (ppl - 1.0) < 1e-6  # exp(0) = 1
  
  def test_single_value (self):
    log_likelihoods = [-2.0]
    ppl = compute_perplexity (log_likelihoods)
    assert abs (ppl - math.exp (2.0)) < 1e-6


# ---------------------------------------------------------------------------
# compute_generation_metrics
# ---------------------------------------------------------------------------


class TestComputeGenerationMetrics:
  def test_returns_generation_metrics_object (self):
    refs = ["The cat sat on the mat."]
    hyps = ["The cat sat on the mat."]
    result = compute_generation_metrics (refs, hyps)
    
    assert isinstance (result, GenerationMetrics)
    assert result.bleu_1 > 0.9
    assert result.rouge_l_f1 > 0.9
    assert result.bertscore_f1 is None  # not requested
  
  def test_bertscore_flag_disabled (self):
    refs = ["Test."]
    hyps = ["Test."]
    result = compute_generation_metrics (refs, hyps, compute_bertscore_flag = False)
    assert result.bertscore_f1 is None
  
  def test_populates_bleu_and_rouge (self):
    refs = ["The quick brown fox"]
    hyps = ["The quick brown dog"]
    result = compute_generation_metrics (refs, hyps)
    
    assert result.bleu_1 > 0.0
    assert result.bleu_4 >= 0.0
    assert result.rouge_l_f1 > 0.0
    assert result.rouge_l_precision > 0.0
    assert result.rouge_l_recall > 0.0
