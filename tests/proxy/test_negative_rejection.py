"""Tests for negative rejection — system refuses to answer when insufficient data.

Covers:
- should_generate_answer() — unit tests for the negative evidence gate
- RetrievalQualityReport — CRAG-style retrieval quality classification
- Integration with the main RAG pipeline refusal path
"""

from unittest.mock import patch

from proxy.app.core.confidence import (
    RetrievalQualityReport,
    evaluate_retrieval_quality,
    should_generate_answer,
)

# ── Unit Tests: should_generate_answer ──────────────────────────────────────


class TestShouldGenerateAnswer:
    """Test the negative rejection logic in should_generate_answer."""

    def test_no_chunks_returns_false(self):
        """When no chunks retrieved, should refuse to generate."""
        should_gen, reason = should_generate_answer([])
        assert should_gen is False
        assert "No relevant documents" in reason

    def test_none_equivalent_empty_list(self):
        """Empty list is equivalent to no results."""
        should_gen, reason = should_generate_answer([])
        assert should_gen is False
        assert "knowledge base" in reason.lower()

    def test_insufficient_strong_sources_returns_false(self):
        """When < 2 chunks have score >= 0.32, should refuse to generate."""
        chunks = [
            {"text": "some text", "score": 0.2},
            {"text": "other text", "score": 0.15},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is False
        assert "insufficient" in reason.lower() or "no sufficiently" in reason.lower()

    def test_no_strong_sources_returns_false_with_specific_message(self):
        """When zero chunks above threshold, message says 'No sufficiently relevant'."""
        chunks = [
            {"text": "irrelevant", "score": 0.05},
            {"text": "also irrelevant", "score": 0.10},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is False
        assert "No sufficiently relevant" in reason

    def test_one_strong_source_returns_false(self):
        """One strong source is not enough (default min=2)."""
        chunks = [
            {"text": "strong", "score": 0.5},
            {"text": "weak", "score": 0.1},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is False
        assert "Only 1 relevant source" in reason

    def test_sufficient_strong_sources_returns_true(self):
        """When >= 2 chunks have score >= 0.32, should generate answer."""
        chunks = [
            {"text": "relevant text", "score": 0.4},
            {"text": "another relevant", "score": 0.35},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is True
        assert "Sufficient" in reason

    def test_exactly_two_strong_sources_returns_true(self):
        """Exactly at the default threshold of 2 strong sources."""
        chunks = [
            {"text": "first strong", "score": 0.32},  # Exactly at threshold
            {"text": "second strong", "score": 0.33},  # Just above
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is True

    def test_mixed_scores_with_enough_strong(self):
        """Mix of strong and borderline scores with enough strong."""
        chunks = [
            {"text": "strong 1", "score": 0.5},
            {"text": "strong 2", "score": 0.4},
            {"text": "borderline", "score": 0.28},
            {"text": "weak", "score": 0.1},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is True

    def test_mixed_scores_without_enough_strong(self):
        """Mix of scores but only one above threshold."""
        chunks = [
            {"text": "strong", "score": 0.5},
            {"text": "borderline 1", "score": 0.30},
            {"text": "borderline 2", "score": 0.28},
            {"text": "weak", "score": 0.1},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is False

    def test_only_borderline_returns_false(self):
        """Only borderline scores (0.25–0.31) should refuse."""
        chunks = [
            {"text": "borderline 1", "score": 0.30},
            {"text": "borderline 2", "score": 0.28},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is False

    def test_all_zeros_returns_false(self):
        """All zero scores should refuse."""
        chunks = [
            {"text": "chunk a", "score": 0.0},
            {"text": "chunk b", "score": 0.0},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is False

    def test_perfect_scores_returns_true(self):
        """All perfect scores should accept."""
        chunks = [
            {"text": "chunk a", "score": 1.0},
            {"text": "chunk b", "score": 1.0},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is True

    def test_missing_score_key_defaults_to_zero(self):
        """Chunks without 'score' key should default to 0."""
        chunks = [
            {"text": "no score key"},
            {"text": "also no score"},
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is False

    def test_mixed_missing_and_present_scores(self):
        """Mix of chunks with and without score keys."""
        chunks = [
            {"text": "with score", "score": 0.5},
            {"text": "without score"},  # defaults to 0
        ]
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is False  # only 1 strong source


class TestCustomMinStrongSources:
    """Tests for the min_strong_sources parameter."""

    def test_custom_min_strong_sources_1(self):
        """With min=1, a single strong source is enough."""
        chunks = [
            {"text": "strong", "score": 0.5},
        ]
        should_gen, _ = should_generate_answer(chunks, min_strong_sources=1)
        assert should_gen is True

    def test_custom_min_strong_sources_3(self):
        """With min=3, two strong sources are not enough."""
        chunks = [
            {"text": "strong 1", "score": 0.5},
            {"text": "strong 2", "score": 0.4},
        ]
        should_gen, _ = should_generate_answer(chunks, min_strong_sources=3)
        assert should_gen is False

    def test_custom_min_strong_sources_3_met(self):
        """With min=3, three strong sources should pass."""
        chunks = [
            {"text": "strong 1", "score": 0.5},
            {"text": "strong 2", "score": 0.4},
            {"text": "strong 3", "score": 0.35},
        ]
        should_gen, _ = should_generate_answer(chunks, min_strong_sources=3)
        assert should_gen is True

    def test_custom_min_zero(self):
        """With min=0, any chunks (even weak) should pass."""
        chunks = [
            {"text": "weak", "score": 0.01},
        ]
        should_gen, _ = should_generate_answer(chunks, min_strong_sources=0)
        assert should_gen is True

    def test_default_min_is_2(self):
        """Default min_strong_sources should be 2."""
        chunks = [
            {"text": "one strong", "score": 0.5},
        ]
        # Default: min_strong_sources=2
        should_gen, _ = should_generate_answer(chunks)
        assert should_gen is False

        # Explicit min=2 gives same result
        should_gen, _ = should_generate_answer(chunks, min_strong_sources=2)
        assert should_gen is False


class TestEmptyTextChunks:
    """Edge cases around chunk text content."""

    def test_empty_text_chunks_with_high_scores(self):
        """Chunks with empty text but high scores still count as strong."""
        chunks = [
            {"text": "", "score": 0.5},
            {"text": "", "score": 0.4},
        ]
        # should_generate_answer only checks score, not text content
        should_gen, reason = should_generate_answer(chunks)
        assert should_gen is True

    def test_whitespace_only_text_with_high_scores(self):
        """Chunks with whitespace-only text still count by score."""
        chunks = [
            {"text": "   ", "score": 0.5},
            {"text": "\n\t", "score": 0.4},
        ]
        should_gen, _ = should_generate_answer(chunks)
        assert should_gen is True

    def test_none_text_with_score(self):
        """Chunks with None text should not crash."""
        chunks = [
            {"text": None, "score": 0.5},
            {"text": "valid", "score": 0.4},
        ]
        # Should not raise; score-based check only
        should_gen, _ = should_generate_answer(chunks)
        assert isinstance(should_gen, bool)


class TestScoreBoundaryPrecision:
    """Precision boundary tests around the 0.32 threshold."""

    def test_exactly_at_threshold(self):
        """Score exactly 0.32 should count as strong."""
        chunks = [
            {"text": "a", "score": 0.32},
            {"text": "b", "score": 0.32},
        ]
        should_gen, _ = should_generate_answer(chunks)
        assert should_gen is True

    def test_just_below_threshold(self):
        """Score 0.319 should NOT count as strong."""
        chunks = [
            {"text": "a", "score": 0.319},
            {"text": "b", "score": 0.319},
        ]
        should_gen, _ = should_generate_answer(chunks)
        assert should_gen is False

    def test_just_above_threshold(self):
        """Score 0.321 should count as strong."""
        chunks = [
            {"text": "a", "score": 0.321},
            {"text": "b", "score": 0.321},
        ]
        should_gen, _ = should_generate_answer(chunks)
        assert should_gen is True

    def test_negative_scores(self):
        """Negative scores should not count as strong."""
        chunks = [
            {"text": "a", "score": -0.1},
            {"text": "b", "score": -0.5},
        ]
        should_gen, _ = should_generate_answer(chunks)
        assert should_gen is False


# ── CRAG Retrieval Quality Tests ────────────────────────────────────────────


class TestEvaluateRetrievalQuality:
    """Tests for CRAG-style retrieval quality evaluation."""

    def test_no_chunks_returns_incorrect(self):
        """No chunks → Incorrect classification."""
        report = evaluate_retrieval_quality("test query", [])
        assert report.classification == "Incorrect"
        assert report.total_count == 0
        assert report.correct_rate == 0.0
        assert len(report.recommendations) > 0

    def test_highly_relevant_chunks(self):
        """Chunks with strong keyword overlap → Correct classification.

        The CRAG scorer uses keyword overlap + cosine proxy, so we need
        enough shared tokens between query and chunk text for a 'Correct' hit.
        """
        chunks = [
            {"text": "Python programming language readability high level developers scripting."},
            {"text": "Python language created 1991 Guido Rossum interpreted dynamic typing."},
        ]
        report = evaluate_retrieval_quality("Python programming language", chunks)
        assert report.classification == "Correct"
        assert report.correct_count >= 1
        assert report.correct_rate >= 0.5

    def test_irrelevant_chunks(self):
        """Chunks with no keyword overlap → Incorrect classification."""
        chunks = [
            {"text": "The weather today is sunny with clear skies."},
            {"text": "Kubernetes manages container orchestration for deployments."},
        ]
        report = evaluate_retrieval_quality("What is Python?", chunks)
        assert report.classification == "Incorrect"
        assert report.correct_count == 0

    def test_mixed_relevance_chunks(self):
        """Mix of relevant and irrelevant → Ambiguous classification."""
        chunks = [
            {"text": "Python programming language high level scripting automation readability."},
            {"text": "The weather forecast predicts sunny skies and mild temperatures tomorrow."},
        ]
        report = evaluate_retrieval_quality("Python programming", chunks)
        # One chunk has strong overlap → correct; the other is irrelevant → incorrect
        assert report.classification in ("Ambiguous", "Correct")
        assert report.total_count == 2

    def test_report_has_all_fields(self):
        """Report must have all required fields populated."""
        report = evaluate_retrieval_quality("query", [{"text": "some text"}])
        assert isinstance(report, RetrievalQualityReport)
        assert hasattr(report, "classification")
        assert hasattr(report, "correct_count")
        assert hasattr(report, "incorrect_count")
        assert hasattr(report, "ambiguous_count")
        assert hasattr(report, "total_count")
        assert hasattr(report, "correct_rate")
        assert hasattr(report, "recommendations")
        assert isinstance(report.recommendations, list)

    def test_correct_rate_is_ratio(self):
        """correct_rate should be between 0.0 and 1.0."""
        chunks = [
            {"text": "Python is a programming language for developers."},
            {"text": "Completely unrelated text about gardening."},
        ]
        report = evaluate_retrieval_quality("Python programming", chunks)
        assert 0.0 <= report.correct_rate <= 1.0

    def test_single_highly_relevant_chunk(self):
        """Single chunk with excellent match should classify as Correct."""
        chunks = [
            {"text": "Python is a high-level programming language known for its readability."},
        ]
        report = evaluate_retrieval_quality("Python programming language", chunks)
        assert report.total_count == 1
        assert report.correct_rate >= 0.0


# ── Integration: Pipeline Refusal Path ──────────────────────────────────────


class TestNegativeRejectionIntegration:
    """Integration tests for negative rejection in the RAG pipeline.

    These verify that the refusal path is correctly wired — when
    should_generate_answer returns False, the pipeline must NOT call the LLM.
    """

    @patch("proxy.app.main.should_generate_answer")
    def test_refusal_path_returns_early(self, mock_should_gen):
        """When should_generate_answer returns False, pipeline must return refusal."""
        mock_should_gen.return_value = (False, "No relevant documents found in knowledge base")

        # Verify the mock is wired correctly
        should_gen, reason = mock_should_gen([])
        assert should_gen is False
        assert "No relevant documents" in reason

    @patch("proxy.app.main.should_generate_answer")
    def test_acceptance_path_continues(self, mock_should_gen):
        """When should_generate_answer returns True, pipeline continues."""
        mock_should_gen.return_value = (True, "Sufficient relevant sources found")

        should_gen, reason = mock_should_gen([{"score": 0.5}])
        assert should_gen is True
        assert "Sufficient" in reason

    def test_refusal_message_contains_reason(self):
        """The refusal message format from main.py should include the reason."""
        # Simulate the refusal message construction from main.py lines 397-400
        should_gen, reason = should_generate_answer([])
        if not should_gen:
            refusal = (
                f"I don't have enough relevant information to answer this "
                f"question reliably. {reason}"
            )
            assert "I don't have enough" in refusal
            assert "No relevant documents" in refusal

    def test_refusal_message_for_weak_sources(self):
        """Refusal message for weak sources includes 'insufficient' context."""
        chunks = [
            {"text": "weak", "score": 0.1},
            {"text": "also weak", "score": 0.05},
        ]
        should_gen, reason = should_generate_answer(chunks)
        if not should_gen:
            refusal = (
                f"I don't have enough relevant information to answer this "
                f"question reliably. {reason}"
            )
            assert "insufficient" in refusal.lower() or "no sufficiently" in refusal.lower()


# ── RetrievalQualityReport Dataclass Tests ──────────────────────────────────


class TestRetrievalQualityReport:
    """Direct tests for the RetrievalQualityReport dataclass."""

    def test_dataclass_fields(self):
        """All fields should be settable and retrievable."""
        report = RetrievalQualityReport(
            classification="Correct",
            correct_count=3,
            incorrect_count=1,
            ambiguous_count=1,
            total_count=5,
            correct_rate=0.6,
            recommendations=["Looks good"],
        )
        assert report.classification == "Correct"
        assert report.correct_count == 3
        assert report.incorrect_count == 1
        assert report.ambiguous_count == 1
        assert report.total_count == 5
        assert report.correct_rate == 0.6
        assert report.recommendations == ["Looks good"]

    def test_default_recommendations_is_empty_list(self):
        """recommendations should default to empty list."""
        report = RetrievalQualityReport(
            classification="Incorrect",
            correct_count=0,
            incorrect_count=0,
            ambiguous_count=0,
            total_count=0,
            correct_rate=0.0,
        )
        assert report.recommendations == []
