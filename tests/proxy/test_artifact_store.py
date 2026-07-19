"""Tests for proxy/app/model_evolution/artifact_store.py — local-mode ArtifactStore."""

import os
from unittest.mock import MagicMock

import pytest

from proxy.app.model_evolution.artifact_store import ArtifactRef, ArtifactStore


class TestArtifactRef:
    """Tests for ArtifactRef dataclass."""

    def test_defaults(self):
        ref = ArtifactRef(bucket="b", key="k")
        assert ref.version_id is None
        assert ref.size == 0
        assert ref.uri == ""

    def test_custom_values(self):
        ref = ArtifactRef(bucket="b", key="k", version_id="v1", size=1024, uri="s3://b/k")
        assert ref.version_id == "v1"
        assert ref.size == 1024
        assert ref.uri == "s3://b/k"


class TestArtifactStoreLocalMode:
    """Tests for ArtifactStore in local filesystem mode."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a local-mode ArtifactStore using tmp dir."""
        store = ArtifactStore(bucket="test-bucket")
        store._local_path = tmp_path / "artifacts" / "test-bucket"
        store._local_path.mkdir(parents=True, exist_ok=True)
        return store

    def test_init_local_mode_no_endpoint(self):
        """Store initializes in local mode when no endpoint provided."""
        store = ArtifactStore(bucket="test-bucket")
        assert store._local_mode is True
        assert store._client is None

    def test_init_local_mode_missing_credentials(self):
        """Store initializes in local mode when credentials are incomplete."""
        store = ArtifactStore(endpoint="localhost:9000", bucket="test-bucket")
        assert store._local_mode is True

    def test_upload_model_local_file(self, store, tmp_path):
        """Upload a single file to local storage."""
        src = tmp_path / "model.bin"
        src.write_bytes(b"fake model weights")

        ref = store.upload_model("my-model", "1.0", str(src))
        assert ref.bucket == "test-bucket"
        assert "my-model" in ref.key
        assert "1.0" in ref.key
        assert ref.uri  # local URI

    def test_upload_model_local_directory(self, store, tmp_path):
        """Upload a directory to local storage."""
        src_dir = tmp_path / "model_dir"
        src_dir.mkdir()
        (src_dir / "config.json").write_text("{}")
        (src_dir / "weights.bin").write_bytes(b"data")

        ref = store.upload_model("my-model", "2.0", str(src_dir))
        assert ref.bucket == "test-bucket"
        # Verify files were copied
        dest = store._local_path / "my-model" / "2.0"
        assert dest.exists()

    def test_download_model_local(self, store, tmp_path):
        """Download a model from local storage."""
        # First upload
        src_dir = tmp_path / "src_model"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("hello")
        store.upload_model("test-model", "1.0", str(src_dir))

        # Now download
        dest = tmp_path / "downloaded"
        result = store.download_model("test-model", "1.0", str(dest))
        assert os.path.isdir(result)

    def test_download_model_nonexistent(self, store, tmp_path):
        """Download a nonexistent model returns empty dir."""
        dest = tmp_path / "download"
        result = store.download_model("no-such-model", "1.0", str(dest))
        assert os.path.isdir(result)

    def test_list_versions_local(self, store, tmp_path):
        """List versions of a locally stored model."""
        src = tmp_path / "m" / "f.txt"
        src.parent.mkdir(parents=True)
        src.write_text("v")
        store.upload_model("my-model", "1.0", str(src))
        store.upload_model("my-model", "2.0", str(src))

        versions = store.list_versions("my-model")
        assert "1.0" in versions
        assert "2.0" in versions

    def test_list_versions_empty(self, store):
        """List versions of a model with no stored versions."""
        versions = store.list_versions("nonexistent")
        assert versions == []

    def test_delete_version_local(self, store, tmp_path):
        """Delete a specific version from local storage."""
        src = tmp_path / "f.txt"
        src.write_text("data")
        store.upload_model("my-model", "1.0", str(src))

        store.delete_version("my-model", "1.0")
        versions = store.list_versions("my-model")
        assert "1.0" not in versions

    def test_delete_version_nonexistent(self, store):
        """Deleting a nonexistent version does not raise."""
        store.delete_version("no-model", "99.0")  # Should not raise


class TestArtifactStoreS3Mode:
    """Tests for ArtifactStore with mocked S3 client."""

    def test_s3_upload_directory(self, tmp_path):
        """Upload a directory via S3 client."""
        mock_client = MagicMock()
        src_dir = tmp_path / "model"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("hello")

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False
        store.bucket = "my-bucket"

        ref = store.upload_model("model", "1.0", str(src_dir))
        assert ref.bucket == "my-bucket"
        mock_client.upload_file.assert_called()

    def test_s3_upload_file(self, tmp_path):
        """Upload a single file via S3 client."""
        mock_client = MagicMock()
        src = tmp_path / "model.bin"
        src.write_bytes(b"data")

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        store.upload_model("model", "1.0", str(src))
        mock_client.upload_file.assert_called_once()

    def test_s3_download_model(self, tmp_path):
        """Download model via S3 client."""
        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"Contents": [{"Key": "models/model/1.0/config.json"}]}]

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        store.download_model("model", "1.0", str(tmp_path))
        mock_client.download_file.assert_called()

    def test_s3_download_empty_contents(self, tmp_path):
        """Download model with no contents."""
        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"Contents": []}]

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        store.download_model("model", "1.0", str(tmp_path))
        mock_client.download_file.assert_not_called()

    def test_s3_list_versions(self):
        """List versions via S3 client."""
        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [
            {"CommonPrefixes": [{"Prefix": "models/model/1.0/"}, {"Prefix": "models/model/2.0/"}]},
        ]

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        versions = store.list_versions("model")
        assert "1.0" in versions
        assert "2.0" in versions

    def test_s3_list_versions_empty(self):
        """List versions with no CommonPrefixes."""
        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"CommonPrefixes": []}]

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        versions = store.list_versions("model")
        assert versions == []

    def test_s3_delete_version(self):
        """Delete version via S3 client."""
        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"Contents": [{"Key": "models/model/1.0/file.bin"}]}]

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        store.delete_version("model", "1.0")
        mock_client.delete_objects.assert_called_once()

    def test_s3_delete_version_empty(self):
        """Delete version with no objects doesn't call delete_objects."""
        mock_client = MagicMock()
        paginator = MagicMock()
        mock_client.get_paginator.return_value = paginator
        paginator.paginate.return_value = [{"Contents": []}]

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        store.delete_version("model", "1.0")
        mock_client.delete_objects.assert_not_called()

    def test_ensure_bucket_creates_if_missing(self):
        """ensure_bucket creates bucket when head_bucket fails."""
        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = Exception("Not Found")

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        store.ensure_bucket()
        mock_client.create_bucket.assert_called_once()

    def test_ensure_bucket_no_client(self):
        """ensure_bucket is a no-op when no S3 client."""
        store = ArtifactStore(bucket="test-bucket")
        store._client = None
        store.ensure_bucket()  # Should not raise

    def test_s3_uri_format(self, tmp_path):
        """S3 upload returns s3:// URI."""
        mock_client = MagicMock()
        src = tmp_path / "f.bin"
        src.write_bytes(b"data")

        store = ArtifactStore(bucket="my-bucket")
        store._client = mock_client
        store._local_mode = False

        ref = store.upload_model("model", "1.0", str(src))
        assert ref.uri.startswith("s3://")
