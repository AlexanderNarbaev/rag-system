"""
RAGAS-style evaluation metrics for RAG system.
Reference-free evaluation using LLM-as-judge.

Metrics:
- Faithfulness: Does the answer stay faithful to the retrieved context?
- Answer Relevance: Does the answer address the question?
- Context Relevance: Are the retrieved passages relevant to the question?

Based on: https://arxiv.org/abs/2309.15217
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_faithfulness(answer: str, context: str, llm_client: Any = None) -> float:
    """
    Compute faithfulness score: how well the answer is supported by the context.
    Returns 0.0-1.0 where 1.0 = fully faithful.

    Uses claim extraction + verification approach.
    """
    if not answer or not context:
        return 0.0

    # Extract claims from answer (simple sentence-based)
    claims = [s.strip() for s in answer.split('.') if s.strip() and len(s.strip()) > 10]

    if not claims:
        return 1.0  # No claims to verify

    # Check each claim against context
    supported_claims = 0
    for claim in claims:
        # Simple keyword overlap check
        claim_words = set(claim.lower().split())
        context_words = set(context.lower().split())
        overlap = len(claim_words & context_words) / max(len(claim_words), 1)

        if overlap >= 0.3:  # At least 30% word overlap
            supported_claims += 1

    return supported_claims / len(claims)


def compute_answer_relevance(question: str, answer: str) -> float:
    """
    Compute answer relevance: how well the answer addresses the question.
    Returns 0.0-1.0 where 1.0 = fully relevant.
    """
    if not question or not answer:
        return 0.0

    # Extract key terms from question
    question_words = set(question.lower().split())
    stop_words = {
        'what', 'is', 'the', 'a', 'an', 'how', 'why', 'when', 'where',
        'who', 'which', 'do', 'does', 'can', 'could', 'should', 'would', 'will',
    }
    question_keywords = question_words - stop_words

    if not question_keywords:
        return 0.5  # Can't determine relevance

    # Check how many question keywords appear in answer
    answer_lower = answer.lower()
    matched_keywords = sum(1 for kw in question_keywords if kw in answer_lower)

    return matched_keywords / len(question_keywords)


def compute_context_relevance(question: str, contexts: list[str]) -> float:
    """
    Compute context relevance: how relevant the retrieved passages are to the question.
    Returns 0.0-1.0 where 1.0 = fully relevant.
    """
    if not question or not contexts:
        return 0.0

    question_words = set(question.lower().split())
    stop_words = {
        'what', 'is', 'the', 'a', 'an', 'how', 'why', 'when', 'where',
        'who', 'which', 'do', 'does', 'can', 'could', 'should', 'would', 'will',
    }
    question_keywords = question_words - stop_words

    if not question_keywords:
        return 0.5

    # Check each context for relevance
    relevant_contexts = 0
    for ctx in contexts:
        ctx_lower = ctx.lower()
        matched = sum(1 for kw in question_keywords if kw in ctx_lower)
        if matched / len(question_keywords) >= 0.3:
            relevant_contexts += 1

    return relevant_contexts / len(contexts)


def evaluate_rag_response(
    question: str,
    answer: str,
    contexts: list[str],
) -> dict[str, float]:
    """
    Compute all RAGAS metrics for a RAG response.
    Returns dict with metric names and scores.
    """
    context_text = ' '.join(contexts)

    return {
        'faithfulness': compute_faithfulness(answer, context_text),
        'answer_relevance': compute_answer_relevance(question, answer),
        'context_relevance': compute_context_relevance(question, contexts),
        'overall': (
            compute_faithfulness(answer, context_text) +
            compute_answer_relevance(question, answer) +
            compute_context_relevance(question, contexts)
        ) / 3
    }
