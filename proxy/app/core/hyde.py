"""HyDE (Hypothetical Document Embeddings) pipeline for query expansion.

Generates a hypothetical answer using SLM, embeds it, and uses the
embedding to search Qdrant for relevant chunks. Falls back to direct
query embedding when SLM is unavailable (no-op HyDE).

Reference: "Precise Zero-Shot Dense Retrieval without Relevance Labels"
(HyDE paper, Gao et al., 2023)
"""

import logging
from typing import Any

from proxy.app.core.retrieval import embedder, hybrid_search
from proxy.app.llm.slm import _call_slm_sync
from proxy.app.shared.config import HYDE_ENABLED, MAX_CHUNKS_RETRIEVAL

logger = logging.getLogger (__name__)


def generate_hypothetical_answer (query: str) -> str:
  """Generate a short hypothetical answer to the query using SLM.

  Uses the SLM to create a plausible answer that captures the expected
  content and terminology of relevant documents. This hypothetical
  document is then embedded for retrieval.

  Args:
      query: The user's question.

  Returns:
      A hypothetical answer string, or the original query on failure.
  """
  if not query or not query.strip ():
    return ""

  prompt = (f"Write a short paragraph that answers the following question. "
            f"Use technical terminology and concrete details. Keep it under 3 sentences.\n\n"
            f"Question: {query}\n\n"
            f"Answer:")

  try:
    result = _call_slm_sync (prompt, max_tokens = 150, temperature = 0.3)
    if result and result.strip ():
      logger.info (f"HyDE generated hypothetical answer ({len (result)} chars)")
      return result.strip ()
    logger.warning ("HyDE SLM returned empty result, falling back to original query")
    return query
  except Exception as e:
    logger.warning (f"HyDE generation failed: {e}, falling back to original query")
    return query


def embed_hypothetical (hypothesis: str) -> list [float]:
  """Embed a hypothetical answer using bge-m3.

  Args:
      hypothesis: The hypothetical answer text.

  Returns:
      A dense embedding vector as a list of floats, or empty list on failure.
  """
  if not hypothesis or not hypothesis.strip ():
    return []

  if embedder is None:
    logger.warning ("Embedder not initialized, cannot embed hypothesis")
    return []

  try:
    vec = embedder.encode (hypothesis, normalize_embeddings = True).tolist ()
    logger.debug (f"HyDE embedded hypothesis: {len (vec)}-dim")
    return [float (x) for x in vec]
  except Exception as e:
    logger.warning (f"HyDE embedding failed: {e}")
    return []


def hyde_search (
    query: str, version: str | None = None, top_k: int | None = None, ) -> list [Any]:
  """Full HyDE pipeline: generate hypothetical answer, embed it, search Qdrant.

  Args:
      query: The original user question.
      version: Optional document version filter.
      top_k: Number of results to return (defaults to MAX_CHUNKS_RETRIEVAL).

  Returns:
      List of Qdrant ScoredPoint objects (or dicts). Empty list on failure.
  """
  if top_k is None:
    top_k = MAX_CHUNKS_RETRIEVAL

  if not HYDE_ENABLED:
    logger.debug ("HyDE disabled, using direct query search")
    hypothesis = query
  else:
    hypothesis = generate_hypothetical_answer (query)

  try:
    # Embed the hypothesis (or original query as fallback)
    hyp_vec = embed_hypothetical (hypothesis)

    # If HyDE embedding failed, fall back to direct query search
    if not hyp_vec:
      logger.debug ("HyDE embedding empty, using hybrid_search directly")
      return hybrid_search (query = query, version = version, top_k = top_k)

    # Use the hypothetical embedding for dense search
    # We bypass the normal hybrid_search flow to use our custom embedding
    from proxy.app.core.retrieval import COLLECTION_NAME, qdrant_client  # type: ignore[attr-defined]

    if qdrant_client is None:
      from proxy.app.core.retrieval import initialize_retrieval

      initialize_retrieval ()

    try:
      from qdrant_client.http import models  # noqa: F811
    except ImportError:
      logger.warning ("Qdrant client not available for HyDE search")
      return hybrid_search (query = query, version = version, top_k = top_k)

    # Build version filter if needed
    filter_conditions: list [Any] = []
    if version:
      filter_conditions.append (models.FieldCondition (key = "version", match = models.MatchValue (value = version)))
    q_filter = models.Filter (must = filter_conditions) if filter_conditions else None

    # Dense search with hypothetical embedding
    assert qdrant_client is not None, "qdrant_client must be initialized"
    from proxy.app.core.retrieval import _get_dense_vector_name  # type: ignore[attr-defined]

    _dense_vector_name = _get_dense_vector_name (qdrant_client)
    response = qdrant_client.query_points (collection_name = COLLECTION_NAME, query = hyp_vec,
        using = _dense_vector_name, limit = top_k, query_filter = q_filter, with_payload = True, )
    results = response.points

    logger.info (f"HyDE search returned {len (results)} chunks for query: '{query [:60]}...'")
    return results

  except Exception as e:
    logger.warning (f"HyDE search failed: {e}, falling back to direct search")
    try:
      return hybrid_search (query = query, version = version, top_k = top_k)
    except Exception:
      return []
