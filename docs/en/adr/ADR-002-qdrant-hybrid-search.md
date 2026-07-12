# ADR-002: Qdrant for Vector Storage with Hybrid Search

**Status:** Accepted
**Date:** 2026-06-22

## Context

The RAG system needs a vector database that supports hybrid search (dense semantic + sparse lexical), handles incremental document updates with versioning, and operates in an air-gapped Docker environment. Technical documents from Confluence, Jira, and GitLab require both exact keyword matching (ticket numbers, code identifiers) and semantic understanding.

Alternatives evaluated: **Milvus** (heavier deployment, immature sparse support at decision time), **Weaviate** (hybrid search but GraphQL-only API, extra complexity), **Pinecone** (SaaS — incompatible with air-gapped requirement), **pgvector** (PostgreSQL extension — no native sparse vector support, limited hybrid RRF). **Elasticsearch** was excluded as it lacks native dense vector capabilities without separate plugins.

## Decision

**Use Qdrant as the primary vector store with hybrid search via Reciprocal Rank Fusion (RRF).** The collection is configured with dual vector types: `dense` (1024-dim, cosine distance) and `sparse` (on-disk index) — configured in `etl/indexer/qdrant_hybrid.py`.

RRF fusion merges dense and sparse result lists in `proxy/app/core/retrieval.py`, using `k=60` to balance rank bias. Sparse index is stored on-disk (`SparseIndexParams(on_disk=True)`) to reduce RAM usage on the proxy machine.

Collection creation supports version-aware filtered queries via Qdrant's `FieldCondition` on the `version` field (`proxy/app/core/retrieval.py`), enabling retrieval of specific document versions when requested.

Quantization (binary/scalar) and HNSW tuning (`ef_construct`, `m`) are deferred defaults; Qdrant's defaults provide adequate performance for <1M chunks.

## Consequences

**Positive:** Single deployment for both dense and sparse search, no separate BM25 index needed. On-disk sparse index keeps RAM under 8 GB for the proxy machine. REST API (`qdrant-client` HTTP at port 6333) simplifies integration with the FastAPI proxy. Incremental upsert by chunk hash enables live document updates without full reindexing.

**Negative:** Qdrant lacks built-in cross-encoder reranking — our pipeline adds this separately via `proxy/app/core/rerank.py`. No native graph traversal (addressed by Neo4j integration). Disk-based sparse index is slower than in-memory for very large collections (>10M points).

**Mitigations:** Cross-encoder reranking post-retrieval compensates for RRF fusion limitations. Cache layer (`proxy/app/shared/cache.py`) reduces repeated identical queries. Monitoring via `/v1/health` endpoint (`proxy/app/api/health.py`) checks Qdrant connectivity on every health probe.
