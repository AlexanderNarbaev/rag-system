"""Comprehensive tests for proxy/app/tools/declarative.py.

Covers _interpolate_variables, _has_metacharacters, _make_http_handler,
_make_shell_handler, _build_params, _build_retry_policy, schema validator,
loader (file/dir/dict paths), and provider.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from proxy.app.tools.declarative import (
    TOOLS_DECLARATIVE_DIR,
    DeclarativeProvider,
    DeclarativeToolLoader,
    DeclarativeToolSchema,
    _build_params,
    _build_retry_policy,
    _has_metacharacters,
    _interpolate_variables,
    _make_http_handler,
    _make_shell_handler,
)

# ---------------------------------------------------------------------------
# _interpolate_variables
# ---------------------------------------------------------------------------


class TestInterpolateVariables:
    def test_no_placeholders(self):
        assert _interpolate_variables("hello", {}, {}, {}) == "hello"

    def test_param_substitution(self):
        result = _interpolate_variables("Hello {{name}}", {"name": "Alice"}, {}, {})
        assert result == "Hello Alice"

    def test_env_var_substitution(self):
        result = _interpolate_variables("Path: {{HOME}}", {}, {"HOME": "/root"}, {})
        assert result == "Path: /root"

    def test_context_substitution(self):
        result = _interpolate_variables(
            "{{CONTEXT.user}}",
            {},
            {},
            {"user": "bob"},
        )
        assert result == "bob"

    def test_param_overrides_env(self):
        # params should win over env
        result = _interpolate_variables(
            "{{X}}",
            {"X": "param-val"},
            {"X": "env-val"},
            {},
        )
        assert result == "param-val"

    def test_unresolved_left_as_is(self):
        result = _interpolate_variables("{{UNKNOWN}}", {}, {}, {})
        assert result == "{{UNKNOWN}}"

    def test_dotted_paths(self):
        # {{a.b}} — split by '.' → key 'a' in params; value 'b' refers to dot-path
        # The function only checks one-level dotting via CONTEXT.
        # For arbitrary dot keys, the parts[0] is not CONTEXT, falls through.
        result = _interpolate_variables(
            "{{a.b}}",
            {"a.b": "value"},
            {},
            {},
        )
        assert result == "value"

    def test_multiple_placeholders(self):
        result = _interpolate_variables(
            "{{a}}-{{b}}",
            {"a": "X", "b": "Y"},
            {},
            {},
        )
        assert result == "X-Y"


# ---------------------------------------------------------------------------
# _has_metacharacters
# ---------------------------------------------------------------------------


class TestHasMetacharacters:
    def test_safe_string(self):
        assert _has_metacharacters("hello") is False

    def test_semicolon(self):
        assert _has_metacharacters("; rm -rf") is True

    def test_ampersand(self):
        assert _has_metacharacters("cmd1 && cmd2") is True

    def test_pipe(self):
        assert _has_metacharacters("cat file | grep") is True

    def test_dollar(self):
        assert _has_metacharacters("$(date)") is True

    def test_backtick(self):
        assert _has_metacharacters("`cmd`") is True

    def test_paren(self):
        assert _has_metacharacters("(subshell)") is True


# ---------------------------------------------------------------------------
# _build_params / _build_retry_policy
# ---------------------------------------------------------------------------


class TestBuildParams:
    def test_empty_input(self):
        assert _build_params({}) == []
        assert _build_params(None) == []

    def test_simple_param(self):
        params = _build_params({"x": {"type": "string"}})
        assert len(params) == 1
        assert params[0].name == "x"
        assert params[0].type == "string"
        assert params[0].required is False  # default

    def test_with_explicit_required(self):
        params = _build_params(
            {"x": {"type": "string", "required": True, "description": "the x"}},
        )
        assert params[0].required is True
        assert params[0].description == "the x"

    def test_multiple(self):
        params = _build_params(
            {
                "a": {"type": "int"},
                "b": {"type": "float"},
            },
        )
        assert len(params) == 2


class TestBuildRetryPolicy:
    def test_none_returns_none(self):
        assert _build_retry_policy(None) is None

    def test_defaults(self):
        rp = _build_retry_policy({})
        assert rp.max_retries == 3
        assert rp.backoff == "exponential"
        assert rp.initial_delay_seconds == 1.0

    def test_explicit(self):
        rp = _build_retry_policy(
            {"max_retries": 5, "backoff": "fixed", "initial_delay_seconds": 2.0},
        )
        assert rp.max_retries == 5
        assert rp.backoff == "fixed"
        assert rp.initial_delay_seconds == 2.0


# ---------------------------------------------------------------------------
# DeclarativeToolSchema.validate_single
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_valid_http_tool(self):
        d = {
            "name": "search",
            "type": "http",
            "description": "search tool",
            "http": {"method": "GET", "url_template": "https://example.com"},
        }
        assert DeclarativeToolSchema.validate_single(d) is True

    def test_valid_shell_tool(self):
        d = {
            "name": "ls_files",
            "type": "shell",
            "description": "list files",
            "shell": {"command": "ls -la"},
        }
        assert DeclarativeToolSchema.validate_single(d) is True

    def test_missing_name(self):
        d = {
            "type": "http",
            "description": "x",
            "http": {"method": "GET", "url_template": "http://x"},
        }
        assert DeclarativeToolSchema.validate_single(d) is False

    def test_invalid_name_pattern(self):
        d = {
            "name": "Has-Capital",
            "type": "http",
            "description": "x",
            "http": {"method": "GET", "url_template": "x"},
        }
        assert DeclarativeToolSchema.validate_single(d) is False

    def test_name_starts_with_underscore_invalid(self):
        d = {
            "name": "_bad",
            "type": "http",
            "description": "x",
            "http": {"method": "GET", "url_template": "x"},
        }
        assert DeclarativeToolSchema.validate_single(d) is False

    def test_missing_description(self):
        d = {
            "name": "good",
            "type": "http",
            "http": {"method": "GET", "url_template": "x"},
        }
        assert DeclarativeToolSchema.validate_single(d) is False

    def test_unknown_type(self):
        d = {
            "name": "good",
            "type": "binary",
            "description": "x",
        }
        assert DeclarativeToolSchema.validate_single(d) is False

    def test_http_missing_method(self):
        d = {
            "name": "good",
            "type": "http",
            "description": "x",
            "http": {"url_template": "http://x"},
        }
        assert DeclarativeToolSchema.validate_single(d) is False

    def test_shell_missing_command(self):
        d = {
            "name": "good",
            "type": "shell",
            "description": "x",
            "shell": {},
        }
        assert DeclarativeToolSchema.validate_single(d) is False


# ---------------------------------------------------------------------------
# _make_http_handler
# ---------------------------------------------------------------------------


class TestHttpHandler:
    def test_returns_callable(self):
        handler = _make_http_handler(
            method="GET",
            url_template="https://example.com",
        )
        assert callable(handler)
        # Should be async
        import inspect

        assert inspect.iscoroutinefunction(handler)

    def test_blocked_host_returns_error(self):
        handler = _make_http_handler(
            method="GET",
            url_template="https://blocked.com/path",
            allowed_hosts=["safe.com"],
        )
        result = asyncio.run(handler())
        assert "not in allowed_hosts" in result

    def test_allowed_host_passes_check(self):
        handler = _make_http_handler(
            method="GET",
            url_template="https://safe.com/path",
            allowed_hosts=["safe.com"],
        )
        # Should not raise, but will fail due to network — still returns error str
        result = asyncio.run(handler())
        # Either "Error: URL host" or actual http error — but no blocked
        assert "not in allowed_hosts" not in result

    def test_subdomain_matching(self):
        handler = _make_http_handler(
            method="GET",
            url_template="https://api.safe.com/path",
            allowed_hosts=["safe.com"],
        )
        result = asyncio.run(handler())
        # Subdomains should match — no "not in allowed_hosts" error
        assert "not in allowed_hosts" not in result


# ---------------------------------------------------------------------------
# _make_shell_handler
# ---------------------------------------------------------------------------


class TestShellHandler:
    def test_returns_callable(self):
        handler = _make_shell_handler(command="ls", allowed_commands=["ls"])
        assert callable(handler)

    def test_blocked_metacharacter(self):
        handler = _make_shell_handler(
            command="ls {{path}}",
            allowed_commands=["ls"],
        )
        # Path with ; should be blocked
        result = handler(path="; rm -rf /")
        assert "metacharacters" in result

    def test_blocked_command(self):
        handler = _make_shell_handler(
            command="evil_cmd",
            allowed_commands=["ls"],
        )
        result = handler()
        assert "not in allowed_commands" in result

    def test_successful_shell_run(self):
        handler = _make_shell_handler(
            command="echo hello",
            allowed_commands=["echo"],
        )
        result = handler()
        assert "hello" in result

    def test_command_timeout_returns_error(self):
        handler = _make_shell_handler(
            command="sleep 99",
            allowed_commands=["sleep"],
        )
        # Set short timeout via direct call won't work; patch subprocess.run
        with patch("proxy.app.tools.declarative.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep", timeout=30)
            result = handler()
        assert "timed out" in result

    def test_subprocess_raises_returns_error(self):
        handler = _make_shell_handler(
            command="ls",
            allowed_commands=["ls"],
        )
        with patch("proxy.app.tools.declarative.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("nope")
            result = handler()
        assert "Error executing" in result


# ---------------------------------------------------------------------------
# DeclarativeToolLoader
# ---------------------------------------------------------------------------


class TestDeclarativeLoader:
    def test_load_from_yaml_file(self, tmp_path: Path):
        yaml_content = """
tools:
  - name: search
    type: http
    description: search
    http:
      method: GET
      url_template: "https://api.example.com/search?q={{q}}"
"""
        (tmp_path / "tool.yaml").write_text(yaml_content, encoding="utf-8")
        loader = DeclarativeToolLoader()
        tools = loader.load_from_file(str(tmp_path / "tool.yaml"))
        assert len(tools) == 1
        assert tools[0].name == "search"
        assert tools[0].provider == "declarative"

    def test_load_from_json_file(self, tmp_path: Path):
        data = {
            "tools": [
                {
                    "name": "ls",
                    "type": "shell",
                    "description": "list files",
                    "shell": {"command": "ls -la", "allowed_commands": ["ls"]},
                },
            ],
        }
        (tmp_path / "tool.json").write_text(json.dumps(data), encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "tool.json"))
        assert len(tools) == 1

    def test_load_invalid_yaml_returns_empty(self, tmp_path: Path):
        (tmp_path / "bad.yaml").write_text("not valid yaml: : :", encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "bad.yaml"))
        assert tools == []

    def test_load_invalid_json_returns_empty(self, tmp_path: Path):
        (tmp_path / "bad.json").write_text("not valid json", encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "bad.json"))
        assert tools == []

    def test_load_unsupported_extension(self, tmp_path: Path):
        (tmp_path / "tool.txt").write_text("anything", encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "tool.txt"))
        assert tools == []

    def test_load_missing_file(self):
        tools = DeclarativeToolLoader().load_from_file("/nonexistent/file.yaml")
        assert tools == []

    def test_load_non_dict_tools(self, tmp_path: Path):
        (tmp_path / "x.json").write_text('{"tools": "not a list"}', encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "x.json"))
        assert tools == []

    def test_load_invalid_tool_skipped(self, tmp_path: Path):
        data = {
            "tools": [
                # valid
                {
                    "name": "valid_one",
                    "type": "http",
                    "description": "ok",
                    "http": {"method": "GET", "url_template": "http://x"},
                },
                # invalid (no name)
                {
                    "type": "http",
                    "description": "no name",
                    "http": {"method": "GET", "url_template": "http://x"},
                },
            ],
        }
        (tmp_path / "x.json").write_text(json.dumps(data), encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "x.json"))
        # Only valid tool loaded
        assert len(tools) == 1

    def test_load_shell_without_allowed_commands_rejected(self, tmp_path: Path):
        data = {
            "tools": [
                {
                    "name": "shell_unsafe",
                    "type": "shell",
                    "description": "danger",
                    "shell": {"command": "rm -rf /"},
                },
            ],
        }
        (tmp_path / "x.json").write_text(json.dumps(data), encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "x.json"))
        # No allowed_commands → rejected
        assert tools == []

    def test_load_unknown_type(self, tmp_path: Path):
        data = {
            "tools": [
                {
                    "name": "weird",
                    "type": "unknown_type",
                    "description": "x",
                },
            ],
        }
        (tmp_path / "x.json").write_text(json.dumps(data), encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "x.json"))
        assert tools == []

    def test_load_invalid_visibility_defaults_to_public(self, tmp_path: Path):
        data = {
            "tools": [
                {
                    "name": "t",
                    "type": "http",
                    "description": "x",
                    "visibility": "bogus-level",
                    "http": {"method": "GET", "url_template": "http://x"},
                },
            ],
        }
        (tmp_path / "x.json").write_text(json.dumps(data), encoding="utf-8")
        tools = DeclarativeToolLoader().load_from_file(str(tmp_path / "x.json"))
        assert len(tools) == 1
        assert tools[0].visibility.value == "public"

    def test_load_from_dir_recursive(self, tmp_path: Path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (tmp_path / "a.yaml").write_text(
            "tools:\n  - name: a\n    type: http\n    description: ok\n"
            "    http: {method: GET, url_template: 'http://x'}\n",
            encoding="utf-8",
        )
        (subdir / "b.json").write_text(
            json.dumps(
                {
                    "tools": [
                        {
                            "name": "b",
                            "type": "http",
                            "description": "ok",
                            "http": {"method": "GET", "url_template": "http://x"},
                        },
                    ],
                },
            ),
            encoding="utf-8",
        )
        tools = DeclarativeToolLoader().load_from_dir(str(tmp_path))
        names = {t.name for t in tools}
        assert names == {"a", "b"}


# ---------------------------------------------------------------------------
# DeclarativeProvider
# ---------------------------------------------------------------------------


class TestDeclarativeProvider:
    def test_provider_name(self):
        assert DeclarativeProvider().provider_name == "declarative"

    def test_discover_no_tools_dir(self, tmp_path: Path):
        with patch.object(
            __import__("proxy.app.tools.declarative", fromlist=["TOOLS_DECLARATIVE_DIR"]),
            "TOOLS_DECLARATIVE_DIR",
            str(tmp_path / "nonexistent"),
        ):
            tools = asyncio.run(DeclarativeProvider().discover())
        assert tools == []

    def test_discover_finds_tools(self, tmp_path: Path):
        (tmp_path / "tool.json").write_text(
            json.dumps(
                {
                    "tools": [
                        {
                            "name": "my_discover_tool",
                            "type": "http",
                            "description": "x",
                            "http": {"method": "GET", "url_template": "http://x"},
                        },
                    ],
                },
            ),
            encoding="utf-8",
        )
        with patch(
            "proxy.app.tools.declarative.TOOLS_DECLARATIVE_DIR",
            str(tmp_path),
        ):
            tools = asyncio.run(DeclarativeProvider().discover())
        # Verify the tool we created is in the discovery result
        names = {t.name for t in tools}
        assert "my_discover_tool" in names


# ---------------------------------------------------------------------------
# TOOLS_DECLARATIVE_DIR constant
# ---------------------------------------------------------------------------


class TestToolsDeclarativeDir:
    def test_default_path(self):
        # TOOLS_DECLARATIVE_DIR is a module-level constant
        assert isinstance(TOOLS_DECLARATIVE_DIR, str)
