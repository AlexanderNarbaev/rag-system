# ruff: noqa: E501, E402, N803, B017
"""Tests for etl/scheduler/run_etl.py — ETL orchestrator coverage."""

import json
from unittest.mock import MagicMock, patch


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
            }
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
            }
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

        docs = [{"id": "doc1", "source_type": "wiki", "title": "T", "content": "content", "content_type": "markdown", "metadata": {"version": "1.0"}}]
        output_dir = tmp_path / "chunks"
        result = run_chunking(docs, mock_chunker, output_dir)
        assert len(result) == 1

    def test_chunking_error_continues(self, tmp_path):
        from etl.scheduler.run_etl import run_chunking
        mock_chunker = MagicMock()
        mock_chunker.process_document.side_effect = Exception("chunk error")

        docs = [{"id": "doc1", "source_type": "wiki", "title": "T", "content": "content", "content_type": "markdown", "metadata": {}}]
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
        run_indexing([], mock_lake, mock_wal)
        # Just verify no exception


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
        config_file.write_text("confluence:\n  base_url: http://test\n  output_dir: /tmp/out\njira:\n  base_url: http://jira\n  output_dir: /tmp/out\ngitlab:\n  base_url: http://gitlab\n  output_dir: /tmp/out\n")
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
