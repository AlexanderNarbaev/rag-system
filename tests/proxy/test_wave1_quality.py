"""Tests for Wave 1 RAG Core Quality features.

Covers:
- FR-01: rag_knowledge_status determination
- FR-02: SSE stream metadata with knowledge status
- FR-03: ConversationMemory wiring
- FR-04: Conversation summarization
- FR-05: Clarifying question generation
- FR-06: Structured uncertainty response
"""

import sys
from unittest.mock import MagicMock

# Mock modules that may not be installed
for _mod in ("qdrant_client", "qdrant_client.http", "sentence_transformers", "neo4j"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


class TestKnowledgeStatus:
    """FR-01: Knowledge status determination."""

    def test_grounded_with_strong_sources(self):
        from proxy.app.core.knowledge_status import determine_knowledge_status

        sources = [
            {"title": "Doc A", "relevance": 0.85},
            {"title": "Doc B", "relevance": 0.65},
            {"title": "Doc C", "relevance": 0.15},
        ]
        result = determine_knowledge_status(sources, should_generate=True)
        assert result.status == "sufficient"
        assert result.source_count == 3
        assert result.strong_source_count == 2
        assert result.max_score == 0.85

    def test_grounded_with_exact_two_strong(self):
        from proxy.app.core.knowledge_status import determine_knowledge_status

        sources = [
            {"title": "Doc A", "relevance": 0.32},
            {"title": "Doc B", "relevance": 0.32},
        ]
        result = determine_knowledge_status(sources, should_generate=True)
        assert result.status == "sufficient"
        assert result.strong_source_count == 2

    def test_partial_with_one_strong(self):
        from proxy.app.core.knowledge_status import determine_knowledge_status

        sources = [
            {"title": "Doc A", "relevance": 0.50},
            {"title": "Doc B", "relevance": 0.20},
            {"title": "Doc C", "relevance": 0.10},
        ]
        result = determine_knowledge_status(sources, should_generate=True)
        assert result.status == "insufficient"
        assert result.strong_source_count == 1

    def test_partial_no_strong(self):
        from proxy.app.core.knowledge_status import determine_knowledge_status

        sources = [
            {"title": "Doc A", "relevance": 0.30},
            {"title": "Doc B", "relevance": 0.25},
        ]
        result = determine_knowledge_status(sources, should_generate=True)
        assert result.status == "partial"
        assert result.strong_source_count == 0

    def test_no_knowledge_empty_sources(self):
        from proxy.app.core.knowledge_status import determine_knowledge_status

        result = determine_knowledge_status([], should_generate=True)
        assert result.status == "absent"
        assert result.source_count == 0
        assert result.strong_source_count == 0

    def test_no_knowledge_refused_generation(self):
        from proxy.app.core.knowledge_status import determine_knowledge_status

        sources = [{"title": "Doc A", "relevance": 0.90}]
        result = determine_knowledge_status(sources, should_generate=False)
        assert result.status == "insufficient"

    def test_uses_score_fallback(self):
        from proxy.app.core.knowledge_status import determine_knowledge_status

        sources = [{"title": "Doc A", "score": 0.80}]
        result = determine_knowledge_status(sources, should_generate=True)
        assert result.max_score == 0.80


class TestConversationMemory:
    """FR-03 & FR-04: ConversationMemory with entity tracking and summarization."""

    def test_add_and_get_turns(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory()
        cm.add_turn("user", "What is Python?")
        cm.add_turn("assistant", "Python is a programming language.")
        assert len(cm) == 2
        ctx = cm.get_context(max_turns=5)
        assert "What is Python" in ctx
        assert "Python is a programming language" in ctx

    def test_entity_tracking(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory()
        cm.add_turn("user", "Tell me about Kubernetes and Docker.")
        cm.add_turn("assistant", "Kubernetes is an orchestration platform. Docker provides containers.")
        entities = cm.get_entity_tracker().get_top_entities()
        assert "Kubernetes" in entities
        assert "Docker" in entities

    def test_needs_summarization(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory(summary_threshold_tokens=10)
        cm.add_turn("user", "a" * 200)
        assert cm.needs_summarization()

        cm2 = ConversationMemory(summary_threshold_tokens=10000)
        cm2.add_turn("user", "short")
        assert not cm2.needs_summarization()

    def test_summarize_older_turns(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory()
        for i in range(10):
            cm.add_turn("user", f"Question {i}")
            cm.add_turn("assistant", f"Answer {i}")
        assert len(cm) == 20
        cm.summarize_older_turns(keep_recent=4)
        assert len(cm) == 4
        assert len(cm.get_summaries()) == 1

    def test_get_context_as_messages(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory()
        cm.add_turn("user", "hello")
        cm.add_turn("assistant", "hi there")
        msgs = cm.get_context_as_messages(max_turns=2)
        assert len(msgs) >= 2
        roles = [m["role"] for m in msgs]
        assert "user" in roles
        assert "assistant" in roles

    def test_get_full_history_includes_summaries(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory()
        cm.add_turn("user", "Q1" * 30)
        cm.add_turn("assistant", "A1" * 30)
        cm.add_turn("user", "Q2" * 30)
        cm.add_turn("assistant", "A2" * 30)
        cm.add_turn("user", "Q3")
        cm.add_turn("assistant", "A3")
        cm.summarize_older_turns(keep_recent=2)
        msgs = cm.get_full_history_as_messages(max_turns=10)
        assert any("SUMMARY" in m["content"] for m in msgs)

    def test_session_store(self):
        from proxy.app.shared.memory_manager import clear_conversation, get_conversation

        cm = get_conversation("test-session")
        cm.add_turn("user", "test")
        assert len(cm) == 1

        cm2 = get_conversation("test-session")
        assert len(cm2) == 1

        clear_conversation("test-session")
        cm3 = get_conversation("test-session")
        assert len(cm3) == 0


class TestConversationSummarization:
    """FR-04: Conversation summarization with token threshold."""

    def test_estimate_tokens(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory()
        cm.add_turn("user", "Hello " * 100)
        tokens = cm.estimate_tokens()
        assert tokens > 0

    def test_summary_replaces_turns_with_summary(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory()
        for i in range(20):
            cm.add_turn("user", f"Question number {i}: " + "details " * 20)
            cm.add_turn("assistant", f"Answer number {i}: " + "details " * 20)
        original_len = len(cm)
        cm.summarize_older_turns(keep_recent=6)
        assert len(cm) < original_len
        assert len(cm.get_summaries()) >= 1

    def test_multiple_summaries_capped(self):
        from proxy.app.shared.memory_manager import ConversationMemory

        cm = ConversationMemory()
        for iteration in range(10):
            for i in range(10):
                cm.add_turn("user", f"Iter{iteration} Q{i} " + "x" * 20)
                cm.add_turn("assistant", f"Iter{iteration} A{i} " + "x" * 20)
            cm.summarize_older_turns(keep_recent=4)
        assert len(cm.get_summaries()) <= 3


class TestClarification:
    """FR-05: Clarifying question generation."""

    def test_no_clarification_when_grounded(self):
        from proxy.app.core.clarification import generate_clarifying_questions

        result = generate_clarifying_questions(
            query="What is Python?",
            status="sufficient",
            use_slm=False,
        )
        assert not result.clarification_needed
        assert len(result.questions) == 0

    def test_no_clarification_when_grounded_old_name(self):
        from proxy.app.core.clarification import generate_clarifying_questions

        result = generate_clarifying_questions(
            query="What is Python?",
            status="grounded",
            use_slm=False,
        )
        assert not result.clarification_needed
        assert len(result.questions) == 0

    def test_heuristic_no_knowledge(self):
        from proxy.app.core.clarification import generate_clarifying_questions

        result = generate_clarifying_questions(
            query="Tell me about X",
            status="absent",
            use_slm=False,
        )
        assert result.clarification_needed
        assert len(result.questions) >= 1
        assert "generated_by" in result.__dict__
        assert result.generated_by == "heuristic"

    def test_heuristic_insufficient(self):
        from proxy.app.core.clarification import generate_clarifying_questions

        result = generate_clarifying_questions(
            query="How do I configure the server?",
            status="insufficient",
            sources=[{"title": "Server Setup Guide", "relevance": 0.35}],
            use_slm=False,
        )
        assert result.clarification_needed
        assert len(result.questions) >= 1

    def test_short_query_gets_rephrase_suggestion(self):
        from proxy.app.core.clarification import generate_clarifying_questions

        result = generate_clarifying_questions(
            query="Kubernetes?",
            status="absent",
            use_slm=False,
        )
        assert result.clarification_needed
        assert any("rephrase" in q.lower() or "specific" in q.lower() for q in result.questions)


class TestUncertaintyResponse:
    """FR-06: Structured uncertainty response template."""

    def test_build_uncertainty_for_no_knowledge(self):
        from proxy.app.core.clarification import build_uncertainty_response

        response = build_uncertainty_response(
            query="What is X?",
            status="absent",
            sources=[],
        )
        assert "wasn't able to find" in response.lower() or "not able" in response.lower()
        assert "What's missing" in response or "missing" in response.lower()
        assert "Suggestions" in response

    def test_build_uncertainty_with_sources(self):
        from proxy.app.core.clarification import build_uncertainty_response

        response = build_uncertainty_response(
            query="How to configure Nginx?",
            status="insufficient",
            sources=[
                {"title": "Apache Configuration", "relevance": 0.30},
            ],
        )
        assert "Apache Configuration" in response
        assert "partial matches" in response.lower()

    def test_build_uncertainty_with_clarification(self):
        from proxy.app.core.clarification import ClarificationResult, build_uncertainty_response

        clarification = ClarificationResult(
            questions=["Are you looking for the setup on Ubuntu or CentOS?"],
            clarification_needed=True,
        )
        response = build_uncertainty_response(
            query="How to install Python?",
            status="insufficient",
            sources=[],
            clarification=clarification,
        )
        assert "Ubuntu" in response
        assert "CentOS" in response

    def test_no_response_for_grounded(self):
        from proxy.app.core.clarification import build_uncertainty_response

        response = build_uncertainty_response(
            query="What is 2+2?",
            status="sufficient",
            sources=[{"title": "Math", "relevance": 0.90}],
        )
        assert response == ""

    def test_no_response_for_grounded_old_name(self):
        from proxy.app.core.clarification import build_uncertainty_response

        response = build_uncertainty_response(
            query="What is 2+2?",
            status="grounded",
            sources=[{"title": "Math", "relevance": 0.90}],
        )
        assert response == ""


class TestChatResponseModel:
    """FR-01: ChatCompletionResponse model with new fields."""

    def test_response_model_has_new_fields(self):
        from proxy.app.api.chat import ChatCompletionResponse, ChatCompletionResponseChoice, ChatMessage

        resp = ChatCompletionResponse(
            id="test-123",
            created=1700000000,
            model="test-model",
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="Hello"),
                    finish_reason="stop",
                ),
            ],
            rag_knowledge_status="sufficient",
            rag_source_count=3,
            rag_clarification_needed=False,
            rag_clarifying_questions=None,
        )
        assert resp.rag_knowledge_status == "sufficient"
        assert resp.rag_source_count == 3
        assert resp.rag_clarification_needed is False

    def test_response_serializes_new_fields(self):
        import json

        from proxy.app.api.chat import ChatCompletionResponse, ChatCompletionResponseChoice, ChatMessage

        resp = ChatCompletionResponse(
            id="test-123",
            created=1700000000,
            model="test-model",
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="Hello"),
                    finish_reason="stop",
                ),
            ],
            rag_knowledge_status="insufficient",
            rag_source_count=1,
            rag_clarification_needed=True,
            rag_clarifying_questions=["Can you be more specific?"],
        )
        data = resp.model_dump()
        assert data["rag_knowledge_status"] == "insufficient"
        assert data["rag_source_count"] == 1
        assert data["rag_clarification_needed"] is True
        assert data["rag_clarifying_questions"] == ["Can you be more specific?"]
        json_str = json.dumps(data)
        assert "rag_knowledge_status" in json_str


class TestConfig:
    """Configuration for Wave 1 features."""

    def test_conversation_config_defaults(self):
        from proxy.app.shared.config import (
            CLARIFICATION_ENABLED,
            CONVERSATION_MAX_TURNS,
            CONVERSATION_SUMMARY_THRESHOLD_TOKENS,
        )

        assert CONVERSATION_MAX_TURNS >= 1
        assert CONVERSATION_SUMMARY_THRESHOLD_TOKENS >= 100
        assert isinstance(CLARIFICATION_ENABLED, bool)
