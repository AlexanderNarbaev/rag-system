# ADR-001: Choosing BAAI/bge-m3 as the Embedding Model

**Status:** Accepted
**Date:** 2026-06-22

## Context

The RAG system requires an embedding model capable of producing both dense and sparse vectors for hybrid search, supporting multilingual technical documents (Russian and English) from Confluence, Jira, and GitLab sources. The environment is air-gapped — models must be downloadable once and run offline. Key requirements: 8192 token context (technical documents often exceed 512 tokens), dense + sparse output in a single pass, and cross-lingual retrieval quality.

Alternatives evaluated: `text-embedding-3-small` (OpenAI API — requires internet, no sparse vectors), `e5-mistral-7b-instruct` (larger model, higher VRAM, no native sparse), `multilingual-e5-large` (dense only), and `sentence-transformers/all-MiniLM-L6-v2` (512 token limit, English only).

## Decision

**Use `BAAI/bge-m3` as the sole embedding model.** It provides dense (1024-dim), sparse (lexical BM25-style), and ColBERT-style multi-vector representations in a single encode call. The model supports 100+ languages and 8192 token input context.

Implementation in code:
- `proxy/app/core/retrieval.py` loads `SentenceTransformer(EMBEDDER_MODEL, device=EMBEDDER_DEVICE)` with `BAAI/bge-m3` as default.
- `etl/indexer/qdrant_hybrid.py` loads the same model for ETL indexing with `encode_sparse()` used to extract sparse vectors.
- Dense vectors are used for semantic cosine search; sparse vectors for lexical BM25 over the same collection with RRF fusion in `proxy/app/core/retrieval.py`.

## Consequences

**Positive:** Single model for both indexing and query-time retrieval; no synchronization needed between separate dense/sparse models. Sparse vector index stored on-disk keeps memory footprint low. Air-gapped compatible — model weights downloaded once to a shared volume.

**Negative:** The model (~2.2 GB) is larger than pure dense alternatives like `all-MiniLM-L6-v2` (~90 MB). Sparse vectors increase collection storage by ~30%. ColBERT multi-vectors are not currently utilized in the pipeline (deferred optimization).

**Mitigations:** Embeddings are cached via Redis/in-memory (`proxy/app/shared/cache.py`), reducing recomputation. CPU inference is acceptable for the ETL batch path; GPU acceleration is optional via `EMBEDDER_DEVICE=cuda` (`proxy/app/shared/config.py`).
