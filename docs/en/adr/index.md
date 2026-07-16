# Architecture Decision Records

Fourteen architecture decisions documented using the ADR format. Each record captures the context, decision,
consequences, and alternatives considered.

| #       | Decision                                                   | Document                                            |
|---------|------------------------------------------------------------|-----------------------------------------------------|
| ADR-001 | BAAI/bge-m3 as the embedding model                         | [ADR-001](ADR-001-bge-m3-embedding-model.md)        |
| ADR-002 | Qdrant for hybrid vector search                            | [ADR-002](ADR-002-qdrant-hybrid-search.md)          |
| ADR-003 | Dual-LLM (SLM + LLM) architecture                          | [ADR-003](ADR-003-dual-llm-architecture.md)         |
| ADR-004 | OpenAI-compatible proxy pattern                            | [ADR-004](ADR-004-openai-compatible-proxy.md)       |
| ADR-005 | Version-aware document indexing                            | [ADR-005](ADR-005-version-aware-indexing.md)        |
| ADR-006 | Agentic RAG with LangGraph                                 | [ADR-006](ADR-006-agentic-rag-langgraph.md)         |
| ADR-007 | Human-in-the-loop feedback system                          | [ADR-007](ADR-007-hitl-feedback-system.md)          |
| ADR-008 | Java/Quarkus proxy migration (rejected — keep Python)      | [ADR-008](ADR-008-java-quarkus-hybrid-migration.md) |
| ADR-009 | Agentic Tools Expansion Architecture                       | [ADR-009](ADR-009-agentic-tools-expansion.md)       |
| ADR-010 | Model Evolution — Fine-Tuning Pipeline & Canary Deployment | [ADR-010](ADR-010-model-evolution.md)               |
| ADR-011 | Incremental/Progressive Architecture                       | [ADR-011](ADR-011-incremental-architecture.md)      |
| ADR-012 | OpenWebUI Integration Architecture                         | [ADR-012](ADR-012-openwebui-integration.md)         |
| ADR-013 | Standalone MCP Server for IDE Integration                  | [ADR-013](ADR-013-mcp-server-architecture.md)       |
| ADR-014 | MinIO Object Storage for File Management                   | [ADR-014](ADR-014-minio-object-storage.md)          |

## Status Summary

| ADR                   | Status      | Date       |
|-----------------------|-------------|------------|
| 001                   | Accepted    | 2026-06-22 |
| 002                   | Accepted    | 2026-06-22 |
| 003                   | Accepted    | 2026-06-22 |
| 004                   | Accepted    | 2026-06-22 |
| 005                   | Accepted    | 2026-06-22 |
| 006                   | Accepted    | 2026-06-22 |
| 007                   | Accepted    | 2026-06-22 |
| 008 (Java/Quarkus)    | Rejected    | 2026-07-16 |
| 009 (Tools)           | Implemented | 2026-07-05 |
| 010 (Model Evolution) | Implemented | 2026-07-05 |
| 011                   | Accepted    | 2026-07-10 |
| 012                   | Accepted    | 2026-07-10 |
| 013                   | Accepted    | 2026-07-10 |
| 014                   | Accepted    | 2026-07-10 |

All ADRs 001-007, 011-014 have been accepted. ADR-008 (Java/Quarkus migration) was proposed, deferred, and formally
rejected on 2026-07-16 — the proxy remains Python/FastAPI. ADR-009 (Agentic Tools) and ADR-010 (Model Evolution)
have been implemented.
