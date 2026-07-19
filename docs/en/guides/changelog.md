# Changelog

All notable changes to the RAG System project.

---

## v2.0.0 (2026-07-16)

### RAG Pipeline
- **Hybrid Retrieval** — dense (BGE-M3) + sparse (BM25) + ColBERT multi-vectors with RRF fusion
- **Cross-Encoder Reranking** — MiniLM-L-6-v2 with two-stage filtering and fine-tuning support
- **Knowledge Graph** — Neo4j entity extraction (10 types, 9 relations), text-to-Cypher, global search
- **HyDE Query Expansion** — hypothetical document generation for improved retrieval recall
- **CRAG Evaluator** — retrieval quality assessment with corrective loops
- **NLI Grounding** — hallucination detection via entailment verification
- **Confidence Scoring** — heuristics + optional SLM verification, negative rejection
- **Token Optimizer** — BPE-aware counting, 4 compression strategies, smart budget allocation

### Agentic Tools
- **Tools SDK** — `@tool` decorator with automatic JSON Schema from type hints
- **Declarative Tools** — YAML/JSON definitions for HTTP and shell commands
- **OpenAPI Auto-Discovery** — convert REST APIs to tools automatically
- **Tool Orchestrator** — parallel execution with dependency resolution
- **Security** — tool sandboxing, permission checks, audit logging

### Model Evolution
- **LoRA/QLoRA Fine-tuning** — SLM, LLM, and Reranker training pipeline
- **EvalGate CI/CD** — quality gating for model promotion
- **Canary Controller** — gradual rollout with traffic splitting
- **Adapter Manager** — hot-reload trained adapters without restart
- **MLflow Tracking** — experiment tracking and model registry

### MCP Server
- **STDIO Transport** — IDE integration (OpenCode, Claude Desktop)
- **Streamable HTTP Transport** — remote agent integration
- **Tools/Resources/Prompts** — full MCP protocol support

### Production
- **Authentication** — JWT (access+refresh pairs), Keycloak OIDC, LDAP/AD, API keys
- **RBAC** — 4 roles (admin, expert, user, read-only)
- **Multi-KB Support** — isolated Qdrant collections per knowledge base, SQLite metadata
- **Rate Limiting** — token bucket per-IP and per-endpoint
- **Federated RAG** — multi-silo fan-out with weighted RRF merge
- **Observability** — Prometheus metrics, structured logging (text/JSON), Grafana dashboards
- **K8s Helm Chart** — HPA, probes, secrets, network policies, 14 templates
- **Air-Gapped** — all models pre-downloaded, fully offline operation

### ETL Pipeline
- **Source Extractors** — Confluence, Jira, GitLab, books, docs, chats, images, tables
- **Semantic Chunker** — adaptive chunking, contextual chunking, hash versioning
- **WAL-Based Incremental** — checkpointing for resume capability
- **Streaming ETL** — Redis Streams, webhook-driven ingestion
- **Graph Builder** — spaCy NER, entity extraction, Neo4j loading

### Infrastructure
- **Backup Automation** — Qdrant snapshots, Neo4j dumps, Redis RDB, MinIO replication
- **Secrets Rotation** — automated credential rotation scripts
- **TLS Setup** — automated certificate management
- **Database Migrations** — migration framework for SQLite schema evolution
- **Operations Scripts** — health check, status, backup, restore, verification

### Documentation
- **14 ADRs** — architecture decisions covering all major design choices
- **44 EN Guides** — comprehensive documentation across all feature areas
- **30 RU Guides** — full Russian translations
- **C4 Diagrams** — 9 architecture diagrams (L1, L2, L3, deployment, data flow, MCP, evolution)
- **OpenAPI Spec** — auto-generated v3.1 spec with 35+ endpoints

### Security
- Input sanitization (XSS, SQLi, injection, length limits)
- Password policy enforcement (min 10 chars, uppercase, lowercase, digit, special)
- Rate limiting on all auth endpoints
- Secret masking in logs
- Audit logging for auth and admin actions
- CORS configuration and security headers (HSTS, X-Frame-Options, CSP)
- Dependency vulnerability scanning (pip-audit, CodeQL)

### S4-2026 Sprint (2026-07-10 to 2026-07-16)
- **Wave 1** — mypy strict mode (0 errors), test collection fix, Dependabot triage, production bugfixes
- **Wave 2** — coverage 80%, eval dataset expansion, security audit, docs completeness
- **Wave 3** — TLS automation, secrets rotation, database migrations, K8s benchmarks
- **Wave 4** — C4 diagrams, OpenAPI export, ADR-008 finalized, maturity review
- **Wave 5** — integration tests fixed, coverage verified at 80%

### Previous Sprints (S3-2026)
- Self-critique verification loop, CRAG evaluator wiring, embedding cache
- Text-to-Cypher for Neo4j, adaptive query routing, global search mode
- Multi-hop reasoning, knee-point pruning, multi-query rewriting

---

## v2.0.0-rc (2026-06-26)

### Initial Release
- Core RAG pipeline (hybrid search, reranking, generation)
- OpenAI-compatible proxy API
- Dual-LLM (SLM + LLM) architecture
- ETL pipeline for Confluence, Jira, GitLab
- HITL feedback dashboard (Streamlit)
- RAG maturity assessment framework
