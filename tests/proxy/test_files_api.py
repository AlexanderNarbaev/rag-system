# tests/proxy/test_files_api.py
"""Tests for file upload/management API endpoints."""

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_context(username="testuser", roles=None):
    """Create a mock UserContext."""
    ctx = MagicMock()
    ctx.username = username
    ctx.roles = roles or ["user"]
    ctx.user_id = "user-123"
    return ctx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Return a TestClient with mocked auth and MinIO."""
    # Import modules first so patch can resolve them
    import proxy.app.api.files as _files_module  # noqa: F401

    with (
        patch("proxy.app.api.files.require_role") as mock_require,
        patch("proxy.app.api.files.MinioClient") as mock_minio_cls,
    ):
        # Mock auth to always return a user context
        user_ctx = _make_user_context()
        mock_require.return_value = lambda: user_ctx

        # Mock MinIO client instance
        mock_minio = MagicMock()
        mock_minio_cls.return_value = mock_minio

        from proxy.app.main import app

        with TestClient(app) as c:
            yield c, mock_minio


# ---------------------------------------------------------------------------
# Tests — POST /v1/files
# ---------------------------------------------------------------------------


class TestUploadFile:
    def test_upload_success(self, client):
        """Successful file upload returns FileUploadResponse."""
        c, mock_minio = client
        mock_minio.upload_file.return_value = "uploads/abc123/test.txt"

        response = c.post(
            "/v1/files",
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test.txt"
        assert data["size"] == 5
        assert data["content_type"] == "text/plain"
        assert "uploads/" in data["id"]

    def test_upload_rejects_disallowed_content_type(self, client):
        """Disallowed MIME types return 400."""
        c, mock_minio = client
        response = c.post(
            "/v1/files",
            files={"file": ("test.exe", io.BytesIO(b"MZ"), "application/x-msdownload")},
        )
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_upload_rejects_oversized_file(self, client):
        """Files exceeding max size return 413."""
        c, mock_minio = client
        large_content = b"x" * (101 * 1024 * 1024)  # 101 MB
        response = c.post(
            "/v1/files",
            files={"file": ("big.txt", io.BytesIO(large_content), "text/plain")},
        )
        assert response.status_code == 413

    def test_upload_handles_storage_error(self, client):
        """StorageError returns 500."""
        c, mock_minio = client
        from proxy.app.shared.exceptions import StorageError

        mock_minio.upload_file.side_effect = StorageError("connection failed")
        response = c.post(
            "/v1/files",
            files={"file": ("test.txt", io.BytesIO(b"data"), "text/plain")},
        )
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# Tests — GET /v1/files
# ---------------------------------------------------------------------------


class TestListFiles:
    def test_list_files_empty(self, client):
        """Empty bucket returns empty list."""
        c, mock_minio = client
        mock_minio.list_files.return_value = []

        response = c.get("/v1/files")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["files"] == []

    def test_list_files_with_results(self, client):
        """Returns file metadata list."""
        c, mock_minio = client
        mock_minio.list_files.return_value = [
            {
                "key": "uploads/abc/test.txt",
                "size": 100,
                "last_modified": "2025-01-01T00:00:00",
                "etag": "abc123",
            }
        ]

        response = c.get("/v1/files")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["files"][0]["id"] == "uploads/abc/test.txt"

    def test_list_files_with_prefix(self, client):
        """Prefix parameter is passed to MinIO client."""
        c, mock_minio = client
        mock_minio.list_files.return_value = []

        response = c.get("/v1/files?prefix=uploads/")
        assert response.status_code == 200
        mock_minio.list_files.assert_called_with(prefix="uploads/")


# ---------------------------------------------------------------------------
# Tests — GET /v1/files/{file_id}
# ---------------------------------------------------------------------------


class TestGetFileMetadata:
    def test_metadata_success(self, client):
        """Returns file metadata."""
        c, mock_minio = client
        mock_minio.get_file_metadata.return_value = {
            "key": "uploads/abc/test.txt",
            "size": 42,
            "last_modified": "2025-01-01T00:00:00",
            "content_type": "text/plain",
            "metadata": {"original_filename": "test.txt"},
            "etag": "abc",
        }

        response = c.get("/v1/files/uploads/abc/test.txt")
        assert response.status_code == 200
        data = response.json()
        assert data["size"] == 42
        assert data["content_type"] == "text/plain"

    def test_metadata_not_found(self, client):
        """Missing file returns 404."""
        c, mock_minio = client
        from proxy.app.shared.exceptions import StorageError

        mock_minio.get_file_metadata.side_effect = StorageError("File not found: 'x'")

        response = c.get("/v1/files/nonexistent.txt")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests — DELETE /v1/files/{file_id}
# ---------------------------------------------------------------------------


class TestDeleteFile:
    def test_delete_success(self, client):
        """Successful deletion returns confirmation."""
        c, mock_minio = client
        mock_minio.get_file_metadata.return_value = {"key": "test.txt"}
        mock_minio.delete_file.return_value = None

        response = c.delete("/v1/files/test.txt")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "deleted" in data["message"].lower()

    def test_delete_not_found(self, client):
        """Deleting nonexistent file returns 404."""
        c, mock_minio = client
        from proxy.app.shared.exceptions import StorageError

        mock_minio.get_file_metadata.side_effect = StorageError("File not found")

        response = c.delete("/v1/files/missing.txt")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests — GET /v1/files/{file_id}/download
# ---------------------------------------------------------------------------


class TestDownloadFile:
    def test_download_success(self, client):
        """Successful download returns file content."""
        c, mock_minio = client
        mock_minio.get_file_metadata.return_value = {
            "key": "test.txt",
            "content_type": "text/plain",
            "metadata": {"original_filename": "test.txt"},
        }
        mock_minio.download_file.return_value = b"file content"

        response = c.get("/v1/files/test.txt/download")
        assert response.status_code == 200
        assert response.content == b"file content"
        assert "attachment" in response.headers.get("content-disposition", "")

    def test_download_not_found(self, client):
        """Missing file returns 404."""
        c, mock_minio = client
        from proxy.app.shared.exceptions import StorageError

        mock_minio.get_file_metadata.side_effect = StorageError("File not found")

        response = c.get("/v1/files/missing.txt/download")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests — GET /v1/files/{file_id}/presigned
# ---------------------------------------------------------------------------


class TestPresignedUrl:
    def test_presigned_url_success(self, client):
        """Returns presigned URL."""
        c, mock_minio = client
        mock_minio.get_file_metadata.return_value = {"key": "test.txt"}
        mock_minio.generate_presigned_url.return_value = (
            "http://localhost:9000/bucket/test.txt?signed=abc"
        )

        response = c.get("/v1/files/test.txt/presigned")
        assert response.status_code == 200
        data = response.json()
        assert "url" in data
        assert data["expires_in"] == 3600

    def test_presigned_url_custom_expiration(self, client):
        """Custom expiration is passed through."""
        c, mock_minio = client
        mock_minio.get_file_metadata.return_value = {"key": "test.txt"}
        mock_minio.generate_presigned_url.return_value = "http://example.com/url"

        response = c.get("/v1/files/test.txt/presigned?expiration=1800")
        assert response.status_code == 200
        assert response.json()["expires_in"] == 1800

    def test_presigned_url_invalid_expiration(self, client):
        """Expiration out of range returns 400."""
        c, mock_minio = client
        mock_minio.get_file_metadata.return_value = {"key": "test.txt"}

        response = c.get("/v1/files/test.txt/presigned?expiration=10")
        assert response.status_code == 400
