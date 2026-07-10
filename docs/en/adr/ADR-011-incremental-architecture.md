# ADR-011: Incremental/Progressive Architecture

**Status:** Accepted
**Date:** 2026-07-10

## Context

The RAG system serves corporate users with diverse deployment environments — from air-gapped on-premise servers to cloud-hosted clusters. Not every deployment needs the full feature set: a small team testing RAG concepts does not need Neo4j graph expansion, Redis caching, or LangGraph agentic orchestration. Meanwhile, production deployments at scale require all of these components working together.

Research into competitive RAG solutions (2026-06-26) revealed that most open-source RAG frameworks fall into two extremes: either too simple (basic vector search + LLM, no hybrid search, no reranking) or too complex (mandatory Kubernetes, mandatory graph DB, steep learning curve). Neither extreme serves the progressive adoption pattern our users need.

Key research findings:
- **RAG best practices**: Hybrid search (dense + sparse) with RRF fusion consistently outperforms pure vector search by 15-25% on technical document retrieval benchmarks. Cross-encoder reranking adds another 10-15% precision at the cost of latency.
- **Self-improving RAG**: Feedback loops (HITL correction → enrichment → re-indexing) create a virtuous cycle where system quality improves over time without manual intervention. However, this requires optional complexity — the feedback loop must not block basic usage.
- **Competitive analysis**: Production RAG systems that succeed share a pattern: simple core with opt-in complexity layers. Systems that mandate all components upfront have higher abandonment rates during evaluation.

The existing codebase already reflects this pattern informally — `USE_LANGGRAPH`, `GRAPH_ENABLED`, `USE_REDIS` flags — but there is no architectural decision documenting why this pattern was chosen and how it should guide future development.

## Decision

**Adopt an explicit incremental/progressive architecture where the system runs with a minimal core (FastAPI + Qdrant + LLM) and every additional component is optional and degrades gracefully when absent.**

The architecture has three tiers:

### Tier 1 — Minimal Core (always required)
- FastAPI proxy with OpenAI-compatible `/v1/chat/completions` endpoint
- Qdrant for vector search (dense embeddings)
- Any OpenAI-compatible LLM backend (vLLM, llama.cpp, or remote API)
- Basic configuration via environment variables

This tier provides a working RAG system with zero additional infrastructure.

### Tier 2 — Enhanced Retrieval (opt-in, recommended for production)
- Hybrid search: dense + sparse vectors with RRF fusion (`BAAI/bge-m3` sparse encoding)
- Cross-encoder reranking (`MiniLM-L-6-v2`)
- Redis caching for embeddings and responses
- Version-aware document indexing with WAL checkpointing
- Token optimization with BPE-aware budget allocation

Enabled via: `USE_REDIS=true`, explicit Qdrant sparse vector configuration.

### Tier 3 — Advanced Orchestration (opt-in, for mature deployments)
- LangGraph agentic pipeline with tool calling
- Neo4j graph expansion for multi-hop entity relationships
- SLM router for intent classification and query decomposition
- HITL feedback loop with self-enrichment
- Model evolution pipeline (LoRA fine-tuning, canary deployment)

Enabled via: `USE_LANGGRAPH=true`, `GRAPH_ENABLED=true`, separate SLM endpoint.

Each tier is independently deployable. Components fail independently — Neo4j being down does not prevent chat completion; Redis being unavailable falls back to in-memory cache; LangGraph errors fall back to simple RAG pipeline.

Implementation evidence in codebase:
- `proxy/app/main.py:78-80` — `USE_LANGGRAPH`, `USE_REDIS` flags control feature activation
- `proxy/app/core/retrieval.py` — graph expansion wrapped in `if GRAPH_ENABLED` guards
- `proxy/app/shared/cache.py` — CacheManager gracefully degrades when Redis URL is not set
- `proxy/app/core/orchestrator.py` — LangGraph pipeline with fallback to simple retrieval
- `proxy/app/shared/config.py` — all advanced features default to `False`

## Consequences

**Positive:**
- **Low barrier to entry**: New users can run `docker-compose up` with minimal `.env` and get a working RAG system in minutes.
- **Incremental adoption**: Teams can enable features as they grow — start with Tier 1, add Redis and reranking when latency matters, add graph expansion when entity relationships matter.
- **Resilience by design**: Each component's absence is a tested code path, not an untested edge case. The chaos/resilience test suite (`tests/resilience/`) validates graceful degradation for every optional component.
- **Air-gapped compatible**: Tier 1 requires only a single model download (embedder). Higher tiers add models incrementally.
- **Clear upgrade path**: Each tier has explicit configuration flags, making it easy to document and automate deployment profiles.

**Negative:**
- **Testing matrix complexity**: With N optional features, the number of configuration combinations is 2^N. Mitigated by testing Tier 1 (all off) and Tier 3 (all on) as primary targets, with targeted tests for individual feature toggles.
- **Code branching overhead**: Every optional component requires conditional guards in the hot path. Mitigated by isolating guards to module boundaries (e.g., `retrieval.py` handles its own graph expansion guard internally).
- **Documentation burden**: Each tier needs clear documentation of what is enabled, what is required, and what degrades. Mitigated by the tiered configuration profiles in `docs/en/guides/deployment-guide.md`.

**Mitigations:**
- Default configuration ships as Tier 1 (all advanced features off) — new deployments get the simplest working system.
- `tests/resilience/test_chaos.py` explicitly tests each component's absence (Qdrant down, Redis down, Neo4j down, LLM timeout, combined failures).
- The `proxy/app/shared/config.py` module centralizes all feature flags with sensible defaults and documentation.
