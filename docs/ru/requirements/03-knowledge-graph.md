# Блок C. Граф знаний — Neo4j (FR-19 — FR-25)

---

## FR-19. Извлечение сущностей (spaCy NER + SLM)

**Описание:**
ETL-пайплайн извлекает сущности из документов с помощью spaCy NER и опционально
SLM-аугментации. Поддерживается 10 типов сущностей: Person, Organization, Project,
Technology, API, Service, Team, Location, Document, Event. И 9 типов отношений:
uses, belongs_to, depends_on, documents, owns, created_by, related_to, manages, hosts.

**Критерий приёмки:**

1. После ETL-запуска Neo4j содержит nodes с типами из списка выше
2. Neo4j содержит relationships с типами из списка выше
3. Каждая сущность имеет properties: name, type, source_doc, created_at

**Статус:** ⚠️ Код есть (`etl/graph_builder/entity_extractor.py`), нужен интеграционный тест
**Приоритет:** HIGH (opt-in)
**Связь:** ADR-006, knowledge-graph-strategy

---

## FR-20. Batch loading в Neo4j (UNWIND)

**Описание:**
Сущности загружаются в Neo4j пакетами через UNWIND-запросы. Параметры:
`batch_size=500`, `max_retries=3`, `retry_delay=1s`. Дубликаты обрабатываются
через MERGE (создать если нет, обновить если есть).

**Критерий приёмки:**

1. 1000 сущностей загружаются за ≤ 5 секунд
2. Повторная загрузка тех же сущностей — не создаёт дубликатов
3. При ошибке Neo4j — повтор до 3 раз с exponential backoff

**Статус:** ⚠️ Код есть (`etl/graph_builder/neo4j_loader.py`), нужен интеграционный тест
**Приоритет:** HIGH (opt-in)
**Связь:** knowledge-graph-strategy 1.4

---

## FR-21. Multi-hop graph traversal

**Описание:**
При поиске система может расширять контекст, traversing по графу знаний:

- 1-hop: соседние сущности найденного чанка
- 2-hop: соседи соседей
- N-hop: с ограничением глубины и centrality scoring (PageRank)

Результаты graph traversal добавляются в контекст для LLM.

**Критерий приёмки:**

1. Запрос, связанный с сущностью в графе — возвращает расширенный контекст
2. Результаты содержат сущности из 2+ hops
3. При недоступном Neo4j — graph expansion пропускается (нет 5xx)

**Статус:** ⚠️ Код есть (`proxy/app/core/retrieval.py`), нужен интеграционный тест
**Приоритет:** HIGH (opt-in)
**Связь:** ADR-006

---

## FR-22. Global Search / Multi-Hop Reasoning / Text-to-Cypher

**Описание:**
Три режима работы с графом:

- **Global Search** — поиск по community summary (кластерам сущностей)
- **Multi-Hop Reasoning** — цепочка рассуждений через несколько сущностей
- **Text-to-Cypher** — LLM генерирует Cypher-запрос из текстового вопроса

**Критерий приёмки:**

1. Global Search — возвращает summary по кластеру
2. Multi-Hop — возвращает цепочку связей между сущностями
3. Text-to-Cypher — LLM генерирует валидный Cypher, Neo4j выполняет его

**Статус:** ⚠️ Код есть (`proxy/app/core/retrieval.py`), нужен интеграционный тест
**Приоритет:** HIGH (opt-in)
**Связь:** roadmap Phase 3

---

## FR-23. Community Detection

**Описание:**
Система выявляет кластеры (community) в графе знаний с помощью алгоритмов
обнаружения сообществ (Louvain/Label Propagation). Community summary используется
для Global Search mode.

**Критерий приёмки:**

1. После ETL в графе есть community nodes с summary
2. Global Search по community возвращает агрегированный контекст

**Статус:** ⚠️ Код есть (`etl/graph_builder/community.py`), нужен интеграционный тест
**Приоритет:** HIGH (opt-in)
**Связь:** roadmap Phase 3

---

## FR-24. Graceful degradation при недоступности Neo4j

**Описание:**
Если Neo4j недоступен, система НЕ падает. Graph expansion пропускается, поиск
работает только через Qdrant. В логе предупреждение. HTTP-код ответа — 200 (не 503).

**Критерий приёмки:**

1. Остановленный Neo4j — запрос обрабатывается успешно (без graph expansion)
2. В логе: "Neo4j unavailable — skipping graph expansion"
3. HTTP-код ответа — 200

**Статус:** ⚠️ Код есть (`proxy/app/core/retrieval.py`), нужен chaos-тест
**Приоритет:** CRITICAL
**Связь:** AGENTS.md, ADR-011

---

## FR-25. Graph schema versioning (90-day retention)

**Описание:**
Сущности и отношения в графе имеют `updated_at` timestamp. Задача по расписанию
(каждые 24 часа) удаляет сущности старше 90 дней, которые не обновлялись.

**Критерий приёмки:**

1. Сущность с `updated_at` > 90 дней назад — удаляется
2. Сущность с недавним `updated_at` — сохраняется
3. Задача выполняется по расписанию (cron)

**Статус:** ❌ Нужна реализация
**Приоритет:** MEDIUM
**Связь:** knowledge-graph-strategy 1.4
