# ADR-006: Agentic RAG Orchestration with LangGraph

**Status:** Accepted
**Date:** 2026-06-22

## Context

Simple RAG (single retrieval then generation) fails for complex queries requiring multi-hop reasoning, insufficient retrieval results, or comparison across documents. Users often phrase questions ambiguously, and the initial embedding-based retrieval may return low-quality chunks. The system must self-correct by detecting poor retrieval quality and iteratively refining both the query and the retrieved context.

Alternatives considered: **LangChain chains** (linear, no conditional looping), **custom state machine** (reinventing control flow, harder to debug), **LLM-only reasoning** (no retrieval loop, hallucination risk), **CrewAI/Multi-agent** (overly complex for current query patterns).

## Decision

**Implement LangGraph-based agentic orchestration as an optional module, with fallback to standard RAG.**

The orchestrator (`proxy/app/orchestrator.py`) defines a state graph (`RAGState` at `orchestrator.py:36-51`) with seven nodes:
1. **rewrite** (`orchestrator.py:53-80`): LLM rewrites the query for better retrieval.
2. **retrieve** (`orchestrator.py:83-105`): hybrid search in Qdrant.
3. **check_sufficiency** (`orchestrator.py:127-146`): evaluates retrieval quality using average score threshold (0.6) and iteratively loops back to rewrite if insufficient — bounded by `MAX_RETRIEVAL_LOOPS` (default 3, `config.py:53`).
4. **graph_expand** (`orchestrator.py:108-124`): optionally enriches context via Neo4j entity graph traversal.
5. **rerank** (`orchestrator.py:149-167`): cross-encoder re-scoring of retrieved chunks.
6. **build_context** (`orchestrator.py:170-182`): assembles final context with graph data.
7. **generate** (`orchestrator.py:185-209`): produces the final answer with LLM.

The graph is compiled with `MemorySaver` checkpointing (`orchestrator.py:258`), enabling state persistence across loop iterations. LangGraph is enabled via `USE_LANGGRAPH` env var (`config.py:52`). When disabled, the proxy falls back to the standard linear pipeline in `main.py:137-208`.

## Consequences

**Positive:** Self-correcting retrieval loops improve answer quality for ambiguous queries. Sufficiency evaluation prevents generation from low-quality context. Graph expansion via Neo4j (`orchestrator.py:118`) adds entity-relationship context not captured by vector search. Modular design — each node can be debugged independently.

**Negative:** Up to 3x latency increase (rewrite + re-retrieve + re-rank loops). LangGraph adds dependency complexity and ~200 MB to the Docker image. Graph expansion requires Neo4j running alongside Qdrant. Fallback to simple RAG means degraded quality without LangGraph.

**Mitigations:** `MAX_RETRIEVAL_LOOPS=3` limits worst-case latency. `check_sufficiency` uses fast heuristics (score threshold) rather than LLM evaluation, keeping loop overhead low. LangGraph is optional — the system runs in simple RAG mode by default (`USE_LANGGRAPH=false` in `config.py:52`).
