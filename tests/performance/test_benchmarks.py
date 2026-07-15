"""Performance benchmarks for RAG System components.

Micro-benchmarks for hot-path functions using pytest-benchmark.
Targets: token counting, hashing, cache lookup, RRF fusion, deduplication.
"""

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeHit:
  """Minimal stand-in for a Qdrant ScoredPoint (needs .id and .score)."""

  __slots__ = ("id", "score")

  def __init__ (self, hit_id: str, score: float) -> None:
    self.id = hit_id
    self.score = score


# ── Benchmarks ───────────────────────────────────────────────────────────────


@pytest.mark.benchmark
def test_benchmark_token_counting (benchmark):
  """Benchmark: Token estimation speed on ~2.6 KB text."""
  from proxy.app.shared.utils import estimate_tokens

  text = "This is a test sentence for token counting. " * 100
  benchmark (estimate_tokens, text)


@pytest.mark.benchmark
def test_benchmark_hash_computation (benchmark):
  """Benchmark: SHA-256 hash computation on ~1.3 KB string."""
  from proxy.app.shared.utils import compute_hash

  text = "test content for hashing " * 100
  benchmark (compute_hash, text)


@pytest.mark.benchmark
def test_benchmark_cache_lookup_sync (benchmark):
  """Benchmark: InMemoryCache sync lookup in a pre-populated cache."""
  from proxy.app.shared.cache import InMemoryCache

  cache = InMemoryCache ()
  # Pre-populate with 1000 entries using the sync helper
  for i in range (1000):
    cache.set_sync (f"key_{i}", f"value_{i}", ttl = 7200)

  benchmark (cache.get_sync, "key_500")


@pytest.mark.benchmark
def test_benchmark_rrf (benchmark):
  """Benchmark: Reciprocal Rank Fusion on two 20-hit lists."""
  from proxy.app.core.retrieval import reciprocal_rank_fusion

  hits_dense = [_FakeHit (f"doc_{i}", 0.9 - i * 0.04) for i in range (20)]
  hits_sparse = [_FakeHit (f"doc_{i}", 0.85 - i * 0.04) for i in range (20)]
  benchmark (reciprocal_rank_fusion, hits_dense, hits_sparse)


@pytest.mark.benchmark
def test_benchmark_dedup (benchmark):
  """Benchmark: Content-hash deduplication on 50 chunk-score pairs."""
  from proxy.app.core.context import deduplicate_chunks

  chunks_with_scores = [
      ({"text": f"This is chunk number {i} with some content.", "source_id": f"doc_{i % 5}"}, 0.9 - i * 0.01) for i in
      range (50)]
  benchmark (deduplicate_chunks, chunks_with_scores)
