# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/warmup.py - model warm-up with graceful degradation."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_modules_to_mock = [
    "qdrant_client", "qdrant_client.http", "qdrant_client.http.models", "sentence_transformers", "langgraph",
    "langgraph.graph", "langgraph.checkpoint", "neo4j", "redis", "redis.asyncio", "tiktoken",
]

for mod in _modules_to_mock:
  if mod not in sys.modules:
    sys.modules [mod] = MagicMock ()

from proxy.app.shared.warmup import (
  WARMUP_DOC, WARMUP_QUERY, WARMUP_TEXT, warmup_all, warmup_embedder, warmup_llm, warmup_reranker,
)


class TestWarmupEmbedder:
  """Tests for embedder warm-up."""
  
  @pytest.mark.asyncio
  async def test_returns_true_on_success (self):
    with patch ("proxy.app.core.retrieval.hybrid_search", return_value = []) as mock_search:
      result = await warmup_embedder ()
      assert result is True
      mock_search.assert_called_once ()
  
  @pytest.mark.asyncio
  async def test_returns_false_on_failure (self):
    with patch ("proxy.app.core.retrieval.hybrid_search", side_effect = RuntimeError ("No GPU")) as mock_search:
      result = await warmup_embedder ()
      assert result is False
      mock_search.assert_called_once ()
  
  @pytest.mark.asyncio
  async def test_import_failure_graceful (self):
    with patch ("proxy.app.core.retrieval.hybrid_search", side_effect = ImportError ()):
      result = await warmup_embedder ()
      assert result is False


class TestWarmupReranker:
  """Tests for reranker warm-up."""
  
  @pytest.mark.asyncio
  async def test_returns_true_on_success (self):
    with patch ("proxy.app.core.rerank.rerank_chunks", return_value = [0]) as mock_rerank:
      result = await warmup_reranker ()
      assert result is True
      mock_rerank.assert_called_once ()
  
  @pytest.mark.asyncio
  async def test_returns_false_on_failure (self):
    with patch ("proxy.app.core.rerank.rerank_chunks", side_effect = RuntimeError ("OOM")):
      result = await warmup_reranker ()
      assert result is False
  
  @pytest.mark.asyncio
  async def test_passes_warmup_query_and_doc (self):
    with patch ("proxy.app.core.rerank.rerank_chunks") as mock_rerank:
      await warmup_reranker ()
      call_args = mock_rerank.call_args
      assert call_args [0] [0] == WARMUP_QUERY
      assert WARMUP_DOC in call_args [0] [1]


class TestWarmupLLM:
  """Tests for LLM warm-up."""
  
  @pytest.mark.asyncio
  async def test_returns_true_on_success (self):
    mock_completion = AsyncMock (return_value = "warm")
    with patch ("proxy.app.shared.warmup.LLM_ENDPOINT", "http://localhost:8000/v1"):
      with patch ("proxy.app.shared.warmup.LLM_MODEL_NAME", "test-model"):
        with patch ("proxy.app.llm.provider.non_stream_completion", mock_completion):
          result = await warmup_llm ()
          assert result is True
  
  @pytest.mark.asyncio
  async def test_returns_false_on_failure (self):
    mock_completion = AsyncMock (side_effect = Exception ("LLM down"))
    with patch ("proxy.app.shared.warmup.LLM_ENDPOINT", "http://localhost:8000/v1"):
      with patch ("proxy.app.shared.warmup.LLM_MODEL_NAME", "test-model"):
        with patch ("proxy.app.llm.provider.non_stream_completion", mock_completion):
          result = await warmup_llm ()
          assert result is False
  
  @pytest.mark.asyncio
  async def test_sends_minimal_tokens (self):
    mock_completion = AsyncMock (return_value = "ok")
    with patch ("proxy.app.shared.warmup.LLM_ENDPOINT", "http://localhost:8000/v1"):
      with patch ("proxy.app.shared.warmup.LLM_MODEL_NAME", "test-model"):
        with patch ("proxy.app.llm.provider.non_stream_completion", mock_completion) as mock:
          await warmup_llm ()
          call_args = mock.call_args
          assert call_args [1].get ("max_tokens") == 1
          assert call_args [1].get ("temperature") == 0.0
  
  @pytest.mark.asyncio
  async def test_skips_when_no_llm_configured (self):
    """When LLM_ENDPOINT or MODEL_NAME is empty, warmup should skip."""
    with patch ("proxy.app.shared.warmup.LLM_ENDPOINT", ""):
      with patch ("proxy.app.shared.warmup.LLM_MODEL_NAME", ""):
        result = await warmup_llm ()
        assert result is False


class TestWarmupAll:
  """Tests for warmup_all orchestration."""
  
  @pytest.mark.asyncio
  async def test_returns_disabled_when_warmup_disabled (self):
    with patch ("proxy.app.shared.warmup.WARMUP_ENABLED", False):
      result = await warmup_all ()
      assert result ["status"] == "disabled"
      assert result ["embedder"] is False
      assert result ["reranker"] is False
      assert result ["llm"] is False
  
  @pytest.mark.asyncio
  async def test_returns_ok_when_all_succeed (self):
    with patch ("proxy.app.shared.warmup.WARMUP_ENABLED", True):
      with patch ("proxy.app.shared.warmup.warmup_embedder", AsyncMock (return_value = True)):
        with patch ("proxy.app.shared.warmup.warmup_reranker", AsyncMock (return_value = True)):
          with patch ("proxy.app.shared.warmup.warmup_llm", AsyncMock (return_value = True)):
            result = await warmup_all ()
            assert result ["status"] == "ok"
            assert result ["embedder"] is True
            assert result ["reranker"] is True
            assert result ["llm"] is True
  
  @pytest.mark.asyncio
  async def test_returns_partial_when_one_fails (self):
    with patch ("proxy.app.shared.warmup.WARMUP_ENABLED", True):
      with patch ("proxy.app.shared.warmup.warmup_embedder", AsyncMock (return_value = True)):
        with patch ("proxy.app.shared.warmup.warmup_reranker", AsyncMock (return_value = False)):
          with patch ("proxy.app.shared.warmup.warmup_llm", AsyncMock (return_value = True)):
            result = await warmup_all ()
            assert result ["status"] == "partial"
            assert result ["embedder"] is True
            assert result ["reranker"] is False
            assert result ["llm"] is True
  
  @pytest.mark.asyncio
  async def test_handles_exceptions_as_false (self):
    with patch ("proxy.app.shared.warmup.WARMUP_ENABLED", True):
      with patch ("proxy.app.shared.warmup.warmup_embedder", AsyncMock (return_value = True)):
        with patch ("proxy.app.shared.warmup.warmup_reranker", AsyncMock (side_effect = Exception ("crash"))):
          with patch ("proxy.app.shared.warmup.warmup_llm", AsyncMock (return_value = True)):
            result = await warmup_all ()
            assert result ["reranker"] is False
            assert result ["status"] == "partial"


class TestWarmupConstants:
  """Tests for warmup constants."""
  
  def test_warmup_text_not_empty (self):
    assert len (WARMUP_TEXT) > 0
  
  def test_warmup_query_not_empty (self):
    assert len (WARMUP_QUERY) > 0
  
  def test_warmup_doc_not_empty (self):
    assert len (WARMUP_DOC) > 0


class TestWarmupConfig:
  """Tests for warmup configuration integration."""
  
  def test_config_defaults (self):
    from proxy.app.shared.config import WARMUP_ENABLED, WARMUP_ON_STARTUP
    
    assert isinstance (WARMUP_ENABLED, bool)
    assert isinstance (WARMUP_ON_STARTUP, bool)
  
  def test_config_env_overrides (self):
    import os
    from importlib import reload
    
    os.environ ["WARMUP_ENABLED"] = "false"
    os.environ ["WARMUP_ON_STARTUP"] = "false"
    
    import proxy.app.shared.config
    
    reload (proxy.app.shared.config)
    
    assert proxy.app.shared.config.WARMUP_ENABLED is False
    assert proxy.app.shared.config.WARMUP_ON_STARTUP is False
