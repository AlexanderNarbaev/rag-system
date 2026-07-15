# proxy/app/tools/openapi/__init__.py
"""OpenAPI auto-discovery — parse OpenAPI/Swagger specs into ToolDefinition objects.

Re-exports all public symbols for backward compatibility with
``from proxy.app.tools.openapi_discovery import ...`` imports.
"""

from proxy.app.tools.openapi.converter import (
  ACTION_METHODS,
  HTTP_METHODS,
  OpenAPIToolGenerator,
  _extract_parameters,
  _make_openapi_handler,
  _resolve_ref,
  _slugify_path,
  _type_from_schema,
)
from proxy.app.tools.openapi.discovery import (
  DiscoveryMode,
  OpenAPIDiscovery,
  OpenAPIProvider,
  _parse_json,
  _parse_yaml,
)

__all__ = [
    "ACTION_METHODS", "DiscoveryMode", "HTTP_METHODS", "OpenAPIDiscovery", "OpenAPIProvider", "OpenAPIToolGenerator",
    "_extract_parameters", "_make_openapi_handler", "_parse_json", "_parse_yaml", "_resolve_ref", "_slugify_path",
    "_type_from_schema",
]
