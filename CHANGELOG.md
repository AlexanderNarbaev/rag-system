# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Model evolution test suite: 277 tests covering trainers, adapter manager, canary controller, eval gate, model registry, experiment tracker
- MCP server test suite: 56 tests covering STDIO and HTTP transports, tool execution, resource handling
- Integration test suite expanded to 64 tests (was 5) covering cross-component flows
- E2E test suite expanded to 32 tests (was 3) covering full-stack scenarios
- Performance test suite expanded to 12 tests (was 2) covering load testing and benchmarks
- GPUStack section added to deployment documentation
- All documentation guides properly linked in navigation

### Fixed
- Removed dead code (stream_consumer stubs, LLMError duplication)
- Replaced 5 fake/no-op tests with honest implementations
- Corrected best-practices-checklist.md scores to reflect audit findings
- Fixed CHANGELOG.md reference (file was missing, now created)
- ETL input validation for extractors and chunkers
- ETL WAL corruption recovery and integrity checks
- ETL retry logic with exponential backoff for transient failures
- Orchestrator sync calls — patched test mocks for restructured orchestrator modules
- ToolError consolidation — unified error hierarchy across tools subsystem
- Ruff lint errors: F821 forward reference fix, E501 line length violations

### Changed
- Improved type hints coverage across proxy and ETL modules
- Added docstrings to previously undocumented public functions
- Testing score updated from 7.5/10 to 8.5/10 (2669 total tests, coverage improved)
- Documentation score updated from 8.0/10 to 9.0/10 (all guides in nav, GPUStack section added)
- Production readiness score updated from 65.5/80 (81.9%) to 67.5/80 (84.4%)
- Roadmap updated — all 8 phases complete, future horizons documented
- Final test count confirmed at 2669 across all test suites

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
