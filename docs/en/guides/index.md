# Design Guides

Comprehensive guides covering design decisions, implementation patterns, operational practices, and project management.

## Getting Started

| Guide                                                           | Description                                              |
|-----------------------------------------------------------------|----------------------------------------------------------|
| [Quick Start](quickstart.md)                                    | 5-minute setup tutorial with troubleshooting             |
| [User Guide](user-guide.md)                                     | End-user guide for RAG interactions                      |
| [API Examples](api-examples.md)                                 | curl, Python, JavaScript examples for all endpoints      |

## Configuration & Development

| Guide                                                                   | Description                                          |
|-------------------------------------------------------------------------|------------------------------------------------------|
| [Configuration Reference](configuration-reference.md)                   | All environment variables, feature flags, and settings |
| [Development Guide](development-guide.md)                               | Local dev setup, testing, debugging                   |
| [Database Migrations](database-migrations.md)                           | SQLite schema migration framework                     |

## Deployment & Operations

| Guide                                                                   | Description                                                    |
|-------------------------------------------------------------------------|----------------------------------------------------------------|
| [Deployment Guide](deployment-guide.md)                                 | Step-by-step production deployment (Docker + K8s)              |
| [Operations Guide](operations-guide.md)                                 | Monitoring, backup, scaling, maintenance                       |
| [Runbook](runbook.md)                                                   | Operational procedures and incident response                   |
| [TLS Setup](tls-setup.md)                                               | Automated TLS certificate management                           |
| [Secrets Rotation](secrets-rotation.md)                                 | Automated credential rotation procedures                       |

## Architecture & Design

| Guide                                                                   | Description                                                    |
|-------------------------------------------------------------------------|----------------------------------------------------------------|
| [RAG Maturity Assessment](rag-maturity-assessment.md)                   | Maturity model with capability scoring across 5 levels         |
| [Production Readiness Checklist](best-practices-checklist.md)           | 8-dimension production readiness tracker                       |
| [Performance & Quality](performance-quality.md)                         | HNSW tuning, quantization, monitoring, resilience              |
| [Performance Baselines](performance-baselines.md)                       | Performance benchmarks and baselines                           |
| [Disaster Recovery Runbook](disaster-recovery-runbook.md)               | Step-by-step DR procedures for all failure scenarios           |
| [SLI/SLO Definitions](../sli_slo.md)                                    | Service level indicators, objectives, and error budgets        |
| [Development Roadmap](roadmap.md)                                       | Phased development approach and feature planning               |

## Security

| Guide                                                                   | Description                                                    |
|-------------------------------------------------------------------------|----------------------------------------------------------------|
| [Security Guide](security-guide.md)                                     | Authentication, authorization, and security best practices     |
| [Access Control & RBAC](access-control-rbac.md)                         | Role-based access control and data classification              |
| [Security Audit (2026-07-16)](security-audit-2026-07-16.md)             | Comprehensive security audit findings and remediation          |

## Data Pipeline

| Guide                                                                   | Description                                                    |
|-------------------------------------------------------------------------|----------------------------------------------------------------|
| [ETL Guide](etl-guide.md)                                               | ETL pipeline configuration, scheduling, and operation          |
| [Extensibility: Adding Data Sources](extensibility-data-sources.md)     | Plugin architecture for custom data source extractors          |
| [Knowledge Graph Strategy](knowledge-graph-strategy.md)                 | Neo4j graph enrichment and context unrolling                   |
| [Knowledge Graph Guide](knowledge-graph-guide.md)                       | Neo4j setup, schema, and graph operations                      |

## Advanced Features

| Guide                                                                   | Description                                                    |
|-------------------------------------------------------------------------|----------------------------------------------------------------|
| [Federated RAG](federated-rag.md)                                       | Multi-silo fan-out, weighted RRF merge, circuit breakers       |
| [Agentic Tools — Python SDK](agentic-tools-sdk.md)                      | `@tool` decorator, `ToolBuilder` API, `ToolContext`            |
| [Agentic Tools — Declarative Reference](agentic-tools-declarative.md)   | YAML/JSON tool definitions with HTTP and shell handlers        |
| [Agentic Tools — OpenAPI Discovery](agentic-tools-openapi.md)           | Auto-discover tools from OpenAPI/Swagger specs                 |
| [Model Evolution](model-evolution.md)                                   | Fine-tuning pipeline: LoRA/QLoRA, EvalGate, canary, hot-reload |

## Observability & Monitoring

| Guide                                                                   | Description                                                    |
|-------------------------------------------------------------------------|----------------------------------------------------------------|
| [Observability](observability.md)                                       | Prometheus metrics, structured logging, distributed tracing    |
| [Monitoring Guide](monitoring-guide.md)                                 | Grafana dashboards, alert rules, SLI/SLO monitoring            |
| [Troubleshooting](troubleshooting.md)                                   | Common issues and their resolution                             |

## Integration

| Guide                                                                   | Description                                                    |
|-------------------------------------------------------------------------|----------------------------------------------------------------|
| [Integration Guide](integration-guide.md)                               | General integration patterns for the RAG system                |
| [Integration with OpenCode](integration-opencode.md)                    | OpenCode IDE setup, MCP server, caching behavior               |
| [MCP Server Guide](mcp-server-guide.md)                                 | MCP server architecture, tools, resources, and prompts         |

## Project Management

| Guide                                                                   | Description                                                    |
|-------------------------------------------------------------------------|----------------------------------------------------------------|
| [Project Checklist](project-checklist.md)                               | Comprehensive project status tracker and scorecard             |
| [Maturity Report](maturity-report.md)                                   | RAG maturity assessment report and findings                    |
| [Quarterly Review Cadence](quarterly-review-cadence.md)                 | Quarterly maturity review process and schedule                 |
| [Improvement Plan 2026 Q3](improvement-plan-2026-q3.md)                 | Q3 2026 improvement plan and priorities                        |
| [Sprint Plan S3-2026](sprint-plan-2026-s3.md)                           | S3-2026 sprint plan and backlog                                |
| [Sprint Plan S3-2026 (Updated)](sprint-plan-2026-s3-updated.md)         | Updated S3-2026 sprint plan with revisions                     |
| [Sprint Plan S4-2026](sprint-plan-2026-s4.md)                           | S4-2026 sprint plan with wave breakdown                        |
| [Current Wave](current_wave.md)                                         | Current sprint wave status and progress                        |
| [Changelog](changelog.md)                                               | Release history and notable changes                            |
