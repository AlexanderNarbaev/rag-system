"""Tests for proxy/app/config.py configuration module."""

import importlib

import pytest

# Import config once (it's already loaded by other test modules)
import proxy.app.shared.config as config_module


class TestConfigDefaults:
  """Test that default values are set correctly on the config module."""
  
  def test_default_values (self):
    """Verify key defaults are set."""
    assert isinstance (config_module.LLM_MODEL_NAME, str)
    assert config_module.EMBEDDER_DEVICE == "cpu"
    assert config_module.MAX_CHUNKS_RETRIEVAL == 50
  
  def test_boolean_defaults_false (self):
    assert config_module.USE_REDIS is False
    assert config_module.USE_LANGGRAPH is False
    assert config_module.GRAPH_ENABLED is False


class TestEnvVarOverrides:
  """Test that environment variables override defaults by reloading config."""
  
  @pytest.fixture (autouse = True)
  def _restore_config (self):
    """Restore config module state after each test."""
    yield
    importlib.reload (config_module)
  
  def test_qdrant_port_set_via_monkeypatch (self, monkeypatch):
    monkeypatch.setenv ("QDRANT_PORT", "9999")
    importlib.reload (config_module)
    assert config_module.QDRANT_PORT == 9999
  
  def test_max_chunks_retrieval_override (self, monkeypatch):
    monkeypatch.setenv ("MAX_CHUNKS_RETRIEVAL", "100")
    importlib.reload (config_module)
    assert config_module.MAX_CHUNKS_RETRIEVAL == 100
  
  def test_reranker_max_length_override (self, monkeypatch):
    monkeypatch.setenv ("RERANKER_MAX_LENGTH", "1024")
    importlib.reload (config_module)
    assert config_module.RERANKER_MAX_LENGTH == 1024
  
  def test_request_timeout_override (self, monkeypatch):
    monkeypatch.setenv ("REQUEST_TIMEOUT", "60")
    importlib.reload (config_module)
    assert config_module.REQUEST_TIMEOUT == 60
  
  def test_use_redis_true_override (self, monkeypatch):
    monkeypatch.setenv ("USE_REDIS", "TRUE")
    importlib.reload (config_module)
    assert config_module.USE_REDIS is True
  
  def test_graph_enabled_true (self, monkeypatch):
    monkeypatch.setenv ("GRAPH_ENABLED", "true")
    importlib.reload (config_module)
    assert config_module.GRAPH_ENABLED is True
  
  def test_max_retries_override (self, monkeypatch):
    monkeypatch.setenv ("MAX_RETRIES", "5")
    importlib.reload (config_module)
    assert config_module.MAX_RETRIES == 5
  
  def test_collection_name_override (self, monkeypatch):
    monkeypatch.setenv ("COLLECTION_NAME", "test_coll")
    importlib.reload (config_module)
    assert config_module.COLLECTION_NAME == "test_coll"


class TestPrintConfig:
  """Test print_config function."""
  
  def test_runs_without_error (self, capsys):
    config_module.print_config ()
    captured = capsys.readouterr ()
    assert "RAG Proxy Configuration" in captured.out
  
  def test_print_config_masks_sensitive (self, capsys):
    config_module.print_config ()
    captured = capsys.readouterr ()
    assert "***" in captured.out  # sensitive keys are masked
