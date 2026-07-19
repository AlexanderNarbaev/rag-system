"""Tests for knowledge_status module (FR-144 taxonomy)."""

from proxy.app.core.knowledge_status import (
    KnowledgeStatus,
    determine_knowledge_status,
    normalize_knowledge_status,
)


class TestKnowledgeStatus:
    def test_status_dataclass(self):
        status = KnowledgeStatus(
            status="sufficient",
            source_count=5,
            strong_source_count=3,
            max_score=0.85,
            reason="well grounded",
        )
        assert status.status == "sufficient"
        assert status.source_count == 5
        assert status.strong_source_count == 3
        assert status.max_score == 0.85
        assert status.reason == "well grounded"


class TestNormalizeKnowledgeStatus:
    def test_new_statuses_passthrough(self):
        assert normalize_knowledge_status("sufficient") == "sufficient"
        assert normalize_knowledge_status("partial") == "partial"
        assert normalize_knowledge_status("insufficient") == "insufficient"
        assert normalize_knowledge_status("absent") == "absent"

    def test_old_grounded_maps_to_sufficient(self):
        assert normalize_knowledge_status("grounded") == "sufficient"

    def test_old_no_knowledge_maps_to_absent(self):
        assert normalize_knowledge_status("no_knowledge") == "absent"


class TestDetermineKnowledgeStatus:
    def test_no_sources_returns_absent(self):
        result = determine_knowledge_status([], should_generate=True)
        assert result.status == "absent"
        assert result.source_count == 0
        assert result.strong_source_count == 0
        assert result.max_score == 0.0
        assert "No relevant sources" in result.reason

    def test_should_not_generate_returns_insufficient(self):
        sources = [{"relevance": 0.9}]
        result = determine_knowledge_status(sources, should_generate=False)
        assert result.status == "insufficient"
        assert result.source_count == 1
        assert "Insufficient source quality" in result.reason

    def test_sufficient_many_strong(self):
        sources = [
            {"relevance": 0.5},
            {"relevance": 0.4},
            {"relevance": 0.32},
        ]
        result = determine_knowledge_status(sources)
        assert result.status == "sufficient"
        assert result.strong_source_count == 3
        assert result.source_count == 3

    def test_sufficient_exactly_min_strong(self):
        sources = [
            {"relevance": 0.32},
            {"relevance": 0.32},
        ]
        result = determine_knowledge_status(sources)
        assert result.status == "sufficient"
        assert result.strong_source_count == 2

    def test_insufficient_one_strong(self):
        sources = [
            {"relevance": 0.9},
            {"relevance": 0.1},
        ]
        result = determine_knowledge_status(sources)
        assert result.status == "insufficient"
        assert result.strong_source_count == 1
        assert result.source_count == 2
        assert "Only 1 strong" in result.reason

    def test_partial_all_weak(self):
        sources = [
            {"relevance": 0.1},
            {"relevance": 0.15},
        ]
        result = determine_knowledge_status(sources)
        assert result.status == "partial"
        assert result.strong_source_count == 0

    def test_uses_score_key_fallback(self):
        sources = [
            {"score": 0.5},
            {"score": 0.4},
        ]
        result = determine_knowledge_status(sources)
        assert result.status == "sufficient"

    def test_max_score_from_sources(self):
        sources = [
            {"relevance": 0.1},
            {"relevance": 0.99},
        ]
        result = determine_knowledge_status(sources)
        assert result.max_score == 0.99

    def test_reason_for_sufficient(self):
        sources = [
            {"relevance": 0.5},
            {"relevance": 0.6},
        ]
        result = determine_knowledge_status(sources)
        assert "grounded in 2 source(s) (2 strong)" in result.reason
