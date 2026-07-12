# tests/etl/test_extractor_validation_wal.py
"""Tests for ETL extractor improvements: input validation, WAL corruption handling."""

import json
import logging

import pytest

from etl.extractors.confluence import ConfluenceExtractor
from etl.extractors.gitlab import GitLabExtractor
from etl.extractors.jira import JiraExtractor

# ---------------------------------------------------------------------------
# Input Validation Tests — ConfluenceExtractor
# ---------------------------------------------------------------------------


class TestConfluenceInputValidation:
    """ConfluenceExtractor should reject invalid config at construction time."""

    def test_empty_url_raises_value_error(self, tmp_path):
        config = {
            "url": "",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            ConfluenceExtractor(config)

    def test_whitespace_only_url_raises_value_error(self, tmp_path):
        config = {
            "url": "   ",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            ConfluenceExtractor(config)

    def test_missing_url_raises_value_error(self, tmp_path):
        config = {
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            ConfluenceExtractor(config)

    def test_invalid_url_format_raises_value_error(self, tmp_path):
        config = {
            "url": "ftp://confluence.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            ConfluenceExtractor(config)

    def test_url_without_scheme_raises_value_error(self, tmp_path):
        config = {
            "url": "confluence.test.local",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            ConfluenceExtractor(config)

    def test_empty_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://confluence.test",
            "token": "",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            ConfluenceExtractor(config)

    def test_whitespace_only_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://confluence.test",
            "token": "   ",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            ConfluenceExtractor(config)

    def test_missing_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://confluence.test",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            ConfluenceExtractor(config)

    def test_valid_http_url_does_not_raise(self, tmp_path):
        config = {
            "url": "http://confluence.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        extractor = ConfluenceExtractor(config)
        assert extractor.url == "http://confluence.test"

    def test_valid_https_url_does_not_raise(self, tmp_path):
        config = {
            "url": "https://confluence.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        extractor = ConfluenceExtractor(config)
        assert extractor.url == "https://confluence.test"


# ---------------------------------------------------------------------------
# Input Validation Tests — JiraExtractor
# ---------------------------------------------------------------------------


class TestJiraInputValidation:
    """JiraExtractor should reject invalid config at construction time."""

    def test_empty_url_raises_value_error(self, tmp_path):
        config = {
            "url": "",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            JiraExtractor(config)

    def test_whitespace_only_url_raises_value_error(self, tmp_path):
        config = {
            "url": "   ",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            JiraExtractor(config)

    def test_missing_url_raises_value_error(self, tmp_path):
        config = {
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            JiraExtractor(config)

    def test_invalid_url_format_raises_value_error(self, tmp_path):
        config = {
            "url": "ftp://jira.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            JiraExtractor(config)

    def test_url_without_scheme_raises_value_error(self, tmp_path):
        config = {
            "url": "jira.test.local",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            JiraExtractor(config)

    def test_empty_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://jira.test",
            "token": "",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            JiraExtractor(config)

    def test_whitespace_only_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://jira.test",
            "token": "   ",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            JiraExtractor(config)

    def test_missing_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://jira.test",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            JiraExtractor(config)

    def test_valid_http_url_does_not_raise(self, tmp_path):
        config = {
            "url": "http://jira.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        extractor = JiraExtractor(config)
        assert extractor.url == "http://jira.test"

    def test_valid_https_url_does_not_raise(self, tmp_path):
        config = {
            "url": "https://jira.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        extractor = JiraExtractor(config)
        assert extractor.url == "https://jira.test"


# ---------------------------------------------------------------------------
# Input Validation Tests — GitLabExtractor
# ---------------------------------------------------------------------------


class TestGitLabInputValidation:
    """GitLabExtractor should reject invalid config at construction time."""

    def test_empty_url_raises_value_error(self, tmp_path):
        config = {
            "url": "",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            GitLabExtractor(config)

    def test_whitespace_only_url_raises_value_error(self, tmp_path):
        config = {
            "url": "   ",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            GitLabExtractor(config)

    def test_missing_url_raises_value_error(self, tmp_path):
        config = {
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'url' is required"):
            GitLabExtractor(config)

    def test_invalid_url_format_raises_value_error(self, tmp_path):
        config = {
            "url": "ftp://gitlab.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            GitLabExtractor(config)

    def test_url_without_scheme_raises_value_error(self, tmp_path):
        config = {
            "url": "gitlab.test.local",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="must start with http:// or https://"):
            GitLabExtractor(config)

    def test_empty_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://gitlab.test",
            "token": "",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            GitLabExtractor(config)

    def test_whitespace_only_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://gitlab.test",
            "token": "   ",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            GitLabExtractor(config)

    def test_missing_token_raises_value_error(self, tmp_path):
        config = {
            "url": "https://gitlab.test",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        with pytest.raises(ValueError, match="'token' is required"):
            GitLabExtractor(config)

    def test_valid_http_url_does_not_raise(self, tmp_path):
        config = {
            "url": "http://gitlab.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        extractor = GitLabExtractor(config)
        assert extractor.url == "http://gitlab.test"

    def test_valid_https_url_does_not_raise(self, tmp_path):
        config = {
            "url": "https://gitlab.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        extractor = GitLabExtractor(config)
        assert extractor.url == "https://gitlab.test"


# ---------------------------------------------------------------------------
# WAL Corruption Handling Tests — ConfluenceExtractor
# ---------------------------------------------------------------------------


class TestConfluenceWalCorruption:
    """ConfluenceExtractor._load_wal should handle corrupted files gracefully."""

    def _make_config(self, tmp_path):
        return {
            "url": "https://confluence.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "wal.json"),
        }

    def test_corrupted_json_returns_defaults(self, tmp_path, caplog):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text("not valid json{{{")

        with caplog.at_level(logging.WARNING):
            extractor = ConfluenceExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["pages_hash"] == {}
        assert "corrupted" in caplog.text.lower() or "unreadable" in caplog.text.lower()

    def test_empty_file_returns_defaults(self, tmp_path, caplog):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text("")

        with caplog.at_level(logging.WARNING):
            extractor = ConfluenceExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["pages_hash"] == {}

    def test_missing_wal_file_returns_defaults(self, tmp_path):
        config = self._make_config(tmp_path)
        # WAL file does not exist (tmp_path is fresh)
        extractor = ConfluenceExtractor(config)
        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["pages_hash"] == {}

    def test_valid_wal_file_returns_parsed_data(self, tmp_path):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_data = {
            "last_run": "2025-06-01T00:00:00",
            "pages_hash": {"page_1": "abc123", "page_2": "def456"},
        }
        wal_path.write_text(json.dumps(wal_data))

        extractor = ConfluenceExtractor(config)
        assert extractor.wal_data["last_run"] == "2025-06-01T00:00:00"
        assert extractor.wal_data["pages_hash"]["page_1"] == "abc123"
        assert extractor.wal_data["pages_hash"]["page_2"] == "def456"

    def test_partial_json_returns_defaults(self, tmp_path, caplog):
        """Truncated JSON (e.g., process killed mid-write) should be handled."""
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text('{"last_run": "2025-06-01')  # truncated

        with caplog.at_level(logging.WARNING):
            extractor = ConfluenceExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["pages_hash"] == {}


# ---------------------------------------------------------------------------
# WAL Corruption Handling Tests — JiraExtractor
# ---------------------------------------------------------------------------


class TestJiraWalCorruption:
    """JiraExtractor._load_wal should handle corrupted files gracefully."""

    def _make_config(self, tmp_path):
        return {
            "url": "https://jira.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "wal.json"),
        }

    def test_corrupted_json_returns_defaults(self, tmp_path, caplog):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text("{invalid json!!!")

        with caplog.at_level(logging.WARNING):
            extractor = JiraExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["last_issue_id"] is None
        assert extractor.wal_data["processed_issues"] == []
        assert "corrupted" in caplog.text.lower() or "unreadable" in caplog.text.lower()

    def test_empty_file_returns_defaults(self, tmp_path, caplog):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text("")

        with caplog.at_level(logging.WARNING):
            extractor = JiraExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["processed_issues"] == []

    def test_missing_wal_file_returns_defaults(self, tmp_path):
        config = self._make_config(tmp_path)
        extractor = JiraExtractor(config)
        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["last_issue_id"] is None
        assert extractor.wal_data["processed_issues"] == []

    def test_valid_wal_file_returns_parsed_data(self, tmp_path):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_data = {
            "last_run": "2025-06-01T00:00:00",
            "last_issue_id": "PROJ-100",
            "processed_issues": ["PROJ-1", "PROJ-2"],
        }
        wal_path.write_text(json.dumps(wal_data))

        extractor = JiraExtractor(config)
        assert extractor.wal_data["last_run"] == "2025-06-01T00:00:00"
        assert extractor.wal_data["last_issue_id"] == "PROJ-100"
        assert "PROJ-1" in extractor.wal_data["processed_issues"]
        assert "PROJ-2" in extractor.wal_data["processed_issues"]

    def test_partial_json_returns_defaults(self, tmp_path, caplog):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text('{"last_run": "2025-06-01T00:00:00", "processed_issues": ["P1"')

        with caplog.at_level(logging.WARNING):
            extractor = JiraExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["processed_issues"] == []


# ---------------------------------------------------------------------------
# WAL Corruption Handling Tests — GitLabExtractor
# ---------------------------------------------------------------------------


class TestGitLabWalCorruption:
    """GitLabExtractor._load_wal should handle corrupted files gracefully."""

    def _make_config(self, tmp_path):
        return {
            "url": "https://gitlab.test",
            "token": "test-token",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "wal.json"),
        }

    def test_corrupted_json_returns_defaults(self, tmp_path, caplog):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text("GARBAGE_DATA_NOT_JSON")

        with caplog.at_level(logging.WARNING):
            extractor = GitLabExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["projects"] == {}
        assert "corrupted" in caplog.text.lower() or "unreadable" in caplog.text.lower()

    def test_empty_file_returns_defaults(self, tmp_path, caplog):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text("")

        with caplog.at_level(logging.WARNING):
            extractor = GitLabExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["projects"] == {}

    def test_missing_wal_file_returns_defaults(self, tmp_path):
        config = self._make_config(tmp_path)
        extractor = GitLabExtractor(config)
        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["projects"] == {}

    def test_valid_wal_file_returns_parsed_data(self, tmp_path):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_data = {
            "last_run": "2025-06-01T00:00:00",
            "projects": {
                "42": {"last_commit_sha": "abc123", "last_commit_date": "2025-06-01"},
                "99": {"last_commit_sha": "def456", "last_commit_date": "2025-05-15"},
            },
        }
        wal_path.write_text(json.dumps(wal_data))

        extractor = GitLabExtractor(config)
        assert extractor.wal_data["last_run"] == "2025-06-01T00:00:00"
        assert extractor.wal_data["projects"]["42"]["last_commit_sha"] == "abc123"
        assert extractor.wal_data["projects"]["99"]["last_commit_sha"] == "def456"

    def test_partial_json_returns_defaults(self, tmp_path, caplog):
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_text('{"last_run": "2025-06-01", "projects": {"42":')

        with caplog.at_level(logging.WARNING):
            extractor = GitLabExtractor(config)

        assert extractor.wal_data["last_run"] is None
        assert extractor.wal_data["projects"] == {}

    def test_binary_garbage_raises_unicode_error(self, tmp_path):
        """Binary data in WAL file triggers UnicodeDecodeError.

        NOTE: This is a remaining risk — _load_wal catches (json.JSONDecodeError, OSError)
        but not UnicodeDecodeError. Binary corruption from disk errors will propagate.
        """
        config = self._make_config(tmp_path)
        wal_path = tmp_path / "wal" / "wal.json"
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        wal_path.write_bytes(b"\x00\x01\x02\x03\xff\xfe\xfd")

        with pytest.raises(UnicodeDecodeError):
            GitLabExtractor(config)
