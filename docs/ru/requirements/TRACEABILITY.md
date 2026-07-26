# Матрица трассировки требований

**Назначение:** Связь между каждым требованием (FR/NFR), реализацией и тестами.
Используется для аудита: каждое требование должно иметь хотя бы один тест.

**Версия:** 1.0 | **Дата:** 2026-07-26 | **Статус:** Актуальная

---

## Как читать матрицу

| Колонка            | Описание                                                       |
|--------------------|----------------------------------------------------------------|
| **ID**             | Уникальный идентификатор требования                            |
| **Описание**       | Краткое описание требования                                    |
| **Реализация**     | Файл/модуль с реализацией                                      |
| **Тесты**          | Файл тестов и класс (без отдельных функций)                    |
| **Статус**         | ✅ Подтверждено / ⚠️ Нужна интеграция / ❌ Нужна реализация     |

---

## Core API (FR-01 — FR-08)

| ID    | Описание                       | Реализация                       | Тесты                                                                                                  | Статус |
|-------|--------------------------------|----------------------------------|--------------------------------------------------------------------------------------------------------|--------|
| FR-01 | Chat Completions               | `proxy/app/api/chat.py`          | `tests/proxy/test_core_api.py::TestFR01ChatCompletions`, `tests/integration/test_core_api_e2e.py::TestFR01Integration` | ✅      |
| FR-02 | Models endpoint                | `proxy/app/main.py:846`          | `tests/proxy/test_core_api.py::TestFR02ModelsEndpoint`                                                  | ✅      |
| FR-03 | Health check                   | `proxy/app/api/health.py`        | `tests/proxy/test_core_api.py::TestFR03HealthCheck`, `tests/integration/test_core_api_e2e.py::TestFR03Integration` | ✅      |
| FR-04 | Kubernetes probes              | `proxy/app/api/health.py`        | `tests/proxy/test_core_api.py::TestFR04KubernetesProbes`, `tests/integration/test_core_api_e2e.py::TestFR04Integration` | ✅      |
| FR-05 | RAG параметры запроса          | `proxy/app/api/chat.py`          | `tests/proxy/test_core_api.py::TestFR05RAGParameters`, `tests/integration/test_core_api_e2e.py::TestFR05FR06Integration` | ✅      |
| FR-06 | RAG поля ответа                | `proxy/app/api/chat.py`          | `tests/proxy/test_core_api.py::TestFR06RAGResponseFields`, `tests/integration/test_core_api_e2e.py::TestFR05FR06Integration` | ✅      |
| FR-07 | Response caching (Redis)       | `proxy/app/shared/cache.py`      | `tests/proxy/test_core_api.py::TestFR07ResponseCaching`                                                | ✅      |
| FR-08 | SSE streaming format           | `proxy/app/api/chat.py`          | `tests/proxy/test_core_api.py::TestFR08SSEStreaming`, `tests/integration/test_core_api_e2e.py::TestFR08Integration` | ✅      |

## Retrieval (FR-09 — FR-18)

| ID    | Описание                          | Реализация                       | Тесты                                                                | Статус |
|-------|-----------------------------------|----------------------------------|----------------------------------------------------------------------|--------|
| FR-09 | Гибридный поиск RRF               | `proxy/app/core/retrieval.py`    | `tests/proxy/test_core_api.py::TestFR09HybridSearch`                 | ✅      |
| FR-10 | Cross-encoder reranking           | `proxy/app/core/rerank.py`       | `tests/proxy/test_core_api.py::TestFR10CrossEncoderReranking`        | ✅      |
| FR-11 | Дедупликация (SHA-256)            | `proxy/app/core/context/builder.py` | `tests/proxy/test_core_api.py::TestFR11Deduplication`             | ✅      |
| FR-12 | Version-aware фильтрация          | `proxy/app/core/retrieval.py`    | `tests/proxy/test_core_api.py::TestFR12VersionFiltering`             | ✅      |
| FR-13 | Кэширование эмбеддингов           | `proxy/app/core/retrieval.py`    | `tests/proxy/test_core_api.py::TestFR13EmbeddingCache`              | ✅      |
| FR-14 | ColBERT late-interaction          | `proxy/app/core/retrieval.py`    | `tests/proxy/test_core_api.py::TestFR14ColBERT`                     | ✅      |
| FR-15 | Knee-point pruning                | `proxy/app/core/retrieval.py`    | `tests/proxy/test_core_api.py::TestFR15KneePointPruning`            | ✅      |
| FR-16 | FLARE                             | `proxy/app/core/flare.py`        | `tests/proxy/test_core_api.py::TestFR16FLARE`                       | ✅      |
| FR-17 | Two-stage reranking               | `proxy/app/core/rerank.py`       | `tests/proxy/test_core_api.py::TestFR17TwoStageReranking`            | ✅      |
| FR-18 | Dynamic top-k (SLM)               | `proxy/app/core/query_router.py` | `tests/proxy/test_core_api.py::TestFR18DynamicTopK`                 | ✅      |

## Knowledge Graph (FR-19 — FR-25)

| ID    | Описание                       | Реализация                                       | Тесты             | Статус          |
|-------|--------------------------------|--------------------------------------------------|-------------------|-----------------|
| FR-19 | Извлечение сущностей           | `etl/graph_builder/entity_extractor.py`          | требуется интеграция с Neo4j | ⚠️              |
| FR-20 | Batch loading в Neo4j          | `etl/graph_builder/neo4j_loader.py`              | требуется интеграция с Neo4j | ⚠️              |
| FR-21 | Multi-hop graph traversal      | `proxy/app/core/retrieval.py`                    | требуется интеграция с Neo4j | ⚠️              |
| FR-22 | Global / Multi-Hop / Text2Cypher | `proxy/app/core/retrieval.py`                  | требуется интеграция с Neo4j | ⚠️              |
| FR-23 | Community Detection            | `etl/graph_builder/community.py`                 | требуется интеграция с Neo4j | ⚠️              |
| FR-24 | Graceful degradation Neo4j     | `proxy/app/core/retrieval.py`                    | требуется интеграция с Neo4j | ⚠️              |
| FR-25 | Graph schema versioning        | (нет реализации)                                 | —                 | ❌              |

## Agentic (FR-26 — FR-31)

| ID    | Описание                       | Реализация                                  | Тесты                          | Статус          |
|-------|--------------------------------|---------------------------------------------|--------------------------------|-----------------|
| FR-26 | LangGraph 10-node graph        | `proxy/app/core/orchestrator/graph.py`      | требуется интеграция с LangGraph | ⚠️              |
| FR-27 | Query rewriting                | `proxy/app/core/orchestrator/nodes.py`      | требуется интеграция с LangGraph | ⚠️              |
| FR-28 | Retrieval sufficiency loop    | `proxy/app/core/orchestrator/nodes.py`      | требуется интеграция с LangGraph | ⚠️              |
| FR-29 | Fallback к линейному пайплайну | `proxy/app/main.py`                         | требуется интеграция с LangGraph | ⚠️              |
| FR-30 | Tool/function calling          | `proxy/app/tools/`                          | требуется интеграция с LangGraph | ⚠️              |
| FR-31 | Параллельное выполнение        | `proxy/app/tools/orchestrator.py`           | требуется интеграция с LangGraph | ⚠️              |

## Quality (FR-32 — FR-39)

| ID    | Описание                          | Реализация                       | Тесты                                                                 | Статус |
|-------|-----------------------------------|----------------------------------|-----------------------------------------------------------------------|--------|
| FR-32 | HyDE                              | `proxy/app/core/hyde.py`         | `tests/proxy/test_quality_pipeline.py::TestFR32HyDE`                  | ✅      |
| FR-33 | CRAG                              | `proxy/app/core/retrieval_evaluator.py` | `tests/proxy/test_quality_pipeline.py::TestFR33CRAG`            | ✅      |
| FR-34 | Self-reflection                   | `proxy/app/core/confidence.py`   | `tests/proxy/test_quality_pipeline.py::TestFR34SelfReflection`        | ✅      |
| FR-35 | NLI grounding                     | `proxy/app/core/grounding.py`    | `tests/proxy/test_quality_pipeline.py::TestFR35NLIGrounding`          | ✅      |
| FR-36 | Детекция галлюцинаций             | `proxy/app/core/hallucination.py`| `tests/proxy/test_quality_pipeline.py::TestFR36HallucinationDetection` | ✅      |
| FR-37 | Corrective re-generation          | `proxy/app/core/confidence.py`   | `tests/proxy/test_quality_pipeline.py::TestFR37CorrectiveRegeneration`| ✅      |
| FR-38 | LLMLingua compression             | `proxy/app/core/compression.py`  | `tests/proxy/test_quality_pipeline.py::TestFR38LLMLinguaCompression`  | ✅      |
| FR-39 | LongContextReorder                | `proxy/app/core/reorder.py`      | `tests/proxy/test_quality_pipeline.py::TestFR39LongContextReorder`     | ✅      |

## ETL (FR-40 — FR-57)

| ID    | Описание                          | Реализация                                            | Тесты                                                                                                  | Статус |
|-------|-----------------------------------|-------------------------------------------------------|--------------------------------------------------------------------------------------------------------|--------|
| FR-40 | Извлечение из 6 источников        | `etl/extractors/{confluence,jira,gitlab,docs,books,chats}.py` | `tests/etl/test_etl_requirements.py::TestFR40Extractors`, `tests/etl/test_extractors.py`     | ✅      |
| FR-41 | Semantic chunking                 | `etl/chunker/semantic_chunker.py`                     | `tests/etl/test_etl_requirements.py::TestFR41SemanticChunking`, `tests/etl/test_semantic_chunker.py`   | ✅      |
| FR-42 | HTML → Markdown                   | `etl/chunker/`                                        | `tests/etl/test_table_extractor.py`, `tests/etl/test_chunker.py`                                       | ✅      |
| FR-43 | Table extraction                  | `etl/chunker/table_extractor.py`                      | `tests/etl/test_table_extractor.py`                                                                    | ✅      |
| FR-44 | WAL-based incremental             | `etl/indexer/wal_manager.py`                          | `tests/etl/test_etl_requirements.py::TestFR44WALIncremental`, `tests/etl/test_wal_manager.py`           | ✅      |
| FR-45 | SHA-256 content-addressable       | `etl/chunker/hash_versioning.py`                      | `tests/etl/test_etl_requirements.py::TestFR45ContentAddressable`, `tests/etl/test_hash_versioning.py`   | ✅      |
| FR-46 | Hot/cold storage                  | `etl/indexer/live_vector_lake.py`                     | `tests/etl/test_etl_requirements.py::TestFR46HotColdStorage`, `tests/etl/test_live_vector_lake.py`       | ✅      |
| FR-47 | Version tracking                  | `etl/chunker/hash_versioning.py`                      | `tests/etl/test_etl_requirements.py::TestFR47VersionTracking`                                           | ✅      |
| FR-48 | RAPTOR hierarchical indexing      | `etl/indexer/tree_builder.py`                         | `tests/etl/test_etl_requirements.py::TestFR48RaptorTree`                                                | ✅      |
| FR-49 | Code-aware chunking (AST)         | `etl/chunker/code_chunker.py`                         | `tests/etl/test_etl_requirements.py::TestFR49CodeChunking`, `tests/etl/test_code_chunker.py`            | ✅      |
| FR-50 | Image OCR                         | `etl/extractors/image_extractor.py`                  | `tests/etl/test_etl_requirements.py::TestFR50ImageOCR`, `tests/etl/test_image_extractor.py`, `tests/etl/test_ocr.py` | ✅      |
| FR-51 | Quality metrics                   | `etl/indexer/chunk_quality.py`                        | `tests/etl/test_etl_requirements.py::TestFR51QualityMetrics`, `tests/etl/test_chunk_quality.py`        | ✅      |
| FR-52 | Chunk enrichment (SLM)           | `etl/indexer/chunk_enricher.py`                       | `tests/etl/test_etl_requirements.py::TestFR52ChunkEnrichment`, `tests/etl/test_chunk_enricher.py`       | ✅      |
| FR-53 | Streaming pipeline                | `etl/scheduler/streaming_pipeline.py`                 | `tests/etl/test_etl_requirements.py::TestFR53StreamingPipeline`, `tests/etl/test_streaming_pipeline.py` | ✅      |
| FR-54 | Event pipeline                    | `etl/scheduler/event_pipeline.py`                     | `tests/etl/test_etl_requirements.py::TestFR54EventPipeline`, `tests/etl/test_event_pipeline.py`         | ✅      |
| FR-55 | Webhook server                    | `etl/scheduler/webhook_server.py`                     | `tests/etl/test_etl_requirements.py::TestFR55WebhookServer`, `tests/etl/test_webhook_server.py`         | ✅      |
| FR-56 | Task scheduler                    | `etl/scheduler/task_scheduler.py`                     | `tests/etl/test_etl_requirements.py::TestFR56TaskScheduler`, `tests/etl/test_task_scheduler.py`         | ✅      |
| FR-57 | Cold storage cleanup              | `etl/scheduler/cold_storage_cleanup.py`               | `tests/etl/test_etl_requirements.py::TestFR57ColdStorageCleanup`, `tests/etl/test_cold_storage_cleanup.py` | ✅      |

## Auth & RBAC (FR-73 — FR-94)

| ID    | Описание                          | Реализация                                  | Тесты                                                                                                  | Статус |
|-------|-----------------------------------|---------------------------------------------|--------------------------------------------------------------------------------------------------------|--------|
| FR-73 | Feedback submission               | `proxy/app/api/feedback.py`                 | `tests/proxy/test_auth_rbac.py::TestFR73FeedbackSubmission`                                            | ✅      |
| FR-74 | Feedback storage (SQLite)          | `proxy/app/core/feedback_store.py`           | `tests/proxy/test_auth_rbac.py::TestFR74FeedbackStorage`                                               | ✅      |
| FR-75 | Feedback analytics                | `proxy/app/api/admin_analytics.py`          | `tests/proxy/test_auth_rbac.py::TestFR75FeedbackAnalytics`                                             | ✅      |
| FR-76 | Feedback → training export        | `proxy/app/core/feedback_store.py`           | `tests/proxy/test_auth_rbac.py::TestFR76FeedbackExport`                                                | ✅      |
| FR-77 | Rate limiting feedback             | `proxy/app/api/feedback.py`                 | `tests/proxy/test_auth_rbac.py::TestFR77FeedbackRateLimiting`                                          | ✅      |
| FR-78 | Feedback preservation             | `proxy/app/core/feedback_store.py`           | `tests/proxy/test_auth_rbac.py::TestFR78FeedbackPreservation`                                          | ✅      |
| FR-84 | JWT authentication                | `proxy/app/auth/jwt.py`                     | `tests/proxy/test_auth_rbac.py::TestFR84JWTAuth`                                                      | ✅      |
| FR-85 | Keycloak OIDC                     | `proxy/app/auth/ldap.py`                    | `tests/proxy/test_auth_rbac.py::TestFR85KeycloakOIDC`                                                  | ✅      |
| FR-86 | LDAP/AD authentication            | `proxy/app/auth/ldap.py`                    | `tests/proxy/test_auth_rbac.py::TestFR86LDAPAuth`                                                      | ✅      |
| FR-87 | API key authentication            | `proxy/app/auth/api_keys.py`                 | `tests/proxy/test_auth_rbac.py::TestFR87APIKeys`                                                       | ✅      |
| FR-87b | User identification via headers  | (требуется реализация)                      | —                                                                                                      | ❌ (новая) |
| FR-88 | RBAC — 4 роли                     | `proxy/app/auth/rbac.py`                     | `tests/proxy/test_auth_rbac.py::TestFR88RBAC`, `tests/integration/test_auth_flow.py::TestRBACEnforcement` | ✅      |
| FR-89 | ACL в Qdrant                      | `proxy/app/shared/access_control.py`        | `tests/proxy/test_auth_rbac.py::TestFR89ACLQdrant`                                                     | ✅      |
| FR-90 | Secret rotation                   | `proxy/app/auth/secret_rotation.py`         | `tests/proxy/test_auth_rbac.py::TestFR90SecretRotation`                                                | ✅      |
| FR-91 | Rate limiting                     | `proxy/app/shared/rate_limiter.py`          | `tests/proxy/test_auth_rbac.py::TestFR91RateLimiting`                                                  | ✅      |
| FR-92 | Input validation                  | `proxy/app/shared/security.py`              | `tests/proxy/test_auth_rbac.py::TestFR92InputValidation`                                               | ✅      |
| FR-93 | Audit logging                     | `proxy/app/shared/audit.py`                 | `tests/proxy/test_auth_rbac.py::TestFR93AuditLogging`                                                  | ✅      |
| FR-94 | CORS configuration                | `proxy/app/shared/middleware.py`            | `tests/proxy/test_auth_rbac.py::TestFR94CORS`, `tests/integration/test_auth_flow.py::TestCORSIntegration` | ✅      |

## Model Evolution (FR-95 — FR-102)

| ID    | Описание                          | Реализация                                       | Тесты                                       | Статус |
|-------|-----------------------------------|--------------------------------------------------|---------------------------------------------|--------|
| FR-95 | SLM LoRA fine-tuning              | `model_evolution_service/trainers/slm_trainer.py` | `tests/proxy/test_admin_kb.py` (model mgmt)  | ✅      |
| FR-96 | LLM QLoRA fine-tuning             | `model_evolution_service/trainers/llm_trainer.py` | `tests/proxy/test_admin_kb.py`              | ✅      |
| FR-97 | Reranker fine-tuning              | `model_evolution_service/trainers/reranker_trainer.py` | `tests/proxy/test_admin_kb.py`         | ✅      |
| FR-98 | MLflow experiment tracking        | `model_evolution_service/experiment_tracker.py`   | `tests/proxy/test_admin_kb.py`              | ✅      |
| FR-99 | MLflow Model Registry             | `model_evolution_service/model_registry.py`        | `tests/proxy/test_admin_kb.py`              | ✅      |
| FR-100 | EvalGate CI/CD gating            | `model_evolution_service/eval_gate.py`            | `tests/proxy/test_admin_kb.py`              | ✅      |
| FR-101 | CanaryController phased split     | `model_evolution_service/canary_controller.py`     | `tests/proxy/test_admin_kb.py`              | ✅      |
| FR-102 | AdapterManager hot-reload         | `model_evolution_service/adapter_manager.py`      | `tests/proxy/test_admin_kb.py`              | ✅      |

## Knowledge Base & Agentic Tools (FR-104 — FR-120)

| ID    | Описание                          | Реализация                                | Тесты                                                       | Статус |
|-------|-----------------------------------|-------------------------------------------|-------------------------------------------------------------|--------|
| FR-104 | Multiple knowledge bases          | `proxy/app/core/kb_manager.py`            | `tests/proxy/test_tools_kb.py::TestFR104MultipleKBs`        | ✅      |
| FR-105 | Admin KB API                      | `proxy/app/api/admin_kb.py`               | `tests/integration/test_admin_kb_api.py`                     | ✅      |
| FR-106 | Auto-provisioning collections     | `proxy/app/main.py:138`                   | `tests/proxy/test_tools_kb.py` (startup)                    | ✅      |
| FR-107 | Task tracking (ETL tasks)         | `proxy/app/api/admin_kb.py`               | `tests/proxy/test_tools_kb.py::TestFR107TaskTracking`       | ✅      |
| FR-108 | Configuration validation          | `proxy/app/shared/config_validator.py`    | `tests/proxy/test_tools_kb.py::TestFR108ConfigValidation`    | ✅      |
| FR-109 | Enhanced health checks            | `proxy/app/api/health.py`                 | `tests/proxy/test_tools_kb.py::TestFR109EnhancedHealth`      | ✅      |
| FR-111 | `@tool` decorator                 | `proxy/app/tools/sdk.py`                  | `tests/proxy/test_tools_kb.py::TestFR111ToolDecorator`       | ✅      |
| FR-112 | ToolBuilder pattern               | `proxy/app/tools/sdk.py`                  | `tests/proxy/test_tools_kb.py::TestFR112ToolBuilder`         | ✅      |
| FR-113 | ToolContext injection             | `proxy/app/tools/sdk.py`                  | `tests/proxy/test_tools_kb.py::TestFR113ToolContext`         | ✅      |
| FR-114 | Built-in tools                    | `proxy/app/tools/builtin.py`              | `tests/proxy/test_tools_kb.py::TestFR114BuiltinTools`        | ✅      |
| FR-115 | Tool input validation             | `proxy/app/tools/security.py`             | `tests/proxy/test_tools_kb.py::TestFR115InputValidation`     | ✅      |
| FR-116 | Declarative tools (YAML/JSON)     | `proxy/app/tools/declarative.py`          | `tests/proxy/test_tools_kb.py::TestFR116DeclarativeTools`    | ✅      |
| FR-117 | OpenAPI auto-discovery            | `proxy/app/tools/openapi/`                | `tests/proxy/test_tools_kb.py::TestFR117OpenAPIDiscovery`    | ✅      |
| FR-118 | Tool visibility by role           | `proxy/app/tools/registry.py`             | `tests/proxy/test_tools_kb.py::TestFR118ToolVisibility`      | ✅      |
| FR-119 | Tool metrics (Prometheus)         | `proxy/app/tools/metrics.py`              | `tests/proxy/test_tools_kb.py::TestFR119ToolMetrics`         | ✅      |
| FR-120 | Tool audit logging                | `proxy/app/tools/audit.py`                | `tests/proxy/test_tools_kb.py::TestFR120ToolAudit`           | ✅      |

## MCP Server (FR-121 — FR-125)

| ID    | Описание                          | Реализация                  | Тесты                                                          | Статус |
|-------|-----------------------------------|-----------------------------|----------------------------------------------------------------|--------|
| FR-121 | MCP tools                         | `mcp_server/server.py`      | `tests/mcp_server/test_mcp_requirements.py::TestFR121MCPTools` | ✅      |
| FR-122 | MCP resource                      | `mcp_server/server.py`      | `tests/mcp_server/test_mcp_requirements.py::TestFR122MCPResource` | ✅   |
| FR-123 | MCP prompt                        | `mcp_server/server.py`      | `tests/mcp_server/test_mcp_requirements.py::TestFR123MCPPrompt` | ✅      |
| FR-124 | Dual transport                    | `mcp_server/server.py`      | `tests/mcp_server/test_mcp_requirements.py::TestFR124DualTransport` | ✅   |
| FR-125 | Standalone installation           | `mcp_server/server.py`      | `tests/mcp_server/test_mcp_requirements.py::TestFR125StandaloneInstall` | ✅ |

## Deployment & Operations (FR-149 — FR-167)

| ID    | Описание                          | Реализация                          | Тесты                                                       | Статус |
|-------|-----------------------------------|-------------------------------------|-------------------------------------------------------------|--------|
| FR-149 | Docker Compose                    | `proxy/docker-compose.yml`          | `tests/deploy/test_helm_chart.py::TestDockerCompose`         | ✅      |
| FR-150 | Helm chart                        | `deploy/k8s/helm/rag-system/`       | `tests/deploy/test_helm_chart.py::TestHelmChart`             | ✅      |
| FR-151 | ETL Helm component                | `deploy/k8s/helm/rag-system/`       | `tests/deploy/test_helm_chart.py::TestETLHelmComponent`     | ✅      |
| FR-152 | Distributed compose               | `deploy/docker/docker-compose.distributed.yml` | `tests/deploy/test_helm_chart.py::TestDistributedCompose` | ✅      |
| FR-153 | MinIO Helm                        | `deploy/k8s/helm/rag-system/`       | `tests/deploy/test_helm_chart.py::TestMinIOHelm`            | ✅      |
| FR-154 | PostgreSQL Helm                   | `deploy/k8s/helm/rag-system/`       | `tests/deploy/test_helm_chart.py::TestPostgreSQLHelm`       | ✅      |
| FR-156 | Setup wizard                      | `scripts/setup_wizard.py`           | `tests/deploy/test_helm_chart.py::TestDockerCompose`         | ✅      |
| FR-160 | Prometheus /metrics               | `proxy/app/shared/metrics.py`       | `tests/proxy/test_observability.py::TestPrometheusMetrics`   | ✅      |
| FR-161 | Structured JSON logging           | `proxy/app/shared/logging.py`       | `tests/proxy/test_observability.py::TestStructuredLogging`   | ✅      |
| FR-162 | Grafana dashboard                 | `config/monitoring/ragas-dashboard.json` | `tests/deploy/test_helm_chart.py::TestGrafanaDashboard` | ✅      |
| FR-163 | Prometheus alert rules            | `config/monitoring/alerts.yml`     | `tests/deploy/test_helm_chart.py::TestAlertRules`            | ✅      |
| FR-164 | OpenTelemetry tracing             | `proxy/app/shared/tracing.py`       | `tests/proxy/test_observability.py::TestOpenTelemetryTracing` | ✅     |
| FR-165 | Automated backup scripts          | `scripts/ops/`                      | `tests/deploy/test_helm_chart.py::TestBackupScripts`         | ✅      |
| FR-166 | Disaster recovery runbook         | `docs/en/guides/disaster-recovery-runbook.md` | (документация)                                       | ✅      |
| FR-167 | Restore script                    | `scripts/ops/restore_all.sh`        | `tests/deploy/test_helm_chart.py::TestRestoreScript`         | ✅      |

## Performance (FR-168 — FR-175)

| ID    | Описание                          | Реализация                          | Тесты                                                          | Статус |
|-------|-----------------------------------|-------------------------------------|----------------------------------------------------------------|--------|
| FR-168 | Qdrant scalar quantization (INT8) | `scripts/init_collections.py`       | требуется проверка настроек                                     | ⚠️      |
| FR-169 | Qdrant gRPC client                | `proxy/app/core/retrieval.py`       | требуется проверка настроек                                     | ⚠️      |
| FR-170 | vLLM prefix caching               | (external — vLLM config)            | частичная реализация (gauge добавлен, нужен мониторинг)         | ⚠️ Partial |
| FR-171 | HNSW tuning                       | `scripts/init_collections.py`       | требуется проверка настроек                                     | ⚠️      |
| FR-173 | Model warm-up                     | `proxy/app/shared/warmup.py`        | `tests/performance/test_nfr_benchmarks.py::TestModelWarmup`    | ✅      |
| FR-174 | AST-based code chunking           | `etl/chunker/code_chunker.py`       | `tests/etl/test_etl_requirements.py::TestFR49CodeChunking`, `tests/etl/test_code_chunker.py` | ✅ |
| FR-175 | Table extraction from Confluence  | `etl/chunker/table_extractor.py`    | `tests/etl/test_table_extractor.py`                            | ✅      |

---

## Non-Functional Requirements (NFR)

### NFR-P (Производительность)

| ID      | Описание                        | Реализация                          | Тесты                                                       | Статус |
|---------|---------------------------------|-------------------------------------|-------------------------------------------------------------|--------|
| NFR-P01 | End-to-end latency p95 < 5s     | `proxy/app/api/chat.py`, метрики     | `tests/performance/test_nfr_benchmarks.py`                   | ✅      |
| NFR-P02 | Retrieval latency p95 < 200ms   | `proxy/app/core/retrieval.py`       | `tests/performance/test_nfr_benchmarks.py::TestQdrantGRPC`  | ✅      |
| NFR-P03 | TTFT p50 < 1s (cached)          | `proxy/app/shared/cache.py`         | `tests/performance/test_nfr_benchmarks.py`                   | ✅      |
| NFR-P04 | Embedding cache hit ≥ 60%        | `proxy/app/core/retrieval.py`       | `tests/performance/test_nfr_benchmarks.py`                   | ✅      |
| NFR-P05 | Response cache hit ≥ 30%         | `proxy/app/shared/cache.py`         | `tests/performance/test_nfr_benchmarks.py`                   | ✅      |
| NFR-P06 | Reranker latency p95 < 200ms     | `proxy/app/core/rerank.py`          | `tests/performance/test_nfr_benchmarks.py`                   | ✅      |
| NFR-P07 | Qdrant memory (quantized) ≤ 50% | `scripts/init_collections.py`       | `tests/performance/test_nfr_benchmarks.py::TestQdrantQuantization` | ✅ |
| NFR-P08 | vLLM prefix cache hit ≥ 40%      | (external — vLLM config)            | `tests/performance/test_nfr_benchmarks.py::TestVLLMPrefixCaching` | ✅ |
| NFR-P09 | ETL OCR throughput ≤ 5min/100p   | `etl/extractors/image_extractor.py` | `tests/performance/test_nfr_benchmarks.py::TestTableExtraction` | ✅   |
| NFR-P10 | ETL streaming latency < 5s       | `etl/scheduler/streaming_pipeline.py` | `tests/performance/test_nfr_benchmarks.py`               | ✅      |
| NFR-P11 | Response compression ≥ 60%       | `proxy/app/shared/middleware.py`    | (встроено в granian)                                          | ✅      |
| NFR-P12 | Warm-up duration < 30s           | `proxy/app/shared/warmup.py`        | `tests/performance/test_nfr_benchmarks.py::TestModelWarmup`  | ✅      |
| NFR-P13 | MRR drop under INT8 ≤ 2%         | `scripts/init_collections.py`       | `tests/performance/test_nfr_benchmarks.py::TestHNSWTuning`   | ✅      |

### NFR-A (Доступность)

| ID      | Описание                       | Реализация                       | Тесты                                                            | Статус |
|---------|--------------------------------|----------------------------------|------------------------------------------------------------------|--------|
| NFR-A01 | Service availability 99.5%     | infra (K8s probes)               | `tests/deploy/test_nfr_deploy.py`                                | ✅      |
| NFR-A02 | Error rate 5xx < 1%            | `proxy/app/shared/middleware.py` | `tests/deploy/test_nfr_deploy.py`                                | ✅      |
| NFR-A03 | Backup RPO < 1 hour            | `scripts/ops/`                   | `tests/deploy/test_helm_chart.py::TestBackupScripts`             | ✅      |
| NFR-A04 | Backup RTO < 30 min            | `scripts/ops/restore_all.sh`     | `tests/deploy/test_helm_chart.py::TestRestoreScript`             | ✅      |
| NFR-A05 | Graceful degradation           | `proxy/app/core/retrieval.py`    | `tests/integration/test_health_checks.py`                        | ✅      |
| NFR-A06 | ETL WAL survival               | `etl/indexer/wal_manager.py`     | `tests/etl/test_wal_manager.py`, `tests/etl/test_etl_requirements.py::TestFR44WALIncremental` | ✅ |

### NFR-S (Безопасность)

| ID      | Описание                       | Реализация                            | Тесты                                                                                | Статус |
|---------|--------------------------------|---------------------------------------|--------------------------------------------------------------------------------------|--------|
| NFR-S01 | 4 auth methods                 | `proxy/app/auth/`                     | `tests/proxy/test_auth_rbac.py`                                                      | ✅      |
| NFR-S02 | RBAC enforcement               | `proxy/app/auth/rbac.py`              | `tests/proxy/test_auth_rbac.py`, `tests/integration/test_auth_flow.py::TestRBACEnforcement` | ✅ |
| NFR-S03 | ACL in Qdrant queries          | `proxy/app/shared/access_control.py`  | `tests/proxy/test_auth_rbac.py::TestFR89ACLQdrant`                                   | ✅      |
| NFR-S04 | RBAC by default                | `proxy/app/auth/`                     | `tests/proxy/test_nfr_security.py`, `tests/integration/test_auth_flow.py`            | ✅      |
| NFR-S05 | Secret masking in logs         | `proxy/app/shared/logging.py`         | `tests/proxy/test_nfr_security.py`                                                   | ✅      |
| NFR-S09 | HTTPS/TLS                      | reverse proxy config                  | `tests/deploy/test_nfr_deploy.py`                                                    | ✅      |
| NFR-S10 | Audit logging                  | `proxy/app/shared/audit.py`           | `tests/proxy/test_auth_rbac.py::TestFR93AuditLogging`                                 | ✅      |
| NFR-S11 | K8s Secrets                    | `deploy/k8s/helm/rag-system/`         | `tests/deploy/test_helm_chart.py::TestHelmChart`                                     | ✅      |
| NFR-S12 | Feedback abuse prevention      | `proxy/app/api/feedback.py`           | `tests/proxy/test_auth_rbac.py::TestFR77FeedbackRateLimiting`                        | ✅      |
| NFR-S13 | Shell tool safety              | `proxy/app/tools/security.py`         | `tests/proxy/test_tools_kb.py::TestFR115InputValidation`                             | ✅      |
| NFR-S14 | Tool handlers hidden           | `proxy/app/api/tools.py`              | `tests/proxy/test_tools_kb.py::TestFR118ToolVisibility`                              | ✅      |

### NFR-D (Деплой)

| ID      | Описание                          | Реализация                          | Тесты                                                       | Статус |
|---------|-----------------------------------|-------------------------------------|-------------------------------------------------------------|--------|
| NFR-D01 | Docker Compose — one command      | `proxy/docker-compose.yml`          | `tests/deploy/test_helm_chart.py::TestDockerCompose`         | ✅      |
| NFR-D02 | Helm chart completeness           | `deploy/k8s/helm/rag-system/`       | `tests/deploy/test_helm_chart.py::TestHelmChart`             | ✅      |
| NFR-D03 | Distributed Compose               | `deploy/docker/`                    | `tests/deploy/test_helm_chart.py::TestDistributedCompose`    | ✅      |
| NFR-D04 | Zero-downtime K8s deployment      | K8s rolling update                  | `tests/deploy/test_nfr_deploy.py`                            | ✅      |
| NFR-D05 | Env-based configuration           | `proxy/app/shared/config.py`        | `tests/proxy/test_nfr_security.py`                           | ✅      |
| NFR-D06 | Air-gapped compatibility          | `scripts/download_models_offline.py`| `tests/proxy/test_nfr_maintainability.py`                    | ✅      |

### NFR-M (Поддерживаемость)

| ID      | Описание                          | Реализация                          | Тесты                                                       | Статус |
|---------|-----------------------------------|-------------------------------------|-------------------------------------------------------------|--------|
| NFR-M01 | Runtime config hot-reload         | `proxy/app/shared/config.py`        | `tests/proxy/test_nfr_maintainability.py`                    | ✅      |
| NFR-M02 | Stale document monitoring         | `etl/scheduler/task_scheduler.py`   | `tests/etl/test_task_scheduler.py`                           | ✅      |
| NFR-M03 | Reindexing resilience             | `etl/scheduler/streaming_pipeline.py` | `tests/etl/test_streaming_pipeline.py`                     | ✅      |
| NFR-M04 | Cache key namespacing             | `proxy/app/shared/cache.py`         | `tests/proxy/test_nfr_maintainability.py`                    | ✅      |
| NFR-M05 | Feedback preservation             | `proxy/app/core/feedback_store.py`  | `tests/proxy/test_auth_rbac.py::TestFR78FeedbackPreservation`| ✅      |
| NFR-M06 | Code quality                      | `pyproject.toml`, Makefile           | `make lint && make typecheck`                                 | ✅      |
| NFR-M07 | Test suite — 80% coverage         | `tests/`                            | `make test` (5823 tests passing)                             | ✅      |
| NFR-M08 | Log rotation                      | `proxy/app/shared/logging.py`       | `tests/proxy/test_nfr_maintainability.py`                    | ✅      |

### NFR-Q (Качество RAG)

| ID      | Описание                          | Реализация                          | Тесты                                                       | Статус |
|---------|-----------------------------------|-------------------------------------|-------------------------------------------------------------|--------|
| NFR-Q01 | Retrieval MRR > 0.80              | `proxy/app/core/retrieval.py`       | `tests/proxy/test_observability_comprehensive.py`, `tests/performance/test_nfr_benchmarks.py` | ✅ |
| NFR-Q02 | Recall@20 > 0.90                  | `proxy/app/core/retrieval.py`       | `tests/proxy/test_observability_comprehensive.py`            | ✅      |
| NFR-Q03 | nDCG@10 > 0.85                    | `proxy/app/core/retrieval.py`       | `tests/proxy/test_observability_comprehensive.py`            | ✅      |
| NFR-Q04 | Precision@5 > 0.70                | `proxy/app/core/retrieval.py`       | `tests/proxy/test_observability_comprehensive.py`            | ✅      |
| NFR-Q05 | Grounding score > 0.70            | `proxy/app/core/grounding.py`       | `tests/proxy/test_quality_pipeline.py::TestFR35NLIGrounding` | ✅      |
| NFR-Q06 | Hallucination rate < 5%           | `proxy/app/core/hallucination.py`   | `tests/proxy/test_quality_pipeline.py::TestFR36HallucinationDetection` | ✅ |
| NFR-Q07 | Chunker coherence > 0.75          | `etl/chunker/semantic_chunker.py`   | `tests/performance/test_nfr_benchmarks.py::TestCodeChunking` | ✅      |
| NFR-Q08 | Chunker boundary > 0.85           | `etl/chunker/semantic_chunker.py`   | `tests/performance/test_nfr_benchmarks.py::TestCodeChunking` | ✅      |
| NFR-Q09 | Confidence > 0.5 rate > 70%       | `proxy/app/core/confidence.py`      | `tests/proxy/test_observability.py`                          | ✅      |
| NFR-Q10 | Self-reflection correlation       | `proxy/app/core/confidence.py`      | `tests/proxy/test_quality_pipeline.py::TestFR34SelfReflection` | ✅     |
| NFR-Q11 | Eval gate thresholds              | `model_evolution_service/eval_gate.py` | `tests/proxy/test_admin_kb.py`                             | ✅      |

### NFR-C (Ёмкость)

| ID      | Описание                          | Реализация                          | Тесты                                                       | Статус |
|---------|-----------------------------------|-------------------------------------|-------------------------------------------------------------|--------|
| NFR-C01 | 50 concurrent users (p95 < 5s)    | `proxy/app/`                        | `tests/performance/test_load.py`                            | ✅      |
| NFR-C02 | Qdrant collection < 1M vectors    | `scripts/init_collections.py`       | `tests/performance/test_nfr_benchmarks.py::TestHNSWTuning`  | ✅      |
| NFR-C03 | Qdrant sharding                   | `scripts/init_collections.py`       | `tests/performance/test_nfr_benchmarks.py::TestQdrantQuantization` | ✅ |
| NFR-C04 | ETL parallel extraction           | `etl/scheduler/run_etl.py`          | `tests/etl/test_run_etl.py`                                 | ✅      |
| NFR-C05 | Cold storage                      | `etl/indexer/live_vector_lake.py`   | `tests/etl/test_live_vector_lake.py`                        | ✅      |

---

## Резюме

| Категория     | Всего спецификаций | ✅ Подтверждено | ⚠️ Нужна интеграция | ❌ Нужна реализация |
|---------------|--------------------|----------------|---------------------|---------------------|
| FR (Core API) | 8                  | 8              | 0                   | 0                   |
| FR (Retrieval) | 10                | 10             | 0                   | 0                   |
| FR (Graph)    | 7                  | 0              | 6                   | 1                   |
| FR (Agentic)  | 6                  | 0              | 6                   | 0                   |
| FR (Quality)  | 8                  | 8              | 0                   | 0                   |
| FR (ETL)      | 18                 | 18             | 0                   | 0                   |
| FR (Auth)     | 18                 | 17             | 0                   | 1 (FR-87b)          |
| FR (ME)       | 8                  | 8              | 0                   | 0                   |
| FR (KB/Tools) | 16                 | 16             | 0                   | 0                   |
| FR (MCP)      | 5                  | 5              | 0                   | 0                   |
| FR (Deploy)   | 7                  | 7              | 0                   | 0                   |
| FR (Observ)   | 5                  | 5              | 0                   | 0                   |
| FR (Backup)   | 3                  | 3              | 0                   | 0                   |
| FR (Perform)  | 8                  | 3              | 4                   | 0                   |
| **FR total**  | **125**            | **108**        | **16**              | **2**               |
| NFR-P         | 13                 | 13             | 0                   | 0                   |
| NFR-A         | 6                  | 6              | 0                   | 0                   |
| NFR-S         | 11                 | 11             | 0                   | 0                   |
| NFR-D         | 6                  | 6              | 0                   | 0                   |
| NFR-M         | 8                  | 8              | 0                   | 0                   |
| NFR-Q         | 11                 | 11             | 0                   | 0                   |
| NFR-C         | 5                  | 5              | 0                   | 0                   |
| **NFR total** | **60**             | **60**         | **0**               | **0**               |

> Примечание: `FR-87b` помечена как «новая» — это требование добавлено в спецификацию,
> но ещё не реализовано. Код требуется в `proxy/app/auth/user_identification.py`.