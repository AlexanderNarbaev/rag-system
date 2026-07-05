"""Tests for proxy/app/tools/declarative.py — YAML/JSON Declarative Tools."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "proxy" / "app"))

YAML_AVAILABLE = True
try:
    import yaml
except ImportError:
    YAML_AVAILABLE = False


@pytest.fixture
def yaml_http_shell_content() -> str:
    return """tools:
  - name: "jira_search_live"
    type: "http"
    description: "Search Jira issues live via REST API"
    category: "live_source"
    tags: ["jira", "live"]
    visibility: "user"
    timeout: 15
    parameters:
      query:
        type: "string"
        description: "JQL search text"
        required: true
      max_results:
        type: "integer"
        description: "Max results"
        default: 5
    http:
      method: "GET"
      url_template: "https://{{JIRA_HOST}}/search"
      headers:
        Authorization: "Basic {{JIRA_AUTH}}"
        Accept: "application/json"
      allowed_hosts:
        - "{{JIRA_HOST}}"

  - name: "system_stats"
    type: "shell"
    description: "Get system resource usage"
    category: "admin"
    visibility: "admin"
    timeout: 5
    shell:
      command: "df -h / | tail -1"
      allowed_commands: ["df", "tail"]
      working_dir: "/tmp"
"""


@pytest.fixture
def yaml_malformed_tool() -> str:
    return """tools:
  - name: "bad_tool"
    type: "unknown_type"
    description: "This should be rejected"
"""


@pytest.fixture
def yaml_shell_no_whitelist() -> str:
    return """tools:
  - name: "bad_shell"
    type: "shell"
    description: "No whitelist"
    shell:
      command: "rm -rf /"
"""


@pytest.fixture
def tmp_yaml_dir(yaml_http_shell_content, yaml_malformed_tool, yaml_shell_no_whitelist):
    """Create a temporary directory with declarative tool YAML files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "tools.yaml").write_text(yaml_http_shell_content)
        (base / "extra.yml").write_text(yaml_http_shell_content)
        (base / "malformed.yaml").write_text(yaml_malformed_tool)
        (base / "no_whitelist.yaml").write_text(yaml_shell_no_whitelist)
        (base / "tools.json").write_text(
            json.dumps({"tools": [
                {
                    "name": "json_tool",
                    "type": "http",
                    "description": "A JSON-defined tool",
                    "http": {
                        "method": "GET",
                        "url_template": "https://api.example.com/data"
                    }
                }
            ]})
        )
        yield str(tmpdir)


class TestInterpolateVariables:
    def test_simple_env_var(self):
        from tools.declarative import _interpolate_variables

        result = _interpolate_variables(
            "Hello {{NAME}}",
            params={},
            env_vars={"NAME": "World"},
            context={},
        )
        assert result == "Hello World"

    def test_param_substitution(self):
        from tools.declarative import _interpolate_variables

        result = _interpolate_variables(
            "https://{{HOST}}/search?q={{query}}",
            params={"query": "test", "max_results": 5},
            env_vars={"HOST": "example.com"},
            context={},
        )
        assert result == "https://example.com/search?q=test"

    def test_context_substitution(self):
        from tools.declarative import _interpolate_variables

        result = _interpolate_variables(
            "User: {{CONTEXT.user_id}}",
            params={},
            env_vars={},
            context={"user_id": "user@corp.com"},
        )
        assert result == "User: user@corp.com"

    def test_missing_var_keeps_placeholder(self):
        from tools.declarative import _interpolate_variables

        result = _interpolate_variables(
            "Hello {{MISSING}}",
            params={},
            env_vars={},
            context={},
        )
        assert result == "Hello {{MISSING}}"


class TestDeclarativeToolLoader:
    @pytest.mark.skipif(not YAML_AVAILABLE, reason="pyyaml not installed")
    def test_load_file_yaml(self, yaml_http_shell_content):
        from tools.declarative import DeclarativeToolLoader

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_http_shell_content)
            f.flush()
            path = f.name

        try:
            loader = DeclarativeToolLoader()
            tools = loader.load_from_file(path)
            assert len(tools) == 2
            assert tools[0].name == "jira_search_live"
            assert tools[0].category == "live_source"
            assert tools[0].provider == "declarative"
            assert len(tools[0].parameters) == 2
            assert tools[1].name == "system_stats"
            assert tools[1].visibility.value == "admin"
        finally:
            os.unlink(path)

    def test_load_file_json(self, tmp_yaml_dir):
        from tools.declarative import DeclarativeToolLoader

        loader = DeclarativeToolLoader()
        json_path = f"{tmp_yaml_dir}/tools.json"
        tools = loader.load_from_file(json_path)
        assert len(tools) == 1
        assert tools[0].name == "json_tool"
        assert tools[0].provider == "declarative"

    def test_reject_unknown_type(self, tmp_yaml_dir):
        from tools.declarative import DeclarativeToolLoader

        loader = DeclarativeToolLoader()
        tools = loader.load_from_file(f"{tmp_yaml_dir}/malformed.yaml")
        assert len(tools) == 0

    @pytest.mark.skipif(not YAML_AVAILABLE, reason="pyyaml not installed")
    def test_shell_without_allowed_commands(self, yaml_shell_no_whitelist):
        from tools.declarative import DeclarativeToolLoader

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_shell_no_whitelist)
            f.flush()
            path = f.name

        try:
            loader = DeclarativeToolLoader()
            tools = loader.load_from_file(path)
            assert len(tools) == 0
        finally:
            os.unlink(path)

    def test_shell_blocks_metacharacters(self):
        from tools.declarative import _make_shell_handler

        handler = _make_shell_handler(
            command="df -h {{path}}",
            allowed_commands=["df"],
            allowed_paths=["/"],
        )

        result = handler(path="; rm -rf /")
        assert result is not None
        assert "Blocked" in result

        result = handler(path="/tmp")
        assert result is not None
        assert "Blocked" not in result

    @pytest.mark.asyncio
    async def test_http_handler_mock(self):
        import os as _os

        from tools.declarative import _make_http_handler

        handler = _make_http_handler(
            method="GET",
            url_template="https://{{HOST}}/search?q={{query}}",
            headers={"Accept": "application/json"},
            allowed_hosts=["api.example.com"],
        )

        _os.environ["HOST"] = "api.example.com"

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value='{"results": []}')

        mock_req_ctx = AsyncMock()
        mock_req_ctx.__aenter__.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.request.return_value = mock_req_ctx
        mock_session.__aenter__.return_value = mock_session

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_session

        try:
            with patch("tools.declarative.aiohttp.ClientSession", return_value=mock_client):
                result = await handler(query="test")

            assert mock_session.request.called
            assert result is not None
        finally:
            del _os.environ["HOST"]


class TestDeclarativeProvider:
    def test_provider_name(self):
        from tools.declarative import DeclarativeProvider

        provider = DeclarativeProvider()
        assert provider.provider_name == "declarative"

    @pytest.mark.asyncio
    async def test_discover_scans_dir(self, tmp_yaml_dir):
        from tools.declarative import DeclarativeProvider

        with patch("tools.declarative.TOOLS_DECLARATIVE_DIR", tmp_yaml_dir):
            provider = DeclarativeProvider()
            tools = await provider.discover()

        names = {t.name for t in tools}
        assert "jira_search_live" in names
        assert "system_stats" in names
        assert "json_tool" in names
        assert "bad_tool" not in names
        assert "bad_shell" not in names


class TestDeclarativeToolSchema:
    def test_validate_valid_http(self):
        from tools.declarative import DeclarativeToolSchema

        valid = {
            "name": "test_api",
            "type": "http",
            "description": "A test API",
            "http": {"method": "GET", "url_template": "https://example.com/api"},
        }
        assert DeclarativeToolSchema.validate_single(valid) is True

    def test_validate_rejects_missing_name(self):
        from tools.declarative import DeclarativeToolSchema

        invalid = {"type": "http", "description": "No name"}
        assert DeclarativeToolSchema.validate_single(invalid) is False

    def test_validate_rejects_bad_name(self):
        from tools.declarative import DeclarativeToolSchema

        invalid = {"name": "123bad", "type": "http", "description": "Bad name"}
        assert DeclarativeToolSchema.validate_single(invalid) is False
