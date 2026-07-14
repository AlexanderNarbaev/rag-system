# proxy/app/shared/__init__.py
"""Shared kernel — config, cache, metrics, logging, middleware, exceptions, utils."""

from proxy.app.shared.cache import CacheManager
from proxy.app.shared.config import (
  AUTH_ENABLED, COLLECTION_NAME, CORS_ORIGINS, GRAPH_ENABLED, LLM_ENDPOINT, LLM_MODEL_NAME, QDRANT_HOST, QDRANT_PORT,
  REDIS_URL, USE_LANGGRAPH, USE_REDIS,
)
from proxy.app.shared.exceptions import (
  AuthError, CacheError, ConfigError, ContextBuildError, EmbeddingError, GraphError, LLMError, RAGError, RateLimitError,
  RerankError, RetrievalError, SecurityError, ValidationError,
)
from proxy.app.shared.logging import setup_logging
from proxy.app.shared.metrics import init_metrics, metrics_endpoint
from proxy.app.shared.middleware import add_cors_middleware, setup_all_middleware
from proxy.app.shared.utils import compute_hash, estimate_tokens, generate_request_id

__all__ = [
    # config
    "AUTH_ENABLED", "COLLECTION_NAME", "CORS_ORIGINS", "GRAPH_ENABLED", "LLM_ENDPOINT", "LLM_MODEL_NAME", "QDRANT_HOST",
    "QDRANT_PORT", "REDIS_URL", "USE_LANGGRAPH", "USE_REDIS", # cache
    "CacheManager", # exceptions
    "AuthError", "CacheError", "ConfigError", "ContextBuildError", "EmbeddingError", "GraphError", "LLMError",
    "RAGError", "RateLimitError", "RerankError", "RetrievalError", "SecurityError", "ValidationError", # logging
    "setup_logging", # metrics
    "init_metrics", "metrics_endpoint", # middleware
    "add_cors_middleware", "setup_all_middleware", # utils
    "compute_hash", "estimate_tokens", "generate_request_id",
]
