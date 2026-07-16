# proxy/app/tools/openapi/converter.py
"""OpenAPI spec to tool conversion — parameter extraction, handler generation."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from proxy.app.tools.definition import _UNSET, ToolDefinition, ToolParam, ToolVisibility

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}

ACTION_METHODS = {"post", "put", "delete", "patch"}


def _slugify_path(path: str) -> str:
    """Convert an OpenAPI path to a safe identifier slug.

    ``/pets/{petId}`` → ``pets_petId``
    ``/store/orders/{orderId}/items/{itemId}`` → ``store_orders_orderId_items_itemId``
    """
    cleaned = re.sub(r"[{}]", "", path)
    segments = [s for s in cleaned.strip("/").split("/") if s]
    return "_".join(segments)


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a JSON ``$ref`` pointer within the spec document."""
    if not ref.startswith("#/"):
        raise ValueError(f"Only local $ref are supported: {ref}")
    parts = ref[2:].split("/")
    current: Any = spec
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[part]
        else:
            raise ValueError(f"Failed to resolve $ref {ref} at {part}")
    if not isinstance(current, dict):
        raise ValueError(f"$ref {ref} resolved to non-dict: {type(current)}")
    return current


def _type_from_schema(schema: dict[str, Any]) -> type | str:
    """Map JSON Schema type to Python type."""
    json_type = schema.get("type", "string")
    type_map: dict[str, type | str] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return type_map.get(json_type, str)


def _extract_parameters(
    operation: dict[str, Any],
    spec: dict[str, Any],
) -> list[ToolParam]:
    """Extract ToolParam objects from an OpenAPI operation.

    Handles path, query, header, cookie parameters and JSON requestBody.
    """
    params: list[ToolParam] = []

    # Path / query / header / cookie parameters
    for raw_param in operation.get("parameters", []):
        resolved = raw_param
        if "$ref" in resolved:
            try:
                resolved = _resolve_ref(spec, resolved["$ref"])
            except ValueError:
                continue

        name = resolved.get("name", "")
        location = resolved.get("in", "")
        description = resolved.get("description", "")
        required = resolved.get("required", False)

        # OpenAPI 3: schema dict; Swagger 2: top-level type
        param_schema = resolved.get("schema")
        if param_schema is None:
            param_schema = {"type": resolved.get("type", "string")}

        # Resolve $ref if needed
        if "$ref" in param_schema:
            try:  # noqa: SIM105
                param_schema = _resolve_ref(spec, param_schema["$ref"])
            except ValueError:
                pass

        param_type = _type_from_schema(param_schema)
        enum_values = param_schema.get("enum")
        default_val = param_schema.get("default", _UNSET)

        params.append(
            ToolParam(
                name=name,
                type=param_type,
                description=description or f"{location} parameter: {name}",
                required=required and location == "path",
                default=default_val if default_val is not _UNSET else _UNSET,
                enum=enum_values,
            )
        )

    # Request body (JSON only for now)
    request_body = operation.get("requestBody")
    if request_body is not None:
        if "$ref" in request_body:
            try:
                request_body = _resolve_ref(spec, request_body["$ref"])
            except ValueError:
                request_body = None

        if request_body is not None:
            content = request_body.get("content", {})
            json_content = content.get("application/json", {})
            body_schema = json_content.get("schema", {})

            if "$ref" in body_schema:
                try:  # noqa: SIM105
                    body_schema = _resolve_ref(spec, body_schema["$ref"])
                except ValueError:
                    pass

            if body_schema.get("type") == "object" and "properties" in body_schema:
                for prop_name, prop_schema in body_schema["properties"].items():
                    if "$ref" in prop_schema:
                        try:  # noqa: SIM105
                            prop_schema = _resolve_ref(spec, prop_schema["$ref"])
                        except ValueError:
                            pass
                    required_list = body_schema.get("required", [])
                    prop_type = _type_from_schema(prop_schema)
                    params.append(
                        ToolParam(
                            name=prop_name,
                            type=prop_type,
                            description=prop_schema.get("description", ""),
                            required=prop_name in required_list,
                            enum=prop_schema.get("enum"),
                        )
                    )

    return params


def _make_openapi_handler(
    base_url: str,
    path_template: str,
    method: str,
    tool_params: list[ToolParam],
) -> Any:
    """Create an async handler that performs the actual HTTP request.

    The handler substitutes path parameters into the URL template,
    appends query parameters, and sends a JSON body for POST/PUT/PATCH.
    """
    import aiohttp

    template_params = set(re.findall(r"\{(\w+)}", path_template))

    async def _handler(**kwargs: Any) -> str:
        url = base_url.rstrip("/") + "/" + path_template.lstrip("/")
        query_params: dict[str, Any] = {}
        body: dict[str, Any] = {}

        for name, value in kwargs.items():
            if name in template_params:
                url = url.replace(f"{{{name}}}", str(value))
            elif method in ACTION_METHODS:
                body[name] = value
            elif method == "get":
                query_params[name] = value

        if query_params:
            url += "?" + urlencode(query_params)

        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if method in ACTION_METHODS:
                    async with session.request(method.upper(), url, json=body) as resp:
                        text = await resp.text()
                        return text
                else:
                    async with session.get(url) as resp:
                        text = await resp.text()
                        return text
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("OpenAPI tool %s %s failed: %s", method.upper(), url, exc)
            return f"Error: {exc}"

    return _handler


class OpenAPIToolGenerator:
    """Converts a single OpenAPI endpoint to a ToolDefinition."""

    @staticmethod
    def from_endpoint(
        path: str,
        method: str,
        operation: dict[str, Any],
        spec: dict[str, Any],
        base_url: str = "",
        default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
    ) -> ToolDefinition:
        """Generate a ToolDefinition from one OpenAPI operation."""
        method_lower = method.lower()
        category = "search" if method_lower == "get" else "action"

        operation_id = operation.get("operationId", "")
        if operation_id:  # noqa: SIM108
            tool_name = operation_id
        else:
            tool_name = f"{method_lower}_{_slugify_path(path)}"

        description = operation.get("description") or operation.get("summary") or f"{method.upper()} {path}"

        tags = operation.get("tags", [])

        params = _extract_parameters(operation, spec)

        handler = _make_openapi_handler(base_url, path, method_lower, params)

        return ToolDefinition(
            name=tool_name,
            description=description,
            parameters=params,
            async_handler=handler,
            category=category,
            tags=tags,
            provider="openapi",
            visibility=default_visibility,
        )
