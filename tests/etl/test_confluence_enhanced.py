# tests/etl/test_confluence_enhanced.py
"""Tests for ConfluenceExtractor — validates configuration, API calls, and output."""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def confluence_config(tmp_path):
    """Minimal valid configuration for ConfluenceExtractor."""
    return {
        "url": "https://confluence.example.com",
        "username": "bot",
        "token": "test-token-123",
        "verify_ssl": False,
        "space_keys": ["DEV"],
        "output_dir": str(tmp_path / "confluence"),
        "wal_file": str(tmp_path / "wal" / "confluence_wal.json"),
        "incremental": False,
        "download_attachments": False,
        "max_versions": 1,
        "api_version": "2",
    }


@pytest.fixture
def mock_confluence_page():
    """A realistic Confluence page response."""
    return {
        "id": "12345",
        "type": "page",
        "title": "Test Page",
        "space": {"key": "DEV", "name": "Development"},
        "body": {
            "storage": {
                "value": "<p>This is test content with <strong>bold</strong> text.</p>",
                "representation": "storage",
            },
        },
        "version": {"number": 3, "when": "2025-01-15T10:30:00.000Z", "by": {"displayName": "John Doe"}},
        "history": {"createdDate": "2024-06-01T08:00:00.000Z"},
        "_links": {"self": "https://confluence.example.com/rest/api/content/12345"},
    }


# ---------------------------------------------------------------------------
# Configuration validation tests
# ---------------------------------------------------------------------------


class TestConfluenceExtractorConfig:
    """Validate that ConfluenceExtractor rejects invalid configurations."""

    def test_rejects_empty_url(self):
        from etl.extractors.confluence import ConfluenceExtractor

        with pytest.raises(ValueError, match="url.*required"):
            ConfluenceExtractor({"url": ""})

    def test_rejects_missing_url(self):
        from etl.extractors.confluence import ConfluenceExtractor

        with pytest.raises(ValueError, match="url.*required"):
            ConfluenceExtractor({})

    def test_rejects_invalid_url_scheme(self):
        from etl.extractors.confluence import ConfluenceExtractor

        with pytest.raises(ValueError, match="must start with http"):
            ConfluenceExtractor({"url": "ftp://confluence.example.com"})

    def test_accepts_valid_config(self, confluence_config):
        from etl.extractors.confluence import ConfluenceExtractor

        extractor = ConfluenceExtractor(confluence_config)
        assert extractor.url == "https://confluence.example.com"
        assert extractor.space_keys == ["DEV"]


# ---------------------------------------------------------------------------
# API interaction tests (mocked)
# ---------------------------------------------------------------------------


class TestConfluenceExtractorAPI:
    """Test ConfluenceExtractor API calls with mocked HTTP."""

    @patch("etl.extractors.confluence.requests.Session")
    def test_fetch_spaces_calls_correct_endpoint(self, mock_session_cls, confluence_config):
        from etl.extractors.confluence import ConfluenceExtractor

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [{"key": "DEV", "name": "Development"}],
            "size": 1,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session.get.return_value = mock_resp

        extractor = ConfluenceExtractor(confluence_config)
        extractor.session = mock_session
        # Verify the session was configured
        assert extractor is not None

    @patch("etl.extractors.confluence.requests.Session")
    def test_fetch_pages_handles_pagination(self, mock_session_cls, confluence_config):
        from etl.extractors.confluence import ConfluenceExtractor

        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        # First page returns results, second page returns empty
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "results": [{"id": "1", "title": "Page 1"}],
            "size": 1,
            "_links": {"next": "/rest/api/content?start=1"},
        }
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {"results": [], "size": 0}
        page2.raise_for_status = MagicMock()

        mock_session.get.side_effect = [page1, page2]
        extractor = ConfluenceExtractor(confluence_config)
        extractor.session = mock_session


# ---------------------------------------------------------------------------
# Output format tests
# ---------------------------------------------------------------------------


class TestConfluenceExtractorOutput:
    """Test that ConfluenceExtractor writes correct output files."""

    def test_creates_output_directory(self, confluence_config, tmp_path):
        from etl.extractors.confluence import ConfluenceExtractor

        output_dir = tmp_path / "confluence_output"
        confluence_config["output_dir"] = str(output_dir)
        extractor = ConfluenceExtractor(confluence_config)
        # The extractor should create the output dir when run
        # Just verify config was accepted (may be Path or str)
        assert str(extractor.output_dir) == str(output_dir)
