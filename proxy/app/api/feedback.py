# proxy/app/api/feedback.py
"""Expert feedback endpoint for HITL quality control."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from proxy.app.auth import UserContext
from proxy.app.auth.rbac import Role, require_role
from proxy.app.shared.tracing import add_event, set_span_error, tracer

logger = logging.getLogger("rag-proxy")

router = APIRouter(tags=["feedback"])


class FeedbackRequest(BaseModel):
    feedback_id: str = Field(..., description="rag_feedback_id from the response")
    rating: str = Field(..., pattern="^(positive|negative)$")
    correction: str | None = Field(None, description="Corrected answer text")
    comment: str | None = Field(None, description="Expert comment")
    question: str | None = Field(None, description="Original user question")
    answer: str | None = Field(None, description="System answer that was rated")
    contexts: list[str] | None = Field(None, description="Retrieved context chunks")


class FeedbackResponse(BaseModel):
    status: str
    message: str


@router.post("/v1/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    raw_request: Request,
    user: UserContext = Depends(require_role(Role.EXPERT)),  # noqa: B008
) -> FeedbackResponse:
    """Submit feedback on a RAG response."""
    from proxy.app.core.hitl import FeedbackType, get_logger

    start_time = time.time()

    with tracer.start_as_current_span("feedback.submit") as span:
        if span.is_recording():
            span.set_attribute("feedback.id", request.feedback_id)
            span.set_attribute("feedback.rating", request.rating)
            has_correction = request.correction is not None and len(request.correction or "") > 0
            span.set_attribute("feedback.has_correction", has_correction)

        from proxy.app.shared.metrics import record_enrichment, record_feedback

        hlog = get_logger()

        feedback_type = FeedbackType.POSITIVE if request.rating == "positive" else FeedbackType.NEGATIVE

        try:
            hlog.log_feedback(
                request_id=request.feedback_id,
                feedback_type=feedback_type,
                comment=request.comment or "",
                corrected_response=request.correction,
            )
            add_event("feedback.logged")
        except Exception as e:
            logger.error(f"Failed to record feedback: {e}")
            set_span_error(e)
            raise HTTPException(status_code=500, detail=f"Failed to record feedback: {e}") from e

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

        return FeedbackResponse(status="ok", message="Feedback recorded")
