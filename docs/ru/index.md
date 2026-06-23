# RAG System — Корпоративный ассистент знаний

OpenAI-совместимый RAG-прокси с ETL-пайплайном для Confluence, Jira, GitLab, документов, книг и истории чатов — индексация в Qdrant + Neo4j, обслуживание через конфигурируемый LLM-бэкенд.

**Версия:** v0.3.0 | **Тестов:** 483 passing | **Зрелость:** RAG Level 4 (Agentic) operational

---

## Архитектура

![C4 Level 1 — System Context](diagrams/c4-level1-context.svg)

Система состоит из четырёх основных компонентов:

| Слой | Роль | Технология |
|------|------|------------|
| **ETL Pipeline** | Извлечение, чанкинг, эмбеддинг, индексация данных | Python, spaCy, sentence-transformers |
| **RAG Proxy** | OpenAI-совместимый API, гибридный поиск, LLM-роутинг | FastAPI, LangGraph, Qdrant, Neo4j |
| **HITL Dashboard** | Экспертная проверка и сбор обратной связи | Streamlit |
| **MCP Server** | Model Context Protocol сервер для IDE-интеграции | FastMCP |

Подробнее — в разделе [C4 Diagrams](diagrams/index.md).

---

## Быстрый старт

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

Для автономных (air-gapped) развёртываний см. [Proxy Deployment Guide](deploy_proxy.md).

---

## Ключевые возможности

<div class="grid cards" markdown>

-   :material-database-search: **Гибридный поиск**

    ---

    Плотные (1024-dim) + разреженные (lexical) векторы с Reciprocal Rank Fusion (RRF) через Qdrant.

-   :material-sort-variant: **Cross-Encoder реранкинг**

    ---

    MiniLM-L-6-v2 переранжирует top-N кандидатов для повышения точности.

-   :material-graph: **Граф знаний**

    ---

    Neo4j с 10 типами сущностей, 9 типами связей, многошаговым обходом.

-   :material-brain: **Двухмодельная архитектура**

    ---

    Лёгкая SLM для быстрой маршрутизации + полноразмерная LLM для генерации ответов.

-   :material-api: **OpenAI-совместимый API**

    ---

    Полная замена любого OpenAI-клиента. `/v1/chat/completions`, `/v1/models`, `/v1/health`.

-   :material-puzzle: **Мульти-провайдерная поддержка**

    ---

    Подключаемые адаптеры для vLLM, llama.cpp и любых OpenAI-совместимых инференс-серверов.

-   :material-tools: **Вызов инструментов**

    ---

    MCP-сервер предоставляет RAG-инструменты для IDE (OpenCode, Claude Desktop) и других MCP-клиентов.

-   :material-refresh: **Инкрементальный ETL**

    ---

    WAL-чейкпоинтинг, SHA-256 content-addressable чанки. Переиндексируются только изменённые документы.

-   :material-shield-check: **Автономный режим**

    ---

    Все модели предварительно загружены. Никаких внешних API-вызовов во время работы.

-   :material-chart-line: **Наблюдаемость**

    ---

    Prometheus-метрики, структурированное JSON-логирование, health-чеки с graceful degradation.

</div>

---

## Технологический стек

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

---

## Навигация

| Мне нужно... | Перейти... |
|-------------|---------|
| Понять, почему приняты те или иные решения | [Architecture Decision Records](adr/index.md) |
| Увидеть архитектуру визуально | [C4 Diagrams](diagrams/index.md) |
| Узнать, как работает поиск | [Performance & Quality Guide](guides/performance-quality.md) |
| Добавить новый источник данных | [Extensibility Guide](guides/extensibility-data-sources.md) |
| Настроить контроль доступа | [Access Control & RBAC](guides/access-control-rbac.md) |
| Понять граф знаний | [Knowledge Graph Strategy](guides/knowledge-graph-strategy.md) |
| Интегрировать с OpenCode IDE | [OpenCode Integration](guides/integration-opencode.md) |
| Вызвать API программно | [API Reference](api_reference.md) |
| Развернуть прокси | [Proxy Deployment](deploy_proxy.md) |
| Развернуть ETL-пайплайн | [ETL Deployment](deploy_etl.md) |
| Мониторить в production | [Operations Guide](guides/operations-guide.md) |
| Отладить проблему | [Troubleshooting](guides/troubleshooting.md) |
| Узнать, что запланировано | [Development Roadmap](guides/roadmap.md) |
| Проверить готовность к production | [Best Practices Checklist](guides/best-practices-checklist.md) |

---

## Зрелость RAG

| Уровень | Статус |
|---------|--------|
| Naive RAG (только dense) | Превзойдён |
| Advanced RAG (hybrid + rerank + dedup) | Реализован |
| GraphRAG (извлечение сущностей + Neo4j) | Реализован |
| Agentic (LangGraph оркестратор) | Реализован |
| Self-Correcting (CRAG-style evaluator) | Частично |

Подробнее — [RAG Maturity Assessment](guides/rag-maturity-assessment.md).

---

## Лицензия

MIT © 2026 Alexander Narbaev
