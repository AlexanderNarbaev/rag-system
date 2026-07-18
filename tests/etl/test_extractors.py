# tests/etl/test_extractors.py
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from etl.extractors.confluence import ConfluenceExtractor
from etl.extractors.gitlab import GitLabExtractor
from etl.extractors.jira import JiraExtractor

# ---------------------------------------------------------------------------
# ConfluenceExtractor tests
# ---------------------------------------------------------------------------

CONFLUENCE_BASE_CONFIG = {
    "url": "https://confluence.test.local",
    "username": "bot",
    "token": "test-token",
    "space_keys": None,
    "output_dir": "/tmp/test_confluence",
    "wal_file": "/tmp/test_confluence/wal.json",
}


class TestConfluenceExtractorInit:
    def test_init_basic(self, tmp_path):
        config = {
            "url": "https://confluence.test",
            "username": "bot",
            "token": "tok",
            "output_dir": str(tmp_path / "output"),
            "wal_file": str(tmp_path / "wal" / "wal.json"),
        }
        extractor = ConfluenceExtractor(config)
        assert extractor.url == "https://confluence.test"
        assert extractor.incremental is True  # default
        assert extractor.download_attachments is True
        assert (tmp_path / "output").is_dir()
        assert (tmp_path / "wal").is_dir()

    def test_init_with_all_options(self, tmp_path):
        config = {
            "url": "https://cf.test",
            "username": "u",
            "token": "t",
            "space_keys": ["DEV", "OPS"],
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "w" / "w.json"),
            "incremental": False,
            "download_attachments": False,
            "max_versions": 5,
            "api_version": "1",
        }
        extractor = ConfluenceExtractor(config)
        assert extractor.space_keys == ["DEV", "OPS"]
        assert extractor.incremental is False
        assert extractor.download_attachments is False
        assert extractor.max_versions == 5
        assert extractor.api_version == "1"


class TestConfluenceCalculatePageHash:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    def test_same_page_same_hash(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        page = {
            "body": {"storage": {"value": "hello"}},
            "version": {"number": 1, "when": "2025-01-01T00:00:00Z"},
        }
        h1 = ex._calculate_page_hash(page)
        h2 = ex._calculate_page_hash(page)
        assert h1 == h2

    def test_different_body_different_hash(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        page1 = {
            "body": {"storage": {"value": "hello"}},
            "version": {"number": 1, "when": "2025-01-01"},
        }
        page2 = {
            "body": {"storage": {"value": "world"}},
            "version": {"number": 1, "when": "2025-01-01"},
        }
        assert ex._calculate_page_hash(page1) != ex._calculate_page_hash(page2)

    def test_hash_changes_with_version(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        page1 = {
            "body": {"storage": {"value": "same"}},
            "version": {"number": 1, "when": "2025-01-01"},
        }
        page2 = {
            "body": {"storage": {"value": "same"}},
            "version": {"number": 2, "when": "2025-01-02"},
        }
        assert ex._calculate_page_hash(page1) != ex._calculate_page_hash(page2)


class TestConfluenceShouldProcessPage:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    def test_should_process_when_incremental_off(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.incremental = False
        assert ex._should_process_page("p1", "anyhash") is True

    def test_new_page_should_process(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        # WAL has no entry for this page
        assert ex._should_process_page("new_page", "hash1") is True

    def test_unchanged_page_should_not_process(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.wal_data["pages_hash"]["p1"] = "oldhash"
        assert ex._should_process_page("p1", "oldhash") is False

    def test_changed_page_should_process(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.wal_data["pages_hash"]["p1"] = "oldhash"
        assert ex._should_process_page("p1", "newhash") is True


class TestConfluenceExtractLinks:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    def test_extract_internal_and_external_links(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        html = """
        <a href="/spaces/DEV/pages/123">Internal</a>
        <a href="https://external.com/page">External</a>
        <a href="https://confluence.test.local/spaces/OPS">Internal too</a>
        """
        links = ex._extract_links_from_html(html)
        assert len(links["internal_links"]) == 2
        assert len(links["external_links"]) == 1

    def test_extract_links_empty_html(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        links = ex._extract_links_from_html("<p>No links here</p>")
        assert links["internal_links"] == []
        assert links["external_links"] == []


class TestConfluenceGetAllPages:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_all_pages_without_since(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {
            "results": [
                {"id": "1", "title": "Page 1", "version": {"number": 1}, "space": {"key": "DEV"}},
                {"id": "2", "title": "Page 2", "version": {"number": 1}, "space": {"key": "DEV"}},
            ],
        }
        pages = ex._get_all_pages(space_key="DEV")
        assert len(pages) == 2
        assert pages[0]["id"] == "1"

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_all_pages_pagination_no_since(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        page1 = {"id": "1", "title": "P1", "version": {"number": 1}, "space": {"key": "DEV"}}
        page2 = {"id": "2", "title": "P2", "version": {"number": 1}, "space": {"key": "DEV"}}
        mock_request.side_effect = [
            {"results": [page1]},
            {"results": [page2]},
            {"results": []},
        ]
        pages = ex._get_all_pages(space_key="DEV", limit=1)
        assert len(pages) == 2

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_all_pages_all_spaces(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {"results": [{"id": "1", "title": "P1", "version": {"number": 1}, "space": {"key": "OPS"}}]}
        pages = ex._get_all_pages()
        assert len(pages) == 1
        call_kwargs = mock_request.call_args[0]
        params_dict = call_kwargs[2] if len(call_kwargs) >= 3 else {}
        assert "spaceKey" not in params_dict


class TestConfluenceRequestErrors:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    @patch("etl.extractors.confluence.requests.Session.get")
    def test_request_http_error_raises(self, mock_get, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("Not Found")
        ex.session.get = mock_get
        mock_get.return_value = mock_resp
        with pytest.raises(requests.exceptions.HTTPError):
            ex._request("/rest/api/content", params={"limit": 1})

    @patch("etl.extractors.confluence.requests.Session.get")
    def test_request_timeout_retries(self, mock_get, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        config["max_retries"] = 2
        config["retry_delay"] = 0.01
        ex = ConfluenceExtractor(config)
        mock_get.side_effect = requests.exceptions.Timeout("timed out")
        ex.session.get = mock_get
        with pytest.raises(requests.exceptions.Timeout):
            ex._request("/rest/api/content")
        assert mock_get.call_count == 3

    @patch("etl.extractors.confluence.requests.Session.get")
    def test_request_connection_error_retries(self, mock_get, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        config["max_retries"] = 1
        config["retry_delay"] = 0.01
        ex = ConfluenceExtractor(config)
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        ex.session.get = mock_get
        with pytest.raises(requests.exceptions.ConnectionError):
            ex._request("/rest/api/content")
        assert mock_get.call_count == 2

    @patch("etl.extractors.confluence.requests.Session.get")
    def test_request_ssl_error_raises_immediately(self, mock_get, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_get.side_effect = requests.exceptions.SSLError("cert verify failed")
        ex.session.get = mock_get
        with pytest.raises(requests.exceptions.SSLError):
            ex._request("/rest/api/content")

    @patch("etl.extractors.confluence.requests.Session.get")
    def test_request_success_after_retry(self, mock_get, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        config["max_retries"] = 3
        config["retry_delay"] = 0.01
        ex = ConfluenceExtractor(config)
        mock_resp_success = MagicMock()
        mock_resp_success.json.return_value = {"results": []}
        mock_resp_success.raise_for_status.return_value = None
        mock_get.side_effect = [
            requests.exceptions.Timeout("timeout"),
            requests.exceptions.ConnectionError("refused"),
            mock_resp_success,
        ]
        ex.session.get = mock_get
        result = ex._request("/rest/api/content")
        assert result == {"results": []}
        assert mock_get.call_count == 3


class TestConfluenceDownloadAttachment:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    def test_download_attachment_success(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = [b"file content"]
        with patch.object(ex.session, "get", return_value=mock_resp):
            path = ex._download_attachment("p1", "a1", "readme.txt", att_dir, "/download/att/1")
        assert path is not None
        assert Path(path).exists()
        saved_content = Path(path).read_text()
        assert "file content" in saved_content

    def test_download_attachment_bad_filename(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = [b"data"]
        with patch.object(ex.session, "get", return_value=mock_resp):
            path = ex._download_attachment("p1", "a1", "!@#$%^", att_dir, "/download")
        assert path is not None
        assert "attachment_a1" in path

    def test_download_attachment_connection_retry(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        mock_fail = MagicMock()
        mock_fail.raise_for_status.side_effect = requests.exceptions.ConnectionError("refused")
        mock_ok = MagicMock()
        mock_ok.raise_for_status.return_value = None
        mock_ok.iter_content.return_value = [b"ok"]
        with patch.object(ex.session, "get", side_effect=[mock_fail, mock_ok]) as mock_get:
            with patch("time.sleep", return_value=None):
                path = ex._download_attachment("p1", "a1", "file.txt", att_dir, "/download")
        assert path is not None
        assert mock_get.call_count == 2

    def test_download_attachment_timeout_retry(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        mock_fail = MagicMock()
        mock_fail.raise_for_status.side_effect = requests.exceptions.Timeout("timed out")
        mock_ok = MagicMock()
        mock_ok.raise_for_status.return_value = None
        mock_ok.iter_content.return_value = [b"ok"]
        with patch.object(ex.session, "get", side_effect=[mock_fail, mock_ok]) as mock_get:
            with patch("time.sleep", return_value=None):
                path = ex._download_attachment("p1", "a1", "file.txt", att_dir, "/download")
        assert path is not None
        assert mock_get.call_count == 2

    def test_download_attachment_max_retries_exceeded(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        att_dir = tmp_path / "attachments"
        att_dir.mkdir()
        mock_fail = MagicMock()
        mock_fail.raise_for_status.side_effect = requests.exceptions.ConnectionError("refused")
        with patch.object(ex.session, "get", return_value=mock_fail) as mock_get:
            with patch("time.sleep", return_value=None):
                path = ex._download_attachment("p1", "a1", "file.txt", att_dir, "/download")
        assert path is None
        assert mock_get.call_count == 4  # 3 retries + initial


class TestConfluenceInputValidation:
    def test_missing_url_raises(self, tmp_path):
        with pytest.raises(ValueError, match="url"):
            ConfluenceExtractor({"token": "tok", "output_dir": str(tmp_path)})

    def test_empty_url_raises(self, tmp_path):
        with pytest.raises(ValueError, match="url"):
            ConfluenceExtractor({"url": "", "token": "tok", "output_dir": str(tmp_path)})

    def test_invalid_url_scheme_raises(self, tmp_path):
        with pytest.raises(ValueError, match="http"):
            ConfluenceExtractor({"url": "ftp://bad.scheme", "token": "tok", "output_dir": str(tmp_path)})

    def test_missing_token_raises(self, tmp_path):
        with pytest.raises(ValueError, match="token"):
            ConfluenceExtractor({"url": "https://cf.test", "output_dir": str(tmp_path)})

    def test_empty_token_raises(self, tmp_path):
        with pytest.raises(ValueError, match="token"):
            ConfluenceExtractor({"url": "https://cf.test", "token": "", "output_dir": str(tmp_path)})

    def test_api_key_as_alternative(self, tmp_path):
        config = {
            "url": "https://cf.test",
            "username": "bot",
            "api_key": "api-token-123",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        ex = ConfluenceExtractor(config)
        assert ex.config["api_key"] == "api-token-123"


class TestConfluenceTestConnection:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    def test_connection_success(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch.object(ex.session, "get", return_value=mock_resp):
            assert ex.test_connection() is True

    def test_connection_auth_failure(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch.object(ex.session, "get", return_value=mock_resp):
            assert ex.test_connection() is False

    def test_connection_exception(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        with patch.object(ex.session, "get", side_effect=requests.exceptions.ConnectionError("no route")):
            assert ex.test_connection() is False


class TestConfluenceGetPageVersions:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_page_versions(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {
            "results": [
                {"number": 1, "when": "2025-01-01T00:00:00Z"},
                {"number": 2, "when": "2025-01-02T00:00:00Z"},
            ],
        }
        versions = ex._get_page_versions("12345")
        assert len(versions) == 2

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_page_versions_with_max_limit(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.max_versions = 1
        versions_data = [{"number": i} for i in range(1, 6)]
        mock_request.return_value = {"results": versions_data}
        versions = ex._get_page_versions("12345")
        assert len(versions) == 1
        assert versions[0]["number"] == 5


class TestConfluenceGetPagesSince:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_pages_since_uses_cql_search(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {
            "results": [
                {
                    "content": {
                        "id": "1",
                        "type": "page",
                        "title": "Updated Page",
                        "version": {"number": 2, "when": "2025-06-15T00:00:00Z"},
                        "space": {"key": "DEV"},
                    },
                },
            ],
            "start": 0,
            "limit": 50,
            "size": 1,
            "totalSize": 1,
        }
        pages = ex._get_all_pages(since="2025-06-01T00:00:00Z")
        assert len(pages) == 1
        assert pages[0]["title"] == "Updated Page"
        assert pages[0]["id"] == "1"

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_pages_since_with_space(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {
            "results": [],
            "start": 0,
            "limit": 50,
            "size": 0,
            "totalSize": 0,
        }
        pages = ex._get_all_pages(space_key="DEV", since="2025-06-01T00:00:00Z")
        assert pages == []

    @patch.object(ConfluenceExtractor, "_request")
    def test_since_date_stored_in_extractor(self, mock_request, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        config["since_date"] = "2025-06-01T00:00:00Z"
        ex = ConfluenceExtractor(config)
        assert ex.since_date == "2025-06-01T00:00:00Z"

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_pages_since_filters_non_page_types(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {
            "results": [
                {
                    "content": {"id": "1", "type": "page", "title": "Page"},
                    "lastModified": "2025-06-15",
                },
                {
                    "content": {"id": "2", "type": "blogpost", "title": "Blog"},
                    "lastModified": "2025-06-15",
                },
            ],
            "start": 0,
            "limit": 50,
            "size": 2,
            "totalSize": 2,
        }
        pages = ex._get_all_pages(since="2025-01-01T00:00:00Z")
        assert len(pages) == 1
        assert pages[0]["id"] == "1"

    @patch.object(ConfluenceExtractor, "_request")
    def test_get_pages_since_pagination(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        page1 = {"content": {"id": "1", "type": "page", "title": "P1"}}
        page2 = {"content": {"id": "2", "type": "page", "title": "P2"}}
        mock_request.side_effect = [
            {"results": [page1], "start": 0, "limit": 1, "size": 1, "totalSize": 2},
            {"results": [page2], "start": 1, "limit": 1, "size": 1, "totalSize": 2},
        ]
        pages = ex._get_all_pages(since="2025-01-01T00:00:00Z", limit=1)
        assert len(pages) == 2
        assert pages[0]["id"] == "1"
        assert pages[1]["id"] == "2"


class TestConfluenceRunIncremental:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    @patch.object(ConfluenceExtractor, "_get_all_pages")
    def test_run_passes_since_date_to_get_all_pages(self, mock_get_pages, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        config["since_date"] = "2025-07-01T00:00:00Z"
        ex = ConfluenceExtractor(config)
        mock_get_pages.return_value = []
        ex.run()
        mock_get_pages.assert_called_once()
        call_kwargs = mock_get_pages.call_args[1]
        assert call_kwargs["since"] == "2025-07-01T00:00:00Z"

    @patch.object(ConfluenceExtractor, "_get_all_pages")
    def test_run_no_since_date_queries_all(self, mock_get_pages, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_get_pages.return_value = []
        ex.run()
        mock_get_pages.assert_called_once()
        call_kwargs = mock_get_pages.call_args[1]
        assert call_kwargs["since"] is None


class TestConfluenceRun:
    def _make_extractor(self, tmp_path):
        config = dict(CONFLUENCE_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "output")
        config["wal_file"] = str(tmp_path / "wal" / "wal.json")
        return ConfluenceExtractor(config)

    @patch.object(ConfluenceExtractor, "_get_all_pages")
    def test_run_with_no_pages(self, mock_get_pages, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_get_pages.return_value = []
        ex.run()  # Should not raise

    @patch.object(ConfluenceExtractor, "_get_all_pages")
    @patch.object(ConfluenceExtractor, "extract_page")
    @patch.object(ConfluenceExtractor, "_save_page_data")
    def test_run_processes_pages(self, mock_save, mock_extract, mock_get_pages, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_get_pages.return_value = [
            {
                "id": "1",
                "title": "Page 1",
                "body": {"storage": {"value": "content"}},
                "version": {"number": 1, "when": "2025-01-01"},
                "space": {"key": "DEV"},
            },
        ]
        mock_extract.return_value = {"id": "1", "title": "Page 1"}
        ex.run()
        mock_extract.assert_called()
        mock_save.assert_called()

    @patch.object(ConfluenceExtractor, "_get_all_pages")
    def test_run_skips_unchanged_pages(self, mock_get_pages, tmp_path):
        ex = self._make_extractor(tmp_path)
        page = {
            "id": "1",
            "title": "Page 1",
            "body": {"storage": {"value": "content"}},
            "version": {"number": 1, "when": "2025-01-01"},
            "space": {"key": "DEV"},
        }
        page_hash = ex._calculate_page_hash(page)
        ex.wal_data["pages_hash"]["1"] = page_hash
        mock_get_pages.return_value = [page]
        # Should run without processing (skipped)
        ex.run()


# ---------------------------------------------------------------------------
# JiraExtractor tests
# ---------------------------------------------------------------------------

JIRA_BASE_CONFIG = {
    "url": "https://jira.test.local",
    "username": "bot",
    "token": "test-token",
    "output_dir": "/tmp/test_jira",
    "wal_file": "/tmp/test_jira/wal.json",
}


class TestJiraExtractorInit:
    def test_init_basic(self, tmp_path):
        config = {
            "url": "https://jira.test",
            "username": "bot",
            "token": "tok",
            "output_dir": str(tmp_path / "output"),
            "wal_file": str(tmp_path / "wal" / "wal.json"),
        }
        extractor = JiraExtractor(config)
        assert extractor.url == "https://jira.test"
        assert extractor.base_jql == "ORDER BY updated DESC"
        assert extractor.incremental is True
        assert (tmp_path / "output").is_dir()

    def test_init_with_custom_jql(self, tmp_path):
        config = {
            "url": "https://jira.test",
            "username": "u",
            "token": "t",
            "jql": "project = DEV",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        extractor = JiraExtractor(config)
        assert extractor.base_jql == "project = DEV"


class TestJiraBuildJql:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    def test_build_jql_no_incremental(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.incremental = False
        jql = ex._build_jql()
        assert jql == ex.base_jql

    def test_build_jql_incremental_with_last_run(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.base_jql = "project = DEV AND status != Closed"
        ex.wal_data["last_run"] = "2025-06-01T00:00:00"
        jql = ex._build_jql()
        assert "updated >=" in jql
        assert "2025-06-01" in jql

    def test_build_jql_incremental_with_since_date(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.base_jql = "project = DEV"
        ex.since_date = "2025-03-01T00:00:00"
        jql = ex._build_jql()
        assert "2025-03-01" in jql

    def test_build_jql_with_existing_updated(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.base_jql = "project = DEV AND updated > 2025-01-01"
        ex.wal_data["last_run"] = "2025-06-01T00:00:00"
        jql = ex._build_jql()
        assert "project = DEV" in jql


class TestJiraExtractLinks:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    def test_extract_urls_and_issue_keys(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        text = "See https://docs.example.com and PROJ-123 for details."
        links = ex._extract_links_from_text(text)
        assert "https://docs.example.com" in links["external_urls"]
        assert "PROJ-123" in links["mentioned_issues"]

    def test_extract_links_empty(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        links = ex._extract_links_from_text(None)
        assert links["external_urls"] == []
        assert links["mentioned_issues"] == []

    def test_extract_links_no_matches(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        text = "Just plain text without links or issues."
        links = ex._extract_links_from_text(text)
        assert links["external_urls"] == []
        assert links["mentioned_issues"] == []


class TestJiraProcessIssue:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    @patch.object(JiraExtractor, "_get_sprints_for_issue")
    def test_process_issue_minimal(self, mock_sprints, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_sprints.return_value = []
        issue = {
            "key": "PROJ-123",
            "fields": {
                "summary": "Test issue",
                "description": "Description text",
                "status": {"name": "Open"},
                "priority": {"name": "High"},
                "issuetype": {"name": "Bug"},
                "created": "2025-01-01T00:00:00Z",
                "updated": "2025-01-02T00:00:00Z",
                "labels": ["backend"],
                "comment": {"comments": []},
            },
        }
        result = ex._process_issue(issue)
        assert result["key"] == "PROJ-123"
        assert result["summary"] == "Test issue"
        assert result["status"] == "Open"
        assert result["priority"] == "High"
        assert result["issuetype"] == "Bug"
        assert result["labels"] == ["backend"]

    @patch.object(JiraExtractor, "_get_sprints_for_issue")
    def test_process_issue_with_links(self, mock_sprints, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_sprints.return_value = []
        issue = {
            "key": "PROJ-456",
            "fields": {
                "summary": "Test",
                "issuelinks": [
                    {
                        "outwardIssue": {"key": "PROJ-100"},
                        "type": {"outward": "blocks"},
                    },
                    {
                        "inwardIssue": {"key": "PROJ-200"},
                        "type": {"inward": "is blocked by"},
                    },
                ],
                "subtasks": [],
                "comment": {"comments": []},
            },
        }
        result = ex._process_issue(issue)
        assert len(result["links"]) == 2
        assert result["links"][0]["target_key"] == "PROJ-100"
        assert result["links"][0]["direction"] == "outward"


class TestJiraRun:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    @patch.object(JiraExtractor, "_paginated_issues")
    @patch.object(JiraExtractor, "_process_issue")
    def test_run_processes_issues(self, mock_process, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        issue = {"key": "PROJ-1", "fields": {}}
        mock_paginated.return_value = iter([issue])
        mock_process.return_value = {"key": "PROJ-1"}
        ex.run()

    @patch.object(JiraExtractor, "_paginated_issues")
    def test_run_respects_max_issues(self, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.max_issues_per_run = 1
        issues = [
            {"key": "PROJ-1", "fields": {}},
            {"key": "PROJ-2", "fields": {}},
        ]
        mock_paginated.return_value = iter(issues)
        with patch.object(ex, "_process_issue") as mock_process:
            mock_process.return_value = {"key": "X"}
            ex.run()
            assert mock_process.call_count <= 1

    @patch.object(JiraExtractor, "_paginated_issues")
    @patch.object(JiraExtractor, "_process_issue")
    def test_run_skips_processed_issues(self, mock_process, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.wal_data["processed_issues"] = ["PROJ-1"]
        mock_paginated.return_value = iter([{"key": "PROJ-1", "fields": {}}])
        ex.run()
        mock_process.assert_not_called()

    @patch.object(JiraExtractor, "_paginated_issues")
    @patch.object(JiraExtractor, "_process_issue")
    def test_run_handles_process_error(self, mock_process, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_paginated.return_value = iter([
            {"key": "PROJ-1", "fields": {}},
            {"key": "PROJ-2", "fields": {}},
        ])
        mock_process.side_effect = [RuntimeError("boom"), {"key": "PROJ-2"}]
        ex.run()


class TestJiraPaginatedIssues:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    @patch.object(JiraExtractor, "_request")
    def test_paginated_issues_single_page(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {
            "issues": [
                {"key": "PROJ-1", "fields": {"summary": "Issue 1"}},
                {"key": "PROJ-2", "fields": {"summary": "Issue 2"}},
            ],
            "total": 2,
        }
        issues = list(ex._paginated_issues("project = DEV"))
        assert len(issues) == 2
        assert issues[0]["key"] == "PROJ-1"

    @patch.object(JiraExtractor, "_request")
    def test_paginated_issues_multiple_pages(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.side_effect = [
            {"issues": [{"key": "PROJ-1"}], "total": 2},
            {"issues": [{"key": "PROJ-2"}], "total": 2},
        ]
        issues = list(ex._paginated_issues("project = DEV", max_results=1))
        assert len(issues) == 2

    @patch.object(JiraExtractor, "_request")
    def test_paginated_issues_empty(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {"issues": [], "total": 0}
        issues = list(ex._paginated_issues("project = EMPTY"))
        assert len(issues) == 0


class TestJiraDownloadAttachment:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    def test_download_attachment_success(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = [b"attachment data"]
        attachment = {"id": "att1", "filename": "report.pdf", "content": "https://jira.test/secure/attachment/1"}
        with patch.object(ex.session, "get", return_value=mock_resp):
            path = ex._download_attachment(attachment, "PROJ-1")
        assert path is not None
        assert Path(path).exists()
        saved_content = Path(path).read_text()
        assert "attachment data" in saved_content

    def test_download_attachment_empty_filename(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = [b"data"]
        attachment = {"id": "att2", "filename": "!@#", "content": "https://jira.test/att/2"}
        with patch.object(ex.session, "get", return_value=mock_resp):
            path = ex._download_attachment(attachment, "PROJ-2")
        assert path is not None
        assert "attachment_att2" in path

    def test_download_attachment_retry_on_connection_error(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_fail = MagicMock()
        mock_fail.raise_for_status.side_effect = requests.exceptions.ConnectionError("refused")
        mock_ok = MagicMock()
        mock_ok.raise_for_status.return_value = None
        mock_ok.iter_content.return_value = [b"ok"]
        attachment = {"id": "att3", "filename": "file.txt", "content": "https://jira.test/att/3"}
        with patch.object(ex.session, "get", side_effect=[mock_fail, mock_ok]) as mock_get:
            with patch("time.sleep", return_value=None):
                path = ex._download_attachment(attachment, "PROJ-3")
        assert path is not None
        assert mock_get.call_count == 2

    def test_download_attachment_max_retries_fails(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_fail = MagicMock()
        mock_fail.raise_for_status.side_effect = requests.exceptions.Timeout("timeout")
        attachment = {"id": "att4", "filename": "file.txt", "content": "https://jira.test/att/4"}
        with patch.object(ex.session, "get", return_value=mock_fail) as mock_get:
            with patch("time.sleep", return_value=None):
                path = ex._download_attachment(attachment, "PROJ-4")
        assert path is None
        assert mock_get.call_count == 4


class TestJiraRequestErrors:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    def test_request_http_error_raises(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        with patch.object(ex.session, "get", return_value=mock_resp):
            with pytest.raises(requests.exceptions.HTTPError):
                ex._request("/rest/api/2/search")

    def test_request_connection_error_retries_then_raises(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        config["max_retries"] = 1
        config["retry_delay"] = 0.01
        ex = JiraExtractor(config)
        with patch.object(ex.session, "get", side_effect=requests.exceptions.ConnectionError("refused")) as mock_get:
            with pytest.raises(requests.exceptions.ConnectionError):
                ex._request("/rest/api/2/search")
        assert mock_get.call_count == 2

    def test_request_ssl_error_raises_immediately(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        with patch.object(ex.session, "get", side_effect=requests.exceptions.SSLError("cert error")):
            with pytest.raises(requests.exceptions.SSLError):
                ex._request("/rest/api/2/search")


class TestJiraInputValidation:
    def test_missing_url_raises(self, tmp_path):
        with pytest.raises(ValueError, match="url"):
            JiraExtractor({"token": "tok", "output_dir": str(tmp_path)})

    def test_invalid_url_scheme_raises(self, tmp_path):
        with pytest.raises(ValueError, match="http"):
            JiraExtractor({"url": "ftp://bad", "token": "tok", "output_dir": str(tmp_path)})

    def test_missing_token_raises(self, tmp_path):
        with pytest.raises(ValueError, match="token"):
            JiraExtractor({"url": "https://jira.test", "output_dir": str(tmp_path)})

    def test_api_key_as_alternative(self, tmp_path):
        config = {
            "url": "https://jira.test",
            "username": "bot",
            "api_key": "api-token-jira",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        ex = JiraExtractor(config)
        assert ex.config["api_key"] == "api-token-jira"


class TestJiraProcessIssueWithAttachments:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    @patch.object(JiraExtractor, "_get_sprints_for_issue")
    @patch.object(JiraExtractor, "_download_attachment")
    def test_process_issue_with_attachments(self, mock_download, mock_sprints, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_sprints.return_value = []
        mock_download.return_value = "/tmp/att/file.txt"
        issue = {
            "key": "PROJ-789",
            "fields": {
                "summary": "With attachments",
                "description": "desc",
                "attachment": [
                    {"id": "att1", "filename": "file.txt", "size": 100, "mimeType": "text/plain", "created": "2025-01-01", "author": {"displayName": "Dev"}},
                ],
                "comment": {"comments": []},
            },
        }
        result = ex._process_issue(issue)
        assert len(result["attachments"]) == 1
        assert result["attachments"][0]["local_path"] == "/tmp/att/file.txt"
        assert result["attachments"][0]["filename"] == "file.txt"

    @patch.object(JiraExtractor, "_get_sprints_for_issue")
    def test_process_issue_attachments_disabled(self, mock_sprints, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.download_attachments = False
        mock_sprints.return_value = []
        issue = {
            "key": "PROJ-790",
            "fields": {
                "summary": "No download",
                "attachment": [
                    {"id": "att1", "filename": "file.txt", "size": 100, "mimeType": "text/plain", "created": "2025-01-01"},
                ],
                "comment": {"comments": []},
            },
        }
        result = ex._process_issue(issue)
        assert len(result["attachments"]) == 1
        assert "local_path" not in result["attachments"][0]


class TestJiraGetTransitions:
    def _make_extractor(self, tmp_path):
        config = dict(JIRA_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return JiraExtractor(config)

    @patch.object(JiraExtractor, "_request")
    def test_get_issue_transitions(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {
            "transitions": [
                {"id": "1", "name": "In Progress"},
                {"id": "2", "name": "Done"},
            ],
        }
        transitions = ex._get_issue_transitions("PROJ-1")
        assert len(transitions) == 2
        assert transitions[0]["name"] == "In Progress"

    @patch.object(JiraExtractor, "_request")
    def test_get_sprints_for_issue(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.return_value = {"fields": {"sprint": [{"id": 1, "name": "Sprint 1"}]}}
        sprints = ex._get_sprints_for_issue("PROJ-1")
        assert len(sprints) == 1

    @patch.object(JiraExtractor, "_request")
    def test_get_sprints_for_issue_error(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_request.side_effect = Exception("API error")
        sprints = ex._get_sprints_for_issue("PROJ-1")
        assert sprints == []


# ---------------------------------------------------------------------------
# GitLabExtractor tests
# ---------------------------------------------------------------------------

GITLAB_BASE_CONFIG = {
    "url": "https://gitlab.test.local",
    "token": "test-token",
    "output_dir": "/tmp/test_gitlab",
    "wal_file": "/tmp/test_gitlab/wal.json",
}


class TestGitLabExtractorInit:
    def test_init_basic(self, tmp_path):
        config = {
            "url": "https://gitlab.test",
            "token": "tok",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        extractor = GitLabExtractor(config)
        assert extractor.url == "https://gitlab.test"
        assert extractor.incremental is True
        assert extractor.fetch_commits is True
        assert extractor.fetch_files is True
        assert extractor.fetch_merge_requests is True
        assert (tmp_path / "out").is_dir()

    def test_init_disabled_features(self, tmp_path):
        config = {
            "url": "https://gitlab.test",
            "token": "tok",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
            "fetch_commits": False,
            "fetch_files": False,
            "fetch_merge_requests": False,
        }
        extractor = GitLabExtractor(config)
        assert extractor.fetch_commits is False
        assert extractor.fetch_files is False
        assert extractor.fetch_merge_requests is False


class TestGitLabMatchesFilter:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return GitLabExtractor(config)

    def test_matches_with_extension_pattern(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.file_paths_filter = ["*.py", "*.md"]
        assert ex._matches_filter("src/main.py") is True
        assert ex._matches_filter("README.md") is True
        assert ex._matches_filter("Dockerfile") is False

    def test_matches_with_exact_pattern(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.file_paths_filter = ["Dockerfile", "Makefile"]
        assert ex._matches_filter("Dockerfile") is True
        assert ex._matches_filter("path/to/Dockerfile") is True  # 'Dockerfile' in path
        assert ex._matches_filter("random.txt") is False

    def test_matches_no_filter_returns_true(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        assert ex._matches_filter("anything.py") is True

    def test_matches_with_substring_match(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.file_paths_filter = ["config"]
        assert ex._matches_filter("src/config/first/path") is True  # 'config' in path


class TestGitLabShouldProcessCommit:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return GitLabExtractor(config)

    def test_should_process_when_incremental_off(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.incremental = False
        assert ex._should_process_commit(1, "sha1", "2025-01-01") is True

    def test_new_project_should_process(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        assert ex._should_process_commit(99, "sha1", "2025-01-01") is True

    def test_same_commit_should_not_process(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.wal_data["projects"]["1"] = {"last_commit_sha": "sha1"}
        assert ex._should_process_commit(1, "sha1", "2025-01-01") is False

    def test_different_commit_should_process(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.wal_data["projects"]["1"] = {"last_commit_sha": "sha1"}
        assert ex._should_process_commit(1, "sha2", "2025-01-02") is True


class TestGitLabGetProjects:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return GitLabExtractor(config)

    @patch.object(GitLabExtractor, "_request")
    def test_get_projects_with_ids(self, mock_request, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.project_ids = [1, 2]
        mock_request.side_effect = [
            {"id": 1, "name": "Project 1"},
            {"id": 2, "name": "Project 2"},
        ]
        projects = ex.get_projects()
        assert len(projects) == 2
        assert projects[0]["id"] == 1
        assert projects[1]["id"] == 2

    @patch.object(GitLabExtractor, "_paginated_get")
    def test_get_projects_all(self, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_paginated.return_value = iter([
            {"id": 1, "name": "Project 1"},
            {"id": 2, "name": "Project 2"},
        ])
        projects = ex.get_projects()
        assert len(projects) == 2

    @patch.object(GitLabExtractor, "_paginated_get")
    def test_get_projects_empty(self, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_paginated.return_value = iter([])
        projects = ex.get_projects()
        assert projects == []


class TestGitLabGetFileContent:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return GitLabExtractor(config)

    @patch("etl.extractors.gitlab.requests.Session.get")
    def test_get_file_content_success(self, mock_get, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = "print('hello world')"
        mock_get.return_value = mock_resp
        ex.session.get = mock_get
        content = ex.get_file_content(1, "src/main.py", ref="main")
        assert content == "print('hello world')"

    @patch("etl.extractors.gitlab.requests.Session.get")
    def test_get_file_content_failure(self, mock_get, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_get.return_value = mock_resp
        ex.session.get = mock_get
        content = ex.get_file_content(1, "missing/file.py")
        assert content is None


class TestGitLabGetMergeRequests:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return GitLabExtractor(config)

    @patch.object(GitLabExtractor, "_paginated_get")
    @patch.object(GitLabExtractor, "_request")
    def test_get_merge_requests(self, mock_request, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        mr = {"iid": 1, "title": "Feature X"}
        mock_paginated.return_value = iter([mr])
        mock_request.return_value = {"changes": []}
        mrs = ex.get_merge_requests(1)
        assert len(mrs) == 1
        assert mrs[0]["title"] == "Feature X"
        assert "discussions" in mrs[0]
        assert "changes" in mrs[0]

    @patch.object(GitLabExtractor, "_paginated_get")
    @patch.object(GitLabExtractor, "_request")
    def test_get_merge_requests_with_since_date(self, mock_request, mock_paginated, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        config["since_date"] = "2025-01-01T00:00:00Z"
        ex = GitLabExtractor(config)
        mock_paginated.return_value = iter([])
        mock_request.return_value = {"changes": []}
        mrs = ex.get_merge_requests(1)
        assert mrs == []
        assert mock_paginated.call_count == 1
        call_args = mock_paginated.call_args[0]
        params_arg = call_args[1] if len(call_args) > 1 else {}
        assert "updated_after" in params_arg
        assert params_arg["updated_after"] == "2025-01-01T00:00:00Z"

    @patch.object(GitLabExtractor, "_paginated_get")
    def test_get_mr_discussions(self, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_paginated.return_value = iter([
            {
                "id": "disc1",
                "notes": [
                    {
                        "id": 10,
                        "author": {"username": "dev1"},
                        "created_at": "2025-01-01",
                        "body": "Looks good",
                        "type": "DiffNote",
                    },
                ],
            },
        ])
        discussions = ex.get_mr_discussions(1, 1)
        assert len(discussions) == 1
        assert discussions[0]["id"] == "disc1"
        assert len(discussions[0]["notes"]) == 1
        assert discussions[0]["notes"][0]["author"] == "dev1"


class TestGitLabGetBranches:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return GitLabExtractor(config)

    @patch.object(GitLabExtractor, "_paginated_get")
    def test_get_branches(self, mock_paginated, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_paginated.return_value = iter([
            {"name": "main", "commit": {"id": "sha1"}},
            {"name": "develop", "commit": {"id": "sha2"}},
        ])
        branches = ex.get_branches(1)
        assert len(branches) == 2
        assert branches[0]["name"] == "main"


class TestGitLabRun:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        config["fetch_files"] = False
        config["fetch_merge_requests"] = False
        return GitLabExtractor(config)

    @patch.object(GitLabExtractor, "get_projects")
    def test_run_with_no_projects(self, mock_projects, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_projects.return_value = []
        ex.run()  # Should not raise

    @patch.object(GitLabExtractor, "get_projects")
    @patch.object(GitLabExtractor, "get_commits")
    @patch.object(GitLabExtractor, "get_branches")
    @patch.object(GitLabExtractor, "_save_project_data")
    def test_run_processes_project(self, mock_save, mock_branches, mock_commits, mock_projects, tmp_path):
        ex = self._make_extractor(tmp_path)
        mock_projects.return_value = [{"id": 1, "path_with_namespace": "test/proj"}]
        mock_commits.return_value = [{"id": "sha1", "created_at": "2025-01-01T00:00:00Z"}]
        mock_branches.return_value = []
        ex.run()
        mock_save.assert_called_once()

    @patch.object(GitLabExtractor, "get_projects")
    def test_run_respects_max_projects(self, mock_projects, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.max_projects = 1
        mock_projects.return_value = [
            {"id": 1, "path_with_namespace": "a/b"},
            {"id": 2, "path_with_namespace": "c/d"},
        ]
        with patch.object(ex, "get_commits", return_value=[]):
            with patch.object(ex, "get_branches", return_value=[]):
                with patch.object(ex, "_save_project_data"):
                    ex.run()


class TestGitLabRequestErrors:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return GitLabExtractor(config)

    def test_request_connection_error_retries(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        config["max_retries"] = 1
        config["retry_delay"] = 0.01
        ex = GitLabExtractor(config)
        with patch.object(ex.session, "request", side_effect=requests.exceptions.ConnectionError("refused")) as mock_req:
            with pytest.raises(requests.exceptions.ConnectionError):
                ex._request("/api/v4/projects")
        assert mock_req.call_count == 2

    def test_request_timeout_retries(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        config["max_retries"] = 1
        config["retry_delay"] = 0.01
        ex = GitLabExtractor(config)
        with patch.object(ex.session, "request", side_effect=requests.exceptions.Timeout("timed out")) as mock_req:
            with pytest.raises(requests.exceptions.Timeout):
                ex._request("/api/v4/projects")
        assert mock_req.call_count == 2

    def test_request_ssl_error_raises(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        with patch.object(ex.session, "request", side_effect=requests.exceptions.SSLError("cert error")):
            with pytest.raises(requests.exceptions.SSLError):
                ex._request("/api/v4/projects")


class TestGitLabInputValidation:
    def test_missing_url_raises(self, tmp_path):
        with pytest.raises(ValueError, match="url"):
            GitLabExtractor({"token": "tok", "output_dir": str(tmp_path)})

    def test_invalid_url_scheme_raises(self, tmp_path):
        with pytest.raises(ValueError, match="http"):
            GitLabExtractor({"url": "ftp://bad", "token": "tok", "output_dir": str(tmp_path)})

    def test_missing_token_raises(self, tmp_path):
        with pytest.raises(ValueError, match="token"):
            GitLabExtractor({"url": "https://gl.test", "output_dir": str(tmp_path)})

    def test_api_key_as_alternative(self, tmp_path):
        config = {
            "url": "https://gl.test",
            "api_key": "gl-pat-123",
            "output_dir": str(tmp_path / "out"),
            "wal_file": str(tmp_path / "wal" / "w.json"),
        }
        ex = GitLabExtractor(config)
        assert ex.token == "gl-pat-123"


class TestGitLabExclusionFilter:
    def _make_extractor(self, tmp_path):
        config = dict(GITLAB_BASE_CONFIG)
        config["output_dir"] = str(tmp_path / "out")
        config["wal_file"] = str(tmp_path / "wal" / "w.json")
        return GitLabExtractor(config)

    def test_exclude_extension(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.file_paths_exclude = ["*.java"]
        assert ex._matches_filter("src/Main.java") is False

    def test_exclude_directory(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.file_paths_exclude = ["node_modules/*"]
        assert ex._matches_filter("node_modules/package.json") is False

    def test_include_overrides_exclude_not_applied(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.file_paths_filter = ["*.py"]
        ex.file_paths_exclude = ["*.java"]
        assert ex._matches_filter("main.py") is True
        assert ex._matches_filter("Main.java") is False

    def test_exclude_specific_path_pattern(self, tmp_path):
        ex = self._make_extractor(tmp_path)
        ex.file_paths_exclude = ["*.class"]
        assert ex._matches_filter("build/classes/Foo.class") is False
