# proxy/app/metrics.py
"""
Prometheus metrics module for RAG proxy observability.
Exposes counters, histograms, and gauges for monitoring.
"""

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

_initialized = False

rag_requests_total = Counter(
    "rag_requests_total",
    "Total number of RAG requests",
    ["endpoint", "status"],
)

rag_request_duration_seconds = Histogram(
    "rag_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

rag_retrieval_duration_seconds = Histogram(
    "rag_retrieval_duration_seconds",
    "Retrieval step duration in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

rag_rerank_duration_seconds = Histogram(
    "rag_rerank_duration_seconds",
    "Rerank step duration in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

rag_llm_duration_seconds = Histogram(
    "rag_llm_duration_seconds",
    "LLM call duration in seconds",
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

rag_cache_hits_total = Counter(
    "rag_cache_hits_total",
    "Total number of cache hits",
)

rag_context_tokens = Gauge(
    "rag_context_tokens",
    "Number of context tokens passed to LLM",
)

rag_active_requests = Gauge(
    "rag_active_requests",
    "Number of currently active requests",
)

# ── Retrieval quality metrics (used by rag-retrieval-quality dashboard) ──

rag_retrieval_chunks_total = Gauge(
    "rag_retrieval_chunks_total",
    "Number of chunks retrieved in the last query",
)

rag_retrieval_chunks_after_rerank = Gauge(
    "rag_retrieval_chunks_after_rerank",
    "Number of chunks remaining after reranking",
)

rag_graph_expansion_rate = Gauge(
    "rag_graph_expansion_rate",
    "Fraction of queries that triggered graph expansion (0-1)",
)

rag_retrieval_mrr = Gauge(
    "rag_retrieval_mrr",
    "Mean Reciprocal Rank of retrieval results",
)

rag_confidence_score_high_ratio = Gauge(
    "rag_confidence_score_high_ratio",
    "Ratio of responses with confidence score above threshold",
)

rag_grounding_score_high_ratio = Gauge(
    "rag_grounding_score_high_ratio",
    "Ratio of responses with grounding score above threshold",
)

rag_compression_ratio = Gauge(
    "rag_compression_ratio",
    "Context compression ratio (compressed / original tokens)",
)


def init_metrics() -> None:
    global _initialized
    _initialized = True


def metrics_endpoint() -> Response:
    """Returns Prometheus-formatted metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def is_initialized() -> bool:
    return _initialized
