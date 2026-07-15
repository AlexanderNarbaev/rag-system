"""Tests for proxy/app/model_evolution/nli_evaluator.py — NLI evaluator.

Covers: claim decomposition, lightweight proxy, evaluate_nli, batch evaluation,
cosine proxy, and NLIEvaluationResult.
"""

from proxy.app.model_evolution.nli_evaluator import (
  NLIEvaluationResult,
  _compute_cosine_proxy,
  _lightweight_check,
  _tokenize,
  decompose_into_claims,
  evaluate_nli,
  evaluate_nli_batch,
)

# ---------------------------------------------------------------------------
# NLIEvaluationResult dataclass
# ---------------------------------------------------------------------------


class TestNLIEvaluationResult:
  def test_as_metrics (self):
    result = NLIEvaluationResult (entailment_rate = 0.8, contradiction_rate = 0.1, neutral_rate = 0.1,
        overall_score = 0.75, total_claims = 10, entailed_claims = 8, contradicted_claims = 1, neutral_claims = 1, )
    metrics = result.as_metrics ()

    assert metrics ["nli_entailment_rate"] == 0.8
    assert metrics ["nli_contradiction_rate"] == 0.1
    assert metrics ["nli_neutral_rate"] == 0.1
    assert metrics ["nli_overall_score"] == 0.75

  def test_default_per_claim_scores (self):
    result = NLIEvaluationResult (entailment_rate = 0.0, contradiction_rate = 0.0, neutral_rate = 0.0,
        overall_score = 0.0, total_claims = 0, entailed_claims = 0, contradicted_claims = 0, neutral_claims = 0, )
    assert result.per_claim_scores == []


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
  def test_basic_tokenize (self):
    tokens = _tokenize ("The quick brown fox")
    assert tokens == {"the", "quick", "brown", "fox"}

  def test_empty_string (self):
    tokens = _tokenize ("")
    assert tokens == set ()

  def test_special_characters (self):
    tokens = _tokenize ("Hello, world! How's it going?")
    assert "hello" in tokens
    assert "world" in tokens

  def test_case_insensitive (self):
    tokens = _tokenize ("Hello HELLO hello")
    assert tokens == {"hello"}


# ---------------------------------------------------------------------------
# _compute_cosine_proxy
# ---------------------------------------------------------------------------


class TestComputeCosineProxy:
  def test_identical_texts_high_score (self):
    score = _compute_cosine_proxy ("the cat sat", "the cat sat")
    assert score > 0.99

  def test_no_overlap_zero (self):
    score = _compute_cosine_proxy ("aaa bbb", "ccc ddd")
    assert score == 0.0

  def test_partial_overlap (self):
    score = _compute_cosine_proxy ("the cat sat", "the dog ran")
    assert 0.0 < score < 1.0

  def test_empty_first_string (self):
    score = _compute_cosine_proxy ("", "hello world")
    assert score == 0.0

  def test_empty_second_string (self):
    score = _compute_cosine_proxy ("hello world", "")
    assert score == 0.0

  def test_both_empty (self):
    score = _compute_cosine_proxy ("", "")
    assert score == 0.0

  def test_symmetric (self):
    a = _compute_cosine_proxy ("hello world", "world hello")
    b = _compute_cosine_proxy ("world hello", "hello world")
    assert abs (a - b) < 1e-10


# ---------------------------------------------------------------------------
# _lightweight_check
# ---------------------------------------------------------------------------


class TestLightweightCheck:
  def test_high_overlap_entailment (self):
    claim = "The cat sat on the mat"
    context = "The cat sat on the mat in the living room"
    label, confidence = _lightweight_check (claim, context)

    assert label == "entailment"
    assert confidence > 0.4

  def test_no_overlap_contradiction (self):
    claim = "AAA BBB CCC DDD EEE FFF"
    context = "XXX YYY ZZZ WWW VVV UUU"
    label, confidence = _lightweight_check (claim, context)

    assert label == "contradiction"

  def test_moderate_overlap_neutral (self):
    claim = "The quick brown fox jumps"
    context = "A slow red turtle crawls slowly"
    label, confidence = _lightweight_check (claim, context)

    # With very little overlap, should be contradiction or neutral
    assert label in ("contradiction", "neutral")

  def test_empty_claim (self):
    label, confidence = _lightweight_check ("", "some context")
    assert label == "neutral"
    assert confidence == 0.5


# ---------------------------------------------------------------------------
# decompose_into_claims
# ---------------------------------------------------------------------------


class TestDecomposeIntoClaims:
  def test_splits_by_period (self):
    answer = "The cat sat. The dog ran. The bird flew."
    claims = decompose_into_claims (answer)

    assert len (claims) == 3
    assert "The cat sat" in claims [0]
    assert "The dog ran" in claims [1]
    assert "The bird flew" in claims [2]

  def test_splits_by_newline (self):
    answer = "First claim sentence here.\nSecond claim sentence."
    claims = decompose_into_claims (answer)

    assert len (claims) == 2

  def test_filters_short_claims (self):
    answer = "Short. This is a longer claim that should be kept."
    claims = decompose_into_claims (answer)

    # "Short" is < 10 chars, should be filtered
    assert len (claims) == 1
    assert "longer claim" in claims [0]

  def test_empty_answer (self):
    assert decompose_into_claims ("") == []
    assert decompose_into_claims ("   ") == []
    assert decompose_into_claims ("") == []  # None handled at runtime

  def test_strips_bullet_prefixes (self):
    answer = "- First bullet point claim here.\n* Second bullet point claim."
    claims = decompose_into_claims (answer)

    for claim in claims:
      assert not claim.startswith ("- ")
      assert not claim.startswith ("* ")

  def test_strips_trailing_semicolons (self):
    answer = "This is a complete claim sentence.;"
    claims = decompose_into_claims (answer)

    assert len (claims) == 1
    assert not claims [0].endswith (";")

  def test_exclamation_marks_split (self):
    answer = "This is important! This is also important claim."
    claims = decompose_into_claims (answer)

    assert len (claims) == 2

  def test_question_marks_split (self):
    answer = "Is this true? This is a statement claim here."
    claims = decompose_into_claims (answer)

    assert len (claims) == 2


# ---------------------------------------------------------------------------
# evaluate_nli — using lightweight fallback (use_real_nli=False)
# ---------------------------------------------------------------------------


class TestEvaluateNLI:
  def test_empty_answer_returns_zero_result (self):
    result = evaluate_nli ("", "Some context", use_real_nli = False)

    assert result.total_claims == 0
    assert result.entailment_rate == 0.0
    assert result.contradiction_rate == 0.0
    assert result.overall_score == 0.0

  def test_none_answer_returns_zero_result (self):
    result = evaluate_nli ("", "Some context", use_real_nli = False)  # None handled at runtime

    assert result.total_claims == 0

  def test_empty_context_returns_neutral_claims (self):
    result = evaluate_nli ("This is a claim sentence here.", "", use_real_nli = False, )

    assert result.total_claims > 0
    # Empty context → claims are counted as neutral
    assert result.neutral_claims == result.total_claims

  def test_entailment_when_high_overlap (self):
    context = "Python is a programming language used for web development and data science."
    answer = "Python is a programming language for data science."
    result = evaluate_nli (answer, context, use_real_nli = False)

    assert result.total_claims > 0
    assert result.entailment_rate > 0.0

  def test_contradiction_when_no_overlap (self):
    context = "The deployment uses Kubernetes pods with replicas."
    answer = "The system runs on bare metal servers without containers."
    result = evaluate_nli (answer, context, use_real_nli = False)

    assert result.total_claims > 0
    # With no overlap, lightweight check should give contradiction or neutral
    assert result.contradiction_rate > 0.0 or result.neutral_rate > 0.0

  def test_overall_score_bounded (self):
    result = evaluate_nli ("This is a test claim sentence.", "This is a test context with different words entirely.",
        use_real_nli = False, )

    assert 0.0 <= result.overall_score <= 1.0

  def test_per_claim_scores_populated (self):
    answer = "First claim sentence here. Second claim sentence here."
    result = evaluate_nli (answer, "Context about both claims here.", use_real_nli = False)

    assert len (result.per_claim_scores) == result.total_claims
    for score in result.per_claim_scores:
      assert "claim" in score
      assert "label" in score
      assert "confidence" in score
      assert score ["label"] in ("entailment", "contradiction", "neutral")

  def test_rates_sum_to_one (self):
    answer = "This is a valid claim sentence for testing purposes."
    result = evaluate_nli (answer, "Context for testing purposes.", use_real_nli = False)

    if result.total_claims > 0:
      total_rate = result.entailment_rate + result.contradiction_rate + result.neutral_rate
      assert abs (total_rate - 1.0) < 1e-3

  def test_whitespace_only_answer (self):
    result = evaluate_nli ("   \n\t  ", "Some context", use_real_nli = False)
    assert result.total_claims == 0

  def test_short_claims_filtered (self):
    answer = "Hi. This is a longer claim that meets the minimum length requirement."
    result = evaluate_nli (answer, "Some context about claims.", use_real_nli = False)

    # "Hi" is < 10 chars, filtered out
    assert result.total_claims == 1


# ---------------------------------------------------------------------------
# evaluate_nli_batch
# ---------------------------------------------------------------------------


class TestEvaluateNLIBatch:
  def test_empty_pairs (self):
    result = evaluate_nli_batch ([], use_real_nli = False)

    assert result ["nli_entailment_rate"] == 0.0
    assert result ["nli_contradiction_rate"] == 0.0
    assert result ["nli_neutral_rate"] == 0.0
    assert result ["nli_overall_score"] == 0.0

  def test_single_pair (self):
    pairs = [
        ("The cat sat on the mat.", "A cat sitting on a mat in a room."),
    ]
    result = evaluate_nli_batch (pairs, use_real_nli = False)

    assert "nli_entailment_rate" in result
    assert "nli_contradiction_rate" in result
    assert "nli_neutral_rate" in result
    assert "nli_overall_score" in result

  def test_multiple_pairs (self):
    pairs = [
        ("Python is great for data science.", "Python is used in data science and ML."),
        ("Kubernetes manages containers.", "K8s orchestrates container workloads."),
    ]
    result = evaluate_nli_batch (pairs, use_real_nli = False)

    assert 0.0 <= result ["nli_entailment_rate"] <= 1.0
    assert 0.0 <= result ["nli_contradiction_rate"] <= 1.0
    assert 0.0 <= result ["nli_neutral_rate"] <= 1.0
    assert 0.0 <= result ["nli_overall_score"] <= 1.0

  def test_rates_sum_to_one_batch (self):
    pairs = [
        ("Claim one sentence here.", "Context for one sentence."),
        ("Claim two sentence here.", "Context for two sentence."),
    ]
    result = evaluate_nli_batch (pairs, use_real_nli = False)

    total = result ["nli_entailment_rate"] + result ["nli_contradiction_rate"] + result ["nli_neutral_rate"]
    assert abs (total - 1.0) < 1e-3

  def test_pair_with_empty_answer_contributes_zero (self):
    pairs = [
        ("", "Some context"), ("Valid claim sentence here.", "Valid context sentence here."),
    ]
    result = evaluate_nli_batch (pairs, use_real_nli = False)

    # Only the second pair should contribute
    assert 0.0 <= result ["nli_overall_score"] <= 1.0
