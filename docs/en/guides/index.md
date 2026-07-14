# Design Guides

Comprehensive guides covering design decisions, implementation patterns, and operational practices.

| Guide                                                                 | Description                                                               |
|-----------------------------------------------------------------------|---------------------------------------------------------------------------|
| [RAG Maturity Assessment](rag-maturity-assessment.md)                 | Maturity model with capability scoring across 5 levels                    |
| [Production Readiness Checklist](best-practices-checklist.md)         | 8-dimension production readiness tracker                                  |
| [Disaster Recovery Runbook](disaster-recovery-runbook.md)             | Step-by-step DR procedures for all failure scenarios                      |
| [SLI/SLO Definitions](../sli_slo.md)                                  | Service level indicators, objectives, and error budgets                   |
| [Performance & Quality](performance-quality.md)                       | HNSW tuning, quantization, monitoring, resilience                         |
| [Extensibility: Adding Data Sources](extensibility-data-sources.md)   | Plugin architecture for custom data source extractors                     |
| [Access Control & RBAC](access-control-rbac.md)                       | Role-based access control and data classification                         |
| [Knowledge Graph Strategy](knowledge-graph-strategy.md)               | Neo4j graph enrichment and context unrolling                              |
| [Federated RAG](federated-rag.md)                                     | Multi-silo fan-out, weighted RRF merge, circuit breakers                  |
| [Agentic Tools — Python SDK](agentic-tools-sdk.md)                    | `@tool` decorator, `ToolBuilder` API, `ToolContext`                       |
| [Agentic Tools — Declarative Reference](agentic-tools-declarative.md) | YAML/JSON tool definitions with HTTP and shell handlers                   |
| [Agentic Tools — OpenAPI Discovery](agentic-tools-openapi.md)         | Auto-discover tools from OpenAPI/Swagger specs                            |
| [Integration with OpenCode](integration-opencode.md)                  | OpenCode IDE setup, MCP server, caching behavior                          |
| [Development Roadmap](roadmap.md)                                     | Phased development approach and feature planning                          |
| [Deployment Guide](deployment-guide.md)                               | Step-by-step production deployment (Docker + K8s)                         |
| [Operations Guide](operations-guide.md)                               | Monitoring, backup, scaling, maintenance                                  |
| [Model Evolution](model-evolution.md)                                 | Fine-tuning pipeline: LoRA/QLoRA, EvalGate, canary deployment, hot-reload |
| [Troubleshooting](troubleshooting.md)                                 | Common issues and their resolution                                        |
