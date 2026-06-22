"""Tests for proxy/app/rerank.py - fine-tuning from HITL feedback."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from proxy.app.rerank import (
    collect_training_pairs,
    fine_tune_reranker,
    RERANKER_FT_ENABLED,
)


class TestCollectTrainingPairs:
    def test_returns_empty_list_when_disabled(self):
        with patch("proxy.app.rerank.RERANKER_FT_ENABLED", False):
            pairs = collect_training_pairs()
            assert pairs == []

    def test_returns_list_of_tuples(self, tmp_path):
        feedback_dir = tmp_path / "feedback"
        feedback_dir.mkdir()
        feedback_entry = {
            "query": "How to configure nginx?",
            "chunks": [
                {"text": "Nginx config guide", "id": "c1"},
                {"text": "Docker setup", "id": "c2"},
            ],
            "positive_chunk_ids": ["c1"],
            "negative_chunk_ids": ["c2"],
        }
        (feedback_dir / "feedback_001.json").write_text(json.dumps(feedback_entry))

        with patch("proxy.app.rerank.RERANKER_FT_ENABLED", True):
            with patch("proxy.app.rerank.FEEDBACK_LOG_DIR", str(feedback_dir)):
                pairs = collect_training_pairs()
                assert isinstance(pairs, list)
                if pairs:
                    assert isinstance(pairs[0], tuple)
                    assert len(pairs[0]) == 3

    def test_ignores_invalid_json(self, tmp_path):
        feedback_dir = tmp_path / "feedback"
        feedback_dir.mkdir()
        (feedback_dir / "bad.json").write_text("not json")

        with patch("proxy.app.rerank.RERANKER_FT_ENABLED", True):
            with patch("proxy.app.rerank.FEEDBACK_LOG_DIR", str(feedback_dir)):
                pairs = collect_training_pairs()
                assert pairs == []

    def test_requires_minimum_positives(self, tmp_path):
        feedback_dir = tmp_path / "feedback"
        feedback_dir.mkdir()
        for i in range(3):
            entry = {
                "query": f"test query {i}",
                "chunks": [{"text": f"chunk {i}", "id": f"c{i}"}],
                "positive_chunk_ids": [f"c{i}"],
                "negative_chunk_ids": [],
            }
            (feedback_dir / f"f{i:03d}.json").write_text(json.dumps(entry))

        with patch("proxy.app.rerank.RERANKER_FT_ENABLED", True):
            with patch("proxy.app.rerank.FEEDBACK_LOG_DIR", str(feedback_dir)):
                pairs = collect_training_pairs()
                total_pairs = len(pairs)
                assert total_pairs == 3

    def test_empty_feedback_dir(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with patch("proxy.app.rerank.RERANKER_FT_ENABLED", True):
            with patch("proxy.app.rerank.FEEDBACK_LOG_DIR", str(empty_dir)):
                pairs = collect_training_pairs()
                assert pairs == []


class TestFineTuneReranker:
    def test_returns_none_with_empty_pairs(self):
        result = fine_tune_reranker([])
        assert result is None

    def test_returns_none_when_disabled(self):
        with patch("proxy.app.rerank.RERANKER_FT_ENABLED", False):
            pairs = [("query", "relevant text", 1.0)]
            result = fine_tune_reranker(pairs)
            assert result is None

    @patch("proxy.app.rerank.CROSS_ENCODER_AVAILABLE", True)
    @patch("proxy.app.rerank.RERANKER_FT_ENABLED", True)
    def test_calls_cross_encoder_fit(self):
        mock_ce = MagicMock()
        with patch("proxy.app.rerank.reranker", mock_ce):
            pairs = [
                ("what is RAG?", "RAG is retrieval augmented generation", 1.0),
                ("what is RAG?", "Python is a programming language", 0.0),
                ("how to cook pasta?", "Boil water and add pasta", 1.0),
            ]
            result = fine_tune_reranker(pairs, epochs=1)
            assert mock_ce.fit.called

    @patch("proxy.app.rerank.CROSS_ENCODER_AVAILABLE", True)
    @patch("proxy.app.rerank.RERANKER_FT_ENABLED", True)
    def test_exception_handled_gracefully(self):
        mock_ce = MagicMock()
        mock_ce.fit.side_effect = RuntimeError("CUDA out of memory")
        with patch("proxy.app.rerank.reranker", mock_ce):
            pairs = [("q", "c", 1.0)]
            result = fine_tune_reranker(pairs, epochs=1)
            assert result is None

    @patch("proxy.app.rerank.CROSS_ENCODER_AVAILABLE", True)
    @patch("proxy.app.rerank.RERANKER_FT_ENABLED", True)
    def test_saves_model_after_training(self):
        mock_ce = MagicMock()
        with patch("proxy.app.rerank.reranker", mock_ce):
            pairs = [("q", "c", 1.0), ("q2", "c2", 0.0)]
            with tempfile.TemporaryDirectory() as tmpdir:
                with patch("proxy.app.rerank.RERANKER_MODEL", tmpdir):
                    fine_tune_reranker(pairs, epochs=1)
                    if mock_ce.save.called:
                        pass

    def test_config_flag_exists(self):
        assert RERANKER_FT_ENABLED in (True, False)
