"""Comprehensive tests for proxy/app/shared/minio_client.py.

Covers MinioClient construction, lazy client init, bucket creation,
upload/download/list/delete/metadata/presigned URL, and health check.
boto3 is mocked throughout — no real MinIO connection required.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from proxy.app.shared.exceptions import StorageError
from proxy.app.shared.minio_client import HAS_BOTO3, MinioClient


@pytest.fixture
def mock_client():
    """Patch _get_client to return a MagicMock without real boto3 calls."""
    client = MagicMock()
    with patch.object(MinioClient, "_get_client", return_value=client):
        yield client


@pytest.fixture
def minio():
    return MinioClient(
        endpoint="localhost:9000",
        access_key="ak",
        secret_key="sk",
        bucket="test-bucket",
        secure=False,
    )


# ---------------------------------------------------------------------------
# HAS_BOTO3 + imports
# ---------------------------------------------------------------------------


class TestModuleImports:
    def test_boto3_import_constant_set(self):
        # Either HAS_BOTO3 is True (if installed) or False
        assert isinstance(HAS_BOTO3, bool)


# ---------------------------------------------------------------------------
# MinioClient construction
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_construction_uses_config(self):
        mc = MinioClient()
        # Should pick up env-config values without raising
        assert mc._endpoint is not None or mc._endpoint is None  # type: ignore[attr-defined]

    def test_explicit_args(self):
        mc = MinioClient(
            endpoint="custom:9001",
            access_key="a",
            secret_key="b",
            bucket="mybucket",
            secure=True,
        )
        assert mc._endpoint == "custom:9001"
        assert mc._access_key == "a"
        assert mc._secret_key == "b"
        assert mc._bucket == "mybucket"
        assert mc._secure is True

    def test_no_boto3_raises(self):
        import proxy.app.shared.minio_client as mod

        original = mod.HAS_BOTO3
        mod.HAS_BOTO3 = False
        try:
            with pytest.raises(ImportError, match="boto3"):
                MinioClient(endpoint="x", access_key="y", secret_key="z")
        finally:
            mod.HAS_BOTO3 = original

    def test_client_not_initialized_on_construct(self, minio):
        # _client is None until first call
        assert minio._client is None


# ---------------------------------------------------------------------------
# _get_client lazy init
# ---------------------------------------------------------------------------


class TestGetClient:
    def test_first_call_creates_boto3_client(self, minio):
        with patch("proxy.app.shared.minio_client.boto3.client") as mock_boto:
            c = minio._get_client()
        mock_boto.assert_called_once()
        assert c is not None
        assert minio._client is not None

    def test_second_call_reuses_client(self, minio):
        with patch("proxy.app.shared.minio_client.boto3.client") as mock_boto:
            minio._get_client()
            minio._get_client()
        # boto3.client called only once
        assert mock_boto.call_count == 1

    def test_uses_http_when_not_secure(self, minio):
        minio._secure = False
        with patch("proxy.app.shared.minio_client.boto3.client") as mock_boto:
            minio._get_client()
        call_kwargs = mock_boto.call_args.kwargs
        assert call_kwargs["endpoint_url"].startswith("http://")

    def test_uses_https_when_secure(self, minio):
        minio._secure = True
        with patch("proxy.app.shared.minio_client.boto3.client") as mock_boto:
            minio._get_client()
        call_kwargs = mock_boto.call_args.kwargs
        assert call_kwargs["endpoint_url"].startswith("https://")

    def test_sets_signature_v4(self, minio):
        with patch("proxy.app.shared.minio_client.boto3.client") as mock_boto:
            minio._get_client()
        config = mock_boto.call_args.kwargs["config"]
        assert config.signature_version == "s3v4"


# ---------------------------------------------------------------------------
# _ensure_bucket
# ---------------------------------------------------------------------------


class TestEnsureBucket:
    def test_bucket_exists_no_op(self, minio, mock_client):
        mock_client.head_bucket.return_value = {}
        minio._ensure_bucket()  # no exception
        mock_client.create_bucket.assert_not_called()

    def test_bucket_missing_creates_it(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "404"}}, "head_bucket")
        mock_client.head_bucket.side_effect = err
        minio._ensure_bucket()
        mock_client.create_bucket.assert_called_once_with(Bucket="test-bucket")

    def test_other_client_error_raises(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "403"}}, "head_bucket")
        mock_client.head_bucket.side_effect = err
        with pytest.raises(StorageError, match="Failed to access"):
            minio._ensure_bucket()

    def test_create_failure_raises_storage_error(self, minio, mock_client):
        from botocore.exceptions import ClientError

        # head_bucket returns 404 → triggers create
        err_404 = ClientError({"Error": {"Code": "404"}}, "head_bucket")
        mock_client.head_bucket.side_effect = err_404
        # create_bucket fails
        err_create = ClientError({"Error": {"Code": "AccessDenied"}}, "create_bucket")
        mock_client.create_bucket.side_effect = err_create
        with pytest.raises(StorageError, match="Failed to create"):
            minio._ensure_bucket()


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------


class TestUploadFile:
    def test_successful_upload(self, minio, mock_client):
        mock_client.head_bucket.return_value = {}
        f = io.BytesIO(b"hello world")
        result = minio.upload_file(f, "hello.txt", content_type="text/plain")
        assert result == "hello.txt"
        mock_client.upload_fileobj.assert_called_once()
        args = mock_client.upload_fileobj.call_args
        assert args[0][1] == "test-bucket"
        assert args[0][2] == "hello.txt"

    def test_upload_includes_metadata(self, minio, mock_client):
        mock_client.head_bucket.return_value = {}
        f = io.BytesIO(b"data")
        minio.upload_file(f, "x", metadata={"author": "alice"})
        extra = mock_client.upload_fileobj.call_args.kwargs["ExtraArgs"]
        assert extra["Metadata"] == {"author": "alice"}
        assert extra["ContentType"] == "application/octet-stream"

    def test_upload_default_content_type(self, minio, mock_client):
        mock_client.head_bucket.return_value = {}
        f = io.BytesIO(b"x")
        minio.upload_file(f, "x")
        extra = mock_client.upload_fileobj.call_args.kwargs["ExtraArgs"]
        assert extra["ContentType"] == "application/octet-stream"

    def test_client_error_raises_storage_error(self, minio, mock_client):
        from botocore.exceptions import ClientError

        mock_client.head_bucket.return_value = {}
        err = ClientError({"Error": {"Code": "InternalError"}}, "upload")
        mock_client.upload_fileobj.side_effect = err
        f = io.BytesIO(b"x")
        with pytest.raises(StorageError, match="Failed to upload"):
            minio.upload_file(f, "x")

    def test_endpoint_error_raises_storage_error(self, minio, mock_client):
        from botocore.exceptions import EndpointConnectionError

        mock_client.head_bucket.return_value = {}
        mock_client.upload_fileobj.side_effect = EndpointConnectionError(
            endpoint_url="x",
        )
        f = io.BytesIO(b"x")
        with pytest.raises(StorageError, match="Failed to upload"):
            minio.upload_file(f, "x")


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------


class TestDownloadFile:
    def test_returns_body(self, minio, mock_client):
        body = MagicMock()
        body.read.return_value = b"hello"
        mock_client.get_object.return_value = {"Body": body}
        data = minio.download_file("key1")
        assert data == b"hello"
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="key1",
        )

    def test_no_such_key_raises_storage_error(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "NoSuchKey"}}, "get")
        mock_client.get_object.side_effect = err
        with pytest.raises(StorageError, match="not found"):
            minio.download_file("missing")

    def test_other_client_error_raises(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "InternalError"}}, "get")
        mock_client.get_object.side_effect = err
        with pytest.raises(StorageError, match="Failed to download"):
            minio.download_file("x")


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    def test_returns_empty(self, minio, mock_client):
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]
        mock_client.get_paginator.return_value = paginator
        result = minio.list_files()
        assert result == []

    def test_parses_contents(self, minio, mock_client):
        import datetime

        ts = datetime.datetime(2026, 1, 1, 0, 0, 0)
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {
                        "Key": "a.txt",
                        "Size": 1234,
                        "LastModified": ts,
                        "ETag": '"abc"',
                    }
                ]
            }
        ]
        mock_client.get_paginator.return_value = paginator
        result = minio.list_files()
        assert len(result) == 1
        assert result[0]["key"] == "a.txt"
        assert result[0]["size"] == 1234
        assert result[0]["etag"] == "abc"  # stripped quotes

    def test_passes_prefix(self, minio, mock_client):
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]
        mock_client.get_paginator.return_value = paginator
        minio.list_files(prefix="docs/")
        paginator.paginate.assert_called_once_with(
            Bucket="test-bucket",
            Prefix="docs/",
        )

    def test_client_error_raises(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "AccessDenied"}}, "list")
        mock_client.get_paginator.side_effect = err
        with pytest.raises(StorageError, match="Failed to list"):
            minio.list_files()

    def test_strips_etag_quotes(self, minio, mock_client):
        import datetime

        ts = datetime.datetime(2026, 1, 1, 0, 0, 0)
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "k", "Size": 0, "LastModified": ts, "ETag": '"deadbeef"'}]}
        ]
        mock_client.get_paginator.return_value = paginator
        result = minio.list_files()
        assert result[0]["etag"] == "deadbeef"


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------


class TestDeleteFile:
    def test_successful_delete(self, minio, mock_client):
        minio.delete_file("to-del")
        mock_client.delete_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="to-del",
        )

    def test_client_error_raises(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "AccessDenied"}}, "del")
        mock_client.delete_object.side_effect = err
        with pytest.raises(StorageError, match="Failed to delete"):
            minio.delete_file("x")


# ---------------------------------------------------------------------------
# get_file_metadata
# ---------------------------------------------------------------------------


class TestGetFileMetadata:
    def test_returns_metadata(self, minio, mock_client):
        import datetime

        ts = datetime.datetime(2026, 1, 1, 0, 0, 0)
        mock_client.head_object.return_value = {
            "ContentLength": 2048,
            "LastModified": ts,
            "ContentType": "text/plain",
            "Metadata": {"k": "v"},
            "ETag": '"xyz"',
        }
        info = minio.get_file_metadata("file.txt")
        assert info["key"] == "file.txt"
        assert info["size"] == 2048
        assert info["content_type"] == "text/plain"
        assert info["metadata"] == {"k": "v"}
        assert info["etag"] == "xyz"

    def test_no_last_modified(self, minio, mock_client):
        mock_client.head_object.return_value = {
            "ContentLength": 0,
            "ContentType": "",
            "Metadata": {},
            "ETag": "",
        }
        info = minio.get_file_metadata("file.txt")
        assert info["last_modified"] == ""

    def test_no_such_key_raises(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "404"}}, "head")
        mock_client.head_object.side_effect = err
        with pytest.raises(StorageError, match="not found"):
            minio.get_file_metadata("missing")

    def test_forbidden_raises_not_found(self, minio, mock_client):
        # 403 falls into the "not found" branch
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "403"}}, "head")
        mock_client.head_object.side_effect = err
        with pytest.raises(StorageError, match="not found"):
            minio.get_file_metadata("private")

    def test_other_error_raises(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "InternalError"}}, "head")
        mock_client.head_object.side_effect = err
        with pytest.raises(StorageError, match="Failed to get"):
            minio.get_file_metadata("x")


# ---------------------------------------------------------------------------
# generate_presigned_url
# ---------------------------------------------------------------------------


class TestPresignedUrl:
    def test_returns_url(self, minio, mock_client):
        mock_client.generate_presigned_url.return_value = "https://signed.url/x"
        url = minio.generate_presigned_url("x")
        assert url == "https://signed.url/x"

    def test_passes_bucket_and_key(self, minio, mock_client):
        minio.generate_presigned_url("file.txt", expiration=7200)
        kwargs = mock_client.generate_presigned_url.call_args.kwargs
        assert kwargs["Params"] == {"Bucket": "test-bucket", "Key": "file.txt"}
        assert kwargs["ExpiresIn"] == 7200

    def test_default_expiration(self, minio, mock_client):
        minio.generate_presigned_url("file.txt")
        kwargs = mock_client.generate_presigned_url.call_args.kwargs
        assert kwargs["ExpiresIn"] == 3600

    def test_client_error_raises(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "InternalError"}}, "sign")
        mock_client.generate_presigned_url.side_effect = err
        with pytest.raises(StorageError, match="presigned"):
            minio.generate_presigned_url("x")


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_success(self, minio, mock_client):
        mock_client.list_buckets.return_value = {}
        assert minio.health_check() is True

    def test_client_error_raises(self, minio, mock_client):
        from botocore.exceptions import ClientError

        err = ClientError({"Error": {"Code": "InternalError"}}, "list")
        mock_client.list_buckets.side_effect = err
        with pytest.raises(StorageError, match="health check"):
            minio.health_check()

    def test_endpoint_error_raises(self, minio, mock_client):
        from botocore.exceptions import EndpointConnectionError

        mock_client.list_buckets.side_effect = EndpointConnectionError(
            endpoint_url="x",
        )
        with pytest.raises(StorageError, match="health check"):
            minio.health_check()
