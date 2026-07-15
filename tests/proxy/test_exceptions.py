"""Tests for proxy/app/exceptions.py — custom exception hierarchy."""

from proxy.app.shared.exceptions import (
  AuthError,
  CacheError,
  ConfigError,
  ContextBuildError,
  EmbeddingError,
  GraphError,
  LLMError,
  RAGError,
  RateLimitError,
  RerankError,
  RetrievalError,
  ValidationError,
)


class TestRAGError:
  """Tests for the base RAGError and its subclasses."""

  def test_base_rag_error_defaults (self):
    err = RAGError ("test message")
    assert str (err) == "test message"
    assert err.component == ""
    assert err.recoverable is True

  def test_base_rag_error_with_component (self):
    err = RAGError ("failed", component = "test-comp", recoverable = False)
    assert err.component == "test-comp"
    assert err.recoverable is False

  def test_retrieval_error (self):
    err = RetrievalError ("search timeout")
    assert isinstance (err, RAGError)
    assert err.component == "retrieval"
    assert err.recoverable is True
    assert "search timeout" in str (err)

  def test_rerank_error (self):
    err = RerankError ("cross-encoder OOM")
    assert isinstance (err, RAGError)
    assert err.component == "rerank"
    assert err.recoverable is True

  def test_llm_error (self):
    err = LLMError ("model unavailable")
    assert isinstance (err, RAGError)
    assert err.component == "llm"
    assert err.recoverable is True

  def test_graph_error (self):
    err = GraphError ("neo4j timeout")
    assert isinstance (err, RAGError)
    assert err.component == "graph"
    assert err.recoverable is True

  def test_cache_error (self):
    err = CacheError ("redis connection refused")
    assert isinstance (err, RAGError)
    assert err.component == "cache"
    assert err.recoverable is True

  def test_embedding_error (self):
    err = EmbeddingError ("embedder not loaded")
    assert isinstance (err, RAGError)
    assert err.component == "embedder"
    assert err.recoverable is True

  def test_config_error (self):
    err = ConfigError ("missing required env var")
    assert isinstance (err, RAGError)
    assert err.component == "config"
    assert err.recoverable is False

  def test_rate_limit_error (self):
    err = RateLimitError ("too many requests")
    assert isinstance (err, RAGError)
    assert err.component == "rate_limiter"
    assert err.recoverable is True

  def test_auth_error (self):
    err = AuthError ("invalid token")
    assert isinstance (err, RAGError)
    assert err.component == "auth"
    assert err.recoverable is False

  def test_context_build_error (self):
    err = ContextBuildError ("token budget exceeded")
    assert isinstance (err, RAGError)
    assert err.component == "context_builder"
    assert err.recoverable is True

  def test_validation_error (self):
    err = ValidationError ("invalid input")
    assert isinstance (err, RAGError)
    assert err.component == "validation"
    assert err.recoverable is False

  def test_exception_can_be_caught_as_rag_error (self):
    try:
      raise RetrievalError ("qdrant timeout")
    except RAGError as e:
      assert isinstance (e, RetrievalError)
      assert e.component == "retrieval"

  def test_all_subclasses_have_default_component (self):
    subclasses = [
        RetrievalError, RerankError, LLMError, GraphError, CacheError, EmbeddingError, ConfigError, RateLimitError,
        AuthError, ContextBuildError, ValidationError,
    ]
    for cls in subclasses:
      instance = cls ("msg")
      assert instance.component != "", f"{cls.__name__} has empty component"
