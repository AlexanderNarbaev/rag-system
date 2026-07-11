# proxy/app/api/files.py
"""
File management API endpoints.

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
    return MinioClient()  # type: ignore[misc]


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
):
    """Upload a file to MinIO storage.

    The file is stored with a UUID-based key under the ``uploads/`` prefix.
    Original filename and content type are preserved as metadata.
    """
    # Validate content type
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Content type '{content_type}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}",
        )

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size ({len(content)} bytes) exceeds maximum ({MAX_UPLOAD_SIZE} bytes)",
        )

    # Generate unique object key
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
):
    """List uploaded files.

    Args:
        prefix: Optional key prefix to filter results (e.g. ``uploads/``).
    """
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

    return FileListResponse(files=files, total=len(files))


@router.get("/v1/files/{file_id:path}/download")
async def download_file(
    file_id: str,
    user: UserContext = Depends(require_role(Role.USER)),  # noqa: B008
    minio: MinioClient = Depends(_get_minio_client),  # noqa: B008
):
    """Download a file from storage.

    Returns the file content as a streaming response.
    """
    try:
        meta = minio.get_file_metadata(file_id)
    except StorageError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        content = minio.download_file(file_id)
    except StorageError as exc:
        logger.error("File download failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = meta.get("metadata", {}).get("original_filename", file_id.split("/")[-1])
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
):
    """Generate a presigned download URL for a file.

    Args:
        file_id: The file identifier (object key).
        expiration: URL expiration in seconds (default: 3600, max: 604800).
    """
    if expiration < 60 or expiration > 604800:
        raise HTTPException(
            status_code=400,
            detail="Expiration must be between 60 and 604800 seconds",
        )

    # Verify file exists
    try:
        minio.get_file_metadata(file_id)
    except StorageError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        url = minio.generate_presigned_url(file_id, expiration=expiration)
    except StorageError as exc:
        logger.error("Presigned URL generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return PresignedUrlResponse(url=url, expires_in=expiration)


@router.get("/v1/files/{file_id:path}", response_model=FileMetadata)
async def get_file_metadata(
    file_id: str,
    user: UserContext = Depends(require_role(Role.USER)),  # noqa: B008
    minio: MinioClient = Depends(_get_minio_client),  # noqa: B008
):
    """Get metadata for a specific file."""
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
):
    """Delete a file from storage.

    Requires EXPERT role or above.
    """
    # Verify file exists first
    try:
        minio.get_file_metadata(file_id)
    except StorageError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=f"File not found: {file_id}") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        minio.delete_file(file_id)
    except StorageError as exc:
        logger.error("File deletion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info("File deleted: %s (user=%s)", file_id, user.username)

    return FileDeleteResponse(
        status="ok",
        message=f"File '{file_id}' deleted successfully",
        id=file_id,
    )
