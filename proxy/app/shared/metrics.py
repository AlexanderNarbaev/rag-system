# proxy/app/metrics.py
"""Prometheus metrics module for RAG proxy observability.
Exposes counters, histograms, and gauges for monitoring.
"""

from typing import Any

import prometheus_client
from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

_initialized = False


def _reuse_metric(name: str, metric_cls: type) -> Any:
    """Return an existing metric with the given name if already registered."""
    registry = prometheus_client.REGISTRY
    for collector in list(registry._collector_to_names):  # noqa: SLF001
        try:
            existing_names = registry._get_names(collector)  # type: ignore[no-untyped-call]
        except Exception:
            continue
        if name in existing_names and isinstance(collector, metric_cls):
            return collector
    return None


rag_requests_total: Any = _reuse_metric("rag_requests_total", Counter) or Counter(
    "rag_requests_total",
    "Total number of RAG requests",
    ["endpoint", "status"],
)

rag_request_duration_seconds: Any = _reuse_metric("rag_request_duration_seconds", Histogram) or Histogram(
    "rag_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

rag_retrieval_duration_seconds: Any = _reuse_metric("rag_retrieval_duration_seconds", Histogram) or Histogram(
    "rag_retrieval_duration_seconds",
    "Retrieval step duration in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

rag_rerank_duration_seconds: Any = _reuse_metric("rag_rerank_duration_seconds", Histogram) or Histogram(
    "rag_rerank_duration_seconds",
    "Rerank step duration in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

rag_llm_duration_seconds: Any = _reuse_metric("rag_llm_duration_seconds", Histogram) or Histogram(
    "rag_llm_duration_seconds",
    "LLM call duration in seconds",
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

rag_cache_hits_total: Any = _reuse_metric("rag_cache_hits_total", Counter) or Counter(
    "rag_cache_hits_total",
    "Total number of cache hits",
)

rag_context_tokens: Any = _reuse_metric("rag_context_tokens", Gauge) or Gauge(
    "rag_context_tokens",
    "Number of context tokens passed to LLM",
)

rag_active_requests: Any = _reuse_metric("rag_active_requests", Gauge) or Gauge(
    "rag_active_requests",
    "Number of currently active requests",
)

# ── Retrieval quality metrics (used by rag-retrieval-quality dashboard) ──

rag_retrieval_chunks_total: Any = _reuse_metric("rag_retrieval_chunks_total", Gauge) or Gauge(
    "rag_retrieval_chunks_total",
    "Number of chunks retrieved in the last query",
)

rag_retrieval_chunks_after_rerank: Any = _reuse_metric("rag_retrieval_chunks_after_rerank", Gauge) or Gauge(
    "rag_retrieval_chunks_after_rerank",
    "Number of chunks remaining after reranking",
)

rag_graph_expansion_rate: Any = _reuse_metric("rag_graph_expansion_rate", Gauge) or Gauge(
    "rag_graph_expansion_rate",
    "Fraction of queries that triggered graph expansion (0-1)",
)

rag_retrieval_mrr: Any = _reuse_metric("rag_retrieval_mrr", Gauge) or Gauge(
    "rag_retrieval_mrr",
    "Mean Reciprocal Rank of retrieval results",
)

rag_confidence_score_high_ratio: Any = _reuse_metric("rag_confidence_score_high_ratio", Gauge) or Gauge(
    "rag_confidence_score_high_ratio",
    "Ratio of responses with confidence score above threshold",
)

rag_grounding_score_high_ratio: Any = _reuse_metric("rag_grounding_score_high_ratio", Gauge) or Gauge(
    "rag_grounding_score_high_ratio",
    "Ratio of responses with grounding score above threshold",
)

rag_compression_ratio: Any = _reuse_metric("rag_compression_ratio", Gauge) or Gauge(
    "rag_compression_ratio",
    "Context compression ratio (compressed / original tokens)",
)

# ── RAG-specific detailed metrics ──

RAG_REQUEST_COUNT: Any = _reuse_metric("rag_request_total", Counter) or Counter(
    "rag_request_total",
    "Total RAG requests",
    ["method", "status", "has_context"],
)

RAG_LATENCY: Any = _reuse_metric("rag_rag_latency_seconds", Histogram) or Histogram(
    "rag_rag_latency_seconds",
    "RAG request latency",
    ["operation"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

RAG_RETRIEVAL_SCORES: Any = _reuse_metric("rag_retrieval_scores", Histogram) or Histogram(
    "rag_retrieval_scores",
    "Distribution of retrieval scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

RAG_CACHE_HITS: Any = _reuse_metric("rag_cache_hits_total_v2", Counter) or Counter(
    "rag_cache_hits_total_v2",
    "Cache hit count",
    ["cache_type"],
)

RAG_CACHE_MISSES: Any = _reuse_metric("rag_cache_misses_total", Counter) or Counter(
    "rag_cache_misses_total",
    "Cache miss count",
    ["cache_type"],
)

RAG_QUEUE_DEPTH: Any = _reuse_metric("rag_queue_depth", Gauge) or Gauge(
    "rag_queue_depth",
    "Current request queue depth",
)

RAG_LLM_TOKENS: Any = _reuse_metric("rag_llm_tokens_total", Counter) or Counter(
    "rag_llm_tokens_total",
    "LLM token usage",
    ["direction"],  # prompt, completion
)

RAG_CONFIDENCE: Any = _reuse_metric("rag_confidence_score", Histogram) or Histogram(
    "rag_confidence_score",
    "RAG confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

RAG_HALLUCINATION_DETECTED: Any = _reuse_metric("rag_hallucination_detected_total", Counter) or Counter(
    "rag_hallucination_detected_total",
    "Hallucination detection events",
)

RAG_NEGATIVE_REJECTION: Any = _reuse_metric("rag_negative_rejection_total", Counter) or Counter(
    "rag_negative_rejection_total",
    "Negative rejection events (refused to answer)",
)

# ── Auth metrics ──

RAG_AUTH_LOGIN_TOTAL: Any = _reuse_metric("rag_auth_login_total", Counter) or Counter(
    "rag_auth_login_total",
    "Total login attempts",
    ["status", "method"],
)

RAG_AUTH_REGISTER_TOTAL: Any = _reuse_metric("rag_auth_register_total", Counter) or Counter(
    "rag_auth_register_total",
    "Total registration attempts",
    ["status"],
)

RAG_AUTH_REFRESH_TOTAL: Any = _reuse_metric("rag_auth_refresh_total", Counter) or Counter(
    "rag_auth_refresh_total",
    "Total token refresh attempts",
    ["status"],
)

RAG_AUTH_LOGOUT_TOTAL: Any = _reuse_metric("rag_auth_logout_total", Counter) or Counter(
    "rag_auth_logout_total",
    "Total logout operations",
)

RAG_AUTH_RATE_LIMIT_TOTAL: Any = _reuse_metric("rag_auth_rate_limit_total", Counter) or Counter(
    "rag_auth_rate_limit_total",
    "Rate limit hits for auth operations",
    ["endpoint"],
)

# ── Feedback metrics ──

RAG_FEEDBACK_TOTAL: Any = _reuse_metric("rag_feedback_total", Counter) or Counter(
    "rag_feedback_total",
    "Total feedback submissions",
    ["rating"],
)

RAG_FEEDBACK_PROCESSING_SECONDS: Any = _reuse_metric("rag_feedback_processing_seconds", Histogram) or Histogram(
    "rag_feedback_processing_seconds",
    "Feedback processing duration",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

RAG_ENRICHMENT_TOTAL: Any = _reuse_metric("rag_enrichment_total", Counter) or Counter(
    "rag_enrichment_total",
    "Self-enrichment operations triggered",
    ["status"],
)

# ── File operation metrics ──

RAG_FILE_UPLOAD_TOTAL: Any = _reuse_metric("rag_file_upload_total", Counter) or Counter(
    "rag_file_upload_total",
    "Total file uploads",
    ["status"],
)

RAG_FILE_UPLOAD_BYTES: Any = _reuse_metric("rag_file_upload_bytes", Histogram) or Histogram(
    "rag_file_upload_bytes",
    "File upload size distribution (bytes)",
    buckets=(1024, 10240, 102400, 1048576, 10485760, 52428800, 104857600),
)

RAG_FILE_DOWNLOAD_TOTAL: Any = _reuse_metric("rag_file_download_total", Counter) or Counter(
    "rag_file_download_total",
    "Total file downloads",
    ["status"],
)

RAG_FILE_DELETE_TOTAL: Any = _reuse_metric("rag_file_delete_total", Counter) or Counter(
    "rag_file_delete_total",
    "Total file deletions",
    ["status"],
)

RAG_FILE_LIST_TOTAL: Any = _reuse_metric("rag_file_list_total", Counter) or Counter(
    "rag_file_list_total",
    "Total file list requests",
)

RAG_FILE_PRESIGNED_TOTAL: Any = _reuse_metric("rag_file_presigned_total", Counter) or Counter(
    "rag_file_presigned_total",
    "Total presigned URL generations",
    ["status"],
)

# ── Admin operation metrics ──

RAG_ADMIN_OPERATIONS_TOTAL: Any = _reuse_metric("rag_admin_operations_total", Counter) or Counter(
    "rag_admin_operations_total",
    "Total admin operations",
    ["operation", "status"],
)

RAG_TRAINING_JOBS_TOTAL: Any = _reuse_metric("rag_training_jobs_total", Counter) or Counter(
    "rag_training_jobs_total",
    "Total training jobs",
    ["trainer_type", "status"],
)

RAG_WARMUP_STATUS: Any = _reuse_metric("rag_warmup_status", Gauge) or Gauge(
    "rag_warmup_status",
    "Warm-up status (1=completed, 0=not started, -1=failed)",
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


# ── Auth helper functions ──


def record_auth_login(status: str, method: str = "local") -> None:
    """Record login attempt."""
    RAG_AUTH_LOGIN_TOTAL.labels(status=status, method=method).inc()


def record_auth_register(status: str) -> None:
    """Record registration attempt."""
    RAG_AUTH_REGISTER_TOTAL.labels(status=status).inc()


def record_auth_refresh(status: str) -> None:
    """Record token refresh attempt."""
    RAG_AUTH_REFRESH_TOTAL.labels(status=status).inc()


def record_auth_logout() -> None:
    """Record logout operation."""
    RAG_AUTH_LOGOUT_TOTAL.inc()


def record_auth_rate_limit(endpoint: str) -> None:
    """Record auth rate limit hit."""
    RAG_AUTH_RATE_LIMIT_TOTAL.labels(endpoint=endpoint).inc()


# ── Feedback helper functions ──


def record_feedback(rating: str, duration: float | None = None) -> None:
    """Record feedback submission."""
    RAG_FEEDBACK_TOTAL.labels(rating=rating).inc()
    if duration is not None:
        RAG_FEEDBACK_PROCESSING_SECONDS.observe(duration)


def record_enrichment(status: str) -> None:
    """Record self-enrichment operation."""
    RAG_ENRICHMENT_TOTAL.labels(status=status).inc()


# ── File operation helper functions ──


def record_file_upload(status: str, size_bytes: int = 0) -> None:
    """Record file upload."""
    RAG_FILE_UPLOAD_TOTAL.labels(status=status).inc()
    if size_bytes > 0:
        RAG_FILE_UPLOAD_BYTES.observe(size_bytes)


def record_file_download(status: str) -> None:
    """Record file download."""
    RAG_FILE_DOWNLOAD_TOTAL.labels(status=status).inc()


def record_file_delete(status: str) -> None:
    """Record file deletion."""
    RAG_FILE_DELETE_TOTAL.labels(status=status).inc()


def record_file_list() -> None:
    """Record file list request."""
    RAG_FILE_LIST_TOTAL.inc()


def record_file_presigned(status: str) -> None:
    """Record presigned URL generation."""
    RAG_FILE_PRESIGNED_TOTAL.labels(status=status).inc()


# ── Admin helper functions ──


def record_admin_operation(operation: str, status: str) -> None:
    """Record admin operation."""
    RAG_ADMIN_OPERATIONS_TOTAL.labels(operation=operation, status=status).inc()


def record_training_job(trainer_type: str, status: str) -> None:
    """Record training job."""
    RAG_TRAINING_JOBS_TOTAL.labels(trainer_type=trainer_type, status=status).inc()


def set_canary_split(model_name: str, ratio: float) -> None:
    """Set canary split gauge for a model."""
    from proxy.app.model_evolution.canary_controller import canary_split_ratio

    canary_split_ratio.labels(model=model_name).set(ratio)


def set_warmup_status(status_value: int) -> None:
    """Set warm-up status gauge (1=completed, 0=not started, -1=failed)."""
    RAG_WARMUP_STATUS.set(status_value)


def init_metrics() -> None:
    global _initialized
    _initialized = True


def metrics_endpoint() -> Response:
    """Returns Prometheus-formatted metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def is_initialized() -> bool:
    return _initialized
