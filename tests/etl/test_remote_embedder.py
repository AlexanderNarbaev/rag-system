"""Tests for etl/indexer/remote_embedder.py."""

from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from etl.indexer.remote_embedder import (
    BackoffStrategy,
    RemoteEmbedder,
    RetryConfig,
    RetryExhaustedError,
    build_remote_embedder_from_config,
    create_remote_embedder,
)


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

    def test_factory_passes_retry_config(self) -> None:
        rc = RetryConfig(max_attempts=10, base_delay=5.0)
        embedder = create_remote_embedder(url="http://host:8080/v1/embeddings", retry_config=rc)
        assert embedder._retry_config.max_attempts == 10

    def test_factory_passes_connection_pool_size(self) -> None:
        embedder = create_remote_embedder(url="http://host:8080/v1/embeddings", connection_pool_size=32)
        assert embedder._connection_pool_size == 32


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

    def test_connection_pool_size_default(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        assert embedder._connection_pool_size == 16


class TestRemoteEmbedderEncode:
    @staticmethod
    def _make_mock_session(mock_vectors: list[list[float]]) -> MagicMock:
        """Mock requests.Session().post() to return given vectors."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"embedding": v, "index": i} for i, v in enumerate(mock_vectors)]}
        mock_resp.raise_for_status = MagicMock()
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        return mock_session

    def test_encode_single_string(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        embedder._session = self._make_mock_session([[0.1, 0.2, 0.3]])
        result = embedder.encode("hello")
        assert isinstance(result, np.ndarray)
        assert result.shape == (3,)

    def test_encode_list_of_strings(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        embedder._session = self._make_mock_session([[0.1, 0.2], [0.3, 0.4]])
        result = embedder.encode(["hello", "world"])
        assert result.shape == (2, 2)

    def test_encode_empty_list(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        result = embedder.encode([])
        assert isinstance(result, np.ndarray)
        assert result.size == 0

    def test_encode_normalizes_embeddings(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        embedder._session = self._make_mock_session([[1.0, 1.0]])
        result = embedder.encode("text", normalize_embeddings=True)
        norm = np.linalg.norm(result)
        assert np.isclose(norm, 1.0)

    def test_encode_sets_embedding_dimension(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        embedder._session = self._make_mock_session([[0.1, 0.2, 0.3, 0.4]])
        embedder.encode(["a", "b"])
        assert embedder.embedding_dimension == 4

    def test_encode_batches_large_input(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings", max_batch_size=4)

        def make_response(texts_in_batch: list[str]) -> MagicMock:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": [{"embedding": [float(i), float(i + 1)], "index": i} for i in range(len(texts_in_batch))]
            }
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        def post_side_effect(url: str, **kwargs: Any) -> MagicMock:
            batch = kwargs["json"]["input"]
            return make_response(batch)

        mock_session = MagicMock()
        mock_session.post.side_effect = post_side_effect
        embedder._session = mock_session

        texts = [f"text{i}" for i in range(10)]
        result = embedder.encode(texts)
        assert result.shape == (10, 2)
        assert mock_session.post.call_count == 3

    def test_encode_marks_unhealthy_on_error(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        embedder._session = MagicMock()
        embedder._session.post.side_effect = OSError("Connection refused")
        with pytest.raises(RetryExhaustedError):
            embedder.encode("text")
        assert not embedder.is_healthy

    def test_retry_on_retryable_status(self) -> None:
        retry_cfg = RetryConfig(
            max_attempts=2,
            base_delay=0.01,
            jitter=False,
            retryable_http_statuses=(500, 502, 503),
        )
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings", retry_config=retry_cfg)

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        embedder._session = mock_session

        with pytest.raises(RetryExhaustedError):
            embedder.encode("text")
        assert mock_session.post.call_count == 2


class TestRemoteEmbedderEncodeBatch:
    def test_encode_batch_single_call(self) -> None:
        embedder = RemoteEmbedder(endpoint="http://host:8080/v1/embeddings")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"embedding": [0.1, 0.2], "index": 0}, {"embedding": [0.3, 0.4], "index": 1}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_session = MagicMock()
        mock_session.post.return_value = mock_resp
        embedder._session = mock_session

        result = embedder.encode_batch(["hello", "world"])
        assert result.shape == (2, 2)
        mock_session.post.assert_called_once()


class TestRetryConfig:
    def test_defaults(self) -> None:
        rc = RetryConfig()
        assert rc.max_attempts == 3
        assert rc.base_delay == 1.0
        assert rc.strategy == BackoffStrategy.EXPONENTIAL
        assert rc.jitter is True

    def test_custom(self) -> None:
        rc = RetryConfig(
            max_attempts=5,
            base_delay=2.0,
            strategy=BackoffStrategy.LINEAR,
            jitter=False,
        )
        assert rc.max_attempts == 5
        assert rc.strategy == BackoffStrategy.LINEAR


class TestBuildRemoteEmbedderFromConfig:
    def test_no_endpoint_returns_none(self) -> None:
        config: dict[str, Any] = {"remote_services": {"embedder": {"model": "bge-m3"}}}
        assert build_remote_embedder_from_config(config) is None

    def test_with_endpoint(self) -> None:
        config: dict[str, Any] = {
            "remote_services": {"embedder": {"endpoint": "http://embedder:8080/v1/embeddings", "model": "bge-m3"}}
        }
        embedder = build_remote_embedder_from_config(config)
        assert embedder is not None
        assert embedder._model == "bge-m3"

    def test_fallback_api_key(self) -> None:
        config: dict[str, Any] = {
            "remote_services": {
                "api_key": "global-key",
                "embedder": {"endpoint": "http://embedder:8080/v1/embeddings"},
            }
        }
        embedder = build_remote_embedder_from_config(config)
        assert embedder is not None
        assert embedder._api_key == "global-key"

    def test_embedder_specific_api_key_overrides_global(self) -> None:
        config: dict[str, Any] = {
            "remote_services": {
                "api_key": "global-key",
                "embedder": {
                    "endpoint": "http://embedder:8080/v1/embeddings",
                    "api_key": "specific-key",
                },
            }
        }
        embedder = build_remote_embedder_from_config(config)
        assert embedder is not None
        assert embedder._api_key == "specific-key"

    def test_backward_compat_url_key(self) -> None:
        config: dict[str, Any] = {
            "remote_services": {"embedder": {"url": "http://old:8080/v1/embeddings", "model": "old-model"}}
        }
        embedder = build_remote_embedder_from_config(config)
        assert embedder is not None
        assert embedder._model == "old-model"
