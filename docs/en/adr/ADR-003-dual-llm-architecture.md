# ADR-003: Dual-LLM Architecture (SLM + LLM)

**Status:** Accepted
**Date:** 2026-06-22

## Context

The RAG system serves two distinct categories of inference workloads: lightweight preprocessing tasks (intent classification, query decomposition, entity extraction) and heavy generation tasks (contextual answer synthesis from retrieved chunks). Running all tasks on a single large model wastes compute and adds latency for preprocessing operations. The system must operate in an air-gapped environment with limited GPU capacity (single machine with one or two GPUs).

Alternatives considered: **single large model** (running everything on one model — high latency for preprocessing, blocking GPU for all requests), **API-only routing** (rejected due to air-gap), **rule-based preprocessing** (insufficient accuracy for multi-hop query decomposition).

## Decision

**Use a dual-LLM architecture: a small language model (SLM) for lightweight routing tasks and a primary large language model (LLM) for generation (for example, Gemma-2B-it and Gemma-4-26B-it).**

The SLM (`SLM_MODEL_NAME` in `proxy/app/shared/config.py`) handles:
- Intent classification (`proxy/app/llm/slm.py`): classifies queries into factual, procedural, comparison, summarization, or greeting.
- Query decomposition (`proxy/app/llm/slm.py`): splits complex queries into up to 3 sub-queries.
- Entity extraction (`proxy/app/llm/slm.py`): extracts technologies, project names, ticket numbers.
- Lightweight query rewriting (`proxy/app/llm/slm.py`).

The LLM (`LLM_MODEL_NAME` in `proxy/app/shared/config.py`) handles generation via `proxy/app/llm/router.py` through an OpenAI-compatible API (e.g., `llama.cpp` or `vLLM` server). Both models are served from the same inference server (`LLM_ENDPOINT`), distinguished by model name.

Fallback: if `SLM_ENDPOINT` is empty (`proxy/app/shared/config.py`), the system uses heuristics — keyword matching for intent, regex for entity extraction.

## Consequences

**Positive:** SLM (~2 GB VRAM) runs alongside LLM (whose VRAM depends on model size and quantization) on a single GPU with batching. Preprocessing latency is ~100ms (SLM) vs ~800ms (LLM). Decoupled scaling — SLM stays on CPU if GPU is fully utilized by LLM generation.

**Negative:** Two models to maintain and update. Prompts must be versioned for both models separately. SLM quality degrades for edge-case queries; the heuristic fallback is crude.

**Mitigations:** SLM tasks are constrained to structured outputs (JSON/enums) for validation. The orchestrator (`proxy/app/core/orchestrator/graph.py`) can use either SLM or LLM for query rewriting, configured via `MAX_RETRIEVAL_LOOPS` (`proxy/app/shared/config.py`).
