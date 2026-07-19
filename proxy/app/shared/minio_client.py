# proxy/app/shared/minio_client.py
"""MinIO client for S3-compatible object storage.

Provides file upload, download, listing, deletion, and presigned URL generation
for the RAG system's document storage needs.

Uses boto3 (S3-compatible API) for MinIO access.
"""

import logging
from typing import Any, BinaryIO

try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError, EndpointConnectionError

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

from proxy.app.shared.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)
from proxy.app.shared.exceptions import StorageError

logger = logging.getLogger("rag-proxy")


class MinioClient:
    """S3-compatible MinIO client for file storage operations.

    Wraps boto3 to provide a clean interface for uploading, downloading,
    listing, and deleting files in a MinIO bucket. Also supports presigned
    URL generation for secure temporary access.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        secure: bool | None = None,
    ) -> None:
        if not HAS_BOTO3:
            raise ImportError("boto3 is required for MinIO. Install with: pip install boto3")
        self._endpoint = endpoint or MINIO_ENDPOINT
        self._access_key = access_key or MINIO_ACCESS_KEY
        self._secret_key = secret_key or MINIO_SECRET_KEY
        self._bucket = bucket or MINIO_BUCKET
        self._secure = secure if secure is not None else MINIO_SECURE
        self._client = None

    def _get_client(self) -> boto3.client:
        """Lazy-initialize and return the boto3 S3 client."""
        if self._client is None:
            scheme = "https" if self._secure else "http"
            self._client = boto3.client(
                "s3",
                endpoint_url=f"{scheme}://{self._endpoint}",
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=BotoConfig(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
                region_name="us-east-1",  # MinIO default
            )
        return self._client

    def _ensure_bucket(self) -> None:
        """Create the bucket if it does not exist."""
        client = self._get_client()
        try:
            client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code == "404":
                try:
                    client.create_bucket(Bucket=self._bucket)
                    logger.info("Created MinIO bucket: %s", self._bucket)
                except ClientError as create_exc:
                    raise StorageError(
                        f"Failed to create bucket '{self._bucket}': {create_exc}",
                        component="minio",
                    ) from create_exc
            else:
                raise StorageError(
                    f"Failed to access bucket '{self._bucket}': {exc}",
                    component="minio",
                ) from exc

    def upload_file(
        self,
        file_obj: BinaryIO,
        object_name: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Upload a file to MinIO.

        Args:
            file_obj: File-like object to upload.
            object_name: Destination key (path) in the bucket.
            content_type: MIME type of the file.
            metadata: Optional user metadata dict.

        Returns:
            The object name (key) of the uploaded file.

        Raises:
            StorageError: If upload fails.

        """
        self._ensure_bucket()
        client = self._get_client()
        extra_args: dict[str, Any] = {"ContentType": content_type}
        if metadata:
            extra_args["Metadata"] = metadata
        try:
            client.upload_fileobj(file_obj, self._bucket, object_name, ExtraArgs=extra_args)
            logger.info("Uploaded '%s' to bucket '%s'", object_name, self._bucket)
            return object_name
        except (ClientError, EndpointConnectionError) as exc:
            raise StorageError(
                f"Failed to upload '{object_name}': {exc}",
                component="minio",
            ) from exc

    def download_file(self, object_name: str) -> bytes:
        """Download a file from MinIO.

        Args:
            object_name: The object key to download.

        Returns:
            File content as bytes.

        Raises:
            StorageError: If download fails.

        """
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self._bucket, Key=object_name)
            data: bytes = response["Body"].read()
            logger.info("Downloaded '%s' from bucket '%s'", object_name, self._bucket)
            return data
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("NoSuchKey", "404"):
                raise StorageError(
                    f"File not found: '{object_name}'",
                    component="minio",
                ) from exc
            raise StorageError(
                f"Failed to download '{object_name}': {exc}",
                component="minio",
            ) from exc

    def list_files(self, prefix: str = "") -> list[dict[str, Any]]:
        """List files in the bucket, optionally filtered by prefix.

        Args:
            prefix: Optional key prefix to filter results.

        Returns:
            List of dicts with keys: key, size, last_modified, etag.

        Raises:
            StorageError: If listing fails.

        """
        client = self._get_client()
        try:
            paginator = client.get_paginator("list_objects_v2")
            results: list[dict[str, Any]] = []
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    results.append(
                        {
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                            "etag": obj.get("ETag", "").strip('"'),
                        },
                    )
            return results
        except ClientError as exc:
            raise StorageError(
                f"Failed to list files: {exc}",
                component="minio",
            ) from exc

    def delete_file(self, object_name: str) -> None:
        """Delete a file from MinIO.

        Args:
            object_name: The object key to delete.

        Raises:
            StorageError: If deletion fails.

        """
        client = self._get_client()
        try:
            client.delete_object(Bucket=self._bucket, Key=object_name)
            logger.info("Deleted '%s' from bucket '%s'", object_name, self._bucket)
        except ClientError as exc:
            raise StorageError(
                f"Failed to delete '{object_name}': {exc}",
                component="minio",
            ) from exc

    def get_file_metadata(self, object_name: str) -> dict[str, Any]:
        """Get metadata for a file without downloading it.

        Args:
            object_name: The object key.

        Returns:
            Dict with keys: key, size, last_modified, content_type, metadata.

        Raises:
            StorageError: If the file does not exist or request fails.

        """
        client = self._get_client()
        try:
            response = client.head_object(Bucket=self._bucket, Key=object_name)
            return {
                "key": object_name,
                "size": response.get("ContentLength", 0),
                "last_modified": response.get("LastModified", "").isoformat() if response.get("LastModified") else "",
                "content_type": response.get("ContentType", ""),
                "metadata": response.get("Metadata", {}),
                "etag": response.get("ETag", "").strip('"'),
            }
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            if error_code in ("NoSuchKey", "404", "403"):
                raise StorageError(
                    f"File not found: '{object_name}'",
                    component="minio",
                ) from exc
            raise StorageError(
                f"Failed to get metadata for '{object_name}': {exc}",
                component="minio",
            ) from exc

    def generate_presigned_url(
        self,
        object_name: str,
        expiration: int = 3600,
    ) -> str:
        """Generate a presigned URL for downloading a file.

        Args:
            object_name: The object key.
            expiration: URL expiration time in seconds (default: 1 hour).

        Returns:
            Presigned URL string.

        Raises:
            StorageError: If URL generation fails.

        """
        client = self._get_client()
        try:
            url: str = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": object_name},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as exc:
            raise StorageError(
                f"Failed to generate presigned URL for '{object_name}': {exc}",
                component="minio",
            ) from exc

    def health_check(self) -> bool:
        """Check MinIO connectivity.

        Returns:
            True if MinIO is reachable and the bucket exists or can be created.

        Raises:
            StorageError: If MinIO is unreachable.

        """
        client = self._get_client()
        try:
            client.list_buckets()
            return True
        except (ClientError, EndpointConnectionError) as exc:
            raise StorageError(
                f"MinIO health check failed: {exc}",
                component="minio",
            ) from exc
