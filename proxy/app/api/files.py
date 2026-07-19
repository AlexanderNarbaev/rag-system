# proxy/app/api/files.py
"""File management API endpoints.

Provides upload, download, listing, metadata, and deletion of files
stored in MinIO via S3-compatible API.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from proxy.app.auth import UserContext
from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.config import MINIO_BUCKET
from proxy.app.shared.exceptions import StorageError
from proxy.app.shared.tracing import set_span_error, tracer

try:
    from proxy.app.shared.minio_client import MinioClient

    HAS_MINIO = True
except ImportError:
    HAS_MINIO = False

logger = logging.getLogger("rag-proxy")

router = APIRouter(tags=["files"])

# Maximum upload size: 100 MB
MAX_UPLOAD_SIZE = 100 * 1024 * 1024

# Allowed MIME types
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "image/png",
    "image/jpeg",
    "image/webp",
}


def _get_minio_client() -> MinioClient:
    """Dependency: return a MinIO client instance."""
    if not HAS_MINIO:
        raise HTTPException(status_code=503, detail="MinIO not available. Install boto3: pip install boto3")
    return MinioClient()


# ── Response Models ────────────────────────────────────────────────────────


class FileUploadResponse(BaseModel):
    id: str = Field(..., description="Unique file identifier (object key)")
    filename: str = Field(..., description="Original filename")
    size: int = Field(..., description="File size in bytes")
    content_type: str = Field(..., description="MIME type")
    bucket: str = Field(..., description="MinIO bucket name")
    uploaded_at: str = Field(..., description="Upload timestamp (ISO 8601)")


class FileMetadata(BaseModel):
    id: str = Field(..., description="File identifier (object key)")
    size: int = Field(..., description="File size in bytes")
    last_modified: str = Field(..., description="Last modified timestamp")
    content_type: str = Field(..., description="MIME type")
    metadata: dict[str, str] = Field(default_factory=dict, description="User metadata")


class FileListResponse(BaseModel):
    files: list[FileMetadata]
    total: int


class FileDeleteResponse(BaseModel):
    status: str
    message: str
    id: str


class PresignedUrlResponse(BaseModel):
    url: str
    expires_in: int


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/v1/files", response_model=FileUploadResponse)
async def upload_file(
    request: Request,
    file: UploadFile,
    user: UserContext = Depends(require_role(Role.USER)),  # noqa: B008
    minio: MinioClient = Depends(_get_minio_client),  # noqa: B008
) -> FileUploadResponse:
    """Upload a file to MinIO storage.

    The file is stored with a UUID-based key under the ``uploads/`` prefix.
    Original filename and content type are preserved as metadata.
    """
    with tracer.start_as_current_span("file.upload") as span:
        from proxy.app.shared.metrics import record_file_upload

        if span.is_recording():
            span.set_attribute("file.filename", file.filename or "unnamed")
            span.set_attribute("file.content_type", file.content_type or "unknown")

        content_type = file.content_type or "application/octet-stream"
        if content_type not in ALLOWED_CONTENT_TYPES:
            record_file_upload("rejected_content_type")
            allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
            raise HTTPException(
                status_code=400,
                detail=f"Content type '{content_type}' is not allowed. Allowed: {allowed}",
            )

        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            record_file_upload("size_exceeded")
            raise HTTPException(
                status_code=413,
                detail=f"File size ({len(content)} bytes) exceeds maximum ({MAX_UPLOAD_SIZE} bytes)",
            )

        file_id = f"uploads/{uuid.uuid4().hex}/{file.filename or 'unnamed'}"
        now = datetime.now(UTC).isoformat()

        metadata = {
            "original_filename": file.filename or "unnamed",
            "uploaded_by": user.username or "anonymous",
            "uploaded_at": now,
        }

        try:
            import io

            minio.upload_file(
                file_obj=io.BytesIO(content),
                object_name=file_id,
                content_type=content_type,
                metadata=metadata,
            )
        except StorageError as exc:
            logger.error("File upload failed: %s", exc)
            record_file_upload("storage_error")
            set_span_error(exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        record_file_upload("success", len(content))
        span.set_attribute("file.id", file_id)
        span.set_attribute("file.size_bytes", len(content))
        logger.info(
            "File uploaded: %s (%d bytes, user=%s)",
            file_id,
            len(content),
            user.username,
        )

        return FileUploadResponse(
            id=file_id,
            filename=file.filename or "unnamed",
            size=len(content),
            content_type=content_type,
            bucket=MINIO_BUCKET,
            uploaded_at=now,
        )


@router.get("/v1/files", response_model=FileListResponse)
async def list_files(
    prefix: str = "",
    user: UserContext = Depends(require_role(Role.USER)),  # noqa: B008
    minio: MinioClient = Depends(_get_minio_client),  # noqa: B008
) -> FileListResponse:
    """List uploaded files.

    Args:
        prefix: Optional key prefix to filter results (e.g. ``uploads/``).

    """
    with tracer.start_as_current_span("file.list") as span:
        if span.is_recording() and prefix:
            span.set_attribute("file.prefix", prefix)
        from proxy.app.shared.metrics import record_file_list

        try:
            raw_files = minio.list_files(prefix=prefix)
        except StorageError as exc:
            logger.error("File listing failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        files = [
            FileMetadata(
                id=f["key"],
                size=f["size"],
                last_modified=f["last_modified"],
                content_type="",
                metadata={},
            )
            for f in raw_files
        ]
        record_file_list()
        return FileListResponse(files=files, total=len(files))


@router.get("/v1/files/{file_id:path}/download")
async def download_file(
    file_id: str,
    user: UserContext = Depends(require_role(Role.USER)),  # noqa: B008
    minio: MinioClient = Depends(_get_minio_client),  # noqa: B008
) -> StreamingResponse:
    """Download a file from storage.

    Returns the file content as a streaming response.
    """
    with tracer.start_as_current_span("file.download") as span:
        if span.is_recording():
            span.set_attribute("file.id", file_id)
        from proxy.app.shared.metrics import record_file_download

        try:
            meta = minio.get_file_metadata(file_id)
        except StorageError as exc:
            if "not found" in str(exc).lower():
                record_file_download("not_found")
                raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from exc
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        try:
            content = minio.download_file(file_id)
        except StorageError as exc:
            logger.error("File download failed: %s", exc)
            record_file_download("error")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        record_file_download("success")
        filename = meta.get("metadata", {}).get("original_filename", file_id.rsplit("/", maxsplit=1)[-1])
        content_type = meta.get("content_type", "application/octet-stream")

        return StreamingResponse(
            iter([content]),
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(content)),
            },
        )


@router.get("/v1/files/{file_id:path}/presigned", response_model=PresignedUrlResponse)
async def get_presigned_url(
    file_id: str,
    expiration: int = 3600,
    user: UserContext = Depends(require_role(Role.USER)),  # noqa: B008
    minio: MinioClient = Depends(_get_minio_client),  # noqa: B008
) -> PresignedUrlResponse:
    """Generate a presigned download URL for a file.

    Args:
        file_id: The file identifier (object key).
        expiration: URL expiration in seconds (default: 3600, max: 604800).

    """
    with tracer.start_as_current_span("file.presigned") as span:
        if span.is_recording():
            span.set_attribute("file.id", file_id)
            span.set_attribute("file.expiration", expiration)
        from proxy.app.shared.metrics import record_file_presigned

        if expiration < 60 or expiration > 604800:
            raise HTTPException(
                status_code=400,
                detail="Expiration must be between 60 and 604800 seconds",
            )

        try:
            minio.get_file_metadata(file_id)
        except StorageError as exc:
            if "not found" in str(exc).lower():
                record_file_presigned("not_found")
                raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from exc
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        try:
            url = minio.generate_presigned_url(file_id, expiration=expiration)
        except StorageError as exc:
            logger.error("Presigned URL generation failed: %s", exc)
            record_file_presigned("error")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        record_file_presigned("success")
        return PresignedUrlResponse(url=url, expires_in=expiration)


@router.get("/v1/files/{file_id:path}", response_model=FileMetadata)
async def get_file_metadata(
    file_id: str,
    user: UserContext = Depends(require_role(Role.USER)),  # noqa: B008
    minio: MinioClient = Depends(_get_minio_client),  # noqa: B008
) -> FileMetadata:
    """Get metadata for a specific file."""
    with tracer.start_as_current_span("file.metadata") as span:
        if span.is_recording():
            span.set_attribute("file.id", file_id)
        try:
            meta = minio.get_file_metadata(file_id)
        except StorageError as exc:
            if "not found" in str(exc).lower():
                raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from exc
            logger.error("Failed to get file metadata: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return FileMetadata(
            id=meta["key"],
            size=meta["size"],
            last_modified=meta["last_modified"],
            content_type=meta["content_type"],
            metadata=meta["metadata"],
        )


@router.delete("/v1/files/{file_id:path}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: str,
    user: UserContext = Depends(require_role(Role.EXPERT)),  # noqa: B008
    minio: MinioClient = Depends(_get_minio_client),  # noqa: B008
) -> FileDeleteResponse:
    """Delete a file from storage.

    Requires EXPERT role or above.
    """
    with tracer.start_as_current_span("file.delete") as span:
        if span.is_recording():
            span.set_attribute("file.id", file_id)
        from proxy.app.shared.metrics import record_file_delete

        try:
            minio.get_file_metadata(file_id)
        except StorageError as exc:
            if "not found" in str(exc).lower():
                record_file_delete("not_found")
                raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from exc
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        try:
            minio.delete_file(file_id)
        except StorageError as exc:
            logger.error("File deletion failed: %s", exc)
            record_file_delete("error")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        record_file_delete("success")
        logger.info("File deleted: %s (user=%s)", file_id, user.username)

        return FileDeleteResponse(
            status="ok",
            message=f"File '{file_id}' deleted successfully",
            id=file_id,
        )
