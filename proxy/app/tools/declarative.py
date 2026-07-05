# proxy/app/tools/declarative.py
"""YAML/JSON Declarative Tool Loader.

Loads tool definitions from YAML/JSON files with schema validation,
variable interpolation, and auto-generated handlers for HTTP and shell tools.

Security:
- Shell tools require ``allowed_commands`` and ``allowed_paths`` whitelists.
- Shell parameter values are checked for metacharacters (;, &&, |, $(), ``).
- HTTP tools support ``allowed_hosts`` to restrict remote endpoints.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from glob import glob
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .definition import (
    _UNSET,
    RetryPolicy,
    ToolDefinition,
    ToolParam,
    ToolVisibility,
)
from .registry import ToolProvider

logger = logging.getLogger(__name__)

TOOLS_DECLARATIVE_DIR: str = os.getenv("TOOLS_DECLARATIVE_DIR", "./tools_declarative")

_VAR_PATTERN: re.Pattern = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")

_SHELL_METACHAR_PATTERN: re.Pattern = re.compile(r"[;&|`$()]")


def _interpolate_variables(
    template: str,
    params: dict[str, Any],
    env_vars: dict[str, str],
    context: dict[str, Any],
) -> str:
    """Replace {{VAR}} placeholders in a template string.

    Resolution order: params → context (CONTEXT.xxx) → env vars.
    Unresolved placeholders are left as-is.
    """

    def _replacer(match: re.Match) -> str:
        key = match.group(1)
        parts = key.split(".", 1)
        if parts[0] == "CONTEXT" and len(parts) == 2:
            value = context.get(parts[1])
            if value is not None:
                return str(value)
        if key in params:
            return str(params[key])
        if key in env_vars:
            return env_vars[key]
        return f"{{{{{key}}}}}"

    return _VAR_PATTERN.sub(_replacer, template)


def _has_metacharacters(value: str) -> bool:
    """Check if a string contains shell metacharacters."""
    return bool(_SHELL_METACHAR_PATTERN.search(value))


def _make_http_handler(
    method: str,
    url_template: str,
    headers: dict[str, str] | None = None,
    body_template: str | None = None,
    response_path: str | None = None,
    allowed_hosts: list[str] | None = None,
) -> Any:
    """Create an async HTTP handler callable for a declarative tool."""

    _method = method
    _url_template = url_template
    _headers = headers or {}
    _body_template = body_template
    _response_path = response_path
    _allowed_hosts = allowed_hosts or []

    def _get_env() -> dict[str, str]:
        return dict(os.environ)

    def _resolve(params: dict[str, Any]) -> tuple[str, dict[str, str], str | None]:
        env = _get_env()
        url = _interpolate_variables(_url_template, params, env, {})
        resolved_headers: dict[str, str] = {}
        for k, v in _headers.items():
            resolved_headers[k] = _interpolate_variables(v, params, env, {})
        body = None
        if _body_template:
            body = _interpolate_variables(_body_template, params, env, {})
        return url, resolved_headers, body

    def _check_allowed_host(url: str) -> bool:
        if not _allowed_hosts:
            return True
        hostname = urlparse(url).hostname or ""
        return any(hostname == h or hostname.endswith(f".{h}") for h in _allowed_hosts)

    async def _http_handler(**params: Any) -> str:
        url, resolved_headers, body = _resolve(params)

        if not _check_allowed_host(url):
            return "Error: URL host not in allowed_hosts list"

        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                kwargs: dict[str, Any] = {"headers": resolved_headers}
                if body:
                    kwargs["data"] = body
                async with session.request(_method, url, **kwargs) as resp:
                    resp.raise_for_status()
                    text = await resp.text()
                    if _response_path:
                        try:
                            data = json.loads(text)
                            for part in _response_path.split("."):
                                if isinstance(data, dict):
                                    data = data.get(part, "")
                                elif isinstance(data, list) and part.isdigit():
                                    data = data[int(part)]
                                else:
                                    data = ""
                            text = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else str(data)
                        except (KeyError, IndexError, json.JSONDecodeError):
                            pass
                    return text
        except Exception as exc:
            return f"HTTP error: {exc}"

    return _http_handler


def _make_shell_handler(
    command: str,
    allowed_commands: list[str],
    allowed_paths: list[str] | None = None,
    working_dir: str = "/tmp",
    env_whitelist: list[str] | None = None,
) -> Any:
    """Create a shell command handler callable with safety checks."""

    _command = command
    _allowed_commands = allowed_commands
    _allowed_paths = allowed_paths or []
    _working_dir = working_dir
    _env_whitelist = env_whitelist or []

    def _check_params(params: dict[str, Any]) -> str | None:
        for key, value in params.items():
            str_value = str(value)
            if _has_metacharacters(str_value):
                return (
                    f"Blocked: parameter '{key}' contains forbidden "
                    f"shell metacharacters in value: {str_value!r}. "
                    f"Characters ;&&|`$() are not allowed."
                )
        return None

    def _check_command(resolved_cmd: str) -> str | None:
        first_word = resolved_cmd.strip().split()[0] if resolved_cmd.strip() else ""
        first_cmd = os.path.basename(first_word)
        if first_cmd not in _allowed_commands:
            return (
                f"Blocked: command '{first_cmd}' is not in allowed_commands: "
                f"{_allowed_commands}"
            )
        return None

    def _shell_handler(**params: Any) -> str:
        check = _check_params(params)
        if check is not None:
            return check

        resolved_cmd = _interpolate_variables(
            _command, params, dict(os.environ), {}
        )

        cmd_check = _check_command(resolved_cmd)
        if cmd_check is not None:
            return cmd_check

        try:
            result = subprocess.run(
                resolved_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=_working_dir,
            )
            output = result.stdout.strip()
            if result.stderr:
                output += f"\n{result.stderr.strip()}" if output else result.stderr.strip()
            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: command timed out"
        except Exception as exc:
            return f"Error executing command: {exc}"

    return _shell_handler


def _build_params(raw_params: dict[str, Any]) -> list[ToolParam]:
    """Convert a raw parameter dict to a list of ToolParam objects."""
    params: list[ToolParam] = []
    for name, spec in (raw_params or {}).items():
        ptype = spec.get("type", "string")
        params.append(ToolParam(
            name=name,
            type=ptype,
            description=spec.get("description", ""),
            required=spec.get("required", False),
            default=spec.get("default", _UNSET),
            enum=spec.get("enum"),
        ))
    return params


def _build_retry_policy(raw: dict[str, Any] | None) -> RetryPolicy | None:
    if raw is None:
        return None
    return RetryPolicy(
        max_retries=raw.get("max_retries", 3),
        backoff=raw.get("backoff", "exponential"),
        initial_delay_seconds=raw.get("initial_delay_seconds", 1.0),
    )


class DeclarativeToolSchema:
    """JSON Schema-based validation for declarative tool definitions."""

    _SCHEMA: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DeclarativeToolFile",
        "type": "object",
        "properties": {
            "tools": {
                "type": "array",
                "items": {"$ref": "#/$defs/DeclarativeTool"},
            }
        },
        "$defs": {
            "DeclarativeTool": {
                "type": "object",
                "required": ["name", "type", "description"],
                "properties": {
                    "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "type": {"enum": ["http", "shell"]},
                    "description": {"type": "string"},
                    "category": {"type": "string", "default": "declarative"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "version": {"type": "string", "default": "1.0.0"},
                    "visibility": {"enum": ["public", "admin", "expert", "user"], "default": "public"},
                    "timeout": {"type": "number", "default": 30},
                    "retry_policy": {
                        "type": "object",
                        "properties": {
                            "max_retries": {"type": "integer", "default": 3},
                            "backoff": {"enum": ["fixed", "exponential"], "default": "exponential"},
                            "initial_delay_seconds": {"type": "number", "default": 1.0},
                        },
                    },
                    "parameters": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "required": ["type"],
                            "properties": {
                                "type": {"type": "string"},
                                "description": {"type": "string"},
                                "default": {},
                                "enum": {"type": "array"},
                                "required": {"type": "boolean", "default": False},
                            },
                        },
                    },
                    "http": {
                        "type": "object",
                        "required": ["method", "url_template"],
                        "properties": {
                            "method": {"enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                            "url_template": {"type": "string"},
                            "headers": {"type": "object"},
                            "body_template": {"type": "string"},
                            "response_path": {"type": "string"},
                            "allowed_hosts": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "shell": {
                        "type": "object",
                        "required": ["command"],
                        "properties": {
                            "command": {"type": "string"},
                            "working_dir": {"type": "string", "default": "/tmp"},
                            "allowed_commands": {"type": "array", "items": {"type": "string"}},
                            "allowed_paths": {"type": "array", "items": {"type": "string"}},
                            "env_whitelist": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        },
    }

    @staticmethod
    def validate_single(tool_data: dict[str, Any]) -> bool:
        """Validate a single tool dict against the schema. Returns True if valid."""
        name = tool_data.get("name", "")
        if not name or not isinstance(name, str):
            return False
        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            return False
        tool_type = tool_data.get("type", "")
        if not tool_data.get("description"):
            return False
        if tool_type not in ("http", "shell"):
            return False
        if tool_type == "http":
            http_cfg = tool_data.get("http", {})
            if not http_cfg.get("method") or not http_cfg.get("url_template"):
                return False
        if tool_type == "shell":
            shell_cfg = tool_data.get("shell", {})
            if not shell_cfg.get("command"):
                return False
        return True


class DeclarativeToolLoader:
    """Loads tool definitions from YAML or JSON files.

    Usage::

        loader = DeclarativeToolLoader()
        tools = loader.load_from_file("tools/admin_tools.yaml")
        # tools is a list[ToolDefinition]

    Supports JSON Schema validation, variable interpolation, and
    auto-generated handlers for HTTP and shell tools.
    """

    def load_from_file(self, filepath: str) -> list[ToolDefinition]:
        """Load tool definitions from a YAML or JSON file.

        Returns a list of ToolDefinition objects (empty if the file
        is invalid or contains no valid tools).
        """
        data = self._read_file(filepath)
        if data is None:
            return []
        tools_data = data.get("tools", [])
        if not isinstance(tools_data, list):
            logger.warning("Invalid tools file: 'tools' must be a list in %s", filepath)
            return []
        return self._parse_tools(tools_data)

    def load_from_dir(self, directory: str) -> list[ToolDefinition]:
        """Load all tool definitions from a directory (YAML/JSON files)."""
        all_tools: list[ToolDefinition] = []
        for ext in ("*.yaml", "*.yml", "*.json"):
            for filepath in glob(os.path.join(directory, ext)):
                all_tools.extend(self.load_from_file(filepath))
            for filepath in glob(os.path.join(directory, "**", ext), recursive=True):
                all_tools.extend(self.load_from_file(filepath))
        return all_tools

    def _read_file(self, filepath: str) -> dict[str, Any] | None:
        """Read and parse a YAML or JSON file."""
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Failed to read tool file %s: %s", filepath, exc)
            return None

        if filepath.endswith((".yaml", ".yml")):
            try:
                import yaml
                data = yaml.safe_load(content)
                return data if isinstance(data, dict) else None
            except ImportError:
                logger.error("pyyaml is required for YAML declarative tools (file: %s)", filepath)
                return None
            except Exception as exc:
                logger.warning("Failed to parse YAML file %s: %s", filepath, exc)
                return None

        if filepath.endswith(".json"):
            try:
                data = json.loads(content)
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError as exc:
                logger.warning("Failed to parse JSON file %s: %s", filepath, exc)
                return None

        logger.warning("Unsupported file format: %s", filepath)
        return None

    def _parse_tools(self, tools_data: list[dict[str, Any]]) -> list[ToolDefinition]:
        """Parse and validate a list of raw tool dicts into ToolDefinitions."""
        result: list[ToolDefinition] = []
        for raw in tools_data:
            if not isinstance(raw, dict):
                continue
            tool = self._parse_single(raw)
            if tool is not None:
                result.append(tool)
        return result

    def _parse_single(self, raw: dict[str, Any]) -> ToolDefinition | None:
        """Parse a single tool dict into a ToolDefinition, or None if invalid."""
        if not DeclarativeToolSchema.validate_single(raw):
            logger.warning("Schema validation failed for tool: %s", raw.get("name", "(unnamed)"))
            return None

        tool_type = raw["type"]

        if tool_type == "http":
            http_cfg = raw.get("http", {})
            handler = _make_http_handler(
                method=http_cfg.get("method", "GET"),
                url_template=http_cfg.get("url_template", ""),
                headers=http_cfg.get("headers"),
                body_template=http_cfg.get("body_template"),
                response_path=http_cfg.get("response_path"),
                allowed_hosts=http_cfg.get("allowed_hosts"),
            )
        elif tool_type == "shell":
            shell_cfg = raw.get("shell", {})
            allowed_commands = shell_cfg.get("allowed_commands", [])
            if not allowed_commands:
                logger.warning(
                    "Shell tool '%s' rejected: allowed_commands whitelist is required",
                    raw.get("name", "(unnamed)"),
                )
                return None

            handler = _make_shell_handler(
                command=shell_cfg.get("command", ""),
                allowed_commands=allowed_commands,
                allowed_paths=shell_cfg.get("allowed_paths"),
                working_dir=shell_cfg.get("working_dir", "/tmp"),
                env_whitelist=shell_cfg.get("env_whitelist"),
            )
        else:
            logger.warning("Unknown tool type: %s", tool_type)
            return None

        visibility_str = raw.get("visibility", "public")
        try:
            visibility = ToolVisibility(visibility_str)
        except ValueError:
            visibility = ToolVisibility.PUBLIC

        return ToolDefinition(
            name=raw["name"],
            description=raw.get("description", ""),
            parameters=_build_params(raw.get("parameters", {})),
            handler=handler if tool_type == "shell" else None,
            async_handler=handler if tool_type == "http" else None,
            category=raw.get("category", "declarative"),
            tags=raw.get("tags", []),
            version=raw.get("version", "1.0.0"),
            visibility=visibility,
            timeout_seconds=raw.get("timeout", 30),
            retry_policy=_build_retry_policy(raw.get("retry_policy")),
            provider="declarative",
        )


class DeclarativeProvider(ToolProvider):
    """Provider for declarative tools (YAML/JSON files).

    Scans TOOLS_DECLARATIVE_DIR for *.yaml, *.yml, and *.json files
    and loads tool definitions from them.
    """

    @property
    def provider_name(self) -> str:
        return "declarative"

    async def discover(self) -> list[ToolDefinition]:
        """Scan TOOLS_DECLARATIVE_DIR and load all declarative tools."""
        loader = DeclarativeToolLoader()
        tools = loader.load_from_dir(TOOLS_DECLARATIVE_DIR)
        logger.info(
            "DeclarativeProvider discovered %d tools from %s",
            len(tools),
            TOOLS_DECLARATIVE_DIR,
        )
        return tools
