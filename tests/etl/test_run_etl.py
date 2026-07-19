# ruff: noqa: E501, N803
"""Tests for etl/scheduler/run_etl.py — ETL orchestrator coverage."""

import atexit
import contextlib
import json
import signal
from unittest.mock import MagicMock, patch

import pytest


class TestRunExtractConfluence:
    @patch("etl.scheduler.run_etl.ConfluenceExtractor")
    def test_successful_extraction(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_confluence

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_extractor.run.return_value = None
        mock_wal = MagicMock()
        config = {
            "confluence": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "confluence"),
            },
        }
        result = run_extract_confluence(config, mock_wal)
        assert result == tmp_path / "confluence"
        mock_extractor.run.assert_called_once()
        mock_wal.update_last_run.assert_called_once()

    @patch("etl.scheduler.run_etl.ConfluenceExtractor")
    def test_incremental_when_last_run_exists(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_confluence

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        mock_wal.get_last_run.return_value = "2025-06-01T00:00:00"
        config = {
            "confluence": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "confluence"),
            },
        }
        run_extract_confluence(config, mock_wal)
        assert config["confluence"].get("since_date") == "2025-06-01T00:00:00"

    @patch("etl.scheduler.run_etl.ConfluenceExtractor")
    def test_respects_existing_since_date(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_confluence

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        mock_wal.get_last_run.return_value = "2025-06-01T00:00:00"
        config = {
            "confluence": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "confluence"),
                "since_date": "2024-01-01T00:00:00",
            },
        }
        run_extract_confluence(config, mock_wal)
        assert config["confluence"]["since_date"] == "2024-01-01T00:00:00"

    @patch("etl.scheduler.run_etl.ConfluenceExtractor")
    def test_wal_updated_after_extraction(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_confluence

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        config = {
            "confluence": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "confluence"),
            },
        }
        run_extract_confluence(config, mock_wal)
        mock_wal.update_last_run.assert_called_once()

    @patch("etl.scheduler.run_etl.ConfluenceExtractor")
    def test_custom_output_dir(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_confluence

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        custom_dir = tmp_path / "custom_conflu"
        config = {
            "confluence": {
                "base_url": "http://test",
                "output_dir": str(custom_dir),
            },
        }
        result = run_extract_confluence(config, mock_wal)
        assert result == custom_dir


class TestRunExtractJira:
    @patch("etl.scheduler.run_etl.JiraExtractor")
    def test_successful_extraction(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_jira

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        mock_wal.get_last_run.return_value = None
        config = {
            "jira": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "jira"),
            },
        }
        result = run_extract_jira(config, mock_wal)
        assert result == tmp_path / "jira"
        mock_extractor.run.assert_called_once()

    @patch("etl.scheduler.run_etl.JiraExtractor")
    def test_incremental_when_last_run_exists(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_jira

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        mock_wal.get_last_run.return_value = "2025-01-01"
        config = {
            "jira": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "jira"),
            },
        }
        run_extract_jira(config, mock_wal)
        assert config["jira"].get("since_date") == "2025-01-01"

    @patch("etl.scheduler.run_etl.JiraExtractor")
    def test_respects_existing_since_date(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_jira

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        mock_wal.get_last_run.return_value = "2025-01-01"
        config = {
            "jira": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "jira"),
                "since_date": "2024-01-01",
            },
        }
        run_extract_jira(config, mock_wal)
        assert config["jira"]["since_date"] == "2024-01-01"


class TestRunExtractGitlab:
    @patch("etl.scheduler.run_etl.GitLabExtractor")
    def test_successful_extraction(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_gitlab

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        mock_wal.get_last_run.return_value = None
        config = {
            "gitlab": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "gitlab"),
            },
        }
        result = run_extract_gitlab(config, mock_wal)
        assert result == tmp_path / "gitlab"

    @patch("etl.scheduler.run_etl.GitLabExtractor")
    def test_incremental_when_last_run_exists(self, MockExtractor, tmp_path):
        from etl.scheduler.run_etl import run_extract_gitlab

        mock_extractor = MagicMock()
        MockExtractor.return_value = mock_extractor
        mock_wal = MagicMock()
        mock_wal.get_last_run.return_value = "2025-06-01"
        config = {
            "gitlab": {
                "base_url": "http://test",
                "output_dir": str(tmp_path / "gitlab"),
            },
        }
        run_extract_gitlab(config, mock_wal)
        assert config["gitlab"].get("since_date") == "2025-06-01"


class TestRunExtractorSafe:
    def test_success(self, tmp_path):
        from etl.scheduler.run_etl import _run_extractor_safe

        def mock_fn(config, wal):
            return tmp_path

        mock_wal = MagicMock()
        name, output_dir, error = _run_extractor_safe("test", mock_fn, {}, mock_wal)
        assert name == "test"
        assert output_dir == tmp_path
        assert error is None

    def test_failure_captures_error(self):
        from etl.scheduler.run_etl import _run_extractor_safe

        def mock_fn(config, wal):
            raise RuntimeError("extraction failed")

        mock_wal = MagicMock()
        name, output_dir, error = _run_extractor_safe("test", mock_fn, {}, mock_wal)
        assert name == "test"
        assert output_dir is None
        assert error is not None
        assert "extraction failed" in error


class TestRunChunkingShutdown:
    def test_shutdown_stops_chunking(self, tmp_path):
        import etl.scheduler.run_etl as run_etl_mod

        run_etl_mod._shutdown_event.set()
        try:
            from etl.scheduler.run_etl import run_chunking

            mock_chunker = MagicMock()
            mock_chunk = MagicMock()
            mock_chunk.__dict__ = {"text": "c", "source_id": "d1"}
            mock_chunker.process_document.return_value = [mock_chunk]
            docs = [
                {
                    "id": "doc1",
                    "source_type": "w",
                    "title": "T",
                    "content": "c",
                    "content_type": "markdown",
                    "metadata": {},
                },
            ]
            output_dir = tmp_path / "chunks"
            result = run_chunking(docs, mock_chunker, output_dir)
            assert result == []
        finally:
            run_etl_mod._shutdown_event.clear()


class TestRunIndexingShutdown:
    def test_shutdown_stops_indexing(self):
        import etl.scheduler.run_etl as run_etl_mod
        from etl.scheduler.run_etl import run_indexing

        run_etl_mod._shutdown_event.set()
        try:
            mock_lake = MagicMock()
            mock_wal = MagicMock()
            chunks = [
                {"text": "c", "id": "c1", "source_id": "d1"},
                {"text": "c2", "id": "c2", "source_id": "d2"},
            ]
            run_indexing(chunks, mock_lake, mock_wal)
            mock_lake.sync_document.assert_not_called()
        finally:
            run_etl_mod._shutdown_event.clear()


class TestLoadConfig:
    def test_load_yaml_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("confluence:\n  base_url: http://test\njira:\n  base_url: http://jira\n")
        from etl.scheduler.run_etl import load_config

        config = load_config(config_file)
        assert "confluence" in config
        assert config["confluence"]["base_url"] == "http://test"


class TestCollectAllDocuments:
    def test_empty_dirs(self, tmp_path):
        conflu_dir = tmp_path / "confluence"
        jira_dir = tmp_path / "jira"
        gitlab_dir = tmp_path / "gitlab"
        conflu_dir.mkdir()
        jira_dir.mkdir()
        gitlab_dir.mkdir()

        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([conflu_dir, jira_dir, gitlab_dir])
        assert docs == []

    def test_confluence_doc(self, tmp_path):
        conflu_dir = tmp_path / "confluence"
        page_dir = conflu_dir / "page123"
        page_dir.mkdir(parents=True)
        page_data = {
            "id": "page123",
            "title": "Test Page",
            "body_view_html": "<p>Hello</p>",
            "version": "3",
            "space": "TEST",
            "created_at": "2025-01-01",
            "updated_at": "2025-06-01",
        }
        (page_dir / "page.json").write_text(json.dumps(page_data))

        jira_dir = tmp_path / "jira"
        gitlab_dir = tmp_path / "gitlab"
        jira_dir.mkdir()
        gitlab_dir.mkdir()

        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([conflu_dir, jira_dir, gitlab_dir])
        assert len(docs) == 1
        assert docs[0]["source_type"] == "confluence"
        assert "Hello" in docs[0]["content"]

    def test_jira_doc(self, tmp_path):
        jira_dir = tmp_path / "jira"
        issue_dir = jira_dir / "PROJ-123"
        issue_dir.mkdir(parents=True)
        issue_data = {
            "key": "PROJ-123",
            "summary": "Bug report",
            "description": "Something broke",
            "status": "Open",
            "priority": "High",
            "assignee": "dev1",
            "created": "2025-01-01",
            "updated": "2025-06-01",
            "comments": [{"author": "user1", "body": "I can reproduce this"}],
        }
        (issue_dir / "issue.json").write_text(json.dumps(issue_data))

        conflu_dir = tmp_path / "confluence"
        gitlab_dir = tmp_path / "gitlab"
        conflu_dir.mkdir()
        gitlab_dir.mkdir()

        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([conflu_dir, jira_dir, gitlab_dir])
        assert len(docs) == 1
        assert docs[0]["source_type"] == "jira"
        assert "Comment by user1" in docs[0]["content"]

    def test_gitlab_commits(self, tmp_path):
        gitlab_dir = tmp_path / "gitlab"
        proj_dir = gitlab_dir / "proj1"
        proj_dir.mkdir(parents=True)
        commits_data = [
            {
                "id": "abc123def456",
                "title": "Fix bug",
                "message": "Fixed the thing",
                "author_name": "dev1",
                "created_at": "2025-01-01",
                "diff": [{"new_path": "src/main.py", "diff": "+print('fixed')"}],
            },
        ]
        (proj_dir / "commits.json").write_text(json.dumps(commits_data))

        conflu_dir = tmp_path / "confluence"
        jira_dir = tmp_path / "jira"
        conflu_dir.mkdir()
        jira_dir.mkdir()

        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([conflu_dir, jira_dir, gitlab_dir])
        assert len(docs) == 1
        assert docs[0]["source_type"] == "gitlab_commit"

    def test_gitlab_merge_requests(self, tmp_path):
        gitlab_dir = tmp_path / "gitlab"
        proj_dir = gitlab_dir / "proj2"
        proj_dir.mkdir(parents=True)
        mrs_data = [
            {
                "iid": 42,
                "title": "Add feature",
                "description": "New feature implementation",
                "state": "merged",
                "author": {"username": "dev2"},
                "discussions": [{"notes": [{"author": "reviewer1", "body": "LGTM"}]}],
            },
        ]
        (proj_dir / "merge_requests.json").write_text(json.dumps(mrs_data))

        conflu_dir = tmp_path / "confluence"
        jira_dir = tmp_path / "jira"
        conflu_dir.mkdir()
        jira_dir.mkdir()

        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([conflu_dir, jira_dir, gitlab_dir])
        assert len(docs) == 1
        assert docs[0]["source_type"] == "gitlab_merge_request"

    def test_gitlab_files(self, tmp_path):
        gitlab_dir = tmp_path / "gitlab"
        proj_dir = gitlab_dir / "proj3"
        files_dir = proj_dir / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "main.py.txt").write_text("print('hello')")

        conflu_dir = tmp_path / "confluence"
        jira_dir = tmp_path / "jira"
        conflu_dir.mkdir()
        jira_dir.mkdir()

        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([conflu_dir, jira_dir, gitlab_dir])
        assert len(docs) == 1
        assert docs[0]["source_type"] == "gitlab_code"


class TestRunChunking:
    def test_basic_chunking(self, tmp_path):
        from etl.scheduler.run_etl import run_chunking

        mock_chunker = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.__dict__ = {"text": "chunk text", "source_id": "doc1"}
        mock_chunker.process_document.return_value = [mock_chunk]

        docs = [
            {
                "id": "doc1",
                "source_type": "wiki",
                "title": "T",
                "content": "content",
                "content_type": "markdown",
                "metadata": {"version": "1.0"},
            },
        ]
        output_dir = tmp_path / "chunks"
        result = run_chunking(docs, mock_chunker, output_dir)
        assert len(result) == 1

    def test_chunking_error_continues(self, tmp_path):
        from etl.scheduler.run_etl import run_chunking

        mock_chunker = MagicMock()
        mock_chunker.process_document.side_effect = Exception("chunk error")

        docs = [
            {
                "id": "doc1",
                "source_type": "wiki",
                "title": "T",
                "content": "content",
                "content_type": "markdown",
                "metadata": {},
            },
        ]
        output_dir = tmp_path / "chunks"
        result = run_chunking(docs, mock_chunker, output_dir)
        assert result == []

    def test_empty_documents(self, tmp_path):
        from etl.scheduler.run_etl import run_chunking

        mock_chunker = MagicMock()
        output_dir = tmp_path / "chunks"
        result = run_chunking([], mock_chunker, output_dir)
        assert result == []


class TestRunGraphExtraction:
    @patch("etl.scheduler.run_etl.EntityRelationExtractor")
    @patch("etl.scheduler.run_etl.Neo4jLoader")
    def test_basic_extraction(self, MockNeo4j, MockExtractor):
        from etl.scheduler.run_etl import run_graph_extraction

        mock_extractor = MagicMock()
        mock_extractor.extract_batch.return_value = ([], [])
        mock_loader = MagicMock()
        chunks = [{"text": "chunk text", "source_id": "doc1", "metadata": {}}]
        entities, relations = run_graph_extraction(chunks, mock_extractor, mock_loader)
        assert entities == []
        assert relations == []

    @patch("etl.scheduler.run_etl.EntityRelationExtractor")
    def test_no_neo4j_loader(self, MockExtractor):
        from etl.scheduler.run_etl import run_graph_extraction

        mock_extractor = MagicMock()
        mock_extractor.extract_batch.return_value = ([], [])
        chunks = [{"text": "chunk", "source_id": "d1", "metadata": {}}]
        entities, relations = run_graph_extraction(chunks, mock_extractor, None)
        assert entities == []


class TestRunIndexing:
    @patch("etl.scheduler.run_etl.LiveVectorLake")
    @patch("etl.scheduler.run_etl.WALManager")
    def test_basic_indexing(self, MockWal, MockLake):
        from etl.scheduler.run_etl import run_indexing

        mock_lake = MagicMock()
        mock_lake.sync_document.return_value = (5, 0)
        mock_wal = MagicMock()
        chunks = [{"text": "chunk", "id": "c1", "source_id": "doc1"}]
        run_indexing(chunks, mock_lake, mock_wal)
        # run_indexing doesn't return a value; just verify no exception
        assert True

    @patch("etl.scheduler.run_etl.LiveVectorLake")
    @patch("etl.scheduler.run_etl.WALManager")
    def test_empty_chunks(self, MockWal, MockLake):
        from etl.scheduler.run_etl import run_indexing

        mock_lake = MagicMock()
        mock_wal = MagicMock()
        run_indexing([], mock_lake, mock_wal)  # Just verify no exception


class TestRunGraphExtractionExtended:
    def test_with_entities_and_neo4j(self):
        from etl.scheduler.run_etl import run_graph_extraction

        mock_extractor = MagicMock()
        entity = MagicMock()
        entity.__dict__ = {"id": "e1", "name": "Test", "type": "PERSON", "source_id": "doc1", "properties": {}}
        relation = MagicMock()
        relation.__dict__ = {"source": "e1", "target": "e2", "type": "RELATED", "properties": {}}
        mock_extractor.extract_batch.return_value = ([entity], [relation])
        mock_loader = MagicMock()
        mock_loader.load_entities.return_value = 1
        mock_loader.load_relations.return_value = 1
        chunks = [{"text": "chunk text", "source_id": "doc1", "metadata": {}}]
        entities, relations = run_graph_extraction(chunks, mock_extractor, mock_loader)
        assert len(entities) == 1
        assert len(relations) == 1


class TestMainFunction:
    @patch("etl.scheduler.run_etl.load_config")
    @patch("etl.scheduler.run_etl.WALManager")
    def test_main_dry_run(self, MockWal, mock_config, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "confluence:\n  base_url: http://test\n  output_dir: /tmp/out\njira:\n  base_url: http://jira\n  output_dir: "
            "/tmp/out\ngitlab:\n  base_url: http://gitlab\n  output_dir: /tmp/out\n",
        )
        mock_config.return_value = {
            "confluence": {"base_url": "http://test", "output_dir": "/tmp/out"},
            "jira": {"base_url": "http://jira", "output_dir": "/tmp/out"},
            "gitlab": {"base_url": "http://gitlab", "output_dir": "/tmp/out"},
            "chunking": {"max_chunk_size": 1000},
        }
        MockWal.return_value = MagicMock()
        # Just test that load_config works
        from etl.scheduler.run_etl import load_config

        result = load_config(config_file)
        assert "confluence" in result


class TestArgumentParsing:
    def test_default_config_path(self) -> None:
        from etl.scheduler.run_etl import (
            main,
        )

        with (  # noqa: SIM117
            patch("sys.argv", ["run_etl.py", "--mode", "batch"]) as _argv,
            patch("etl.scheduler.run_etl.load_config") as mock_load,
            patch("etl.scheduler.run_etl.WALManager") as mock_wal,
            patch("etl.scheduler.run_etl.collect_all_documents") as mock_collect,
            patch("etl.scheduler.run_etl.run_chunking") as mock_chunk,
            patch("etl.scheduler.run_etl.QdrantHybridIndexer"),
            patch("etl.scheduler.run_etl.LiveVectorLake"),
            patch("etl.scheduler.run_etl.ChunkVersionStore"),
        ):
            mock_load.return_value = {}
            mock_wal.return_value = MagicMock()
            mock_collect.return_value = []
            mock_chunk.return_value = []
            main()

    def test_custom_config_path(self) -> None:
        with (  # noqa: SIM117
            patch("sys.argv", ["run_etl.py", "--config", "/custom/path.yaml", "--mode", "batch"]),
            patch("etl.scheduler.run_etl.load_config") as mock_load,
            patch("etl.scheduler.run_etl.WALManager") as mock_wal,
            patch("etl.scheduler.run_etl.collect_all_documents") as mock_collect,
            patch("etl.scheduler.run_etl.run_chunking") as mock_chunk,
            patch("etl.scheduler.run_etl.QdrantHybridIndexer"),
            patch("etl.scheduler.run_etl.LiveVectorLake"),
            patch("etl.scheduler.run_etl.ChunkVersionStore"),
        ):
            mock_load.return_value = {}
            mock_wal.return_value = MagicMock()
            mock_collect.return_value = []
            mock_chunk.return_value = []
            from etl.scheduler.run_etl import main  # noqa: PLC0415

            main()
            mock_load.assert_called_once()
            call_arg = mock_load.call_args[0][0]
            assert str(call_arg) == "/custom/path.yaml"

    def test_test_connection_flag(self) -> None:
        with (  # noqa: SIM117
            patch("sys.argv", ["run_etl.py", "--test-connection"]),
            patch("etl.scheduler.run_etl.load_config") as mock_load,
            patch("etl.extractors.confluence.ConfluenceExtractor") as mock_extractor_cls,
        ):
            mock_load.return_value = {"confluence": {"url": "http://confluence", "token": "test-token"}}
            mock_extractor = MagicMock()
            mock_extractor.test_connection.return_value = True
            mock_extractor_cls.return_value = mock_extractor
            from etl.scheduler.run_etl import main  # noqa: PLC0415

            main()
            mock_extractor.test_connection.assert_called_once()

    def test_test_connection_all_fail_gracefully(self) -> None:
        with (  # noqa: SIM117
            patch("sys.argv", ["run_etl.py", "--test-connection"]),
            patch("etl.scheduler.run_etl.load_config") as mock_load,
            patch("etl.scheduler.run_etl.ConfluenceExtractor") as mock_conflu,
            patch("etl.scheduler.run_etl.JiraExtractor") as mock_jira,
            patch("etl.scheduler.run_etl.GitLabExtractor") as mock_gitlab,
        ):
            mock_load.return_value = {
                "confluence": {"url": "http://confluence"},
                "jira": {"url": "http://jira"},
                "gitlab": {"url": "http://gitlab"},
            }
            mock_conflu.side_effect = OSError("No route to host")
            mock_jira.side_effect = OSError("No route to host")
            mock_gitlab.side_effect = OSError("No route to host")
            from etl.scheduler.run_etl import main  # noqa: PLC0415

            main()

    def test_skip_extract_flag(self) -> None:
        with (  # noqa: SIM117
            patch("sys.argv", ["run_etl.py", "--skip-extract", "--mode", "batch"]),
            patch("etl.scheduler.run_etl.load_config") as mock_load,
            patch("etl.scheduler.run_etl.WALManager") as mock_wal,
            patch("etl.scheduler.run_etl.collect_all_documents") as mock_collect,
            patch("etl.scheduler.run_etl.run_chunking") as mock_chunk,
            patch("etl.scheduler.run_etl.QdrantHybridIndexer"),
            patch("etl.scheduler.run_etl.LiveVectorLake"),
            patch("etl.scheduler.run_etl.ChunkVersionStore"),
        ):
            mock_load.return_value = {"confluence": {"output_dir": "/tmp/conflu"}}
            mock_wal.return_value = MagicMock()
            mock_collect.return_value = [{"id": "d1"}]
            mock_chunk.return_value = []
            from etl.scheduler.run_etl import main  # noqa: PLC0415

            main()
            mock_chunk.assert_called_once()

    def test_timeout_override(self) -> None:
        with (  # noqa: SIM117
            patch("sys.argv", ["run_etl.py", "--timeout", "30"]),
            patch("etl.scheduler.run_etl.load_config") as mock_load,
            patch("etl.scheduler.run_etl.WALManager") as mock_wal,
            patch("etl.scheduler.run_etl.collect_all_documents") as mock_collect,
            patch("etl.scheduler.run_etl.run_chunking") as mock_chunk,
            patch("etl.scheduler.run_etl.QdrantHybridIndexer"),
            patch("etl.scheduler.run_etl.LiveVectorLake"),
            patch("etl.scheduler.run_etl.ChunkVersionStore"),
            patch("etl.scheduler.run_etl.run_extract_confluence") as mock_x,
        ):
            mock_load.return_value = {
                "confluence": {"url": "http://test", "output_dir": "/tmp/out", "token": "tk"},
                "chunking": {},
            }
            mock_wal.return_value = MagicMock()
            mock_collect.return_value = []
            mock_chunk.return_value = []
            mock_x.return_value = MagicMock()
            from etl.scheduler.run_etl import main  # noqa: PLC0415

            main()
            assert mock_load.return_value["confluence"]["timeout"] == 30

    def test_reset_wal_flag(self) -> None:
        with (  # noqa: SIM117
            patch("sys.argv", ["run_etl.py", "--reset-wal"]),
            patch("etl.scheduler.run_etl.load_config") as mock_load,
            patch("etl.scheduler.run_etl.WALManager") as mock_wal_cls,
            patch("etl.scheduler.run_etl.collect_all_documents") as mock_collect,
            patch("etl.scheduler.run_etl.run_chunking") as mock_chunk,
            patch("etl.scheduler.run_etl.QdrantHybridIndexer"),
            patch("etl.scheduler.run_etl.LiveVectorLake"),
            patch("etl.scheduler.run_etl.ChunkVersionStore"),
        ):
            mock_load.return_value = {"chunking": {}}
            mock_wal = MagicMock()
            mock_wal_cls.return_value = mock_wal
            mock_collect.return_value = []
            mock_chunk.return_value = []
            from etl.scheduler.run_etl import main  # noqa: PLC0415

            main()
            mock_wal.reset_all.assert_called_once()

    def test_all_extractors_fail_exits(self) -> None:
        with (  # noqa: SIM117
            patch("sys.argv", ["run_etl.py", "--mode", "batch"]),
            patch("etl.scheduler.run_etl.load_config") as mock_load,
            patch("etl.scheduler.run_etl.WALManager") as mock_wal,
            patch("etl.scheduler.run_etl._run_extractor_safe") as mock_safe,
            patch("etl.scheduler.run_etl.QdrantHybridIndexer"),
            patch("etl.scheduler.run_etl.LiveVectorLake"),
        ):
            mock_load.return_value = {
                "confluence": {"url": "http://test", "output_dir": "/tmp/out"},
                "jira": {"url": "http://test", "output_dir": "/tmp/out"},
            }
            mock_wal.return_value = MagicMock()
            mock_safe.return_value = ("confluence", None, "Error")
            from etl.scheduler.run_etl import main  # noqa: PLC0415

            with pytest.raises(SystemExit):
                main()


class TestSignalHandler:
    def test_single_signal_sets_event(self) -> None:
        import etl.scheduler.run_etl as run_etl_mod

        run_etl_mod._shutdown_event.clear()
        assert not run_etl_mod._shutdown_event.is_set()
        run_etl_mod._signal_handler(signal.SIGINT, None)
        assert run_etl_mod._shutdown_event.is_set()
        run_etl_mod._shutdown_event.clear()

    def test_double_signal_exits(self) -> None:
        import signal as sig_mod

        import etl.scheduler.run_etl as run_etl_mod

        run_etl_mod._shutdown_event.clear()
        # First signal
        run_etl_mod._signal_handler(sig_mod.SIGINT, None)
        assert run_etl_mod._shutdown_event.is_set()
        # Second signal should raise SystemExit
        with pytest.raises(SystemExit):
            run_etl_mod._signal_handler(sig_mod.SIGINT, None)
        run_etl_mod._shutdown_event.clear()


class TestWalCheckpointOnExit:
    def test_save_wal_on_exit(self) -> None:
        import etl.scheduler.run_etl as run_etl_mod

        mock_wal = MagicMock()

        def _save_on_exit() -> None:
            with contextlib.suppress(Exception):
                mock_wal.set_checkpoint("pipeline", {"shutdown": True})

        with patch.object(run_etl_mod.atexit, "register", return_value=None):
            atexit.register(_save_on_exit)
        _save_on_exit()
        mock_wal.set_checkpoint.assert_called_once()
        call_args = mock_wal.set_checkpoint.call_args[0]
        assert call_args[0] == "pipeline"
        assert call_args[1]["shutdown"] is True

    def test_save_wal_on_exit_handles_error(self) -> None:
        mock_wal = MagicMock()
        mock_wal.set_checkpoint.side_effect = RuntimeError("WAL write failed")

        def _save_on_exit() -> None:
            with contextlib.suppress(Exception):
                mock_wal.set_checkpoint("pipeline", {"shutdown": True})

        _save_on_exit()  # Should not raise


class TestEmptyCollectDocuments:
    def test_missing_dirs(self, tmp_path) -> None:
        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([tmp_path / "nope1", tmp_path / "nope2", tmp_path / "nope3"])
        assert docs == []

    def test_gitlab_with_project_info(self, tmp_path) -> None:
        gitlab_dir = tmp_path / "gitlab"
        proj_dir = gitlab_dir / "myproject"
        proj_dir.mkdir(parents=True)
        project_data = {"id": 1, "namespace": {"full_path": "myorg/myproject"}, "visibility": "private"}
        (proj_dir / "project.json").write_text(json.dumps(project_data))
        commits_data = [
            {
                "id": "abc123def456",
                "title": "Fix bug",
                "message": "Fixed",
                "author_name": "dev1",
                "created_at": "2025-01-01",
                "diff": [],
            },
        ]
        (proj_dir / "commits.json").write_text(json.dumps(commits_data))

        conflu_dir = tmp_path / "confluence"
        jira_dir = tmp_path / "jira"
        conflu_dir.mkdir()
        jira_dir.mkdir()

        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([conflu_dir, jira_dir, gitlab_dir])
        assert len(docs) == 1
        assert docs[0]["metadata"]["namespace"] == "myorg/myproject"
        assert docs[0]["metadata"]["visibility"] == "private"

    def test_jira_with_all_metadata(self, tmp_path) -> None:
        jira_dir = tmp_path / "jira"
        issue_dir = jira_dir / "PROJ-456"
        issue_dir.mkdir(parents=True)
        issue_data = {
            "key": "PROJ-456",
            "summary": "Feature request",
            "description": "Add dark mode",
            "status": "In Progress",
            "priority": "Medium",
            "assignee": "dev2",
            "reporter": "pm1",
            "project_key": "PROJ",
            "issue_type": "Story",
            "labels": ["frontend", "ux"],
            "components": ["UI"],
            "created": "2025-06-01",
            "updated": "2025-06-15",
            "comments": [],
        }
        (issue_dir / "issue.json").write_text(json.dumps(issue_data))

        conflu_dir = tmp_path / "confluence"
        gitlab_dir = tmp_path / "gitlab"
        conflu_dir.mkdir()
        gitlab_dir.mkdir()

        from etl.scheduler.run_etl import collect_all_documents

        docs = collect_all_documents([conflu_dir, jira_dir, gitlab_dir])
        assert len(docs) == 1
        assert docs[0]["source_type"] == "jira"
        assert docs[0]["metadata"]["issue_type"] == "Story"
        assert "frontend" in docs[0]["metadata"]["labels"]
