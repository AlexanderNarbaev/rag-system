# tests/proxy/test_config_validator.py
"""Tests for configuration validation."""

import os
from unittest.mock import patch

from proxy.app.shared.config_validator import check_startup_health, validate_config


class TestValidateConfig:
    """Test configuration validation logic."""

    @patch.dict(os.environ, {"LLM_ENDPOINT": "http://localhost:8000/v1"})
    def test_valid_llm_endpoint(self):
        results = validate_config()
        llm_results = [r for r in results if r.component == "LLM_ENDPOINT"]
        assert len(llm_results) == 1
        assert llm_results[0].status == "ok"

    @patch.dict(os.environ, {"LLM_ENDPOINT": ""})
    def test_missing_llm_endpoint(self):
        results = validate_config()
        llm_results = [r for r in results if r.component == "LLM_ENDPOINT"]
        assert len(llm_results) == 1
        assert llm_results[0].status == "error"

    @patch.dict(os.environ, {"LLM_ENDPOINT": "ftp://invalid"})
    def test_invalid_llm_endpoint_scheme(self):
        results = validate_config()
        llm_results = [r for r in results if r.component == "LLM_ENDPOINT"]
        assert len(llm_results) == 1
        assert llm_results[0].status == "error"

    @patch.dict(os.environ, {"USE_REDIS": "true", "REDIS_URL": ""})
    def test_redis_enabled_no_url(self):
        results = validate_config()
        redis_results = [r for r in results if r.component == "REDIS"]
        assert len(redis_results) == 1
        assert redis_results[0].status == "warning"

    @patch.dict(os.environ, {"USE_REDIS": "true", "REDIS_URL": "redis://localhost:6379"})
    def test_redis_enabled_with_url(self):
        results = validate_config()
        redis_results = [r for r in results if r.component == "REDIS"]
        assert len(redis_results) == 1
        assert redis_results[0].status == "ok"

    @patch.dict(os.environ, {"AUTH_ENABLED": "true", "JWT_SECRET_KEY": "change-me-in-production"})
    def test_auth_default_secret_warning(self):
        results = validate_config()
        auth_results = [r for r in results if r.component == "AUTH"]
        assert len(auth_results) == 1
        assert auth_results[0].status == "warning"

    @patch.dict(os.environ, {"AUTH_ENABLED": "true", "JWT_SECRET_KEY": "my-super-secret-key-123"})
    def test_auth_strong_secret_ok(self):
        results = validate_config()
        auth_results = [r for r in results if r.component == "AUTH"]
        assert len(auth_results) == 1
        assert auth_results[0].status == "ok"


class TestCheckStartupHealth:
    """Test startup health check."""

    @patch.dict(os.environ, {"LLM_ENDPOINT": "http://localhost:8000/v1"})
    def test_can_start_with_valid_config(self):
        can_start, results = check_startup_health()
        assert can_start is True
        assert len(results) > 0

    @patch.dict(os.environ, {"LLM_ENDPOINT": ""})
    def test_cannot_start_without_llm(self):
        can_start, results = check_startup_health()
        assert can_start is False
        errors = [r for r in results if r.status == "error"]
        assert len(errors) > 0


class TestConfigValidatorEdgeCases:
    """Test config validator edge cases."""

    @patch.dict(os.environ, {"GRAPH_ENABLED": "true", "NEO4J_URI": ""})
    def test_graph_enabled_no_neo4j_uri(self):
        results = validate_config()
        neo4j_results = [r for r in results if r.component == "NEO4J"]
        assert len(neo4j_results) == 1
        assert neo4j_results[0].status == "warning"

    @patch.dict(os.environ, {"GRAPH_ENABLED": "true", "NEO4J_URI": "bolt://localhost:7687"})
    def test_graph_enabled_with_uri(self):
        results = validate_config()
        neo4j_results = [r for r in results if r.component == "NEO4J"]
        assert len(neo4j_results) == 1
        assert neo4j_results[0].status == "ok"

    @patch.dict(os.environ, {"GRAPH_ENABLED": "false"})
    def test_graph_disabled(self):
        results = validate_config()
        neo4j_results = [r for r in results if r.component == "NEO4J"]
        assert neo4j_results[0].status == "ok"
        assert "disabled" in neo4j_results[0].message.lower()

    @patch.dict(os.environ, {"USE_REDIS": "false"})
    def test_redis_disabled(self):
        results = validate_config()
        redis_results = [r for r in results if r.component == "REDIS"]
        assert redis_results[0].status == "ok"
        assert "disabled" in redis_results[0].message.lower()

    @patch.dict(os.environ, {"AUTH_ENABLED": "false"})
    def test_auth_disabled(self):
        results = validate_config()
        auth_results = [r for r in results if r.component == "AUTH"]
        assert auth_results[0].status == "ok"
        assert "disabled" in auth_results[0].message.lower()

    @patch.dict(os.environ, {"LANGGRAPH_ENABLED": "true"})
    def test_langgraph_component_present(self):
        results = validate_config()
        lg_results = [r for r in results if r.component == "LANGGRAPH"]
        assert len(lg_results) == 1
        assert lg_results[0].status == "ok"

    @patch.dict(os.environ, {"QDRANT_HOST": "qdrant.internal", "QDRANT_PORT": "6334"})
    def test_qdrant_custom_host(self):
        results = validate_config()
        qdrant_results = [r for r in results if r.component == "QDRANT"]
        assert len(qdrant_results) == 1
        assert qdrant_results[0].status == "ok"

    @patch.dict(os.environ, {"LLM_ENDPOINT": ""})
    def test_check_startup_with_warnings_only(self):
        can_start, results = check_startup_health()
        errors = [r for r in results if r.status == "error"]
        warnings = [r for r in results if r.status == "warning"]
        assert can_start is False
        assert len(errors) > 0
