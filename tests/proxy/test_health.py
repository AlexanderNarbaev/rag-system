# tests/proxy/test_health.py
"""Tests for health check endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client ():
  """Create a TestClient for health endpoints."""
  from fastapi import FastAPI
  
  from proxy.app.api.health import router
  
  app = FastAPI ()
  app.include_router (router)
  return TestClient (app)


class TestHealthLive:
  """Test /v1/health/live endpoint."""
  
  def test_live_returns_200 (self, client):
    response = client.get ("/v1/health/live")
    assert response.status_code == 200
    data = response.json ()
    assert data ["status"] == "alive"
    assert "timestamp" in data


class TestHealthReady:
  """Test /v1/health/ready endpoint."""
  
  @patch ("proxy.app.api.health._check_llm", return_value = ("ok", {}))
  @patch ("proxy.app.api.health._check_qdrant", return_value = ("ok", {"collections": 3}))
  def test_ready_when_all_ok (self, mock_qdrant, mock_llm, client):
    response = client.get ("/v1/health/ready")
    assert response.status_code == 200
    data = response.json ()
    assert data ["status"] == "ready"
    assert data ["components"] ["qdrant"] == "ok"
    assert data ["components"] ["llm"] == "ok"
  
  @patch ("proxy.app.api.health._check_llm", return_value = ("error: timeout", {}))
  @patch ("proxy.app.api.health._check_qdrant", return_value = ("ok", {}))
  def test_not_ready_when_llm_down (self, mock_qdrant, mock_llm, client):
    response = client.get ("/v1/health/ready")
    assert response.status_code == 503
    data = response.json ()
    assert data ["status"] == "not_ready"
    assert data ["components"] ["llm"] == "error: timeout"
  
  @patch ("proxy.app.api.health._check_llm", return_value = ("ok", {}))
  @patch ("proxy.app.api.health._check_qdrant", return_value = ("unavailable", {}))
  def test_not_ready_when_qdrant_down (self, mock_qdrant, mock_llm, client):
    response = client.get ("/v1/health/ready")
    assert response.status_code == 503
    data = response.json ()
    assert data ["status"] == "not_ready"
    assert data ["components"] ["qdrant"] == "unavailable"


class TestHealthFull:
  """Test /v1/health endpoint."""
  
  @patch ("proxy.app.api.health._check_kb_manager", return_value = ("ok", {"knowledge_bases": 2}))
  @patch ("proxy.app.api.health._check_llm", return_value = ("ok", {"endpoint": "http://llm:8000"}))
  @patch ("proxy.app.api.health._check_qdrant", return_value = ("ok", {"collections": 5}))
  def test_health_all_ok (self, mock_qdrant, mock_llm, mock_kb, client):
    response = client.get ("/v1/health")
    assert response.status_code == 200
    data = response.json ()
    assert data ["status"] == "ok"
    assert data ["components"] ["qdrant"] == "ok"
    assert data ["components"] ["llm"] == "ok"
    assert data ["components"] ["kb_manager"] == "ok"
    assert data ["components"] ["qdrant_info"] ["collections"] == 5
  
  @patch ("proxy.app.api.health._check_kb_manager", return_value = ("ok", {}))
  @patch ("proxy.app.api.health._check_llm", return_value = ("error: connection refused", {}))
  @patch ("proxy.app.api.health._check_qdrant", return_value = ("ok", {}))
  def test_health_degraded_when_llm_down (self, mock_qdrant, mock_llm, mock_kb, client):
    response = client.get ("/v1/health")
    assert response.status_code == 503
    data = response.json ()
    assert data ["status"] == "degraded"
    assert data ["components"] ["llm"] == "error: connection refused"
