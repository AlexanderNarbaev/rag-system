# RAG System — Корпоративный ассистент знаний · Corporate Knowledge Assistant

**EN:** OpenAI-compatible RAG proxy with ETL pipeline for Confluence, Jira, GitLab, documents, books, and chat history — indexed into Qdrant + Neo4j, served via any LLM through an OpenAI-compatible inference server.

**RU:** OpenAI-совместимый RAG-прокси с ETL-конвейером для Confluence, Jira, GitLab, документов, книг и истории чатов — индексация в Qdrant + Neo4j, обслуживается любой LLM через OpenAI-совместимый сервер инференса.

---

## Status · Статус

**EN:** **v0.4** — Self-improving RAG with confidence scoring, active feedback, VERIFY_CASCADE routing, and knowledge base self-enrichment. 919 tests passing. See [ADR documents](docs/adr/) for architecture decisions and [C4 diagrams](docs/diagrams/) for visual architecture.

**RU:** **v0.4** — Самоулучшающийся RAG с оценкой уверенности, активной обратной связью, маршрутизацией VERIFY_CASCADE и самообогащением базы знаний. 919 тестов проходят. См. [ADR-документы](docs/adr/) с архитектурными решениями и [C4-диаграммы](docs/diagrams/) с визуальной архитектурой.

---

## Architecture · Архитектура

**EN:** Three-layer architecture with supporting services:

1. **ETL Layer** — data extraction, semantic chunking, embedding, indexing (runs on a separate machine)
2. **Proxy Layer** — FastAPI app with OpenAI-compatible API, hybrid retrieval, reranking, multi-provider LLM routing
3. **HITL Layer** — Streamlit expert dashboard for feedback and quality control
4. **MCP Server** — Model Context Protocol server exposing RAG tools to MCP-compatible clients (OpenCode, Claude Desktop)

**RU:** Трёхуровневая архитектура с вспомогательными сервисами:

1. **Уровень ETL** — извлечение данных, семантический чанкинг, эмбеддинг, индексация (на отдельной машине)
2. **Уровень Прокси** — FastAPI с OpenAI-совместимым API, гибридный поиск, реранкинг, мультипровайдерная маршрутизация LLM
3. **Уровень HITL** — Streamlit дашборд экспертной оценки и контроля качества
4. **MCP Сервер** — Model Context Protocol сервер, предоставляющий RAG-инструменты MCP-совместимым клиентам (OpenCode, Claude Desktop)

```
┌─────────────────────────────────────────────────────────────────┐
│                        ETL Machine · Машина ETL                    │
│  extractors/ → chunker/ → graph_builder/ → indexer/ → scheduler/ │
│  (Confluence, Jira, GitLab, Books, Docs, Chats → Qdrant+Neo4j)  │
└──────────────────┬──────────────────────────────────────────────┘
                   │ shared volumes / API
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Proxy Machine · Машина прокси (Docker)          │
│  ┌──────────────────────────────────────────────────────┐       │
│  │ rag-proxy (FastAPI :8080)                             │       │
│  │  ├─ retrieval (Qdrant hybrid: dense+sparse RRF)      │       │
│  │  ├─ rerank (cross-encoder)                            │       │
│  │  ├─ context_builder (dedup + versioning)              │       │
│  │  ├─ provider_adapter (OpenAI / Anthropic / Ollama)    │       │
│  │  ├─ llm_router (streaming + non-streaming + tools)    │       │
│  │  ├─ slm_router (intent classification, decomposition) │       │
│  │  ├─ token_optimizer (BPE counting, compression)       │       │
│  │  ├─ orchestrator (LangGraph: agentic multi-step)      │       │
│  │  ├─ cache (Redis: embeddings, rerank, responses)      │       │
│  │  └─ hitl (interaction logging + feedback)             │       │
│  ├─ qdrant (vector DB :6333)                              │       │
│  ├─ redis (cache :6379)                                   │       │
│  └─ neo4j (graph DB :7687)                                │       │
└──────────────────┬──────────────────────────────────────────────┘
                   │ OpenAI-compatible API (/v1/chat/completions)
                   ▼
         OpenWebUI, OpenCode, n8n, custom clients
                   │
                   ▼
         HITL Dashboard (Streamlit :8501) — expert feedback
                   │
                   ▼
         MCP Server — RAG tools for MCP clients (OpenCode, Claude)
```

### C4 Architecture Diagrams · C4-диаграммы

| Level | Scope | File |
|-------|-------|------|
| **L1** | System Context (11 nodes) | [`c4-level1-context`](docs/diagrams/c4-level1-context.svg) |
| **L2** | Containers (10 nodes) | [`c4-level2-containers`](docs/diagrams/c4-level2-containers.svg) |
| **L3** | RAG Proxy Components (13 nodes) | [`c4-level3-proxy-components`](docs/diagrams/c4-level3-proxy-components.svg) |
| **L3** | ETL Pipeline Components (14 nodes) | [`c4-level3-etl-components`](docs/diagrams/c4-level3-etl-components.svg) |

**EN:** Editable `.excalidraw` files available in `docs/diagrams/`.

**RU:** Редактируемые `.excalidraw` файлы доступны в `docs/diagrams/`.

---

## Key Principles · Ключевые принципы

**EN:**

1. **Air-gapped first** — all models pre-downloaded, no external API calls at runtime. The system must function fully offline.
2. **Graceful degradation** — every component can fail independently: Neo4j unavailable → skip graph expansion; Reranker OOM → use raw hybrid scores; Redis down → fall back to in-memory cache. The proxy never crashes on component failure.
3. **Incremental by default** — WAL-based ETL checkpointing. SHA-256 content-addressable chunks. Only changed documents are reindexed.
4. **OpenAI compatibility** — drop-in replacement for any OpenAI client. RAG-specific extensions (`rag_version`, `rag_force_refresh`) are silently ignored by standard clients.
5. **Multi-provider routing** — supports OpenAI-compatible (vLLM, llama.cpp, Ollama, LiteLLM), Anthropic (Claude API), and Generic REST. Tool/function calling works across all providers.
6. **Dual-model routing** — a small language model (SLM) handles fast preprocessing (intent classification, query decomposition); a large language model (LLM) handles heavy generation. Keeps latency low for routing tasks.
7. **Optional complexity** — LangGraph orchestrator, Neo4j graph expansion, and Redis caching are all optional. The system runs in simple RAG mode by default.
8. **Token economy** — BPE-aware token counting, 4 compression strategies, smart budget allocation.
9. **Self-improving RAG** — confidence scoring on every answer, VERIFY_CASCADE routing triggers query rewrites for low-confidence responses, active feedback via `/v1/feedback` endpoint, knowledge base self-enrichment from expert corrections.

**RU:**

1. **Air-gapped first** — все модели предварительно загружены, никаких внешних API-вызовов во время работы. Система полностью автономна.
2. **Graceful degradation** — каждый компонент может отказать независимо: Neo4j недоступен → пропускаем графовое расширение; реранкер OOM → используем сырые гибридные оценки; Redis недоступен → переключаемся на in-memory кэш. Прокси никогда не падает при отказе компонента.
3. **Инкрементальность по умолчанию** — WAL-контрольные точки ETL. SHA-256 контентно-адресуемые чанки. Только изменённые документы переиндексируются.
4. **OpenAI-совместимость** — совместим с любым OpenAI-клиентом. RAG-расширения (`rag_version`, `rag_force_refresh`) игнорируются стандартными клиентами.
5. **Мультипровайдерная маршрутизация** — поддержка OpenAI-совместимых (vLLM, llama.cpp, Ollama, LiteLLM), Anthropic (Claude API) и Generic REST. Tool/function calling работает для всех провайдеров.
6. **Двухмодельная маршрутизация** — малая языковая модель (SLM) для быстрой предобработки; большая языковая модель (LLM) для генерации. Минимизирует задержки.
7. **Опциональная сложность** — LangGraph-оркестратор, Neo4j-расширение графом и Redis-кэширование опциональны. По умолчанию система работает в простом RAG-режиме.
8. **Экономия токенов** — BPE-осознанный подсчёт токенов, 4 стратегии сжатия, умное распределение бюджета.
9. **Самоулучшающийся RAG** — оценка уверенности для каждого ответа, VERIFY_CASCADE-маршрутизация запускает перезапрос при низкой уверенности, активная обратная связь через `/v1/feedback`, самообогащение базы знаний из экспертных исправлений.

---

## Project Structure · Структура проекта

```
rag-system/
├── etl/                              # ETL pipeline (runs separately) · запускается отдельно
│   ├── extractors/                   # confluence.py, jira.py, gitlab.py, books.py, docs.py, chats.py
│   ├── chunker/                      # semantic_chunker.py, hash_versioning.py
│   ├── graph_builder/                # entity_extractor.py, neo4j_loader.py, schema.yaml
│   ├── indexer/                      # qdrant_hybrid.py, live_vector_lake.py, wal_manager.py
│   ├── scheduler/                    # run_etl.py (orchestrates full pipeline)
│   ├── config/                       # etl_config.yaml
│   ├── Dockerfile.etl
│   └── requirements_etl.txt
├── proxy/                            # RAG proxy (Dockerized) · в Docker
│   ├── app/
│   │   ├── main.py                   # FastAPI entry point (8 endpoints + health + metrics)
│   │   ├── orchestrator.py           # LangGraph agentic query pipeline (7-node state graph)
│   │   ├── retrieval.py              # Qdrant hybrid search (dense+sparse RRF) + graph expansion
│   │   ├── rerank.py                 # Cross-encoder reranker
│   │   ├── context_builder.py        # Context assembly: dedup, versioning, token-budgeted assembly
│   │   ├── provider_adapter.py       # Multi-provider adapter (OpenAI, Anthropic, Ollama, Generic)
│   │   ├── llm_router.py             # Async LLM adapter (streaming + non-streaming + tools)
│   │   ├── slm_router.py             # SLM: intent classification, query decomposition, entity extraction
│   │   ├── token_optimizer.py        # BPE-aware token counting, compression, budget allocation
│   │   ├── cache.py                  # Redis + in-memory multi-tier cache
│   │   ├── hitl.py                   # Human-in-the-loop: async interaction logging, feedback
│   │   ├── metrics.py                # Prometheus metrics (counters, histograms, gauges)
│   │   ├── rate_limiter.py           # Token bucket rate limiting middleware (per IP)
│   │   ├── middleware.py             # Request ID, correlation ID, logging middleware
│   │   ├── logging_config.py         # Structured logging (text/JSON), secret masking
│   │   ├── config.py                 # Environment-based configuration (all settings)
│   │   └── utils.py                  # Shared utilities: token counting, hashing, masking, safe division
│   ├── .env                          # Configuration (edit before first run) · настройка перед запуском
│   ├── Dockerfile
│   ├── requirements_proxy.txt
│   └── docker-compose.yml            # Qdrant + Redis + Neo4j + Proxy
├── mcp_server/                       # MCP server for OpenCode/Claude Desktop integration
│   ├── server.py                     # STDIO + Streamable HTTP transports, tools/resources/prompts
│   └── __init__.py
├── hitl_dashboard/                   # Streamlit expert review dashboard
│   ├── dashboard.py
│   └── feedback_logger.py
├── scripts/                          # Utility scripts · утилиты
│   ├── init_collections.py           # Initialize Qdrant collections
│   └── download_models_offline.py    # Pre-download models for air-gapped env
├── tests/                            # Test suite (483+ tests passing)
│   ├── proxy/                        # 282 proxy unit tests
│   ├── etl/                          # 121 ETL unit tests
│   ├── integration/                  # 56 integration tests
│   ├── mcp_server/                   # 46 MCP server tests
│   └── conftest.py                   # Shared fixtures
├── docs/                             # Documentation · документация
│   ├── adr/                          # 7 Architecture Decision Records
│   ├── diagrams/                     # 4 C4 diagrams (SVG + Excalidraw)
│   └── guides/                       # 11 design & implementation guides
├── Makefile                          # Primary dev entry point
├── pyproject.toml                    # Python project config (ruff, mypy, pytest)
├── setup.sh                          # Installation script
├── opencode.json                     # OpenCode IDE configuration
├── AGENTS.md
└── README.md
```

---

## Tech Stack · Технологический стек

| Component | Technology | Purpose / Назначение |
|-----------|-----------|---------|
| **LLM** | Any model via OpenAI-compatible API (e.g., Gemma, Llama, Mistral, Qwen) | Response generation · Генерация ответов |
| **SLM** | Any small model via OpenAI-compatible API (e.g., Gemma-2B, Phi-3, Qwen2.5-1.5B) | Query routing, entity extraction · Маршрутизация, извлечение сущностей |
| **Embeddings** | BAAI/bge-m3 (or any SentenceTransformer model) | Dense (1024-dim) + sparse (lexical) + ColBERT |
| **Vector DB** | Qdrant | Hybrid search (dense + sparse), RRF fusion |
| **Graph DB** | Neo4j | Entity relationships, multi-hop traversal |
| **Cache** | Redis | Embedding cache, rerank results, response cache |
| **Proxy** | FastAPI + LangGraph | OpenAI-compatible API, agentic orchestration · агентная оркестрация |
| **Inference** | Any OpenAI-compatible server (vLLM, llama.cpp, Ollama, LiteLLM, etc.) | LLM/SLM serving · обслуживание моделей |
| **Providers** | OpenAI, Anthropic, Ollama, Generic REST | Multi-provider routing with tool/function calling |
| **ETL** | Python, requests, BeautifulSoup, spaCy | Data extraction, chunking, indexing |
| **Dashboard** | Streamlit | HITL expert review · экспертная оценка |
| **MCP** | FastMCP | Model Context Protocol server for IDE integration |
| **Auth** | JWT + Keycloak (planned) | Corporate SSO, RBAC · корпоративная аутентификация |
| **Infra** | Docker Compose | Containerized deployment · контейнеризация |

---

## Key Design Decisions · Ключевые проектные решения

**EN:**

1. **Hybrid embeddings** — BAAI/bge-m3 provides dense + sparse + ColBERT in one model
2. **Qdrant** — native hybrid search with RRF fusion, on-disk sparse index
3. **Semantic chunking** — MDKeyChunker, structure-aware splitting by headers/sections
4. **Version-aware** — SHA-256 hashing, LiveVectorLake for hot/cold storage stratification
5. **Dual LLM** — SLM for fast query routing + LLM for generation (any OpenAI-compatible models)
6. **Multi-provider** — transparent routing to OpenAI, Anthropic, Ollama, or Generic endpoints with tool/function calling
7. **OpenAI-compatible** — drop-in replacement for any OpenAI client
8. **WAL-based ETL** — incremental checkpointing with resume capability
9. **Air-gapped** — all models pre-downloaded, no external API dependencies
10. **LangGraph** — optional agentic orchestration with multi-step retrieval and self-correction

**RU:**

1. **Гибридные эмбеддинги** — BAAI/bge-m3 предоставляет dense + sparse + ColBERT в одной модели
2. **Qdrant** — нативный гибридный поиск с RRF-фьюжном, on-disk sparse index
3. **Семантический чанкинг** — MDKeyChunker, структурно-осознанное разделение по заголовкам/секциям
4. **Версионирование** — SHA-256 хеширование, LiveVectorLake для стратификации hot/cold хранения
5. **Двухмодельная LLM** — SLM для быстрой маршрутизации + LLM для генерации (любые OpenAI-совместимые модели)
6. **Мультипровайдер** — прозрачная маршрутизация к OpenAI, Anthropic, Ollama или Generic эндпоинтам с поддержкой tool/function calling
7. **OpenAI-совместимость** — совместим с любым OpenAI-клиентом
8. **WAL-based ETL** — инкрементальные контрольные точки с возможностью возобновления
9. **Автономность (Air-gapped)** — все модели загружены заранее, внешние API не требуются
10. **LangGraph** — опциональная агентная оркестрация с многошаговым поиском и самокоррекцией

---

## Multi-Provider Support · Мультипровайдерная поддержка

**EN:** The proxy supports multiple AI providers through a unified adapter layer. Configure via `LLM_PROVIDER_TYPE`:

| Provider | `LLM_PROVIDER_TYPE` | Protocol | Tool Calling |
|----------|---------------------|----------|-------------|
| **OpenAI-compatible** | `openai` | OpenAI `/v1/chat/completions` | Yes · Да |
| **Anthropic** | `anthropic` | Claude Messages API | Yes · Да |
| **Ollama** | `ollama` | OpenAI-compatible via `ollama serve` | Yes · Да |
| **Generic REST** | `generic` | Custom endpoint, configurable mapping | Partial |

**RU:** Прокси поддерживает несколько AI-провайдеров через унифицированный слой адаптеров. Настройка через `LLM_PROVIDER_TYPE`:

| Провайдер | `LLM_PROVIDER_TYPE` | Протокол | Tool Calling |
|-----------|---------------------|----------|-------------|
| **OpenAI-совместимый** | `openai` | OpenAI `/v1/chat/completions` | Да |
| **Anthropic** | `anthropic` | Claude Messages API | Да |
| **Ollama** | `ollama` | OpenAI-совместимый через `ollama serve` | Да |
| **Generic REST** | `generic` | Произвольный эндпоинт, настраиваемый маппинг | Частично |

Tool/function calling is supported across all providers. The adapter automatically translates between internal OpenAI-compatible format and provider-specific schemas (Anthropic content blocks, Ollama native tools, etc.). Streaming is fully supported with real-time translation.

Tool/function calling поддерживается для всех провайдеров. Адаптер автоматически транслирует между внутренним OpenAI-совместимым форматом и схемами конкретных провайдеров. Стриминг полностью поддерживается с трансляцией в реальном времени.

---

## RAG Maturity Levels · Уровни зрелости RAG

**EN:**

| Level | Retrieval | Ranking | Multi-hop | Self-correction |
|-------|-----------|---------|-----------|-----------------|
| Naive | Dense only | None | No | No |
| Advanced | Hybrid (dense+BM25) | Cross-encoder | Query rewrite | No |
| **GraphRAG** | Graph+vector | Node centrality | Graph composition | Partial |
| Agentic | Adaptive multi-try | Sufficiency eval | Task decomposition | Full iterative |

This project implements **Advanced RAG with GraphRAG extensions** (Level 3).
The LangGraph orchestrator (`proxy/app/orchestrator.py`) provides agentic capabilities (Level 4) when enabled.

**RU:**

| Уровень | Поиск | Ранжирование | Многошаговость | Самокоррекция |
|---------|-------|-------------|----------------|---------------|
| Наивный | Только dense | Нет | Нет | Нет |
| Продвинутый | Гибридный (dense+BM25) | Cross-encoder | Перезапись запроса | Нет |
| **GraphRAG** | Граф+вектор | Центральность узлов | Графовая композиция | Частичная |
| Агентный | Адаптивный multi-try | Оценка достаточности | Декомпозиция задач | Полная итеративная |

Проект реализует **продвинутый RAG с расширениями GraphRAG** (уровень 3).
LangGraph-оркестратор (`proxy/app/orchestrator.py`) предоставляет агентные возможности (уровень 4) при включении.

---

## Documentation Index · Индекс документации

### Architecture Decision Records (ADRs)

| # | Decision / Решение | Document |
|---|--------------------|----------|
| 001 | BAAI/bge-m3 as embedding model | [`ADR-001`](docs/adr/ADR-001-bge-m3-embedding-model.md) |
| 002 | Qdrant for hybrid vector search | [`ADR-002`](docs/adr/ADR-002-qdrant-hybrid-search.md) |
| 003 | Dual-LLM (SLM + LLM) architecture | [`ADR-003`](docs/adr/ADR-003-dual-llm-architecture.md) |
| 004 | OpenAI-compatible proxy pattern | [`ADR-004`](docs/adr/ADR-004-openai-compatible-proxy.md) |
| 005 | Version-aware document indexing | [`ADR-005`](docs/adr/ADR-005-version-aware-indexing.md) |
| 006 | Agentic RAG with LangGraph | [`ADR-006`](docs/adr/ADR-006-agentic-rag-langgraph.md) |
| 007 | Human-in-the-loop feedback system | [`ADR-007`](docs/adr/ADR-007-hitl-feedback-system.md) |

### Design Guides · Руководства

| Guide / Руководство | Document |
|---------------------|----------|
| Extensibility: adding new data sources | [`extensibility-data-sources.md`](docs/guides/extensibility-data-sources.md) |
| Access control & RBAC | [`access-control-rbac.md`](docs/guides/access-control-rbac.md) |
| Knowledge graph enrichment & unrolling | [`knowledge-graph-strategy.md`](docs/guides/knowledge-graph-strategy.md) |
| Performance & quality best practices | [`performance-quality.md`](docs/guides/performance-quality.md) |
| RAG maturity assessment | [`rag-maturity-assessment.md`](docs/guides/rag-maturity-assessment.md) |
| Production readiness checklist | [`best-practices-checklist.md`](docs/guides/best-practices-checklist.md) |
| Roadmap (v0.1 → v1.0) | [`roadmap.md`](docs/guides/roadmap.md) |
| Deployment guide | [`deployment-guide.md`](docs/guides/deployment-guide.md) |
| Operations guide | [`operations-guide.md`](docs/guides/operations-guide.md) |
| OpenCode IDE integration | [`integration-opencode.md`](docs/guides/integration-opencode.md) |
| Troubleshooting | [`troubleshooting.md`](docs/guides/troubleshooting.md) |

---

## Quick Start · Быстрый старт

**EN:**

```bash
# 1. Install (one-time):
curl -fsSL https://raw.githubusercontent.com/AlexanderNarbaev/opencode_initializer/main/setup.sh | bash -s -- --full
bash setup.sh --rag-system

# 2. Configure:
cd rag-system/proxy
cp .env.example .env  # edit with your settings

# 3. Start the proxy:
docker-compose up -d

# 4. Run ETL pipeline:
cd ../etl
python scheduler/run_etl.py --config config/etl_config.yaml
```

**RU:**

```bash
# 1. Установка (однократно):
curl -fsSL https://raw.githubusercontent.com/AlexanderNarbaev/opencode_initializer/main/setup.sh | bash -s -- --full
bash setup.sh --rag-system

# 2. Настройка:
cd rag-system/proxy
cp .env.example .env  # отредактируйте под свои параметры

# 3. Запуск прокси:
docker-compose up -d

# 4. Запуск ETL-конвейера:
cd ../etl
python scheduler/run_etl.py --config config/etl_config.yaml
```

---

## Configuration · Конфигурация

**EN:** All configuration via environment variables or `.env` file in `proxy/.env`. Key settings:

```bash
# Required / Обязательные
QDRANT_HOST=localhost                        # Qdrant server
LLM_ENDPOINT=http://localhost:8000/v1        # OpenAI-compatible inference server
LLM_MODEL_NAME=your-model-name               # e.g., gemma-4-26b-it, meta-llama/Llama-3.1-70B
LLM_PROVIDER_TYPE=openai                     # openai, anthropic, ollama, generic

# SLM (optional, disabled if endpoint is empty)
SLM_ENDPOINT=http://localhost:8001/v1        # SLM inference server
SLM_MODEL_NAME=your-slm-model-name           # e.g., gemma-2b-it, Phi-3-mini-4k-instruct

# Optional features (disabled by default) / Опционально (выключены по умолчанию)
USE_LANGGRAPH=true                           # Enable agentic orchestration
USE_REDIS=true                               # Enable Redis caching
GRAPH_ENABLED=true                           # Enable Neo4j graph expansion
USE_GRAPH_EXPANSION=true                     # Enable graph context enrichment
RATE_LIMIT_ENABLED=true                      # Enable rate limiting
METRICS_ENABLED=true                         # Enable Prometheus metrics
LOG_FORMAT=json                              # Structured JSON logging
AUTH_ENABLED=true                            # Enable JWT authentication
```

See `proxy/app/config.py` for all available settings and defaults.

**RU:** Вся конфигурация через переменные окружения или файл `.env` в `proxy/.env`. См. `proxy/app/config.py` для всех настроек и значений по умолчанию.

---

## API Endpoints · API-эндпоинты

| Endpoint | Method | Description / Описание |
|----------|--------|------------------------|
| `/v1/chat/completions` | POST | Chat completion (streaming + non-streaming + tools) |
| `/v1/models` | GET | List available models · список моделей |
| `/v1/health` | GET | Health check (Qdrant + LLM status) · проверка здоровья |
| `/metrics` | GET | Prometheus metrics · метрики Prometheus |

**EN:** The `/v1/chat/completions` endpoint accepts standard OpenAI parameters plus:
- `rag_version` — request a specific document version
- `rag_force_refresh` — bypass response cache
- `tools` — tool/function calling definitions (works across all providers)
- `stream` — streaming via SSE (works across all providers)

**RU:** Эндпоинт `/v1/chat/completions` принимает стандартные OpenAI-параметры плюс:
- `rag_version` — запросить конкретную версию документа
- `rag_force_refresh` — обойти кэш ответов
- `tools` — определения tool/function calling (работает со всеми провайдерами)
- `stream` — стриминг через SSE (работает со всеми провайдерами)

---

## Running Tests · Запуск тестов

```bash
# All tests (no external services required) · Все тесты (внешние сервисы не требуются):
pytest tests/ -v

# Specific suites · Конкретные наборы:
pytest tests/proxy/ -v        # 282 proxy unit tests
pytest tests/etl/ -v          # 121 ETL unit tests
pytest tests/integration/ -v  # 56 integration tests

# Coverage · Покрытие:
pytest tests/ --cov=proxy --cov=etl --cov-report=html
```

---

## Development · Разработка

```bash
make install        # Full setup (proxy + ETL) · полная установка
make install-dev    # Setup with dev dependencies · установка с dev-зависимостями
make test           # Run all tests (483+ passing) · все тесты
make lint           # Lint with ruff · линтинг
make format         # Format with ruff · форматирование
make typecheck      # Run mypy static type checker · статическая типизация
make docker-build   # Build Docker images · сборка образов
make docker-up      # Start docker-compose services · запуск сервисов
make docker-down    # Stop docker-compose services · остановка сервисов
make all            # CI pipeline: install → lint → test · CI-конвейер
make help           # Show all available targets · все цели
```

---

## Git Remotes

- GitHub: https://github.com/AlexanderNarbaev/rag-system
- GitVerse: https://gitverse.ru/AlexandrNarbaev/rag-system

---

## License · Лицензия

MIT © 2026 Alexander Narbaev
