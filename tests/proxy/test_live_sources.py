# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/live_sources.py — Live Confluence/Jira/GitLab API clients."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

sys.path.insert (0, str (Path (__file__).parent.parent.parent / "proxy"))


# ── Helpers ──


def make_mock_response (status = 200, json_data = None, text_data = ""):
  resp = AsyncMock ()
  resp.status = status
  resp.json = AsyncMock (return_value = json_data or {})
  resp.text = AsyncMock (return_value = text_data)
  resp.__aenter__ = AsyncMock (return_value = resp)
  resp.__aexit__ = AsyncMock (return_value = None)
  return resp


def make_mock_session (post_response = None, get_response = None):
  session = AsyncMock ()
  session.__aenter__ = AsyncMock (return_value = session)
  session.__aexit__ = AsyncMock (return_value = None)
  session.post = MagicMock (return_value = post_response or make_mock_response ())
  session.get = MagicMock (return_value = get_response or make_mock_response ())
  return session


# ── F2: ConfluenceLiveClient ──


def _enable_client (client_obj):
  """Patch _enabled property to return True on a live-source client instance."""
  return patch.object (client_obj.__class__, "_enabled", new_callable = PropertyMock, return_value = True)


class TestConfluenceLiveClient:
  @pytest.fixture
  def client (self):
    with patch ("proxy.app.core.live_sources.CONFLUENCE_API_URL", "https://confluence.example.com/rest/api"):
      with patch ("proxy.app.core.live_sources.CONFLUENCE_API_TOKEN", "test-token"):
        with patch ("proxy.app.core.live_sources.CONFLUENCE_API_USER", "testuser@example.com"):
          from proxy.app.core.live_sources import ConfluenceLiveClient

          c = ConfluenceLiveClient ()
          return c

  def test_init_with_config (self, client):
    assert client.base_url == "https://confluence.example.com/rest/api"
    assert "Authorization" in client.headers

  @pytest.mark.asyncio
  async def test_search_confluence_success (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {
        "results": [
            {"id": "123", "title": "RAG Guide", "type": "page", "space": {"key": "DEV"}},
            {"id": "456", "title": "API Docs", "type": "page", "space": {"key": "ENG"}},
        ], "size": 2,
    }))

    with _enable_client (client), patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_confluence ("RAG", max_results = 5)
      assert len (results) == 2
      assert results [0].id == "123"
      assert results [0].title == "RAG Guide"
      assert results [0].space_key == "DEV"

  @pytest.mark.asyncio
  async def test_search_confluence_empty (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {"results": [], "size": 0}))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_confluence ("nothing", max_results = 5)
      assert results == []

  @pytest.mark.asyncio
  async def test_search_confluence_api_error_graceful (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (status = 500, text_data = "Internal error"))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_confluence ("query", max_results = 5)
      assert results == []

  @pytest.mark.asyncio
  async def test_search_confluence_timeout_graceful (self, client):
    with patch ("aiohttp.ClientSession") as mock_sess_cls:
      mock_sess_cls.side_effect = TimeoutError ("Connection timed out")
      results = await client.search_confluence ("query", max_results = 5)
      assert results == []

  @pytest.mark.asyncio
  async def test_get_confluence_page_success (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {
        "id": "123", "title": "RAG Guide", "type": "page", "space": {"key": "DEV", "name": "Development"},
        "body": {"view": {"value": "<p>RAG content here</p>"}},
    }))

    with _enable_client (client), patch ("aiohttp.ClientSession", return_value = mock_session):
      page = await client.get_confluence_page ("123")
      assert page is not None
      assert page.id == "123"
      assert page.title == "RAG Guide"
      assert "RAG content here" in page.body

  @pytest.mark.asyncio
  async def test_get_confluence_page_not_found (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (status = 404))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      page = await client.get_confluence_page ("999")
      assert page is None

  @pytest.mark.asyncio
  async def test_search_confluence_cache_hit (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {
        "results": [{"id": "1", "title": "Cached", "type": "page", "space": {"key": "DEV"}}], "size": 1,
    }))

    with _enable_client (client), patch ("aiohttp.ClientSession", return_value = mock_session):
      r1 = await client.search_confluence ("Cached", max_results = 5)
      assert len (r1) == 1
      r2 = await client.search_confluence ("Cached", max_results = 5)
      assert len (r2) == 1


# ── F3: JiraLiveClient ──


class TestJiraLiveClient:
  @pytest.fixture
  def client (self):
    with patch ("proxy.app.core.live_sources.JIRA_API_URL", "https://jira.example.com/rest/api/2"):
      with patch ("proxy.app.core.live_sources.JIRA_API_TOKEN", "test-api-token"):
        with patch ("proxy.app.core.live_sources.JIRA_API_USER", "testuser@example.com"):
          from proxy.app.core.live_sources import JiraLiveClient

          return JiraLiveClient ()

  def test_init_with_config (self, client):
    assert client.base_url == "https://jira.example.com/rest/api/2"
    assert "Authorization" in client.headers

  @pytest.mark.asyncio
  async def test_search_jira_success (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {
        "issues": [
            {
                "id": "10001", "key": "DEV-123", "fields": {
                "summary": "Add RAG integration", "description": "Implement RAG search",
                "status": {"name": "In Progress"}, "priority": {"name": "High"},
            },
            },
        ], "total": 1,
    }))

    with _enable_client (client), patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_jira ("RAG", max_results = 5)
      assert len (results) == 1
      assert results [0].key == "DEV-123"
      assert results [0].summary == "Add RAG integration"
      assert results [0].status == "In Progress"

  @pytest.mark.asyncio
  async def test_search_jira_empty (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {"issues": [], "total": 0}))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_jira ("nothing", max_results = 5)
      assert results == []

  @pytest.mark.asyncio
  async def test_search_jira_api_error_graceful (self, client):
    mock_session = make_mock_session (
      get_response = make_mock_response (status = 503, text_data = "Service Unavailable"))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_jira ("query", max_results = 5)
      assert results == []

  @pytest.mark.asyncio
  async def test_get_jira_issue_success (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {
        "id": "10001", "key": "DEV-123", "fields": {
            "summary": "Add RAG integration", "description": "Implement RAG search", "status": {"name": "In Progress"},
            "priority": {"name": "High"}, "assignee": {"displayName": "Ivan Ivanov"}, "issuetype": {"name": "Task"},
        },
    }))

    with _enable_client (client), patch ("aiohttp.ClientSession", return_value = mock_session):
      issue = await client.get_jira_issue ("DEV-123")
      assert issue is not None
      assert issue.key == "DEV-123"
      assert issue.assignee == "Ivan Ivanov"
      assert issue.issue_type == "Task"

  @pytest.mark.asyncio
  async def test_get_jira_issue_not_found (self, client):
    mock_session = make_mock_session (
        get_response = make_mock_response (status = 404, text_data = '{"errorMessages":["Issue does not exist"]}'))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      issue = await client.get_jira_issue ("NONEXIST-1")
      assert issue is None


# ── F4: GitLabLiveClient ──


class TestGitLabLiveClient:
  @pytest.fixture
  def client (self):
    with patch ("proxy.app.core.live_sources.GITLAB_API_URL", "https://gitlab.example.com/api/v4"):
      with patch ("proxy.app.core.live_sources.GITLAB_API_TOKEN", "glpat-test-token"):
        from proxy.app.core.live_sources import GitLabLiveClient

        return GitLabLiveClient ()

  def test_init_with_config (self, client):
    assert client.base_url == "https://gitlab.example.com/api/v4"
    assert client.headers ["PRIVATE-TOKEN"] == "glpat-test-token"

  @pytest.mark.asyncio
  async def test_search_gitlab_success (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = [
        {
            "id": 1, "name": "RAG System", "path_with_namespace": "team/rag-system", "description": "Corporate RAG",
        }, {"id": 2, "name": "ML Pipeline", "path_with_namespace": "team/ml-pipeline", "description": ""},
    ]))

    with _enable_client (client), patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_gitlab ("RAG", max_results = 5)
      assert len (results) == 2
      assert results [0].id == "1"
      assert results [0].name == "RAG System"

  @pytest.mark.asyncio
  async def test_search_gitlab_empty (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = []))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_gitlab ("nothing", max_results = 5)
      assert results == []

  @pytest.mark.asyncio
  async def test_search_gitlab_api_error_graceful (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (status = 403, text_data = "Forbidden"))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      results = await client.search_gitlab ("query", max_results = 5)
      assert results == []

  @pytest.mark.asyncio
  async def test_get_gitlab_file_success (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {
        "file_name": "README.md", "file_path": "README.md", "size": 1234,
        "content": "IyBSQUcgU3lzdGVtCgpUaGlzIGlzIHRoZSBSQUcgc3lzdGVtLg==", "encoding": "base64", "ref": "main",
    }))

    with _enable_client (client), patch ("aiohttp.ClientSession", return_value = mock_session):
      file_obj = await client.get_gitlab_file ("1", "README.md", ref = "main")
      assert file_obj is not None
      assert file_obj.file_path == "README.md"
      assert "RAG System" in file_obj.content

  @pytest.mark.asyncio
  async def test_get_gitlab_file_not_found (self, client):
    mock_session = make_mock_session (
        get_response = make_mock_response (status = 404, text_data = '{"message":"404 File not found"}'))

    with patch ("aiohttp.ClientSession", return_value = mock_session):
      file_obj = await client.get_gitlab_file ("1", "missing.py", ref = "main")
      assert file_obj is None

  @pytest.mark.asyncio
  async def test_get_gitlab_file_plain_text (self, client):
    mock_session = make_mock_session (get_response = make_mock_response (json_data = {
        "file_name": "config.py", "file_path": "config.py", "size": 100, "content": "print('hello')",
        "encoding": "text", "ref": "main",
    }))

    with _enable_client (client), patch ("aiohttp.ClientSession", return_value = mock_session):
      file_obj = await client.get_gitlab_file ("1", "config.py", ref = "main")
      assert file_obj is not None
      assert file_obj.content == "print('hello')"


# ── Caching ──


class TestLiveSourceCaching:
  @pytest.mark.asyncio
  async def test_cache_ttl_expiry (self):
    """Verify that cache expires after TTL."""
    with (
      patch ("proxy.app.core.live_sources.CONFLUENCE_API_URL", "https://c.example.com/rest/api"), patch (
        "proxy.app.core.live_sources.CONFLUENCE_API_TOKEN", "tok"), patch (
        "proxy.app.core.live_sources.CONFLUENCE_API_USER", "user"), ):
      from proxy.app.core.live_sources import ConfluenceLiveClient

      client = ConfluenceLiveClient ()

      client._cache ["key"] = (["cached"], 0)

      result = client._get_from_cache ("key")
      assert result is None
