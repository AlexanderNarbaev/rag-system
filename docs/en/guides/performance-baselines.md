# Performance Baselines

This document establishes latency baselines for every major component in the RAG System pipeline.
These baselines serve as regression gates — any p95 latency exceeding the documented threshold
indicates a performance regression that must be investigated before merge.

## Running Benchmarks

```bash
# Run all latency benchmarks
python scripts/run_benchmarks.py

# Run specific category
python scripts/run_benchmarks.py --category retrieval
python scripts/run_benchmarks.py --category embedding
python scripts/run_benchmarks.py --category context

# Compare against a previous baseline
python scripts/run_benchmarks.py --compare tests/performance/latency_benchmarks.json

# Fail CI on >20% regression
python scripts/run_benchmarks.py --compare baseline.json --fail-on-regression

# Via Makefile
make benchmark-baselines
make benchmark-compare
```

### Output Files

| File | Format | Purpose |
|------|--------|---------|
| `tests/performance/latency_benchmarks.json` | JSON | Machine-readable for CI gates |
| `tests/performance/latency_benchmarks.md` | Markdown | Human-readable report |

## Reference Hardware

All baselines below were measured on:

| Spec | Value |
|------|-------|
| **CPU** | Intel Xeon E5-2686 v4 (8 cores) / AMD EPYC equivalent |
| **RAM** | 32 GB DDR4 |
| **Python** | 3.11+ |
| **GPU** | None (CPU-only benchmarks) |
| **OS** | Linux (Ubuntu 22.04+ / Debian 12+) |

!!! note
    These are **component-level** latencies measured with mocked external services.
    Actual end-to-end latency includes network round-trips to Qdrant, LLM, and Redis.
    See [End-to-End Latency](#end-to-end-latency) for the full pipeline picture.

---

## Component Latency Baselines

### 1. Embedding Operations

| Benchmark | Input Size | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (p95) |
|-----------|-----------|----------|----------|----------|-----------------|
| Token estimation (short) | ~50 tokens / 200 chars | <0.1 | <1.0 | <2.0 | 1.0 ms |
| Token estimation (long) | ~2500 tokens / 10 KB | <1.0 | <5.0 | <10.0 | 5.0 ms |
| SHA-256 hashing | ~2.6 KB string | <0.1 | <0.5 | <1.0 | 0.5 ms |
| Embedding cache hit | 1000-entry cache | <0.01 | <0.1 | <0.2 | 0.1 ms |
| Embedding cache miss | 1000-entry cache | <0.1 | <1.0 | <2.0 | 1.0 ms |
| Cosine similarity | 1024-d vectors | <0.1 | <0.5 | <1.0 | 0.5 ms |

**Key observations:**

- Token estimation via `tiktoken` is O(n) in text length; the fallback `len(text)//4` is constant-time.
- Embedding cache uses two-level lookup: exact hash match (O(1)) then semantic word-overlap scan (O(n)).
- Cosine similarity on 1024-d vectors is ~0.05ms on modern CPUs with NumPy.

### 2. Retrieval / Search

| Benchmark | Input Size | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (p95) |
|-----------|-----------|----------|----------|----------|-----------------|
| RRF fusion (20 hits) | 2 × 20 ranked lists | <0.1 | <1.0 | <2.0 | 1.0 ms |
| RRF fusion (50 hits) | 2 × 50 ranked lists | <0.5 | <2.0 | <4.0 | 2.0 ms |
| Knee-point pruning | 20 results | <0.5 | <2.0 | <4.0 | 2.0 ms |
| Score filtering | 20 results | <0.1 | <1.0 | <2.0 | 1.0 ms |
| In-memory cache get | 1000-entry cache | <0.1 | <0.5 | <1.0 | 0.5 ms |

**Key observations:**

- RRF fusion is O(n+m) where n, m are result list sizes. With 50 hits each, this stays under 2ms.
- Knee-point pruning uses NumPy vectorized operations; dominated by `np.argmax` on the distance array.
- Score filtering is a simple list comprehension with threshold checks.

### 3. Reranking

| Benchmark | Input Size | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (p95) |
|-----------|-----------|----------|----------|----------|-----------------|
| ColBERT score (5×10) | 5 query × 10 doc tokens, 64-d | <0.5 | <5.0 | <10.0 | 5.0 ms |
| ColBERT score (20×50) | 20 query × 50 doc tokens, 128-d | <5.0 | <50.0 | <100.0 | 50.0 ms |
| Text truncation | ~20 KB input | <0.1 | <0.5 | <1.0 | 0.5 ms |
| Cache key generation | ~80 chars each | <0.1 | <0.5 | <1.0 | 0.5 ms |

**Key observations:**

- ColBERT late interaction is O(q_tokens × d_tokens) per document. The 20×50 benchmark at 128-d
  represents the upper bound of expected token counts.
- Text truncation is O(1) — it's a simple string slice at `max_tokens * 4` characters.
- Cross-encoder latency is NOT benchmarked here (requires the actual model loaded).
  Expect 150–400ms per batch of 20 pairs with `ms-marco-MiniLM-L-6-v2` on CPU.

### 4. Context Assembly

| Benchmark | Input Size | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (p95) |
|-----------|-----------|----------|----------|----------|-----------------|
| Chunk hash (SHA-256) | ~500 chars | <0.1 | <0.5 | <1.0 | 0.5 ms |
| Deduplication (10 chunks) | 10 (chunk, score) pairs | <0.1 | <1.0 | <2.0 | 1.0 ms |
| Deduplication (50 chunks) | 50 pairs | <0.5 | <5.0 | <10.0 | 5.0 ms |
| Deduplication (200 chunks) | 200 pairs | <2.0 | <20.0 | <40.0 | 20.0 ms |
| Context build (5 chunks) | 5 chunks, 4K token budget | <0.5 | <5.0 | <10.0 | 5.0 ms |
| Context build (20 chunks) | 20 chunks, 16K token budget | <2.0 | <20.0 | <40.0 | 20.0 ms |
| Context reorder | 10 chunks | <0.1 | <1.0 | <2.0 | 1.0 ms |
| Prepare context (full) | 15 chunks, dedup + build | <5.0 | <30.0 | <60.0 | 30.0 ms |

**Key observations:**

- Deduplication is O(n) with SHA-256 hashing per chunk. At 200 chunks, expect ~10–20ms.
- Context build iterates chunks and estimates tokens per chunk; dominated by string concatenation.
- `prepare_context` is the full pipeline: dedup → version resolve → group → build. It's the
  best indicator of real context assembly latency.

### 5. Graph / Multi-hop

| Benchmark | Input Size | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (p95) |
|-----------|-----------|----------|----------|----------|-----------------|
| Multi-hop BFS (2 hops) | 5 start entities, 20 total | <1.0 | <10.0 | <20.0 | 10.0 ms |
| Cypher generation | 4 queries | <0.1 | <0.5 | <1.0 | 0.5 ms |
| Global search (20 summaries) | 20 communities, 100 words each | <0.5 | <5.0 | <10.0 | 5.0 ms |

**Key observations:**

- BFS traversal is bounded by `max_hops` × `max_results_per_hop`. With 2 hops and 10 results
  per hop, worst case is ~200 path explorations.
- Cypher generation is pure string pattern matching — negligible latency.
- Global search does keyword overlap scoring across all community summaries.

### 6. Scoring & Heuristics

| Benchmark | Input Size | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (p95) |
|-----------|-----------|----------|----------|----------|-----------------|
| Time decay (20 chunks) | 20 chunks with timestamps | <0.5 | <5.0 | <10.0 | 5.0 ms |
| Dynamic top-k | 3 queries | <1.0 | <10.0 | <20.0 | 10.0 ms |

**Key observations:**

- Time decay uses `exp(-age_days / decay_days)` per chunk — O(n) math operations.
- Dynamic top-k calls the SLM for complexity scoring when available; falls back to word-count heuristics.

---

## End-to-End Latency

These benchmarks measure the full FastAPI pipeline with mocked external services
(Qdrant, LLM, Redis). They isolate **framework overhead** from service latency.

| Endpoint | Method | p50 (ms) | p95 (ms) | p99 (ms) | Threshold (p95) |
|----------|--------|----------|----------|----------|-----------------|
| `/v1/chat/completions` (non-stream) | POST | <100 | <5000 | <8000 | 5000 ms |
| `/v1/chat/completions` (stream) | POST | <100 | <5000 | <8000 | 5000 ms |
| `/v1/health/live` | GET | <10 | <200 | <400 | 200 ms |
| `/v1/models` | GET | <20 | <500 | <800 | 500 ms |

**Note:** With real services, add:

| Service | Expected Latency | Notes |
|---------|-----------------|-------|
| Qdrant dense search | 5–30 ms | Depends on collection size and HNSW params |
| Qdrant sparse search | 10–50 ms | bge-m3 sparse encoding is CPU-bound |
| Embedder (bge-m3, CPU) | 50–200 ms | Single query, 1024-d |
| Embedder (bge-m3, GPU) | 5–20 ms | Single query, 1024-d |
| Cross-encoder rerank (CPU) | 150–400 ms | 20 pairs, MiniLM-L-6-v2 |
| Cross-encoder rerank (GPU) | 20–50 ms | 20 pairs, MiniLM-L-6-v2 |
| LLM generation (vLLM) | 500–3000 ms | Depends on model, prompt length, max_tokens |
| Redis cache lookup | <1 ms | Network RTT included |

**Expected total E2E latency (real services, CPU):**

| Scenario | p50 | p95 |
|----------|-----|-----|
| Simple query, cached | 200 ms | 500 ms |
| Simple query, no cache | 800 ms | 2000 ms |
| Complex query, graph expansion | 1500 ms | 4000 ms |
| Streaming TTFT | 600 ms | 1500 ms |

---

## Regression Detection

### CI Integration

Add to your CI pipeline:

```yaml
# .github/workflows/benchmark.yml
- name: Run latency benchmarks
  run: |
    python scripts/run_benchmarks.py \
      --compare tests/performance/latency_benchmarks.json \
      --fail-on-regression

- name: Upload benchmark report
  uses: actions/upload-artifact@v4
  with:
    name: benchmark-report
    path: tests/performance/latency_benchmarks.*
```

### Regression Thresholds

| Severity | p95 Delta | Action |
|----------|-----------|--------|
| OK | <10% | No action needed |
| Warning | 10–20% | Investigate in PR review |
| Regression | >20% | Block merge, must fix |
| Critical | >50% | Revert immediately |

### Updating Baselines

After confirmed improvements (e.g., new caching, algorithm optimization):

```bash
# Run benchmarks and save as new baseline
python scripts/run_benchmarks.py --output tests/performance
git add tests/performance/latency_benchmarks.json
git commit -m "perf: update latency baselines"
```

---

## Tuning Recommendations

### If Embedding Cache Hit >0.1ms

- Reduce `EmbeddingCache.max_size` (default: 1000)
- Switch to LRU eviction instead of FIFO
- Consider using Redis for shared cache across workers

### If RRF Fusion >2ms for 50 Hits

- Pre-sort input lists (already sorted from Qdrant)
- Use NumPy vectorized RRF instead of Python dict operations
- Consider reducing `top_k` from 50 to 30 for non-critical queries

### If ColBERT Score >50ms for 20×50

- Reduce token dimensions (64-d vs 128-d)
- Pre-filter documents with bi-encoder before ColBERT
- Batch ColBERT scoring on GPU if available

### If Deduplication >20ms for 200 Chunks

- Add Bloom filter pre-filtering for exact hash matches
- Reduce retrieval `top_k` to limit input size
- Use set-based dedup on truncated text (first 200 chars)

### If Context Build >30ms for 15 Chunks

- Pre-compute chunk hashes at indexing time
- Reduce metadata verbosity in context headers
- Use string builder pattern instead of repeated concatenation

### If Graph Traversal >10ms for 2 Hops

- Limit entity map connectivity (max 10 neighbors per entity)
- Add entity importance scoring to prune low-value paths
- Cache graph traversal results for repeated entity sets

---

## Related Documentation

- [Performance & Quality Best Practices](performance-quality.md) — HNSW tuning, quantization, caching
- [Monitoring Guide](monitoring-guide.md) — Prometheus metrics, Grafana dashboards
- [Operations Guide](operations-guide.md) — Production runbooks, SLOs
- [Disaster Recovery Runbook](disaster-recovery-runbook.md) — Failure scenarios and recovery
