# Обогащение графа знаний и развёртывание контекста

## 1. Текущая архитектура графа

### 1.1 Типы сущностей и схема

Граф знаний моделирует 10 типов сущностей, покрывающих корпоративный домен, определённых в `etl/graph_builder/schema.yaml:9-158`:

| Тип сущности | Метка Neo4j | Свойства | Источник |
|---|---|---|---|
| PERSON | `:Entity:Person` | full_name, username, email, role, department | confluence.author, jira.assignee/reporter, gitlab.author |
| PROJECT | `:Entity` | key, name, url, source_system (jira/gitlab/confluence) | Ключ проекта Jira, ID проекта GitLab, ключ пространства Confluence |
| DOCUMENT | `:Entity:Document` | id, title, url, source_type, version, updated_at | Все страницы/задачи/коммиты источников |
| TICKET | `:Entity:Ticket` | key, status, priority, issue_type (Bug/Task/Story/Epic) | Подтип DOCUMENT из Jira |
| COMMIT | `:Entity:Commit` | sha, message, author, date | Подтип DOCUMENT из GitLab |
| CODE_FILE | `:Entity:CodeFile` | path, language, repository | Файлы GitLab |
| ORGANIZATION | `:Entity:Organization` | name, type (team/department/company), parent | Меж-источниковый |
| TECHNOLOGY | `:Entity:Technology` | name, category, version | Все источники (сопоставление ключевых слов) |
| PRODUCT | `:Entity:Product` | name, status (active/deprecated/planning), owner | Все источники |
| CONCEPT | `:Entity:Concept` | name, definition | Все источники |
| LOCATION | `:Entity:Location` | name, country, city | Все источники |

### 1.2 Типы связей

Девять типов связей, определённых в `schema.yaml:161-251`:

- **WORKS_ON** — PERSON → PROJECT/TICKET (роль, дата начала)
- **AUTHORED_BY** — DOCUMENT/COMMIT/TICKET/CODE_FILE → PERSON (дата)
- **MENTIONS** — DOCUMENT → PERSON/TECHNOLOGY/PRODUCT/PROJECT/CONCEPT (контекст, количество)
- **DEPENDS_ON** — PROJECT/TICKET/CODE_FILE → PROJECT/PRODUCT/TECHNOLOGY (тип: build/runtime/optional)
- **RELATES_TO** — любой → любой (сила 0..1, доказательство)
- **CONTAINS** — PROJECT/DOCUMENT → CODE_FILE/DOCUMENT/TICKET
- **PARENT_OF** — TICKET/DOCUMENT → TICKET/DOCUMENT (epic→task, folder→page)
- **REFERENCES** — DOCUMENT → DOCUMENT (url, тип: internal/external)
- **UPDATES** — COMMIT → CODE_FILE/TICKET (lines_added, lines_deleted)
- **BELONGS_TO** — DOCUMENT/TICKET/CODE_FILE → PROJECT/ORGANIZATION

### 1.3 Конвейер извлечения сущностей

Реализован в `etl/graph_builder/entity_extractor.py:51-277`:

1. **spaCy NER** (`extract_entities_spacy`, строка 117) — извлекает PERSON, ORG, GPE, PRODUCT, EVENT из текстовых чанков. Сопоставляет метки spaCy с внутренними типами. Использует `ru_core_news_sm` по умолчанию.
2. **Дополнение SLM** (`extract_relations_slm`, строка 149) — отправляет текст + список сущностей локальной SLM для вывода связей. Промпт структурирован для вывода только JSON. Результаты кэшируются по SHA-256 текста.
3. **Дедупликация** (`extract_batch`, строка 248) — объединяет дублирующиеся сущности по ID и дублирующиеся связи по кортежу (source, target, type).

### 1.4 Загрузка графа и ограничения

Neo4jLoader (`etl/graph_builder/neo4j_loader.py:26-352`):

- **Ограничения**: Уникальные ограничения на `Entity.id`, `Person.id`, `Organization.id`, `Technology.id`, `Product.id`, `Location.id` (строки 101-107)
- **Индексы**: На `Entity.name`, `Entity.source_id`, `Entity.type` и `RELATES_TO.type` (строки 108-113)
- **Пакетная загрузка**: Операции на основе UNWIND с настраиваемыми `batch_size=500` и `max_retries=3` (строки 121-212)
- **Очистка состояния**: `delete_outdated_entities` по source_id (строка 214) и `delete_outdated_relations` по `max_age_days=30` (строка 239)
- **Версионирование**: Временная метка `updated_at` на всех узлах/рёбрах, хранение 90 дней (schema.yaml:298-302)

---

## 2. Многошаговое развёртывание знаний

### 2.1 Конвейер от поиска к графу

Основная идея: векторный поиск возвращает чанки документов → извлечение сущностей из чанков → обход графа → возврат обогащённого контекста.

```
Запрос → hybrid_search(Qdrant) → top-k чанков → NER по тексту чанка
  → поиск сущностей в Neo4j → обход 1/2/N-hop путей → оценка путей → возврат контекста графа
```

### 2.2 Стратегии обхода

**1-hop: Прямые связи** — Самый быстрый, используется при конкретном интенте запроса:
```cypher
MATCH (e:Entity {name: $entity})-[:WORKS_ON|AUTHORED_BY|MENTIONS|BELONGS_TO]->(related)
RETURN related.name, labels(related), type(r)
```
Покрывает: человек→команда, тикет→проект, документ→автор, коммит→файл.

**2-hop: Косвенные связи** — Раскрывает скрытые связи:
```cypher
MATCH (e:Entity {name: $entity})-[r1]->(mid)-[r2]->(target)
WHERE target <> e
RETURN e.name, type(r1), mid.name, type(r2), target.name
```
Примеры: человек→команда→проект, задача Jira→references→страница Confluence, MR→updates→файл→belongs_to→репо.

**N-hop с оценкой центральности** — Для исследовательских вопросов:
```cypher
CALL gds.pageRank.stream('entity-graph') YIELD nodeId, score
MATCH (n) WHERE id(n) = nodeId AND score > 0.01
WITH n, score ORDER BY score DESC LIMIT 20
MATCH path = shortestPath((start)-[*1..3]-(n))
RETURN path, score
```
Использовать библиотеку Neo4j GDS PageRank и Betweenness centrality. Фильтровать пути по `score > 0.01` для подавления шума.

### 2.3 Оценка и ранжирование путей

```
path_score = Σ(node_centrality × 0.3) + Σ(relation_strength × 0.5) + log(1 + mentions_count) × 0.2
```

- **node_centrality**: Оценка PageRank (0..1)
- **relation_strength**: из свойства `RELATES_TO.strength` (0..1)
- **mentions_count**: из свойства `MENTIONS.count`

Порог фильтрации: `path_score > 0.15`. Ранжировать по убыванию оценки, ограничить top-10 путями.

---

## 3. Поиск с расширением графа

### 3.1 Текущая реализация

`graph_expand_query()` в `proxy/app/retrieval.py:180-216`: Базовая реализация с простым сопоставлением ключевых слов:
- Разбивает запрос на слова > 3 символов
- Выполняет CONTAINS match по `Entity.name`
- Возвращает 1-hop соседей как текстовые строки

**Ограничения**: Нет распознавания сущностей, нет multi-hop, нет оценки, нет управления бюджетом токенов.

### 3.2 Предлагаемые улучшения

**Извлечение подграфа вокруг найденных сущностей**: После векторного поиска извлечь имена сущностей из top-10 найденных чанков с помощью spaCy NER, затем получить индуцированный подграф из Neo4j:

```cypher
MATCH (e:Entity) WHERE e.name IN $entity_names
MATCH (e)-[r*1..2]-(related:Entity)
RETURN e, r, related
```

**Обогащение контекста с учётом связей**: Вместо плоских текстовых списков форматировать результаты графа как структурированную разметку:

```
[GRAPH_CONTEXT]
Entity: PROJ-123 (TICKET) — status: In Progress, priority: High
  AUTHORED_BY → Иван Иванов (role: backend developer)
  PARENT_OF → PROJ-456 (sub-task)
  DEPENDS_ON → PostgreSQL 15 (runtime dependency)
  MENTIONS → CI/CD Pipeline (count: 3)
[/GRAPH_CONTEXT]
```

**Внимание графа для оценки релевантности**: Оценивать сущности графа с помощью взвешенной комбинации векторного сходства (из Qdrant), центральности графа (PageRank) и релевантности типа связи домену запроса. Взвешенный фьюжн:
```
final_score = 0.4 × vector_score + 0.3 × centrality + 0.3 × relation_relevance
```

### 3.3 Интеграция с оркестратором

В конвейере LangGraph (`orchestrator.py:212-251`) расширение графа выполняется между `rerank` и `build_context`:

```
rewrite → retrieve → check_sufficiency → rerank → graph_expand → build_context → generate
```

Когда `check_sufficiency` обнаруживает низкую уверенность (`avg_score < 0.6`), конвейер возвращается к `rewrite`. Если уверенность маргинальна (0.6–0.75), расширение графа запускается как дополнение без полного цикла переписывания.

---

## 4. Меж-источниковое разрешение сущностей

### 4.1 Правила разрешения идентичности

**Сопоставление авторов** (Jira ↔ GitLab ↔ Confluence):
- Канонический ключ: `email` (наивысшая уверенность), `username` (средняя), `full_name` (низкая, требует нечёткого сопоставления)
- Порог нечёткого сопоставления: расстояние Левенштейна ≤ 2 для имён
- Разрешение: `MERGE` по email, затем опционально объединить совпадения только по имени с `similarity_score > 0.9`

**Связывание задачи и документа** (PROJ-123 ↔ связанная страница Confluence):
- На основе паттернов: Извлечь ключи задач Jira (`[A-Z]{2,}-\d+`) из содержимого и комментариев страниц Confluence
- Явные ссылки: Парсить макрос Confluence `{jira:PROJ-123}`
- Разрешение обратных ссылок: Поле Jira "mentioned in" → URL страницы Confluence

**Цепочка: merge request → решённая задача → обновлённая документация**:
```
COMMIT (sha) → UPDATES → CODE_FILE
COMMIT (sha) → MENTIONS (PROJ-123) → TICKET → REFERENCES → DOCUMENT (Confluence)
```

### 4.2 Каноническое хранилище сущностей

Предлагается свойство `canonical_id` на всех сущностях. Конвейер разрешения:
1. Группировать сущности по email/username (строгое совпадение)
2. Внутри каждой группы выбрать сущность с наибольшим количеством свойств как каноническую
3. Установить `canonical_id` на дубликатах, указывающий на каноническую сущность
4. Запускать еженедельно для объединения новообнаруженных идентичностей

---

## 5. Темпоральная осведомлённость

### 5.1 Отслеживание эволюции версий

Каждый узел и связь несут `updated_at` (datetime) и `source_version` (string). При переиндексации ETL:
- Новая версия: вставить с новым `source_version`, сохранить старый узел с `deprecated: true`
- Цепочка версий: связь `PREVIOUS_VERSION` между версиями документа

### 5.2 Запросы "по состоянию на дату X"

Фильтрация обхода графа по темпоральному ограничению:
```cypher
MATCH (e:Entity)-[r:RELATES_TO]->(related)
WHERE r.updated_at <= datetime($target_date)
  AND (r.deprecated IS NULL OR r.deprecated > datetime($target_date))
RETURN e, r, related
```

### 5.3 Очистка устаревших связей

`Neo4jLoader.delete_outdated_relations(max_age_days=30)` удаляет связи, не тронутые более 30 дней. Запускать как ежедневный cron вместе с инкрементальным ETL.

---

## 6. Самообогащающаяся база знаний

### 6.1 Автоматическое обнаружение отсутствующих связей

- **Майнинг совместной встречаемости**: Сущности, часто появляющиеся в одних и тех же чанках, но без связи → предложить `RELATES_TO` со слабой `strength=0.3` и `evidence="co-occurrence"`
- **Вывод на основе паттернов**: Текстовый паттерн "X зависит от Y" → создать связь `DEPENDS_ON`
- **Транзитивное замыкание**: Если существует A→B→C и отсутствует A→C, а оценка пути > 0.5, предложить A→C

### 6.2 Периодическая аналитика графа

Запускать еженедельно (запланировано в планировщике ETL):
- **Обнаружение сообществ** (алгоритм Louvain через GDS): Идентифицировать кластеры документов/задач по домену проекта
- **Пересчёт центральности**: Обновить оценки PageRank, хранящиеся как свойство `pagerank` на всех узлах Entity
- **Обнаружение сирот**: Сущности со степенью 0 — пометить для проверки HITL или авто-очистки через 90 дней

### 6.3 Цикл обратной связи HITL

Из `hitl_dashboard/`:
- Эксперт отмечает предложенную связь как "подтверждённую" → установить `strength=1.0`, `evidence="hitl_verified"`
- Эксперт отмечает как "некорректную" → установить `deprecated=true` с `deprecated_reason`
- Обратная связь интегрируется через хуки `proxy/app/hitl.py`, записывается обратно в Neo4j в следующем цикле ETL

---

## 7. Сборка контекста с данными графа

### 7.1 Формат для внедрения в промпт LLM

Контекст графа добавляется к векторному контексту с чёткими разделителями:

```
=== КОНТЕКСТ ДОКУМЕНТА ===
[chunk 1] ... (score: 0.89)
[chunk 2] ... (score: 0.82)

=== ГРАФ ЗНАНИЙ ===
Entity: Иван Иванов (PERSON)
  WORKS_ON → PROJ-123 (с 2025-01)
  AUTHORED_BY → Confluence: Architecture Overview (2025-03-15)

Entity: PROJ-123 (TICKET) — status: In Progress
  DEPENDS_ON → PostgreSQL 15
  REFERENCES → GitLab: backend/schema.sql
```

### 7.2 Распределение бюджета токенов

С окном контекста настроенной LLM:

| Компонент | Токенов | Процент |
|---|---|---|
| Системный промпт | ~500 | <1% |
| Запрос пользователя | ~200 | <1% |
| Векторно-найденные чанки (top-10) | ~90 000 | 69% |
| Контекст графа | ~30 000 | 23% |
| Резерв генерации (вывод) | ~9 300 | 7% |

**Правило**: Контекст графа ограничен `min(30 000 токенов, 25% оставшегося бюджета)`. Когда векторный контекст уже потребляет >100K токенов, контекст графа обрезается до top-5 сущностей только с 1-hop связями.

### 7.3 Формат сводки сущность-связь

Для запросов с множеством попаданий в граф сжать до сводной таблицы:

```
| Сущность | Тип | Связи |
|---|---|---|
| PROJ-123 | TICKET | depends on: PostgreSQL 15, Redis; worked on by: Иван Иванов |
| Architecture Overview | DOCUMENT | references: PROJ-123; authored by: Иван Иванов |
```

Это сжимает ~2 000 токенов текста графа в ~200 токенов, сохраняя семантику связей.
