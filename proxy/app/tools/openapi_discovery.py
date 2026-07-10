# proxy/app/tools/openapi_discovery.py
"""OpenAPI auto-discovery — parse OpenAPI/Swagger specs into ToolDefinition objects.

Auto mode: GET endpoints become search tools. POST/PUT/PATCH/DELETE become action tools.
LLM-driven mode: stub — sends spec to LLM for tool selection (future).

Also provides the OpenAPIProvider (ToolProvider integration) and the
OpenAPIToolGenerator utility for single-endpoint conversion.
"""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .definition import _UNSET, ToolDefinition, ToolParam, ToolVisibility

logger = logging.getLogger(__name__)


class DiscoveryMode(StrEnum):
    AUTO = "auto"
    LLM_DRIVEN = "llm_driven"


HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}

ACTION_METHODS = {"post", "put", "delete", "patch"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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

    _path_param_names = {p.name for p in tool_params}
    # Identify path params from the template
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
            logger.warning("OpenAPI tool %s %s failed: %s", method.upper(), url, exc)
            return f"Error: {exc}"

    return _handler


# ---------------------------------------------------------------------------
# OpenAPIToolGenerator
# ---------------------------------------------------------------------------


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
        """Generate a ToolDefinition from one OpenAPI operation.

        Args:
            path: OpenAPI path (e.g. ``/pets/{petId}``).
            method: HTTP method (``get``, ``post``, etc.).
            operation: The operation object from the spec.
            spec: The full OpenAPI spec (for $ref resolution).
            base_url: Base URL for the API server.
            default_visibility: Visibility for the generated tool.

        Returns:
            A ToolDefinition ready for registration.
        """
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


# ---------------------------------------------------------------------------
# OpenAPIDiscovery
# ---------------------------------------------------------------------------


class OpenAPIDiscovery:
    """Parse OpenAPI/Swagger specs and generate tool definitions.

    Supports two modes:
    - ``AUTO`` — registers all GET as search tools, all POST/PUT/DELETE as action tools.
    - ``LLM_DRIVEN`` — stub; sends spec to LLM for tool selection (future).
    """

    def discover(
        self,
        spec: dict[str, Any],
        mode: DiscoveryMode = DiscoveryMode.AUTO,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
        base_url_override: str = "",
    ) -> list[ToolDefinition]:
        """Parse an OpenAPI spec and return tool definitions.

        Args:
            spec: The parsed OpenAPI/Swagger spec dict.
            mode: Discovery mode (AUTO or LLM_DRIVEN).
            include_tags: If set, only include endpoints with these tags.
            exclude_tags: If set, exclude endpoints with these tags.
            default_visibility: Default visibility for generated tools.
            base_url_override: Override the base URL (defaults to first server or empty).

        Returns:
            List of ToolDefinition objects.
        """
        if mode == DiscoveryMode.LLM_DRIVEN:
            return self._discover_llm_driven(spec)

        return self._discover_auto(
            spec=spec,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            default_visibility=default_visibility,
            base_url_override=base_url_override,
        )

    def discover_from_spec(
        self,
        spec: dict[str, Any],
        mode: DiscoveryMode = DiscoveryMode.AUTO,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
        base_url_override: str = "",
    ) -> list[ToolDefinition]:
        """Alias for discover()."""
        return self.discover(
            spec=spec,
            mode=mode,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            default_visibility=default_visibility,
            base_url_override=base_url_override,
        )

    def discover_from_url(
        self,
        url: str,
        mode: DiscoveryMode = DiscoveryMode.AUTO,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
        base_url_override: str = "",
        timeout: float = 30.0,
    ) -> list[ToolDefinition]:
        """Fetch an OpenAPI spec from a URL and parse it into tools."""
        import asyncio

        import aiohttp

        async def _fetch() -> dict[str, Any]:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session, session.get(url) as resp:
                text = await resp.text()
                content_type = resp.content_type or ""
                if "yaml" in content_type or url.endswith((".yaml", ".yml")):
                    return _parse_yaml(text)
                return _parse_json(text)

        try:
            # Try to use existing event loop if available
            try:
                _loop = asyncio.get_running_loop()
                # Running in event loop — use synchronous HTTP fallback
                import urllib.request

                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    text = resp.read().decode("utf-8")
                    if url.endswith((".yaml", ".yml")):  # noqa: SIM108
                        spec = _parse_yaml(text)
                    else:
                        spec = _parse_json(text)
            except RuntimeError:
                spec = asyncio.run(_fetch())
        except Exception as exc:
            logger.error("Failed to fetch OpenAPI spec from %s: %s", url, exc)
            return []

        return self.discover(
            spec=spec,
            mode=mode,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            default_visibility=default_visibility,
            base_url_override=base_url_override or self._extract_base_url(spec, url),
        )

    def discover_from_file(
        self,
        file_path: str,
        mode: DiscoveryMode = DiscoveryMode.AUTO,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
        base_url_override: str = "",
    ) -> list[ToolDefinition]:
        """Load an OpenAPI spec from a JSON/YAML file and parse into tools."""
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")

        if path.suffix in (".yaml", ".yml"):  # noqa: SIM108
            spec = _parse_yaml(content)
        else:
            spec = _parse_json(content)

        return self.discover(
            spec=spec,
            mode=mode,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            default_visibility=default_visibility,
            base_url_override=base_url_override or self._extract_base_url(spec, f"file://{file_path}"),
        )

    # ── Private helpers ───────────────────────────────────────────────────

    def _discover_auto(
        self,
        spec: dict[str, Any],
        include_tags: list[str] | None,
        exclude_tags: list[str] | None,
        default_visibility: ToolVisibility,
        base_url_override: str,
    ) -> list[ToolDefinition]:
        """Iterate all paths and generate tools automatically."""
        tools: list[ToolDefinition] = []

        base_url = base_url_override or self._extract_base_url(spec, "")

        paths = spec.get("paths", {})
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            for method in HTTP_METHODS:
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue

                # Tag filtering
                op_tags = operation.get("tags", [])
                if include_tags and not set(include_tags) & set(op_tags):
                    continue
                if exclude_tags and set(exclude_tags) & set(op_tags):
                    continue

                tool_def = OpenAPIToolGenerator.from_endpoint(
                    path=path,
                    method=method,
                    operation=operation,
                    spec=spec,
                    base_url=base_url,
                    default_visibility=default_visibility,
                )
                tools.append(tool_def)

        return tools

    def _discover_llm_driven(self, spec: dict[str, Any]) -> list[ToolDefinition]:
        """Stub: LLM-driven discovery — returns empty list for now."""
        return []

    @staticmethod
    def _extract_base_url(spec: dict[str, Any], fallback: str = "") -> str:
        """Extract the base URL from the spec's servers or host fields."""
        # OpenAPI 3: servers[0].url
        servers = spec.get("servers", [])
        if servers and isinstance(servers, list):
            first = servers[0]
            if isinstance(first, dict):
                return first.get("url", fallback)

        # Swagger 2: schemes + host + basePath
        if "swagger" in spec:
            schemes = spec.get("schemes", ["https"])
            host = spec.get("host", "")
            base_path = spec.get("basePath", "")
            if host:
                scheme = schemes[0] if isinstance(schemes, list) else str(schemes)
                return f"{scheme}://{host}{base_path}"

        return fallback


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_json(text: str) -> dict[str, Any]:
    """Parse a JSON string into a spec dict."""
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object, got {type(result)}")
    return result


def _parse_yaml(text: str) -> dict[str, Any]:
    """Parse a YAML string into a spec dict."""
    try:
        import yaml

        result = yaml.safe_load(text)
    except ImportError:
        try:
            import tomllib  # noqa: F401  # Python 3.11+ only

            raise ImportError("yaml not available")
        except ImportError:
            raise ImportError(
                "PyYAML is required for YAML OpenAPI specs. Install it with: pip install pyyaml"
            ) from None

    if not isinstance(result, dict):
        raise ValueError(f"Expected YAML mapping, got {type(result)}")
    return result


# ---------------------------------------------------------------------------
# OpenAPIProvider — ToolProvider integration
# ---------------------------------------------------------------------------


class OpenAPIProvider:
    """ToolProvider for OpenAPI spec-derived tools.

    Reads ``TOOLS_OPENAPI_SPECS`` from config and fetches/parses each spec
    to generate tool definitions.

    Lazily imported to avoid circular dependencies on config.
    """

    provider_name: str = "openapi"

    async def discover(self) -> list[ToolDefinition]:
        """Discover tools from all configured OpenAPI specs."""
        all_tools: list[ToolDefinition] = []
        discovery = OpenAPIDiscovery()

        for spec_config in self._get_spec_configs():
            try:
                spec_url = spec_config.get("url", "")
                spec_file = spec_config.get("file", "")
                spec_mode_str = spec_config.get("mode", "auto")
                spec_mode = DiscoveryMode(spec_mode_str)
                include_tags = spec_config.get("include_tags")
                exclude_tags = spec_config.get("exclude_tags")
                visibility_str = spec_config.get("visibility", "public")
                default_visibility = ToolVisibility(visibility_str)
                base_url = spec_config.get("base_url_override", "")

                if spec_url:
                    tools = discovery.discover_from_url(
                        url=spec_url,
                        mode=spec_mode,
                        include_tags=include_tags,
                        exclude_tags=exclude_tags,
                        default_visibility=default_visibility,
                        base_url_override=base_url,
                    )
                elif spec_file:
                    tools = discovery.discover_from_file(
                        file_path=spec_file,
                        mode=spec_mode,
                        include_tags=include_tags,
                        exclude_tags=exclude_tags,
                        default_visibility=default_visibility,
                        base_url_override=base_url,
                    )
                else:
                    logger.warning("OpenAPI spec config missing 'url' or 'file': %s", spec_config)
                    continue

                all_tools.extend(tools)
                logger.info(
                    "Discovered %d tools from OpenAPI spec '%s'",
                    len(tools),
                    spec_config.get("name", spec_url or spec_file),
                )
            except Exception as exc:
                spec_name = spec_config.get("name", spec_config.get("url", "unknown"))
                logger.warning("Failed to discover tools from OpenAPI spec '%s': %s", spec_name, exc)

        return all_tools

    async def reload(self) -> list[ToolDefinition]:
        """Hot-reload tools from spec sources."""
        return await self.discover()

    async def validate(self) -> list[str]:
        """Validate all configured spec URLs/files exist and parse."""
        issues: list[str] = []
        for spec_config in self._get_spec_configs():
            spec_name = spec_config.get("name", "unnamed")
            spec_url = spec_config.get("url", "")
            spec_file = spec_config.get("file", "")

            if spec_file:
                if not Path(spec_file).exists():
                    issues.append(f"Spec file not found: {spec_file} ({spec_name})")
            elif not spec_url:
                issues.append(f"Spec '{spec_name}' has neither url nor file configured")

        return issues

    @staticmethod
    def _get_spec_configs() -> list[dict[str, Any]]:
        """Load OpenAPI spec configs from app config."""
        try:
            from proxy.app.shared.config import TOOLS_OPENAPI_SPECS

            return list(TOOLS_OPENAPI_SPECS) if TOOLS_OPENAPI_SPECS else []
        except ImportError:
            return []
