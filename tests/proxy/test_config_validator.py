# tests/proxy/test_config_validator.py
"""Tests for configuration validation."""

import os
from unittest.mock import patch

import pytest

from proxy.app.shared.config_validator import check_startup_health, validate_config


class TestValidateConfig:
  """Test configuration validation logic."""
  
  @patch.dict (os.environ, {"LLM_ENDPOINT": "http://localhost:8000/v1"})
  def test_valid_llm_endpoint (self):
    results = validate_config ()
    llm_results = [r for r in results if r.component == "LLM_ENDPOINT"]
    assert len (llm_results) == 1
    assert llm_results [0].status == "ok"
  
  @patch.dict (os.environ, {"LLM_ENDPOINT": ""})
  def test_missing_llm_endpoint (self):
    results = validate_config ()
    llm_results = [r for r in results if r.component == "LLM_ENDPOINT"]
    assert len (llm_results) == 1
    assert llm_results [0].status == "error"
  
  @patch.dict (os.environ, {"LLM_ENDPOINT": "ftp://invalid"})
  def test_invalid_llm_endpoint_scheme (self):
    results = validate_config ()
    llm_results = [r for r in results if r.component == "LLM_ENDPOINT"]
    assert len (llm_results) == 1
    assert llm_results [0].status == "error"
  
  @patch.dict (os.environ, {"USE_REDIS": "true", "REDIS_URL": ""})
  def test_redis_enabled_no_url (self):
    results = validate_config ()
    redis_results = [r for r in results if r.component == "REDIS"]
    assert len (redis_results) == 1
    assert redis_results [0].status == "warning"
  
  @patch.dict (os.environ, {"USE_REDIS": "true", "REDIS_URL": "redis://localhost:6379"})
  def test_redis_enabled_with_url (self):
    results = validate_config ()
    redis_results = [r for r in results if r.component == "REDIS"]
    assert len (redis_results) == 1
    assert redis_results [0].status == "ok"
  
  @patch.dict (os.environ, {"AUTH_ENABLED": "true", "JWT_SECRET_KEY": "change-me-in-production"})
  def test_auth_default_secret_warning (self):
    results = validate_config ()
    auth_results = [r for r in results if r.component == "AUTH"]
    assert len (auth_results) == 1
    assert auth_results [0].status == "warning"
  
  @patch.dict (os.environ, {"AUTH_ENABLED": "true", "JWT_SECRET_KEY": "my-super-secret-key-123"})
  def test_auth_strong_secret_ok (self):
    results = validate_config ()
    auth_results = [r for r in results if r.component == "AUTH"]
    assert len (auth_results) == 1
    assert auth_results [0].status == "ok"


class TestCheckStartupHealth:
  """Test startup health check."""
  
  @patch.dict (os.environ, {"LLM_ENDPOINT": "http://localhost:8000/v1"})
  def test_can_start_with_valid_config (self):
    can_start, results = check_startup_health ()
    assert can_start is True
    assert len (results) > 0
  
  @patch.dict (os.environ, {"LLM_ENDPOINT": ""})
  def test_cannot_start_without_llm (self):
    can_start, results = check_startup_health ()
    assert can_start is False
    errors = [r for r in results if r.status == "error"]
    assert len (errors) > 0
