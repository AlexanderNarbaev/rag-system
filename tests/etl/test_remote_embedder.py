"""Tests for etl/indexer/remote_embedder.py."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from etl.indexer.remote_embedder import RemoteEmbedder, create_remote_embedder


class TestCreateRemoteEmbedder:
    def test_factory_returns_embedder(self) -> None:
        embedder = create_remote_embedder(url="http://host:8080/v1/embeddings")
        assert isinstance(embedder, RemoteEmbedder)

    def test_factory_passes_model(self) -> None:
        embedder = create_remote_embedder(url="http://host:8080/v1/embeddings", model="bge-m3")
        assert embedder._model == "bge-m3"

    def test_factory_passes_api_key(self) -> None:
        embedder = create_remote_embedder(url="http://host:8080/v1/embeddings", api_key="sk-test")
        assert embedder._api_key == "sk-test"

    def test_factory_passes_timeout(self) -> None:
        embedder = create_remote_embedder(url="http://host:8080/v1/embeddings", timeout=30)
        assert embedder._timeout == 30


class TestRemoteEmbedderProperties:
    def test_healthy_by_default(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        assert embedder.is_healthy

    def test_embedding_dimension_none_initially(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        assert embedder.embedding_dimension is None

    def test_encode_sparse_returns_none(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        assert embedder.encode_sparse("text") is None

    def test_endpoint_normalization(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        assert embedder._embedding_url == "http://host:8080/v1/embeddings"

    def test_endpoint_normalization_strips_duplicate_suffix(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings/v1/embeddings")
        assert embedder._embedding_url == "http://host:8080/v1/embeddings/v1/embeddings"

    def test_endpoint_normalization_without_suffix(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080")
        assert embedder._embedding_url == "http://host:8080/v1/embeddings"

    def test_api_key_in_headers(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings", api_key="sk-test")
        headers = embedder._make_headers()
        assert headers["Authorization"] == "Bearer sk-test"

    def test_no_api_key_in_headers(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        headers = embedder._make_headers()
        assert "Authorization" not in headers


class TestRemoteEmbedderEncode:
    def _mock_urlopen(self, vectors: list[list[float]]) -> Any:
        """Create a mock urlopen that returns the given vectors."""
        mock = MagicMock()
        data = {"data": [{"embedding": v, "index": i} for i, v in enumerate(vectors)]}
        mock.__enter__.return_value.read.return_value = json.dumps(data).encode("utf-8")
        return mock

    @patch("urllib.request.urlopen")
    def test_encode_single_string(self, mock_urlopen: Any) -> None:
        mock_urlopen.return_value = self._mock_urlopen([[0.1, 0.2, 0.3]])
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        result = embedder.encode("hello")
        assert isinstance(result, np.ndarray)
        assert result.shape == (3,)

    @patch("urllib.request.urlopen")
    def test_encode_list_of_strings(self, mock_urlopen: Any) -> None:
        mock_urlopen.return_value = self._mock_urlopen([[0.1, 0.2], [0.3, 0.4]])
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        result = embedder.encode(["hello", "world"])
        assert result.shape == (2, 2)

    @patch("urllib.request.urlopen")
    def test_encode_empty_list(self, mock_urlopen: Any) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        result = embedder.encode([])
        assert isinstance(result, np.ndarray)
        assert result.size == 0

    @patch("urllib.request.urlopen")
    def test_encode_normalizes_embeddings(self, mock_urlopen: Any) -> None:
        mock_urlopen.return_value = self._mock_urlopen([[1.0, 1.0]])
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        result = embedder.encode("text", normalize_embeddings=True)
        norm = np.linalg.norm(result)
        assert np.isclose(norm, 1.0)

    @patch("urllib.request.urlopen")
    def test_encode_sets_embedding_dimension(self, mock_urlopen: Any) -> None:
        mock_urlopen.return_value = self._mock_urlopen([[0.1, 0.2, 0.3, 0.4]])
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        embedder.encode(["a", "b"])
        assert embedder.embedding_dimension == 4

    @patch("urllib.request.urlopen")
    def test_encode_batches_large_input(self, mock_urlopen: Any) -> None:
        def side_effect(*args: Any, **kwargs: Any) -> Any:
            req = args[0]
            body = json.loads(req.data)
            texts_in_batch = body["input"]
            batch_vectors = [[float(i), float(i + 1)] for i in range(len(texts_in_batch))]
            mock = MagicMock()
            data = {"data": [{"embedding": v, "index": i} for i, v in enumerate(batch_vectors)]}
            mock.__enter__.return_value.read.return_value = json.dumps(data).encode("utf-8")
            return mock

        mock_urlopen.side_effect = side_effect
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings", max_batch_size=4)
        texts = [f"text{i}" for i in range(10)]
        result = embedder.encode(texts)
        assert result.shape == (10, 2)
        assert mock_urlopen.call_count == 3

    @patch("urllib.request.urlopen")
    def test_encode_marks_unhealthy_on_error(self, mock_urlopen: Any) -> None:
        mock_urlopen.side_effect = OSError("Connection refused")
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        with pytest.raises(OSError):
            embedder.encode("text")
        assert not embedder.is_healthy
