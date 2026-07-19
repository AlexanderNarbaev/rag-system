# tests/proxy/test_minio_client.py
"""Tests for MinIO client (S3-compatible object storage)."""

import io
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.shared.exceptions import StorageError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_boto3_client():
    """Return a mock boto3 S3 client."""
    client = MagicMock()
    return client


@pytest.fixture
def minio_client(mock_boto3_client):
    """Return a MinioClient with mocked boto3."""
    # Import the module first so patch can resolve it
    import proxy.app.shared.minio_client as _mc_module  # noqa: F401

    with patch("proxy.app.shared.minio_client.boto3") as mock_boto:
        mock_boto.client.return_value = mock_boto3_client
        from proxy.app.shared.minio_client import MinioClient

        c = MinioClient(
            endpoint="localhost:9000",
            access_key="testkey",
            secret_key="testsecret",
            bucket="test-bucket",
            secure=False,
        )
        c._client = mock_boto3_client
        yield c


# ---------------------------------------------------------------------------
# Tests — upload_file
# ---------------------------------------------------------------------------


class TestUploadFile:
    def test_upload_success(self, minio_client, mock_boto3_client):
        """Successful upload returns the object name."""
        mock_boto3_client.head_bucket.return_value = {}
        data = io.BytesIO(b"hello world")
        result = minio_client.upload_file(data, "test.txt", content_type="text/plain")
        assert result == "test.txt"
        mock_boto3_client.upload_fileobj.assert_called_once()

    def test_upload_with_metadata(self, minio_client, mock_boto3_client):
        """Metadata is passed as ExtraArgs."""
        mock_boto3_client.head_bucket.return_value = {}
        data = io.BytesIO(b"data")
        minio_client.upload_file(data, "doc.pdf", content_type="application/pdf", metadata={"author": "test"})
        call_args = mock_boto3_client.upload_fileobj.call_args
        assert call_args[1]["ExtraArgs"]["Metadata"] == {"author": "test"}

    def test_upload_creates_bucket_if_missing(self, minio_client, mock_boto3_client):
        """Bucket is created if head_bucket raises 404."""
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "404", "Message": "Not Found"}}
        mock_boto3_client.head_bucket.side_effect = ClientError(error_response, "HeadBucket")
        mock_boto3_client.create_bucket.return_value = {}

        data = io.BytesIO(b"data")
        minio_client.upload_file(data, "file.txt")
        mock_boto3_client.create_bucket.assert_called_once()

    def test_upload_failure_raises_storage_error(self, minio_client, mock_boto3_client):
        """Upload failure raises StorageError."""
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "500", "Message": "Internal Error"}}
        mock_boto3_client.head_bucket.return_value = {}
        mock_boto3_client.upload_fileobj.side_effect = ClientError(error_response, "UploadPart")
        with pytest.raises(StorageError, match="Failed to upload"):
            minio_client.upload_file(io.BytesIO(b"x"), "bad.txt")


# ---------------------------------------------------------------------------
# Tests — download_file
# ---------------------------------------------------------------------------


class TestDownloadFile:
    def test_download_success(self, minio_client, mock_boto3_client):
        """Successful download returns file bytes."""
        body_mock = MagicMock()
        body_mock.read.return_value = b"file content"
        mock_boto3_client.get_object.return_value = {"Body": body_mock}

        result = minio_client.download_file("test.txt")
        assert result == b"file content"

    def test_download_not_found(self, minio_client, mock_boto3_client):
        """Missing file raises StorageError."""
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}
        mock_boto3_client.get_object.side_effect = ClientError(error_response, "GetObject")
        with pytest.raises(StorageError, match="not found"):
            minio_client.download_file("missing.txt")


# ---------------------------------------------------------------------------
# Tests — list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    def test_list_files_success(self, minio_client, mock_boto3_client):
        """Returns list of file dicts."""
        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [
            {
                "Contents": [
                    {
                        "Key": "file1.txt",
                        "Size": 100,
                        "LastModified": datetime(2025, 1, 1, tzinfo=UTC),
                        "ETag": '"abc123"',
                    },
                ],
            },
        ]
        mock_boto3_client.get_paginator.return_value = paginator_mock

        result = minio_client.list_files()
        assert len(result) == 1
        assert result[0]["key"] == "file1.txt"
        assert result[0]["size"] == 100

    def test_list_files_empty(self, minio_client, mock_boto3_client):
        """Empty bucket returns empty list."""
        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [{}]
        mock_boto3_client.get_paginator.return_value = paginator_mock

        result = minio_client.list_files()
        assert result == []

    def test_list_files_with_prefix(self, minio_client, mock_boto3_client):
        """Prefix is passed to paginator."""
        paginator_mock = MagicMock()
        paginator_mock.paginate.return_value = [{}]
        mock_boto3_client.get_paginator.return_value = paginator_mock

        minio_client.list_files(prefix="uploads/")
        call_kwargs = mock_boto3_client.get_paginator.return_value.paginate.call_args[1]
        assert call_kwargs["Prefix"] == "uploads/"


# ---------------------------------------------------------------------------
# Tests — delete_file
# ---------------------------------------------------------------------------


class TestDeleteFile:
    def test_delete_success(self, minio_client, mock_boto3_client):
        """Successful delete calls delete_object."""
        minio_client.delete_file("test.txt")
        mock_boto3_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="test.txt")

    def test_delete_failure(self, minio_client, mock_boto3_client):
        """Delete failure raises StorageError."""
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "500", "Message": "Fail"}}
        mock_boto3_client.delete_object.side_effect = ClientError(error_response, "DeleteObject")
        with pytest.raises(StorageError, match="Failed to delete"):
            minio_client.delete_file("bad.txt")


# ---------------------------------------------------------------------------
# Tests — get_file_metadata
# ---------------------------------------------------------------------------


class TestGetFileMetadata:
    def test_metadata_success(self, minio_client, mock_boto3_client):
        """Returns metadata dict."""
        mock_boto3_client.head_object.return_value = {
            "ContentLength": 42,
            "LastModified": datetime(2025, 1, 1, tzinfo=UTC),
            "ContentType": "text/plain",
            "Metadata": {"author": "test"},
            "ETag": '"etag123"',
        }
        result = minio_client.get_file_metadata("test.txt")
        assert result["size"] == 42
        assert result["content_type"] == "text/plain"
        assert result["metadata"]["author"] == "test"

    def test_metadata_not_found(self, minio_client, mock_boto3_client):
        """Missing file raises StorageError."""
        from botocore.exceptions import ClientError

        error_response = {"Error": {"Code": "404", "Message": "Not Found"}}
        mock_boto3_client.head_object.side_effect = ClientError(error_response, "HeadObject")
        with pytest.raises(StorageError, match="not found"):
            minio_client.get_file_metadata("missing.txt")


# ---------------------------------------------------------------------------
# Tests — generate_presigned_url
# ---------------------------------------------------------------------------


class TestPresignedUrl:
    def test_presigned_url_success(self, minio_client, mock_boto3_client):
        """Returns presigned URL string."""
        mock_boto3_client.generate_presigned_url.return_value = "http://localhost:9000/test-bucket/test.txt?signed=..."
        url = minio_client.generate_presigned_url("test.txt", expiration=1800)
        assert "localhost:9000" in url

    def test_presigned_url_default_expiration(self, minio_client, mock_boto3_client):
        """Default expiration is 3600 seconds."""
        mock_boto3_client.generate_presigned_url.return_value = "http://example.com/url"
        minio_client.generate_presigned_url("test.txt")
        call_kwargs = mock_boto3_client.generate_presigned_url.call_args[1]
        assert call_kwargs["ExpiresIn"] == 3600


# ---------------------------------------------------------------------------
# Tests — health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_check_success(self, minio_client, mock_boto3_client):
        """Healthy MinIO returns True."""
        mock_boto3_client.list_buckets.return_value = {"Buckets": []}
        assert minio_client.health_check() is True

    def test_health_check_failure(self, minio_client, mock_boto3_client):
        """Unreachable MinIO raises StorageError."""
        from botocore.exceptions import EndpointConnectionError

        mock_boto3_client.list_buckets.side_effect = EndpointConnectionError(
            endpoint_url="http://localhost:9000",
            error_msg="Connection refused",
        )
        with pytest.raises(StorageError, match="health check failed"):
            minio_client.health_check()
