# ruff: noqa: E501, E402
"""Tests for proxy/app/llm/remote_services.py."""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestRemoteEmbeddingClient:
    """Tests for RemoteEmbeddingClient class."""

    def test_init_defaults(self):
        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
        assert client._endpoint == "http://localhost:8080"
        assert client._model == "default"
        assert client._healthy is True

    def test_init_strips_trailing_slash(self):
        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        client = RemoteEmbeddingClient(endpoint="http://localhost:8080/")
        assert client._endpoint == "http://localhost:8080"

    def test_encode_empty_input(self):
        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
        result = client.encode([])
        assert isinstance(result, np.ndarray)
        assert len(result) == 0

    def test_encode_sparse_returns_none(self):
        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
        assert client.encode_sparse("hello") is None

    def test_is_healthy_property(self):
        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
        assert client.is_healthy is True
        client._healthy = False
        assert client.is_healthy is False

    def test_check_health_already_unhealthy(self):
        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
        client._healthy = False
        assert client._check_health() is False

    def test_encode_single_text(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            client = RemoteEmbeddingClient(endpoint="http://localhost:8080", model="test-model")
            result = client.encode("hello world")
            assert isinstance(result, np.ndarray)
            assert result.shape == (3,)

    def test_encode_multiple_texts(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "data": [
                    {"embedding": [0.1, 0.2, 0.3], "index": 0},
                    {"embedding": [0.4, 0.5, 0.6], "index": 1},
                ]
            }
        ).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
            result = client.encode(["text1", "text2"])
            assert result.shape == (2, 3)

    def test_encode_http_error(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        with patch.object(urllib.request, "urlopen", side_effect=Exception("Connection refused")):
            client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
            with pytest.raises(Exception, match="Connection refused"):
                client.encode("hello")
            assert client._healthy is False

    def test_check_health_success(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        with patch.object(urllib.request, "urlopen", return_value=MagicMock()):
            client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
            assert client._check_health() is True

    def test_check_health_failure(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        with patch.object(urllib.request, "urlopen", side_effect=Exception("Refused")):
            client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
            assert client._check_health() is False
            assert client._healthy is False

    def test_encode_with_api_key(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": [{"embedding": [0.1], "index": 0}]}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            client = RemoteEmbeddingClient(endpoint="http://localhost:8080", api_key="test-key")
            result = client.encode("hello")
            assert isinstance(result, np.ndarray)

    def test_encode_no_normalization(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteEmbeddingClient

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": [{"embedding": [3.0, 4.0], "index": 0}]}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            client = RemoteEmbeddingClient(endpoint="http://localhost:8080")
            result = client.encode("hello", normalize_embeddings=False)
            # Without normalization, values should be [3.0, 4.0]
            assert result[0] == pytest.approx(3.0)


class TestRemoteRerankerClient:
    """Tests for RemoteRerankerClient class."""

    def test_init_defaults(self):
        from proxy.app.llm.remote_services import RemoteRerankerClient

        client = RemoteRerankerClient(endpoint="http://localhost:8080")
        assert client._endpoint == "http://localhost:8080"
        assert client._model == "default"
        assert client._healthy is True
        assert client.max_length == 512

    def test_max_length_setter(self):
        from proxy.app.llm.remote_services import RemoteRerankerClient

        client = RemoteRerankerClient(endpoint="http://localhost:8080")
        client.max_length = 1024
        assert client.max_length == 1024

    def test_predict_empty_pairs(self):
        from proxy.app.llm.remote_services import RemoteRerankerClient

        client = RemoteRerankerClient(endpoint="http://localhost:8080")
        result = client.predict([])
        assert isinstance(result, np.ndarray)
        assert len(result) == 0

    def test_predict_success(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteRerankerClient

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 1, "relevance_score": 0.3},
                ]
            }
        ).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            client = RemoteRerankerClient(endpoint="http://localhost:8080", model="test-model")
            result = client.predict([("query", "doc1"), ("query", "doc2")])
            assert len(result) == 2
            assert result[0] == pytest.approx(0.9)
            assert result[1] == pytest.approx(0.3)

    def test_predict_http_error(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteRerankerClient

        with patch.object(urllib.request, "urlopen", side_effect=Exception("Timeout")):
            client = RemoteRerankerClient(endpoint="http://localhost:8080")
            with pytest.raises(Exception, match="Timeout"):
                client.predict([("query", "doc1")])
            assert client._healthy is False

    def test_check_health_success(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteRerankerClient

        with patch.object(urllib.request, "urlopen", return_value=MagicMock()):
            client = RemoteRerankerClient(endpoint="http://localhost:8080")
            assert client._check_health() is True

    def test_check_health_failure(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteRerankerClient

        with patch.object(urllib.request, "urlopen", side_effect=Exception("Refused")):
            client = RemoteRerankerClient(endpoint="http://localhost:8080")
            assert client._check_health() is False

    def test_check_health_already_unhealthy(self):
        from proxy.app.llm.remote_services import RemoteRerankerClient

        client = RemoteRerankerClient(endpoint="http://localhost:8080")
        client._healthy = False
        assert client._check_health() is False

    def test_predict_multiple_queries(self):
        import urllib.request

        from proxy.app.llm.remote_services import RemoteRerankerClient

        call_count = [0]

        def mock_urlopen(req, timeout=60):
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"results": [{"index": 0, "relevance_score": 0.8}]}).encode(
                "utf-8"
            )
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            call_count[0] += 1
            return mock_resp

        with patch.object(urllib.request, "urlopen", side_effect=mock_urlopen):
            client = RemoteRerankerClient(endpoint="http://localhost:8080")
            result = client.predict([("q1", "doc1"), ("q2", "doc2")])
            assert len(result) == 2


class TestFactoryFunctions:
    """Tests for create_embedder and create_reranker factory functions."""

    @patch("proxy.app.llm.remote_services.EMBEDDER_ENDPOINT", "http://remote:8080")
    @patch("proxy.app.llm.remote_services.EMBEDDER_API_KEY", "test-key")
    @patch("proxy.app.llm.remote_services.EMBEDDER_MODEL", "test-model")
    @patch("proxy.app.llm.remote_services.RemoteEmbeddingClient._check_health", return_value=True)
    def test_create_embedder_remote(self, mock_health):
        import proxy.app.llm.remote_services as rs

        rs._embedder_instance = None
        embedder = rs.create_embedder()
        assert embedder is not None
        rs._embedder_instance = None

    @patch("proxy.app.llm.remote_services.EMBEDDER_ENDPOINT", "http://remote:8080")
    @patch("proxy.app.llm.remote_services.EMBEDDER_FALLBACK_LOCAL", False)
    @patch("proxy.app.llm.remote_services.RemoteEmbeddingClient._check_health", return_value=False)
    def test_create_embedder_remote_no_fallback(self, mock_health):
        import proxy.app.llm.remote_services as rs

        rs._embedder_instance = None
        with pytest.raises(ConnectionError):
            rs.create_embedder()
        rs._embedder_instance = None

    @patch("proxy.app.llm.remote_services.EMBEDDER_ENDPOINT", "")
    @patch("proxy.app.llm.remote_services.EMBEDDER_MODEL", "")
    def test_create_embedder_no_model_raises(self):
        import proxy.app.llm.remote_services as rs

        rs._embedder_instance = None
        with pytest.raises((ValueError, ImportError)):
            rs.create_embedder()
        rs._embedder_instance = None

    @patch("proxy.app.llm.remote_services.RERANKER_ENDPOINT", "http://remote:8080")
    @patch("proxy.app.llm.remote_services.RERANKER_API_KEY", "test-key")
    @patch("proxy.app.llm.remote_services.RERANKER_MODEL", "test-model")
    @patch("proxy.app.llm.remote_services.RemoteRerankerClient._check_health", return_value=True)
    def test_create_reranker_remote(self, mock_health):
        import proxy.app.llm.remote_services as rs

        rs._reranker_instance = None
        reranker = rs.create_reranker()
        assert reranker is not None
        rs._reranker_instance = None

    @patch("proxy.app.llm.remote_services.RERANKER_ENDPOINT", "http://remote:8080")
    @patch("proxy.app.llm.remote_services.RERANKER_FALLBACK_LOCAL", False)
    @patch("proxy.app.llm.remote_services.RemoteRerankerClient._check_health", return_value=False)
    def test_create_reranker_remote_no_fallback(self, mock_health):
        import proxy.app.llm.remote_services as rs

        rs._reranker_instance = None
        with pytest.raises(ConnectionError):
            rs.create_reranker()
        rs._reranker_instance = None

    @patch("proxy.app.llm.remote_services.RERANKER_ENDPOINT", "")
    @patch("proxy.app.llm.remote_services.RERANKER_MODEL", "")
    def test_create_reranker_no_model_raises(self):
        import proxy.app.llm.remote_services as rs

        rs._reranker_instance = None
        with pytest.raises((ValueError, ImportError)):
            rs.create_reranker()
        rs._reranker_instance = None

    def test_get_embedder_returns_none_by_default(self):
        import proxy.app.llm.remote_services as rs

        old = rs._embedder_instance
        rs._embedder_instance = None
        assert rs.get_embedder() is None
        rs._embedder_instance = old

    def test_get_reranker_returns_none_by_default(self):
        import proxy.app.llm.remote_services as rs

        old = rs._reranker_instance
        rs._reranker_instance = None
        assert rs.get_reranker() is None
        rs._reranker_instance = old

    @patch("proxy.app.llm.remote_services.EMBEDDER_ENDPOINT", "http://remote:8080")
    @patch("proxy.app.llm.remote_services.EMBEDDER_FALLBACK_LOCAL", True)
    @patch("proxy.app.llm.remote_services.EMBEDDER_MODEL", "")
    @patch("proxy.app.llm.remote_services.RemoteEmbeddingClient._check_health", return_value=False)
    def test_create_embedder_fallback_no_model(self, mock_health):
        import proxy.app.llm.remote_services as rs

        rs._embedder_instance = None
        with pytest.raises((ValueError, ImportError)):
            rs.create_embedder()
        rs._embedder_instance = None

    @patch("proxy.app.llm.remote_services.RERANKER_ENDPOINT", "http://remote:8080")
    @patch("proxy.app.llm.remote_services.RERANKER_FALLBACK_LOCAL", True)
    @patch("proxy.app.llm.remote_services.RERANKER_MODEL", "")
    @patch("proxy.app.llm.remote_services.RemoteRerankerClient._check_health", return_value=False)
    def test_create_reranker_fallback_no_model(self, mock_health):
        import proxy.app.llm.remote_services as rs

        rs._reranker_instance = None
        with pytest.raises((ValueError, ImportError)):
            rs.create_reranker()
        rs._reranker_instance = None

    @patch("proxy.app.llm.remote_services.RemoteEmbeddingClient._check_health", return_value=True)
    def test_create_embedder_caches_instance(self, mock_health):
        import proxy.app.llm.remote_services as rs

        rs._embedder_instance = None
        with patch("proxy.app.llm.remote_services.EMBEDDER_ENDPOINT", "http://remote:8080"):
            e1 = rs.create_embedder()
            e2 = rs.create_embedder()
            assert e1 is e2
        rs._embedder_instance = None

    @patch("proxy.app.llm.remote_services.RemoteRerankerClient._check_health", return_value=True)
    def test_create_reranker_caches_instance(self, mock_health):
        import proxy.app.llm.remote_services as rs

        rs._reranker_instance = None
        with patch("proxy.app.llm.remote_services.RERANKER_ENDPOINT", "http://remote:8080"):
            r1 = rs.create_reranker()
            r2 = rs.create_reranker()
            assert r1 is r2
        rs._reranker_instance = None
