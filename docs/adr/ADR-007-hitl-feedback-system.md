# ADR-007: Human-in-the-Loop Feedback System

**Status:** Accepted
**Date:** 2026-06-22

## Context

The RAG system's answer quality depends on retrieval relevance, context assembly, and LLM generation accuracy. Without feedback collection, quality issues go undetected and there is no mechanism for continuous improvement. Expert users (domain specialists) need a way to correct inaccurate responses and mark good answers. Additionally, corrected answers form a valuable training dataset for future fine-tuning of the Gemma model.

Alternatives considered: **no feedback** (quality degrades over time), **automated evaluation** (metrics like ROUGE/BERTScore don't capture factual correctness for technical content), **external annotation platform** (overkill, adds integration complexity).

## Decision

**Implement a lightweight Human-in-the-Loop (HITL) feedback system with JSONL logging, a Streamlit expert dashboard, and training dataset export.**

The `InteractionLogger` (`proxy/app/hitl.py:28-109`) records every query-response pair as JSON Lines (`interactions.jsonl`) with request ID, timestamp, user query (up to 5000 chars of context), response, and metadata (model, version, client IP, cache status). Feedback is stored separately in `feedback.jsonl` (`hitl.py:72-96`) with three types: `positive`, `negative`, and `correction` (expert-corrected response).

Logging is asynchronous and non-blocking (`hitl.py:122-144`) — executed via `asyncio.to_thread()` so it never delays the API response. It can be disabled with `LOG_REQUESTS=false` (`config.py:63`).

The training dataset exporter (`hitl.py:166-192`) filters interactions for:
1. Expert-corrected responses (pair: original question → corrected answer)
2. Positively-rated responses (pair: question → system answer)

Output is JSONL formatted for fine-tuning pipelines (`{"prompt": "...", "completion": "..."}`).

The expert review dashboard (under `hitl_dashboard/`, Streamlit-based) provides:
- Browse recent interactions with search/filter
- Submit corrections and feedback
- Export training datasets on demand

## Consequences

**Positive:** Zero-latency impact on API responses (async, non-blocking logging). Complete audit trail of all interactions enables debugging of retrieval failures. Corrections accumulate into a domain-specific fine-tuning dataset over time. JSONL format is simple, append-only, and easy to parse with standard tools.

**Negative:** JSONL files grow unboundedly — no automatic rotation or retention policy. Feedback depends on expert availability; without experts, only raw logs are collected (no corrections, no positive signal). No authentication/authorization on the feedback path — any client can submit feedback.

**Mitigations:** Context is truncated to 5000 characters (`hitl.py:56`) to bound log file growth. Training dataset export supports `min_length=50` to filter noise. Future improvements: log rotation via logrotate or internal retention policy, feedback endpoint authentication.
