"""
FLARE: Forward-Looking Active REtrieval

Monitors generation confidence and triggers re-retrieval when low-confidence
tokens appear. Based on arxiv:2305.06983

Architecture:
1. Generate initial response
2. Monitor token confidence during generation
3. When confidence drops below threshold:
   a. Pause generation
   b. Use upcoming sentence as query
   c. Retrieve additional context
   d. Resume generation with new context
"""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# FLARE configuration
FLARE_ENABLED = False  # Disabled by default — enable via config
FLARE_CONFIDENCE_THRESHOLD = 0.5  # Trigger re-retrieval below this
FLARE_MAX_RETRIEVALS = 3  # Maximum re-retrievals per response
FLARE_CONTEXT_WINDOW = 500  # Characters to use as query


class FLAREController:
    """
    Controls active retrieval during generation.

    Usage:
        controller = FLAREController(search_fn, rerank_fn)
        response = controller.generate_with_flare(query, initial_context)
    """

    def __init__(
        self,
        search_fn: Callable | None = None,
        rerank_fn: Callable | None = None,
        confidence_threshold: float = 0.5,
        max_retrievals: int = 3,
    ):
        self.search_fn = search_fn
        self.rerank_fn = rerank_fn
        self.confidence_threshold = confidence_threshold
        self.max_retrievals = max_retrievals
        self.retrieval_count = 0

    def should_retrieve(self, token_confidence: float) -> bool:
        """Check if we should trigger re-retrieval based on token confidence."""
        if self.retrieval_count >= self.max_retrievals:
            return False
        return token_confidence < self.confidence_threshold

    def extract_query_from_context(self, context: str) -> str:
        """Extract a query from the upcoming generation context."""
        # Take last N characters as query
        if len(context) > FLARE_CONTEXT_WINDOW:
            return context[-FLARE_CONTEXT_WINDOW:]
        return context

    def retrieve_additional_context(
        self,
        query: str,
        existing_context: list[str],
    ) -> list[str]:
        """Retrieve additional context for the query."""
        if not self.search_fn:
            return []

        try:
            results = self.search_fn(query=query, top_k=3)
            new_contexts = []
            for r in results:
                text = r.payload.get("text", "") if hasattr(r, "payload") else str(r)
                if text and text not in existing_context:
                    new_contexts.append(text)
            self.retrieval_count += 1
            return new_contexts
        except Exception as e:
            logger.warning(f"FLARE re-retrieval failed: {e}")
            return []

    def generate_with_flare(
        self,
        query: str,
        initial_context: list[str],
        generate_fn: Callable | None = None,
        max_tokens: int = 1000,
    ) -> dict[str, Any]:
        """
        Generate response with FLARE active retrieval.

        Returns dict with:
        - response: generated text
        - retrievals: number of re-retrievals performed
        - contexts: all contexts used
        """
        if not FLARE_ENABLED or not generate_fn:
            # Fallback to normal generation
            response = generate_fn(query, initial_context) if generate_fn else ""
            return {
                "response": response,
                "retrievals": 0,
                "contexts": initial_context,
            }

        all_contexts = list(initial_context)
        self.retrieval_count = 0

        # Generate with monitoring
        response = ""
        remaining_query = query

        for _ in range(self.max_retrievals + 1):
            # Generate chunk
            chunk = generate_fn(remaining_query, all_contexts)
            response += chunk

            # Check confidence (simplified — in production, use token-level confidence)
            # For now, use a heuristic: if response is too short, confidence is low
            confidence = min(1.0, len(chunk) / 100)

            if not self.should_retrieve(confidence):
                break

            # Extract query from response for re-retrieval
            retrieval_query = self.extract_query_from_context(response)
            new_contexts = self.retrieve_additional_context(retrieval_query, all_contexts)

            if not new_contexts:
                break

            all_contexts.extend(new_contexts)
            remaining_query = retrieval_query

        return {
            "response": response,
            "retrievals": self.retrieval_count,
            "contexts": all_contexts,
        }
