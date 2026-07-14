# proxy/app/api/feedback.py
"""Expert feedback endpoint for HITL quality control."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from proxy.app.auth import UserContext
from proxy.app.auth.rbac import Role, require_role

logger = logging.getLogger ("rag-proxy")

router = APIRouter (tags = ["feedback"])


class FeedbackRequest (BaseModel):
  feedback_id: str = Field (..., description = "rag_feedback_id from the response")
  rating: str = Field (..., pattern = "^(positive|negative)$")
  correction: str | None = Field (None, description = "Corrected answer text")
  comment: str | None = Field (None, description = "Expert comment")
  question: str | None = Field (None, description = "Original user question")
  answer: str | None = Field (None, description = "System answer that was rated")
  contexts: list [str] | None = Field (None, description = "Retrieved context chunks")


class FeedbackResponse (BaseModel):
  status: str
  message: str


@router.post ("/v1/feedback", response_model = FeedbackResponse)
async def submit_feedback (
    request: FeedbackRequest, raw_request: Request, user: UserContext = Depends (require_role (Role.EXPERT)),
    # noqa: B008
) -> FeedbackResponse:
  """Submit feedback on a RAG response."""
  from proxy.app.core.hitl import FeedbackType, get_logger
  
  hlog = get_logger ()
  
  feedback_type = FeedbackType.POSITIVE if request.rating == "positive" else FeedbackType.NEGATIVE
  
  try:
    hlog.log_feedback (request_id = request.feedback_id, feedback_type = feedback_type, comment = request.comment or "",
        corrected_response = request.correction, )
    
    # Compute RAGAS evaluation metrics when question and contexts are available
    ragas_scores = None
    if request.contexts and request.question:
      from proxy.app.core.ragas_eval import evaluate_rag_response
      
      ragas_scores = evaluate_rag_response (question = request.question, answer = request.answer or "",
          contexts = request.contexts, )
      logger.info (f"RAGAS scores for feedback {request.feedback_id}: {ragas_scores}")
    
    from proxy.app.shared.config import ENRICHMENT_ENABLED
    
    if ENRICHMENT_ENABLED and (request.rating == "positive" or request.correction):
      try:
        from proxy.app.core.enricher import enrich_from_feedback
        
        await enrich_from_feedback (request)
      except Exception as e:
        logger.error (f"Enrichment failed (non-blocking): {e}")
    
    return FeedbackResponse (status = "ok", message = "Feedback recorded")
  except Exception as e:
    logger.error (f"Failed to record feedback: {e}")
    raise HTTPException (status_code = 500, detail = f"Failed to record feedback: {e}") from e
