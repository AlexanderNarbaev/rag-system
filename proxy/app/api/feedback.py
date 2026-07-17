# proxy/app/api/feedback.py
"""User and expert feedback endpoint for HITL quality control."""

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from proxy.app.auth import UserContext
from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.tracing import add_event, set_span_error, tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(tags=["feedback"])


class ChunkFeedbackItem(BaseModel):
    chunk_id: str = Field(..., description="ID of the retrieved chunk")
    relevance_score: int = Field(..., ge=1, le=5, description="Relevance score 1-5")


class FeedbackRequest(BaseModel):
    feedback_id: str = Field(..., description="rag_feedback_id from the response")
    rating: str = Field(..., pattern="^(positive|negative)$")
    correction: str | None = Field(None, description="Corrected answer text (expert-only)")
    comment: str | None = Field(None, description="Free-text comment")
    question: str | None = Field(None, description="Original user question")
    answer: str | None = Field(None, description="System answer that was rated")
    contexts: list[str] | None = Field(None, description="Retrieved context chunks")
    kb_id: str | None = Field(None, description="Knowledge base identifier")
    confidence: float | None = Field(None, description="Confidence score of the original response")
    chunk_feedback: list[ChunkFeedbackItem] | None = Field(None, description="Per-chunk relevance ratings")
    retrieval_quality: int | None = Field(None, ge=1, le=5, description="Overall retrieval quality 1-5")


class FeedbackResponse(BaseModel):
    status: str
    message: str
    feedback_id: str


@router.post("/v1/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    raw_request: Request,
    user: UserContext = Depends(require_role(Role.USER)),  # noqa: B008
) -> FeedbackResponse:
    """Submit feedback on a RAG response.

    Role.USER and above can submit simple feedback (rating + comment).
    Corrections (corrected_answer) are restricted to Role.EXPERT and above.
    """
    from proxy.app.core.hitl import FeedbackType, get_logger

    has_correction = request.correction is not None and len(request.correction or "") > 0

    if has_correction and "expert" not in user.roles and "admin" not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Corrections require expert or admin role",
        )

    is_expert = has_correction and ("expert" in user.roles or "admin" in user.roles)
    feedback_type_value = "expert_correction" if is_expert else "user_rating"

    start_time = time.time()

    with tracer.start_as_current_span("feedback.submit") as span:
        if span.is_recording():
            span.set_attribute("feedback.id", request.feedback_id)
            span.set_attribute("feedback.rating", request.rating)
            span.set_attribute("feedback.has_correction", has_correction)
            span.set_attribute("feedback.type", feedback_type_value)

        from proxy.app.shared.metrics import record_enrichment, record_feedback

        hlog = get_logger()
        feedback_enum = FeedbackType.POSITIVE if request.rating == "positive" else FeedbackType.NEGATIVE

        try:
            hlog.log_feedback(
                request_id=request.feedback_id,
                feedback_type=feedback_enum,
                comment=request.comment or "",
                corrected_response=request.correction,
                expert_id=user.username if has_correction else None,
            )
            add_event("feedback.logged")
        except Exception as e:
            logger.error(f"Failed to record feedback: {e}")
            set_span_error(e)
            raise HTTPException(status_code=500, detail="Failed to record feedback") from e

        try:
            from proxy.app.core.feedback_store import FeedbackEntry, get_feedback_store

            entry = FeedbackEntry(
                feedback_id=request.feedback_id,
                user_id=user.user_id,
                username=user.username,
                role=user.roles[0] if user.roles else "user",
                rating=request.rating,
                feedback_type=feedback_type_value,
                comment=request.comment,
                correction=request.correction,
                question=request.question,
                answer=request.answer,
                contexts_json=_json_dumps(request.contexts),
                kb_id=request.kb_id,
                confidence=request.confidence,
                chunk_feedback_json=_json_dumps(
                    [cf.model_dump() for cf in request.chunk_feedback] if request.chunk_feedback else None
                ),
                retrieval_quality=request.retrieval_quality,
            )
            get_feedback_store().insert(entry)
            add_event("feedback.store_inserted")
        except Exception as e:
            logger.error(f"Failed to store feedback in SQLite: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to store feedback: {e}") from e

        ragas_scores = None
        if request.contexts and request.question:
            from proxy.app.core.ragas_eval import evaluate_rag_response

            ragas_scores = evaluate_rag_response(
                question=request.question,
                answer=request.answer or "",
                contexts=request.contexts,
            )
            logger.info(f"RAGAS scores for feedback {request.feedback_id}: {ragas_scores}")
            if span.is_recording() and ragas_scores:
                for key, value in ragas_scores.items():
                    span.set_attribute(f"ragas.{key}", value)

        from proxy.app.shared.config import ENRICHMENT_ENABLED

        if ENRICHMENT_ENABLED and (request.rating == "positive" or request.correction):
            try:
                from proxy.app.core.enricher import enrich_from_feedback

                await enrich_from_feedback(request)
                record_enrichment("success")
                add_event("feedback.enriched")
            except Exception as e:
                logger.error(f"Enrichment failed (non-blocking): {e}")
                record_enrichment("failure")
                add_event("feedback.enrichment_failed", {"error": str(e)})

        duration = time.time() - start_time
        record_feedback(request.rating, duration)

        return FeedbackResponse(
            status="ok",
            message="Feedback recorded",
            feedback_id=request.feedback_id,
        )


def _json_dumps(obj: Any) -> str | None:
    import json

    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False)
