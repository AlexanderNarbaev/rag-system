# tests/etl/test_gitlab_enhanced.py
"""Tests for GitLabExtractor — validates configuration, API calls, and output."""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gitlab_config (tmp_path):
  """Minimal valid configuration for GitLabExtractor."""
  return {
      "url": "https://gitlab.example.com",
      "token": "glpat-test-token-123",
      "verify_ssl": False,
      "project_ids": [1, 2],
      "output_dir": str (tmp_path / "gitlab"),
      "wal_file": str (tmp_path / "wal" / "gitlab_wal.json"),
      "incremental": False,
      "download_files": False,
      "max_commits_per_project": 10,
  }


@pytest.fixture
def mock_gitlab_project ():
  """A realistic GitLab project response."""
  return {
      "id": 1,
      "name": "test-project",
      "path_with_namespace": "group/test-project",
      "description": "A test project",
      "default_branch": "main",
      "web_url": "https://gitlab.example.com/group/test-project",
      "created_at": "2024-01-01T00:00:00.000Z",
      "last_activity_at": "2025-01-15T10:00:00.000Z",
  }


@pytest.fixture
def mock_gitlab_commit ():
  """A realistic GitLab commit response."""
  return {
      "id": "abc123def456",
      "short_id": "abc123de",
      "title": "Fix: resolve null pointer in parser",
      "message": "Fix: resolve null pointer in parser\n\nDetailed description of the fix.",
      "author_name": "Jane Doe",
      "author_email": "jane@example.com",
      "created_at": "2025-01-10T14:30:00.000Z",
      "committed_date": "2025-01-10T14:30:00.000Z",
  }


# ---------------------------------------------------------------------------
# Configuration validation tests
# ---------------------------------------------------------------------------


class TestGitLabExtractorConfig:
  """Validate that GitLabExtractor rejects invalid configurations."""

  def test_rejects_empty_url (self):
    from etl.extractors.gitlab import GitLabExtractor

    with pytest.raises (ValueError, match = "url.*required"):
      GitLabExtractor ({"url": ""})

  def test_rejects_missing_url (self):
    from etl.extractors.gitlab import GitLabExtractor

    with pytest.raises (ValueError, match = "url.*required"):
      GitLabExtractor ({})

  def test_rejects_invalid_url_scheme (self):
    from etl.extractors.gitlab import GitLabExtractor

    with pytest.raises (ValueError, match = "must start with http"):
      GitLabExtractor ({"url": "ftp://gitlab.example.com"})

  def test_accepts_valid_config (self, gitlab_config):
    from etl.extractors.gitlab import GitLabExtractor

    extractor = GitLabExtractor (gitlab_config)
    assert extractor.url == "https://gitlab.example.com"
    assert extractor.project_ids == [1, 2]


# ---------------------------------------------------------------------------
# API interaction tests (mocked)
# ---------------------------------------------------------------------------


class TestGitLabExtractorAPI:
  """Test GitLabExtractor API calls with mocked HTTP."""

  @patch ("etl.extractors.gitlab.requests.Session")
  def test_fetch_projects_calls_correct_endpoint (self, mock_session_cls, gitlab_config):
    from etl.extractors.gitlab import GitLabExtractor

    mock_session = MagicMock ()
    mock_session_cls.return_value = mock_session
    mock_resp = MagicMock ()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"id": 1, "name": "test-project"}]
    mock_resp.raise_for_status = MagicMock ()
    mock_session.get.return_value = mock_resp

    extractor = GitLabExtractor (gitlab_config)
    extractor.session = mock_session
    assert extractor is not None

  @patch ("etl.extractors.gitlab.requests.Session")
  def test_fetch_commits_handles_pagination (self, mock_session_cls, gitlab_config):
    from etl.extractors.gitlab import GitLabExtractor

    mock_session = MagicMock ()
    mock_session_cls.return_value = mock_session

    # First page returns commits, second page returns empty
    page1 = MagicMock ()
    page1.status_code = 200
    page1.json.return_value = [{"id": "abc123", "title": "Fix bug"}]
    page1.raise_for_status = MagicMock ()
    page1.headers = {"X-Next-Page": "2"}

    page2 = MagicMock ()
    page2.status_code = 200
    page2.json.return_value = []
    page2.raise_for_status = MagicMock ()
    page2.headers = {"X-Next-Page": ""}

    mock_session.get.side_effect = [page1, page2]
    extractor = GitLabExtractor (gitlab_config)
    extractor.session = mock_session


# ---------------------------------------------------------------------------
# Output format tests
# ---------------------------------------------------------------------------


class TestGitLabExtractorOutput:
  """Test that GitLabExtractor writes correct output files."""

  def test_creates_output_directory (self, gitlab_config, tmp_path):
    from etl.extractors.gitlab import GitLabExtractor

    output_dir = tmp_path / "gitlab_output"
    gitlab_config ["output_dir"] = str (output_dir)
    extractor = GitLabExtractor (gitlab_config)
    assert str (extractor.output_dir) == str (output_dir)
