# tests/etl/test_wal_remote.py
"""Tests for FR-08: Remote WAL storage (Redis and Proxy backends)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestFileWALBackend:
    def test_init_creates_wal_file(self, tmp_path):
        from etl.indexer.wal_manager import FileWALBackend

        wal_path = tmp_path / "test_wal.json"
        backend = FileWALBackend(wal_path, use_lock=False)
        assert wal_path.exists()
        assert backend.read() == {}

    def test_read_write_round_trip(self, tmp_path):
        from etl.indexer.wal_manager import FileWALBackend

        wal_path = tmp_path / "test_wal.json"
        backend = FileWALBackend(wal_path, use_lock=False)
        data = {"pipeline_a": {"last_run": "2025-01-01", "count": 42}}
        backend.write(data)
        assert backend.read() == data

    def test_read_corrupted_file(self, tmp_path):
        from etl.indexer.wal_manager import FileWALBackend

        wal_path = tmp_path / "corrupted.json"
        wal_path.write_text("not valid json{")
        backend = FileWALBackend(wal_path, use_lock=False)
        assert backend.read() == {}

    def test_read_missing_file(self, tmp_path):
        from etl.indexer.wal_manager import FileWALBackend

        wal_path = tmp_path / "missing.json"
        backend = FileWALBackend(wal_path, use_lock=False)
        # FileWALBackend creates the file on init, so it should work
        assert backend.read() == {}


class TestRedisWALBackend:
    def test_init_defaults(self):
        from etl.indexer.wal_manager import RedisWALBackend

        backend = RedisWALBackend()
        assert backend.redis_host == "localhost"
        assert backend.redis_port == 6379
        assert backend.key_prefix == "etl:wal"

    def test_custom_params(self):
        from etl.indexer.wal_manager import RedisWALBackend

        backend = RedisWALBackend(redis_host="redis.example.com", redis_port=6380, key_prefix="custom:wal")
        assert backend.redis_host == "redis.example.com"
        assert backend.redis_port == 6380
        assert backend.key_prefix == "custom:wal"

    def test_read(self):
        from unittest.mock import MagicMock, patch

        from etl.indexer.wal_manager import RedisWALBackend

        mock_redis = MagicMock()
        mock_redis.keys.return_value = ["etl:wal:pipeline_a", "etl:wal:pipeline_b"]
        mock_redis.get.side_effect = [
            json.dumps({"last_run": "2025-01-01", "count": 42}),
            json.dumps({"last_run": "2025-06-01", "status": "ok"}),
        ]

        with patch.object(RedisWALBackend, "_get_redis", return_value=mock_redis):
            backend = RedisWALBackend()
            result = backend.read()
        assert "pipeline_a" in result
        assert result["pipeline_a"]["count"] == 42
        assert "pipeline_b" in result
        assert result["pipeline_b"]["status"] == "ok"

    def test_read_with_corrupted_value(self):
        from unittest.mock import MagicMock, patch

        from etl.indexer.wal_manager import RedisWALBackend

        mock_redis = MagicMock()
        mock_redis.keys.return_value = ["etl:wal:bad_pipeline"]
        mock_redis.get.return_value = "not valid json{{{"

        with patch.object(RedisWALBackend, "_get_redis", return_value=mock_redis):
            backend = RedisWALBackend()
            result = backend.read()
        assert "bad_pipeline" in result
        assert result["bad_pipeline"] == {}

    def test_read_connection_error(self):
        from unittest.mock import patch

        from etl.indexer.wal_manager import RedisWALBackend

        with patch.object(RedisWALBackend, "_get_redis", side_effect=ConnectionRefusedError("No Redis")):
            backend = RedisWALBackend()
            result = backend.read()
        assert result == {}

    def test_write(self):
        from unittest.mock import MagicMock, patch

        from etl.indexer.wal_manager import RedisWALBackend

        mock_redis = MagicMock()
        mock_pipeline = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline

        with patch.object(RedisWALBackend, "_get_redis", return_value=mock_redis):
            backend = RedisWALBackend()
            backend.write({"pipe_a": {"x": 1}, "pipe_b": {"y": 2}})
        assert mock_pipeline.set.call_count == 2
        mock_pipeline.execute.assert_called_once()


class TestProxyWALBackend:
    def test_init(self):
        from etl.indexer.wal_manager import ProxyWALBackend

        backend = ProxyWALBackend(proxy_url="http://proxy:8080")
        assert backend.proxy_url == "http://proxy:8080"
        assert backend.api_key is None

    def test_init_with_api_key(self):
        from etl.indexer.wal_manager import ProxyWALBackend

        backend = ProxyWALBackend(proxy_url="http://proxy:8080", api_key="secret")
        assert backend.api_key == "secret"

    @patch("urllib.request.urlopen")
    def test_read(self, mock_urlopen):
        from etl.indexer.wal_manager import ProxyWALBackend

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "checkpoints": {"pipe_a": {"last_run": "2025-01-01"}, "pipe_b": {"count": 10}},
                "count": 2,
            }
        ).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        backend = ProxyWALBackend(proxy_url="http://proxy:8080")
        result = backend.read()
        assert "pipe_a" in result
        assert result["pipe_a"]["last_run"] == "2025-01-01"
        assert result["pipe_b"]["count"] == 10

    @patch("urllib.request.urlopen")
    def test_read_connection_error(self, mock_urlopen):
        from etl.indexer.wal_manager import ProxyWALBackend

        mock_urlopen.side_effect = OSError("Connection refused")
        backend = ProxyWALBackend(proxy_url="http://proxy:8080")
        result = backend.read()
        assert result == {}

    @patch("urllib.request.urlopen")
    def test_write(self, mock_urlopen):
        from etl.indexer.wal_manager import ProxyWALBackend

        mock_response = MagicMock()
        mock_response.status = 201
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        backend = ProxyWALBackend(proxy_url="http://proxy:8080")
        backend.write({"pipe_a": {"x": 1}})
        mock_urlopen.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_write_error(self, mock_urlopen):
        from etl.indexer.wal_manager import ProxyWALBackend

        mock_urlopen.side_effect = OSError("Connection refused")
        backend = ProxyWALBackend(proxy_url="http://proxy:8080")
        with pytest.raises(OSError):
            backend.write({"pipe_a": {"x": 1}})


class TestCreateWALManager:
    def test_default_file_backend(self):
        from etl.indexer.wal_manager import create_wal_manager

        config = {"wal": {"wal_file": "./wal/test.json"}}
        wm = create_wal_manager(config)
        assert wm is not None
        assert wm.wal_path == Path("./wal/test.json")

    def test_redis_backend(self):
        from etl.indexer.wal_manager import RedisWALBackend, create_wal_manager

        config = {
            "wal": {
                "wal_backend": "redis",
                "redis_host": "redis.local",
                "redis_port": 6380,
            },
        }
        wm = create_wal_manager(config)
        assert isinstance(wm._backend, RedisWALBackend)
        assert wm._backend.redis_host == "redis.local"
        assert wm._backend.redis_port == 6380

    def test_proxy_backend(self):
        from etl.indexer.wal_manager import ProxyWALBackend, create_wal_manager

        config = {
            "wal": {
                "wal_backend": "proxy",
                "proxy_url": "http://proxy.local:8080",
            },
        }
        wm = create_wal_manager(config)
        assert isinstance(wm._backend, ProxyWALBackend)
        assert wm._backend.proxy_url == "http://proxy.local:8080"

    def test_unknown_backend_falls_back_to_file(self):
        from etl.indexer.wal_manager import FileWALBackend, create_wal_manager

        config = {"wal": {"wal_backend": "unknown", "wal_file": "./wal/test.json"}}
        wm = create_wal_manager(config)
        assert isinstance(wm._backend, FileWALBackend)

    def test_redis_backend_via_env_var(self, monkeypatch):
        from etl.indexer.wal_manager import RedisWALBackend, create_wal_manager

        monkeypatch.setenv("WAL_BACKEND", "redis")
        monkeypatch.setenv("REDIS_HOST", "redis-env.local")
        monkeypatch.setenv("REDIS_PORT", "6381")
        config: dict = {}
        wm = create_wal_manager(config)
        assert isinstance(wm._backend, RedisWALBackend)
        assert wm._backend.redis_host == "redis-env.local"
        assert wm._backend.redis_port == 6381

    def test_proxy_backend_via_env_var(self, monkeypatch):
        from etl.indexer.wal_manager import ProxyWALBackend, create_wal_manager

        monkeypatch.setenv("WAL_BACKEND", "proxy")
        monkeypatch.setenv("PROXY_URL", "http://env-proxy:9090")
        config: dict = {}
        wm = create_wal_manager(config)
        assert isinstance(wm._backend, ProxyWALBackend)
        assert wm._backend.proxy_url == "http://env-proxy:9090"


class TestWALManagerWithBackend:
    def test_wal_manager_with_redis_backend(self):
        from unittest.mock import MagicMock

        from etl.indexer.wal_manager import WALManager

        mock_backend = MagicMock()
        mock_backend.read.return_value = {}
        wm = WALManager(backend=mock_backend, wal_path=Path("./dummy.json"), use_lock=False)
        wm.set_checkpoint("pipe_a", {"x": 1})
        mock_backend.write.assert_called()

    def test_wal_manager_without_path_or_backend_raises(self):
        from etl.indexer.wal_manager import WALManager

        with pytest.raises(ValueError, match="Either wal_path or backend must be provided"):
            WALManager()

    def test_wal_manager_get_checkpoint_with_backend(self):
        from unittest.mock import MagicMock

        from etl.indexer.wal_manager import WALManager

        mock_backend = MagicMock()
        mock_backend.read.return_value = {"pipe_a": {"count": 42}}
        wm = WALManager(backend=mock_backend, wal_path=Path("./dummy.json"), use_lock=False)
        assert wm.get_checkpoint("pipe_a", "count") == 42
        mock_backend.read.assert_called()

    def test_wal_manager_graceful_degradation(self):
        from unittest.mock import MagicMock

        from etl.indexer.wal_manager import WALManager

        mock_backend = MagicMock()
        mock_backend.read.side_effect = RuntimeError("backend unavailable")
        wm = WALManager(backend=mock_backend, wal_path=Path("./dummy.json"), use_lock=False)
        result = wm.get_checkpoint("pipe_a")
        assert result == {}
