# proxy/app/metrics.py
"""
Prometheus metrics module for RAG proxy observability.
Exposes counters, histograms, and gauges for monitoring.
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

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


def init_metrics():
    global _initialized
    _initialized = True


def metrics_endpoint():
    """Returns Prometheus-formatted metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def is_initialized() -> bool:
    return _initialized
