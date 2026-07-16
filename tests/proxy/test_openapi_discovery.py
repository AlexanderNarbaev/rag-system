# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/tools/openapi/discovery.py — OpenAPI spec discovery."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.tools.definition import ToolVisibility
from proxy.app.tools.openapi.discovery import (
    DiscoveryMode,
    OpenAPIDiscovery,
    OpenAPIProvider,
    _parse_json,
    _parse_yaml,
)


SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "tags": ["pets"],
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}, "description": "Max results"}
                ],
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "tags": ["pets"],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "Pet name"},
                                    "age": {"type": "integer", "description": "Pet age"},
                                },
                                "required": ["name"],
                            }
                        }
                    }
                },
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a pet by ID",
                "tags": ["pets"],
                "parameters": [
                    {"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
            },
            "delete": {
                "operationId": "deletePet",
                "summary": "Delete a pet",
                "tags": ["admin"],
            },
        },
    },
}


class TestParseHelpers:
    """Tests for _parse_json and _parse_yaml."""

    def test_parse_json_valid(self):
        result = _parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_invalid_type(self):
        with pytest.raises(ValueError, match="Expected JSON object"):
            _parse_json("[1, 2, 3]")

    def test_parse_yaml_valid(self):
        try:
            result = _parse_yaml("key: value\nlist:\n  - a\n  - b")
            assert result["key"] == "value"
            assert result["list"] == ["a", "b"]
        except ImportError:
            pytest.skip("PyYAML not installed")

    def test_parse_yaml_invalid_type(self):
        try:
            with pytest.raises(ValueError, match="Expected YAML mapping"):
                _parse_yaml("- a\n- b")
        except ImportError:
            pytest.skip("PyYAML not installed")


class TestOpenAPIDiscovery:
    """Tests for OpenAPIDiscovery.discover."""

    def test_discover_all_endpoints(self):
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(SAMPLE_SPEC)
        names = {t.name for t in tools}
        assert "listPets" in names
        assert "createPet" in names
        assert "getPet" in names
        assert "deletePet" in names

    def test_discover_with_include_tags(self):
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(SAMPLE_SPEC, include_tags=["pets"])
        names = {t.name for t in tools}
        assert "listPets" in names
        assert "deletePet" not in names  # tag is "admin"

    def test_discover_with_exclude_tags(self):
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(SAMPLE_SPEC, exclude_tags=["admin"])
        names = {t.name for t in tools}
        assert "deletePet" not in names

    def test_discover_llm_driven_mode(self):
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(SAMPLE_SPEC, mode=DiscoveryMode.LLM_DRIVEN)
        assert tools == []

    def test_discover_from_spec_alias(self):
        discovery = OpenAPIDiscovery()
        tools = discovery.discover_from_spec(SAMPLE_SPEC)
        assert len(tools) > 0

    def test_discover_from_file_json(self, tmp_path):
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(SAMPLE_SPEC))
        discovery = OpenAPIDiscovery()
        tools = discovery.discover_from_file(str(spec_file))
        assert len(tools) > 0

    def test_discover_from_file_yaml(self, tmp_path):
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        spec_file = tmp_path / "spec.yaml"
        spec_file.write_text(yaml.dump(SAMPLE_SPEC))
        discovery = OpenAPIDiscovery()
        tools = discovery.discover_from_file(str(spec_file))
        assert len(tools) > 0

    def test_extract_base_url_openapi3(self):
        discovery = OpenAPIDiscovery()
        url = discovery._extract_base_url(SAMPLE_SPEC, "")
        assert url == "https://api.example.com"

    def test_extract_base_url_swagger2(self):
        spec = {
            "swagger": "2.0",
            "schemes": ["https"],
            "host": "api.example.com",
            "basePath": "/v1",
        }
        discovery = OpenAPIDiscovery()
        url = discovery._extract_base_url(spec, "")
        assert url == "https://api.example.com/v1"

    def test_extract_base_url_fallback(self):
        discovery = OpenAPIDiscovery()
        url = discovery._extract_base_url({}, "https://fallback.com")
        assert url == "https://fallback.com"

    def test_extract_base_url_no_servers(self):
        spec = {"openapi": "3.0.0"}
        discovery = OpenAPIDiscovery()
        url = discovery._extract_base_url(spec, "fallback")
        assert url == "fallback"

    def test_discover_empty_spec(self):
        discovery = OpenAPIDiscovery()
        tools = discovery.discover({})
        assert tools == []

    def test_discover_skips_non_dict_path_items(self):
        spec = {"paths": {"/bad": "not a dict"}}
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(spec)
        assert tools == []

    def test_tool_category_assignment(self):
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(SAMPLE_SPEC)
        get_tools = [t for t in tools if t.category == "search"]
        action_tools = [t for t in tools if t.category == "action"]
        assert len(get_tools) >= 2  # listPets, getPet
        assert len(action_tools) >= 2  # createPet, deletePet

    def test_default_visibility(self):
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(SAMPLE_SPEC, default_visibility=ToolVisibility.ADMIN)
        assert all(t.visibility == ToolVisibility.ADMIN for t in tools)


class TestOpenAPIProvider:
    """Tests for OpenAPIProvider."""

    def test_provider_name(self):
        provider = OpenAPIProvider()
        assert provider.provider_name == "openapi"

    @pytest.mark.asyncio
    async def test_discover_no_specs(self):
        with patch.object(OpenAPIProvider, "_get_spec_configs", return_value=[]):
            provider = OpenAPIProvider()
            tools = await provider.discover()
            assert tools == []

    @pytest.mark.asyncio
    async def test_validate_no_specs(self):
        with patch.object(OpenAPIProvider, "_get_spec_configs", return_value=[]):
            provider = OpenAPIProvider()
            issues = await provider.validate()
            assert issues == []

    @pytest.mark.asyncio
    async def test_validate_missing_file(self):
        configs = [{"name": "test", "file": "/nonexistent/spec.json"}]
        with patch.object(OpenAPIProvider, "_get_spec_configs", return_value=configs):
            provider = OpenAPIProvider()
            issues = await provider.validate()
            assert len(issues) == 1
            assert "not found" in issues[0]

    @pytest.mark.asyncio
    async def test_validate_no_url_or_file(self):
        configs = [{"name": "test"}]
        with patch.object(OpenAPIProvider, "_get_spec_configs", return_value=configs):
            provider = OpenAPIProvider()
            issues = await provider.validate()
            assert len(issues) == 1
            assert "neither url nor file" in issues[0]

    @pytest.mark.asyncio
    async def test_reload_calls_discover(self):
        with patch.object(OpenAPIProvider, "_get_spec_configs", return_value=[]):
            provider = OpenAPIProvider()
            tools = await provider.reload()
            assert tools == []

    def test_get_spec_configs_import_error(self):
        with patch.dict("sys.modules", {"proxy.app.shared.config": None}):
            configs = OpenAPIProvider._get_spec_configs()
            assert configs == []
