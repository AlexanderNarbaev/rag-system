# Block B. Hybrid Search and Ranking (FR-09 — FR-18)

---

## FR-09. Hybrid search — dense + sparse RRF

**Description:**
The system performs hybrid search, combining:

- **Dense** — vector search over 1024-dimensional BGE-M3 embeddings
- **Sparse** — lexical search over sparse vectors (BM25-style, also from BGE-M3)
- **Fusion** — results are merged via Reciprocal Rank Fusion (RRF) with k=60

RRF formula: `score(d) = Σ 1/(k + rank_i(d))` where k=60, summed over all search methods.

**Acceptance criteria:**

1. A search query returns results from both methods (dense and sparse)
2. The RRF score of each result is the sum of ranks from both methods
3. The final list is sorted by RRF score (descending)
4. The `hybrid_search()` function returns Qdrant ScoredPoints with payload

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR09HybridSearch`)
**Priority:** CRITICAL
**Reference:** ADR-001, ADR-002

---

## FR-10. Cross-encoder reranking

**Description:**
After hybrid search of the top-N results (50 by default), the system reranks them
using the BGE-Reranker-v2-m3 cross-encoder model. The cross-encoder takes a
(query, document) pair and outputs a relevance score. This is more accurate than a
bi-encoder but slower, so it is applied only to the top-N.

Parameters: `batch_size=32`, BGE-Reranker-v2-m3 model (100+ languages supported).

**Acceptance criteria:**

1. After reranking, the order of the top-20 results differs from the original (the reranker reorders)
2. Results with low relevance are filtered out
3. The `rerank_chunks()` function returns sorted indices

**Status:** ✅ Confirmed (`proxy/app/core/rerank.py`)
**Priority:** CRITICAL
**Reference:** ADR-002

---

## FR-11. Content-based deduplication (SHA-256)

**Description:**
During context assembly, the system removes duplicate chunks using the SHA-256 hash
of the content. If two chunks have the same hash, only one is kept (the one with the
higher score). This prevents the same text from repeating in the context.

**Acceptance criteria:**

1. Two identical chunks — only one remains in the context
2. Two similar (but not identical) chunks — both remain
3. The `deduplicate_chunks()` function reduces the chunk count when duplicates exist

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR11Deduplication`)
**Priority:** CRITICAL
**Reference:** ADR-005

---

## FR-12. Version-aware filtering

**Description:**
Each chunk in Qdrant has a `version` field (a string, e.g., "v1", "v2"). The
`rag_version` parameter filters search results, returning only chunks of the specified
version. If no version is specified, chunks of the latest version are returned.
Filtering takes into account not only the version but also the chunk's ACL metadata
(access_level, allowed_groups, allowed_users).

**Acceptance criteria:**

1. `rag_version="v1"` — all returned chunks have `version="v1"`
2. Without the parameter — chunks of any version are returned (latest takes priority)

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR12VersionFiltering`)
**Priority:** CRITICAL
**Reference:** ADR-005

---

## FR-13. Embedding caching

**Description:**
User query embeddings are cached at two levels:

- In-memory LRU cache (fast, lost on restart)
- Redis (optional, persistent)

The cache key is the MD5 hash of the query text. On a repeated request, the embedding
is taken from the cache without calling the model.

**Acceptance criteria:**

1. A repeated request with the same text — the embedding is taken from cache (log: "Embedding cache hit")
2. The `rag_cache_hit_ratio{cache_type="embedding"}` metric ≥ 60% on repeated requests

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR13EmbeddingCache`)
**Priority:** CRITICAL
**Reference:** ADR-001

---

## FR-14. ColBERT late-interaction retrieval

**Description:**
BGE-M3 produces not only dense embeddings (1024-dim) but also ColBERT vectors —
multiple vectors per token. ColBERT enables more accurate relevance computation
through late interaction (comparing token-level vectors).

The system supports ColBERT as an additional search channel in hybrid mode.

**Acceptance criteria:**

1. ColBERT search returns results
2. Results are combined with dense/sparse via RRF

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR14ColBERT`)
**Priority:** HIGH
**Reference:** roadmap Phase 1

---

## FR-15. Knee-point pruning

**Description:**
After hybrid search, the system analyzes the score distribution and prunes
results below the "knee point" — the point of a sharp relevance drop. This removes
noisy results that only bloat the context.

**Acceptance criteria:**

1. When a distinct knee point exists — results below it are pruned
2. With a uniform distribution — all results are kept
3. The number of results after pruning ≤ the number before pruning

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR15KneePointPruning`)
**Priority:** HIGH
**Reference:** roadmap Phase 2

---

## FR-16. FLARE — Forward-Looking Active Retrieval

**Description:**
During answer generation, the system detects whether the LLM generates an "uncertain"
token (probability < threshold). If so, the system pauses generation, forms a new
search query from the already generated text, retrieves additional chunks, and
continues generation with the expanded context.

**Acceptance criteria:**

1. During low-confidence generation — an additional search is triggered
2. Generation continues with the new chunks
3. The final answer contains information from the additional chunks

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR16FLARE`)
**Priority:** HIGH
**Reference:** roadmap Phase 5

---

## FR-17. Two-stage reranking

**Description:**
Two-stage ranking:

1. First stage — fast bi-encoder (BGE-M3) for coarse filtering top-100 → top-50
2. Second stage — precise cross-encoder (BGE-Reranker-v2-m3) for the final top-50 → top-20

This reduces latency compared to a single-pass cross-encoder over all results.

**Acceptance criteria:**

1. nDCG@10 of two-stage ranking ≥ nDCG@10 of single-pass
2. Two-stage latency < single-pass latency (with top-100 input)

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR17TwoStageReranking`)
**Priority:** HIGH
**Reference:** roadmap Phase 5

---

## FR-18. SLM-based dynamic top-k

**Description:**
The SLM classifies query complexity (simple/medium/complex). Based on the
classification, the number of chunks to retrieve is selected dynamically:

- simple → top_k=5 (less context, faster)
- medium → top_k=10
- complex → top_k=20

This reduces latency for simple queries and improves quality for complex ones.

**Acceptance criteria:**

1. A simple query (e.g., "what is the date?") — ≤ 5 chunks retrieved
2. A complex query (e.g., "compare the architecture of X and Y") — ≥ 15 chunks retrieved
3. The log contains "Query classified as 'simple'/'complex'"

**Status:** ✅ Confirmed (`tests/proxy/test_core_api.py::TestFR18DynamicTopK`)
**Priority:** HIGH
**Reference:** roadmap Phase 3
