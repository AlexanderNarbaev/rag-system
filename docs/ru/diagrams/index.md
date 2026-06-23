# Архитектурные диаграммы C4

Архитектура системы задокументирована на четырёх уровнях с использованием модели C4. Все диаграммы доступны в виде SVG-изображений и редактируемых исходных файлов `.excalidraw`.

## Уровень 1 — Контекст системы

![C4 Level 1 — System Context](c4-level1-context.svg)

Показывает RAG-систему в контексте пользователей и внешних систем (11 узлов).

## Уровень 2 — Контейнеры

![C4 Level 2 — Containers](c4-level2-containers.svg)

Декомпозиция системы на развёртываемые контейнеры: ETL Pipeline, RAG Proxy, Qdrant, Neo4j, Redis, LLM-бэкенд (10 узлов).

## Уровень 3 — Компоненты RAG Proxy

![C4 Level 3 — Proxy Components](c4-level3-proxy-components.svg)

Внутренние компоненты контейнера RAG Proxy: retrieval, reranker, context builder, LLM/SLM routers, orchestrator, cache, HITL logging (13 узлов).

## Уровень 3 — Компоненты ETL Pipeline

![C4 Level 3 — ETL Components](c4-level3-etl-components.svg)

Внутренние компоненты ETL Pipeline: extractors, chunker, graph builder, indexer, WAL manager, scheduler (14 узлов).

## Исходные файлы

Для каждой диаграммы доступны редактируемые файлы `.excalidraw`:

- [`c4-level1-context.excalidraw`](c4-level1-context.excalidraw)
- [`c4-level2-containers.excalidraw`](c4-level2-containers.excalidraw)
- [`c4-level3-proxy-components.excalidraw`](c4-level3-proxy-components.excalidraw)
- [`c4-level3-etl-components.excalidraw`](c4-level3-etl-components.excalidraw)

Откройте их в [Excalidraw](https://excalidraw.com) для редактирования.
