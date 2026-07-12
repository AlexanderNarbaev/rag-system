# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Removed dead code (stream_consumer stubs, LLMError duplication)
- Replaced 5 fake/no-op tests with honest implementations
- Corrected best-practices-checklist.md scores to reflect audit findings
- Fixed CHANGELOG.md reference (file was missing, now created)

## [v2.0.0] - 2026-06-26

### Added
- HyDE query expansion (query_enhancer.py)
- CRAG evaluator with action mapping
- Self-reflection module
- NLI hallucination grounding
- Corrective re-generation loops
- Agentic tool calling (live Confluence/Jira/GitLab)
- Multi-language support (RU/EN/DE/FR/ZH)
- Cross-lingual retrieval benchmarks
- Live source connectors (direct API integration)
- Self-reflection graph patterns (Neo4j)
- LLMLingua compression integration
- LongContextReorder integration
- MCP server for OpenCode/Claude Desktop integration
- Agentic Tools SDK (@tool decorator, ToolBuilder, ToolContext)
- Declarative tool definitions (YAML/JSON)
- OpenAPI auto-discovery for tool registration
- Model evolution pipeline (LoRA/QLoRA fine-tuning, EvalGate, canary deployment)

## [v1.0.0] - 2026-03-01

### Added
- OpenAI-compatible proxy API
- Qdrant hybrid search (dense + sparse + RRF)
- Cross-encoder reranking (MiniLM-L-6-v2)
- Neo4j graph expansion
- JWT authentication with RBAC
- Redis caching (embedding + response)
- Streamlit expert dashboard (HITL)
- Prometheus metrics and Grafana dashboards
- Docker Compose deployment
- Comprehensive test suite
- ADR documentation (10+ records)
- Performance and security guides
