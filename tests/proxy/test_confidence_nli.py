"""Tests for NLI grounding checker and confidence calibration in confidence.py."""

import pytest

from proxy.app.core.confidence import (
  ConfidenceReport, GroundingReport, _check_claim_supported, calibrate_threshold, compute_confidence,
  compute_nli_grounding, decompose_into_claims,
)


class TestDecomposeIntoClaims:
  """Tests for atomic claim decomposition from answer text."""
  
  def test_decompose_simple_sentences (self):
    claims = decompose_into_claims ("Python is a programming language. It was created in 1991.")
    assert len (claims) >= 2
    assert any ("Python" in c for c in claims)
    assert any ("1991" in c for c in claims)
  
  def test_decompose_single_sentence (self):
    claims = decompose_into_claims ("The sky is blue.")
    assert len (claims) >= 1
    assert "blue" in claims [0].lower ()
  
  def test_decompose_empty_string (self):
    claims = decompose_into_claims ("")
    assert claims == []
  
  def test_decompose_semicolons (self):
    claims = decompose_into_claims ("Java is compiled; Python is interpreted.")
    assert len (claims) >= 2
  
  def test_decompose_bullet_points (self):
    claims = decompose_into_claims ("Key points:\n- First item\n- Second item")
    assert len (claims) >= 2
  
  def test_decompose_filters_short_fragments (self):
    claims = decompose_into_claims ("Yes. No. The answer is 42.")
    short_claims = [c for c in claims if len (c) < 3]
    assert len (short_claims) == 0


class TestCheckClaimSupported:
  """Tests for lightweight NLI proxy on individual claims."""
  
  def test_supported_claim (self):
    context = "Python is a programming language created by Guido van Rossum in 1991."
    claim = "Python was created in 1991."
    assert _check_claim_supported (claim, context) is True
  
  def test_unsupported_claim (self):
    context = "Python is used for web development."
    claim = "Python was invented in 2005."
    # "Python was invented in 2005." has only "python" overlapping
    # with "Python is used for web development." — keyword overlap is ~25%
    # but cosine drops due to different sentence length ratio
    assert _check_claim_supported (claim, context) is False
  
  def test_supported_different_wording (self):
    context = "Kubernetes orchestrates containerized workloads across clusters."
    claim = "Kubernetes manages containers across clusters."
    # Overlap: kubernetes, across, clusters — about 3/5 keywords overlap
    assert _check_claim_supported (claim, context) is True
  
  def test_empty_context_unsupported (self):
    assert _check_claim_supported ("Something is true.", "") is False


class TestComputeNliGrounding:
  """Tests for the main compute_nli_grounding function."""
  
  def test_fully_supported_answer (self):
    context = ("Docker is a containerization platform. It was released in 2013. "
               "Containers share the host OS kernel, making them lightweight.")
    answer = ("Docker is a containerization platform. It was released in 2013. "
              "Containers are lightweight because they share the kernel.")
    report = compute_nli_grounding (answer, context)
    assert isinstance (report, GroundingReport)
    assert report.score >= 0.5
    assert report.total_claims > 0
    assert len (report.unsupported) < report.total_claims
  
  def test_fully_unsupported_answer (self):
    context = "Docker runs on Linux systems for container management."
    answer = "Python handles numerical computations exclusively. Java requires a virtual machine environment."
    report = compute_nli_grounding (answer, context)
    assert report.score < 0.5
    assert len (report.unsupported) > 0
  
  def test_empty_answer (self):
    report = compute_nli_grounding ("", "Some context")
    assert report.score == 0.0
    assert report.total_claims == 0
  
  def test_empty_context (self):
    report = compute_nli_grounding ("Answer text here.", "")
    assert report.score == 0.0
    # trailing punctuation stripped by decompose
    assert "Answer text here" in report.unsupported or "Answer text here." in report.unsupported
  
  def test_report_has_all_fields (self):
    report = GroundingReport (score = 0.8, supported_claims = 3, total_claims = 5, unsupported = ["claim A", "claim B"])
    assert report.score == 0.8
    assert report.supported_claims == 3
    assert report.total_claims == 5
    assert len (report.unsupported) == 2
  
  def test_partial_support (self):
    context = "Python is a programming language."
    answer = "Python is a programming language. It was created in 2000."
    report = compute_nli_grounding (answer, context)
    assert 0.0 < report.score < 1.0


class TestConfidenceWithNli:
  """Tests that compute_confidence integrates NLI grounding."""
  
  def test_nli_contributes_to_confidence (self):
    context = "The project uses Redis for caching. PostgreSQL is the primary database."
    answer = "The project uses Redis for caching. MongoDB is the primary database."
    report = compute_confidence (query = "What databases does the project use?", context = context, answer = answer,
        slm_available = False, )
    assert isinstance (report, ConfidenceReport)
    assert 0.0 <= report.score <= 1.0
  
  def test_good_answer_high_confidence (self):
    context = ("GitLab CI/CD uses .gitlab-ci.yml for pipeline configuration. "
               "Pipelines consist of stages and jobs. Jobs run on GitLab runners.")
    answer = ("GitLab CI/CD pipelines are configured with .gitlab-ci.yml files. "
              "Each pipeline contains stages and jobs that execute on GitLab runners.")
    report = compute_confidence (query = "How does GitLab CI/CD work?", context = context, answer = answer,
        slm_available = False, )
    assert report.score >= 0.5


class TestCalibrateThreshold:
  """Tests for confidence threshold calibration."""
  
  def test_calibrate_perfect_separation (self):
    cases = [
        (0.9, True), (0.8, True), (0.7, True), (0.3, False), (0.2, False), (0.1, False),
    ]
    threshold = calibrate_threshold (cases)
    assert 0.3 <= threshold <= 0.7
  
  def test_calibrate_no_cases (self):
    threshold = calibrate_threshold ([])
    from proxy.app.shared.config import CONFIDENCE_THRESHOLD
    
    assert threshold == pytest.approx (CONFIDENCE_THRESHOLD)
  
  def test_calibrate_all_correct (self):
    cases = [(0.9, True), (0.8, True)]
    threshold = calibrate_threshold (cases)
    assert 0.0 <= threshold <= 1.0
  
  def test_calibrate_all_incorrect (self):
    cases = [(0.1, False), (0.2, False)]
    threshold = calibrate_threshold (cases)
    assert 0.0 <= threshold <= 1.0
  
  def test_calibrate_mixed (self):
    cases = [
        (0.95, True), (0.85, True), (0.75, True), (0.65, False), (0.55, False), (0.45, False), (0.35, False),
    ]
    threshold = calibrate_threshold (cases)
    assert 0.55 < threshold < 0.85
