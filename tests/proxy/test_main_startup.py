# tests/proxy/test_main_startup.py
"""Tests for proxy startup functions — auto-provisioning, initialization."""

from unittest.mock import MagicMock, patch


class TestEnsureQdrantCollection:
    """Test _ensure_qdrant_collection() in main.py."""

    @patch("proxy.app.main.COLLECTION_NAME", "test_kb")
    def test_creates_collection_when_not_exists(self):
        from proxy.app.main import _ensure_qdrant_collection

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.create_collection.return_value = True
        mock_client.create_payload_index.return_value = MagicMock()

        with patch("proxy.app.core.retrieval.qdrant_client", mock_client):
            _ensure_qdrant_collection()

        mock_client.create_collection.assert_called_once()

    @patch("proxy.app.main.COLLECTION_NAME", "test_kb")
    def test_skips_when_collection_exists(self):
        from proxy.app.main import _ensure_qdrant_collection

        mock_collection = MagicMock()
        mock_collection.name = "test_kb"
        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[mock_collection])

        with patch("proxy.app.core.retrieval.qdrant_client", mock_client):
            _ensure_qdrant_collection()

        mock_client.create_collection.assert_not_called()

    @patch("proxy.app.main.COLLECTION_NAME", "test_kb")
    def test_skips_when_client_is_none(self):
        from proxy.app.main import _ensure_qdrant_collection

        with patch("proxy.app.core.retrieval.qdrant_client", None):
            _ensure_qdrant_collection()

    @patch("proxy.app.main.COLLECTION_NAME", "test_kb")
    def test_handles_create_collection_error(self):
        from proxy.app.main import _ensure_qdrant_collection

        mock_client = MagicMock()
        mock_client.get_collections.side_effect = Exception("Qdrant timeout")

        with patch("proxy.app.core.retrieval.qdrant_client", mock_client):
            _ensure_qdrant_collection()
