# proxy/app/api/admin_kb.py
"""Knowledge Base Administration API.

Provides CRUD endpoints for managing multiple knowledge bases,
ETL task tracking, and statistics. Inspired by RAGFlow's dataset management.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from proxy.app.auth.rbac import Role, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/kb", tags=["admin-kb"])
reindex_router = APIRouter(prefix="/v1/admin/reindex", tags=["admin-reindex"])


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
async def create_knowledge_base(
    req: KBCreateRequest,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> KBResponse:
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
async def list_knowledge_bases(
    include_deleted: bool = False,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> KBListResponse:
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
async def get_knowledge_base(
    kb_id: str,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> KBResponse:
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
async def update_knowledge_base(
    kb_id: str,
    req: KBUpdateRequest,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> KBResponse:
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
async def delete_knowledge_base(
    kb_id: str,
    hard: bool = False,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> dict[str, Any]:
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
async def create_etl_task(
    kb_id: str,
    req: TaskCreateRequest,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> TaskResponse:
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
async def list_etl_tasks(
    kb_id: str,
    status: str | None = None,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> TaskListResponse:
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
async def get_etl_task(
    kb_id: str,
    task_id: str,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> TaskResponse:
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


# ---------------------------------------------------------------------------
# FR-16: Stale Document Detection
# ---------------------------------------------------------------------------


class StaleDocumentItem(BaseModel):
    """A single stale document with staleness score."""

    id: str
    source_type: str
    source_id: str
    title: str
    last_updated: float | None = None
    staleness_score: float
    expected_refresh_days: int


class StaleDocumentsResponse(BaseModel):
    """Response for stale document detection."""

    kb_id: str
    stale_count: int
    total_scanned: int
    threshold: float
    documents: list[StaleDocumentItem]


@router.get("/{kb_id}/stale", response_model=StaleDocumentsResponse)
async def get_stale_documents(
    kb_id: str,
    threshold: float = 100.0,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> StaleDocumentsResponse:
    """Get stale documents for a knowledge base.

    Returns documents past their freshness threshold with staleness scores (0-100).
    Optional ?threshold=70 filter to show only highly stale documents.
    """
    mgr = _get_kb_manager()
    kb = mgr.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")

    from proxy.app.core.retrieval import qdrant_client
    from proxy.app.core.stale_detector import detect_stale_documents, update_prometheus_metrics

    stale_docs = detect_stale_documents(
        kb_id=kb_id,
        kb_manager=mgr,
        qdrant_client=qdrant_client,
        collection_name=kb.collection_name,
        threshold=threshold,
    )
    update_prometheus_metrics(kb_id, len(stale_docs))

    return StaleDocumentsResponse(
        kb_id=kb_id,
        stale_count=len(stale_docs),
        total_scanned=len(stale_docs),
        threshold=threshold,
        documents=[
            StaleDocumentItem(
                id=d["id"],
                source_type=d["source_type"],
                source_id=d["source_id"],
                title=d["title"],
                last_updated=d.get("last_updated"),
                staleness_score=d["staleness_score"],
                expected_refresh_days=d["expected_refresh_days"],
            )
            for d in stale_docs
        ],
    )


# ---------------------------------------------------------------------------
# FR-17: Reindex Scheduler
# ---------------------------------------------------------------------------


class ReindexResponse(BaseModel):
    """Response for forced reindex of stale documents."""

    kb_id: str
    stale_count: int
    tasks_created: int
    errors: list[str]
    documents: list[StaleDocumentItem]


class ReindexStatusResponse(BaseModel):
    """Response for reindex scheduler status."""

    running: bool
    last_check_time: float | None
    total_stale_found: int
    tasks_triggered: int
    errors: list[str]
    per_kb: dict[str, Any]


@reindex_router.post("/stale/{kb_id}", response_model=ReindexResponse)
async def force_reindex_stale_endpoint(
    kb_id: str,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> ReindexResponse:
    """Force reindex all stale documents in a knowledge base."""
    mgr = _get_kb_manager()
    kb = mgr.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")

    from proxy.app.core.reindex_scheduler import force_reindex_stale
    from proxy.app.core.retrieval import qdrant_client

    result = await force_reindex_stale(
        kb_id=kb_id,
        kb_manager=mgr,
        qdrant_client=qdrant_client,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return ReindexResponse(
        kb_id=result["kb_id"],
        stale_count=result["stale_count"],
        tasks_created=result["tasks_created"],
        errors=result.get("errors", []),
        documents=[
            StaleDocumentItem(
                id=d["id"],
                source_type=d["source_type"],
                source_id=d["source_id"],
                title=d["title"],
                last_updated=d.get("last_updated"),
                staleness_score=d["staleness_score"],
                expected_refresh_days=d["expected_refresh_days"],
            )
            for d in result.get("documents", [])
        ],
    )


@reindex_router.get("/status", response_model=ReindexStatusResponse)
async def get_reindex_status(
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> ReindexStatusResponse:
    """Get current reindex scheduler status."""
    from proxy.app.core.reindex_scheduler import get_reindex_status

    status = get_reindex_status()
    return ReindexStatusResponse(
        running=status.get("running", False),
        last_check_time=status.get("last_check_time"),
        total_stale_found=status.get("total_stale_found", 0),
        tasks_triggered=status.get("tasks_triggered", 0),
        errors=status.get("errors", []),
        per_kb=status.get("per_kb", {}),
    )


# ---------------------------------------------------------------------------
# FR-18: Knowledge Integrity Validation
# ---------------------------------------------------------------------------


class ContradictionPair(BaseModel):
    """A pair of contradictory chunks."""

    source_id: str
    chunk_a_id: str
    chunk_a_title: str
    chunk_b_id: str
    chunk_b_title: str
    source_type: str
    contradiction_score: float
    entailment_score: float
    neutral_score: float
    text_preview_a: str
    text_preview_b: str


class CoverageGap(BaseModel):
    """A coverage gap in knowledge base."""

    type: str
    message: str
    age_days: float | None = None
    source: str | None = None


class IntegrityResponse(BaseModel):
    """Response for knowledge integrity validation."""

    kb_id: str
    overall_score: float
    contradictions: list[ContradictionPair]
    coverage: dict[str, Any]
    coverage_gaps: list[CoverageGap]


@router.get("/{kb_id}/integrity", response_model=IntegrityResponse)
async def get_integrity_check(
    kb_id: str,
    _user: Any = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> IntegrityResponse:
    """Get knowledge integrity report for a KB.

    Returns contradiction pairs, coverage gaps, and overall integrity score.
    """
    mgr = _get_kb_manager()
    kb = mgr.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base {kb_id} not found")

    from proxy.app.core.integrity_checker import compute_integrity_score
    from proxy.app.core.retrieval import qdrant_client

    result = compute_integrity_score(
        kb_id=kb_id,
        qdrant_client=qdrant_client,
        collection_name=kb.collection_name,
    )

    coverage_gaps = []
    for gap in result.get("coverage", {}).get("coverage_gaps", []):
        coverage_gaps.append(
            CoverageGap(
                type=gap.get("type", ""),
                message=gap.get("message", ""),
                age_days=gap.get("age_days"),
                source=gap.get("source"),
            )
        )

    return IntegrityResponse(
        kb_id=result["kb_id"],
        overall_score=result["overall_score"],
        contradictions=[
            ContradictionPair(
                source_id=c["source_id"],
                chunk_a_id=c["chunk_a_id"],
                chunk_a_title=c["chunk_a_title"],
                chunk_b_id=c["chunk_b_id"],
                chunk_b_title=c["chunk_b_title"],
                source_type=c["source_type"],
                contradiction_score=c["contradiction_score"],
                entailment_score=c["entailment_score"],
                neutral_score=c["neutral_score"],
                text_preview_a=c["text_preview_a"],
                text_preview_b=c["text_preview_b"],
            )
            for c in result.get("contradictions", [])
        ],
        coverage=result.get("coverage", {}),
        coverage_gaps=coverage_gaps,
    )
