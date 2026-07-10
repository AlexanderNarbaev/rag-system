# tests/etl/test_live_upsert.py
"""Tests for live Qdrant upsert/delete operations (atomic chunk-level updates)."""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# PointStruct stub
# ---------------------------------------------------------------------------
# When the full suite runs, proxy tests inject MagicMock into sys.modules for
# qdrant_client.http.models *before* this file is collected.  That causes
# etl.indexer.qdrant_hybrid.PointStruct to resolve to a MagicMock instead of
# the real class, breaking assertions on point.id / point.payload.
#
# We define a lightweight stand-in that the indexer fixture patches in so
# _chunk_to_point() produces objects with real .id / .vector / .payload.
# ---------------------------------------------------------------------------


class _StubPointStruct:
    """Minimal PointStruct replacement used when the real class is unavailable."""

    def __init__(self, id=None, vector=None, payload=None, **kwargs):
        self.id = id
        self.vector = vector
        self.payload = payload or {}


@pytest.fixture
def mock_qdrant_client():
    client = MagicMock()
    client.get_collections.return_value = MagicMock()
    client.upsert.return_value = None
    client.delete.return_value = None
    client.collection_exists.return_value = True
    return client


@pytest.fixture
def mock_embedder():
    with patch("sentence_transformers.SentenceTransformer") as mock_st:
        instance = mock_st.return_value
        obj = MagicMock()
        obj.tolist.return_value = [0.1] * 1024
        instance.encode.return_value = obj
        sparse_obj = MagicMock()
        sparse_obj.tolist.side_effect = [[1, 5, 10], [0.5, 0.3, 0.2]]
        instance.encode_sparse.return_value = {
            "indices": [1, 5, 10],
            "values": [0.5, 0.3, 0.2],
        }
        yield mock_st


@pytest.fixture
def indexer(mock_qdrant_client, mock_embedder):
    """Build a QdrantHybridIndexer with mocked internals.

    Patches ``etl.indexer.qdrant_hybrid.PointStruct`` with ``_StubPointStruct``
    to avoid the MagicMock contamination from proxy test sys.modules injection.
    """
    from etl.indexer import qdrant_hybrid

    # Ensure PointStruct produces real objects (not MagicMock from sys.modules)
    with patch.object(qdrant_hybrid, "PointStruct", _StubPointStruct):
        from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

        idx = QdrantHybridIndexer.__new__(QdrantHybridIndexer)
        idx.client = mock_qdrant_client
        idx.collection_name = "knowledge_base"
        idx.embedder = mock_embedder.return_value
        idx.dense_vector_size = 1024
        idx.batch_size = 100
        idx.sparse_index_on_disk = True
        idx.supports_sparse = True
        yield idx


def _make_chunk_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class TestLiveUpsert:
    def test_live_upsert_single_chunk(self, indexer, mock_qdrant_client):
        chunk = {
            "hash": _make_chunk_hash("test content"),
            "text": "test content for live upsert",
            "title": "Test Chunk",
            "source_type": "confluence",
            "source_id": "conf_123",
            "version": "1.0",
            "doc_title": "Test Doc",
            "keywords": ["test"],
            "entities": [],
            "summary": "test summary",
        }

        result = indexer.live_upsert(chunk)
        assert result is True
        mock_qdrant_client.upsert.assert_called_once()

    def test_live_upsert_uses_hash_as_point_id(self, indexer, mock_qdrant_client):
        chunk_hash = _make_chunk_hash("idempotent content")
        chunk = {
            "hash": chunk_hash,
            "text": "idempotent content",
            "title": "Idempotent",
            "source_type": "gitlab_commit",
            "source_id": "gl_1",
        }

        indexer.live_upsert(chunk)
        call_args = mock_qdrant_client.upsert.call_args
        points = call_args[1]["points"] if "points" in call_args[1] else call_args[0][1]
        assert points[0].id == chunk_hash

    def test_live_upsert_missing_hash_returns_false(self, indexer):
        chunk = {"text": "no hash field", "title": "Bad"}
        result = indexer.live_upsert(chunk)
        assert result is False

    def test_live_upsert_empty_text_returns_false(self, indexer):
        chunk = {"hash": "abc123", "text": "", "title": "Empty"}
        result = indexer.live_upsert(chunk)
        assert result is False

    def test_live_upsert_missing_text_returns_false(self, indexer):
        chunk = {"hash": "abc123", "title": "No text"}
        result = indexer.live_upsert(chunk)
        assert result is False

    def test_live_upsert_preserves_payload_fields(self, indexer, mock_qdrant_client):
        chunk = {
            "hash": _make_chunk_hash("payload test"),
            "text": "payload test content",
            "title": "Payload",
            "source_type": "jira",
            "source_id": "jira_1",
            "version": "2.0",
            "doc_title": "Jira Doc",
            "keywords": ["k1", "k2"],
            "entities": ["E1"],
            "summary": "sum",
            "position": 3,
            "semantic_key": "sk1",
            "created_at": "2025-01-01",
            "updated_at": "2025-06-01",
        }

        indexer.live_upsert(chunk)
        call_args = mock_qdrant_client.upsert.call_args
        points = call_args[1]["points"] if "points" in call_args[1] else call_args[0][1]
        payload = points[0].payload
        assert payload["text"] == "payload test content"
        assert payload["source_type"] == "jira"
        assert payload["version"] == "2.0"
        assert "keywords" in payload

    def test_live_upsert_qdrant_error_returns_false(self, indexer, mock_qdrant_client):
        mock_qdrant_client.upsert.side_effect = Exception("Qdrant connection error")
        chunk = {
            "hash": _make_chunk_hash("error test"),
            "text": "error test content",
            "title": "Error",
            "source_type": "confluence",
            "source_id": "conf_err",
        }
        result = indexer.live_upsert(chunk)
        assert result is False


class TestLiveDelete:
    def test_live_delete_by_chunk_id(self, indexer, mock_qdrant_client):
        chunk_id = "abc123def456"
        result = indexer.live_delete(chunk_id)
        assert result is True
        mock_qdrant_client.delete.assert_called_once()

    def test_live_delete_uses_point_id_list(self, indexer, mock_qdrant_client):
        chunk_id = "delete_me_hash"
        indexer.live_delete(chunk_id)
        call_args = mock_qdrant_client.delete.call_args
        selector = call_args[1].get("points_selector") or call_args[0][1]
        assert selector is not None

    def test_live_delete_empty_id_returns_false(self, indexer):
        result = indexer.live_delete("")
        assert result is False

    def test_live_delete_none_id_returns_false(self, indexer):
        result = indexer.live_delete(None)
        assert result is False

    def test_live_delete_qdrant_error_returns_false(self, indexer, mock_qdrant_client):
        mock_qdrant_client.delete.side_effect = Exception("Qdrant connection error")
        result = indexer.live_delete("valid_id")
        assert result is False

    def test_live_delete_idempotent(self, indexer, mock_qdrant_client):
        result = indexer.live_delete("same_id")
        assert result is True
        result = indexer.live_delete("same_id")
        assert result is True
        assert mock_qdrant_client.delete.call_count == 2
