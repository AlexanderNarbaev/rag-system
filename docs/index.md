# RAG System — Корпоративный ассистент знаний / Corporate Knowledge Assistant

OpenAI-совместимый RAG-прокси с ETL-пайплайном для Confluence, Jira, GitLab, документов, книг и истории чатов — индексация в Qdrant + Neo4j, обслуживание через конфигурируемый LLM-бэкенд.

OpenAI-compatible RAG proxy with ETL pipeline for Confluence, Jira, GitLab, documents, books, and chat history — indexed into Qdrant + Neo4j, served via configurable LLM backend.

**Версия / Version:** v0.3.0 | **Тестов / Tests:** 483 passing | **Зрелость / Maturity:** RAG Level 4 (Agentic) operational

---

## Архитектура / Architecture at a Glance

![C4 Level 1 — System Context](diagrams/c4-level1-context.svg)

### RU

Система состоит из четырёх основных компонентов:

| Слой | Роль | Технология |
|------|------|------------|
| **ETL Pipeline** | Извлечение, чанкинг, эмбеддинг, индексация данных | Python, spaCy, sentence-transformers |
| **RAG Proxy** | OpenAI-совместимый API, гибридный поиск, LLM-роутинг | FastAPI, LangGraph, Qdrant, Neo4j |
| **HITL Dashboard** | Экспертная проверка и сбор обратной связи | Streamlit |
| **MCP Server** | Model Context Protocol сервер для IDE-интеграции | FastMCP |

### EN

The system has four primary components:

| Layer | Role | Technology |
|-------|------|------------|
| **ETL Pipeline** | Data extraction, chunking, embedding, indexing | Python, spaCy, sentence-transformers |
| **RAG Proxy** | OpenAI-compatible API, hybrid retrieval, LLM routing | FastAPI, LangGraph, Qdrant, Neo4j |
| **HITL Dashboard** | Expert review and feedback collection | Streamlit |
| **MCP Server** | Model Context Protocol server for IDE integration | FastMCP |

Подробнее — в разделе [C4 Diagrams](diagrams/index.md). / See the [C4 Diagrams](diagrams/index.md) section for detailed container and component views.

---

## Быстрый старт / Quick Start

### RU

```bash
# 1. Установка компонентов RAG-системы:
bash setup.sh --rag-system

# 2. Конфигурация:
cd rag-system/proxy
cp .env.example .env  # отредактируйте под свои настройки

# 3. Запуск прокси:
docker-compose up -d

# 4. Запуск ETL-пайплайна:
cd ../etl
python scheduler/run_etl.py --config config/etl_config.yaml

# 5. Проверка:
curl http://localhost:8080/v1/health
```

### EN

```bash
# 1. Install RAG system components:
bash setup.sh --rag-system

# 2. Configure:
cd rag-system/proxy
cp .env.example .env  # edit with your settings

# 3. Start the proxy:
docker-compose up -d

# 4. Run ETL pipeline:
cd ../etl
python scheduler/run_etl.py --config config/etl_config.yaml

# 5. Verify:
curl http://localhost:8080/v1/health
```

Для автономных (air-gapped) развёртываний см. [Proxy Deployment Guide](deploy_proxy.md). / For air-gapped deployments, see the [Proxy Deployment Guide](deploy_proxy.md).

---

## Ключевые возможности / Key Features

<div class="grid cards" markdown>

-   :material-database-search: **Гибридный поиск / Hybrid Retrieval**

    ---

    Плотные (1024-dim) + разреженные (lexical) векторы с Reciprocal Rank Fusion (RRF) через Qdrant.

    Dense (1024-dim) + sparse (lexical) vectors with Reciprocal Rank Fusion (RRF) via Qdrant.

-   :material-sort-variant: **Cross-Encoder реранкинг / Cross-Encoder Reranking**

    ---

    MiniLM-L-6-v2 переранжирует top-N кандидатов для повышения точности.

    MiniLM-L-6-v2 reranks top-N candidates for precision.

-   :material-graph: **Граф знаний / Knowledge Graph**

    ---

    Neo4j с 10 типами сущностей, 9 типами связей, многошаговым обходом.

    Neo4j with 10 entity types, 9 relation types, multi-hop traversal.

-   :material-brain: **Двухмодельная архитектура / Dual-Model Architecture**

    ---

    Лёгкая SLM для быстрой маршрутизации + полноразмерная LLM для генерации ответов.

    Lightweight SLM for fast routing + full-scale LLM for response generation.

-   :material-api: **OpenAI-совместимый API / OpenAI-Compatible API**

    ---

    Полная замена любого OpenAI-клиента. `/v1/chat/completions`, `/v1/models`, `/v1/health`.

    Drop-in replacement for any OpenAI client. `/v1/chat/completions`, `/v1/models`, `/v1/health`.

-   :material-puzzle: **Мульти-провайдерная поддержка / Multi-Provider Support**

    ---

    Подключаемые адаптеры для vLLM, llama.cpp и любых OpenAI-совместимых инференс-серверов.

    Pluggable adapters for vLLM, llama.cpp, and any OpenAI-compatible inference server.

-   :material-tools: **Вызов инструментов / Tool Calling**

    ---

    MCP-сервер предоставляет RAG-инструменты для IDE (OpenCode, Claude Desktop) и других MCP-клиентов.

    MCP server exposes RAG tools to IDEs (OpenCode, Claude Desktop) and other MCP-compatible clients.

-   :material-refresh: **Инкрементальный ETL / Incremental ETL**

    ---

    WAL-чейкпоинтинг, SHA-256 content-addressable чанки. Переиндексируются только изменённые документы.

    WAL-based checkpointing, SHA-256 content-addressable chunks. Only changed documents reindexed.

-   :material-shield-check: **Автономный режим / Air-Gapped Ready**

    ---

    Все модели предварительно загружены. Никаких внешних API-вызовов во время работы.

    All models pre-downloaded. No external API calls at runtime. Works fully offline.

-   :material-chart-line: **Наблюдаемость / Observability**

    ---

    Prometheus-метрики, структурированное JSON-логирование, health-чеки с graceful degradation.

    Prometheus metrics, structured JSON logging, health checks with graceful degradation.

</div>

---

## Технологический стек / Technology Stack

### RU

| Компонент | Технология | Назначение |
|-----------|-----------|------------|
| **LLM** | Любая OpenAI-совместимая модель (через vLLM, llama.cpp или OpenAI-compatible API) | Генерация ответов (конфигурируемая длина контекста) |
| **SLM** | Лёгкая модель (~2–3B параметров) | Маршрутизация запросов, извлечение сущностей (быстрый путь) |
| **Embeddings** | BAAI/bge-m3 | Dense (1024-dim) + sparse (lexical) + ColBERT |
| **Vector DB** | Qdrant | Гибридный поиск, RRF-фьюжн, on-disk sparse index |
| **Graph DB** | Neo4j | Связи сущностей, многошаговый обход |
| **Cache** | Redis | Кэш эмбеддингов, результатов реранкинга, кэш ответов |
| **Proxy** | FastAPI + LangGraph | OpenAI-совместимый API, агентная оркестрация |
| **ETL** | Python, requests, BeautifulSoup, spaCy | Извлечение, чанкинг, индексация данных |
| **Dashboard** | Streamlit | HITL экспертная проверка |
| **MCP** | FastMCP | Model Context Protocol сервер для IDE-интеграции |
| **Auth** | Keycloak (запланировано v0.4) | Корпоративный SSO, RBAC |

### EN

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM** | Any OpenAI-compatible model (via vLLM, llama.cpp, or OpenAI-compatible API) | Response generation (configurable context length) |
| **SLM** | Lightweight model (~2–3B params) | Query routing, entity extraction (fast path) |
| **Embeddings** | BAAI/bge-m3 | Dense (1024-dim) + sparse (lexical) + ColBERT |
| **Vector DB** | Qdrant | Hybrid search, RRF fusion, on-disk sparse index |
| **Graph DB** | Neo4j | Entity relationships, multi-hop traversal |
| **Cache** | Redis | Embedding cache, rerank results, response cache |
| **Proxy** | FastAPI + LangGraph | OpenAI-compatible API, agentic orchestration |
| **ETL** | Python, requests, BeautifulSoup, spaCy | Data extraction, chunking, indexing |
| **Dashboard** | Streamlit | HITL expert review |
| **MCP** | FastMCP | Model Context Protocol server for IDE integration |
| **Auth** | Keycloak (planned v0.4) | Corporate SSO, RBAC |

---

## Навигация / Navigation Guide

| Мне нужно... / I want to... | Перейти... / Go to... |
|-------------|---------|
| Понять, почему приняты те или иные решения / Understand why decisions were made | [Architecture Decision Records](adr/index.md) |
| Увидеть архитектуру визуально / See system architecture visually | [C4 Diagrams](diagrams/index.md) |
| Узнать, как работает поиск / Learn how retrieval works | [Performance & Quality Guide](guides/performance-quality.md) |
| Добавить новый источник данных / Add a new data source | [Extensibility Guide](guides/extensibility-data-sources.md) |
| Настроить контроль доступа / Set up access control | [Access Control & RBAC](guides/access-control-rbac.md) |
| Понять граф знаний / Understand the knowledge graph | [Knowledge Graph Strategy](guides/knowledge-graph-strategy.md) |
| Интегрировать с OpenCode IDE / Integrate with OpenCode IDE | [OpenCode Integration](guides/integration-opencode.md) |
| Вызвать API программно / Call the API programmatically | [API Reference](api_reference.md) |
| Развернуть прокси / Deploy the proxy | [Proxy Deployment](deploy_proxy.md) |
| Развернуть ETL-пайплайн / Deploy the ETL pipeline | [ETL Deployment](deploy_etl.md) |
| Мониторить в production / Monitor in production | [Operations Guide](guides/operations-guide.md) |
| Отладить проблему / Debug an issue | [Troubleshooting](guides/troubleshooting.md) |
| Узнать, что запланировано / See what's coming next | [Development Roadmap](guides/roadmap.md) |
| Проверить готовность к production / Check production readiness | [Best Practices Checklist](guides/best-practices-checklist.md) |

---

## Зрелость RAG / RAG Maturity

### RU

| Уровень | Статус |
|---------|--------|
| Naive RAG (только dense) | Превзойдён / Exceeded |
| Advanced RAG (hybrid + rerank + dedup) | Реализован / Implemented |
| GraphRAG (извлечение сущностей + Neo4j) | Реализован / Implemented |
| Agentic (LangGraph оркестратор) | Реализован / Implemented |
| Self-Correcting (CRAG-style evaluator) | Частично / Partial |

### EN

| Level | Status |
|-------|--------|
| Naive RAG (dense only) | Exceeded |
| Advanced RAG (hybrid + rerank + dedup) | Implemented |
| GraphRAG (entity extraction + Neo4j) | Implemented |
| Agentic (LangGraph orchestrator) | Implemented |
| Self-Correcting (CRAG-style evaluator) | Partial |

Подробнее — [RAG Maturity Assessment](guides/rag-maturity-assessment.md). / See [RAG Maturity Assessment](guides/rag-maturity-assessment.md) for full details.

---

## Лицензия / License

MIT © 2026 Alexander Narbaev
