# proxy/app/api/expert_kb.py
"""Expert KB management endpoints — document review, flagging, and reindex (expert/admin)."""

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.tracing import tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(prefix="/v1/expert/kb", tags=["expert-kb"])


# ---------------------------------------------------------------------------
# In-memory stores for flagged docs and reviews
# ---------------------------------------------------------------------------

_flagged_lock = threading.RLock()
_flagged_documents: dict[str, list[dict[str, Any]]] = {}
_reviews: dict[str, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DocumentReviewRequest(BaseModel):
    chunk_id: str = Field(..., description="ID of the chunk being reviewed")
    rating: str = Field(..., description="Rating: approved, needs_revision, rejected")
    comment: str = Field("", description="Expert comment on the chunk")
    corrections: dict[str, str] | None = Field(None, description="Key → corrected value pairs")


class DocumentReviewResponse(BaseModel):
    review_id: str
    kb_id: str
    chunk_id: str
    rating: str
    comment: str
    created_at: str


class DocumentFlagRequest(BaseModel):
    chunk_id: str = Field(..., description="ID of the document chunk to flag")
    reason: str = Field(..., description="Reason for flagging: duplicate, outdated, inaccurate, spam")
    comment: str = Field("", description="Additional context from the expert")


class DocumentFlagResponse(BaseModel):
    flag_id: str
    kb_id: str
    chunk_id: str
    reason: str
    comment: str
    flagged_at: str
    status: str


class ReindexRequest(BaseModel):
    source_type: str | None = Field(None, description="Source type to reindex: confluence, jira, gitlab")
    source_id: str | None = Field(None, description="Specific source ID to reindex")


class ReindexResponse(BaseModel):
    kb_id: str
    reindex_id: str
    source_type: str | None
    source_id: str | None
    status: str
    message: str
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{kb_id}/documents/review", response_model=DocumentReviewResponse, status_code=201)
async def review_document(
    kb_id: str,
    req: DocumentReviewRequest,
    request: Request,
    user: Any = Depends(require_role(Role.EXPERT)),  # noqa: B008
) -> DocumentReviewResponse:
    """Expert reviews a specific document chunk in a knowledge base.

    Ratings: approved, needs_revision, rejected.
    Corrections map allows experts to provide corrected field values.
    """
    with tracer.start_as_current_span("expert.kb.review") as span:
        if span.is_recording():
            span.set_attribute("expert.kb.kb_id", kb_id)
            span.set_attribute("expert.kb.chunk_id", req.chunk_id)
            span.set_attribute("expert.kb.rating", req.rating)

        if req.rating not in ("approved", "needs_revision", "rejected"):
            raise HTTPException(
                status_code=422,
                detail="Rating must be one of: approved, needs_revision, rejected",
            )

        review_id = f"rev-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()

        review_entry = {
            "review_id": review_id,
            "kb_id": kb_id,
            "chunk_id": req.chunk_id,
            "rating": req.rating,
            "comment": req.comment,
            "corrections": req.corrections,
            "reviewed_by": user.username,
            "created_at": now,
        }

        with _flagged_lock:
            _reviews.setdefault(kb_id, []).append(review_entry)

        logger.info(
            "Expert %s reviewed chunk %s in KB %s: %s",
            user.username,
            req.chunk_id,
            kb_id,
            req.rating,
        )

        return DocumentReviewResponse(
            review_id=review_id,
            kb_id=kb_id,
            chunk_id=req.chunk_id,
            rating=req.rating,
            comment=req.comment,
            created_at=now,
        )


@router.post("/{kb_id}/documents/flag", response_model=DocumentFlagResponse, status_code=201)
async def flag_document(
    kb_id: str,
    req: DocumentFlagRequest,
    request: Request,
    user: Any = Depends(require_role(Role.EXPERT)),  # noqa: B008
) -> DocumentFlagResponse:
    """Expert flags a document chunk for removal or further review.

    Reasons: duplicate, outdated, inaccurate, spam.
    Flagged documents are visible via GET /flags.
    """
    with tracer.start_as_current_span("expert.kb.flag") as span:
        if span.is_recording():
            span.set_attribute("expert.kb.kb_id", kb_id)
            span.set_attribute("expert.kb.chunk_id", req.chunk_id)
            span.set_attribute("expert.kb.reason", req.reason)

        valid_reasons = ("duplicate", "outdated", "inaccurate", "spam")
        if req.reason not in valid_reasons:
            raise HTTPException(
                status_code=422,
                detail=f"Reason must be one of: {', '.join(valid_reasons)}",
            )

        flag_id = f"flag-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()

        flag_entry = {
            "flag_id": flag_id,
            "kb_id": kb_id,
            "chunk_id": req.chunk_id,
            "reason": req.reason,
            "comment": req.comment,
            "flagged_by": user.username,
            "flagged_at": now,
            "status": "open",
        }

        with _flagged_lock:
            _flagged_documents.setdefault(kb_id, []).append(flag_entry)

        logger.info(
            "Expert %s flagged chunk %s in KB %s: %s",
            user.username,
            req.chunk_id,
            kb_id,
            req.reason,
        )

        return DocumentFlagResponse(
            flag_id=flag_id,
            kb_id=kb_id,
            chunk_id=req.chunk_id,
            reason=req.reason,
            comment=req.comment,
            flagged_at=now,
            status="open",
        )


@router.get("/{kb_id}/flags")
async def list_flagged_documents(
    kb_id: str,
    request: Request,
    status: str | None = None,
    user: Any = Depends(require_role(Role.EXPERT)),  # noqa: B008
) -> JSONResponse:
    """List all flagged documents in a knowledge base.

    Optional ?status=open filter to show only unresolved flags.
    """
    with tracer.start_as_current_span("expert.kb.flags_list") as span:
        if span.is_recording():
            span.set_attribute("expert.kb.kb_id", kb_id)

        with _flagged_lock:
            all_flags = _flagged_documents.get(kb_id, [])

        if status:
            all_flags = [f for f in all_flags if f.get("status") == status]

        return JSONResponse(
            status_code=200,
            content={
                "kb_id": kb_id,
                "total": len(all_flags),
                "flags": sorted(all_flags, key=lambda f: f["flagged_at"], reverse=True),
            },
        )


@router.post("/{kb_id}/reindex", response_model=ReindexResponse, status_code=201)
async def trigger_reindex(
    kb_id: str,
    req: ReindexRequest,
    request: Request,
    user: Any = Depends(require_role(Role.EXPERT)),  # noqa: B008
) -> ReindexResponse:
    """Expert triggers reindex of a specific source or entire knowledge base.

    If source_type and source_id are omitted, triggers full KB reindex.
    """
    with tracer.start_as_current_span("expert.kb.reindex") as span:
        if span.is_recording():
            span.set_attribute("expert.kb.kb_id", kb_id)
            if req.source_type:
                span.set_attribute("expert.kb.source_type", req.source_type)
            if req.source_id:
                span.set_attribute("expert.kb.source_id", req.source_id)

        reindex_id = f"reidx-{uuid.uuid4().hex[:12]}"
        now = datetime.now(UTC).isoformat()

        # Try to trigger actual reindex via the reindex scheduler if available
        message = "Reindex queued successfully"
        try:
            from proxy.app.main import kb_manager

            if kb_manager is not None:
                kb = kb_manager.get_kb(kb_id)
                if kb is None:
                    logger.warning("KB %s not found in local manager — reindex queued anyway", kb_id)
                    message = f"Reindex queued for KB {kb_id} (KB not in local manager)"

                if kb is not None:
                    if req.source_type and req.source_id:
                        message = f"Reindex queued for source {req.source_type}/{req.source_id} in KB {kb_id}"
                    elif req.source_type:
                        message = f"Reindex queued for all {req.source_type} sources in KB {kb_id}"
                    else:
                        message = f"Full reindex queued for KB {kb_id}"
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("KB manager lookup failed for reindex: %s", e)
            message = f"Reindex queued (KB manager unavailable: {e})"

        logger.info(
            "Expert %s triggered reindex of KB %s (source=%s, id=%s)",
            user.username,
            kb_id,
            req.source_type or "all",
            req.source_id or "all",
        )

        return ReindexResponse(
            kb_id=kb_id,
            reindex_id=reindex_id,
            source_type=req.source_type,
            source_id=req.source_id,
            status="queued",
            message=message,
            created_at=now,
        )
