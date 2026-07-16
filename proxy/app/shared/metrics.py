# proxy/app/metrics.py
"""Prometheus metrics module for RAG proxy observability.
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

# ── RAG-specific detailed metrics ──

RAG_REQUEST_COUNT = Counter(
    "rag_request_total",
    "Total RAG requests",
    ["method", "status", "has_context"],
)

RAG_LATENCY = Histogram(
    "rag_rag_latency_seconds",
    "RAG request latency",
    ["operation"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

RAG_RETRIEVAL_SCORES = Histogram(
    "rag_retrieval_scores",
    "Distribution of retrieval scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

RAG_CACHE_HITS = Counter(
    "rag_cache_hits_total_v2",
    "Cache hit count",
    ["cache_type"],
)

RAG_CACHE_MISSES = Counter(
    "rag_cache_misses_total",
    "Cache miss count",
    ["cache_type"],
)

RAG_QUEUE_DEPTH = Gauge(
    "rag_queue_depth",
    "Current request queue depth",
)

RAG_LLM_TOKENS = Counter(
    "rag_llm_tokens_total",
    "LLM token usage",
    ["direction"],  # prompt, completion
)

RAG_CONFIDENCE = Histogram(
    "rag_confidence_score",
    "RAG confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

RAG_HALLUCINATION_DETECTED = Counter(
    "rag_hallucination_detected_total",
    "Hallucination detection events",
)

RAG_NEGATIVE_REJECTION = Counter(
    "rag_negative_rejection_total",
    "Negative rejection events (refused to answer)",
)


# ── Helper functions ──


def record_rag_request(method: str, status: str, has_context: bool, duration: float) -> None:
    """Record RAG request metrics."""
    RAG_REQUEST_COUNT.labels(method=method, status=status, has_context=str(has_context)).inc()
    RAG_LATENCY.labels(operation="total").observe(duration)


def record_retrieval(score: float, duration: float) -> None:
    """Record retrieval metrics."""
    RAG_RETRIEVAL_SCORES.observe(score)
    RAG_LATENCY.labels(operation="retrieval").observe(duration)


def record_cache_hit(cache_type: str) -> None:
    """Record cache hit."""
    RAG_CACHE_HITS.labels(cache_type=cache_type).inc()


def record_cache_miss(cache_type: str) -> None:
    """Record cache miss."""
    RAG_CACHE_MISSES.labels(cache_type=cache_type).inc()


def set_queue_depth(depth: int) -> None:
    """Set current request queue depth."""
    RAG_QUEUE_DEPTH.set(depth)


def record_llm_tokens(prompt_tokens: int, completion_tokens: int) -> None:
    """Record LLM token usage."""
    RAG_LLM_TOKENS.labels(direction="prompt").inc(prompt_tokens)
    RAG_LLM_TOKENS.labels(direction="completion").inc(completion_tokens)


def record_confidence(score: float) -> None:
    """Record confidence score."""
    RAG_CONFIDENCE.observe(score)


def record_hallucination() -> None:
    """Record hallucination detection."""
    RAG_HALLUCINATION_DETECTED.inc()


def record_negative_rejection() -> None:
    """Record negative rejection."""
    RAG_NEGATIVE_REJECTION.inc()


def init_metrics() -> None:
    global _initialized
    _initialized = True


def metrics_endpoint() -> Response:
    """Returns Prometheus-formatted metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def is_initialized() -> bool:
    return _initialized
