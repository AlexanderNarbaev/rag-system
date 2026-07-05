"""Tests for proxy/app/tools/openapi_discovery.py — OpenAPI Auto-Discovery."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))

PETSORE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "PetStore API", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "description": "Returns all pets from the store",
                "tags": ["pets"],
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "description": "Max items to return",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "status",
                        "in": "query",
                        "description": "Filter by pet status",
                        "required": False,
                        "schema": {"type": "string", "enum": ["available", "pending", "sold"]},
                    },
                ],
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "tags": ["pets"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"name": {"type": "string"}, "status": {"type": "string"}}}
                        }
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
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                        "description": "Pet ID",
                    }
                ],
            },
            "delete": {
                "operationId": "deletePet",
                "summary": "Delete a pet",
                "tags": ["admin"],
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                        "description": "Pet ID to delete",
                    }
                ],
            },
        },
    },
}


class TestDiscoveryMode:
    def test_enum_values(self):
        from tools.openapi_discovery import DiscoveryMode

        assert DiscoveryMode.AUTO.value == "auto"
        assert DiscoveryMode.LLM_DRIVEN.value == "llm_driven"

    def test_enum_is_string_subclass(self):
        from tools.openapi_discovery import DiscoveryMode

        assert isinstance(DiscoveryMode.AUTO, str)


class TestOpenAPIDiscoveryAuto:
    def test_discover_auto_generates_four_tools(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO)

        assert len(tools) == 4
        names = {t.name for t in tools}
        assert names == {"listPets", "createPet", "getPetById", "deletePet"}

    def test_get_endpoints_are_search_category(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO)

        get_tools = [t for t in tools if t.name in {"listPets", "getPetById"}]
        for t in get_tools:
            assert t.category == "search", f"{t.name} should be search, got {t.category}"

    def test_post_delete_are_action_category(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO)

        mutation_tools = [t for t in tools if t.name in {"createPet", "deletePet"}]
        for t in mutation_tools:
            assert t.category == "action", f"{t.name} should be action, got {t.category}"

    def test_path_params_extracted_as_tool_param(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO)

        get_by_id = next(t for t in tools if t.name == "getPetById")
        param_names = {p.name for p in get_by_id.parameters}
        assert "petId" in param_names

        pet_id_param = next(p for p in get_by_id.parameters if p.name == "petId")
        assert pet_id_param.required is True
        assert pet_id_param.type == int

    def test_query_params_extracted_as_optional_tool_param(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO)

        list_pets = next(t for t in tools if t.name == "listPets")
        param_names = {p.name for p in list_pets.parameters}
        assert "limit" in param_names
        assert "status" in param_names

        limit = next(p for p in list_pets.parameters if p.name == "limit")
        assert limit.required is False
        assert limit.type == int

        status = next(p for p in list_pets.parameters if p.name == "status")
        assert status.required is False
        assert status.type == str
        assert status.enum == ["available", "pending", "sold"]

    def test_request_body_json_mapped_to_tool_param(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO)

        create_pet = next(t for t in tools if t.name == "createPet")
        body_params = {p.name for p in create_pet.parameters}
        assert "name" in body_params
        assert "status" in body_params

    def test_include_tags_filtering(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO, include_tags=["admin"])

        assert len(tools) == 1
        assert tools[0].name == "deletePet"

    def test_exclude_tags_filtering(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO, exclude_tags=["admin"])

        assert len(tools) == 3
        names = {t.name for t in tools}
        assert "deletePet" not in names

    def test_all_tools_have_openapi_provider(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO)

        for t in tools:
            assert t.provider == "openapi", f"{t.name} provider should be openapi"

    def test_async_handler_is_set(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.AUTO, base_url_override="https://api.example.com")

        for t in tools:
            assert t.async_handler is not None, f"{t.name} should have async_handler"


class TestSlugify:
    def test_slugify_path_with_params(self):
        from tools.openapi_discovery import _slugify_path

        result = _slugify_path("/pets/{petId}")
        assert result == "pets_petId"

    def test_slugify_path_nested_with_params(self):
        from tools.openapi_discovery import _slugify_path

        result = _slugify_path("/store/orders/{orderId}/items/{itemId}")
        assert result == "store_orders_orderId_items_itemId"


class TestEndpointFallbackNaming:
    def test_no_operation_id_uses_method_path_slug(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/users/{id}": {
                    "get": {
                        "summary": "Get user",
                        "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    }
                }
            },
        }
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(spec, mode=DiscoveryMode.AUTO)

        assert len(tools) == 1
        assert tools[0].name == "get_users_id"

    def test_swagger_2_0_spec_parsing(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        spec = {
            "swagger": "2.0",
            "info": {"title": "Swagger Petstore", "version": "1.0.0"},
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "findPets",
                        "summary": "Find pets",
                        "parameters": [
                            {"name": "limit", "in": "query", "type": "integer", "description": "Max results"},
                        ],
                    }
                }
            },
        }
        discovery = OpenAPIDiscovery()
        tools = discovery.discover(spec, mode=DiscoveryMode.AUTO)

        assert len(tools) == 1
        assert tools[0].name == "findPets"
        assert tools[0].provider == "openapi"


class TestLLMDrivenMode:
    def test_llm_driven_returns_empty_stub(self):
        from tools.openapi_discovery import DiscoveryMode, OpenAPIDiscovery

        discovery = OpenAPIDiscovery()
        tools = discovery.discover(PETSORE_SPEC, mode=DiscoveryMode.LLM_DRIVEN)

        assert isinstance(tools, list)
        assert len(tools) == 0
