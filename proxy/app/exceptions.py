# proxy/app/exceptions.py
"""
Custom exception hierarchy for RAG system.

Provides typed exceptions for better error handling, logging, and graceful degradation.
Allows catch blocks to use specific exception types instead of generic Exception.
"""


class RAGError(Exception):
    """Base exception for all RAG system errors."""

    def __init__(self, message: str = "", component: str = "", recoverable: bool = True):
        super().__init__(message)
        self.component = component
        self.recoverable = recoverable


class RetrievalError(RAGError):
    """Errors during retrieval (Qdrant search failures, empty results)."""

    def __init__(self, message: str = "", component: str = "retrieval"):
        super().__init__(message, component=component, recoverable=True)


class RerankError(RAGError):
    """Errors during reranking (cross-encoder failures)."""

    def __init__(self, message: str = "", component: str = "rerank"):
        super().__init__(message, component=component, recoverable=True)


class LLMError(RAGError):
    """Errors from the LLM backend (timeout, model unavailable, bad response)."""

    def __init__(self, message: str = "", component: str = "llm"):
        super().__init__(message, component=component, recoverable=True)


class GraphError(RAGError):
    """Errors from Neo4j / graph expansion."""

    def __init__(self, message: str = "", component: str = "graph"):
        super().__init__(message, component=component, recoverable=True)


class CacheError(RAGError):
    """Errors from Redis / caching layer."""

    def __init__(self, message: str = "", component: str = "cache"):
        super().__init__(message, component=component, recoverable=True)


class EmbeddingError(RAGError):
    """Errors during embedding generation."""

    def __init__(self, message: str = "", component: str = "embedder"):
        super().__init__(message, component=component, recoverable=True)


class ConfigError(RAGError):
    """Configuration or environment errors (missing required vars, invalid values)."""

    def __init__(self, message: str = "", component: str = "config"):
        super().__init__(message, component=component, recoverable=False)


class RateLimitError(RAGError):
    """Rate limit exceeded."""

    def __init__(self, message: str = "", component: str = "rate_limiter"):
        super().__init__(message, component=component, recoverable=True)


class AuthError(RAGError):
    """Authentication or authorization errors."""

    def __init__(self, message: str = "", component: str = "auth"):
        super().__init__(message, component=component, recoverable=False)


class ContextError(RAGError):
    """Errors during context grounding or assembly (cosine similarity, embedding mismatch)."""

    def __init__(self, message: str = "", component: str = "context"):
        super().__init__(message, component=component, recoverable=True)


class ContextBuildError(RAGError):
    """Errors during context assembly."""

    def __init__(self, message: str = "", component: str = "context_builder"):
        super().__init__(message, component=component, recoverable=True)


class RerankerError(RAGError):
    """Errors during reranking (cross-encoder failures). Kept as alias for RerankError."""

    def __init__(self, message: str = "", component: str = "reranker"):
        super().__init__(message, component=component, recoverable=True)


class ValidationError(RAGError):
    """Input validation errors."""

    def __init__(self, message: str = "", component: str = "validation"):
        super().__init__(message, component=component, recoverable=False)


class SecurityError(RAGError):
    """Security violations — unauthorized access, injection attempts, policy violations."""

    def __init__(self, message: str = "", component: str = "security"):
        super().__init__(message, component=component, recoverable=False)
