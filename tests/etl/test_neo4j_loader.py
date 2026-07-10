# ruff: noqa: E501, E402, N803, B017
"""Tests for etl/graph_builder/neo4j_loader.py — Neo4j loader coverage."""

from unittest.mock import MagicMock, patch

import pytest


class TestNeo4jLoaderInit:
    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_init_with_defaults(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        assert loader.uri == "bolt://localhost:7687"
        assert loader.user == "neo4j"
        assert loader.database == "neo4j"
        assert loader.batch_size == 500
        assert loader.max_retries == 3

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_init_with_custom_params(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(
            uri="bolt://remote:7687", user="admin", password="secret",
            database="mydb", batch_size=100, max_retries=5
        )
        assert loader.database == "mydb"
        assert loader.batch_size == 100
        assert loader.max_retries == 5

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", False)
    def test_init_import_error(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        with pytest.raises(ImportError):
            Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")


class TestNeo4jLoaderConnect:
    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.GraphDatabase")
    def test_connect(self, MockGD):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        mock_driver = MagicMock()
        MockGD.driver.return_value = mock_driver
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        loader.connect()
        assert loader.driver is mock_driver
        mock_driver.verify_connectivity.assert_called_once()

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_close(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        mock_driver = MagicMock()
        loader.driver = mock_driver
        loader.close()
        mock_driver.close.assert_called_once()

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_close_no_driver(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        loader.close()  # Should not raise

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.GraphDatabase")
    def test_context_manager(self, MockGD):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        MockGD.driver.return_value = MagicMock()
        with Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass") as loader:
            assert loader.driver is not None


class TestExecuteWithRetry:
    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_not_connected_raises(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        with pytest.raises(RuntimeError, match="Not connected"):
            loader._execute_with_retry("MATCH (n) RETURN n")

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_success_on_first_try(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_summary = MagicMock()
        mock_summary.counters.contains_updates = True
        mock_result.consume.return_value = mock_summary
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session
        result = loader._execute_with_retry("CREATE (n:Test)")
        assert result is True

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_retry_on_failure(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=2)
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_summary = MagicMock()
        mock_summary.counters.contains_updates = False
        mock_result.consume.return_value = mock_summary
        # First call fails, second succeeds
        mock_session.run.side_effect = [Exception("transient error"), mock_result]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session
        result = loader._execute_with_retry("MATCH (n) RETURN n")
        assert result is False


class TestLoadEntities:
    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_empty_entities(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        result = loader.load_entities([])
        assert result == 0

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_load_with_mock(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", batch_size=2)
        loader._execute_with_retry = MagicMock(return_value=True)
        entities = [
            {"id": "e1", "name": "Test1", "type": "PERSON", "source_id": "doc1", "properties": {}},
            {"id": "e2", "name": "Test2", "type": "ORGANIZATION", "source_id": "doc2", "properties": {}},
            {"id": "e3", "name": "Test3", "type": "TECHNOLOGY", "source_id": "doc3", "properties": {}},
        ]
        result = loader.load_entities(entities)
        assert result == 3

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_load_failure_raises(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        loader._execute_with_retry = MagicMock(side_effect=Exception("neo4j error"))
        entities = [{"id": "e1", "name": "Test", "type": "PERSON", "source_id": "doc1", "properties": {}}]
        with pytest.raises(Exception, match="neo4j error"):
            loader.load_entities(entities)


class TestLoadRelations:
    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_empty_relations(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        result = loader.load_relations([])
        assert result == 0

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_load_with_apoc(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        loader._execute_with_retry = MagicMock(return_value=True)
        relations = [{"source": "e1", "target": "e2", "type": "RELATED", "properties": {}}]
        result = loader.load_relations(relations)
        assert result == 1

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_load_fallback_to_merge(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        # First call (APOC) fails, second (fallback) succeeds
        loader._execute_with_retry = MagicMock(side_effect=[Exception("no apoc"), True])
        relations = [{"source": "e1", "target": "e2", "type": "RELATED", "properties": {}}]
        result = loader.load_relations(relations)
        assert result == 1


class TestDeleteOutdatedEntities:
    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_empty_source_ids(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        result = loader.delete_outdated_entities([])
        assert result == 0

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_delete_with_mock(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        loader._execute_with_retry = MagicMock(return_value=True)
        mock_session = MagicMock()
        mock_record = {"deleted": 5}
        mock_session.run.return_value.single.return_value = mock_record
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session
        result = loader.delete_outdated_entities(["doc1", "doc2"])
        assert result == 5


class TestGetGraphStatistics:
    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_statistics(self):
        from etl.graph_builder.neo4j_loader import Neo4jLoader
        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")
        mock_session = MagicMock()
        # First query for nodes
        mock_result1 = MagicMock()
        mock_result1.single.return_value = {"total_nodes": 100, "labels": []}
        mock_session.run.side_effect = [mock_result1, MagicMock(single=MagicMock(return_value={"total_rels": 50}))]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session
        stats = loader.get_graph_statistics()
        assert stats["nodes"] == 100
        assert stats["relations"] == 50


class TestBatchLoadFromExtractor:
    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_basic_batch_load(self):
        from etl.graph_builder.neo4j_loader import batch_load_from_extractor
        loader = MagicMock()
        loader.load_entities.return_value = 2
        loader.load_relations.return_value = 1
        entities = [
            {"id": "e1", "name": "Test", "type": "PERSON", "source_id": "doc1", "properties": {}},
            {"id": "e2", "name": "Org", "type": "ORGANIZATION", "source_id": "doc1", "properties": {}},
        ]
        relations = [{"source": "e1", "target": "e2", "type": "WORKS_AT", "properties": {}}]
        batch_load_from_extractor(loader, entities, relations)
        loader.load_entities.assert_called_once()
        loader.load_relations.assert_called_once()

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_batch_load_with_clear_old(self):
        from etl.graph_builder.neo4j_loader import batch_load_from_extractor
        loader = MagicMock()
        loader.load_entities.return_value = 1
        loader.load_relations.return_value = 0
        entities = [{"id": "e1", "name": "Test", "type": "PERSON", "source_id": "doc1", "properties": {}}]
        batch_load_from_extractor(loader, entities, [], clear_old=True, valid_source_ids=["doc1"])
        loader.delete_outdated_entities.assert_called_once_with(["doc1"])
