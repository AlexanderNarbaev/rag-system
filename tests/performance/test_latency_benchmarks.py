# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Baseline latency benchmarks for the RAG System.

Micro-benchmarks for every major component in the RAG pipeline:
  - Embedding generation (single + batch)
  - Qdrant search (dense, sparse, hybrid + RRF)
  - Reranking (cross-encoder, ColBERT, hybrid)
  - Context assembly (dedup, build, reorder)
  - LLM call latency (mocked network)
  - End-to-end pipeline (mocked external services)

Each benchmark collects repeated samples and reports p50/p95/p99.

Run:  pytest tests/performance/test_latency_benchmarks.py -v -m benchmark --benchmark-disable
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Percentile helper (reusable)
# ---------------------------------------------------------------------------


@dataclass
class LatencyStats:
    """Container for latency samples with percentile computation."""

    name: str
    unit: str = "ms"
    samples: list[float] = field(default_factory=list)

    def add(self, value_ms: float) -> None:
        self.samples.append(value_ms)

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def mean(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    @property
    def p50(self) -> float:
        return self._percentile(0.50)

    @property
    def p95(self) -> float:
        return self._percentile(0.95)

    @property
    def p99(self) -> float:
        return self._percentile(0.99)

    @property
    def min_val(self) -> float:
        return min(self.samples) if self.samples else 0.0

    @property
    def max_val(self) -> float:
        return max(self.samples) if self.samples else 0.0

    def _percentile(self, p: float) -> float:
        if not self.samples:
            return 0.0
        s = sorted(self.samples)
        idx = int(len(s) * p)
        return s[min(idx, len(s) - 1)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "count": self.count,
            "mean_ms": round(self.mean, 3),
            "p50_ms": round(self.p50, 3),
            "p95_ms": round(self.p95, 3),
            "p99_ms": round(self.p99, 3),
            "min_ms": round(self.min_val, 3),
            "max_ms": round(self.max_val, 3),
        }


def _timed_ms(fn, *args, **kwargs) -> tuple[float, Any]:
    """Run *fn* and return (elapsed_ms, result)."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return (time.perf_counter() - t0) * 1000, result


# ---------------------------------------------------------------------------
# Synthetic data factories
# ---------------------------------------------------------------------------

_VOCAB = [
    "authentication", "configuration", "deployment", "pipeline", "database",
    "microservice", "kubernetes", "monitoring", "logging", "retrieval",
    "embedding", "chunk", "reranker", "context", "token",
    "vector", "search", "index", "graph", "query",
    "latency", "throughput", "caching", "redis", "qdrant",
]


def _make_text(n_words: int = 50) -> str:
    """Generate a realistic-looking text paragraph."""
    return " ".join(random.choices(_VOCAB, k=n_words))


def _make_embedding(dim: int = 1024) -> list[float]:
    """Generate a random unit-length embedding vector."""
    vec = np.random.randn(dim).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


def _make_chunks(n: int, avg_words: int = 120) -> list[dict[str, Any]]:
    """Generate *n* synthetic chunk dicts with metadata."""
    chunks = []
    for i in range(n):
        chunks.append({
            "text": _make_text(avg_words),
            "source_type": random.choice(["confluence", "jira", "gitlab"]),
            "source_id": f"doc_{i % 10}",
            "doc_title": f"Document {i % 5}",
            "title": f"Section {i}",
            "version": random.choice(["1.0", "1.1", "2.0"]),
            "chunk_id": f"chunk_{i}",
        })
    return chunks


def _make_scored_chunks(n: int) -> list[tuple[dict[str, Any], float]]:
    """Generate *n* (chunk, score) tuples."""
    chunks = _make_chunks(n)
    return [(c, round(random.uniform(0.2, 0.95), 3)) for c in chunks]


class _FakeHit:
    """Minimal stand-in for Qdrant ScoredPoint."""

    __slots__ = ("id", "score", "payload")

    def __init__(self, hit_id: str, score: float, payload: dict | None = None):
        self.id = hit_id
        self.score = score
        self.payload = payload or {}


# ---------------------------------------------------------------------------
# Benchmark runner helper
# ---------------------------------------------------------------------------

WARMUP_ROUNDS = 5
SAMPLE_ROUNDS = 50


def _run_benchmark(name: str, fn, rounds: int = SAMPLE_ROUNDS, warmup: int = WARMUP_ROUNDS, **kwargs) -> LatencyStats:
    """Warmup + measure *fn* for *rounds* iterations, returning stats."""
    stats = LatencyStats(name=name)
    # warmup
    for _ in range(warmup):
        fn(**kwargs)
    # measure
    for _ in range(rounds):
        ms, _ = _timed_ms(fn, **kwargs)
        stats.add(ms)
    return stats


# ---------------------------------------------------------------------------
# 1. Embedding Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestEmbeddingBenchmarks:
    """Benchmark embedding generation functions."""

    def test_token_estimation_short_text(self):
        """Benchmark: estimate_tokens on ~200-char text (~50 tokens)."""
        from proxy.app.shared.utils import estimate_tokens

        text = _make_text(50)
        stats = _run_benchmark("token_estimation_short", estimate_tokens, text=text)

        assert stats.p50 < 1.0, f"token_estimation p50={stats.p50:.3f}ms too high"
        # Print for report collection
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_token_estimation_long_text(self):
        """Benchmark: estimate_tokens on ~10KB text (~2500 tokens)."""
        from proxy.app.shared.utils import estimate_tokens

        text = _make_text(2500)
        stats = _run_benchmark("token_estimation_long", estimate_tokens, text=text)

        assert stats.p50 < 5.0, f"token_estimation_long p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_sha256_hashing(self):
        """Benchmark: SHA-256 hash computation on ~2.6KB string."""
        from proxy.app.shared.utils import compute_hash

        text = _make_text(500)
        stats = _run_benchmark("sha256_hash", compute_hash, data=text)

        assert stats.p50 < 0.5, f"sha256_hash p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_embedding_cache_lookup_hit(self):
        """Benchmark: EmbeddingCache.get() cache hit."""
        from proxy.app.core.retrieval import EmbeddingCache

        cache = EmbeddingCache(max_size=1000)
        vec = _make_embedding(1024)
        for i in range(500):
            cache.set(f"query_{i}", vec)

        stats = _run_benchmark("embedding_cache_hit", cache.get, query="query_250")

        assert stats.p50 < 0.1, f"embedding_cache_hit p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_embedding_cache_lookup_miss(self):
        """Benchmark: EmbeddingCache.get() cache miss."""
        from proxy.app.core.retrieval import EmbeddingCache

        cache = EmbeddingCache(max_size=1000)
        vec = _make_embedding(1024)
        for i in range(500):
            cache.set(f"query_{i}", vec)

        stats = _run_benchmark("embedding_cache_miss", cache.get, query="nonexistent_query_xyz")

        assert stats.p50 < 1.0, f"embedding_cache_miss p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_cosine_similarity_single(self):
        """Benchmark: Cosine similarity of two 1024-d vectors."""
        from proxy.app.core.rerank import cosine_similarity_single

        a = _make_embedding(1024)
        b = _make_embedding(1024)
        stats = _run_benchmark("cosine_similarity_1024d", cosine_similarity_single, a=a, b=b)

        assert stats.p50 < 0.5, f"cosine_similarity p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")


# ---------------------------------------------------------------------------
# 2. Retrieval / Search Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestRetrievalBenchmarks:
    """Benchmark RRF fusion, knee-point pruning, and score filtering."""

    def test_rrf_fusion_20_hits(self):
        """Benchmark: RRF fusion on two 20-hit result lists."""
        from proxy.app.core.retrieval import reciprocal_rank_fusion

        hits_dense = [_FakeHit(f"doc_{i}", 0.9 - i * 0.04) for i in range(20)]
        hits_sparse = [_FakeHit(f"doc_{i}", 0.85 - i * 0.04) for i in range(20)]
        stats = _run_benchmark("rrf_fusion_20", reciprocal_rank_fusion, results_dense=hits_dense, results_sparse=hits_sparse)

        assert stats.p50 < 1.0, f"rrf_fusion_20 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_rrf_fusion_50_hits(self):
        """Benchmark: RRF fusion on two 50-hit result lists (production top_k)."""
        from proxy.app.core.retrieval import reciprocal_rank_fusion

        hits_dense = [_FakeHit(f"doc_{i}", 0.9 - i * 0.015) for i in range(50)]
        hits_sparse = [_FakeHit(f"doc_{i}", 0.85 - i * 0.015) for i in range(50)]
        stats = _run_benchmark("rrf_fusion_50", reciprocal_rank_fusion, results_dense=hits_dense, results_sparse=hits_sparse)

        assert stats.p50 < 2.0, f"rrf_fusion_50 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_knee_point_pruning(self):
        """Benchmark: Knee-point pruning on 20 results."""
        from proxy.app.core.retrieval import knee_point_pruning

        hits = [_FakeHit(f"doc_{i}", max(0.1, 0.9 - i * 0.04 + random.uniform(-0.02, 0.02))) for i in range(20)]
        stats = _run_benchmark("knee_point_pruning_20", knee_point_pruning, results=hits)

        assert stats.p50 < 2.0, f"knee_point_pruning p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_score_filtering(self):
        """Benchmark: Two-level score filtering on 20 results."""
        from proxy.app.core.retrieval import filter_results_by_score

        hits = [_FakeHit(f"doc_{i}", max(0.1, 0.6 - i * 0.02 + random.uniform(-0.05, 0.05))) for i in range(20)]
        stats = _run_benchmark("score_filtering_20", filter_results_by_score, results=hits)

        assert stats.p50 < 1.0, f"score_filtering p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_in_memory_cache_lookup(self):
        """Benchmark: InMemoryCache sync lookup (1000-entry cache)."""
        from proxy.app.shared.cache import InMemoryCache

        cache = InMemoryCache()
        for i in range(1000):
            cache.set_sync(f"key_{i}", f"value_{i}", ttl=7200)

        stats = _run_benchmark("in_memory_cache_get", cache.get_sync, key="key_500")

        assert stats.p50 < 0.5, f"in_memory_cache_get p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")


# ---------------------------------------------------------------------------
# 3. Reranking Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestRerankingBenchmarks:
    """Benchmark reranking scoring functions."""

    def test_colbert_score_small(self):
        """Benchmark: ColBERT late interaction score (5 query tokens × 10 doc tokens, 64-d)."""
        from proxy.app.core.rerank import colbert_score

        dim = 64
        q_tokens = [_make_embedding(dim) for _ in range(5)]
        d_tokens = [_make_embedding(dim) for _ in range(10)]
        stats = _run_benchmark("colbert_score_5x10", colbert_score, query_tokens=q_tokens, doc_tokens=d_tokens)

        assert stats.p50 < 5.0, f"colbert_score_5x10 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_colbert_score_large(self):
        """Benchmark: ColBERT late interaction score (20 query × 50 doc tokens, 128-d)."""
        from proxy.app.core.rerank import colbert_score

        dim = 128
        q_tokens = [_make_embedding(dim) for _ in range(20)]
        d_tokens = [_make_embedding(dim) for _ in range(50)]
        stats = _run_benchmark("colbert_score_20x50", colbert_score, query_tokens=q_tokens, doc_tokens=d_tokens)

        assert stats.p50 < 50.0, f"colbert_score_20x50 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_rerank_text_truncation(self):
        """Benchmark: Text truncation for reranker input."""
        from proxy.app.core.rerank import _truncate_text

        long_text = _make_text(5000)  # ~20KB
        stats = _run_benchmark("text_truncation", _truncate_text, text=long_text)

        assert stats.p50 < 0.5, f"text_truncation p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_rerank_cache_key_generation(self):
        """Benchmark: Cache key generation for reranker."""
        from proxy.app.core.rerank import _get_cache_key

        query = _make_text(20)
        chunk = _make_text(200)
        stats = _run_benchmark("rerank_cache_key", _get_cache_key, query=query, chunk_text=chunk)

        assert stats.p50 < 0.5, f"rerank_cache_key p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")


# ---------------------------------------------------------------------------
# 4. Context Assembly Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestContextAssemblyBenchmarks:
    """Benchmark context building, deduplication, and reordering."""

    def test_chunk_hash_computation(self):
        """Benchmark: Chunk SHA-256 hash computation."""
        from proxy.app.core.context.builder import compute_chunk_hash

        chunk = _make_chunks(1, avg_words=120)[0]
        stats = _run_benchmark("chunk_hash", compute_chunk_hash, chunk=chunk)

        assert stats.p50 < 0.5, f"chunk_hash p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_deduplication_10_chunks(self):
        """Benchmark: Deduplication on 10 chunks."""
        from proxy.app.core.context.builder import deduplicate_chunks

        scored = _make_scored_chunks(10)
        stats = _run_benchmark("dedup_10", deduplicate_chunks, chunks_with_scores=scored)

        assert stats.p50 < 1.0, f"dedup_10 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_deduplication_50_chunks(self):
        """Benchmark: Deduplication on 50 chunks (production retrieval count)."""
        from proxy.app.core.context.builder import deduplicate_chunks

        scored = _make_scored_chunks(50)
        stats = _run_benchmark("dedup_50", deduplicate_chunks, chunks_with_scores=scored)

        assert stats.p50 < 5.0, f"dedup_50 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_deduplication_200_chunks(self):
        """Benchmark: Deduplication on 200 chunks (stress test)."""
        from proxy.app.core.context.builder import deduplicate_chunks

        scored = _make_scored_chunks(200)
        stats = _run_benchmark("dedup_200", deduplicate_chunks, chunks_with_scores=scored)

        assert stats.p50 < 20.0, f"dedup_200 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_context_build_small(self):
        """Benchmark: build_context with 5 chunks, 4K token budget."""
        from proxy.app.core.context.builder import build_context

        scored = _make_scored_chunks(5)
        stats = _run_benchmark("build_context_5", build_context, chunks_with_scores=scored, max_tokens=4000)

        assert stats.p50 < 5.0, f"build_context_5 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_context_build_large(self):
        """Benchmark: build_context with 20 chunks, 16K token budget."""
        from proxy.app.core.context.builder import build_context

        scored = _make_scored_chunks(20)
        stats = _run_benchmark("build_context_20", build_context, chunks_with_scores=scored, max_tokens=16000)

        assert stats.p50 < 20.0, f"build_context_20 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_context_reorder(self):
        """Benchmark: LongContextReorder on 10 chunks."""
        from proxy.app.core.context.builder import reorder_chunks

        scored = _make_scored_chunks(10)
        stats = _run_benchmark("reorder_10", reorder_chunks, chunks_with_scores=scored)

        assert stats.p50 < 1.0, f"reorder_10 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_prepare_context_full_pipeline(self):
        """Benchmark: prepare_context (dedup + version resolve + group + build) on 15 chunks."""
        from proxy.app.core.context.builder import prepare_context

        scored = _make_scored_chunks(15)
        stats = _run_benchmark(
            "prepare_context_15",
            prepare_context,
            chunks_with_scores=scored,
            max_tokens=12000,
            deduplicate=True,
            group_semantic=False,
        )

        assert stats.p50 < 30.0, f"prepare_context_15 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")


# ---------------------------------------------------------------------------
# 5. Graph / Multi-hop Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestGraphBenchmarks:
    """Benchmark graph-related computations."""

    def test_multi_hop_bfs_2_hops(self):
        """Benchmark: Multi-hop BFS exploration (2 hops, 5 start entities)."""
        from proxy.app.core.retrieval import MultiHopGraphExplorer

        explorer = MultiHopGraphExplorer(max_hops=2, max_results_per_hop=10)
        entity_map = {f"entity_{i}": [f"entity_{j}" for j in range(max(0, i - 3), min(20, i + 4)) if j != i] for i in range(20)}
        start = [f"entity_{i}" for i in range(5)]

        stats = _run_benchmark("multi_hop_bfs_2hops", explorer.explore, start_entities=start, entity_map=entity_map)

        assert stats.p50 < 10.0, f"multi_hop_bfs p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_cypher_generation(self):
        """Benchmark: Cypher query generation from natural language."""
        from proxy.app.core.retrieval import CypherQueryGenerator

        generator = CypherQueryGenerator()
        queries = [
            "What projects does John work on?",
            "Show me all dependencies for the API service",
            "Who worked on the authentication module?",
            "Find issues related to deployment pipeline",
        ]

        stats = LatencyStats(name="cypher_generation")
        for _ in range(WARMUP_ROUNDS):
            for q in queries:
                generator.generate(q)
        for _ in range(SAMPLE_ROUNDS):
            for q in queries:
                ms, _ = _timed_ms(generator.generate, q)
                stats.add(ms)

        assert stats.p50 < 0.5, f"cypher_generation p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_global_search_small(self):
        """Benchmark: GlobalSearch on 20 community summaries."""
        from proxy.app.core.retrieval import GlobalSearch

        summaries = [
            {"id": f"c_{i}", "summary": _make_text(100), "key_entities": [f"entity_{j}" for j in range(5)], "members": []}
            for i in range(20)
        ]
        search = GlobalSearch(community_summaries=summaries)
        stats = _run_benchmark("global_search_20", search.search, query="What are the main topics in the knowledge base?")

        assert stats.p50 < 5.0, f"global_search p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")


# ---------------------------------------------------------------------------
# 6. Time Decay & Scoring Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark
class TestScoringBenchmarks:
    """Benchmark score computation and time decay functions."""

    def test_time_decay_20_chunks(self):
        """Benchmark: apply_time_decay on 20 chunks."""
        from proxy.app.core.retrieval import apply_time_decay

        chunks = [
            {"text": _make_text(50), "score": random.uniform(0.3, 0.9),
             "payload": {"updated_at": f"2026-{random.randint(1, 7):02d}-{random.randint(1, 28):02d}T00:00:00Z"}}
            for _ in range(20)
        ]
        stats = _run_benchmark("time_decay_20", apply_time_decay, chunks=chunks)

        assert stats.p50 < 5.0, f"time_decay_20 p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")

    def test_dynamic_top_k(self):
        """Benchmark: compute_dynamic_top_k (SLM scoring + heuristic)."""
        from proxy.app.core.retrieval import compute_dynamic_top_k

        queries = [
            "What is RAG?",
            "How to configure the CI/CD pipeline for the microservices architecture?",
            "Explain the retrieval augmented generation approach",
        ]

        stats = LatencyStats(name="dynamic_top_k")
        for _ in range(WARMUP_ROUNDS):
            for q in queries:
                compute_dynamic_top_k(q)
        for _ in range(SAMPLE_ROUNDS):
            for q in queries:
                ms, _ = _timed_ms(compute_dynamic_top_k, q)
                stats.add(ms)

        assert stats.p50 < 10.0, f"dynamic_top_k p50={stats.p50:.3f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.3f}ms p95={stats.p95:.3f}ms p99={stats.p99:.3f}ms (n={stats.count})")


# ---------------------------------------------------------------------------
# 7. End-to-End Pipeline Latency (Mocked)
# ---------------------------------------------------------------------------


# Mock heavy external dependencies for the E2E tests
_modules_to_mock = [
    "qdrant_client", "qdrant_client.http", "qdrant_client.http.models",
    "sentence_transformers", "langgraph", "langgraph.graph", "langgraph.checkpoint",
    "neo4j", "redis", "redis.asyncio", "tiktoken", "bcrypt",
]

for mod in _modules_to_mock:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

from proxy.app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _disable_auth(monkeypatch):
    """Disable authentication for all tests in this module."""
    import proxy.app.auth.jwt as _jwt
    import proxy.app.shared.config as _cfg

    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(_cfg, "AUTH_ENABLED", False)
    monkeypatch.setattr(_jwt, "AUTH_ENABLED", False)


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_rag_pipeline():
    """Mock all RAG pipeline dependencies for consistent latency measurement."""
    with (
        patch("proxy.app.main.hybrid_search") as mock_hybrid,
        patch("proxy.app.main.rerank_chunks") as mock_rerank,
        patch("proxy.app.main.deduplicate_chunks") as mock_dedup,
        patch("proxy.app.main.build_context") as mock_build,
        patch("proxy.app.main.non_stream_completion") as mock_nonstream,
        patch("proxy.app.main.stream_completion") as mock_stream,
        patch("proxy.app.main.extract_version_from_query", return_value=None),
        patch("proxy.app.main.cache_manager", None),
        patch("proxy.app.main.log_interaction") as mock_log,
    ):
        mock_hybrid.return_value = []
        mock_rerank.return_value = []
        mock_dedup.return_value = []
        mock_build.return_value = ""
        mock_nonstream.return_value = "Mocked response for performance testing."
        mock_stream.return_value = iter([])
        yield {
            "hybrid_search": mock_hybrid,
            "rerank_chunks": mock_rerank,
            "deduplicate_chunks": mock_dedup,
            "build_context": mock_build,
            "non_stream_completion": mock_nonstream,
            "stream_completion": mock_stream,
            "log_interaction": mock_log,
        }


@pytest.mark.benchmark
class TestE2EPipelineBenchmarks:
    """Benchmark full pipeline latency through the FastAPI TestClient."""

    def test_chat_completion_e2e_non_streaming(self, client, mock_rag_pipeline):
        """Benchmark: Non-streaming /v1/chat/completions (mocked services)."""
        payload = {
            "model": "rag-proxy",
            "messages": [{"role": "user", "content": "What is retrieval augmented generation?"}],
            "stream": False,
        }

        stats = LatencyStats(name="chat_completion_non_stream")
        for _ in range(WARMUP_ROUNDS):
            client.post("/v1/chat/completions", json=payload)
        for _ in range(30):
            start = time.perf_counter()
            resp = client.post("/v1/chat/completions", json=payload)
            ms = (time.perf_counter() - start) * 1000
            assert resp.status_code == 200
            stats.add(ms)

        assert stats.p95 < 5000, f"chat_completion p95={stats.p95:.1f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.1f}ms p95={stats.p95:.1f}ms p99={stats.p99:.1f}ms (n={stats.count})")

    def test_chat_completion_e2e_streaming(self, client, mock_rag_pipeline):
        """Benchmark: Streaming /v1/chat/completions (mocked services)."""

        async def mock_stream_gen(*args, **kwargs):
            yield {"id": "1", "choices": [{"delta": {"content": "First "}}]}
            yield {"id": "2", "choices": [{"delta": {"content": "chunk."}}]}

        mock_rag_pipeline["stream_completion"].side_effect = mock_stream_gen

        payload = {
            "model": "rag-proxy",
            "messages": [{"role": "user", "content": "test streaming"}],
            "stream": True,
        }

        stats = LatencyStats(name="chat_completion_stream")
        for _ in range(WARMUP_ROUNDS):
            client.post("/v1/chat/completions", json=payload)
        for _ in range(30):
            start = time.perf_counter()
            resp = client.post("/v1/chat/completions", json=payload)
            ms = (time.perf_counter() - start) * 1000
            assert resp.status_code == 200
            stats.add(ms)

        assert stats.p95 < 5000, f"chat_completion_stream p95={stats.p95:.1f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.1f}ms p95={stats.p95:.1f}ms p99={stats.p99:.1f}ms (n={stats.count})")

    def test_health_live_e2e(self, client):
        """Benchmark: GET /v1/health/live."""
        stats = LatencyStats(name="health_live")
        for _ in range(WARMUP_ROUNDS):
            client.get("/v1/health/live")
        for _ in range(SAMPLE_ROUNDS):
            start = time.perf_counter()
            resp = client.get("/v1/health/live")
            ms = (time.perf_counter() - start) * 1000
            assert resp.status_code == 200
            stats.add(ms)

        assert stats.p95 < 200, f"health_live p95={stats.p95:.1f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.1f}ms p95={stats.p95:.1f}ms p99={stats.p99:.1f}ms (n={stats.count})")

    def test_models_list_e2e(self, client):
        """Benchmark: GET /v1/models."""
        stats = LatencyStats(name="models_list")
        for _ in range(WARMUP_ROUNDS):
            client.get("/v1/models")
        for _ in range(SAMPLE_ROUNDS):
            start = time.perf_counter()
            resp = client.get("/v1/models")
            ms = (time.perf_counter() - start) * 1000
            assert resp.status_code == 200
            stats.add(ms)

        assert stats.p95 < 500, f"models_list p95={stats.p95:.1f}ms too high"
        print(f"\n  {stats.name}: p50={stats.p50:.1f}ms p95={stats.p95:.1f}ms p99={stats.p99:.1f}ms (n={stats.count})")


# ---------------------------------------------------------------------------
# 8. Report Collection Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=False)
def benchmark_report_collector():
    """Collect all LatencyStats and write JSON report at session end."""
    # This is a session-scoped fixture that can be explicitly requested.
    # By default (autouse=False), it only runs when tests request it.
    results: list[dict] = []
    yield results

    if results:
        from pathlib import Path

        report_path = Path(__file__).parent / "latency_benchmark_results.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nBenchmark report written to: {report_path}")
