# Performance & Quality Best Practices

## 1. Retrieval Performance

### 1.1 Qdrant HNSW Tuning

The HNSW index governs search speed vs. recall trade-off. Tune per collection size:

| Collection Size | ef_construct | ef_search | m | Expected Recall@10 |
|---|---|---|---|---|
| <100K vectors | 128 | 64 | 16 | >0.98 |
| 100K–1M vectors | 200 | 128 | 24 | >0.96 |
| >1M vectors | 256 | 200 | 32 | >0.94 |

Set via Qdrant collection creation:
```python
models.HnswConfigDiff(ef_construct=200, m=24, ef=128)
```

**On-disk mode** for sparse vectors: Set `on_disk_payload=True` and `on_disk=True` in collection config. For bge-m3 sparse vectors (up to 250K dimensions per vector), on-disk indexing reduces RAM usage by 60% with only ~5% latency increase.

### 1.2 Quantization Strategies

| Strategy | RAM Reduction | Recall Impact | When to Use |
|---|---|---|---|
| Scalar (int8) | 4× | <1% | Default for production, always enable |
| Product (PQ) | 16× | 2–4% | Use for >5M vectors, budget-constrained RAM |
| Binary (BQ) | 32× | 5–8% | Use for >10M vectors, retrieval is pre-filtered |

Enable scalar quantization as default:
```python
models.ScalarQuantization(scalar=models.ScalarQuantizationConfig(type=models.ScalarType.INT8))
```

### 1.3 Query Batching

For multi-query scenarios (parallel user requests, query decomposition), batch dense embeddings:

```python
vectors = embedder.encode(queries, batch_size=32, normalize_embeddings=True)
```
Use `batch_size=32` for GPU (max throughput), `batch_size=8` for CPU (lower memory pressure).

### 1.4 Cache Hit Ratio Optimization

Current cache key design in `retrieval.py:89` uses `md5(text.encode()).hexdigest()`. Improvements:

| Cache Tier | Key Pattern | TTL | Expected Hit Rate |
|---|---|---|---|
| Embedding | `embed:{md5(text)}` | 1 hour | 15–25% (query rewriting helps) |
| Search result | `search:{md5(query)}:{version}:{top_k}` | 5 min | 5–10% |
| LLM answer | `llm:{md5(prompt)}` | 10 min | 3–8% (semantic dedup) |
| Rerank scores | `rerank:{md5(query)}:{md5(chunk_ids)}` | 5 min | 8–12% |

Redis recommended config: `maxmemory 2GB`, `maxmemory-policy allkeys-lru`.

---

## 2. Inference Optimization

### 2.1 Embedding Batching

`SentenceTransformer.encode()` batch sizing:
- **GPU (24GB VRAM)**: `batch_size=64` for bge-m3, 9ms per batch
- **CPU (32 cores)**: `batch_size=16`, parallelize with `pool` processes
- **Mixed**: GPU for dense, CPU for sparse (bge-m3 sparse encoding is CPU-bound)

Enable `show_progress_bar=False` in production to avoid tqdm overhead.

### 2.2 Reranker Trade-off

Current reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2` (80M params, `proxy/app/config.py:25`).

| Model | Latency per pair | MRR Improvement | VRAM |
|---|---|---|---|
| MiniLM-L-6-v2 (current) | 8ms | +15% over dense | 0.5GB |
| MiniLM-L-12-v2 | 15ms | +18% | 1GB |
| bge-reranker-v2-m3 | 25ms | +22% | 2GB |

**Recommendation**: Stay with MiniLM-L-6-v2 for <50 chunks. Switch to bge-reranker-v2-m3 only if MRR drops below 0.75 in monitoring. Batch reranker inputs at `batch_size=32`.

### 2.3 LLM Inference

Your configured LLM via the backend adapter with these optimizations:

| Setting | Value | Rationale |
|---|---|---|
| `--max-model-len` | 131072 | Match model's max context |
| `--gpu-memory-utilization` | 0.92 | Leave 8% for KV-cache spikes |
| `--enable-prefix-caching` | true | Reuse system prompt KV state |
| `--max-num-seqs` | 4 | Concurrent requests for RAG proxy |
| `--dtype` | awq (4-bit) | AWQ quantization reduces VRAM significantly |

AWQ quantization: 4-bit with group size 128, keeps perplexity within 1% of FP16. For GPU with <16GB VRAM, mandatory.

### 2.4 SLM vs LLM Routing

The dual-model architecture routes queries:
- **SLM (your lightweight model)**: Query rewriting, entity extraction (fast path, <50ms)
- **LLM (your full-scale model)**: Final answer generation (slow path, 2–8s)

Routing heuristic: if `llm_router` detects a query requiring only fact retrieval (no reasoning), answer directly from retrieved context without LLM call — saves 2–3s latency.

### 2.5 Streaming Chunk Size

For `stream=True` responses, output chunks of **16–32 tokens** (default for most backends is 16). This provides smooth UX without excessive HTTP frame overhead.

---

## 3. Memory Management

### 3.1 Model Offloading

| Model | GPU VRAM | CPU RAM | Strategy |
|---|---|---|---|
| bge-m3 (embedder) | 2.2GB | 0 | Keep on GPU permanently |
| MiniLM-L-6-v2 (reranker) | 0.5GB | 0 | Keep on GPU |
| Your LLM (quantized) | varies | 0 | GPU only, backend managed |
| Your SLM (lightweight) | ~1.8GB | 0 | GPU if VRAM available, else CPU |
| spaCy ru_core_news_sm | 0 | 50MB | CPU only |

Total GPU VRAM budget: varies by model choice. If using 16GB card, move SLM to CPU and reduce `gpu-memory-utilization` to 0.88.

### 3.2 Embedding Cache Sizing

In-memory embedding cache (`retrieval.py:88-95`): with 100K documents and 10 chunks each, expect ~500K unique query+chunk embeddings. At 1024 floats per dense vector × 4 bytes = 4KB each → **2GB** for dense embedding cache. Set Redis `maxmemory 2GB` with TTL-based eviction to stay within budget.

### 3.3 Redis Memory Policy

```
maxmemory 2gb
maxmemory-policy allkeys-lru
```
`allkeys-lru` ensures high hit rate for embeddings and search results. Monitor with `INFO stats` — target `evicted_keys` near zero. If evictions > 100/hour, increase `maxmemory` to 4GB or reduce embedding TTL from 3600s to 1800s.

### 3.4 ETL Memory Profiling

Python ETL pipeline memory hotspots:
- **spaCy**: `nlp.pipe(texts, batch_size=50)` instead of sequential `nlp(text)` to cut memory by 40%
- **SentenceTransformer**: Explicitly call `torch.cuda.empty_cache()` after each batch of 100 chunks
- **Neo4j loading**: Use `UNWIND $batch` with `batch_size=500` (already implemented in `neo4j_loader.py:34`)

Profile with `memory_profiler`:
```python
@profile
def extract_batch(self, chunks): ...
```

---

## 4. Pipeline Quality

### 4.1 Chunker Quality Metrics

Evaluate the semantic chunker (`etl/chunker/semantic_chunker.py`) on:

| Metric | Target | Measurement |
|---|---|---|
| Semantic coherence (cosine intra-chunk) | >0.75 | Mean cosine similarity of sentences within a chunk |
| Boundary precision | >0.85 | % of chunk boundaries at section/heading breaks |
| Overlap ratio | 10–15% | Tokens shared between consecutive chunks |
| Chunk size (tokens) | 256–1024 | P50: 512, P95: 900 |

### 4.2 Retrieval Quality (Offline Evaluation)

Run weekly against a labeled evaluation set of 200+ query–document pairs:

| Metric | Baseline (dense only) | Target (hybrid+rerank) |
|---|---|---|
| MRR (Mean Reciprocal Rank) | 0.62 | >0.80 |
| nDCG@10 | 0.55 | >0.75 |
| Recall@20 | 0.78 | >0.90 |
| Recall@50 | 0.85 | >0.95 |

### 4.3 Reranker Impact

Measure delta: `MRR_rerank − MRR_dense`. If delta < 0.10, the reranker is not adding enough value — investigate whether retrieval is already returning near-perfect ranking (unlikely) or if the reranker model is mismatched to the domain. Consider fine-tuning on in-domain relevance judgments from HITL data.

### 4.4 Hallucination Detection

Implement context grounding score:
```python
grounding_score = cos_sim(embed(answer), embed(context))
```
- Score > 0.7: Well-grounded
- Score 0.4–0.7: Partial grounding, flag for HITL review
- Score < 0.4: Likely hallucination, return "I don't have enough information"

Log grounding score with every generation for monitoring.

### 4.5 Retrieval Sufficiency

The `check_sufficiency` node in `orchestrator.py:127-146` uses a simple heuristic (`avg_score < 0.6`). Upgrade to LLM-based evaluation:

```python
sufficiency_prompt = f"""
Query: {query}
Retrieved context summary (10 chunks):
{[c['text'][:200] for c in chunks]}

Does this context contain enough information to answer the query?
Answer YES or NO with confidence 0-100.
"""
```
If confidence < 70, trigger graph expansion. If < 50, trigger query rewrite loop (capped at `MAX_RETRIEVAL_LOOPS=3`).

---

## 5. Monitoring & Observability

### 5.1 Key Metrics

| Metric | Collection Method | Alert Threshold |
|---|---|---|
| Proxy latency p50/p95/p99 | Middleware timer | p95 > 5s (warn), p95 > 10s (crit) |
| Qdrant search latency | `qdrant_client.search()` timer | p95 > 200ms |
| LLM generation latency (TTFT) | Time to first token | p50 > 3s |
| Cache hit ratio | Redis `INFO stats` | <15% (investigate key design) |
| Error rate (5xx) | FastAPI middleware | >1% of requests |
| Graph expansion latency | `graph_expand_query()` timer | p95 > 500ms |
| Reranker batch latency | Timer in `rerank.py` | >100ms per batch |

### 5.2 Structured Logging

All logs in JSON format with consistent fields:
```json
{"timestamp": "2026-06-22T10:30:00Z", "level": "INFO", "component": "retrieval",
 "query_hash": "a1b2c3", "action": "hybrid_search", "latency_ms": 45, "results_count": 50}
```
Use `python-json-logger` or `structlog`. Redact `LLM_API_KEY` and `NEO4J_PASSWORD` from logs (masked via `SENSITIVE_SECRETS` config).

### 5.3 Health Check Endpoints

`/v1/health` — comprehensive health:
```json
{
  "status": "healthy",
  "components": {
    "qdrant": "ok",
    "redis": "ok",
    "neo4j": "ok",
    "embedder": "ok",
    "reranker": "ok",
    "llm": "ok"
  },
  "latency_ms": {"qdrant_ping": 2, "redis_ping": 1, "neo4j_ping": 5},
  "uptime_seconds": 3600
}
```

`/v1/health/live` — liveness probe (HTTP 200 if process alive). `/v1/health/ready` — readiness probe (all components connected).

### 5.4 Prometheus Integration

Expose metrics at `/metrics` with `prometheus_fastapi_instrumentator`:
- `rag_search_latency_seconds` (histogram, labels: `{type: dense|sparse|fusion}`)
- `rag_cache_hits_total` / `rag_cache_misses_total` (counter)
- `rag_llm_tokens_total` (counter, labels: `{type: prompt|completion}`)
- `rag_graph_expansions_total` (counter, labels: `{status: success|failure}`)
- `rag_retrieval_loops` (histogram, count of rewrite-retrieve loops per query)

---

## 6. Scalability

### 6.1 Horizontal Scaling

Proxy layer is stateless (session state in Redis, LangGraph checkpointer in MemorySaver/RedisSaver). Scale:
- **Docker Compose**: `docker-compose up -d --scale rag-proxy=3`
- **Kubernetes**: HPA on CPU >70% or request latency p95 >3s
- **Load balancing**: Round-robin at nginx/HAProxy layer, no sticky sessions needed

### 6.2 Qdrant Sharding

For collections >10M vectors:
```python
models.CreateCollection(
    shard_number=4,
    replication_factor=2,
    ...
)
```
- **Shard count**: 4 shards for 10M–50M vectors, 8 shards for >50M
- **Replication factor**: 2 (tolerates 1 node failure)
- Each shard: ~2.5M vectors at 1024-dim = ~10GB RAM (with scalar quantization)

### 6.3 ETL Parallelization

Source-level parallelism in `scheduler/run_etl.py`:
- **Confluence**: 3 workers (rate-limited by API, 10 req/s)
- **Jira**: 5 workers (issue-level parallelism)
- **GitLab**: 3 workers (commit-level + file-level)

Use `concurrent.futures.ProcessPoolExecutor(max_workers=8)` for chunking/embedding stages. Separate GPU-accelerated embedding into a dedicated worker pool to avoid CUDA OOM.

### 6.4 Cold Storage Tiering

`LiveVectorLake` (`etl/indexer/live_vector_lake.py`): Keep current version (+1 prior) in Qdrant (hot). Move versions older than 2 epochs to on-disk Parquet files with manifest tracking. Query with `version=` parameter falls back to cold storage lookup (50–200ms latency) with transparent caching.

---

## 7. Resilience

### 7.1 Retry Logic

Exponential backoff with jitter:

| Service | Max Retries | Base Delay | Max Delay | Jitter |
|---|---|---|---|---|
| LLM backend | 3 | 1s | 30s | ±20% |
| Qdrant | 5 | 100ms | 5s | ±50% |
| Neo4j | 3 | 500ms | 10s | ±25% |
| Embedder (local) | 0 | — | — | No network, no retry |

Already implemented in `neo4j_loader.py:83` for Neo4j. Extend pattern to LLM and Qdrant calls.

### 7.2 Circuit Breaker Pattern

Protect against cascading failures:
- **Qdrant circuit**: Open after 5 consecutive failures in 30s window. Half-open after 60s, test with 1 probe request.
- **Neo4j circuit**: Open after 3 failures in 20s window. Half-open after 45s.
- **LLM circuit**: Open after 3 timeouts in 60s window. Half-open after 90s.

Use `pybreaker` library or manual implementation with `asyncio.Event` flags.

### 7.3 Graceful Degradation

| Component Failed | Degradation Mode | User Impact |
|---|---|---|
| Neo4j unavailable | Skip graph_expand, serve vector-only context | Slightly less connected answers |
| Reranker OOM/error | Skip rerank, use raw hybrid scores | Top-5 chunks slightly less precise |
| Redis unavailable | Fall back to InMemoryCache | Cold-start latency spike (~100ms→500ms) |
| LLM timeout | Return "Service temporarily degraded, retry in 30s" | User retries |
| Qdrant unavailable | Return 503 with Retry-After header | Full outage |

Proxy must never crash on component failure — always return the best available answer.

### 7.4 WAL-Based Recovery for ETL

The ETL pipeline uses a Write-Ahead Log at `etl/scheduler/wal/`:
- Before each extraction step, write `{source}_{timestamp}_{checkpoint}.wal` with source, batch info, progress
- On crash/restart, replay WAL to find last committed checkpoint
- Resume extraction from `last_processed_id` in checkpoint
- Cleanup WAL entries older than 7 days

Implemented as `CheckpointManager` in scheduler with:
```python
wal_format = {
    "source": "confluence",
    "batch_id": 42,
    "last_processed_id": "page_12345",
    "entities_loaded": 15600,
    "timestamp": "2026-06-22T10:30:00Z"
}
```

---

## 8. Multi-Modal & ColBERT Performance (v0.5)

### 8.1 ColBERT Late Interaction

bge-m3 ColBERT multi-vector retrieval provides higher precision than dense-only search by computing token-level MaxSim interactions:

```python
from etl.indexer.qdrant_hybrid import QdrantHybridIndexer

indexer = QdrantHybridIndexer(collection_name="knowledge_base")
indexer.index_with_colbert("def hello(): return 'world'")
results = indexer.search_colbert("python hello function", limit=10)
```

**Performance characteristics:**
- Storage: ~100× more vectors per document (one per token vs one per doc)
- Latency: 30-80ms additional vs dense search (with ColBERT enabled)
- Recall@20: +3-5% improvement over dense+sparse hybrid alone
- Requires: Qdrant 1.10+ with multi-vector support

### 8.2 Evaluation Metrics

Run automated retrieval quality evaluation:

```bash
python proxy/app/evaluation.py --eval-dataset data/eval_queries.json --top-k 20
```

Output metrics:
- **MRR** (Mean Reciprocal Rank): Expected ≥0.75 for production
- **Recall@20**: Expected ≥0.85 for production
- **nDCG@10**: Expected ≥0.70 for production
- **Precision@5**: Expected ≥0.80 for production

### 8.3 Grounding Score

NLI-based factual grounding check prevents hallucinations:

```python
from proxy.app.grounding import compute_nli_grounding

report = compute_nli_grounding(answer_text, context_text)
# report.supported_claims, report.unsupported_claims, report.overall_score
```

- Score ≥0.7: Well-grounded, safe to return
- Score 0.4-0.7: Flag for HITL review, return with `rag_confidence` warning
- Score <0.4: Return "I don't have enough information to answer this accurately"

### 8.4 Reranker Fine-Tuning from HITL

Fine-tune the cross-encoder on domain-specific relevance judgments:

```python
from proxy.app.rerank import collect_training_pairs, fine_tune_reranker

pairs = collect_training_pairs()          # From /v1/feedback logs
if len(pairs) > 500:
    fine_tune_reranker(pairs, epochs=3)   # Saves to FT_MODEL_DIR
```

Expected MRR improvement: ≥5% after 500+ expert corrections.
