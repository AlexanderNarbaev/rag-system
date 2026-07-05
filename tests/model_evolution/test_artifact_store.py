"""Tests for proxy/app/model_evolution/artifact_store.py — ArtifactStore MinIO/S3 client."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.model_evolution.artifact_store import ArtifactRef, ArtifactStore


def _mock_boto3_client() -> tuple[MagicMock, MagicMock]:
    """Create a mock boto3 module with a mock S3 client."""
    mock_s3 = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3
    return mock_boto3, mock_s3


class TestArtifactRef:
    def test_dataclass_fields(self):
        ref = ArtifactRef(bucket="test-bucket", key="models/llm/v1/model.bin")
        assert ref.bucket == "test-bucket"
        assert ref.key == "models/llm/v1/model.bin"
        assert ref.version_id == ""
        assert ref.size == 0

    def test_uri_property(self):
        ref = ArtifactRef(bucket="my-bucket", key="models/llm/v2/adapter.bin")
        assert ref.uri == "s3://my-bucket/models/llm/v2/adapter.bin"

    def test_with_version_id_and_size(self):
        ref = ArtifactRef(
            bucket="bucket",
            key="path/file.bin",
            version_id="v123",
            size=1024
        )
        assert ref.version_id == "v123"
        assert ref.size == 1024


class TestArtifactStoreLocalMode:
    def test_local_mode_default(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        assert store.local_mode is True
        assert store._local_path == tmp_path

    def test_upload_model_creates_files(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "model.bin"
        src_file.write_text("model data")

        ref = store.upload_model("llm", "v1.0", str(src_file))
        assert ref.bucket == "local"
        assert "models/llm/v1.0/model.bin" in ref.key
        assert (tmp_path / "models" / "llm" / "v1.0" / "model.bin").exists()

    def test_upload_model_directory(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        src_dir = tmp_path / "adapter_dir"
        src_dir.mkdir()
        (src_dir / "adapter_config.json").write_text("{}")
        (src_dir / "adapter_model.bin").write_text("weights")

        ref = store.upload_model("slm", "v2", str(src_dir))
        assert ref.bucket == "local"
        assert (tmp_path / "models" / "slm" / "v2" / "adapter_config.json").exists()
        assert (tmp_path / "models" / "slm" / "v2" / "adapter_model.bin").exists()

    def test_download_model(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        model_dir = tmp_path / "models" / "slm" / "v1.0"
        model_dir.mkdir(parents=True)
        (model_dir / "adapter.bin").write_text("local weights")

        dst = tmp_path / "downloaded"
        dst.mkdir()
        result = store.download_model("slm", "v1.0", str(dst))
        assert os.path.isdir(result)
        assert (dst / "adapter.bin").exists()
        assert (dst / "adapter.bin").read_text() == "local weights"

    def test_download_model_missing_version(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            store.download_model("nonexistent", "v99", str(tmp_path))

    def test_download_model_specific_file(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        model_dir = tmp_path / "models" / "llm" / "v3"
        model_dir.mkdir(parents=True)
        (model_dir / "config.json").write_text("cfg")
        (model_dir / "weights.bin").write_text("w")

        dst = tmp_path / "single"
        dst.mkdir()
        result = store.download_model("llm", "v3", str(dst), filename="weights.bin")
        assert os.path.isfile(result)
        assert result.endswith("weights.bin")
        assert Path(result).read_text() == "w"
        assert not (dst / "config.json").exists()

    def test_list_versions(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        for ver in ["v1.0", "v1.1", "v2.0"]:
            (tmp_path / "models" / "llm" / ver).mkdir(parents=True)

        versions = store.list_versions("llm")
        assert len(versions) == 3
        assert {v.key for v in versions} == {
            "models/llm/v1.0", "models/llm/v1.1", "models/llm/v2.0"
        }

    def test_list_versions_empty(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        (tmp_path / "models" / "llm").mkdir(parents=True)
        versions = store.list_versions("llm")
        assert versions == []

    def test_list_versions_missing_model(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        versions = store.list_versions("no-such-model")
        assert versions == []

    def test_delete_version(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        model_dir = tmp_path / "models" / "llm" / "v1.0"
        model_dir.mkdir(parents=True)
        (model_dir / "model.bin").write_text("data")

        store.delete_version("llm", "v1.0")
        assert not model_dir.exists()

    def test_delete_version_nonexistent(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        store.delete_version("llm", "nonexistent")

    def test_auto_local_mode_when_no_minio_config(self, tmp_path):
        store = ArtifactStore()
        assert store.local_mode is True


class TestArtifactStoreRemoteMode:
    def _setup_mock_boto3(self, monkeypatch) -> tuple[MagicMock, MagicMock]:
        """Setup mocked boto3 in sys.modules and return (mock_boto3, mock_s3)."""
        monkeypatch.setenv("MINIO_ENDPOINT", "s3.example.com:9000")
        monkeypatch.setenv("MINIO_ACCESS_KEY", "ak")
        monkeypatch.setenv("MINIO_SECRET_KEY", "sk")
        mock_boto3, mock_s3 = _mock_boto3_client()
        monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
        return mock_boto3, mock_s3

    def test_client_lazy_init(self, monkeypatch):
        monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
        monkeypatch.setenv("MINIO_ACCESS_KEY", "admin")
        monkeypatch.setenv("MINIO_SECRET_KEY", "password")

        mock_boto3, mock_s3 = _mock_boto3_client()
        monkeypatch.setitem(sys.modules, "boto3", mock_boto3)

        store = ArtifactStore()
        assert store._client_cache is None
        client = store._get_client()
        assert client is mock_s3

    def test_upload_model_to_s3(self, monkeypatch, tmp_path):
        _, mock_s3 = self._setup_mock_boto3(monkeypatch)
        monkeypatch.setenv("MINIO_BUCKET", "my-bucket")

        store = ArtifactStore()
        src_file = tmp_path / "model.bin"
        src_file.write_text("data")

        ref = store.upload_model("llm", "v1.0", str(src_file))
        mock_s3.upload_file.assert_called_once()
        assert ref.bucket == "my-bucket"
        assert ref.key == "models/llm/v1.0/model.bin"

    def test_download_model_from_s3(self, monkeypatch, tmp_path):
        _, mock_s3 = self._setup_mock_boto3(monkeypatch)
        monkeypatch.setenv("MINIO_BUCKET", "my-bucket")

        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "models/llm/v1.0/adapter.bin", "Size": 100},
                {"Key": "models/llm/v1.0/config.json", "Size": 50},
            ]
        }
        store = ArtifactStore()

        dst = str(tmp_path / "output")
        result = store.download_model("llm", "v1.0", dst)
        assert mock_s3.download_file.call_count == 2
        assert os.path.isdir(result)

    def test_download_model_missing_from_s3(self, monkeypatch, tmp_path):
        _, mock_s3 = self._setup_mock_boto3(monkeypatch)
        monkeypatch.setenv("MINIO_BUCKET", "my-bucket")

        mock_s3.list_objects_v2.return_value = {}
        store = ArtifactStore()

        with pytest.raises(FileNotFoundError):
            store.download_model("llm", "v99", str(tmp_path))

    def test_list_versions_from_s3(self, monkeypatch):
        _, mock_s3 = self._setup_mock_boto3(monkeypatch)
        monkeypatch.setenv("MINIO_BUCKET", "my-bucket")

        mock_s3.list_objects_v2.return_value = {
            "CommonPrefixes": [
                {"Prefix": "models/llm/v1.0/"},
                {"Prefix": "models/llm/v2.0/"},
            ]
        }
        store = ArtifactStore()

        versions = store.list_versions("llm")
        assert len(versions) == 2
        assert versions[0].key == "models/llm/v1.0"
        assert versions[1].key == "models/llm/v2.0"

    def test_delete_version_from_s3(self, monkeypatch, tmp_path):
        _, mock_s3 = self._setup_mock_boto3(monkeypatch)
        monkeypatch.setenv("MINIO_BUCKET", "my-bucket")

        mock_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "models/llm/v1.0/model.bin"},
            ]
        }
        store = ArtifactStore()

        store.delete_version("llm", "v1.0")
        mock_s3.delete_objects.assert_called_once()

    def test_ensure_bucket_remote(self, monkeypatch):
        _, mock_s3 = self._setup_mock_boto3(monkeypatch)
        monkeypatch.setenv("MINIO_BUCKET", "my-bucket")

        store = ArtifactStore()
        store.ensure_bucket()
        mock_s3.head_bucket.assert_called_once_with(Bucket="my-bucket")

    def test_ensure_bucket_creates_if_missing(self, monkeypatch):
        _, mock_s3 = self._setup_mock_boto3(monkeypatch)
        monkeypatch.setenv("MINIO_BUCKET", "my-bucket")

        mock_s3.head_bucket.side_effect = Exception("NoSuchBucket")
        store = ArtifactStore()
        store.ensure_bucket()
        mock_s3.create_bucket.assert_called_once_with(Bucket="my-bucket")

    def test_ensure_bucket_noop_local_mode(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        store.ensure_bucket()

    def test_import_error_graceful(self, monkeypatch):
        monkeypatch.setenv("MINIO_ENDPOINT", "s3.example.com:9000")
        monkeypatch.setenv("MINIO_ACCESS_KEY", "ak")
        monkeypatch.setenv("MINIO_SECRET_KEY", "sk")
        monkeypatch.setenv("MINIO_BUCKET", "my-bucket")

        with patch.dict("sys.modules", {"boto3": None}), pytest.raises(ImportError, match="boto3"):
            store = ArtifactStore()
            store._get_client()

    def test_invalid_model_name_raises(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        with pytest.raises(ValueError, match="model_name"):
            store.upload_model("", "v1", str(tmp_path))

    def test_invalid_version_raises(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        with pytest.raises(ValueError, match="version"):
            store.upload_model("llm", "", str(tmp_path))

    def test_nonexistent_source_file(self, tmp_path):
        store = ArtifactStore(local_mode=True, local_storage_path=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            store.upload_model("llm", "v1", str(tmp_path / "no-file.bin"))
