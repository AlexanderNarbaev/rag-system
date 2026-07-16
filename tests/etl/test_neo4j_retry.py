# tests/etl/test_neo4j_retry.py
"""Tests for Neo4j loader retry logic: connect() and _execute_with_retry()."""

from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# connect() retry tests
# ---------------------------------------------------------------------------


class TestNeo4jConnectRetry:
    """Neo4jLoader.connect() should retry with exponential backoff on transient failures."""

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.GraphDatabase", create=True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_connect_retries_on_transient_failure_then_succeeds(self, mock_sleep, mock_gd):
        """First attempt fails with a transient error, second attempt succeeds."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        mock_driver = MagicMock()
        # First call raises transient error, second succeeds
        mock_gd.driver.side_effect = [
            Exception("ServiceUnavailable: Connection refused"),
            mock_driver,
        ]

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)
        loader.connect()

        assert loader.driver is mock_driver
        assert mock_gd.driver.call_count == 2
        mock_driver.verify_connectivity.assert_called_once()
        # Should have slept with exponential backoff (2^0 * base_delay=2 => 2s)
        mock_sleep.assert_called_once_with(2)

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.GraphDatabase", create=True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_connect_fails_after_max_retries(self, mock_sleep, mock_gd):
        """All attempts fail → should raise after max_retries exhausted."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        mock_gd.driver.side_effect = Exception("ServiceUnavailable")

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)

        with pytest.raises(Exception, match="ServiceUnavailable"):
            loader.connect()

        # Should have tried 3 times (max_retries=3)
        assert mock_gd.driver.call_count == 3
        # Should have slept 2 times (not after last attempt)
        assert mock_sleep.call_count == 2
        # Exponential backoff: 2s, 4s
        mock_sleep.assert_any_call(2)
        mock_sleep.assert_any_call(4)

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.GraphDatabase", create=True)
    def test_connect_succeeds_on_first_try(self, mock_gd):
        """No failures → connect succeeds immediately, no retries."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        mock_driver = MagicMock()
        mock_gd.driver.return_value = mock_driver

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)
        loader.connect()

        assert loader.driver is mock_driver
        assert mock_gd.driver.call_count == 1
        mock_driver.verify_connectivity.assert_called_once()

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.GraphDatabase", create=True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_connect_cleans_up_driver_on_failure(self, mock_sleep, mock_gd):
        """Failed driver should be closed and set to None before retry."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        mock_driver_1 = MagicMock()
        mock_driver_2 = MagicMock()
        # First driver fails during verify_connectivity
        mock_driver_1.verify_connectivity.side_effect = Exception("Auth error")
        # Second driver succeeds
        mock_gd.driver.side_effect = [mock_driver_1, mock_driver_2]

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)
        loader.connect()

        # First driver should have been closed
        mock_driver_1.close.assert_called_once()
        assert loader.driver is mock_driver_2

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.GraphDatabase", create=True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_connect_exponential_backoff_timing(self, mock_sleep, mock_gd):
        """Verify exponential backoff: 2s, 4s, 8s for 5 retries."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        mock_gd.driver.side_effect = Exception("Transient")

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=5)

        with pytest.raises(Exception, match="Transient"):
            loader.connect()

        # Should sleep 4 times (not after last attempt): 2, 4, 8, 16
        expected_calls = [call(2), call(4), call(8), call(16)]
        assert mock_sleep.call_args_list == expected_calls


# ---------------------------------------------------------------------------
# _execute_with_retry() tests
# ---------------------------------------------------------------------------


class TestExecuteWithRetryAdvanced:
    """_execute_with_retry should retry on transient failures and raise on permanent ones."""

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_execute_with_retry_transient_then_success(self, mock_sleep):
        """First call raises transient error, second succeeds."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)

        mock_session = MagicMock()
        mock_result_success = MagicMock()
        mock_summary = MagicMock()
        mock_summary.counters.contains_updates = True
        mock_result_success.consume.return_value = mock_summary

        # First call fails, second succeeds
        mock_session.run.side_effect = [Exception("Transient error"), mock_result_success]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session

        result = loader._execute_with_retry("CREATE (n:Test)")
        assert result is True
        assert mock_session.run.call_count == 2
        mock_sleep.assert_called_once_with(1)  # base_delay=1, 2^0 * 1 = 1

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_execute_with_retry_permanent_failure_raises(self, mock_sleep):
        """All retries fail → should raise the last exception."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)

        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Permanent failure")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session

        with pytest.raises(Exception, match="Permanent failure"):
            loader._execute_with_retry("MATCH (n) RETURN n")

        assert mock_session.run.call_count == 3
        # Should have slept 2 times (not after last attempt)
        assert mock_sleep.call_count == 2

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_execute_with_retry_exponential_backoff(self, mock_sleep):
        """Verify exponential backoff: 1s, 2s for max_retries=3."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)

        mock_session = MagicMock()
        mock_session.run.side_effect = Exception("Transient")
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session

        with pytest.raises(Exception, match="Transient"):
            loader._execute_with_retry("MATCH (n) RETURN n")

        expected_calls = [call(1), call(2)]  # 2^0*1, 2^1*1
        assert mock_sleep.call_args_list == expected_calls

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_execute_with_retry_success_on_first_try(self):
        """No failures → succeeds immediately, no retries."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_summary = MagicMock()
        mock_summary.counters.contains_updates = False
        mock_result.consume.return_value = mock_summary
        mock_session.run.return_value = mock_result
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session

        result = loader._execute_with_retry("MATCH (n) RETURN n")
        assert result is False
        assert mock_session.run.call_count == 1

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    def test_execute_with_retry_not_connected_raises(self):
        """Calling _execute_with_retry without connect() should raise RuntimeError."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass")

        with pytest.raises(RuntimeError, match="Not connected"):
            loader._execute_with_retry("MATCH (n) RETURN n")

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_execute_with_retry_passes_parameters(self, mock_sleep):
        """Verify parameters are passed through to session.run()."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=2)

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

        query = "MATCH (n {id: $id}) RETURN n"
        params = {"id": "entity_1"}
        loader._execute_with_retry(query, params)

        mock_session.run.assert_called_once_with(query, params)

    @patch("etl.graph_builder.neo4j_loader.NEO4J_AVAILABLE", True)
    @patch("etl.graph_builder.neo4j_loader.time.sleep")
    def test_execute_with_retry_two_failures_then_success(self, mock_sleep):
        """Two failures then success with max_retries=3."""
        from etl.graph_builder.neo4j_loader import Neo4jLoader

        loader = Neo4jLoader(uri="bolt://localhost:7687", user="neo4j", password="pass", max_retries=3)

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_summary = MagicMock()
        mock_summary.counters.contains_updates = True
        mock_result.consume.return_value = mock_summary

        mock_session.run.side_effect = [
            Exception("Fail 1"),
            Exception("Fail 2"),
            mock_result,
        ]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        loader.driver = MagicMock()
        loader.driver.session.return_value = mock_session

        result = loader._execute_with_retry("MERGE (n:Test {id: 'x'})")
        assert result is True
        assert mock_session.run.call_count == 3
        # Slept twice: 1s, 2s
        assert mock_sleep.call_count == 2
