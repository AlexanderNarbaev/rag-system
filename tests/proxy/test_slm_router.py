# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/slm_router.py - SLM routing with mocked _call_slm_sync."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from proxy.app.llm.slm import (
  IntentType, _call_slm_sync, classify_intent, decompose_query, extract_entities_slm, needs_retrieval,
  rewrite_query_slm, should_use_graph,
)


class TestCallSlmSync:
  """Tests for _call_slm_sync behavior."""
  
  def test_returns_empty_when_not_configured (self):
    with patch ("proxy.app.llm.slm.SLM_ENDPOINT", ""):
      result = _call_slm_sync ("some prompt")
      assert result == ""
  
  def test_sends_request_when_configured (self):
    mock_response = MagicMock ()
    mock_response.json.return_value = {"choices": [{"message": {"content": " factual"}}]}
    mock_response.raise_for_status = MagicMock ()
    
    with (
      patch ("proxy.app.llm.slm.SLM_ENDPOINT", "http://slm:8080/v1"), patch ("requests.post",
                                                                             return_value = mock_response), ):
      result = _call_slm_sync ("classify this")
      assert result == "factual"
  
  def test_handles_request_exception (self):
    with (
      patch ("proxy.app.llm.slm.SLM_ENDPOINT", "http://slm:8080/v1"), patch ("requests.post",
                                                                             side_effect = Exception ("timeout")), ):
      result = _call_slm_sync ("prompt")
      assert result == ""
  
  def test_includes_auth_header (self):
    mock_response = MagicMock ()
    mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_response.raise_for_status = MagicMock ()
    
    with (
      patch ("proxy.app.llm.slm.SLM_ENDPOINT", "http://slm:8080/v1"), patch ("proxy.app.llm.slm.SLM_API_KEY",
                                                                             "secret-key"), patch ("requests.post",
                                                                                                   return_value =
                                                                                                   mock_response) as
    mock_post, ):
      _call_slm_sync ("prompt")
      call_headers = mock_post.call_args [1] ["headers"]
      assert "Authorization" in call_headers
      assert "secret-key" in call_headers ["Authorization"]


class TestClassifyIntent:
  """Tests for classify_intent."""
  
  def test_factual_intent (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "factual"):
      intent, confidence = classify_intent ("What is Kubernetes?")
      assert intent == IntentType.FACTUAL
      assert confidence == 0.8
  
  def test_procedural_intent (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "procedural"):
      intent, _ = classify_intent ("How to set up CI/CD?")
      assert intent == IntentType.PROCEDURAL
  
  def test_comparison_intent (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "comparison"):
      intent, _ = classify_intent ("Compare GitLab vs GitHub")
      assert intent == IntentType.COMPARISON
  
  def test_summarize_intent (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "summarize"):
      intent, _ = classify_intent ("Summarize this document")
      assert intent == IntentType.SUMMARIZATION
  
  def test_greeting_intent (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "greeting"):
      intent, _ = classify_intent ("Hello there!")
      assert intent == IntentType.GREETING
  
  def test_unknown_when_slm_fails (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "nonsense"):
      intent, confidence = classify_intent ("blah")
      assert intent == IntentType.UNKNOWN
      assert confidence == 0.5
  
  def test_unknown_when_slm_empty (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = ""):
      intent, _ = classify_intent ("anything")
      assert intent == IntentType.UNKNOWN


class TestDecomposeQuery:
  """Tests for decompose_query."""
  
  def test_valid_json_response (self):
    response = json.dumps (["sub1", "sub2", "sub3"])
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = response):
      result = decompose_query ("complex query", max_subqueries = 3)
      assert result == ["sub1", "sub2", "sub3"]
  
  def test_truncates_to_max (self):
    response = json.dumps (["a", "b", "c", "d"])
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = response):
      result = decompose_query ("q", max_subqueries = 2)
      assert result == ["a", "b"]
  
  def test_fallback_on_invalid_json (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = 'not json but "extracted" and "more"'):
      result = decompose_query ("q")
      assert "extracted" in result
      assert "more" in result
  
  def test_fallback_on_non_list (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = '{"a": 1}'):
      result = decompose_query ("q")
      assert result == ["q"]  # fallback to original
  
  def test_slm_empty_fallback (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = ""):
      result = decompose_query ("original query")
      assert result == ["original query"]


class TestNeedsRetrieval:
  """Tests for needs_retrieval function."""
  
  def test_factual_needs_retrieval (self):
    assert needs_retrieval (IntentType.FACTUAL) is True
  
  def test_procedural_needs_retrieval (self):
    assert needs_retrieval (IntentType.PROCEDURAL) is True
  
  def test_comparison_needs_retrieval (self):
    assert needs_retrieval (IntentType.COMPARISON) is True
  
  def test_summarization_needs_retrieval (self):
    assert needs_retrieval (IntentType.SUMMARIZATION) is True
  
  def test_greeting_no_retrieval (self):
    assert needs_retrieval (IntentType.GREETING) is False
  
  def test_unknown_no_retrieval (self):
    assert needs_retrieval (IntentType.UNKNOWN) is False


class TestRewriteQuerySlm:
  """Tests for rewrite_query_slm."""
  
  def test_rewrite_success (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "CI/CD pipeline setup guide"):
      result = rewrite_query_slm ("How to set up CI/CD?")
      assert result == "CI/CD pipeline setup guide"
  
  def test_fallback_to_original (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = ""):
      result = rewrite_query_slm ("original question")
      assert result == "original question"


class TestExtractEntitiesSlm:
  """Tests for extract_entities_slm."""
  
  def test_extracts_entities_from_json (self):
    response = json.dumps (["GitLab", "CI/CD", "PROJ-123"])
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = response):
      result = extract_entities_slm ("How to use GitLab CI/CD PROJ-123?")
      assert result == ["GitLab", "CI/CD", "PROJ-123"]
  
  def test_regex_fallback_on_bad_json (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "not valid json"):
      result = extract_entities_slm ("Use GitLab and Docker")
      assert len (result) > 0
  
  def test_empty_when_slm_fails_and_no_caps (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = "bad"):
      result = extract_entities_slm ("all lowercase words only")
      assert result == []
  
  def test_non_list_json_returns_empty (self):
    with patch ("proxy.app.llm.slm._call_slm_sync", return_value = '{"key": "value"}'):
      result = extract_entities_slm ("query")
      assert result == []


class TestShouldUseGraph:
  """Tests for should_use_graph function."""
  
  def test_comparison_uses_graph (self):
    assert should_use_graph (IntentType.COMPARISON, "compare x and y") is True
  
  def test_relation_words_trigger_graph (self):
    assert should_use_graph (IntentType.FACTUAL, "как связан проект А и Б") is True
    assert should_use_graph (IntentType.FACTUAL, "кто использует Docker?") is True
  
  def test_factual_without_relation_no_graph (self):
    assert should_use_graph (IntentType.FACTUAL, "What is Kubernetes?") is False
  
  def test_procedural_no_graph (self):
    assert should_use_graph (IntentType.PROCEDURAL, "How to install Docker?") is False


class TestScoreQueryComplexity:
  """Tests for score_query_complexity heuristic."""
  
  def test_short_query_low_complexity (self):
    from proxy.app.llm.slm import score_query_complexity
    
    score = score_query_complexity ("Hello")
    assert 1 <= score <= 3
  
  def test_long_query_high_complexity (self):
    from proxy.app.llm.slm import score_query_complexity
    
    query = ("Please explain how everything works in great detail including all the steps and configurations that need "
             "to be set up correctly")
    score = score_query_complexity (query)
    assert score >= 5
  
  def test_comparison_query_high_complexity (self):
    from proxy.app.llm.slm import score_query_complexity
    
    with patch ("proxy.app.llm.slm.classify_intent", return_value = (IntentType.COMPARISON, 0.9)):
      score = score_query_complexity ("Compare Kubernetes vs Docker Swarm for production")
      assert score >= 7
  
  def test_procedural_query_medium_complexity (self):
    from proxy.app.llm.slm import score_query_complexity
    
    with patch ("proxy.app.llm.slm.classify_intent", return_value = (IntentType.PROCEDURAL, 0.9)):
      score = score_query_complexity ("How to set up CI/CD pipeline?")
      assert score >= 5
  
  def test_returns_valid_range (self):
    from proxy.app.llm.slm import score_query_complexity
    
    for query in ["Hi", "What is RAG?", "How to deploy and configure the entire system with all components"]:
      score = score_query_complexity (query)
      assert 1 <= score <= 10, f"query='{query}' score={score}"
  
  def test_falls_back_on_classify_error (self):
    from proxy.app.llm.slm import score_query_complexity
    
    with patch ("proxy.app.llm.slm.classify_intent", side_effect = Exception ("no SLM")):
      score = score_query_complexity ("test query")
      assert 1 <= score <= 10
  
  def test_multi_question_increases_complexity (self):
    from proxy.app.llm.slm import score_query_complexity
    
    single_score = score_query_complexity ("What is Docker?")
    multi_score = score_query_complexity ("What is Docker? How does it work? Why is it useful?")
    assert multi_score >= single_score


class TestDynamicTopKFromComplexity:
  """Tests for dynamic_top_k_from_complexity mapping."""
  
  def test_complexity_1_maps_to_5 (self):
    from proxy.app.llm.slm import dynamic_top_k_from_complexity
    
    assert dynamic_top_k_from_complexity (1) == 5
  
  def test_complexity_5_maps_to_15 (self):
    from proxy.app.llm.slm import dynamic_top_k_from_complexity
    
    assert dynamic_top_k_from_complexity (5) == 15
  
  def test_complexity_10_maps_to_50 (self):
    from proxy.app.llm.slm import dynamic_top_k_from_complexity
    
    assert dynamic_top_k_from_complexity (10) == 50
  
  def test_out_of_range_uses_default (self):
    from proxy.app.llm.slm import dynamic_top_k_from_complexity
    
    assert dynamic_top_k_from_complexity (0) == 50
    assert dynamic_top_k_from_complexity (11) == 50
    assert dynamic_top_k_from_complexity (100, max_default = 30) == 30


class TestMultilingualIntentClassification:
  """F2: Language-aware intent classification for non-EN/RU queries."""
  
  def test_multilingual_intent_detects_german (self):
    """When query is in German, intent should be classified with simple heuristics."""
    from proxy.app.llm.slm import classify_intent_multilingual
    
    intent, confidence = classify_intent_multilingual ("Wie richte ich eine CI/CD Pipeline ein?")
    assert intent in (IntentType.FACTUAL, IntentType.PROCEDURAL)
    assert confidence >= 0.4
  
  def test_multilingual_intent_detects_french (self):
    from proxy.app.llm.slm import classify_intent_multilingual
    
    intent, confidence = classify_intent_multilingual ("Comment configurer un pipeline CI/CD?")
    assert intent in (IntentType.FACTUAL, IntentType.PROCEDURAL)
    assert confidence >= 0.4
  
  def test_multilingual_intent_detects_chinese (self):
    from proxy.app.llm.slm import classify_intent_multilingual
    
    intent, confidence = classify_intent_multilingual ("如何在GitLab中设置CI/CD管道？")
    assert intent in (IntentType.FACTUAL, IntentType.PROCEDURAL)
    assert confidence >= 0.4
  
  def test_multilingual_intent_delegates_english_to_main_classifier (self):
    from proxy.app.llm.slm import classify_intent_multilingual
    
    intent, confidence = classify_intent_multilingual ("How to set up CI/CD pipeline?")
    assert isinstance (intent, IntentType)
    assert confidence >= 0.3
  
  def test_multilingual_intent_delegates_russian_to_main_classifier (self):
    from proxy.app.llm.slm import classify_intent_multilingual
    
    intent, confidence = classify_intent_multilingual ("Как настроить CI/CD пайплайн?")
    assert isinstance (intent, IntentType)
    assert confidence >= 0.3
  
  def test_multilingual_intent_heuristic_german_greeting (self):
    from proxy.app.llm.slm import classify_intent_multilingual
    
    intent, _ = classify_intent_multilingual ("Hallo, wie geht es Ihnen?")
    assert intent == IntentType.GREETING
  
  def test_multilingual_intent_heuristic_french_greeting (self):
    from proxy.app.llm.slm import classify_intent_multilingual
    
    intent, _ = classify_intent_multilingual ("Bonjour, comment allez-vous?")
    assert intent == IntentType.GREETING
  
  def test_multilingual_intent_heuristic_chinese_greeting (self):
    from proxy.app.llm.slm import classify_intent_multilingual
    
    intent, _ = classify_intent_multilingual ("你好")
    assert intent == IntentType.GREETING


# ── LocalSLMClient tests ──

# Patch path for requests inside the slm_router module.
_SLM_REQUESTS = "proxy.app.llm.slm.requests"


class TestLocalSLMClientGenerate:
  """Tests for LocalSLMClient.generate() with mocked subprocess and network."""
  
  @staticmethod
  def _make_health_side_effect (*, fail_count: int = 1):
    """Return a side_effect for requests.get that fails N times then succeeds."""
    call_count = 0
    
    def _side_effect (*args, **kwargs):
      nonlocal call_count
      call_count += 1
      if call_count <= fail_count:
        raise requests.exceptions.ConnectionError ("not ready")
      resp = MagicMock ()
      resp.status_code = 200
      return resp
    
    return _side_effect
  
  @pytest.fixture
  def mock_server_startup (self):
    """Simulate a server that starts after a brief health check delay."""
    with (
      patch ("subprocess.Popen") as mock_popen, patch (_SLM_REQUESTS + ".get") as mock_get, patch (
        _SLM_REQUESTS + ".post") as mock_post, ):
      # Simulate a running process (poll returns None = still running).
      mock_proc = MagicMock ()
      mock_proc.poll.return_value = None
      mock_popen.return_value = mock_proc
      
      # Health check fails twice (first check + double-check inside lock),
      # then succeeds on the third call (after Popen starts the server).
      mock_get.side_effect = self._make_health_side_effect (fail_count = 2)
      
      # Generate returns valid JSON.
      mock_gen = MagicMock ()
      mock_gen.json.return_value = {
          "choices": [{"message": {"content": " factual"}}],
      }
      mock_gen.raise_for_status = MagicMock ()
      mock_post.return_value = mock_gen
      
      yield mock_popen, mock_get, mock_post, mock_proc
  
  @pytest.fixture
  def mock_already_running (self):
    """Simulate a server that is already running (health check passes)."""
    with (
      patch ("subprocess.Popen") as mock_popen, patch (_SLM_REQUESTS + ".get") as mock_get, patch (
        _SLM_REQUESTS + ".post") as mock_post, ):
      mock_proc = MagicMock ()
      mock_proc.poll.return_value = None
      mock_popen.return_value = mock_proc
      
      # Health check passes immediately (server already running).
      mock_health = MagicMock ()
      mock_health.status_code = 200
      mock_get.return_value = mock_health
      
      mock_gen = MagicMock ()
      mock_gen.json.return_value = {
          "choices": [{"message": {"content": " factual"}}],
      }
      mock_gen.raise_for_status = MagicMock ()
      mock_post.return_value = mock_gen
      
      yield mock_popen, mock_get, mock_post, mock_proc
  
  def test_generates_text (self, mock_already_running):
    """LocalSLMClient.generate() should return generated text."""
    from proxy.app.llm.slm import LocalSLMClient
    
    client = LocalSLMClient (binary = "/usr/bin/llama-server", model_path = "/models/slm.gguf", port = 18081, )
    result = client.generate ("classify this", max_tokens = 10, temperature = 0)
    assert result == "factual"
  
  def test_starts_server_on_first_call (self, mock_server_startup):
    """First generate() call should start the subprocess."""
    mock_popen, mock_get, mock_post, mock_proc = mock_server_startup
    
    from proxy.app.llm.slm import LocalSLMClient
    
    client = LocalSLMClient (binary = "/usr/bin/llama-server", model_path = "/models/slm.gguf", port = 18082, )
    client.generate ("hello")
    
    mock_popen.assert_called_once ()
    # Verify the correct CLI arguments.
    call_args = mock_popen.call_args [0] [0]
    assert "--port" in call_args
    assert "18082" in call_args
    assert "-m" in call_args
    assert "/models/slm.gguf" in call_args
  
  def test_reuses_running_server (self, mock_server_startup):
    """Second generate() call should not restart the server."""
    mock_popen, mock_get, mock_post, mock_proc = mock_server_startup
    
    from proxy.app.llm.slm import LocalSLMClient
    
    client = LocalSLMClient (binary = "/usr/bin/llama-server", model_path = "/models/slm.gguf", port = 18083, )
    client.generate ("first")
    client.generate ("second")
    
    # Popen should only have been called once (first call starts, second reuses).
    assert mock_popen.call_count == 1
  
  def test_handles_server_crash (self, mock_server_startup):
    """After the process dies, the next call should restart it."""
    mock_popen, mock_get, mock_post, mock_proc = mock_server_startup
    
    from proxy.app.llm.slm import LocalSLMClient
    
    client = LocalSLMClient (binary = "/usr/bin/llama-server", model_path = "/models/slm.gguf", port = 18084, )
    # First call — health fails once, then succeeds → server starts.
    client.generate ("first")
    assert mock_popen.call_count == 1
    
    # Simulate server crash: poll returns a non-None return code.
    mock_proc.poll.return_value = 1
    
    # Reset the health side effect so the restart loop works.
    # Need fail_count=2: first check + double-check before Popen.
    mock_get.side_effect = self._make_health_side_effect (fail_count = 2)
    
    # Next call should detect the dead process and restart.
    client.generate ("second")
    assert mock_popen.call_count == 2
  
  def test_handles_request_timeout (self):
    """When the HTTP request times out, returns empty string."""
    with (
      patch ("subprocess.Popen") as mock_popen, patch (_SLM_REQUESTS + ".get") as mock_get, patch (
        _SLM_REQUESTS + ".post", side_effect = requests.exceptions.Timeout), ):
      mock_proc = MagicMock ()
      mock_proc.poll.return_value = None
      mock_popen.return_value = mock_proc
      
      mock_health = MagicMock ()
      mock_health.status_code = 200
      mock_get.return_value = mock_health
      
      from proxy.app.llm.slm import LocalSLMClient
      
      client = LocalSLMClient (binary = "/usr/bin/llama-server", model_path = "/models/slm.gguf", port = 18085, )
      result = client.generate ("prompt")
      assert result == ""
  
  def test_handles_server_unavailable (self):
    """When the server never becomes healthy, generate returns empty."""
    with patch ("subprocess.Popen") as mock_popen, patch (_SLM_REQUESTS + ".get") as mock_get:
      mock_proc = MagicMock ()
      mock_proc.poll.return_value = None
      mock_popen.return_value = mock_proc
      
      # Health check always fails.
      mock_get.side_effect = requests.exceptions.ConnectionError
      
      from proxy.app.llm.slm import LocalSLMClient
      
      client = LocalSLMClient (binary = "/usr/bin/llama-server", model_path = "/models/slm.gguf", port = 18086,
          startup_timeout = 1,  # Short timeout for test speed.
      )
      result = client.generate ("prompt")
      assert result == ""
  
  def test_shutdown_terminates_process (self, mock_server_startup):
    """shutdown() should terminate the subprocess."""
    mock_popen, mock_get, mock_post, mock_proc = mock_server_startup
    
    from proxy.app.llm.slm import LocalSLMClient
    
    client = LocalSLMClient (binary = "/usr/bin/llama-server", model_path = "/models/slm.gguf", port = 18087, )
    client.generate ("test")  # Ensure process is started.
    client.shutdown ()
    
    mock_proc.terminate.assert_called_once ()
  
  def test_shutdown_idempotent (self, mock_server_startup):
    """Multiple shutdown() calls are safe."""
    mock_popen, mock_get, mock_post, mock_proc = mock_server_startup
    
    from proxy.app.llm.slm import LocalSLMClient
    
    client = LocalSLMClient (binary = "/usr/bin/llama-server", model_path = "/models/slm.gguf", port = 18088, )
    client.generate ("test")
    client.shutdown ()
    client.shutdown ()
    client.shutdown ()
    
    # terminate should only have been called once.
    mock_proc.terminate.assert_called_once ()


class TestCallSlmSyncLocalMode:
  """Tests for _call_slm_sync when SLM_LOCAL_ENABLED is True."""
  
  def test_routes_to_local_client_when_enabled (self):
    """When SLM_LOCAL_ENABLED=True, use LocalSLMClient."""
    mock_client = MagicMock ()
    mock_client.generate.return_value = "factual"
    
    with (
      patch ("proxy.app.llm.slm.SLM_LOCAL_ENABLED", True), patch ("proxy.app.llm.slm._get_local_slm_client",
                                                                  return_value = mock_client), ):
      result = _call_slm_sync ("classify this", max_tokens = 10, temperature = 0)
      assert result == "factual"
      mock_client.generate.assert_called_once_with ("classify this", max_tokens = 10, temperature = 0, )
  
  def test_returns_empty_when_no_model_path (self):
    """When SLM_LOCAL_ENABLED=True but no model path, returns empty."""
    with patch ("proxy.app.llm.slm.SLM_LOCAL_ENABLED", True), patch ("proxy.app.llm.slm.SLM_LOCAL_MODEL_PATH", ""):
      result = _call_slm_sync ("prompt")
      assert result == ""
  
  def test_falls_back_to_empty_on_local_error (self):
    """When the local client raises RuntimeError, returns empty."""
    mock_client = MagicMock ()
    mock_client.generate.side_effect = RuntimeError ("server crashed")
    
    with (
      patch ("proxy.app.llm.slm.SLM_LOCAL_ENABLED", True), patch ("proxy.app.llm.slm._get_local_slm_client",
                                                                  return_value = mock_client), ):
      result = _call_slm_sync ("prompt")
      assert result == ""


class TestGetLocalSlmClient:
  """Tests for the module-level _get_local_slm_client singleton factory."""
  
  def test_returns_none_without_model_path (self):
    """When SLM_LOCAL_MODEL_PATH is empty, returns None."""
    from proxy.app.llm.slm import _get_local_slm_client
    
    with patch ("proxy.app.llm.slm.SLM_LOCAL_MODEL_PATH", ""):
      # Reset the singleton before testing.
      with patch ("proxy.app.llm.slm._local_slm_client", None):
        client = _get_local_slm_client ()
        assert client is None
  
  def test_singleton_returns_same_instance (self):
    """Multiple calls return the same LocalSLMClient instance."""
    from proxy.app.llm.slm import _get_local_slm_client
    
    with patch ("proxy.app.llm.slm.SLM_LOCAL_MODEL_PATH", "/models/test.gguf"):
      with patch ("proxy.app.llm.slm._local_slm_client", None):
        client1 = _get_local_slm_client ()
        client2 = _get_local_slm_client ()
        assert client1 is client2
