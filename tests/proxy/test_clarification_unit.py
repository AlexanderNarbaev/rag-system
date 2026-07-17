"""Tests for clarification module."""

from unittest.mock import patch

from proxy.app.core.clarification import (
    ClarificationResult,
    _generate_heuristic,
    build_uncertainty_response,
    generate_clarifying_questions,
)


class TestGenerateClarifyingQuestions:
    def test_grounded_status_returns_empty(self):
        result = generate_clarifying_questions(
            "What is RAG?",
            status="grounded",
            sources=[],
            use_slm=False,
        )
        assert result.clarification_needed is False
        assert result.questions == []

    def test_no_slm_falls_back_to_heuristic_no_knowledge(self):
        result = generate_clarifying_questions(
            "What is X?",
            status="no_knowledge",
            sources=[],
            use_slm=False,
        )
        assert result.clarification_needed is True
        assert len(result.questions) >= 1
        assert result.generated_by == "heuristic"

    def test_no_slm_falls_back_to_heuristic_partial(self):
        result = generate_clarifying_questions(
            "What is X?",
            status="partial",
            sources=[],
            use_slm=False,
        )
        assert result.clarification_needed is True
        assert len(result.questions) >= 1
        assert result.generated_by == "heuristic"

    def test_slm_attempt_fails_falls_back(self):
        with patch("proxy.app.core.clarification._generate_with_slm") as mock_slm:
            mock_slm.side_effect = RuntimeError("SLM crash")
            result = generate_clarifying_questions(
                "What is X?",
                status="no_knowledge",
                sources=[],
                use_slm=True,
            )
            assert result.clarification_needed is True
            assert result.generated_by == "heuristic"

    def test_slm_returns_empty_falls_back(self):
        with patch("proxy.app.core.clarification._generate_with_slm") as mock_slm:
            mock_slm.return_value = ClarificationResult()
            result = generate_clarifying_questions(
                "What is X?",
                status="no_knowledge",
                sources=[],
                use_slm=True,
            )
            assert result.clarification_needed is True
            assert result.generated_by == "heuristic"


class TestGenerateHeuristic:
    def test_no_knowledge_short_query(self):
        result = _generate_heuristic("What is X?", "no_knowledge", [])
        assert result.clarification_needed is True
        assert result.generated_by == "heuristic"
        assert len(result.questions) == 1
        assert "rephrase" in result.questions[0].lower()

    def test_no_knowledge_long_query(self):
        query = "What is the meaning of life the universe and everything in this world and beyond?"
        result = _generate_heuristic(query, "no_knowledge", [])
        assert len(result.questions) == 2
        assert any("smaller" in q.lower() for q in result.questions)

    def test_partial_with_sources_having_titles(self):
        sources = [{"title": "Authentication Guide", "source": "confluence"}]
        result = _generate_heuristic("How to auth?", "partial", sources)
        assert len(result.questions) >= 1
        assert "Authentication Guide" in result.questions[0]

    def test_partial_with_sources_no_titles(self):
        sources = [{"source": "unknown"}]
        result = _generate_heuristic("How to auth?", "partial", sources)
        assert len(result.questions) >= 1
        assert "specific aspect" in result.questions[0].lower()

    def test_partial_no_sources(self):
        result = _generate_heuristic("How to auth?", "partial", [])
        assert len(result.questions) >= 1
        assert "more specific details" in result.questions[0].lower()

    def test_returns_at_most_two_questions(self):
        sources = [
            {"title": "Doc A", "source": "confluence"},
            {"title": "Doc B", "source": "jira"},
            {"title": "Doc C", "source": "gitlab"},
        ]
        result = _generate_heuristic("topic", "partial", sources)
        assert len(result.questions) <= 2


class TestBuildUncertaintyResponse:
    def test_grounded_returns_empty(self):
        result = build_uncertainty_response("query", "grounded", [])
        assert result == ""

    def test_no_knowledge_no_sources(self):
        result = build_uncertainty_response("What is X?", "no_knowledge", [])
        assert "What is X?" in result
        assert "No matching documents" in result
        assert "What's missing" in result
        assert "Suggestions" in result

    def test_partial_with_sources(self):
        sources = [
            {"title": "Doc1", "relevance": 0.45},
            {"source": "source2", "relevance": 0.30},
        ]
        result = build_uncertainty_response("query", "partial", sources)
        assert "Doc1" in result
        assert "0.45" in result
        assert "partial matches" in result
        assert "Suggestions" in result

    def test_partial_source_with_no_title_uses_source(self):
        sources = [{"source": "my_source", "relevance": 0.50}]
        result = build_uncertainty_response("query", "partial", sources)
        assert "my_source" in result
        assert "0.50" in result

    def test_short_query_suggestion(self):
        result = build_uncertainty_response("Hi", "no_knowledge", [])
        assert "more specific details" in result.lower()

    def test_long_query_suggestion(self):
        result = build_uncertainty_response("What is the best way to do this thing?", "no_knowledge", [])
        assert "different keywords" in result.lower()

    def test_with_clarifying_questions(self):
        clarification = ClarificationResult(
            questions=["Could you clarify X?", "What about Y?"],
            clarification_needed=True,
            generated_by="heuristic",
        )
        result = build_uncertainty_response("query", "partial", [], clarification)
        assert "Clarifying questions:" in result
        assert "Could you clarify X?" in result
        assert "What about Y?" in result

    def test_sources_limited_to_three(self):
        sources = [
            {"title": f"Doc{i}", "relevance": 0.5} for i in range(5)
        ]
        result = build_uncertainty_response("query", "partial", sources)
        assert "Doc0" in result
        assert "Doc2" in result
        assert "Doc3" not in result
