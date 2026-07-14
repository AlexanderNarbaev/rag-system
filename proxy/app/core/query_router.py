"""
Adaptive Query Routing

Classifies queries by complexity and routes to appropriate retrieval strategy:
- Simple: no retrieval needed (FAQ, greetings)
- Moderate: single-step RAG
- Complex: multi-step iterative RAG

Based on: Adaptive-RAG (arxiv:2403.14403)

Expected impact: 40-60% latency reduction for simple queries.
"""

import logging
import re
from typing import Any, Literal

logger = logging.getLogger (__name__)


class QueryComplexityRouter:
  """
  Route queries based on complexity level.

  Classification:
  - direct: Simple queries that don't need retrieval (greetings, FAQ)
  - single: Moderate queries needing single-step RAG
  - multi: Complex queries needing multi-step iterative RAG

  Usage:
      router = QueryComplexityRouter()
      strategy = router.classify("What is RAG?")  # Returns "single"
      strategy = router.classify("Hello")  # Returns "direct"
  """
  
  # Patterns for direct (no-retrieval) queries
  DIRECT_PATTERNS = [
      r"^(hi|hello|hey|good morning|good afternoon|good evening)\b", r"^(thank|thanks|thank you)\b",
      r"^(yes|no|ok|okay|sure)\b", r"^(bye|goodbye|see you)\b", r"^(what time|what date|what day)\b",
      r"^(how are you|how do you do)\b", r"^(help|menu|options)\b",
  ]
  
  # Patterns for complex (multi-step) queries
  COMPLEX_PATTERNS = [
      r"compare.*and.*", r"contrast.*with.*", r"what are the differences between.*and.*", r"analyze.*and.*explain.*",
      r"step by step.*", r"first.*then.*finally.*", r"explain the relationship between.*and.*", r"how does.*affect.*",
      r"what would happen if.*", r"pros and cons.*", r"advantages and disadvantages.*",
  ]
  
  # Keywords that suggest retrieval is needed
  RETRIEVAL_KEYWORDS = [
      "document", "documentation", "guide", "manual", "specification", "config", "configuration", "setting",
      "parameter", "option", "error", "issue", "problem", "bug", "fix", "solution", "how to", "how do", "how can",
      "what is", "what are", "explain", "describe", "define", "meaning", "example", "sample", "template", "pattern",
      "version", "release", "changelog", "update",
  ]
  
  def classify (self, query: str) -> Literal ["direct", "single", "multi"]:
    """
    Classify query complexity.

    Returns:
        "direct" - no retrieval needed
        "single" - single-step RAG
        "multi" - multi-step iterative RAG
    """
    query_lower = query.lower ().strip ()
    
    # Check for direct patterns (no retrieval needed)
    for pattern in self.DIRECT_PATTERNS:
      if re.match (pattern, query_lower):
        logger.debug (f"Query classified as 'direct': {query [:50]}...")
        return "direct"
    
    # Check for complex patterns
    for pattern in self.COMPLEX_PATTERNS:
      if re.search (pattern, query_lower):
        logger.debug (f"Query classified as 'multi': {query [:50]}...")
        return "multi"
    
    # Check query length and keyword presence
    words = query_lower.split ()
    
    # Very short queries are likely simple
    if len (words) <= 3:
      # But check if they contain retrieval keywords
      has_retrieval_keyword = any (kw in query_lower for kw in self.RETRIEVAL_KEYWORDS)
      if not has_retrieval_keyword:
        logger.debug (f"Query classified as 'direct' (short, no keywords): {query [:50]}...")
        return "direct"
    
    # Check for question words + retrieval keywords
    question_words = {"what", "how", "why", "when", "where", "who", "which"}
    has_question_word = any (w in words for w in question_words)
    has_retrieval_keyword = any (kw in query_lower for kw in self.RETRIEVAL_KEYWORDS)
    
    if has_question_word and has_retrieval_keyword:
      # Moderate complexity - single RAG step
      logger.debug (f"Query classified as 'single': {query [:50]}...")
      return "single"
    
    # Default to single for most queries
    logger.debug (f"Query classified as 'single' (default): {query [:50]}...")
    return "single"
  
  def get_retrieval_params (
      self, complexity: Literal ["direct", "single", "multi"], ) -> dict [str, Any]:
    """
    Get retrieval parameters for the complexity level.

    Returns dict with:
    - retrieve: whether to retrieve
    - top_k: number of results to retrieve
    - rerank: whether to rerank
    - max_iterations: max retrieval iterations (for multi)
    """
    if complexity == "direct":
      return {
          "retrieve": False, "top_k": 0, "rerank": False, "max_iterations": 0,
      }
    elif complexity == "single":
      return {
          "retrieve": True, "top_k": 10, "rerank": True, "max_iterations": 1,
      }
    else:  # multi
      return {
          "retrieve": True, "top_k": 15, "rerank": True, "max_iterations": 3,
      }


# Global router instance
_query_router = QueryComplexityRouter ()


def get_query_router () -> QueryComplexityRouter:
  """Get the global query complexity router."""
  return _query_router
