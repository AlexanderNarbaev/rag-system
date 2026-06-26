"""Tests for proxy/app/slm_router.py - SLM routing with mocked _call_slm_sync."""
import json
from unittest.mock import patch, MagicMock

import pytest

from proxy.app.slm_router import (
    IntentType,
    classify_intent,
    decompose_query,
    needs_retrieval,
    rewrite_query_slm,
    extract_entities_slm,
    should_use_graph,
    _call_slm_sync,
)


class TestCallSlmSync:
    """Tests for _call_slm_sync behavior."""

    def test_returns_empty_when_not_configured(self):
        with patch("proxy.app.slm_router.SLM_ENDPOINT", ""):
            result = _call_slm_sync("some prompt")
            assert result == ""

    def test_sends_request_when_configured(self):
        import requests as real_requests
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": " factual"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("proxy.app.slm_router.SLM_ENDPOINT", "http://slm:8080/v1"), \
             patch("requests.post", return_value=mock_response):
            result = _call_slm_sync("classify this")
            assert result == "factual"

    def test_handles_request_exception(self):
        with patch("proxy.app.slm_router.SLM_ENDPOINT", "http://slm:8080/v1"), \
             patch("requests.post", side_effect=Exception("timeout")):
            result = _call_slm_sync("prompt")
            assert result == ""

    def test_includes_auth_header(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("proxy.app.slm_router.SLM_ENDPOINT", "http://slm:8080/v1"), \
             patch("proxy.app.slm_router.SLM_API_KEY", "secret-key"), \
             patch("requests.post", return_value=mock_response) as mock_post:
            result = _call_slm_sync("prompt")
            call_headers = mock_post.call_args[1]["headers"]
            assert "Authorization" in call_headers
            assert "secret-key" in call_headers["Authorization"]


class TestClassifyIntent:
    """Tests for classify_intent."""

    def test_factual_intent(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="factual"):
            intent, confidence = classify_intent("What is Kubernetes?")
            assert intent == IntentType.FACTUAL
            assert confidence == 0.8

    def test_procedural_intent(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="procedural"):
            intent, _ = classify_intent("How to set up CI/CD?")
            assert intent == IntentType.PROCEDURAL

    def test_comparison_intent(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="comparison"):
            intent, _ = classify_intent("Compare GitLab vs GitHub")
            assert intent == IntentType.COMPARISON

    def test_summarize_intent(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="summarize"):
            intent, _ = classify_intent("Summarize this document")
            assert intent == IntentType.SUMMARIZATION

    def test_greeting_intent(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="greeting"):
            intent, _ = classify_intent("Hello there!")
            assert intent == IntentType.GREETING

    def test_unknown_when_slm_fails(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="nonsense"):
            intent, confidence = classify_intent("blah")
            assert intent == IntentType.UNKNOWN
            assert confidence == 0.5

    def test_unknown_when_slm_empty(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value=""):
            intent, _ = classify_intent("anything")
            assert intent == IntentType.UNKNOWN


class TestDecomposeQuery:
    """Tests for decompose_query."""

    def test_valid_json_response(self):
        response = json.dumps(["sub1", "sub2", "sub3"])
        with patch("proxy.app.slm_router._call_slm_sync", return_value=response):
            result = decompose_query("complex query", max_subqueries=3)
            assert result == ["sub1", "sub2", "sub3"]

    def test_truncates_to_max(self):
        response = json.dumps(["a", "b", "c", "d"])
        with patch("proxy.app.slm_router._call_slm_sync", return_value=response):
            result = decompose_query("q", max_subqueries=2)
            assert result == ["a", "b"]

    def test_fallback_on_invalid_json(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value='not json but "extracted" and "more"'):
            result = decompose_query("q")
            assert "extracted" in result
            assert "more" in result

    def test_fallback_on_non_list(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value='{"a": 1}'):
            result = decompose_query("q")
            assert result == ["q"]  # fallback to original

    def test_slm_empty_fallback(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value=""):
            result = decompose_query("original query")
            assert result == ["original query"]


class TestNeedsRetrieval:
    """Tests for needs_retrieval function."""

    def test_factual_needs_retrieval(self):
        assert needs_retrieval(IntentType.FACTUAL) is True

    def test_procedural_needs_retrieval(self):
        assert needs_retrieval(IntentType.PROCEDURAL) is True

    def test_comparison_needs_retrieval(self):
        assert needs_retrieval(IntentType.COMPARISON) is True

    def test_summarization_needs_retrieval(self):
        assert needs_retrieval(IntentType.SUMMARIZATION) is True

    def test_greeting_no_retrieval(self):
        assert needs_retrieval(IntentType.GREETING) is False

    def test_unknown_no_retrieval(self):
        assert needs_retrieval(IntentType.UNKNOWN) is False


class TestRewriteQuerySlm:
    """Tests for rewrite_query_slm."""

    def test_rewrite_success(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="CI/CD pipeline setup guide"):
            result = rewrite_query_slm("How to set up CI/CD?")
            assert result == "CI/CD pipeline setup guide"

    def test_fallback_to_original(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value=""):
            result = rewrite_query_slm("original question")
            assert result == "original question"


class TestExtractEntitiesSlm:
    """Tests for extract_entities_slm."""

    def test_extracts_entities_from_json(self):
        response = json.dumps(["GitLab", "CI/CD", "PROJ-123"])
        with patch("proxy.app.slm_router._call_slm_sync", return_value=response):
            result = extract_entities_slm("How to use GitLab CI/CD PROJ-123?")
            assert result == ["GitLab", "CI/CD", "PROJ-123"]

    def test_regex_fallback_on_bad_json(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="not valid json"):
            result = extract_entities_slm("Use GitLab and Docker")
            assert len(result) > 0

    def test_empty_when_slm_fails_and_no_caps(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value="bad"):
            result = extract_entities_slm("all lowercase words only")
            assert result == []

    def test_non_list_json_returns_empty(self):
        with patch("proxy.app.slm_router._call_slm_sync", return_value='{"key": "value"}'):
            result = extract_entities_slm("query")
            assert result == []


class TestShouldUseGraph:
    """Tests for should_use_graph function."""

    def test_comparison_uses_graph(self):
        assert should_use_graph(IntentType.COMPARISON, "compare x and y") is True

    def test_relation_words_trigger_graph(self):
        assert should_use_graph(IntentType.FACTUAL, "как связан проект А и Б") is True
        assert should_use_graph(IntentType.FACTUAL, "кто использует Docker?") is True

    def test_factual_without_relation_no_graph(self):
        assert should_use_graph(IntentType.FACTUAL, "What is Kubernetes?") is False

    def test_procedural_no_graph(self):
        assert should_use_graph(IntentType.PROCEDURAL, "How to install Docker?") is False


class TestScoreQueryComplexity:
    """Tests for score_query_complexity heuristic."""

    def test_short_query_low_complexity(self):
        from proxy.app.slm_router import score_query_complexity

        score = score_query_complexity("Hello")
        assert 1 <= score <= 3

    def test_long_query_high_complexity(self):
        from proxy.app.slm_router import score_query_complexity

        query = "Please explain how everything works in great detail including all the steps and configurations that need to be set up correctly"
        score = score_query_complexity(query)
        assert score >= 5

    def test_comparison_query_high_complexity(self):
        from proxy.app.slm_router import score_query_complexity

        with patch("proxy.app.slm_router.classify_intent", return_value=(IntentType.COMPARISON, 0.9)):
            score = score_query_complexity("Compare Kubernetes vs Docker Swarm for production")
            assert score >= 7

    def test_procedural_query_medium_complexity(self):
        from proxy.app.slm_router import score_query_complexity

        with patch("proxy.app.slm_router.classify_intent", return_value=(IntentType.PROCEDURAL, 0.9)):
            score = score_query_complexity("How to set up CI/CD pipeline?")
            assert score >= 5

    def test_returns_valid_range(self):
        from proxy.app.slm_router import score_query_complexity

        for query in ["Hi", "What is RAG?", "How to deploy and configure the entire system with all components"]:
            score = score_query_complexity(query)
            assert 1 <= score <= 10, f"query='{query}' score={score}"

    def test_falls_back_on_classify_error(self):
        from proxy.app.slm_router import score_query_complexity

        with patch("proxy.app.slm_router.classify_intent", side_effect=Exception("no SLM")):
            score = score_query_complexity("test query")
            assert 1 <= score <= 10

    def test_multi_question_increases_complexity(self):
        from proxy.app.slm_router import score_query_complexity

        single_score = score_query_complexity("What is Docker?")
        multi_score = score_query_complexity("What is Docker? How does it work? Why is it useful?")
        assert multi_score >= single_score


class TestDynamicTopKFromComplexity:
    """Tests for dynamic_top_k_from_complexity mapping."""

    def test_complexity_1_maps_to_5(self):
        from proxy.app.slm_router import dynamic_top_k_from_complexity

        assert dynamic_top_k_from_complexity(1) == 5

    def test_complexity_5_maps_to_15(self):
        from proxy.app.slm_router import dynamic_top_k_from_complexity

        assert dynamic_top_k_from_complexity(5) == 15

    def test_complexity_10_maps_to_50(self):
        from proxy.app.slm_router import dynamic_top_k_from_complexity

        assert dynamic_top_k_from_complexity(10) == 50

    def test_out_of_range_uses_default(self):
        from proxy.app.slm_router import dynamic_top_k_from_complexity

        assert dynamic_top_k_from_complexity(0) == 50
        assert dynamic_top_k_from_complexity(11) == 50
        assert dynamic_top_k_from_complexity(100, max_default=30) == 30


class TestMultilingualIntentClassification:
    """F2: Language-aware intent classification for non-EN/RU queries."""

    def test_multilingual_intent_detects_german(self):
        """When query is in German, intent should be classified with simple heuristics."""
        from proxy.app.slm_router import classify_intent_multilingual

        intent, confidence = classify_intent_multilingual("Wie richte ich eine CI/CD Pipeline ein?")
        assert intent in (IntentType.FACTUAL, IntentType.PROCEDURAL)
        assert confidence >= 0.4

    def test_multilingual_intent_detects_french(self):
        from proxy.app.slm_router import classify_intent_multilingual

        intent, confidence = classify_intent_multilingual("Comment configurer un pipeline CI/CD?")
        assert intent in (IntentType.FACTUAL, IntentType.PROCEDURAL)
        assert confidence >= 0.4

    def test_multilingual_intent_detects_chinese(self):
        from proxy.app.slm_router import classify_intent_multilingual

        intent, confidence = classify_intent_multilingual("如何在GitLab中设置CI/CD管道？")
        assert intent in (IntentType.FACTUAL, IntentType.PROCEDURAL)
        assert confidence >= 0.4

    def test_multilingual_intent_delegates_english_to_main_classifier(self):
        from proxy.app.slm_router import classify_intent_multilingual

        intent, confidence = classify_intent_multilingual("How to set up CI/CD pipeline?")
        assert isinstance(intent, IntentType)
        assert confidence >= 0.3

    def test_multilingual_intent_delegates_russian_to_main_classifier(self):
        from proxy.app.slm_router import classify_intent_multilingual

        intent, confidence = classify_intent_multilingual("Как настроить CI/CD пайплайн?")
        assert isinstance(intent, IntentType)
        assert confidence >= 0.3

    def test_multilingual_intent_heuristic_german_greeting(self):
        from proxy.app.slm_router import classify_intent_multilingual

        intent, _ = classify_intent_multilingual("Hallo, wie geht es Ihnen?")
        assert intent == IntentType.GREETING

    def test_multilingual_intent_heuristic_french_greeting(self):
        from proxy.app.slm_router import classify_intent_multilingual

        intent, _ = classify_intent_multilingual("Bonjour, comment allez-vous?")
        assert intent == IntentType.GREETING

    def test_multilingual_intent_heuristic_chinese_greeting(self):
        from proxy.app.slm_router import classify_intent_multilingual

        intent, _ = classify_intent_multilingual("你好")
        assert intent == IntentType.GREETING
