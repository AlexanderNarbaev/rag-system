# proxy/app/api/admin_feedback.py
"""Admin feedback review workflow — list, update, stats, chunk-analysis."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from proxy.app.auth import UserContext
from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.tracing import add_event, tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(prefix="/v1/admin/feedback", tags=["admin-feedback"])


class FeedbackEntryResponse(BaseModel):
    id: str
    feedback_id: str
    user_id: str
    username: str
    role: str
    rating: str
    feedback_type: str
    comment: str | None = None
    correction: str | None = None
    question: str | None = None
    answer: str | None = None
    contexts: list[str] = []
    kb_id: str | None = None
    confidence: float | None = None
    chunk_feedback: list[dict[str, Any]] = []
    retrieval_quality: int | None = None
    status: str = "pending"
    admin_notes: str | None = None
    created_at: str = ""
    updated_at: str = ""


class FeedbackListResponse(BaseModel):
    entries: list[FeedbackEntryResponse]
    total: int


class FeedbackUpdateRequest(BaseModel):
    status: str | None = Field(None, pattern="^(pending|reviewed|accepted|rejected)$")
    admin_notes: str | None = None


class FeedbackStatsResponse(BaseModel):
    total: int
    positive: int
    negative: int
    pos_ratio: float
    neg_ratio: float
    average_confidence: float | None = None
    average_retrieval_quality: float | None = None
    most_corrected_topics: list[dict[str, Any]]
    feedback_by_user: list[dict[str, Any]]


class ChunkStatEntry(BaseModel):
    chunk_id: str
    average_relevance: float
    ratings_count: int
    low_ratings: int


class NegativeTrainingPair(BaseModel):
    query: str
    chunk_id: str
    relevance_score: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    status: str | None = Query(None, description="Filter: pending, reviewed, accepted, rejected"),
    kb_id: str | None = Query(None, description="Filter by knowledge base"),
    date_from: str | None = Query(None, description="ISO datetime lower bound"),
    date_to: str | None = Query(None, description="ISO datetime upper bound"),
    min_confidence: float | None = Query(None, description="Max confidence (filters low-confidence responses)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> FeedbackListResponse:
    """List feedback entries with filters. Admin only."""
    from proxy.app.core.feedback_store import get_feedback_store

    with tracer.start_as_current_span("admin.feedback.list"):
        store = get_feedback_store()
        filters: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            filters["status"] = status
        if kb_id:
            filters["kb_id"] = kb_id
        if date_from:
            filters["date_from"] = date_from
        if date_to:
            filters["date_to"] = date_to
        if min_confidence is not None:
            filters["min_confidence"] = min_confidence

        entries = store.list(**filters)
        add_event("admin.feedback.listed", {"count": len(entries)})

    return FeedbackListResponse(
        entries=[FeedbackEntryResponse(**e.to_dict()) for e in entries],
        total=len(entries),
    )


@router.patch("/{feedback_id}")
async def update_feedback(
    feedback_id: str,
    body: FeedbackUpdateRequest,
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> JSONResponse:
    """Update feedback status and admin notes. Admin only."""
    from proxy.app.core.feedback_store import get_feedback_store

    with tracer.start_as_current_span("admin.feedback.update") as span:
        if span.is_recording():
            span.set_attribute("feedback.id", feedback_id)

        store = get_feedback_store()
        existing = store.get(feedback_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Feedback {feedback_id} not found")

        updates: dict[str, Any] = {}
        if body.status:
            updates["status"] = body.status
        if body.admin_notes is not None:
            updates["admin_notes"] = body.admin_notes

        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        store.update(feedback_id, updates)
        add_event("admin.feedback.updated")

    updated = store.get(feedback_id)
    return JSONResponse(status_code=200, content={
        "feedback_id": feedback_id,
        "status": updated.status if updated else existing.status,
        **updates,
    })


@router.get("/stats", response_model=FeedbackStatsResponse)
async def feedback_stats(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> FeedbackStatsResponse:
    """Feedback statistics: pos/neg ratio, corrected topics, confidence, volume. Admin only."""
    from proxy.app.core.feedback_store import get_feedback_store

    with tracer.start_as_current_span("admin.feedback.stats"):
        store = get_feedback_store()
        stats = store.stats(date_from=date_from, date_to=date_to)
        add_event("admin.feedback.stats_retrieved")

    return FeedbackStatsResponse(**stats)


@router.get("/chunk-stats", response_model=list[ChunkStatEntry])
async def chunk_stats(
    min_count: int = Query(1, ge=1),
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> list[ChunkStatEntry]:
    """Get chunk-level feedback statistics: which chunks are rated lowest. Admin only."""
    from proxy.app.core.feedback_store import get_feedback_store

    with tracer.start_as_current_span("admin.feedback.chunk_stats"):
        store = get_feedback_store()
        results = store.chunk_stats(min_count=min_count)
        add_event("admin.feedback.chunk_stats_retrieved", {"count": len(results)})

    return [ChunkStatEntry(**r) for r in results]


@router.get("/negative-pairs", response_model=list[NegativeTrainingPair])
async def negative_training_pairs(
    user: UserContext = Depends(require_role(Role.ADMIN)),  # noqa: B008
) -> list[NegativeTrainingPair]:
    """Get negative training pairs from chunks marked irrelevant (score 1-2). For reranker training. Admin only."""
    from proxy.app.core.feedback_store import get_feedback_store

    with tracer.start_as_current_span("admin.feedback.negative_pairs"):
        store = get_feedback_store()
        pairs = store.get_negative_training_pairs()
        add_event("admin.feedback.negative_pairs_retrieved", {"count": len(pairs)})

    return [NegativeTrainingPair(**p) for p in pairs]
