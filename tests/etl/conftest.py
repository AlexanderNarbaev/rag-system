"""Shared fixtures for ETL tests.

Provides common configurations, sample data, and mock objects
for all ETL extractor, chunker, indexer, and graph builder tests.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure etl/ is importable
sys.path.insert (0, str (Path (__file__).parent.parent.parent / "etl"))


# ---------------------------------------------------------------------------
# Common extractor configs
# ---------------------------------------------------------------------------


@pytest.fixture
def confluence_config (tmp_path):
  """Minimal Confluence extractor configuration."""
  return {
      "url": "https://confluence.test.local", "username": "bot", "token": "test-token", "space_keys": ["DEV"],
      "output_dir": str (tmp_path / "output"), "wal_file": str (tmp_path / "wal" / "wal.json"),
  }


@pytest.fixture
def jira_config (tmp_path):
  """Minimal Jira extractor configuration."""
  return {
      "url": "https://jira.test.local", "username": "bot", "token": "test-token", "project_keys": ["PROJ"],
      "output_dir": str (tmp_path / "output"), "wal_file": str (tmp_path / "wal" / "wal.json"),
  }


@pytest.fixture
def gitlab_config (tmp_path):
  """Minimal GitLab extractor configuration."""
  return {
      "url": "https://gitlab.test.local", "token": "test-token", "project_ids": [1],
      "output_dir": str (tmp_path / "output"), "wal_file": str (tmp_path / "wal" / "wal.json"),
  }


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_confluence_page ():
  """Sample Confluence page data."""
  return {
      "id": "12345", "title": "Test Page", "space": {"key": "DEV"}, "version": {
          "number": 1, "when": "2025-01-15T10:00:00Z", "by": {"displayName": "Test User"},
      }, "body": {
          "storage": {"value": "<p>Test content with RAG information.</p>"},
          "view": {"value": "<p>Test content with RAG information.</p>"},
      },
  }


@pytest.fixture
def sample_jira_issue ():
  """Sample Jira issue data."""
  return {
      "key": "PROJ-123", "fields": {
          "summary": "Test issue", "description": "Test description", "status": {"name": "Open"},
          "priority": {"name": "High"}, "assignee": {"displayName": "Test User"}, "comment": {"comments": []},
      },
  }


@pytest.fixture
def sample_gitlab_commit ():
  """Sample GitLab commit data."""
  return {
      "id": "abc123def456", "short_id": "abc123d", "title": "Test commit", "message": "Test commit message",
      "author_name": "Test User", "author_email": "test@test.local", "created_at": "2025-01-15T10:00:00Z",
  }


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_requests_session ():
  """Mock requests.Session for extractor HTTP calls."""
  session = MagicMock ()
  response = MagicMock ()
  response.status_code = 200
  response.json.return_value = {"results": []}
  response.text = '{"results": []}'
  response.raise_for_status = MagicMock ()
  session.get.return_value = response
  session.post.return_value = response
  session.headers = {}
  return session
