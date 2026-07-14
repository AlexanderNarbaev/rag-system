# proxy/app/tools/openapi/discovery.py
"""OpenAPI spec parsing and tool discovery."""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

from proxy.app.tools.definition import ToolDefinition, ToolVisibility
from proxy.app.tools.openapi.converter import (
  HTTP_METHODS, OpenAPIToolGenerator,
)

logger = logging.getLogger (__name__)


class DiscoveryMode (StrEnum):
  AUTO = "auto"
  LLM_DRIVEN = "llm_driven"


class OpenAPIDiscovery:
  """Parse OpenAPI/Swagger specs and generate tool definitions.

  Supports two modes:
  - ``AUTO`` — registers all GET as search tools, all POST/PUT/DELETE as action tools.
  - ``LLM_DRIVEN`` — stub; sends spec to LLM for tool selection (future).
  """
  
  def discover (
      self, spec: dict [str, Any], mode: DiscoveryMode = DiscoveryMode.AUTO, include_tags: list [str] | None = None,
      exclude_tags: list [str] | None = None, default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
      base_url_override: str = "", ) -> list [ToolDefinition]:
    """Parse an OpenAPI spec and return tool definitions."""
    if mode == DiscoveryMode.LLM_DRIVEN:
      return self._discover_llm_driven (spec)
    
    return self._discover_auto (spec = spec, include_tags = include_tags, exclude_tags = exclude_tags,
        default_visibility = default_visibility, base_url_override = base_url_override, )
  
  def discover_from_spec (
      self, spec: dict [str, Any], mode: DiscoveryMode = DiscoveryMode.AUTO, include_tags: list [str] | None = None,
      exclude_tags: list [str] | None = None, default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
      base_url_override: str = "", ) -> list [ToolDefinition]:
    """Alias for discover()."""
    return self.discover (spec = spec, mode = mode, include_tags = include_tags, exclude_tags = exclude_tags,
        default_visibility = default_visibility, base_url_override = base_url_override, )
  
  def discover_from_url (
      self, url: str, mode: DiscoveryMode = DiscoveryMode.AUTO, include_tags: list [str] | None = None,
      exclude_tags: list [str] | None = None, default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
      base_url_override: str = "", timeout: float = 30.0, ) -> list [ToolDefinition]:
    """Fetch an OpenAPI spec from a URL and parse it into tools."""
    import asyncio
    
    import aiohttp
    
    async def _fetch () -> dict [str, Any]:
      timeout_obj = aiohttp.ClientTimeout (total = timeout)
      async with aiohttp.ClientSession (timeout = timeout_obj) as session, session.get (url) as resp:
        text = await resp.text ()
        content_type = resp.content_type or ""
        if "yaml" in content_type or url.endswith ((".yaml", ".yml")):
          return _parse_yaml (text)
        return _parse_json (text)
    
    try:
      # Try to use existing event loop if available
      try:
        _loop = asyncio.get_running_loop ()
        # Running in event loop — use synchronous HTTP fallback
        import urllib.request
        
        with urllib.request.urlopen (url,
                                     timeout = timeout) as resp:  # nosec B310 — URL from admin config, not user input
          text = resp.read ().decode ("utf-8")
          if url.endswith ((".yaml", ".yml")):  # noqa: SIM108
            spec = _parse_yaml (text)
          else:
            spec = _parse_json (text)
      except RuntimeError:
        spec = asyncio.run (_fetch ())
    except Exception as exc:
      logger.error ("Failed to fetch OpenAPI spec from %s: %s", url, exc)
      return []
    
    return self.discover (spec = spec, mode = mode, include_tags = include_tags, exclude_tags = exclude_tags,
        default_visibility = default_visibility,
        base_url_override = base_url_override or self._extract_base_url (spec, url), )
  
  def discover_from_file (
      self, file_path: str, mode: DiscoveryMode = DiscoveryMode.AUTO, include_tags: list [str] | None = None,
      exclude_tags: list [str] | None = None, default_visibility: ToolVisibility = ToolVisibility.PUBLIC,
      base_url_override: str = "", ) -> list [ToolDefinition]:
    """Load an OpenAPI spec from a JSON/YAML file and parse into tools."""
    path = Path (file_path)
    content = path.read_text (encoding = "utf-8")
    
    if path.suffix in (".yaml", ".yml"):  # noqa: SIM108
      spec = _parse_yaml (content)
    else:
      spec = _parse_json (content)
    
    return self.discover (spec = spec, mode = mode, include_tags = include_tags, exclude_tags = exclude_tags,
        default_visibility = default_visibility,
        base_url_override = base_url_override or self._extract_base_url (spec, f"file://{file_path}"), )
  
  # ── Private helpers ───────────────────────────────────────────────────
  
  def _discover_auto (
      self, spec: dict [str, Any], include_tags: list [str] | None, exclude_tags: list [str] | None,
      default_visibility: ToolVisibility, base_url_override: str, ) -> list [ToolDefinition]:
    """Iterate all paths and generate tools automatically."""
    tools: list [ToolDefinition] = []
    
    base_url = base_url_override or self._extract_base_url (spec, "")
    
    paths = spec.get ("paths", {})
    for path, path_item in paths.items ():
      if not isinstance (path_item, dict):
        continue
      
      for method in HTTP_METHODS:
        operation = path_item.get (method)
        if not isinstance (operation, dict):
          continue
        
        # Tag filtering
        op_tags = operation.get ("tags", [])
        if include_tags and not set (include_tags) & set (op_tags):
          continue
        if exclude_tags and set (exclude_tags) & set (op_tags):
          continue
        
        tool_def = OpenAPIToolGenerator.from_endpoint (path = path, method = method, operation = operation, spec = spec,
            base_url = base_url, default_visibility = default_visibility, )
        tools.append (tool_def)
    
    return tools
  
  def _discover_llm_driven (self, spec: dict [str, Any]) -> list [ToolDefinition]:
    """Stub: LLM-driven discovery — returns empty list for now."""
    return []
  
  @staticmethod
  def _extract_base_url (spec: dict [str, Any], fallback: str = "") -> str:
    """Extract the base URL from the spec's servers or host fields."""
    # OpenAPI 3: servers[0].url
    servers = spec.get ("servers", [])
    if servers and isinstance (servers, list):
      first = servers [0]
      if isinstance (first, dict):
        return str (first.get ("url", fallback))
    
    # Swagger 2: schemes + host + basePath
    if "swagger" in spec:
      schemes = spec.get ("schemes", ["https"])
      host = spec.get ("host", "")
      base_path = spec.get ("basePath", "")
      if host:
        scheme = schemes [0] if isinstance (schemes, list) else str (schemes)
        return f"{scheme}://{host}{base_path}"
    
    return fallback


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_json (text: str) -> dict [str, Any]:
  """Parse a JSON string into a spec dict."""
  result = json.loads (text)
  if not isinstance (result, dict):
    raise ValueError (f"Expected JSON object, got {type (result)}")
  return result


def _parse_yaml (text: str) -> dict [str, Any]:
  """Parse a YAML string into a spec dict."""
  try:
    import yaml
    
    result = yaml.safe_load (text)
  except ImportError:
    try:
      import tomllib  # noqa: F401  # Python 3.11+ only
      
      raise ImportError ("yaml not available")
    except ImportError:
      raise ImportError ("PyYAML is required for YAML OpenAPI specs. Install it with: pip install pyyaml") from None
  
  if not isinstance (result, dict):
    raise ValueError (f"Expected YAML mapping, got {type (result)}")
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
  
  async def discover (self) -> list [ToolDefinition]:
    """Discover tools from all configured OpenAPI specs."""
    all_tools: list [ToolDefinition] = []
    discovery = OpenAPIDiscovery ()
    
    for spec_config in self._get_spec_configs ():
      try:
        spec_url = spec_config.get ("url", "")
        spec_file = spec_config.get ("file", "")
        spec_mode_str = spec_config.get ("mode", "auto")
        spec_mode = DiscoveryMode (spec_mode_str)
        include_tags = spec_config.get ("include_tags")
        exclude_tags = spec_config.get ("exclude_tags")
        visibility_str = spec_config.get ("visibility", "public")
        default_visibility = ToolVisibility (visibility_str)
        base_url = spec_config.get ("base_url_override", "")
        
        if spec_url:
          tools = discovery.discover_from_url (url = spec_url, mode = spec_mode, include_tags = include_tags,
              exclude_tags = exclude_tags, default_visibility = default_visibility, base_url_override = base_url, )
        elif spec_file:
          tools = discovery.discover_from_file (file_path = spec_file, mode = spec_mode, include_tags = include_tags,
              exclude_tags = exclude_tags, default_visibility = default_visibility, base_url_override = base_url, )
        else:
          logger.warning ("OpenAPI spec config missing 'url' or 'file': %s", spec_config)
          continue
        
        all_tools.extend (tools)
        logger.info ("Discovered %d tools from OpenAPI spec '%s'", len (tools),
            spec_config.get ("name", spec_url or spec_file), )
      except Exception as exc:
        spec_name = spec_config.get ("name", spec_config.get ("url", "unknown"))
        logger.warning ("Failed to discover tools from OpenAPI spec '%s': %s", spec_name, exc)
    
    return all_tools
  
  async def reload (self) -> list [ToolDefinition]:
    """Hot-reload tools from spec sources."""
    return await self.discover ()
  
  async def validate (self) -> list [str]:
    """Validate all configured spec URLs/files exist and parse."""
    issues: list [str] = []
    for spec_config in self._get_spec_configs ():
      spec_name = spec_config.get ("name", "unnamed")
      spec_url = spec_config.get ("url", "")
      spec_file = spec_config.get ("file", "")
      
      if spec_file:
        if not Path (spec_file).exists ():
          issues.append (f"Spec file not found: {spec_file} ({spec_name})")
      elif not spec_url:
        issues.append (f"Spec '{spec_name}' has neither url nor file configured")
    
    return issues
  
  @staticmethod
  def _get_spec_configs () -> list [dict [str, Any]]:
    """Load OpenAPI spec configs from app config."""
    try:
      from proxy.app.shared.config import TOOLS_OPENAPI_SPECS
      
      return list (TOOLS_OPENAPI_SPECS) if TOOLS_OPENAPI_SPECS else []  # type: ignore[arg-type]
    except ImportError:
      return []
