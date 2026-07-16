"""Tests for proxy/app/tools/openapi/ — enhanced coverage for discovery and converter."""

import json
from unittest.mock import AsyncMock, patch

import pytest

PETSORE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "PetStore API", "version": "1.0.0"},
    "servers": [{"url": "https://petstore.example.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "tags": ["pets"],
                "parameters": [],
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "tags": ["pets"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {},
                            },
                        },
                    },
                },
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPetById",
                "summary": "Get a pet by ID",
                "tags": ["pets"],
                "parameters": [
                    {"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}},
                ],
            },
        },
    },
}

SWAGGER_2_0_SPEC = {
    "swagger": "2.0",
    "info": {"title": "Swagger API", "version": "1.0.0"},
    "host": "api.example.com",
    "basePath": "/v2",
    "schemes": ["https"],
    "paths": {
        "/users": {
            "get": {
                "operationId": "listUsers",
                "summary": "List users",
                "parameters": [],
            },
        },
    },
}


class TestOpenAPIDiscoveryEnhanced:
    def test_discover_from_file_json(self, tmp_path):
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        spec_file = tmp_path / "openapi.json"
        spec_file.write_text(json.dumps(PETSORE_SPEC))

        discovery = OpenAPIDiscovery()
        tools = discovery.discover_from_file(str(spec_file), mode=DiscoveryMode.AUTO)
        assert len(tools) == 3

    def test_discover_from_file_yaml(self, tmp_path):
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        spec_file = tmp_path / "openapi.yaml"
        spec_file.write_text("openapi: '3.0.0'\ninfo:\n  title: Test\n  version: '1.0'\npaths: {}\n")

        with patch(
            "yaml.safe_load", return_value={"openapi": "3.0.0", "info": {"title": "T", "version": "1.0"}, "paths": {}}
        ):
            discovery = OpenAPIDiscovery()
            tools = discovery.discover_from_file(str(spec_file), mode=DiscoveryMode.AUTO)
            assert isinstance(tools, list)

    def test_discover_from_file_yml(self, tmp_path):
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        spec_file = tmp_path / "openapi.yml"
        spec_file.write_text("openapi: '3.0.0'\ninfo:\n  title: Test\n  version: '1.0'\npaths: {}\n")

        with patch(
            "yaml.safe_load", return_value={"openapi": "3.0.0", "info": {"title": "T", "version": "1.0"}, "paths": {}}
        ):
            discovery = OpenAPIDiscovery()
            tools = discovery.discover_from_file(str(spec_file), mode=DiscoveryMode.AUTO)
            assert tools == []

    def test_discover_from_spec_alias(self):
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover_from_spec(PETSORE_SPEC, mode=DiscoveryMode.AUTO)
        assert len(tools) == 3

    def test_extract_base_url_oapi3_servers(self):
        from proxy.app.tools.openapi.discovery import OpenAPIDiscovery

        url = OpenAPIDiscovery._extract_base_url(PETSORE_SPEC, "")
        assert url == "https://petstore.example.com/v1"

    def test_extract_base_url_oapi3_no_servers_returns_fallback(self):
        from proxy.app.tools.openapi.discovery import OpenAPIDiscovery

        spec = {"openapi": "3.0.0", "info": {}, "paths": {}}
        assert OpenAPIDiscovery._extract_base_url(spec, "http://fallback") == "http://fallback"

    def test_extract_base_url_swagger_2(self):
        from proxy.app.tools.openapi.discovery import OpenAPIDiscovery

        url = OpenAPIDiscovery._extract_base_url(SWAGGER_2_0_SPEC, "")
        assert url == "https://api.example.com/v2"

    def test_extract_base_url_swagger_2_scheme_default(self):
        from proxy.app.tools.openapi.discovery import OpenAPIDiscovery

        spec = {"swagger": "2.0", "host": "test.com", "basePath": "/api"}
        url = OpenAPIDiscovery._extract_base_url(spec, "")
        assert url == "https://test.com/api"

    def test_extract_base_url_no_servers_no_host(self):
        from proxy.app.tools.openapi.discovery import OpenAPIDiscovery

        spec = {"openapi": "3.0.0", "info": {}}
        url = OpenAPIDiscovery._extract_base_url(spec, "default")
        assert url == "default"

    def test_discover_from_url_async_path(self):
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        with patch.object(discovery, "discover", return_value=[]):
            tools = discovery.discover_from_url("https://example.com/api.json", mode=DiscoveryMode.AUTO)
            assert tools == []

    def test_llm_driven_mode_discover(self):
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.LLM_DRIVEN)
        assert tools == []

    def test_paths_with_non_dict_items_skipped(self):
        from proxy.app.tools.openapi.discovery import DiscoveryMode, OpenAPIDiscovery

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/not-a-dict": "skipped",
                "/valid": {
                    "get": {
                        "operationId": "validEndpoint",
                        "summary": "Valid",
                        "parameters": [],
                    },
                },
            },
        }
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(spec, mode=DiscoveryMode.AUTO)
        assert len(tools) == 1
        assert tools[0].name == "validEndpoint"


class TestOpenAPIConverterEnhanced:
    def test_resolve_ref_valid(self):
        from proxy.app.tools.openapi.converter import _resolve_ref

        spec = {"components": {"schemas": {"Pet": {"type": "object"}}}}
        result = _resolve_ref(spec, "#/components/schemas/Pet")
        assert result == {"type": "object"}

    def test_resolve_ref_non_local_raises(self):
        from proxy.app.tools.openapi.converter import _resolve_ref

        with pytest.raises(ValueError, match="Only local"):
            _resolve_ref({}, "https://external.com/schema")

    def test_resolve_ref_resolves_to_non_dict_raises(self):
        from proxy.app.tools.openapi.converter import _resolve_ref

        with pytest.raises(ValueError, match="non-dict"):
            _resolve_ref({"x": "string_value"}, "#/x")

    def test_type_from_schema_all_types(self):
        from proxy.app.tools.openapi.converter import _type_from_schema

        assert _type_from_schema({"type": "string"}) is str
        assert _type_from_schema({"type": "integer"}) is int
        assert _type_from_schema({"type": "number"}) is float
        assert _type_from_schema({"type": "boolean"}) is bool
        assert _type_from_schema({"type": "array"}) is list
        assert _type_from_schema({"type": "object"}) is dict
        assert _type_from_schema({"type": "unknown"}) is str

    def test_type_from_schema_default(self):
        from proxy.app.tools.openapi.converter import _type_from_schema

        assert _type_from_schema({}) is str

    def test_make_openapi_handler_get_request(self):
        from proxy.app.tools.openapi.converter import _make_openapi_handler

        handler = _make_openapi_handler("https://api.example.com", "/pets", "get", [])
        assert callable(handler)

    def test_make_openapi_handler_post_request(self):
        from proxy.app.tools.openapi.converter import _make_openapi_handler

        handler = _make_openapi_handler("https://api.example.com", "/pets", "post", [])
        assert callable(handler)

    def test_make_openapi_handler_put_request(self):
        from proxy.app.tools.openapi.converter import _make_openapi_handler

        handler = _make_openapi_handler("https://api.example.com", "/pets/{id}", "put", [])
        assert callable(handler)

    def test_make_openapi_handler_patch_request(self):
        from proxy.app.tools.openapi.converter import _make_openapi_handler

        handler = _make_openapi_handler("https://api.example.com", "/pets/{id}", "patch", [])
        assert callable(handler)

    def test_make_openapi_handler_delete_request(self):
        from proxy.app.tools.openapi.converter import _make_openapi_handler

        handler = _make_openapi_handler("https://api.example.com", "/pets/{id}", "delete", [])
        assert callable(handler)


class TestOpenAPIProvider:
    def test_provider_name(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        assert OpenAPIProvider.provider_name == "openapi"

    @pytest.mark.asyncio
    async def test_discover_empty_configs(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        with patch(
            "proxy.app.tools.openapi.discovery.OpenAPIProvider._get_spec_configs",
            return_value=[],
        ):
            provider = OpenAPIProvider()
            tools = await provider.discover()
            assert tools == []

    @pytest.mark.asyncio
    async def test_discover_config_missing_url_and_file(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        configs = [{"name": "test", "mode": "auto"}]
        with patch(
            "proxy.app.tools.openapi.discovery.OpenAPIProvider._get_spec_configs",
            return_value=configs,
        ):
            provider = OpenAPIProvider()
            tools = await provider.discover()
            assert tools == []

    @pytest.mark.asyncio
    async def test_discover_from_url_config(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        configs = [{"name": "petstore", "url": "https://example.com/openapi.json", "mode": "auto"}]
        with (
            patch(
                "proxy.app.tools.openapi.discovery.OpenAPIProvider._get_spec_configs",
                return_value=configs,
            ),
            patch(
                "proxy.app.tools.openapi.discovery.OpenAPIDiscovery.discover_from_url",
                return_value=[],
            ),
        ):
            provider = OpenAPIProvider()
            tools = await provider.discover()
            assert tools == []

    @pytest.mark.asyncio
    async def test_discover_from_file_config(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        configs = [{"name": "local", "file": "/path/to/spec.json", "mode": "auto"}]
        with (
            patch(
                "proxy.app.tools.openapi.discovery.OpenAPIProvider._get_spec_configs",
                return_value=configs,
            ),
            patch(
                "proxy.app.tools.openapi.discovery.OpenAPIDiscovery.discover_from_file",
                return_value=[],
            ),
        ):
            provider = OpenAPIProvider()
            tools = await provider.discover()
            assert tools == []

    @pytest.mark.asyncio
    async def test_discover_handles_exception(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        configs = [{"name": "bad", "url": "https://bad.example.com/spec.json"}]
        with (
            patch(
                "proxy.app.tools.openapi.discovery.OpenAPIProvider._get_spec_configs",
                return_value=configs,
            ),
            patch(
                "proxy.app.tools.openapi.discovery.OpenAPIDiscovery.discover_from_url",
                side_effect=Exception("Boom"),
            ),
        ):
            provider = OpenAPIProvider()
            tools = await provider.discover()
            assert tools == []

    @pytest.mark.asyncio
    async def test_reload_delegates_to_discover(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        provider = OpenAPIProvider()
        provider.discover = AsyncMock(return_value=[])
        result = await provider.reload()
        assert result == []

    @pytest.mark.asyncio
    async def test_validate_file_not_found(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        configs = [{"name": "missing", "file": "/nonexistent/file.json"}]
        with patch(
            "proxy.app.tools.openapi.discovery.OpenAPIProvider._get_spec_configs",
            return_value=configs,
        ):
            provider = OpenAPIProvider()
            issues = await provider.validate()
            assert len(issues) > 0
            assert "not found" in issues[0]

    @pytest.mark.asyncio
    async def test_validate_missing_url_and_file(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        configs = [{"name": "incomplete"}]
        with patch(
            "proxy.app.tools.openapi.discovery.OpenAPIProvider._get_spec_configs",
            return_value=configs,
        ):
            provider = OpenAPIProvider()
            issues = await provider.validate()
            assert len(issues) > 0

    @pytest.mark.asyncio
    async def test_validate_no_issues(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        configs = [{"name": "remote", "url": "https://example.com/spec.json"}]
        with patch(
            "proxy.app.tools.openapi.discovery.OpenAPIProvider._get_spec_configs",
            return_value=configs,
        ):
            provider = OpenAPIProvider()
            issues = await provider.validate()
            assert issues == []

    def test_get_spec_configs_import_error_falls_back_empty(self):
        from proxy.app.tools.openapi.discovery import OpenAPIProvider

        with patch("proxy.app.tools.openapi.discovery.TOOLS_OPENAPI_SPECS", [], create=True):
            result = OpenAPIProvider._get_spec_configs()
            assert result == []
