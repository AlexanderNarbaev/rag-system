# tests/etl/test_extractors.py
from unittest.mock import patch

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
            ]
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
        ex.run()
        # Should not raise

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
        ex.run()
        # Should not raise

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
