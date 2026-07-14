# ADR-014: MinIO Object Storage for File Management

**Status:** Accepted  
**Date:** 2026-07-10  
**Author:** Architecture Design  
**Scope:** S3-compatible object storage for file uploads, document management, and model artifacts

---

## Context

The RAG system needs persistent file storage for:

- User-uploaded documents (via OpenWebUI or API)
- ETL pipeline artifacts (chunks, embeddings)
- Model artifacts (LoRA adapters, fine-tuned models)
- Backup files

Requirements:

- S3-compatible API (for boto3 compatibility)
- Air-gapped deployment (no external cloud storage)
- Scalable and reliable
- Integration with OpenWebUI file uploads

## Decision

Deploy MinIO as the object storage backend:

1. **S3-compatible API** — Works with boto3, AWS SDK, and OpenWebUI
2. **Three buckets**:
    - `rag-documents` — User-uploaded documents
    - `rag-artifacts` — Model artifacts and training data
    - `open-webui` — OpenWebUI file uploads
3. **Docker deployment** — Single container with persistent volume
4. **Presigned URLs** — Secure temporary access to files

## Architecture

```
OpenWebUI → MinIO (9000) → S3 API
ETL Pipeline → MinIO → rag-documents bucket
Model Evolution → MinIO → rag-artifacts bucket
RAG Proxy → MinIO → File metadata + presigned URLs
```

## API Endpoints

| Endpoint                       | Method        | Description               |
|--------------------------------|---------------|---------------------------|
| `POST /v1/files`               | Upload file   | Multipart upload to MinIO |
| `GET /v1/files`                | List files    | List objects in bucket    |
| `GET /v1/files/{id}`           | Get metadata  | Object metadata           |
| `GET /v1/files/{id}/download`  | Download      | Stream object content     |
| `GET /v1/files/{id}/presigned` | Presigned URL | Temporary download URL    |
| `DELETE /v1/files/{id}`        | Delete        | Remove object             |

## Configuration

```env
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=rag-documents
MINIO_SECURE=false
```

## Consequences

### Positive

- S3-compatible API works with all AWS SDKs
- Air-gapped (no external dependencies)
- Scalable (can add nodes later)
- OpenWebUI native support

### Negative

- Additional infrastructure component
- Storage management overhead
- Backup complexity

### Mitigations

- Single Docker container for small deployments
- Automated backup scripts in scripts/ops/
- Health check monitoring
