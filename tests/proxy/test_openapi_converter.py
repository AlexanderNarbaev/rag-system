# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/tools/openapi/converter.py — OpenAPI spec to tool conversion."""

import pytest

from proxy.app.tools.openapi.converter import (
    OpenAPIToolGenerator,
    _extract_parameters,
    _make_openapi_handler,
    _resolve_ref,
    _slugify_path,
    _type_from_schema,
)


class TestSlugifyPath:
    """Tests for _slugify_path."""

    def test_simple_path(self):
        assert _slugify_path("/pets") == "pets"

    def test_path_with_param(self):
        assert _slugify_path("/pets/{petId}") == "pets_petId"

    def test_nested_path(self):
        assert _slugify_path("/store/orders/{orderId}/items/{itemId}") == "store_orders_orderId_items_itemId"

    def test_trailing_slash(self):
        assert _slugify_path("/pets/") == "pets"

    def test_root_path(self):
        assert _slugify_path("/") == ""


class TestResolveRef:
    """Tests for _resolve_ref."""

    def test_simple_ref(self):
        spec = {"components": {"schemas": {"Pet": {"type": "object", "properties": {"name": {"type": "string"}}}}}}
        result = _resolve_ref(spec, "#/components/schemas/Pet")
        assert result["type"] == "object"

    def test_nested_ref(self):
        spec = {"a": {"b": {"c": {"value": 42}}}}
        result = _resolve_ref(spec, "#/a/b/c")
        assert result["value"] == 42

    def test_non_local_ref_raises(self):
        with pytest.raises(ValueError, match="Only local"):
            _resolve_ref({}, "https://example.com/schema")

    def test_missing_key_raises(self):
        with pytest.raises(KeyError):
            _resolve_ref({}, "#/nonexistent/key")

    def test_tilde_escape(self):
        spec = {"a~b": {"value": 1}, "c/d": {"value": 2}}
        assert _resolve_ref(spec, "#/a~0b")["value"] == 1
        assert _resolve_ref(spec, "#/c~1d")["value"] == 2


class TestTypeFromSchema:
    """Tests for _type_from_schema."""

    def test_string(self):
        assert _type_from_schema({"type": "string"}) == str  # noqa: E721

    def test_integer(self):
        assert _type_from_schema({"type": "integer"}) == int  # noqa: E721

    def test_number(self):
        assert _type_from_schema({"type": "number"}) == float  # noqa: E721

    def test_boolean(self):
        assert _type_from_schema({"type": "boolean"}) == bool  # noqa: E721

    def test_array(self):
        assert _type_from_schema({"type": "array"}) == list  # noqa: E721

    def test_object(self):
        assert _type_from_schema({"type": "object"}) == dict  # noqa: E721

    def test_unknown_type_defaults_to_string(self):
        assert _type_from_schema({"type": "unknown"}) == str  # noqa: E721

    def test_no_type_defaults_to_string(self):
        assert _type_from_schema({}) == str  # noqa: E721


class TestExtractParameters:
    """Tests for _extract_parameters."""

    def test_query_params(self):
        operation = {
            "parameters": [
                {"name": "limit", "in": "query", "schema": {"type": "integer"}, "description": "Max results"},
            ]
        }
        params = _extract_parameters(operation, {})
        assert len(params) == 1
        assert params[0].name == "limit"
        assert params[0].type == int  # noqa: E721

    def test_path_params(self):
        operation = {
            "parameters": [
                {"name": "petId", "in": "path", "required": True, "schema": {"type": "string"}},
            ]
        }
        params = _extract_parameters(operation, {})
        assert len(params) == 1
        assert params[0].required is True

    def test_request_body(self):
        operation = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "age": {"type": "integer"},
                            },
                            "required": ["name"],
                        }
                    }
                }
            }
        }
        params = _extract_parameters(operation, {})
        assert len(params) == 2
        names = {p.name for p in params}
        assert "name" in names
        assert "age" in names

    def test_ref_in_parameter(self):
        spec = {
            "components": {
                "parameters": {"LimitParam": {"name": "limit", "in": "query", "schema": {"type": "integer"}}}
            }
        }
        operation = {"parameters": [{"$ref": "#/components/parameters/LimitParam"}]}
        params = _extract_parameters(operation, spec)
        assert len(params) == 1
        assert params[0].name == "limit"

    def test_ref_in_request_body(self):
        spec = {
            "components": {
                "schemas": {
                    "CreatePet": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    }
                }
            }
        }
        operation = {
            "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreatePet"}}}}
        }
        params = _extract_parameters(operation, spec)
        assert len(params) == 1
        assert params[0].name == "name"

    def test_enum_values(self):
        operation = {
            "parameters": [
                {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["active", "inactive"]}},
            ]
        }
        params = _extract_parameters(operation, {})
        assert params[0].enum == ["active", "inactive"]

    def test_empty_operation(self):
        params = _extract_parameters({}, {})
        assert params == []

    def test_ref_in_property(self):
        spec = {"components": {"schemas": {"Name": {"type": "string", "description": "name"}}}}
        operation = {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"pet_name": {"$ref": "#/components/schemas/Name"}},
                        }
                    }
                }
            }
        }
        params = _extract_parameters(operation, spec)
        assert len(params) == 1


class TestOpenAPIToolGenerator:
    """Tests for OpenAPIToolGenerator.from_endpoint."""

    def test_get_endpoint(self):
        operation = {
            "operationId": "listItems",
            "summary": "List items",
            "tags": ["items"],
            "parameters": [],
        }
        tool = OpenAPIToolGenerator.from_endpoint(
            path="/items", method="get", operation=operation, spec={}, base_url="https://api.test.com"
        )
        assert tool.name == "listItems"
        assert tool.category == "search"
        assert tool.provider == "openapi"

    def test_post_endpoint(self):
        operation = {
            "operationId": "createItem",
            "summary": "Create item",
            "tags": ["items"],
        }
        tool = OpenAPIToolGenerator.from_endpoint(
            path="/items", method="post", operation=operation, spec={}, base_url="https://api.test.com"
        )
        assert tool.category == "action"

    def test_no_operation_id(self):
        operation = {"summary": "Get root"}
        tool = OpenAPIToolGenerator.from_endpoint(path="/", method="get", operation=operation, spec={})
        assert "get" in tool.name

    def test_description_fallback(self):
        operation = {"operationId": "test"}
        tool = OpenAPIToolGenerator.from_endpoint(path="/test", method="get", operation=operation, spec={})
        assert "GET /test" in tool.description


class TestMakeOpenapiHandler:
    """Tests for _make_openapi_handler."""

    @pytest.mark.asyncio
    async def test_handler_substitutes_path_params(self):
        handler = _make_openapi_handler("https://api.test.com", "/pets/{petId}", "get", [])
        # We can't easily test the actual HTTP call, but verify the handler is callable
        assert callable(handler)

    @pytest.mark.asyncio
    async def test_handler_returns_string(self):
        """Test handler returns a string (even on error)."""
        handler = _make_openapi_handler("https://nonexistent.invalid", "/test", "get", [])
        result = await handler()
        assert isinstance(result, str)
        assert "Error" in result
