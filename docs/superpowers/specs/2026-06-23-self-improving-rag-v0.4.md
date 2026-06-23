# Self-Improving RAG v0.4 — Design Spec

## Goal
Transform the RAG system into a self-improving knowledge assistant that collects feedback in real-time, rates its own confidence, alerts humans when uncertain, and enriches its knowledge base from validated interactions.

## Scope — Iteration A (v0.4)
Four new capabilities, layered on top of existing code:

1. **VERIFY_CASCADE routing** — answer cheap, verify quality, escalate if needed
2. **Active feedback collection** — real-time 👍/👎 + correction in chat completion response
3. **Confidence scoring** — Critic agent rates every answer 0.0–1.0, stored in audit
4. **Self-enrichment pipeline** — accepted Q&A pairs ingested back into Qdrant

## Architecture Principles (from existing system)
- Air-gapped first
- Graceful degradation — every component optional
- Incremental by default
- Token economy — every token counts

## Components

### A. Confidence Scorer (`proxy/app/confidence.py`) — NEW
- `compute_confidence(query, context, answer) -> ConfidenceReport`
- Uses heuristics + optional SLM verification (when SLM enabled)
- Reports: score, uncertainties, sources with low relevance, recommendation
- Score < threshold → flag for admin review

### B. Active Feedback (`proxy/app/main.py` — MODIFY)
- Response now includes `rag_feedback_id` in choices[0].message
- New endpoint: `POST /v1/feedback` — submit 👍/👎/correction
- Integrated with existing `hitl.py` InteractionLogger

### C. VERIFY_CASCADE (`proxy/app/orchestrator.py` — MODIFY)
- New orchestrator state fields: `confidence`, `needs_escalation`, `escalation_reason`
- After generation → run confidence check → if low + loops remain → rewrite + re-retrieve
- Falls through to admin alert if all loops exhausted with low confidence

### D. Self-Enrichment (`proxy/app/enricher.py`) — NEW
- `enrich_from_feedback(feedback_record) -> None`
- Extracts Q&A pair from accepted interaction
- Chunks + hashes + upserts to Qdrant with metadata (source=user_feedback)
- Marks existing chunks as potentially deprecated if correction provided

## Data Flow
```
User Query → [Retrieve → Rerank → Build Context → Generate] → Response + feedback_id
                                                                      │
                                                          User clicks 👍/👎
                                                                      │
                                                    Enricher: extract Q&A → chunk → Qdrant
```

```
User Query → Retrieve → Generate → Confidence Check
                                      │
                          score < 0.5? → Rewrite query → Re-retrieve → Re-generate
                                      │
                          still low? → Flag admin + respond with caveat
```

## Non-Goals (Iteration B)
- Full 6-agent multi-agent architecture
- Semantic response cache
- Cross-provider failover
- Knowledge base correction UI redesign
