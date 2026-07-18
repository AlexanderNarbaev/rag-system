# ruff: noqa: SIM117
"""Tests for rerank.py advanced features: TwoStageReranker, hybrid_rerank, colbert_score, etc."""

from unittest.mock import MagicMock, patch

import pytest

from proxy.app.core.rerank import (
    TwoStageReranker,
    _call_reranker_safe,
    colbert_score,
    collect_training_pairs,
    cosine_similarity_single,
    fine_tune_reranker,
    hybrid_rerank,
)


class TestCosineSimilaritySingle:
    """Tests for cosine_similarity_single."""

    def test_identical_vectors(self):
        assert cosine_similarity_single([1, 0], [1, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity_single([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity_single([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert cosine_similarity_single([0, 0], [1, 1]) == 0.0


class TestColbertScore:
    """Tests for colbert_score."""

    def test_empty_query_tokens(self):
        assert colbert_score([], [[1, 0]]) == 0.0

    def test_empty_doc_tokens(self):
        assert colbert_score([[1, 0]], []) == 0.0

    def test_identical_tokens(self):
        score = colbert_score([[1, 0, 0]], [[1, 0, 0]])
        assert score == pytest.approx(1.0)

    def test_multiple_tokens(self):
        qt = [[1, 0], [0, 1]]
        dt = [[1, 0], [0, 1], [1, 1]]
        score = colbert_score(qt, dt)
        assert score > 0


class TestHybridRerank:
    """Tests for hybrid_rerank."""

    def test_empty_documents(self):
        assert hybrid_rerank("query", []) == []

    def test_combines_scores(self):
        docs = [
            {"text": "doc about Python", "metadata": {}},
            {"text": "doc about Java", "metadata": {}},
        ]
        with patch("proxy.app.core.rerank.rerank_chunks") as mock_rerank:
            mock_rerank.return_value = [0, 1]
            result = hybrid_rerank("Python programming", docs)
            assert len(result) == 2
            assert all("score" in d for d in result)

    def test_with_colbert_tokens(self):
        docs = [
            {
                "text": "doc text",
                "metadata": {
                    "query_tokens": [[1, 0]],
                    "colbert_tokens": [[1, 0]],
                },
            },
        ]
        with patch("proxy.app.core.rerank.rerank_chunks") as mock_rerank:
            mock_rerank.return_value = [0]
            result = hybrid_rerank("test", docs)
            assert len(result) == 1
            assert "colbert_score" in result[0]


class TestCallRerankerSafe:
    """Tests for _call_reranker_safe."""

    def test_none_reranker(self):
        with patch("proxy.app.core.rerank.reranker", None):
            scores = _call_reranker_safe([("q", "d")])
            assert scores == [0.5]

    def test_with_mock_reranker(self):
        mock_reranker = MagicMock()
        mock_reranker.predict.return_value = [0.9, 0.8]
        import proxy.app.core.rerank as rerank_mod

        original = rerank_mod.reranker
        try:
            rerank_mod.reranker = mock_reranker
            scores = _call_reranker_safe([("q", "d1"), ("q", "d2")])
            assert scores == [0.9, 0.8]
        finally:
            rerank_mod.reranker = original


class TestCollectTrainingPairs:
    """Tests for collect_training_pairs."""

    def test_disabled(self):
        with patch("proxy.app.core.rerank.RERANKER_FT_ENABLED", False):
            assert collect_training_pairs() == []

    def test_no_feedback_dir(self):
        with patch("proxy.app.core.rerank.RERANKER_FT_ENABLED", True):
            with patch("proxy.app.core.rerank.FEEDBACK_LOG_DIR", "/nonexistent"):
                assert collect_training_pairs() == []

    def test_reads_feedback_files(self, tmp_path):
        feedback = {
            "query": "test query",
            "chunks": [{"id": "c1", "text": "chunk 1"}, {"id": "c2", "text": "chunk 2"}],
            "positive_chunk_ids": ["c1"],
            "negative_chunk_ids": ["c2"],
        }
        (tmp_path / "fb1.json").write_text(__import__("json").dumps(feedback), encoding="utf-8")
        with patch("proxy.app.core.rerank.RERANKER_FT_ENABLED", True):
            with patch("proxy.app.core.rerank.FEEDBACK_LOG_DIR", str(tmp_path)):
                pairs = collect_training_pairs()
                assert len(pairs) == 2
                assert any(s == 1.0 for _, _, s in pairs)
                assert any(s == 0.0 for _, _, s in pairs)

    def test_invalid_json_file(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
        with patch("proxy.app.core.rerank.RERANKER_FT_ENABLED", True):
            with patch("proxy.app.core.rerank.FEEDBACK_LOG_DIR", str(tmp_path)):
                pairs = collect_training_pairs()
                assert pairs == []


class TestFineTuneReranker:
    """Tests for fine_tune_reranker."""

    def test_disabled(self):
        with patch("proxy.app.core.rerank.RERANKER_FT_ENABLED", False):
            assert fine_tune_reranker([]) is None

    def test_empty_pairs(self):
        with patch("proxy.app.core.rerank.RERANKER_FT_ENABLED", True):
            assert fine_tune_reranker([]) is None

    def test_cpu_fallback(self):
        with patch("proxy.app.core.rerank.RERANKER_FT_ENABLED", True):
            with patch("proxy.app.core.rerank.TORCH_AVAILABLE", False):
                with patch("proxy.app.core.rerank._fine_tune_full") as mock_ft:
                    mock_ft.return_value = "/path/to/model"
                    result = fine_tune_reranker([("q", "d", 1.0)], epochs=1)
                    assert result == "/path/to/model"


class TestTwoStageReranker:
    """Tests for TwoStageReranker."""

    def test_init(self):
        r = TwoStageReranker(fast_model="test-model", fast_top_k=10, final_top_k=3)
        assert r.fast_model == "test-model"
        assert r.fast_top_k == 10
        assert r.final_top_k == 3

    def test_fast_score_no_encoder(self):
        r = TwoStageReranker(fast_model="")
        scores = r.fast_score("test", ["doc1", "doc2"])
        assert scores == [0.5, 0.5]

    def test_fast_score_with_encoder(self):
        r = TwoStageReranker(fast_model="test")
        mock_encoder = MagicMock()
        import numpy as np

        mock_encoder.encode.side_effect = [
            np.array([1.0, 0.0]),  # query
            np.array([[1.0, 0.0], [0.0, 1.0]]),  # docs
        ]
        r._fast_encoder = mock_encoder
        scores = r.fast_score("test", ["doc1", "doc2"])
        assert len(scores) == 2

    def test_fast_score_failure_returns_uniform(self):
        r = TwoStageReranker(fast_model="test")
        mock_encoder = MagicMock()
        mock_encoder.encode.side_effect = RuntimeError("OOM")
        r._fast_encoder = mock_encoder
        scores = r.fast_score("test", ["doc"])
        assert scores == [0.5]

    def test_rerank_empty(self):
        r = TwoStageReranker()
        assert r.rerank("query", []) == []

    def test_rerank_combines_stages(self):
        r = TwoStageReranker(fast_top_k=5, final_top_k=2)
        docs = [{"text": f"doc {i}"} for i in range(10)]
        with patch.object(r, "fast_score", return_value=[0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]):
            with patch.object(r, "cross_encoder_score", return_value=[1.0, 2.0, 3.0, 4.0, 5.0]):
                result = r.rerank("test", docs)
                assert len(result) <= 2

    def test_cross_encoder_score(self):
        r = TwoStageReranker()
        with patch("proxy.app.core.rerank.rerank_chunks") as mock:
            mock.return_value = [1, 0]
            scores = r.cross_encoder_score("q", ["d1", "d2"])
            assert len(scores) == 2
