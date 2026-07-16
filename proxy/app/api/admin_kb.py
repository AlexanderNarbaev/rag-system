# proxy/app/api/admin_kb.py
"""Knowledge Base Administration API.

Provides CRUD endpoints for managing multiple knowledge bases,
ETL task tracking, and statistics. Inspired by RAGFlow's dataset management.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/kb", tags=["admin-kb"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class KBCreateRequest(BaseModel):
    """Request to create a knowledge base."""

    name: str = Field(..., min_length=1, max_length=128, description="Knowledge base name")
    description: str = Field("", description="KB description")
    embedding_model: str = Field("BAAI/bge-m3", description="Embedding model name")
    dense_vector_size: int = Field(1024, description="Dense vector dimension")
    parser_config: dict[str, Any] | None = Field(None, description="Parser configuration")


class KBUpdateRequest(BaseModel):
    """Request to update a knowledge base."""

    name: str | None = None
    description: str | None = None
    embedding_model: str | None = None
    parser_config: dict[str, Any] | None = None


class KBResponse(BaseModel):
    """Knowledge base response."""

    id: str
    name: str
    description: str
    collection_name: str
    embedding_model: str
    dense_vector_size: int
    parser_config: dict[str, Any]
    doc_count: int
    chunk_count: int
    token_count: int
    status: str
    created_at: float
    updated_at: float


class TaskCreateRequest(BaseModel):
    """Request to create an ETL task."""

    source_type: str = Field(..., description="Source type: confluence, jira, gitlab, file")
    source_id: str = Field(..., description="Source identifier (page ID, issue key, etc.)")


class TaskResponse(BaseModel):
    """ETL task response."""

    id: str
    kb_id: str
    source_type: str
    source_id: str
    status: str
    progress: float
    error_message: str
    created_at: float
    updated_at: float


class KBListResponse(BaseModel):
    """List of knowledge bases."""

    knowledge_bases: list[KBResponse]
    total: int


class TaskListResponse(BaseModel):
    """List of ETL tasks."""

    tasks: list[TaskResponse]
    total: int


# ---------------------------------------------------------------------------
# Dependency: get the KnowledgeBaseManager instance
# ---------------------------------------------------------------------------


def _get_kb_manager() -> Any:
    """Get the KB manager from the main app state."""
    from proxy.app.main import kb_manager

    if kb_manager is None:
        raise HTTPException(status_code=503, detail="Knowledge base manager not initialized")
    return kb_manager


# ---------------------------------------------------------------------------
# Knowledge Base endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=KBResponse, status_code=201)
async def create_knowledge_base(req: KBCreateRequest) -> KBResponse:
    """Create a new knowledge base with its own Qdrant collection."""
    mgr = _get_kb_manager()
    try:
        kb = mgr.create_kb(
            name=req.name,
            description=req.description,
            embedding_model=req.embedding_model,
            dense_vector_size=req.dense_vector_size,
            parser_config=req.parser_config,
        )
        return KBResponse(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            collection_name=kb.collection_name,
            embedding_model=kb.embedding_model,
            dense_vector_size=kb.dense_vector_size,
            parser_config=kb.parser_config,
            doc_count=kb.doc_count,
            chunk_count=kb.chunk_count,
            token_count=kb.token_count,
            status=kb.status,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/", response_model=KBListResponse)
async def list_knowledge_bases(include_deleted: bool = False) -> KBListResponse:
    """List all knowledge bases."""
    mgr = _get_kb_manager()
    kbs = mgr.list_kbs(include_deleted=include_deleted)
    return KBListResponse(
        knowledge_bases=[
            KBResponse(
                id=kb.id,
                name=kb.name,
                description=kb.description,
                collection_name=kb.collection_name,
                embedding_model=kb.embedding_model,
                dense_vector_size=kb.dense_vector_size,
                parser_config=kb.parser_config,
                doc_count=kb.doc_count,
                chunk_count=kb.chunk_count,
                token_count=kb.token_count,
                status=kb.status,
                created_at=kb.created_at,
                updated_at=kb.updated_at,
            )
            for kb in kbs
        ],
        total=len(kbs),
    )


@router.get("/{kb_id}", response_model=KBResponse)
async def get_knowledge_base(kb_id: str) -> KBResponse:
    """Get a knowledge base by ID."""
    mgr = _get_kb_manager()
    kb = mgr.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")
    return KBResponse(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        collection_name=kb.collection_name,
        embedding_model=kb.embedding_model,
        dense_vector_size=kb.dense_vector_size,
        parser_config=kb.parser_config,
        doc_count=kb.doc_count,
        chunk_count=kb.chunk_count,
        token_count=kb.token_count,
        status=kb.status,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


@router.put("/{kb_id}", response_model=KBResponse)
async def update_knowledge_base(kb_id: str, req: KBUpdateRequest) -> KBResponse:
    """Update a knowledge base."""
    mgr = _get_kb_manager()
    try:
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        kb = mgr.update_kb(kb_id, **updates)
        return KBResponse(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            collection_name=kb.collection_name,
            embedding_model=kb.embedding_model,
            dense_vector_size=kb.dense_vector_size,
            parser_config=kb.parser_config,
            doc_count=kb.doc_count,
            chunk_count=kb.chunk_count,
            token_count=kb.token_count,
            status=kb.status,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: str, hard: bool = False) -> dict[str, Any]:
    """Delete a knowledge base (soft delete by default)."""
    mgr = _get_kb_manager()
    success = mgr.delete_kb(kb_id, hard=hard)
    if not success:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")
    return {"status": "deleted", "kb_id": kb_id, "hard": hard}


# ---------------------------------------------------------------------------
# ETL Task endpoints
# ---------------------------------------------------------------------------


@router.post("/{kb_id}/tasks", response_model=TaskResponse, status_code=201)
async def create_etl_task(kb_id: str, req: TaskCreateRequest) -> TaskResponse:
    """Create an ETL task for a knowledge base."""
    mgr = _get_kb_manager()
    kb = mgr.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")
    task = mgr.create_task(kb_id=kb_id, source_type=req.source_type, source_id=req.source_id)
    return TaskResponse(
        id=task.id,
        kb_id=task.kb_id,
        source_type=task.source_type,
        source_id=task.source_id,
        status=task.status,
        progress=task.progress,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("/{kb_id}/tasks", response_model=TaskListResponse)
async def list_etl_tasks(kb_id: str, status: str | None = None) -> TaskListResponse:
    """List ETL tasks for a knowledge base."""
    mgr = _get_kb_manager()
    tasks = mgr.list_tasks(kb_id=kb_id, status=status)
    return TaskListResponse(
        tasks=[
            TaskResponse(
                id=t.id,
                kb_id=t.kb_id,
                source_type=t.source_type,
                source_id=t.source_id,
                status=t.status,
                progress=t.progress,
                error_message=t.error_message,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
            for t in tasks
        ],
        total=len(tasks),
    )


@router.get("/{kb_id}/tasks/{task_id}", response_model=TaskResponse)
async def get_etl_task(kb_id: str, task_id: str) -> TaskResponse:
    """Get an ETL task by ID."""
    mgr = _get_kb_manager()
    task = mgr.get_task(task_id)
    if task is None or task.kb_id != kb_id:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found in KB {kb_id}")
    return TaskResponse(
        id=task.id,
        kb_id=task.kb_id,
        source_type=task.source_type,
        source_id=task.source_id,
        status=task.status,
        progress=task.progress,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
