# Architecture Decision Records

Ten architecture decisions documented using the ADR format. Each record captures the context, decision, consequences,
and alternatives considered.

| #       | Decision                                                   | Document                                            |
|---------|------------------------------------------------------------|-----------------------------------------------------|
| ADR-001 | BAAI/bge-m3 as the embedding model                         | [ADR-001](ADR-001-bge-m3-embedding-model.md)        |
| ADR-002 | Qdrant for hybrid vector search                            | [ADR-002](ADR-002-qdrant-hybrid-search.md)          |
| ADR-003 | Dual-LLM (SLM + LLM) architecture                          | [ADR-003](ADR-003-dual-llm-architecture.md)         |
| ADR-004 | OpenAI-compatible proxy pattern                            | [ADR-004](ADR-004-openai-compatible-proxy.md)       |
| ADR-005 | Version-aware document indexing                            | [ADR-005](ADR-005-version-aware-indexing.md)        |
| ADR-006 | Agentic RAG with LangGraph                                 | [ADR-006](ADR-006-agentic-rag-langgraph.md)         |
| ADR-007 | Human-in-the-loop feedback system                          | [ADR-007](ADR-007-hitl-feedback-system.md)          |
| ADR-008 | Java 25 + Quarkus hybrid migration                         | [ADR-008](ADR-008-java-quarkus-hybrid-migration.md) |
| ADR-009 | Agentic Tools Expansion Architecture                       | [ADR-009](ADR-009-agentic-tools-expansion.md)       |
| ADR-010 | Model Evolution — Fine-Tuning Pipeline & Canary Deployment | [ADR-010](ADR-010-model-evolution.md)               |

## Status Summary

| ADR                   | Status      | Date    |
|-----------------------|-------------|---------|
| 001                   | Accepted    | 2025-12 |
| 002                   | Accepted    | 2025-12 |
| 003                   | Accepted    | 2026-01 |
| 004                   | Accepted    | 2026-01 |
| 005                   | Accepted    | 2026-02 |
| 006                   | Accepted    | 2026-03 |
| 007                   | Accepted    | 2026-04 |
| 008 (Java)            | Proposed    | 2026-07 |
| 009 (Tools)           | Implemented | 2026-07 |
| 010 (Model Evolution) | Implemented | 2026-07 |

All ADRs 001-007 have been implemented. ADR-008 (Java/Quarkus) is proposed and deferred. ADR-009 (Agentic Tools) and
ADR-010 (Model Evolution) have been implemented.
