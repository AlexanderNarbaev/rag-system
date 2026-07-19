# ADR-005: Version-Aware Document Indexing

**Status:** Accepted
**Date:** 2026-06-22

## Context

Corporate knowledge sources (Confluence pages, Jira issues, GitLab merge requests) are continuously updated. A naive "
reindex everything" approach wastes compute and produces stale results between ETL runs. Users need the ability to query
specific document versions (e.g., "as of Q3 2025") and the system must avoid showing conflicting versions of the same
document simultaneously. The ETL pipeline runs periodically on a separate machine; the proxy must reflect updates within
minutes.

Alternatives considered: **full reindexing per ETL run** (wasteful, high latency), **timestamp-based diff** (brittle,
clock skew issues), **document-level version APIs** (not all sources provide them — Jira and GitLab APIs lack proper
versioning primitives).

## Decision

**Implement content-addressable chunk versioning via SHA-256 hashing with a LiveVectorLake hot/cold storage pattern and
WAL-based incremental checkpointing.**

The `ChunkVersionStore` (`etl/chunker/hash_versioning.py`) computes SHA-256 hashes over chunk content and key metadata.
The hash serves as the Qdrant point ID, making every chunk uniquely addressable. Incremental updates compare new chunk
hashes against the WAL-stored last-known state, returning only added and deleted hashes.

`LiveVectorLake` (`etl/indexer/live_vector_lake.py`) stratifies storage: hot layer (Qdrant — current chunks for fast
search) and cold layer (Parquet/Delta Lake — complete version history with timestamps). The `sync_document()` method
coordinates both layers: new chunks are upserted to Qdrant, deleted chunks removed, and all changes appended to cold
storage.

WAL (`etl/indexer/wal_manager.py`) tracks per-pipeline checkpoints (Confluence, Jira, GitLab, Indexing, Graph), enabling
resume-after-failure without data loss. The ETL orchestrator (`etl/scheduler/run_etl.py`) updates WAL after indexing
completes.

Version-pinned retrieval is supported via Qdrant filter on the `version` payload field (`proxy/app/core/retrieval.py`),
exposed through the proxy's `rag_version` parameter.

## Consequences

**Positive:** Incremental updates reduce ETL runtime from hours to minutes for large repositories. Content
addressability eliminates duplicates — same content across sources shares the same hash. Rollback support via cold
storage (`live_vector_lake.py:169-209`). Hot/cold separation reduces Qdrant storage costs.

**Negative:** SHA-256 computation adds ~5ms per chunk during ETL. Cold storage (Parquet files) grows unboundedly;
cleanup is manual. Hash collisions are theoretically possible but practically negligible with SHA-256. WAL corruption
requires manual intervention (`--reset-wal` flag in `run_etl.py`).

**Mitigations:** `force_reindex` in `run_etl.py` bypasses WAL for disaster recovery. Version-aware deduplication at
retrieval time (`proxy/app/core/context/builder.py`) resolves same-document conflicts by preferring newer versions or
explicit user requests.
