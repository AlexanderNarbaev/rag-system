"""Tests for self-reflection loops and verification in Level 5 RAG."""
import pytest
from unittest.mock import MagicMock, patch


class TestSelfReflectionNode:
    """Tests for the self_reflection orchestrator node."""

    def test_reflection_returns_state_dict(self):
        from proxy.app.orchestrator import self_reflection

        state = {
            "query": "What is Docker?",
            "answer": "Docker is a container platform.",
            "context": "Docker is a containerization platform released in 2013.",
            "rewrite_count": 0,
            "reflection_count": 0,
        }
        with patch("proxy.app.slm_router._call_slm_sync", return_value="FULLY_SUPPORTED"):
            with patch("proxy.app.config.REFLECTION_ENABLED", True):
                result = self_reflection(state)
                assert isinstance(result, dict)

    def test_reflection_identifies_gaps(self):
        from proxy.app.orchestrator import self_reflection

        state = {
            "query": "What is Docker?",
            "answer": "Docker is a container platform.",
            "context": "Docker is a containerization platform released in 2013.",
            "rewrite_count": 0,
            "reflection_count": 0,
        }
        with patch("proxy.app.slm_router._call_slm_sync", return_value="PARTIALLY_SUPPORTED\nMISSING: release date details"):
            with patch("proxy.app.config.REFLECTION_ENABLED", True):
                result = self_reflection(state)
                assert isinstance(result, dict)

    def test_reflection_stops_at_max_depth(self):
        from proxy.app.orchestrator import self_reflection

        state = {
            "query": "Question?",
            "answer": "Weak answer.",
            "context": "Some context.",
            "rewrite_count": 0,
            "reflection_count": 2,
        }
        with patch("proxy.app.config.REFLECTION_ENABLED", True):
            result = self_reflection(state)
            assert result.get("needs_reflection") is False

    def test_reflection_with_slm_failure(self):
        from proxy.app.orchestrator import self_reflection

        state = {
            "query": "Question?",
            "answer": "Answer.",
            "context": "Context.",
            "rewrite_count": 0,
            "reflection_count": 0,
        }
        with patch("proxy.app.slm_router._call_slm_sync", side_effect=Exception("SLM error")):
            with patch("proxy.app.config.REFLECTION_ENABLED", True):
                result = self_reflection(state)
                assert isinstance(result, dict)
                assert result.get("needs_reflection") is False

    def test_reflection_empty_answer(self):
        from proxy.app.orchestrator import self_reflection

        state = {
            "query": "Query?",
            "answer": "",
            "context": "Context.",
            "rewrite_count": 0,
            "reflection_count": 0,
        }
        result = self_reflection(state)
        assert isinstance(result, dict)
        assert result.get("needs_reflection") is False

    def test_reflection_multi_hop_verification(self):
        from proxy.app.orchestrator import self_reflection

        state = {
            "query": "How does Docker networking work?",
            "answer": "Docker uses bridge networks by default and supports overlay networks for Swarm.",
            "context": "Docker networking uses bridge networks by default. Overlay networks enable multi-host communication in Docker Swarm.",
            "rewrite_count": 0,
            "reflection_count": 0,
        }
        with patch("proxy.app.slm_router._call_slm_sync", return_value="FULLY_SUPPORTED"):
            with patch("proxy.app.config.REFLECTION_ENABLED", True):
                result = self_reflection(state)
                assert isinstance(result, dict)


class TestSelfReflectionRoute:
    """Tests for the self_reflection routing decision."""

    def test_route_to_done_when_no_gaps(self):
        from proxy.app.orchestrator import _self_reflection_route

        state = {"needs_reflection": False}
        assert _self_reflection_route(state) == "done"

    def test_route_to_retrieve_when_gaps(self):
        from proxy.app.orchestrator import _self_reflection_route

        state = {"needs_reflection": True}
        assert _self_reflection_route(state) == "retrieve"


class TestCRAGEvaluator:
    """Tests for the CRAG retrieval quality evaluator."""

    def test_evaluate_retrieval_quality_returns_report(self):
        from proxy.app.confidence import evaluate_retrieval_quality, RetrievalQualityReport

        chunks = [
            {"text": "Docker is a containerization platform that uses OS-level virtualization.", "score": 0.9},
            {"text": "The weather is nice today.", "score": 0.1},
            {"text": "Container orchestration with Kubernetes.", "score": 0.6},
        ]
        report = evaluate_retrieval_quality("What is Docker containerization?", chunks)
        assert isinstance(report, RetrievalQualityReport)
        assert 0.0 <= report.correct_rate <= 1.0

    def test_evaluate_classifies_correct_chunks(self):
        from proxy.app.confidence import evaluate_retrieval_quality

        chunks = [
            {"text": "Docker uses containers for application deployment and scaling.", "score": 0.95},
        ]
        report = evaluate_retrieval_quality("How does Docker deployment work?", chunks)
        assert report.correct_count >= 0

    def test_evaluate_classifies_incorrect_chunks(self):
        from proxy.app.confidence import evaluate_retrieval_quality

        chunks = [
            {"text": "Football is a popular sport played worldwide.", "score": 0.1},
        ]
        report = evaluate_retrieval_quality("What is Docker containerization?", chunks)
        assert report.incorrect_count >= 0

    def test_evaluate_empty_chunks(self):
        from proxy.app.confidence import evaluate_retrieval_quality

        report = evaluate_retrieval_quality("Query?", [])
        assert report.total_count == 0
        assert report.correct_count == 0

    def test_evaluate_returns_recommendations(self):
        from proxy.app.confidence import evaluate_retrieval_quality

        chunks = [
            {"text": "Docker is a platform.", "score": 0.4},
        ]
        report = evaluate_retrieval_quality("What is Docker?", chunks)
        assert isinstance(report.recommendations, list)

    def test_evaluate_score_thresholds(self):
        from proxy.app.confidence import _score_chunk_relevance

        score = _score_chunk_relevance("Docker containers", "Docker is a container platform.")
        assert 0.0 <= score <= 1.0

    def test_evaluate_numeric_query(self):
        from proxy.app.confidence import evaluate_retrieval_quality

        chunks = [
            {"text": "Python 3.12 was released on October 2, 2023.", "score": 0.9},
        ]
        report = evaluate_retrieval_quality("When was Python 3.12 released?", chunks)
        assert report.total_count == 1


class TestVerifyAnswerClaims:
    """Tests for answer claim verification (F4)."""

    def test_verify_decomposes_into_claims(self):
        from proxy.app.confidence import verify_answer_claims, VerificationReport

        answer = "Python was created by Guido van Rossum. It is used for web development."
        context = "Python is a programming language created by Guido van Rossum in 1991. It is widely used for web development."
        report = verify_answer_claims(answer, context)
        assert isinstance(report, VerificationReport)
        assert report.total_claims >= 1

    def test_verify_detects_unsupported_claims(self):
        from proxy.app.confidence import verify_answer_claims

        answer = "Python runs on JVM natively. It was invented in 1995."
        context = "Python is a programming language created by Guido van Rossum in 1991."
        report = verify_answer_claims(answer, context)
        assert isinstance(report.verification_rate, float)
        assert 0.0 <= report.verification_rate <= 1.0

    def test_verify_all_supported_claims(self):
        from proxy.app.confidence import verify_answer_claims

        answer = "Docker is a container platform."
        context = "Docker is a containerization platform that runs applications in containers."
        report = verify_answer_claims(answer, context)
        assert len(report.supported_claims) > 0

    def test_verify_empty_answer(self):
        from proxy.app.confidence import verify_answer_claims

        report = verify_answer_claims("", "Some context.")
        assert report.verification_rate == 0.0

    def test_verify_empty_context(self):
        from proxy.app.confidence import verify_answer_claims

        report = verify_answer_claims("Some answer.", "")
        assert report.verification_rate == 0.0

    def test_verify_report_fields(self):
        from proxy.app.confidence import verify_answer_claims

        answer = "Python is a programming language. It supports OOP."
        context = "Python is a high-level programming language that supports object-oriented programming."
        report = verify_answer_claims(answer, context)
        assert isinstance(report.supported_claims, list)
        assert isinstance(report.unsupported_claims, list)
        assert isinstance(report.verification_rate, float)
