"""Tests for proxy/app/grounding.py — context grounding score."""

from unittest.mock import patch

import pytest


class TestComputeGrounding:
  """Tests for compute_grounding function."""

  def test_empty_answer_returns_zero (self):
    from proxy.app.core.grounding import compute_grounding

    score = compute_grounding ("", "some context")
    assert score == 0.0

  def test_empty_context_returns_zero (self):
    from proxy.app.core.grounding import compute_grounding

    score = compute_grounding ("some answer", "")
    assert score == 0.0

  def test_both_empty_returns_zero (self):
    from proxy.app.core.grounding import compute_grounding

    score = compute_grounding ("", "")
    assert score == 0.0

  def test_no_embedder_returns_zero (self):
    from proxy.app.core import grounding

    grounding._embedder = None
    with patch.object (grounding, "_get_embedder", return_value = None):
      score = grounding.compute_grounding ("answer", "context")
      assert score == 0.0

  def test_similar_texts_high_score (self):
    from proxy.app.core.grounding import _get_embedder, compute_grounding

    embedder = _get_embedder ()
    if embedder is None:
      pytest.skip ("sentence-transformers not available")
    score = compute_grounding ("RAG combines retrieval with generation.",
        "RAG combines retrieval with generation for accurate responses.", )
    assert 0.5 <= score <= 1.0

  def test_different_texts_lower_score (self):
    from proxy.app.core.grounding import _get_embedder, compute_grounding

    embedder = _get_embedder ()
    if embedder is None:
      pytest.skip ("sentence-transformers not available")
    score_similar = compute_grounding ("RAG combines retrieval with generation.",
        "RAG combines retrieval with generation for accurate responses.", )
    score_diff = compute_grounding ("RAG combines retrieval with generation.",
        "The capital of France is Paris and it is a beautiful city.", )
    assert score_diff < score_similar

  def test_returns_float (self):
    from proxy.app.core.grounding import _get_embedder, compute_grounding

    embedder = _get_embedder ()
    if embedder is None:
      pytest.skip ("sentence-transformers not available")
    score = compute_grounding ("hello world", "hello world test")
    assert isinstance (score, float)

  def test_score_in_valid_range (self):
    from proxy.app.core.grounding import _get_embedder, compute_grounding

    embedder = _get_embedder ()
    if embedder is None:
      pytest.skip ("sentence-transformers not available")
    score = compute_grounding ("any text", "some context text")
    assert 0.0 <= score <= 1.0

  def test_embedding_error_handled_gracefully (self):
    from proxy.app.core import grounding

    grounding._embedder = None

    class FailingEmbedder:
      def encode (self, text, normalize_embeddings = True):
        raise RuntimeError ("GPU OOM")

    with patch.object (grounding, "_get_embedder", return_value = FailingEmbedder ()):
      score = grounding.compute_grounding ("answer", "context")
      assert score == 0.0


class TestGetEmbedder:
  """Tests for _get_embedder helper."""

  def test_returns_none_when_st_unavailable (self):
    from proxy.app.core import grounding

    grounding._embedder = None
    with patch ("proxy.app.llm.remote_services.create_embedder", side_effect = ImportError ("no st")):
      embedder = grounding._get_embedder ()
      assert embedder is None

  def test_caches_embedder (self):
    from proxy.app.core import grounding

    grounding._embedder = None
    mock_embedder = object ()
    with patch ("proxy.app.llm.remote_services.create_embedder", return_value = mock_embedder):
      e1 = grounding._get_embedder ()
      e2 = grounding._get_embedder ()
      assert e1 is e2
      assert e1 is mock_embedder
