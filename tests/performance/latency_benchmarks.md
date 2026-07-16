# RAG System — Latency Benchmark Report

**Generated:** 2026-07-16T06:23:24.656613+00:00
**Host:** alexandr-narbaev-JIAOLONG-Series
**Platform:** Linux 7.0.0-27-generic
**Python:** 3.14.6
**CPUs:** 32
**Duration:** 2.71s

---

## Summary

| Metric | Value |
|--------|-------|
| Total Benchmarks | 32 |
| Passed | 32 |
| Failed | 0 |
| Pass Rate | 100.0% |

### By Category

| Category | Passed | Failed | Total |
|----------|--------|--------|-------|
| context | 8 | 0 | 8 |
| e2e | 4 | 0 | 4 |
| embedding | 6 | 0 | 6 |
| graph | 3 | 0 | 3 |
| reranking | 4 | 0 | 4 |
| retrieval | 5 | 0 | 5 |
| scoring | 2 | 0 | 2 |

---

## Detailed Results

### Context

| Benchmark | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (ms) | Status |
|-----------|----------|----------|----------|----------------|--------|
| build context 20 | 0.011 | 0.011 | 0.015 | 20.0 | OK PASS |
| build context 5 | 0.003 | 0.004 | 0.008 | 5.0 | OK PASS |
| chunk hash | 0.001 | 0.001 | 0.001 | 0.5 | OK PASS |
| dedup 10 | 0.009 | 0.010 | 0.013 | 1.0 | OK PASS |
| dedup 200 | 0.179 | 0.228 | 0.234 | 20.0 | OK PASS |
| dedup 50 | 0.044 | 0.046 | 0.047 | 5.0 | OK PASS |
| prepare context 15 | 0.032 | 0.033 | 0.035 | 30.0 | OK PASS |
| reorder 10 | 0.001 | 0.001 | 0.001 | 1.0 | OK PASS |
### E2E

| Benchmark | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (ms) | Status |
|-----------|----------|----------|----------|----------------|--------|
| chat completion non stream | 2.200 | 3.100 | 4.900 | 5000.0 | OK PASS |
| chat completion stream | 1.300 | 1.900 | 2.100 | 5000.0 | OK PASS |
| health live | 0.600 | 0.900 | 1.000 | 200.0 | OK PASS |
| models list | 0.700 | 1.000 | 1.100 | 500.0 | OK PASS |
### Embedding

| Benchmark | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (ms) | Status |
|-----------|----------|----------|----------|----------------|--------|
| cosine similarity 1024d | 0.046 | 0.048 | 0.049 | 0.5 | OK PASS |
| embedding cache hit | 0.001 | 0.001 | 0.001 | 0.1 | OK PASS |
| embedding cache miss | 0.106 | 0.159 | 0.160 | 1.0 | OK PASS |
| sha256 hash | 0.002 | 0.002 | 0.002 | 0.5 | OK PASS |
| token estimation long | 0.018 | 0.022 | 0.088 | 5.0 | OK PASS |
| token estimation short | 0.017 | 0.020 | 0.079 | 1.0 | OK PASS |
### Graph

| Benchmark | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (ms) | Status |
|-----------|----------|----------|----------|----------------|--------|
| cypher generation | 0.001 | 0.002 | 0.002 | 0.5 | OK PASS |
| global search 20 | 0.070 | 0.089 | 0.102 | 5.0 | OK PASS |
| multi hop bfs 2hops | 0.005 | 0.005 | 0.005 | 10.0 | OK PASS |
### Reranking

| Benchmark | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (ms) | Status |
|-----------|----------|----------|----------|----------------|--------|
| colbert score 20x50 | 6.343 | 7.304 | 7.625 | 50.0 | OK PASS |
| colbert score 5x10 | 0.174 | 0.177 | 0.188 | 5.0 | OK PASS |
| rerank cache key | 0.002 | 0.002 | 0.002 | 0.5 | OK PASS |
| text truncation | 0.000 | 0.000 | 0.000 | 0.5 | OK PASS |
### Retrieval

| Benchmark | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (ms) | Status |
|-----------|----------|----------|----------|----------------|--------|
| in memory cache get | 0.000 | 0.000 | 0.001 | 0.5 | OK PASS |
| knee point pruning 20 | 0.054 | 0.057 | 0.058 | 2.0 | OK PASS |
| rrf fusion 20 | 0.004 | 0.004 | 0.004 | 1.0 | OK PASS |
| rrf fusion 50 | 0.010 | 0.010 | 0.010 | 2.0 | OK PASS |
| score filtering 20 | 0.001 | 0.001 | 0.001 | 1.0 | OK PASS |
### Scoring

| Benchmark | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (ms) | Status |
|-----------|----------|----------|----------|----------------|--------|
| dynamic top k | 0.011 | 0.014 | 0.017 | 10.0 | OK PASS |
| time decay 20 | 0.011 | 0.015 | 0.018 | 5.0 | OK PASS |

---

## Baseline Expectations (Reference Hardware)

These baselines were measured on:
- **CPU:** Intel Xeon E5-2686 v4 (8 cores) or equivalent
- **RAM:** 32 GB
- **Python:** 3.12+
- **No GPU** (CPU-only benchmarks)

### Component Latency Targets

| Component | Target p50 | Target p95 | Notes |
|-----------|------------|------------|-------|
| Token estimation (short) | <0.1ms | <1.0ms | ~50 tokens, tiktoken fallback |
| Token estimation (long) | <1.0ms | <5.0ms | ~2500 tokens |
| SHA-256 hashing | <0.1ms | <0.5ms | ~2.6KB input |
| Embedding cache hit | <0.01ms | <0.1ms | In-memory lookup |
| Embedding cache miss | <0.1ms | <1.0ms | Full word-overlap scan |
| Cosine similarity (1024-d) | <0.1ms | <0.5ms | Single pair |
| RRF fusion (20 hits) | <0.1ms | <1.0ms | Two ranked lists |
| RRF fusion (50 hits) | <0.5ms | <2.0ms | Production top_k |
| Knee-point pruning | <0.5ms | <2.0ms | NumPy-based |
| Score filtering | <0.1ms | <1.0ms | Two-level threshold |
| ColBERT score (5x10) | <0.5ms | <5.0ms | 64-d tokens |
| ColBERT score (20x50) | <5.0ms | <50.0ms | 128-d tokens |
| Dedup (10 chunks) | <0.1ms | <1.0ms | SHA-256 hash |
| Dedup (50 chunks) | <0.5ms | <5.0ms | Production size |
| Dedup (200 chunks) | <2.0ms | <20.0ms | Stress test |
| Context build (5 chunks) | <0.5ms | <5.0ms | 4K token budget |
| Context build (20 chunks) | <2.0ms | <20.0ms | 16K token budget |
| Context reorder | <0.1ms | <1.0ms | LongContextReorder |
| Prepare context (15) | <5.0ms | <30.0ms | Full pipeline |
| Multi-hop BFS (2 hops) | <1.0ms | <10.0ms | 20 entities |
| Cypher generation | <0.1ms | <0.5ms | Pattern matching |
| Global search (20) | <0.5ms | <5.0ms | Keyword overlap |
| Time decay (20 chunks) | <0.5ms | <5.0ms | Exponential decay |
| Dynamic top-k | <1.0ms | <10.0ms | SLM + heuristic |

### End-to-End (Mocked Services)

| Endpoint | Target p50 | Target p95 | Notes |
|----------|------------|------------|-------|
| Chat (non-streaming) | <100ms | <5000ms | Framework overhead only |
| Chat (streaming) | <100ms | <5000ms | TTFT with mocked LLM |
| Health /live | <10ms | <200ms | Liveness probe |
| Models list | <20ms | <500ms | Static response |

---

## Tuning Recommendations

1. **Embedding cache**: If cache hit latency >0.1ms, reduce cache size or use LRU eviction
2. **RRF fusion**: If >2ms for 50 hits, consider pre-sorting or using NumPy vectorization
3. **ColBERT scoring**: If >50ms for 20x50, reduce token dimensions or batch on GPU
4. **Deduplication**: If >20ms for 200 chunks, consider Bloom filter pre-filtering
5. **Context build**: If >30ms for 15 chunks, reduce metadata overhead or pre-compute hashes
6. **Graph traversal**: If >10ms for 2 hops, limit entity map connectivity or add indexing
