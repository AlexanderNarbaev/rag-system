# Архитектурные диаграммы C4

Архитектура системы задокументирована с использованием [модели C4](https://c4model.com) — иерархического набора диаграмм
для описания архитектуры ПО на четырёх уровнях детализации. Все диаграммы доступны в виде SVG-изображений и
редактируемых исходных файлов [Excalidraw](https://excalidraw.com).

## Обзор диаграмм

| Уровень                  | Диаграмма                | Назначение                                   | Узлов |
|:-------------------------|:-------------------------|:---------------------------------------------|:-----:|
| **1 — Контекст**         | Контекст системы         | RAG-система + пользователи + внешние системы |  11   |
| **2 — Контейнеры**       | Декомпозиция контейнеров | Развёртываемые модули (ETL, Proxy, БД, LLM)  |  10   |
| **3 — Компоненты Proxy** | Внутренности прокси      | Поиск, реранкер, оркестратор, роутеры        |  13   |
| **3 — Компоненты ETL**   | Внутренности ETL         | Экстракторы, чанкер, индексатор, планировщик |  14   |

---

## Уровень 1 — Контекст системы

Показывает RAG-систему как «чёрный ящик», расположенный между пользователями (DevOps-инженеры, разработчики, аналитики,
менеджеры знаний) и внешними системами (Confluence, Jira, GitLab, файловая система, HTTP API). Определяет границы
системы и всех участников.

<a href="c4-level1-context.svg" target="_blank">
  <img src="c4-level1-context.svg" alt="C4 Level 1 — Диаграмма контекста системы" style="max-width:100%; cursor:zoom-in">
</a>

<p><em>Нажмите на диаграмму для просмотра в полном размере</em></p>

---

## Уровень 2 — Контейнеры

Декомпозирует систему на развёртываемые контейнеры: ETL Pipeline, RAG Proxy, Qdrant (векторная БД), Neo4j (графовая БД),
Redis (кэш), LLM Backend (vLLM/llama.cpp) и мониторинг (Prometheus + Grafana). Показывает технологические решения и
протоколы межконтейнерного взаимодействия.

<a href="c4-level2-containers.svg" target="_blank">
  <img src="c4-level2-containers.svg" alt="C4 Level 2 — Диаграмма контейнеров" style="max-width:100%; cursor:zoom-in">
</a>

<p><em>Нажмите на диаграмму для просмотра в полном размере</em></p>

---

## Уровень 3 — Компоненты RAG Proxy

Увеличивает контейнер RAG Proxy, показывая его внутренние компоненты: API-слой (FastAPI), Оркестратор (LangGraph),
Поиск (Qdrant-клиент), Реранкер (кросс-энкодер), Сборщик контекста, LLM-роутер, SLM-роутер, Оптимизатор токенов,
Кэш-слой, Ограничитель частоты, HITL-логгер и Метрики (Prometheus).

<a href="c4-level3-proxy-components.svg" target="_blank">
  <img src="c4-level3-proxy-components.svg" alt="C4 Level 3 — Диаграмма компонентов прокси" style="max-width:100%; cursor:zoom-in">
</a>

<p><em>Нажмите на диаграмму для просмотра в полном размере</em></p>

---

## Уровень 3 — Компоненты ETL Pipeline

Увеличивает контейнер ETL Pipeline, показывая его внутренние компоненты: Экстракторы источников (Confluence, Jira,
GitLab, Docs, Books, Chats), Семантический чанкер, Версионирование хэшами, Извлечение сущностей, Neo4j-загрузчик,
Qdrant-индексатор, Live Vector Lake, WAL-менеджер и Планировщик.

<a href="c4-level3-etl-components.svg" target="_blank">
  <img src="c4-level3-etl-components.svg" alt="C4 Level 3 — Диаграмма компонентов ETL" style="max-width:100%; cursor:zoom-in">
</a>

<p><em>Нажмите на диаграмму для просмотра в полном размере</em></p>

---

## Исходные файлы

Для каждой диаграммы предоставлены редактируемые исходные файлы `.excalidraw`. Откройте их
в [Excalidraw](https://excalidraw.com) для редактирования архитектуры.

| Диаграмма              | Исходник Excalidraw                                                              | Экспорт SVG                                                        |
|:-----------------------|:---------------------------------------------------------------------------------|:-------------------------------------------------------------------|
| Уровень 1 — Контекст   | [`c4-level1-context.excalidraw`](c4-level1-context.excalidraw)                   | [`c4-level1-context.svg`](c4-level1-context.svg)                   |
| Уровень 2 — Контейнеры | [`c4-level2-containers.excalidraw`](c4-level2-containers.excalidraw)             | [`c4-level2-containers.svg`](c4-level2-containers.svg)             |
| Уровень 3 — Proxy      | [`c4-level3-proxy-components.excalidraw`](c4-level3-proxy-components.excalidraw) | [`c4-level3-proxy-components.svg`](c4-level3-proxy-components.svg) |
| Уровень 3 — ETL        | [`c4-level3-etl-components.excalidraw`](c4-level3-etl-components.excalidraw)     | [`c4-level3-etl-components.svg`](c4-level3-etl-components.svg)     |

Чтобы отредактировать диаграмму, скачайте файл `.excalidraw` и перетащите его в редактор Excalidraw
на [excalidraw.com](https://excalidraw.com) или
используйте [Obsidian Excalidraw plugin](https://github.com/zsviczian/obsidian-excalidraw-plugin). После редактирования
экспортируйте в SVG и замените соответствующий `.svg` файл.
