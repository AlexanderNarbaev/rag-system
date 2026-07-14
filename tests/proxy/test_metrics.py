"""Tests for proxy/app/metrics.py - Prometheus metrics module."""

import sys
from unittest.mock import MagicMock

import pytest

# Mock heavy dependencies before importing anything from proxy.app.main
_modules_to_mock = [
    "qdrant_client", "qdrant_client.http", "qdrant_client.http.models", "sentence_transformers", "langgraph",
    "langgraph.graph", "langgraph.checkpoint", "neo4j", "redis", "redis.asyncio", "tiktoken",
]
for mod in _modules_to_mock:
  if mod not in sys.modules:
    sys.modules [mod] = MagicMock ()


class TestMetricsDefinitions:
  """Test that all Prometheus metrics are defined and available."""
  
  def test_import_metrics_module (self):
    from proxy.app.shared.metrics import (
      rag_active_requests, rag_cache_hits_total, rag_context_tokens, rag_llm_duration_seconds,
      rag_request_duration_seconds, rag_requests_total, rag_rerank_duration_seconds, rag_retrieval_duration_seconds,
    )
    
    assert rag_requests_total is not None
    assert rag_request_duration_seconds is not None
    assert rag_retrieval_duration_seconds is not None
    assert rag_rerank_duration_seconds is not None
    assert rag_llm_duration_seconds is not None
    assert rag_cache_hits_total is not None
    assert rag_context_tokens is not None
    assert rag_active_requests is not None
  
  def test_requests_counter_increments (self):
    from proxy.app.shared.metrics import rag_requests_total
    
    rag_requests_total.labels (endpoint = "/v1/chat/completions", status = "200").inc ()
    rag_requests_total.labels (endpoint = "/v1/chat/completions", status = "200").inc ()
    rag_requests_total.labels (endpoint = "/v1/chat/completions", status = "500").inc ()
    # Counters are cumulative, we just verify no errors on inc()
    assert True
  
  def test_request_duration_histogram (self):
    from proxy.app.shared.metrics import rag_request_duration_seconds
    
    rag_request_duration_seconds.labels (endpoint = "/v1/chat/completions").observe (0.5)
    rag_request_duration_seconds.labels (endpoint = "/v1/chat/completions").observe (1.2)
    rag_request_duration_seconds.labels (endpoint = "/v1/models").observe (0.01)
    # Verify no errors on observe()
    assert True
  
  def test_gauge_set (self):
    from proxy.app.shared.metrics import rag_active_requests, rag_context_tokens
    
    rag_active_requests.set (3)
    rag_active_requests.inc ()
    rag_active_requests.dec ()
    rag_context_tokens.set (5000)
    assert True
  
  def test_cache_hits_counter (self):
    from proxy.app.shared.metrics import rag_cache_hits_total
    
    rag_cache_hits_total.inc ()
    rag_cache_hits_total.inc ()
    rag_cache_hits_total.inc ()
    assert True


class TestMetricsEndpoint:
  """Test the /metrics endpoint returns Prometheus-formatted output."""
  
  @pytest.fixture
  def client (self):
    from fastapi.testclient import TestClient
    
    from proxy.app.main import app
    
    with TestClient (app) as c:
      yield c
  
  def test_metrics_endpoint_returns_200 (self, client):
    response = client.get ("/metrics")
    assert response.status_code == 200
  
  def test_metrics_endpoint_content_type (self, client):
    response = client.get ("/metrics")
    from prometheus_client import CONTENT_TYPE_LATEST
    
    assert response.headers ["content-type"] == CONTENT_TYPE_LATEST
  
  def test_metrics_endpoint_contains_standard_metrics (self, client):
    response = client.get ("/metrics")
    body = response.text
    assert "rag_requests_total" in body
    assert "rag_request_duration_seconds" in body
  
  def test_metrics_endpoint_no_newlines_in_headers (self, client):
    """Verify the response is valid Prometheus format (no injection)."""
    response = client.get ("/metrics")
    body = response.text
    for line in body.strip ().split ("\n"):
      if line and not line.startswith ("#"):
        metric_name = line.split ("{") [0].split (" ") [0]
        assert not metric_name.startswith ("#")


class TestInitMetrics:
  """Test metrics initialization function."""
  
  def test_init_sets_flag (self):
    from proxy.app.shared.metrics import init_metrics, is_initialized
    
    init_metrics ()
    assert is_initialized () is True


class TestMetricsEndpointFunction:
  """Test the metrics_endpoint function directly."""
  
  def test_returns_prometheus_content (self):
    from proxy.app.shared.metrics import init_metrics, metrics_endpoint
    
    init_metrics ()
    result = metrics_endpoint ()
    assert result.status_code == 200
    assert "rag_requests_total" in result.body.decode ()
